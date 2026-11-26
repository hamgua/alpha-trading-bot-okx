"""
精简版交易机器人主类
核心逻辑：
1. 15分钟周期执行（随机偏移±3分钟）
2. 调用AI获取信号（buy/hold/sell）
3. 信号处理
4. 止损订单管理
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..config.models import Config
from ..utils.observability import record_live_guard_block
from ..utils.technical import calculate_trend
from .decision_journal import DecisionJournal
from .drawdown_guard import DrawdownGuard, DrawdownStatus
from .position_manager import PositionManager
from .signal_processor import SignalProcessor
from .stop_loss_manager import StopLossManager
from .trading_scheduler import TradingScheduler

logger = logging.getLogger(__name__)


@dataclass
class ExecutionResult:
    """信号执行结果（P1：供决策日志记录）"""

    # open_long / update_stop / close / none / blocked_drawdown / blocked_other / error
    action: str
    detail: str = ""


class TradingBot:
    """精简版交易机器人"""

    def __init__(self, config: Optional[Config] = None):
        self.config = config or Config.from_env()
        self._running = False
        self._initialized = False

        # 使用独立的组件
        self.scheduler = TradingScheduler(config)
        self.position_manager = PositionManager(config)
        self._stop_loss_manager: Optional[StopLossManager] = None

        # P1 回撤停机总闸（30% 回撤禁止新开仓；高水位持久化，手动恢复）
        self._drawdown_guard = DrawdownGuard(
            threshold=self.config.trading.risk_drawdown_halt,
            resume=self.config.trading.risk_resume,
        )
        self._drawdown_status: Optional[DrawdownStatus] = None

        # P1 决策日志（各层信号 + T+4h/24h 结果回填）
        self._decision_journal = (
            DecisionJournal(enabled=self.config.trading.decision_journal_enabled)
            if self.config.trading.decision_journal_enabled
            else None
        )

        # 2026-11 开仓频度控制 (key=YYYY-MM-DD):
        # 每日新开仓计数 + 超卖抄底独立通道每日触发计数。
        # 2026-11-26 P0-3: 计数持久化跨重启 (原纯内存重启清零,
        # 部署重启击穿 "每方向每日 ≤1 次" 门禁: 11-25 一天 2 笔趋势空单)。
        self._daily_open_counts: Dict[str, int] = {}
        self._oversold_buy_counts: Dict[str, int] = {}
        # 2026-11-24 高潮做空独立通道: 每日触发计数 + 机会审计限频计数
        self._climax_short_counts: Dict[str, int] = {}
        self._climax_audit_counts: Dict[str, int] = {}
        # 2026-11-25 趋势跟踪独立通道: 每日触发计数 (key=YYYY-MM-DD)
        self._trend_follow_counts: Dict[str, int] = {}
        # 2026-11-26 P0-3: 从持久化恢复每日计数 (只保留今天/昨天)
        (
            _r_open,
            _r_trend,
            _r_oversold,
            _r_climax,
        ) = self.position_manager.load_daily_counts()
        self._daily_open_counts = _r_open
        self._trend_follow_counts = _r_trend
        self._oversold_buy_counts = _r_oversold
        self._climax_short_counts = _r_climax
        # 2026-11-26 P2-10: 信号连续确认 (同向信号连续周期数, 持久化)
        self._last_signal: str
        self._signal_streak: int
        self._last_signal, self._signal_streak = (
            self.position_manager.load_signal_streak()
        )
        # 2026-11-26 P1-4: 重启后首个周期只同步不交易 (STARTUP_SYNC_ONLY)
        self._first_cycle_after_startup = True
        # 2026-11-24 机会审计: AI 连续零方向信号计数 (每周期 +1, 出方向信号清零)
        self._no_direction_streak = 0

    @property
    def exchange(self):
        """获取交易所客户端（延迟初始化）"""
        return getattr(self, "_exchange", None)

    @property
    def ai_client(self):
        """获取AI客户端（延迟初始化）"""
        return getattr(self, "_ai_client", None)

    async def initialize(self) -> bool:
        """初始化交易所和AI客户端"""
        try:
            logger.info("初始化交易机器人...")

            from ..exchange.client import ExchangeClient

            self._exchange = ExchangeClient(
                api_key=self.config.exchange.api_key,
                secret=self.config.exchange.secret,
                password=self.config.exchange.password,
                symbol=self.config.exchange.symbol,
                allow_short_selling=self.config.trading.allow_short_selling,
                test_mode=self.config.trading.test_mode,
                max_position_usage=self.config.exchange.max_position_usage,
                order_confirm_timeout_seconds=(
                    self.config.trading.order_confirm_timeout_seconds
                ),
                order_confirm_poll_interval_seconds=(
                    self.config.trading.order_confirm_poll_interval_seconds
                ),
            )
            await self._exchange.initialize()
            await self._exchange.set_leverage(self.config.exchange.leverage)

            self._stop_loss_manager = StopLossManager(
                self._exchange, self.config, self.position_manager
            )

            from ..ai.client import AIClient

            self._ai_client = AIClient(
                config=self.config.ai, api_keys=self.config.ai.api_keys
            )

            # 检查止损单恢复
            await self._check_stop_order_recovery()

            self._initialized = True
            logger.info("初始化完成")
            return True

        except Exception as e:
            logger.error(f"初始化失败: {e}")
            return False

    async def _check_stop_order_recovery(self) -> None:
        """检查并恢复止损单"""
        # 从交易所获取最新持仓状态
        try:
            position_data = await self._exchange.get_position()
        except Exception as e:
            logger.error(f"[止损恢复] 获取持仓失败: {e}")
            return
        if position_data:
            self.position_manager.update_from_exchange(position_data)

        # 检查是否需要恢复止损单
        if not self.position_manager.has_position():
            return

        # 查找交易所现有的止损单
        exchange_stop_order_id = await self._get_existing_stop_order_id()

        if exchange_stop_order_id:
            logger.info(f"[止损恢复] 发现交易所止损单: {exchange_stop_order_id}")
            self.position_manager.set_stop_order(exchange_stop_order_id)
        elif self.position_manager.needs_stop_order_recovery():
            logger.warning("[止损恢复] 有持仓但无止损单，需要重建止损单")
            await self._recreate_stop_order()

        # P1-3: 止盈单恢复（与止损恢复对称）：有持仓但本地无止盈单 ID →
        # 按入场价重建。持久化已有止盈单 ID 时视为仍在生效（止盈单若已
        # 触发，仓位已平，不会走到这里）。
        if not self.position_manager.take_profit_order_id:
            await self._recreate_take_profit_order()

    async def _recreate_stop_order(self) -> None:
        """重建止损单"""
        position = self.position_manager.position
        if not position:
            return

        # 获取当前价格
        market_data = await self._exchange.get_market_data()
        current_price = market_data.get("price", 0)

        if current_price <= 0:
            logger.error("[止损恢复] 无法获取当前价格")
            return

        # 计算止损价 (2026-11-24: 多空统一, 空仓止损走 ATR 逻辑)
        stop_price = self.position_manager.calculate_stop_price_unified(current_price)
        if stop_price <= 0:
            logger.error("[止损恢复] 无法计算止损价 (仓位方向无效?)")
            return

        logger.info(
            f"[止损恢复] 创建止损单: 止损价={stop_price}, 数量={position.amount}, "
            f"方向={position.side}"
        )

        try:
            # 2026-11-24: 方向感知 (多仓止损=sell, 空仓止损=buy)
            stop_side = "sell" if position.side == "long" else "buy"
            stop_order_id = await self._exchange.create_stop_loss(
                symbol=self.config.exchange.symbol,
                side=stop_side,
                amount=position.amount,
                stop_price=stop_price,
            )
            # 2026-11-25: 重建止损时幂等补设 initial_stop (旧状态无该字段 →
            # 用重建价锁定 R 基准, 使追踪止损跨重启可用)
            self.position_manager.set_initial_stop(stop_price)
            self.position_manager.set_stop_order(stop_order_id)
            logger.info(f"[止损恢复] 止损单重建成功: {stop_order_id}")
        except Exception as e:
            logger.error(f"[止损恢复] 止损单重建失败: {e}")

    async def _recreate_take_profit_order(self) -> None:
        """按入场价重建止盈单（P1-3，与止损单重建对称）"""
        position = self.position_manager.position
        if not position:
            return

        entry_price = self.position_manager.entry_price
        # 2026-11-24: 方向感知 (空仓止盈=buy, 多仓止盈=sell)
        side = "short" if position.side == "short" else "long"
        tp_price = self._calculate_take_profit_price(
            entry_price, position.amount, side=side
        )
        if tp_price <= 0:
            return

        logger.warning(
            f"[止盈恢复] 有持仓但无止盈单，重建: 止盈价={tp_price}, "
            f"数量={position.amount}, 方向={side}"
        )
        try:
            tp_side = "buy" if side == "short" else "sell"
            tp_order_id = await self._exchange.create_take_profit(
                symbol=self.config.exchange.symbol,
                side=tp_side,
                amount=position.amount,
                take_profit_price=tp_price,
            )
            if tp_order_id:
                self.position_manager.set_take_profit_order(tp_order_id, tp_price)
                logger.info(f"[止盈恢复] 止盈单重建成功: {tp_order_id}")
            else:
                logger.error("[止盈恢复] 止盈单重建失败: 仓位由止损单兜底")
        except Exception as e:
            logger.error(f"[止盈恢复] 止盈单重建异常: {e}")

    async def run(self) -> None:
        """主循环"""
        if not self._initialized:
            if not await self.initialize():
                raise RuntimeError("初始化失败")

        self._running = True
        logger.info("交易机器人启动")

        try:
            first_run = True
            while self._running:
                await self._trading_cycle(first_run=first_run)
                first_run = False

        except asyncio.CancelledError:
            logger.info("收到停止信号")
        finally:
            await self.cleanup()

    # 交易周期全局超时（秒）- 防止 AI 调用或交易所调用挂起导致整个 bot 阻塞
    TRADING_CYCLE_TIMEOUT = 300  # 5分钟

    async def _trading_cycle(self, first_run: bool = False) -> None:
        """单次交易周期（带全局超时保护）"""
        # 1. 等待周期
        await self.scheduler.wait_for_next_cycle(first_run)

        try:
            await asyncio.wait_for(
                self._execute_trading_cycle(),
                timeout=self.TRADING_CYCLE_TIMEOUT,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[交易周期] 交易周期超时 ({self.TRADING_CYCLE_TIMEOUT}秒)，强制结束本周期"
            )
        except Exception as e:
            logger.error(f"[交易周期] 交易周期异常: {e}")
            logger.exception("详细错误:")

    async def _execute_trading_cycle(self) -> None:
        """执行交易周期的核心逻辑"""

        logger.info("=" * 60)
        logger.info("开始新的交易周期")
        logger.info("=" * 60)

        # 2. 获取市场数据
        market_data = await self._exchange.get_market_data()
        current_price = market_data.get("price", 0)
        change_percent = market_data.get("change_percent", 0)
        recent_drop = market_data.get("recent_drop_percent", 0)
        technical = market_data.get("technical", {})
        rsi = technical.get("rsi") if technical else None
        atr = technical.get("atr") if technical else None

        # 格式化显示
        change_str = f"{change_percent:.2f}%" if change_percent else "N/A"
        recent_drop_str = f"{recent_drop * 100:.2f}%" if recent_drop else "N/A"
        rsi_str = f"{rsi:.2f}" if rsi is not None else "N/A"
        atr_str = f"{atr:.2f}" if atr is not None else "N/A"

        logger.info(f"[市场数据] 当前价格: {current_price}")
        logger.info(f"[市场数据] 24h涨跌幅: {change_str}")
        logger.info(f"[市场数据] 1h涨跌幅: {recent_drop_str}")
        logger.info(f"[市场数据] RSI: {rsi_str}")
        logger.info(f"[市场数据] ATR: {atr_str}")

        # P1: 回填 4h/24h 前向收益（用本周期最新价格）
        if self._decision_journal is not None:
            from datetime import datetime as _dt

            try:
                self._decision_journal.backfill(_dt.now(), current_price)
            except Exception as e:
                logger.warning("[决策日志] 回填失败（周期不受影响）: %s", e)

        # 3. 检查当前持仓状态
        try:
            position_data = await self._exchange.get_position()
            api_query_failed = False
        except Exception as e:
            logger.error(f"[持仓状态] 获取持仓失败: {e}")
            position_data = None
            api_query_failed = True
        if position_data:
            self.position_manager.update_from_exchange(position_data)
        elif api_query_failed:
            logger.warning(
                "[持仓对账] API查询持仓失败，保留本地持仓状态不清理，"
                "等待下一周期重试"
            )
        else:
            if self.position_manager.has_position():
                # 2026-11 P2-12 保护单成交归因: 仓位在交易所侧被止损/止盈单
                # 平掉后, 原先要等下一周期对账才发现 (15 分钟盲区) 且不知
                # 是哪张单触发的。此处按 当前价 vs 止损/止盈价 做 best-effort
                # 归因, 明确盈亏路径 (仅审计日志, 不改状态)。
                await self._log_protection_order_fill(current_price)
                logger.warning(
                    "[持仓对账] API返回无持仓，但本地PositionManager仍有持仓状态，"
                    f"清理本地缓存。本地持仓: "
                    f"方向={self.position_manager.position.side if self.position_manager.position else 'N/A'}, "
                    f"入场价={self.position_manager.entry_price}"
                )
                # P0-2: 仓位在交易所侧被平掉（止损/止盈单触发），
                # 同样盖平仓时间戳，冷却门禁对两类平仓路径一视同仁
                self.position_manager.mark_last_close()
            self.position_manager.update_from_exchange({})
        has_position = self.position_manager.has_position()

        if has_position:
            pm = self.position_manager
            position_info = pm.position
            if position_info is None:
                logger.error(
                    "[持仓状态] 数据不一致: has_position=True 但 position 为 None"
                )
                return
            logger.info(
                "[持仓状态] 持仓中 - "
                f"方向:{position_info.side}, 数量:{position_info.amount}张, "
                f"入场价:{position_info.entry_price}"
            )
            position_context = pm.get_position_context(current_price)
            unrealized_pnl = position_info.unrealized_pnl
            pnl_percent = position_context.get("pnl_percent", 0)
            duration_hours = position_context.get("duration_hours", 0)
            health = position_context.get("health", "unknown")
            logger.info(
                f"[持仓状态] 未实现盈亏: {unrealized_pnl:.2f} USDT ({pnl_percent:.2f}%), "
                f"持仓时长: {duration_hours:.1f}小时, 健康度: {health}"
            )
            market_data["position"] = position_context
        else:
            logger.info("[持仓状态] 无持仓")
            market_data["position"] = {}

        # 3.5 回撤总闸检查（P1）
        await self._check_drawdown()

        # 3.6 2026-11-26 P1-4: 重启后首个周期只同步不交易。
        # 11-25 22:04/22:06 两次部署重启的 "首次立即周期" 直接造成开仓
        # (22:05) 与 2 分钟后平仓 (22:07)。持仓/保护单对账已在步骤 3 完成,
        # 此处跳过 AI 信号与全部开/平仓路径 (STARTUP_SYNC_ONLY=false 可回滚)。
        if self._first_cycle_after_startup:
            self._first_cycle_after_startup = False
            if self.config.trading.startup_sync_only:
                logger.warning(
                    "[启动同步] 重启后首个周期仅同步 (持仓/保护单对账已完成), "
                    "不获取 AI 信号/不开平仓 (STARTUP_SYNC_ONLY=true)"
                )
                return

        logger.info(f"[交易决策] 当前价格: {current_price}")

        # 4. 获取AI信号
        signal: Optional[str] = None
        try:
            logger.info("[AI信号] 正在获取交易信号...")
            signal = await self._ai_client.get_signal(market_data)
            signal = SignalProcessor.process(signal)
            logger.info(f"[AI信号] 原始信号: {signal}")
            # 2026-11-26 P2-10: 更新信号连续确认计数 (同向 +1, 换向重置)
            self._update_signal_streak(signal)

            # 执行层置信度门禁（P0-1）：取最终置信度（0-1），解析失败→None（门禁不生效）
            final_conf_raw = market_data.get("final_confidence")
            try:
                final_confidence: Optional[float] = (
                    float(final_conf_raw) if final_conf_raw is not None else None
                )
            except (TypeError, ValueError):
                final_confidence = None

            # 5. 处理信号
            # R/R 感知动态门禁所需的"方向一致 R/R": 只有市场结构方向与该侧一致时
            # 才参与放宽 (多结构+HTF冲突已被降级为 none → 不放宽)。
            # 2026-11-24 (P0-B): 做多侧改用 ATR 口径 R/R (long_risk_reward_ratio),
            # 不再用结构 R/R——底部区结构 R/R 是几何伪影 (价贴支撑时分母极小,
            # 回放 13:30 R/R=81.38 / 13:43 R/R=4.03 放行了错误抄底)。
            mkt_direction = market_data.get("market_structure_direction", "")
            relief_long_rr = (
                float(market_data.get("long_risk_reward_ratio", 0.0) or 0.0)
                if mkt_direction == "long"
                else 0.0
            )
            relief_short_rr = (
                float(market_data.get("short_risk_reward_ratio", 0.0) or 0.0)
                if mkt_direction == "short"
                else 0.0
            )
            execution_result = await self._execute_signal(
                signal,
                current_price,
                has_position,
                final_confidence,
                structure_rr=relief_long_rr,
                short_rr=relief_short_rr,
                change_percent=change_percent,
                atr_percent=technical.get("atr_percent", 0.0) if technical else 0.0,
                buy_mode=str(market_data.get("adaptive_buy_mode", "") or ""),
                trend_direction=str((technical or {}).get("trend_direction", "") or ""),
                signal_streak=self._signal_streak,
            )

            # 5.5 超卖抄底独立通道（2026-11 底部捕获 / P1-5）:
            # AI 路径未开仓 (HOLD / 被门禁拦) 且技术极端超卖条件满足时,
            # 独立规则抄底 (半仓, 每日 1 次)。回放: 11-21 14:14 RSI=16
            # 底部原路径 66.5%<0.75 被拦, 错过 55.6k→60.7k 反弹。
            if (
                not has_position
                and signal != "BUY"
                and execution_result.action
                in (
                    "none",
                    "blocked_low_confidence",
                    # 2026-11-26 P2-10: AI 等待信号确认时技术通道不受影响
                    "blocked_signal_confirm",
                )
            ):
                oversold_result = await self._maybe_oversold_bottom_buy(
                    market_data, current_price
                )
                if oversold_result is not None:
                    logger.info(
                        "[超卖抄底] 独立通道开仓成功 (AI信号=%s 路径未开仓)" % signal
                    )
                    execution_result = oversold_result

            # 5.6 高潮做空独立通道（2026-11-24 顶部捕获 / P0-2）:
            # AI 路径未开空 (HOLD / SHORT 被门禁拦) 且价格处于 24h 高点区 +
            # 1h RSI 超买 + 做空 R/R ≥ 阈值时, 独立规则做空 (半仓, 每日 N 次)。
            # 回放: 11-23 22:00-23:57 做空 R/R 3.0-7.1 + RSI(1h) 67-78,
            # 随后 11-24 62.8k→59.5k 主跌段。
            if (
                not self.position_manager.has_position()
                and signal != "SHORT"
                and execution_result.action
                in (
                    "none",
                    "blocked_low_confidence",
                    "blocked_daily_limit",
                    "blocked_cooldown",
                    "blocked_drawdown",
                    "blocked_short_disabled",
                    # 2026-11-26 P2-10: AI 等待信号确认时技术通道不受影响
                    "blocked_signal_confirm",
                )
            ):
                climax_result = await self._maybe_climax_short(
                    market_data, current_price
                )
                if climax_result is not None:
                    logger.info(
                        "[高潮做空] 独立通道开仓成功 (AI信号=%s 路径未开仓)" % signal
                    )
                    execution_result = climax_result

            # 5.8 趋势跟踪独立通道 (2026-11-25 / 模块 0, 顺势入场):
            # AI 路径未开仓 (HOLD / 被门禁拦) 且趋势方向条件满足
            # (SMA10/20 1h 方向 + 24h 涨跌幅 ±2% + RSI 排除) → 趋势方向半仓,
            # 让利润奔跑由追踪止损承接 (见 StopLossManager trailing)。
            if (
                not self.position_manager.has_position()
                and signal not in ("BUY", "SHORT")
                and execution_result.action
                in (
                    "none",
                    "blocked_low_confidence",
                    "blocked_daily_limit",
                    "blocked_cooldown",
                    "blocked_drawdown",
                    "blocked_short_disabled",
                    # 2026-11-26 P2-10: AI 等待信号确认时技术通道不受影响
                    "blocked_signal_confirm",
                )
            ):
                trend_result = await self._maybe_trend_follow(
                    market_data, current_price
                )
                if trend_result is not None:
                    logger.info(
                        "[趋势跟踪] 独立通道开仓成功 (AI信号=%s 路径未开仓)" % signal
                    )
                    execution_result = trend_result

            # 5.7 P1 机会审计: AI 连续零方向信号 (单AI恒 HOLD 时量化漏单)
            if signal is None or str(signal).upper() == "HOLD":
                self._no_direction_streak += 1
                if self._no_direction_streak in (24, 48, 96):
                    logger.warning(
                        "[机会审计] AI 已连续 %d 个周期 (~%.1f小时) 无方向信号 "
                        "(buy/sell/short), 全部 HOLD; 当前仅独立通道 "
                        "(超卖抄底/高潮做空/趋势跟踪) 可开仓。请检查 prompt 置信度校准 "
                        "或 MIN_CONFIDENCE_OPEN/阈值配置",
                        self._no_direction_streak,
                        self._no_direction_streak
                        * self.config.trading.cycle_minutes
                        / 60.0,
                    )
            else:
                self._no_direction_streak = 0

            # P1: 记录本周期决策日志
            await self._record_decision(market_data, signal, execution_result)
        except Exception as e:
            logger.error(f"[交易周期] 获取/处理AI信号时出错: {e}")
            logger.exception("详细错误:")
            await self._record_decision(
                market_data, signal, ExecutionResult("error", f"{e}")
            )
            return  # 直接返回，跳过后续处理

        logger.info("交易周期完成")
        logger.info("=" * 60)

    async def _check_drawdown(self) -> None:
        """周期内回撤总闸检查（P1）：只拦新开仓，不影响已持仓管理。

        余额获取失败时跳过本轮（不中断周期、不误停机）。
        """
        try:
            equity = await self._exchange.get_balance()
            self._drawdown_status = self._drawdown_guard.check(equity)
        except Exception as e:
            logger.warning(
                "[风控总闸] 权益获取失败，跳过本轮检查（fail-closed：保留既有停机状态）: %s",
                e,
            )
            self._drawdown_status = self._drawdown_guard.snapshot()

    async def _record_decision(
        self,
        market_data: Dict[str, Any],
        signal: Optional[str],
        execution: Optional[ExecutionResult],
    ) -> None:
        """记录本周期决策日志（P1）：任何异常都不得中断周期。"""
        if self._decision_journal is None:
            return
        try:
            trace = (
                self._ai_client.get_last_signal_trace()
                if self._ai_client is not None
                else {}
            )
            integrator = trace.get("integrator") or {}
            final = integrator.get("final_signal") or signal
            entry = {
                "price": market_data.get("price"),
                "market": {
                    "price": market_data.get("price"),
                    "rsi": (market_data.get("technical") or {}).get("rsi")
                    or market_data.get("rsi"),
                    "atr": (market_data.get("technical") or {}).get("atr")
                    or market_data.get("atr"),
                    "change_24h": market_data.get("change_percent"),
                },
                "jev": trace.get("jev"),
                "llm": trace.get("llm"),
                "integrator": integrator,
                "cache_hit": bool(trace.get("cache_hit")),
                "final": str(final).upper(),
                "execution": {
                    "action": execution.action if execution else "error",
                    "detail": execution.detail if execution else "",
                },
                "drawdown_halted": bool(
                    self._drawdown_status is not None and self._drawdown_status.halted
                ),
            }
            self._decision_journal.record_cycle(entry)
        except Exception as e:
            logger.warning("[决策日志] 记录失败（周期不受影响）: %s", e)

    def _effective_open_confidence_gate(self, aligned_rr: float) -> float:
        """开仓置信度门禁（R/R 感知动态放宽, 2026-11-24 回放 / P0-3）。

        方向一致的结构 R/R ≥ gate_relief_rr_min 时, 门禁放宽 gate_relief_amount
        (下限 gate_relief_floor)。证据 (2026-11-23/24 回放): 217 周期最终
        置信度 46-72% (均值 58.5%), 固定 0.65 门禁仅 15/217 通过且全为 HOLD;
        高 R/R setups 应放行 55-64% 犹豫带。min_confidence_open=0 (关闭门禁)
        时原样返回 0。
        """
        cfg = self.config.trading
        base = cfg.min_confidence_open
        if base <= 0:
            return 0.0
        if cfg.gate_relief_rr_min > 0 and aligned_rr >= cfg.gate_relief_rr_min:
            relaxed = max(cfg.gate_relief_floor, base - cfg.gate_relief_amount)
            if relaxed < base:
                logger.info(
                    "[机会审计] 方向一致 R/R=%.2f ≥ %.1f → 开仓门禁放宽 " "%.2f → %.2f",
                    aligned_rr,
                    cfg.gate_relief_rr_min,
                    base,
                    relaxed,
                )
            return relaxed
        return base

    def _position_upl_percent(self, current_price: float) -> Optional[float]:
        """持仓浮动盈亏百分比 (多: (现价-入场)/入场; 空: (入场-现价)/入场)。

        2026-11-24 / P0-A: 亏损态平仓门禁下移的 UPL 判据。
        数据不可用时返回 None (门禁不放宽, 保守方向)。
        """
        entry = self.position_manager.entry_price
        if not entry or entry <= 0 or not current_price or current_price <= 0:
            return None
        try:
            side = self.position_manager.position_side
            if side == "short":
                return (entry - current_price) / entry
            return (current_price - entry) / entry
        except Exception:
            return None

    async def _execute_signal(
        self,
        signal: str,
        current_price: float,
        has_position: bool,
        final_confidence: Optional[float] = None,
        structure_rr: float = 0.0,
        short_rr: float = 0.0,
        change_percent: float = 0.0,
        atr_percent: float = 0.0,
        buy_mode: str = "",
        trend_direction: str = "",
        signal_streak: int = 1,
    ) -> ExecutionResult:
        """执行信号

        final_confidence: 信号最终置信度（0-1）。非 None 时执行层置信度门禁生效：
        - BUY + 无持仓: 低于开仓门禁（R/R 感知动态放宽, P0-3）→ 禁止开仓（P0-1）
        - SHORT + 无持仓: 同上 (做空侧, 2026-11-24 新增执行路径)
        - 平仓意图 (SELL+多 / BUY+空 / SHORT+多): 低于 min_confidence_close → 禁止平仓
        None（旧 3 参调用路径）：门禁不生效并 WARNING 提示（零回归）。

        structure_rr / short_rr: 方向一致的 ATR 口径 R/R (仅放宽对应侧门禁用)。
        change_percent: 24h 涨跌幅% (做空逆势门禁 short_entry_max_daily_change)。
        atr_percent: ATR 百分比 (开仓 ATR 止损用, 0=不传)。
        buy_mode: 自适应买入模式 (oversold_rebound 翻转开仓用半仓, P1-C)。
        trend_direction: 1h 趋势方向 (up/down/neutral, P0-2 反手保护技术反转判定)。
        signal_streak: 同向信号连续周期数 (P2-10 信号连续确认, 1=无确认要求)。
        """
        logger.info(
            f"[信号执行] 开始处理信号: {signal}, 当前价格: {current_price}, "
            f"持仓状态: {'有持仓' if has_position else '无持仓'}"
        )

        # 2026-11-24: 持仓方向感知 (prompt 持仓语义):
        #   多仓: SELL/SHORT=平多, BUY=继续持有; 空仓: BUY=平空, SELL/SHORT=继续持有
        position_side = self.position_manager.position_side if has_position else "none"

        # 执行层置信度门禁（2026-10-08 手续费出血修复 / P0-1；
        # 2026-11-24 P0-3: 开仓侧 R/R 感知动态放宽）：
        # 低置信度往返单的成本 ≈ 11.5bp，而 54-67% 置信度信号的毛利 ≈ 0，
        # 只放行有把握（>= 门禁）的开/平仓，其余交给止损/止盈单管理。
        # 2026-11-26 P2-10: 信号连续确认 (单 AI 置信度漂移防护):
        # 方向性信号 (BUY/SELL/SHORT) 需连续 N 个周期同向才执行,
        # 孤立单次信号 (11-25 两笔亏损平仓均为前后 HOLD 的孤立 BUY) 本轮保持。
        confirm_cycles = self.config.trading.signal_confirm_cycles
        if (
            final_confidence is not None
            and confirm_cycles > 1
            and signal in ("BUY", "SELL", "SHORT")
            and signal_streak < confirm_cycles
        ):
            logger.info(
                "[信号执行] %s信号 + 仅连续 %d 周期同向 < %d -> 本轮保持 "
                "(P2-10 信号连续确认, 独立技术通道不受影响)",
                signal,
                signal_streak,
                confirm_cycles,
            )
            return ExecutionResult(
                "blocked_signal_confirm",
                f"streak={signal_streak}<need={confirm_cycles}",
            )

        if final_confidence is None:
            if signal in ("BUY", "SELL", "SHORT"):
                logger.warning(
                    "[信号执行] 未提供置信度 (final_confidence=None)，"
                    "置信度门禁本轮不生效（旧调用路径）"
                )
        elif signal == "BUY" and not has_position:
            min_conf = self._effective_open_confidence_gate(structure_rr)
            if min_conf > 0 and final_confidence < min_conf:
                # 2026-11 机会审计: 记录 最终置信度 vs 门禁 的 gap, 复盘时
                # 一行 grep 即可定位漏单 (而非翻 5000 行日志)
                logger.info(
                    "[信号执行] BUY信号 + 置信度 %.2f < 门禁 %.2f -> 禁止开仓 "
                    "(P0-1 置信度门禁) [机会审计] gap=%.1fpt",
                    final_confidence,
                    min_conf,
                    (min_conf - final_confidence) * 100,
                )
                return ExecutionResult(
                    "blocked_low_confidence",
                    f"buy_conf={final_confidence:.2f}<min={min_conf:.2f}",
                )
        elif signal == "SHORT" and not has_position:
            if not self.config.trading.allow_short_selling:
                logger.info(
                    "[信号执行] SHORT信号 + 无持仓 + 做空已禁用 "
                    "(ALLOW_SHORT_SELLING=false) -> 不操作"
                )
                return ExecutionResult(
                    "blocked_short_disabled", "allow_short_selling=false"
                )
            min_conf = self._effective_open_confidence_gate(short_rr)
            if min_conf > 0 and final_confidence < min_conf:
                logger.info(
                    "[信号执行] SHORT信号 + 置信度 %.2f < 门禁 %.2f -> 禁止开空 "
                    "(P0-1 置信度门禁) [机会审计] gap=%.1fpt",
                    final_confidence,
                    min_conf,
                    (min_conf - final_confidence) * 100,
                )
                return ExecutionResult(
                    "blocked_low_confidence",
                    f"short_conf={final_confidence:.2f}<min={min_conf:.2f}",
                )
        elif has_position:
            # 平仓意图: SELL+多 / BUY+空 / SHORT+多 (prompt 持仓语义)
            is_close_intent = (
                (signal == "SELL" and position_side == "long")
                or (signal == "BUY" and position_side == "short")
                or (signal == "SHORT" and position_side == "long")
            )
            if is_close_intent:
                min_close = self.config.trading.min_confidence_close
                # 2026-11-26 P0-2: 趋势通道新仓反手保护——趋势仓开仓后
                # trend_close_protection_minutes 内, 反向 AI 信号需
                # 置信度 ≥ trend_close_min_confidence 且 1h 技术趋势已反转
                # 才允许平仓 (11-25 复盘: 趋势开空 2~4 分钟后被单次 BUY 反手平掉)。
                pm_pos = self.position_manager.position
                if (
                    pm_pos is not None
                    and pm_pos.origin == "trend"
                    and self._trend_close_protection_active(
                        self.position_manager.entry_time,
                        pm_pos.side,
                        final_confidence,
                        trend_direction,
                        change_percent,
                    )
                ):
                    logger.info(
                        "[信号执行] %s信号 + 趋势仓新仓保护期内 "
                        "(置信度 %.2f / 技术趋势未反转) -> 忽略平仓信号 "
                        "(仓位由止损单保护, P0-2 反手保护)",
                        signal,
                        final_confidence if final_confidence is not None else 0.0,
                    )
                    return ExecutionResult(
                        "protected_trend_position", "trend_close_protection"
                    )
                # 2026-11-24 (P0-A): 亏损态平仓下移——浮亏时门禁
                # close_relief_amount (下限 close_relief_floor)。回放 11-24
                # 13:43-14:15: 浮亏 -0.21%/-0.43% 时三次 SELL (51%/55%/57%)
                # 全被 0.60 门禁拦截, 直到 AI 原始 78% 才放行, 吃满 -0.42%
                # 阴跌。放宽只作用于"离场", 重开仍受平仓冷却约束 (不引入
                # 2026-10-08 修复过的 churn)。
                upl = self._position_upl_percent(current_price)
                # 2026-11-26 P0-2: P0-A 亏损态放宽不适用于趋势仓 (它加速离场,
                # 与趋势通道 "让利润奔跑" 设计冲突)
                if (
                    min_close > 0
                    and upl is not None
                    and upl < 0
                    and self.config.trading.close_relief_amount > 0
                    and (pm_pos is None or pm_pos.origin != "trend")
                ):
                    relaxed_close = max(
                        self.config.trading.close_relief_floor,
                        min_close - self.config.trading.close_relief_amount,
                    )
                    if relaxed_close < min_close:
                        logger.info(
                            "[机会审计] 浮亏 %.2f%% < 0 → 平仓门禁下移 "
                            "%.2f → %.2f (P0-A 亏损态放宽, 仓位离场加速)",
                            upl * 100,
                            min_close,
                            relaxed_close,
                        )
                        min_close = relaxed_close
                if min_close > 0 and final_confidence < min_close:
                    logger.info(
                        "[信号执行] %s信号 + %s持仓 + 置信度 %.2f < 平仓门禁 %.2f "
                        "-> 禁止平仓 (P0-1 置信度门禁，仓位由止损单保护) "
                        "[机会审计] gap=%.1fpt",
                        signal,
                        position_side,
                        final_confidence,
                        min_close,
                        (min_close - final_confidence) * 100,
                    )
                    return ExecutionResult(
                        "blocked_low_confidence",
                        f"close_conf={final_confidence:.2f}<min={min_close:.2f}",
                    )

        if signal == "BUY":
            if not has_position:
                # 2026-11 每日新开仓上限: 门禁下调后的成本控制 (0=关闭)
                daily_limit = self.config.trading.daily_open_limit
                if daily_limit > 0:
                    today = datetime.now().strftime("%Y-%m-%d")
                    if self._daily_open_counts.get(today, 0) >= daily_limit:
                        logger.info(
                            "[信号执行] BUY信号 + 无持仓 + 已达每日开仓上限 "
                            "(%d笔) -> 禁止新开仓 (成本防护)",
                            daily_limit,
                        )
                        return ExecutionResult(
                            "blocked_daily_limit",
                            f"daily_opens={self._daily_open_counts.get(today, 0)}"
                            f">=limit={daily_limit}",
                        )
                # P1 回撤总闸：停机期间禁止新开仓（已持仓管理不受影响）
                if self._drawdown_status is not None and self._drawdown_status.halted:
                    logger.warning(
                        "[信号执行] BUY信号 + 无持仓 + 回撤总闸生效 -> 禁止新开仓"
                        "（回撤 %.1f%%）",
                        self._drawdown_status.drawdown * 100,
                    )
                    return ExecutionResult(
                        "blocked_drawdown",
                        f"drawdown={self._drawdown_status.drawdown:.2%}",
                    )
                # P0-2 平仓后冷却：平仓后 N 分钟内禁止重新开仓
                # （斩断"平仓后 5 分钟即重开"式 churn，每 churn 一次 ≈ -0.23% 账户成本）
                cooldown = self.config.trading.post_close_cooldown_minutes
                if cooldown > 0 and self.position_manager.is_in_post_close_cooldown(
                    cooldown
                ):
                    logger.info(
                        "[信号执行] BUY信号 + 无持仓 + 处于平仓后冷却期 (%d分钟) "
                        "-> 禁止重新开仓 (P0-2 冷却)",
                        cooldown,
                    )
                    return ExecutionResult(
                        "blocked_cooldown", f"cooldown_minutes={cooldown}"
                    )
                # 2026-11-24 (P1-C): oversold_rebound 翻转是逆势抄底入场
                # → 半仓 (与超卖抄底独立通道同口径), 降低单笔逆势风险。
                # 回放 11-24 13:43: 0.03 张全仓抄底, -0.42% 即账户 -1.3%。
                open_size_factor = 1.0
                if buy_mode == "oversold_rebound":
                    open_size_factor = self.config.trading.oversold_buy_position_factor
                logger.info(
                    "[信号执行] BUY信号 + 无持仓 -> 执行开仓 "
                    "(模式=%s, 仓位系数=%.2f)",
                    buy_mode or "none",
                    open_size_factor,
                )
                opened = await self._open_position(
                    current_price,
                    size_factor=open_size_factor,
                    atr_percent=(
                        atr_percent if atr_percent and atr_percent > 0 else None
                    ),
                )
                if opened:
                    today = datetime.now().strftime("%Y-%m-%d")
                    self._daily_open_counts[today] = (
                        self._daily_open_counts.get(today, 0) + 1
                    )
                    self._persist_daily_counts()
                return ExecutionResult("open_long", f"price={current_price}")
            if position_side == "short":
                # prompt 语义: 持有空仓 + BUY = 平空
                logger.info("[信号执行] BUY信号 + 持有空仓 -> 执行平空")
                await self._close_position(current_price)
                return ExecutionResult("close", f"price={current_price},side=short")
            logger.info("[信号执行] BUY信号 + 多仓 -> 更新止损")
            await self._update_stop_loss(current_price, atr_percent=atr_percent)
            return ExecutionResult("update_stop")

        if signal == "HOLD":
            if has_position:
                logger.info("[信号执行] HOLD信号 + 有持仓 -> 更新止损")
                await self._update_stop_loss(current_price, atr_percent=atr_percent)
                return ExecutionResult("update_stop")
            logger.info("[信号执行] HOLD信号 + 无持仓 -> 不操作")
            logger.info(
                "[机会评估] 当前为HOLD信号，系统持续监控中。如需更多交易机会，可考虑: "
                "1)提高DAILY_OPEN_LIMIT 2)检查超卖抄底/高潮做空独立通道是否被冷却/"
                "每日上限拦截 3)复核MIN_CONFIDENCE_OPEN门禁与[机会审计]gap"
            )
            return ExecutionResult("none")

        if signal == "SELL":
            if has_position:
                if position_side == "short":
                    # prompt 语义: 持有空仓 + SELL = 同向继续持有
                    logger.info("[信号执行] SELL信号 + 空仓 -> 同向持有 (更新止损)")
                    await self._update_stop_loss(current_price, atr_percent=atr_percent)
                    return ExecutionResult("update_stop")
                logger.info("[信号执行] SELL信号 + 多仓 -> 执行平仓")
                await self._close_position(current_price)
                return ExecutionResult("close", f"price={current_price}")
            logger.info("[信号执行] SELL信号 + 无持仓 -> 不操作")
            return ExecutionResult("none")

        if signal == "SHORT":
            if has_position:
                if position_side == "short":
                    # prompt 语义: 持有空仓 + SHORT = 同向继续持有
                    logger.info("[信号执行] SHORT信号 + 空仓 -> 同向持有 (更新止损)")
                    await self._update_stop_loss(current_price, atr_percent=atr_percent)
                    return ExecutionResult("update_stop")
                # 多仓 + SHORT = 平多 (prompt 语义: SELL/SHORT 表示平多)
                logger.info("[信号执行] SHORT信号 + 多仓 -> 执行平多")
                await self._close_position(current_price)
                return ExecutionResult("close", f"price={current_price},side=long")
            # 无持仓 + SHORT -> 执行开空 (2026-11-24 新增, 此前 SHORT 无执行路径)
            # 逆势做空门禁: 24h 大幅上涨日禁止逆势开空 (2026-09-18 复盘)
            gate = self.config.trading.short_entry_max_daily_change
            if gate > 0 and change_percent > gate:
                logger.info(
                    "[信号执行] SHORT信号 + 无持仓 + 24h涨幅 %.2f%% > 门禁 %.1f%% "
                    "-> 禁止逆势开空 (成本防护)",
                    change_percent,
                    gate,
                )
                return ExecutionResult(
                    "blocked_short_daily_change",
                    f"24h_change={change_percent:.2f}>gate={gate}",
                )
            # 2026-11 每日新开仓上限 (与 BUY 同一计数器)
            daily_limit = self.config.trading.daily_open_limit
            if daily_limit > 0:
                today = datetime.now().strftime("%Y-%m-%d")
                if self._daily_open_counts.get(today, 0) >= daily_limit:
                    logger.info(
                        "[信号执行] SHORT信号 + 无持仓 + 已达每日开仓上限 "
                        "(%d笔) -> 禁止新开空 (成本防护)",
                        daily_limit,
                    )
                    return ExecutionResult(
                        "blocked_daily_limit",
                        f"daily_opens={self._daily_open_counts.get(today, 0)}"
                        f">=limit={daily_limit}",
                    )
            if self._drawdown_status is not None and self._drawdown_status.halted:
                logger.warning(
                    "[信号执行] SHORT信号 + 无持仓 + 回撤总闸生效 -> 禁止新开空"
                    "（回撤 %.1f%%）",
                    self._drawdown_status.drawdown * 100,
                )
                return ExecutionResult(
                    "blocked_drawdown",
                    f"drawdown={self._drawdown_status.drawdown:.2%}",
                )
            cooldown = self.config.trading.post_close_cooldown_minutes
            if cooldown > 0 and self.position_manager.is_in_post_close_cooldown(
                cooldown
            ):
                logger.info(
                    "[信号执行] SHORT信号 + 无持仓 + 处于平仓后冷却期 (%d分钟) "
                    "-> 禁止新开空 (P0-2 冷却)",
                    cooldown,
                )
                return ExecutionResult(
                    "blocked_cooldown", f"cooldown_minutes={cooldown}"
                )
            logger.info("[信号执行] SHORT信号 + 无持仓 -> 执行开空")
            opened = await self._open_position(
                current_price,
                side="short",
                atr_percent=(atr_percent if atr_percent and atr_percent > 0 else None),
            )
            if opened:
                today = datetime.now().strftime("%Y-%m-%d")
                self._daily_open_counts[today] = (
                    self._daily_open_counts.get(today, 0) + 1
                )
                self._persist_daily_counts()
            return ExecutionResult("open_short", f"price={current_price}")

        logger.warning(f"[信号执行] 未知信号: {signal}")
        return ExecutionResult("error", f"unknown_signal={signal}")

    def _trend_close_protection_active(
        self,
        entry_time: Optional[str],
        position_side: str,
        final_confidence: Optional[float],
        trend_direction: str,
        change_percent: float,
    ) -> bool:
        """趋势仓反向平仓是否应被拦截 (2026-11-26 P0-2)。

        开仓后 trend_close_protection_minutes 内, 反向 AI 信号需同时满足:
        - 置信度 ≥ trend_close_min_confidence
        - 1h 技术趋势已反转 (空仓→up / 多仓→down) 或 24h 涨跌号翻转
        才允许平仓。保护窗口=0 / 无入场时间 / 解析失败 → False (fail-open,
        止损单仍兜底)。11-25 复盘: 趋势开空 2~4 分钟后被 AI 单次 BUY
        (55~81%) 反手平掉, 三笔全部亏损。
        """
        cfg = self.config.trading
        if cfg.trend_close_protection_minutes <= 0:
            return False
        if not entry_time:
            return False
        try:
            entry_dt = datetime.fromisoformat(entry_time)
        except (TypeError, ValueError):
            logger.warning(
                "[趋势仓保护] 入场时间解析失败, 本轮跳过保护: %s", entry_time
            )
            return False
        age_minutes = (datetime.now() - entry_dt).total_seconds() / 60.0
        if age_minutes >= cfg.trend_close_protection_minutes:
            return False
        conf_ok = (
            final_confidence is not None
            and final_confidence >= cfg.trend_close_min_confidence
        )
        if position_side == "short":
            flip_ok = trend_direction == "up" or change_percent > 0
        else:
            flip_ok = trend_direction == "down" or change_percent < 0
        if conf_ok and flip_ok:
            logger.info(
                "[趋势仓保护] 反向信号满足平仓条件 (置信度 %.2f ≥ %.2f 且 "
                "技术趋势已反转/24h 号翻转), 放行平仓",
                final_confidence or 0.0,
                cfg.trend_close_min_confidence,
            )
            return False
        return True

    def _persist_daily_counts(self) -> None:
        """持久化每日计数 (2026-11-26 P0-3, 重启不再清零)。"""
        try:
            self.position_manager.save_daily_counts(
                self._daily_open_counts,
                self._trend_follow_counts,
                self._oversold_buy_counts,
                self._climax_short_counts,
            )
        except Exception as e:
            logger.warning("[每日计数] 持久化失败（不影响主流程）: %s", e)

    def _update_signal_streak(self, signal: str) -> int:
        """更新信号连续确认计数 (2026-11-26 P2-10, 持久化跨重启)。

        同一方向信号连续周期数 +1, 方向变化 (含 HOLD) 重置为 1。
        返回当前 streak (供执行层 SIGNAL_CONFIRM_CYCLES 门禁用)。
        """
        sig = str(signal or "").upper()
        if sig == self._last_signal:
            self._signal_streak += 1
        else:
            self._last_signal = sig
            self._signal_streak = 1
        try:
            self.position_manager.save_signal_streak(sig, self._signal_streak)
        except Exception as e:
            logger.warning("[信号确认] 持久化失败（不影响主流程）: %s", e)
        return self._signal_streak

    @staticmethod
    def _htf_trend_direction(closes: List[float]) -> str:
        """1h 收盘聚合为 4h 后判断高级别趋势 (2026-11-26 P1-7)。

        与 AI 层 market_structure._detect_htf_structure 同口径
        (每 4 根 1h 取最后一根作为 4h 收盘), 但用 SMA10/20 判定:
        price>sma10>sma20 → up; price<sma10<sma20 → down; 其余 → sideways。
        数据不足 (21 根 4h 收盘 ≈ 84 根 1h) → unknown (调用方 fail-closed)。
        """
        if not closes or len(closes) < 84:
            return "unknown"
        tail = list(closes[-100:])
        n = len(tail) // 4  # 完整的 4h 根数 (对齐到最新收盘)
        if n < 21:
            return "unknown"
        # 每 4 根 1h 的最后一根 = 4h 收盘; k=0 为最新, 逆序后旧→新
        htf_closes = [tail[len(tail) - 4 * k - 1] for k in range(n)]
        htf_closes.reverse()
        trend = calculate_trend(htf_closes)
        return {"up": "up", "down": "down"}.get(trend.get("direction", ""), "sideways")

    async def _query_protection_fill_attribution(
        self,
        stop_order_id: Optional[str],
        tp_order_id: Optional[str],
    ) -> Optional[Tuple[str, float]]:
        """查交易所算法单状态, 定位真实平仓触发单 (2026-11-26 P1-5)。

        Returns:
            (触发源描述, 真实成交/触发价) 或 None (查不到/TEST_MODE →
            调用方回退到现价比对启发式)。best-effort, 任何异常不中断主流程。

        11-26 00:14 复盘: 旧启发式拿尖峰回落后的现价比对, 把真实止损
        成交 (触发价 58673) 误标为 "未知保护单" 且盈亏误估 -0.14%
        (实际 -0.64%)。
        """
        symbol = self.config.exchange.symbol
        ord_types = ["conditional", "trigger", "move_order_stop"]
        try:
            for algo_id, kind in (
                (stop_order_id, "止损单"),
                (tp_order_id, "止盈单"),
            ):
                if not algo_id:
                    continue
                history = await self._exchange.get_algo_order_history(
                    symbol,
                    algo_id=str(algo_id),
                    limit=5,
                    ord_types=ord_types,
                )
                for order in history or []:
                    if str(order.get("id")) != str(algo_id):
                        continue
                    info = order.get("info") or {}
                    # 用 OKX 原始状态: effective=生效中, filled=已触发成交
                    raw_state = str(info.get("state") or "").lower()
                    if raw_state != "filled":
                        continue
                    try:
                        avg_px = float(info.get("avgPx") or 0) or 0.0
                    except (TypeError, ValueError):
                        avg_px = 0.0
                    trigger_raw = (
                        info.get("slTriggerPx")
                        if kind == "止损单"
                        else info.get("tpTriggerPx")
                    )
                    try:
                        trigger_px = float(trigger_raw) if trigger_raw else 0.0
                    except (TypeError, ValueError):
                        trigger_px = 0.0
                    detail = []
                    if trigger_px > 0:
                        detail.append(f"触发价 {trigger_px:.1f}")
                    if avg_px > 0:
                        detail.append(f"成交价 {avg_px:.1f}")
                    return (
                        f"{kind} (algoId={algo_id} 已成交, {', '.join(detail)})",
                        avg_px or trigger_px,
                    )
        except Exception as e:
            logger.debug("[保护单归因] 查询算法单历史失败 (best-effort): %s", e)
        return None

    async def _log_protection_order_fill(self, current_price: float) -> None:
        """保护单成交归因 (2026-11 P2-12 → 2026-11-26 P1-5 增强)。

        对账发现仓位已在交易所侧消失时: 优先查交易所算法单状态定位真实
        触发单与触发价; 查不到 (TEST_MODE/接口失败) 再回退 当前价 vs
        止损/止盈价启发式。11-26 00:14 复盘: 旧启发式拿尖峰回落后的现价
        比对, 把真实止损成交误标为 "未知保护单" 且盈亏误估 -0.14%
        (实际 -0.64%)。任何异常不中断主流程。
        """
        try:
            pm = self.position_manager
            pos = pm.position
            if pos is None or current_price <= 0:
                return
            side = pos.side
            entry = pm.entry_price
            last_sl = pm.last_stop_price
            last_tp = pm.last_take_profit_price

            # P1-5: 优先查交易所真实触发单 (状态 filled → 归因确定)
            real = await self._query_protection_fill_attribution(
                pm.stop_order_id, pm.take_profit_order_id
            )
            if real is not None:
                attribution, fill_px = real
                # 用真实成交/触发价估算盈亏 (尖峰后现价已回落, 现价会低估)
                ref_px = fill_px if fill_px > 0 else current_price
                pnl_hint = (
                    f", 约 {(entry - ref_px) / entry * 100:+.2f}% (入场 {entry:.1f})"
                    if side == "short" and entry > 0
                    else (
                        f", 约 {(ref_px - entry) / entry * 100:+.2f}% (入场 {entry:.1f})"
                        if entry > 0
                        else ""
                    )
                )
                logger.info(
                    "[保护单归因] 仓位已在交易所侧平仓, 触发源: %s, " "当前价 %.1f%s",
                    attribution,
                    current_price,
                    pnl_hint,
                )
                return

            attribution = "未知保护单"
            pnl_hint = ""
            if side == "long":
                if last_tp > 0 and current_price >= last_tp * 0.999:
                    attribution = f"止盈单 (触发价 {last_tp:.1f})"
                elif last_sl > 0 and current_price <= last_sl * 1.001:
                    attribution = f"止损单 (触发价 {last_sl:.1f})"
                if entry > 0:
                    pnl_pct = (current_price - entry) / entry * 100
                    pnl_hint = f", 约 {pnl_pct:+.2f}% (入场 {entry:.1f})"
            else:  # short
                if last_tp > 0 and current_price <= last_tp * 1.001:
                    attribution = f"止盈单 (触发价 {last_tp:.1f})"
                elif last_sl > 0 and current_price >= last_sl * 0.999:
                    attribution = f"止损单 (触发价 {last_sl:.1f})"
                if entry > 0:
                    pnl_pct = (entry - current_price) / entry * 100
                    pnl_hint = f", 约 {pnl_pct:+.2f}% (入场 {entry:.1f})"

            logger.info(
                "[保护单归因] 仓位已在交易所侧平仓, 推断触发源: %s, " "当前价 %.1f%s",
                attribution,
                current_price,
                pnl_hint,
            )
        except Exception as e:
            logger.debug("[保护单归因] 失败 (不影响主流程): %s", e)

    async def _maybe_oversold_bottom_buy(
        self, market_data: Dict[str, Any], current_price: float
    ) -> Optional[ExecutionResult]:
        """超卖抄底独立通道（2026-11 底部捕获 / P1-5）。

        技术极端超卖独立触发: RSI ≤ oversold_buy_rsi_max 且价格位于
        24h 低点 near_low_pct 以内 → 逆势抄底 (半仓, 每日最多 1 次),
        绕过 AI 置信度门禁。保留门禁: 实盘闸门 / 回撤总闸 /
        平仓冷却 / 每日开仓上限 (均在 _open_position 或本方法内)。

        回放依据: 11-21 14:14 (RSI=16.2, 55647=24h 最低区) 原流水线
        5 层折扣后 66.5% < 0.75 门禁被拦, 错过 55.6k→60.7k (+9.1%)
        反弹。本通道半仓 + 每日 1 次, 成本可控; 触发后由止损单兜底。

        2026-11-24 回放增强 (P1-6):
        - 1h 动量守卫: 1h 涨跌幅 ≤ oversold_buy_min_1h_change 时跳过
          (动量仍在崩塌, 不接飞刀)。
        - ATR 止损: 开仓时按 max(默认止损, clamp(ATR, 0.3%, 5%)) 挂止损,
          避免 0.5% 固定止损被 15m wick 瞬间扫掉。
          回放 11-24 11:03: 入场 60,123.4, 旧止损 59,822.78 (0.5%) 在 8 分钟
          内被 59,536 击穿; ATR=1.245% → 新止损 ≈59,371, 可守住该低点并
          吃到后续反弹。
        """
        cfg = self.config.trading
        if not cfg.oversold_buy_enabled:
            return None
        if not current_price or current_price <= 0:
            return None

        rsi = market_data.get("technical", {}).get("rsi", 50.0)
        if rsi > cfg.oversold_buy_rsi_max:
            return None

        low_24h = market_data.get("low", 0)
        if not low_24h or low_24h <= 0:
            return None
        if current_price > low_24h * (1 + cfg.oversold_buy_near_low_pct):
            return None

        # 1h 动量守卫 (2026-11-24 回放 / P1-6): 1h 仍大幅下跌时动量未止,
        # 本周期跳过, 等待下一周期 (价格企稳后 1h 涨跌幅转正/收窄)。
        recent_1h = market_data.get("recent_drop_percent", 0.0) or 0.0
        if recent_1h <= cfg.oversold_buy_min_1h_change:
            logger.info(
                "[超卖抄底] 技术条件满足但1h涨跌幅 %.2f%% ≤ 守卫 %.2f%% "
                "(动量仍在崩塌) → 跳过",
                recent_1h * 100,
                cfg.oversold_buy_min_1h_change * 100,
            )
            return None

        today = datetime.now().strftime("%Y-%m-%d")
        if self._oversold_buy_counts.get(today, 0) >= cfg.oversold_buy_daily_limit:
            logger.info(
                "[超卖抄底] 技术条件满足但今日已触发 %d 次 (上限 %d) → 跳过",
                self._oversold_buy_counts.get(today, 0),
                cfg.oversold_buy_daily_limit,
            )
            return None

        # 既有门禁复用 (与 BUY 分支同口径)
        if self._drawdown_status is not None and self._drawdown_status.halted:
            logger.info(
                "[超卖抄底] 技术条件满足但回撤总闸生效 → 跳过 (回撤 %.1f%%)",
                self._drawdown_status.drawdown * 100,
            )
            return None
        cooldown = cfg.post_close_cooldown_minutes
        if cooldown > 0 and self.position_manager.is_in_post_close_cooldown(cooldown):
            logger.info("[超卖抄底] 技术条件满足但处于平仓后冷却期 → 跳过")
            return None
        daily_limit = cfg.daily_open_limit
        if daily_limit > 0 and self._daily_open_counts.get(today, 0) >= daily_limit:
            logger.info(
                "[超卖抄底] 技术条件满足但已达每日开仓上限 (%d笔) → 跳过",
                daily_limit,
            )
            return None

        atr_percent = (market_data.get("technical") or {}).get("atr_percent")

        logger.warning(
            "[超卖抄底] 独立通道触发: RSI=%.1f ≤ %.0f, 价格 %.1f 位于 24h 低点 "
            "%.1f 的 %.0f%% 以内 (1h=%.2f%%) → 逆势抄底 (半仓, ATR止损, "
            "审计置信度 %.2f)",
            rsi,
            cfg.oversold_buy_rsi_max,
            current_price,
            low_24h,
            cfg.oversold_buy_near_low_pct * 100,
            recent_1h * 100,
            cfg.oversold_buy_confidence,
        )

        opened = await self._open_position(
            current_price,
            size_factor=cfg.oversold_buy_position_factor,
            atr_percent=atr_percent,
            origin="oversold",
        )
        if opened:
            self._oversold_buy_counts[today] = (
                self._oversold_buy_counts.get(today, 0) + 1
            )
            self._daily_open_counts[today] = self._daily_open_counts.get(today, 0) + 1
            self._persist_daily_counts()
            return ExecutionResult(
                "open_long_oversold",
                f"price={current_price},rsi={rsi:.1f},"
                f"audit_conf={cfg.oversold_buy_confidence:.2f}",
            )
        return None

    async def _maybe_climax_short(
        self, market_data: Dict[str, Any], current_price: float
    ) -> Optional[ExecutionResult]:
        """高潮做空独立通道（2026-11-24 顶部捕获 / P0-2）。

        "Climax top 做空"独立触发: 价格贴近 24h 高点 (near_high_pct 以内)
        + 1h RSI ≥ climax_short_rsi_min (超买) + 做空 R/R ≥ climax_short_rr_min
        → 逆势开空 (半仓, 每日 N 次), 绕过 AI 置信度门禁。与超卖抄底通道
        对称: 抄底抓 24h 低点区, 本通道抓 24h 高点区。

        回放依据 (2026-11-23 22:00-23:57): 做空 R/R 3.0-7.1 (excellent),
        RSI(1h) 67-78, 价格处 24h 高点区, 随后 11-24 62.8k→59.5k (-5.3%)
        主跌段完全空仓错过。误报排除验证: 11-23 02:14 做空 R/R=4.36 但
        RSI≈50 (<65) 且价格远离 24h 高点 → 正确排除 (该时段实际上涨 5.6%)。

        止损/止盈直接采用 R/R 计算器的做空建议价 (摆动高点+ATR 缓冲止损 /
        最近支撑止盈), 保留门禁: 实盘闸门 / 回撤总闸 / 平仓冷却 /
        每日开仓上限 / 做空开关。
        """
        cfg = self.config.trading
        if not cfg.climax_short_enabled or not cfg.allow_short_selling:
            return None
        if not current_price or current_price <= 0:
            return None

        high_24h = market_data.get("high", 0)
        if not high_24h or high_24h <= 0:
            return None
        # 高潮区判定: 价格 ≥ 24h 高点 × (1 - near_high_pct)
        if current_price < high_24h * (1 - cfg.climax_short_near_high_pct):
            return None

        today = datetime.now().strftime("%Y-%m-%d")

        rsi = market_data.get("technical", {}).get("rsi", 50.0)
        if rsi < cfg.climax_short_rsi_min:
            # 机会审计 (限频): 高潮区+超买未满足时量化 gap
            if self._climax_audit_counts.get(today, 0) < 4:
                self._climax_audit_counts[today] = (
                    self._climax_audit_counts.get(today, 0) + 1
                )
                logger.info(
                    "[机会审计] 处于24h高点区 (%.1f%%内) 但 RSI(1h)=%.1f < %.0f "
                    "(未超买) → 高潮做空条件不足, 跳过",
                    cfg.climax_short_near_high_pct * 100,
                    rsi,
                    cfg.climax_short_rsi_min,
                )
            return None

        if self._climax_short_counts.get(today, 0) >= cfg.climax_short_daily_limit:
            logger.info(
                "[高潮做空] 技术条件满足但今日已触发 %d 次 (上限 %d) → 跳过",
                self._climax_short_counts.get(today, 0),
                cfg.climax_short_daily_limit,
            )
            return None

        # 既有门禁复用 (与 BUY 分支同口径)
        if self._drawdown_status is not None and self._drawdown_status.halted:
            logger.info(
                "[高潮做空] 技术条件满足但回撤总闸生效 → 跳过 (回撤 %.1f%%)",
                self._drawdown_status.drawdown * 100,
            )
            return None
        cooldown = cfg.post_close_cooldown_minutes
        if cooldown > 0 and self.position_manager.is_in_post_close_cooldown(cooldown):
            logger.info("[高潮做空] 技术条件满足但处于平仓后冷却期 → 跳过")
            return None
        daily_limit = cfg.daily_open_limit
        if daily_limit > 0 and self._daily_open_counts.get(today, 0) >= daily_limit:
            logger.info(
                "[高潮做空] 技术条件满足但已达每日开仓上限 (%d笔) → 跳过",
                daily_limit,
            )
            return None

        # 做空 R/R (复用 integrator 的计算器; 支撑/阻力由市场结构附加到 market_data)
        technical = market_data.get("technical") or {}
        atr_percent = technical.get("atr_percent", 0.0)
        support = market_data.get("nearest_support", 0.0) or 0.0
        resistance = market_data.get("nearest_resistance", 0.0) or 0.0
        if self._ai_client is None or support <= 0 or resistance <= 0:
            logger.info("[高潮做空] 市场结构/支撑阻力不可用 → 跳过")
            return None
        try:
            short_rr_result = (
                self._ai_client.integrator.risk_reward_calculator.calculate_for_short(
                    current_price=current_price,
                    support=support,
                    resistance=resistance,
                    atr_percent=atr_percent,
                )
            )
        except Exception as e:
            logger.warning("[高潮做空] 做空R/R计算失败 (跳过本周期): %s", e)
            return None

        if short_rr_result.rr_ratio < cfg.climax_short_rr_min:
            logger.info(
                "[机会审计] 高潮区 (RSI=%.1f, 距24h高点 %.2f%%) 但做空R/R=%.2f "
                "< %.1f → 高潮做空跳过",
                rsi,
                (1 - current_price / high_24h) * 100,
                short_rr_result.rr_ratio,
                cfg.climax_short_rr_min,
            )
            return None

        logger.warning(
            "[高潮做空] 独立通道触发: 价格 %.1f 位于 24h 高点 %.1f 的 %.0f%% 以内, "
            "RSI(1h)=%.1f ≥ %.0f, 做空R/R=%.2f → 开空 (半仓, 止损=%.1f 止盈=%.1f)",
            current_price,
            high_24h,
            cfg.climax_short_near_high_pct * 100,
            rsi,
            cfg.climax_short_rsi_min,
            short_rr_result.rr_ratio,
            short_rr_result.stop_loss_price,
            short_rr_result.take_profit_price,
        )

        opened = await self._open_position(
            current_price,
            size_factor=cfg.climax_short_position_factor,
            side="short",
            atr_percent=atr_percent,
            stop_price_override=short_rr_result.stop_loss_price,
            tp_price_override=short_rr_result.take_profit_price,
            origin="climax",
        )
        if opened:
            self._climax_short_counts[today] = (
                self._climax_short_counts.get(today, 0) + 1
            )
            self._daily_open_counts[today] = self._daily_open_counts.get(today, 0) + 1
            self._persist_daily_counts()
            return ExecutionResult(
                "open_short_climax",
                f"price={current_price},rr={short_rr_result.rr_ratio:.2f},"
                f"rsi={rsi:.1f}",
            )
        return None

    async def _apply_risk_backcheck(
        self,
        price: float,
        amount: float,
        stop_distance: Optional[float] = None,
    ) -> float:
        """单笔风险反查（P1）：止损触发时的预期亏损 ≤ 账户 risk_per_trade_max。

        止损距离 d 默认取 StopLossManager 入场式止损同一口径
        (stop_loss_percent)，避免双套止损价口径；2026-11-24: 开仓使用
        ATR/结构止损时传入实际止损距离 (stop_distance) 按真实风险核验。
        预期亏损按真实名义计算（张数 × ctVal × 价格，经
        ExchangeClient.calculate_notional_usdt）；合约规格不可用时回退旧公式
        （amount×price×d，张数当 BTC 数量，高估亏损 → 保守方向）。余额无效/
        获取失败时跳过反查（不阻断开仓，与回撤总闸的"跳过"语义一致；此时风险
        由止损单本身兜底）。

        Args:
            price: 当前入场价格。
            amount: 原始可开合约数（张）。
            stop_distance: 可选的实际止损距离 (entry 的百分比, 0~1)。
                None/≤0 → 默认 stop_loss_percent（零回归）。

        Returns:
            反查后的合约数（张）；未触发反查时原样返回 amount。
        """
        d = self.config.stop_loss.stop_loss_percent
        if stop_distance is not None and stop_distance > 0:
            d = stop_distance
        if d <= 0 or price <= 0 or amount <= 0:
            return amount
        try:
            balance = await self._exchange.get_balance()
        except Exception as e:
            logger.warning("[开仓] 风险反查: 余额获取失败，跳过反查: %s", e)
            return amount
        if balance <= 0:
            return amount
        max_loss = balance * self.config.trading.risk_per_trade_max
        try:
            # 真实名义（张数 → USDT，走 spec.notional_usdt 的 ctVal 换算）
            notional = self._exchange.calculate_notional_usdt(amount, price)
            expected_loss = notional * d
            if expected_loss <= max_loss:
                return amount
            # 缩仓到风险上限：单张名义 = 总名义 / 张数（上方已保证 amount > 0）
            notional_per_unit = notional / amount
            shrunk = float(f"{max_loss / (notional_per_unit * d):.4f}")
        except (RuntimeError, ValueError) as e:
            # 合约规格不可用：回退旧公式（张数当 BTC 数量，高估亏损 → 保守方向）
            logger.warning("[开仓][风险反查] 合约规格不可用，回退旧公式（保守）: %s", e)
            expected_loss = amount * price * d
            if expected_loss <= max_loss:
                return amount
            shrunk = float(f"{max_loss / (price * d):.4f}")
        logger.warning(
            "[开仓][风险反查] 止损距离 %.2f%% 下预期亏损 %.2f USDT 超过账户 "
            "%.0f%% (%.2f USDT)，仓位 %s → %s 张",
            d * 100,
            expected_loss,
            self.config.trading.risk_per_trade_max * 100,
            max_loss,
            amount,
            shrunk,
        )
        return shrunk

    async def _maybe_trend_follow(
        self, market_data: Dict[str, Any], current_price: float
    ) -> Optional[ExecutionResult]:
        """趋势跟踪独立通道 (2026-11-25 / 模块 0, 顺势入场)。

        触发 (多空对称, 口径与回放工具 trend_replay.trigger_at 一致):
        - 空: trend_direction=="down" (SMA10/20 1h) 且 24h 涨跌幅 ≤ -change_pct
          且 RSI(1h) ≥ short_rsi_floor (防末端追空)
        - 多: trend_direction=="up" 且 24h 涨跌幅 ≥ +change_pct
          且 RSI(1h) ≤ long_rsi_ceil (防末端追多)
        止损: 24h 摆动点 ∓ 0.5×ATR(1h), 距离上限 2.5%; 10R 安全止盈。
        让利润奔跑由追踪止损承接 (StopLossManager trailing, Task 4)。
        回放依据: 11-13→11-25 真实数据 7 笔 +6.34R (修正后基线)。
        绕过 AI 置信度门禁, 独立规则 (与高潮做空/超卖抄底通道同模式)。
        """
        cfg = self.config.trading
        if not cfg.trend_follow_enabled:
            return None
        if not current_price or current_price <= 0:
            return None
        # 无持仓 (调用点已守卫, 此处防御性再查)
        if self.position_manager.has_position():
            return None

        technical = market_data.get("technical") or {}
        trend_direction = technical.get("trend_direction", "neutral")
        rsi = float(technical.get("rsi", 50.0) or 50.0)
        atr_percent = float(technical.get("atr_percent", 0.0) or 0.0)
        change_percent = float(market_data.get("change_percent", 0.0) or 0.0)

        if trend_direction == "down" and (
            change_percent <= -cfg.trend_follow_change_pct
        ):
            if rsi < cfg.trend_follow_short_rsi_floor:
                logger.info(
                    "[趋势跟踪] 跳过(RSI(1h)=%.1f < %.0f 末端禁空) "
                    "trend=%s 24h涨跌=%.2f%%",
                    rsi,
                    cfg.trend_follow_short_rsi_floor,
                    trend_direction,
                    change_percent,
                )
                return None
            side = "short"
        elif trend_direction == "up" and (
            change_percent >= cfg.trend_follow_change_pct
        ):
            if rsi > cfg.trend_follow_long_rsi_ceil:
                logger.info(
                    "[趋势跟踪] 跳过(RSI(1h)=%.1f > %.0f 末端禁多) "
                    "trend=%s 24h涨跌=%.2f%%",
                    rsi,
                    cfg.trend_follow_long_rsi_ceil,
                    trend_direction,
                    change_percent,
                )
                return None
            side = "long"
        else:
            return None

        # 空侧需要做空能力
        if side == "short" and not cfg.allow_short_selling:
            logger.info(
                "[趋势跟踪] 跳过(空头条件满足但做空未启用 ALLOW_SHORT_SELLING=false)"
            )
            return None

        high_history = market_data.get("high_history") or []
        low_history = market_data.get("low_history") or []
        if len(high_history) < 24 or len(low_history) < 24:
            logger.info(
                "[趋势跟踪] 跳过(1h 高低点数据不足: %d/%d < 24)",
                len(high_history),
                len(low_history),
            )
            return None

        # 2026-11-26 P1-7: HTF(4h) 对齐——高级别趋势与入场方向一致才入场。
        # 11-25 复盘: T2/T3 入场时 HTF=sideways (震荡), 趋势通道开空后仅
        # 存活数分钟。SMA10/20 口径与 AI 层 HTF 结构判定同向;
        # 数据不足 (1h < 84 根) → fail-open + WARNING (其余门禁仍在,
        # 数据降级不应让整个通道静默死亡)。
        htf = "unknown"
        if cfg.trend_follow_require_htf_alignment:
            htf = self._htf_trend_direction(market_data.get("price_history") or [])
            if htf == "unknown":
                logger.warning(
                    "[趋势跟踪] HTF 对齐检查数据不足 (需 ≥84 根 1h 收盘), "
                    "本轮放行 (其余门禁仍生效)"
                )
            elif (side == "short" and htf != "down") or (
                side == "long" and htf != "up"
            ):
                logger.info("[趋势跟踪] 跳过(HTF(4h)=%s 与方向 %s 不对齐)", htf, side)
                return None

        # 2026-11-26 P1-7: 端点禁追——价格在 24h 极值内侧 x% 内 (区间末端
        # 拐头区) 跳过; 突破极值之外 (新低点/新高点) 是趋势延续, 放行。
        # 11-25 复盘: T2 入场 57,421 距 24h 低点 0.04% (区间末端), RSI≈24,
        # 随后反弹; 三笔全亏。三重区内 (极值内侧) 禁止, 区外允许。
        extreme_pct = cfg.trend_follow_extreme_distance_pct
        if extreme_pct > 0:
            if side == "short":
                low_24h = min(low_history[-24:])
                if low_24h <= current_price < low_24h * (1 + extreme_pct):
                    logger.info(
                        "[趋势跟踪] 跳过(端点禁追: 价 %.1f 在 24h 低点 %.1f "
                        "内侧 %.2f%% 区间, 区间末端不追空)",
                        current_price,
                        low_24h,
                        extreme_pct * 100,
                    )
                    return None
            else:
                high_24h = max(high_history[-24:])
                if high_24h * (1 - extreme_pct) < current_price <= high_24h:
                    logger.info(
                        "[趋势跟踪] 跳过(端点禁追: 价 %.1f 在 24h 高点 %.1f "
                        "内侧 %.2f%% 区间, 区间末端不追多)",
                        current_price,
                        high_24h,
                        extreme_pct * 100,
                    )
                    return None

        # ---- 既有门禁 (顺序与 BUY/SHORT 分支一致) ----
        today = datetime.now().strftime("%Y-%m-%d")
        if self._drawdown_status is not None and self._drawdown_status.halted:
            logger.info(
                "[趋势跟踪] 技术条件满足(%s) 但回撤总闸生效中 → 跳过 (回撤 %.1f%%)",
                side,
                self._drawdown_status.drawdown * 100,
            )
            return None
        cooldown = cfg.post_close_cooldown_minutes
        if cooldown > 0 and self.position_manager.is_in_post_close_cooldown(cooldown):
            logger.info("[趋势跟踪] 技术条件满足(%s) 但处于平仓后冷却期 → 跳过", side)
            return None
        daily_limit = cfg.daily_open_limit
        if daily_limit > 0 and self._daily_open_counts.get(today, 0) >= daily_limit:
            logger.info(
                "[趋势跟踪] 技术条件满足(%s) 但当日开仓数已达上限(%d) → 跳过",
                side,
                daily_limit,
            )
            return None
        if self._trend_follow_counts.get(today, 0) >= cfg.trend_follow_daily_limit:
            logger.info(
                "[趋势跟踪] 技术条件满足(%s) 但本通道今日已触发 %d 次 (上限 %d) → 跳过",
                side,
                self._trend_follow_counts.get(today, 0),
                cfg.trend_follow_daily_limit,
            )
            return None

        # ---- 止损价: 24h 摆动点 ∓ 0.5×ATR(1h), 距离上限 max_stop_pct ----
        # atr_percent 为 0~1 比率 (见 utils/technical/volatility.py), 直接乘价格得 ATR 绝对值
        atr_abs = atr_percent * current_price if atr_percent > 0 else 0.0
        if side == "short":
            swing = max(high_history[-24:])
            stop = min(
                swing + cfg.trend_follow_stop_atr_buffer * atr_abs,
                current_price * (1 + cfg.trend_follow_max_stop_pct),
            )
            if stop <= current_price:  # 摆动点已低于入场 → 取上限距离
                stop = current_price * (1 + cfg.trend_follow_max_stop_pct)
            tp = current_price - cfg.trend_follow_safety_tp_r * (stop - current_price)
        else:
            swing = min(low_history[-24:])
            stop = max(
                swing - cfg.trend_follow_stop_atr_buffer * atr_abs,
                current_price * (1 - cfg.trend_follow_max_stop_pct),
            )
            if stop >= current_price:  # 摆动点已高于入场 → 取上限距离
                stop = current_price * (1 - cfg.trend_follow_max_stop_pct)
            tp = current_price + cfg.trend_follow_safety_tp_r * (current_price - stop)

        logger.warning(
            "[趋势跟踪] 独立通道触发: %s 入场=%.1f trend=%s 24h涨跌=%.2f%% "
            "RSI(1h)=%.1f 止损=%.2f 安全止盈=%.2f (半仓)",
            side,
            current_price,
            trend_direction,
            change_percent,
            rsi,
            stop,
            tp,
        )
        opened = await self._open_position(
            current_price,
            size_factor=cfg.trend_follow_position_factor,
            side=side,
            atr_percent=atr_percent if atr_percent > 0 else None,
            stop_price_override=stop,
            tp_price_override=tp,
            origin="trend",
        )
        if opened:
            self._trend_follow_counts[today] = (
                self._trend_follow_counts.get(today, 0) + 1
            )
            self._daily_open_counts[today] = self._daily_open_counts.get(today, 0) + 1
            self._persist_daily_counts()
            return ExecutionResult(
                "open_trend_follow",
                f"price={current_price},side={side},stop={stop:.2f},tp={tp:.2f}",
            )
        return None

    def _calculate_take_profit_price(
        self,
        entry_price: float,
        amount: float,
        stop_distance: Optional[float] = None,
        side: str = "long",
    ) -> float:
        """止盈价计算（P1-3，standard bot 1-2R 止盈单；2026-11-24 多空双向）。

        TP 距离 = 止损距离 × max(take_profit_rr_multiple, take_profit_min_rr_ratio)
        （R/R 下限不变式复用既有 take_profit_min_rr_ratio，默认 2R）。
        2026-11-24: 止损距离优先取本次开仓的实际止损距离 (ATR/结构止损),
        None/≤0 → 默认 stop_loss_percent；side="short" 时止盈价在入场价下方。
        take_profit_rr_multiple <= 0（禁用）或名义低于 take_profit_min_notional
        时返回 0.0；名义计算失败 → fail-open（照挂，默认阈值 0 本就不拦）。
        """
        mult = self.config.stop_loss.take_profit_rr_multiple
        if mult <= 0 or entry_price <= 0 or amount <= 0:
            return 0.0
        stop_dist = self.config.stop_loss.stop_loss_percent
        if stop_distance is not None and stop_distance > 0:
            stop_dist = stop_distance
        tp_dist = stop_dist * max(mult, self.config.stop_loss.take_profit_min_rr_ratio)
        try:
            notional = self._exchange.calculate_notional_usdt(amount, entry_price)
            if notional < self.config.stop_loss.take_profit_min_notional:
                logger.info(
                    f"[止盈单] 名义 {notional:.2f} USDT 低于下限 "
                    f"{self.config.stop_loss.take_profit_min_notional:.2f}，"
                    "不挂止盈单（仅止损单）"
                )
                return 0.0
        except (RuntimeError, ValueError, AttributeError) as e:
            logger.warning("[止盈单] 名义计算不可用，跳过年名义检查 (fail-open): %s", e)
        if side == "short":
            return entry_price * (1 - tp_dist)
        return entry_price * (1 + tp_dist)

    async def _open_position(
        self,
        price: float,
        size_factor: float = 1.0,
        side: str = "long",
        atr_percent: Optional[float] = None,
        stop_price_override: Optional[float] = None,
        tp_price_override: Optional[float] = None,
        origin: str = "ai",
    ) -> bool:
        """开仓 - 根据余额动态计算交易量 (2026-11-24: 多空双向)

        止损保护：如果止损单创建失败，立即市价平仓，不允许无止损持仓。

        Args:
            price: 当前价格
            size_factor: 仓位缩仓系数 (0,1]，超卖抄底/高潮做空独立通道用 0.5 半仓。
                1.0=不缩仓（默认，零回归）。
            side: "long" (默认, 零回归) 或 "short"
            atr_percent: 开仓时刻 ATR 百分比 (0~1)。传入时止损距离取
                max(默认, clamp(ATR, 0.3%, 5%))——15m 级别的 wick 行情下
                0.5% 固定止损会被瞬间扫掉 (2026-11-24 11:03 抄底回放)。
            stop_price_override: 结构止损价 (高潮做空通道传入 R/R 计算器的
                摆动止损), 传入时优先于 ATR/默认止损。
            tp_price_override: 结构止盈价 (同上, 传入时优先于 RR 倍数止盈)。
            origin: 开仓来源 (trend/oversold/climax/ai, 2026-11-26 P0-2
                反手保护用, 持久化跨重启)。

        Returns:
            是否成功开仓 (订单创建成功, 含 TEST_MODE 模拟单)。
        """
        logger.info(f"[开仓] 开始开仓流程, 当前价格: {price}, 方向: {side}")

        live_allowed, reason = self.config.check_live_trading_preconditions()
        if not live_allowed:
            logger.warning(f"[实盘闸门] 拒绝开仓: {reason}")
            record_live_guard_block()
            return False

        # P1 回撤总闸纵深防线（周期级检查之外的兜底）
        if self._drawdown_status is not None and self._drawdown_status.halted:
            logger.warning(
                "[开仓] 回撤总闸生效，拒绝新开仓（回撤 %.1f%%）",
                self._drawdown_status.drawdown * 100,
            )
            return False

        amount = await self._exchange.calculate_max_contracts(
            price, self.config.exchange.leverage
        )

        if amount <= 0:
            logger.warning("[开仓] 无法计算有效交易量，取消开仓")
            return False

        # 2026-11 仓位缩仓系数 (超卖抄底/高潮做空独立通道半仓等场景)
        if 0 < size_factor < 1:
            amount *= size_factor
            logger.info(f"[开仓] 仓位缩仓系数 {size_factor:.2f} → {amount} 张")

        # P1 单笔风险反查：止损触发预期亏损 ≤ 账户 10%（超限缩仓，缩到最小 1 手以下则放弃）
        # 2026-11-24: ATR/结构止损时按实际止损距离核验
        est_stop_distance: Optional[float] = None
        if stop_price_override and stop_price_override > 0:
            if side == "long":
                est_stop_distance = (
                    (price - stop_price_override) / price
                    if stop_price_override < price
                    else None
                )
            else:
                est_stop_distance = (
                    (stop_price_override - price) / price
                    if stop_price_override > price
                    else None
                )
        if est_stop_distance is None and atr_percent:
            atr_clamped = max(0.003, min(float(atr_percent), 0.05))
            est_stop_distance = max(
                self.config.stop_loss.stop_loss_percent, atr_clamped
            )
        amount = await self._apply_risk_backcheck(
            price,
            amount,
            est_stop_distance if est_stop_distance and est_stop_distance > 0 else None,
        )

        # 张数截断（ROUND_FLOOR 到 lotSz）：以真实张数下单；截断后低于最小张数
        # 则取消开仓（保守方向）。规格不可用时保持修正前行为（不截断，由下方
        # amount < 0.01 检查兜底，绝不放大仓位）。
        try:
            amount = self._exchange.normalize_order_size(amount)
        except ValueError:
            logger.warning("[开仓] 张数截断后低于最小张数，取消开仓 (原 %.4f)", amount)
            return False
        except RuntimeError:
            logger.warning("[开仓] 合约规格不可用，跳过张数截断（保守回退）")

        if amount < 0.01:
            logger.warning(
                "[开仓] 风险反查后仓位 %.4f 张 < 最小 0.01 张，取消开仓", amount
            )
            return False

        logger.info(
            f"[开仓] 计算可开合约数: {amount} 张 "
            f"(杠杆: {self.config.exchange.leverage}x, 方向: {side})"
        )

        # 2026-11-24: 方向感知开仓方向 (多=buy, 空=sell)
        open_side = "buy" if side == "long" else "sell"
        order_id = await self._exchange.create_order(
            symbol=self.config.exchange.symbol,
            side=open_side,
            amount=amount,
            price=None,
        )

        if not order_id:
            logger.error("[开仓] 开仓订单创建失败，取消后续操作")
            return False

        # TEST_MODE 模拟订单检测
        from ..exchange.client import ExchangeClient

        if ExchangeClient.is_simulated_order(order_id):
            logger.info(
                f"[模拟交易] ✅ TEST_MODE模拟开仓成功: "
                f"价格={price}, 数量={amount}张, 方向={side}, "
                f"杠杆={self.config.exchange.leverage}x, 模拟订单ID={order_id}"
            )
            logger.info(
                f"[模拟交易] 提示: 切换实盘需设置 TEST_MODE=false + "
                f"REAL_TRADING_CONFIRMED=true + RUNTIME_ENVIRONMENT=prod"
            )
            return True

        logger.info(f"[开仓] 订单创建成功: 订单ID={order_id}")

        self.position_manager.update_position(
            amount, price, self.config.exchange.symbol, side=side, origin=origin
        )

        # 2026-11-24: 方向感知止损价 (多=下方, 空=上方)
        if side == "long":
            stop_price = (
                stop_price_override
                if stop_price_override and stop_price_override > 0
                else self.position_manager.calculate_stop_price(
                    price, dynamic_atr_percent=atr_percent
                )
            )
        else:
            stop_price = (
                stop_price_override
                if stop_price_override and stop_price_override > 0
                else self.position_manager.calculate_short_stop_price(
                    price, dynamic_atr_percent=atr_percent
                )
            )
        if side == "long":
            actual_stop_distance = max((price - stop_price) / price, 0.0)
        else:
            actual_stop_distance = max((stop_price - price) / price, 0.0)
        logger.info(
            f"[止损计算] 入场价={price}, 止损价={stop_price:.1f}, 方向={side} "
            f"(止损距离 {actual_stop_distance * 100:.2f}%, 由PositionManager统一计算)"
        )

        # 2026-11-24: 方向感知止损方向 (多仓止损=sell, 空仓止损=buy)
        stop_side = "sell" if side == "long" else "buy"
        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self.config.exchange.symbol,
            side=stop_side,
            amount=amount,
            stop_price=stop_price,
        )

        if stop_order_id:
            # 2026-11-25: 锁定初始止损价 (追踪止损 R 基准, 幂等; 须在
            # set_stop_order 持久化前写入, 随同一次 save_position 落盘)
            self.position_manager.set_initial_stop(stop_price)
            self.position_manager.set_stop_order(stop_order_id, stop_price)
            logger.info(
                f"[开仓] 开仓完成 - 价格:{price}, 数量:{amount}张, "
                f"止损:{stop_price}, 方向:{side}"
            )
            # P1-3 止盈单（standard bot）：止损单就绪后挂 1-2R 止盈，
            # 交易所侧由止损/止盈单兜底仓位。失败不回滚仓位（止损单兜底，
            # 安全不变式保持）。数量与止损单同一截断值（同一 amount）。
            # 2026-11-24: 方向感知 (空仓止盈=buy, 在入场价下方) + 结构止盈可覆盖
            if tp_price_override and tp_price_override > 0:
                tp_price = tp_price_override
            else:
                tp_price = self._calculate_take_profit_price(
                    price,
                    amount,
                    stop_distance=(
                        actual_stop_distance if actual_stop_distance > 0 else None
                    ),
                    side=side,
                )
            if tp_price > 0:
                tp_side = "buy" if side == "short" else "sell"
                try:
                    tp_order_id = await self._exchange.create_take_profit(
                        symbol=self.config.exchange.symbol,
                        side=tp_side,
                        amount=amount,
                        take_profit_price=tp_price,
                    )
                except Exception as e:
                    logger.warning(f"[止盈保护] 止盈单创建异常（止损单兜底）: {e}")
                    tp_order_id = None
                if tp_order_id:
                    self.position_manager.set_take_profit_order(tp_order_id, tp_price)
                    logger.info(
                        "[开仓] 止盈单已创建: ID=%s, 止盈价:%s (方向=%s, P1-3)",
                        tp_order_id,
                        tp_price,
                        side,
                    )
                else:
                    logger.warning(
                        "[止盈保护] 止盈单创建失败: 仓位由止损单兜底，不回滚"
                    )
        else:
            logger.critical(
                f"[止损保护] 止损单创建失败！立即市价平仓保护资金安全。"
                f"开仓订单={order_id}, 数量={amount}张, 方向={side}"
            )
            try:
                # 2026-11-24: 方向感知紧急平仓 (空仓平仓=buy)
                close_side = "buy" if side == "short" else "sell"
                close_order_id = await self._exchange.create_order(
                    symbol=self.config.exchange.symbol,
                    side=close_side,
                    amount=amount,
                    price=None,
                )
                if close_order_id:
                    logger.info(f"[止损保护] 紧急平仓成功: {close_order_id}")
                else:
                    logger.critical(
                        "[止损保护] 紧急平仓也失败！需要人工介入检查持仓状态！"
                    )
            except Exception as e:
                logger.critical(
                    f"[止损保护] 紧急平仓异常: {e}！需要人工介入检查持仓状态！"
                )
            finally:
                self.position_manager.clear_position()
            # 止损单创建失败 → 仓位已紧急平掉, 视为开仓未成功
            return False

        # 正常路径: 开仓单 + 止损单就绪, 持仓有效
        return True

    async def _get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return None
        return await self._stop_loss_manager.get_existing_stop_order_id()

    async def _update_stop_loss(
        self, current_price: float, atr_percent: float = 0.0
    ) -> None:
        """更新止损订单（委托给StopLossManager）

        atr_percent: 0~1 比率的 ATR(1h), 供追踪止损的 2R 追踪段使用
        (0 → 追踪段关闭, 保本段仍可用; 旧调用不传零回归)。
        """
        if self._stop_loss_manager is None:
            return
        await self._stop_loss_manager.update_stop_loss(
            current_price, atr_percent=atr_percent
        )

    async def _create_stop_loss_with_retry(
        self,
        amount: float,
        stop_price: float,
        current_price: float,
        max_retries: int = 2,
    ) -> Optional[str]:
        """创建止损单（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return None
        return await self._stop_loss_manager.create_stop_loss_with_retry(
            amount, stop_price, current_price, max_retries
        )

    async def _close_position(self, price: float) -> None:
        """平仓"""
        if not self.position_manager.has_position():
            logger.warning("[平仓] 无持仓，跳过平仓")
            return

        live_allowed, reason = self.config.check_live_trading_preconditions()
        if not live_allowed:
            logger.warning(f"[实盘闸门] 拒绝平仓: {reason}")
            record_live_guard_block()
            return

        position = self.position_manager.position
        if position is None:
            logger.error("[平仓] 数据不一致: has_position=True 但 position 为 None")
            return

        amount = position.amount
        logger.info(
            f"[平仓] 开始平仓流程, 当前价格: {price}, 数量: {amount}张, "
            f"方向: {position.side}"
        )

        # 2026-11-24: 方向感知平仓 (空仓平仓=buy, 多仓平仓=sell)
        close_side = "buy" if position.side == "short" else "sell"
        order_id = await self._exchange.create_order(
            symbol=self.config.exchange.symbol,
            side=close_side,
            amount=amount,
            price=None,
        )

        from ..exchange.client import ExchangeClient

        if ExchangeClient.is_simulated_order(order_id):
            logger.info(f"[平仓] TEST_MODE 模拟平仓: ID={order_id}, 跳过状态清理")
            return

        logger.info(f"[平仓] 平仓订单创建成功: 订单ID={order_id}")

        if self.position_manager.stop_order_id:
            logger.info(f"[平仓] 取消旧止损单: {self.position_manager.stop_order_id}")
            try:
                cancel_result = await self._exchange.cancel_algo_order(
                    self.position_manager.stop_order_id, self.config.exchange.symbol
                )
                cancel_success, cancel_reason = cancel_result
                if cancel_success:
                    logger.info("[平仓] 止损单取消成功")
                elif cancel_reason == "already_gone":
                    logger.info("[平仓] 止损单已不存在(可能已触发)")
                else:
                    logger.warning("[平仓] 取消止损单失败")
            except Exception as e:
                logger.warning(f"[平仓] 取消止损单异常: {e}")

        # P1-3: 同步取消旧止盈单（与止损单同一 cancel_algo_order 路径）
        if self.position_manager.take_profit_order_id:
            logger.info(
                f"[平仓] 取消旧止盈单: {self.position_manager.take_profit_order_id}"
            )
            try:
                cancel_result = await self._exchange.cancel_algo_order(
                    self.position_manager.take_profit_order_id,
                    self.config.exchange.symbol,
                )
                cancel_success, cancel_reason = cancel_result
                if cancel_success:
                    logger.info("[平仓] 止盈单取消成功")
                elif cancel_reason == "already_gone":
                    logger.info("[平仓] 止盈单已不存在(可能已触发)")
                else:
                    logger.warning("[平仓] 取消止盈单失败")
            except Exception as e:
                logger.warning(f"[平仓] 取消止盈单异常: {e}")

        self.position_manager.clear_position()
        # P0-2: 盖平仓时间戳（平仓后冷却门禁，重启可恢复）
        self.position_manager.mark_last_close()
        logger.info(f"[平仓] 平仓完成 - 价格:{price}, 数量:{amount}张")

    async def cleanup(self) -> None:
        """清理资源"""
        logger.info("清理资源...")
        if hasattr(self, "_exchange"):
            await self._exchange.cleanup()

    async def stop(self) -> None:
        """停止机器人"""
        self._running = False
        logger.info("交易机器人停止")


async def main():
    """入口"""
    import logging

    logging.basicConfig(level=logging.INFO)

    bot = TradingBot()
    try:
        await bot.run()
    except KeyboardInterrupt:
        await bot.stop()


if __name__ == "__main__":
    asyncio.run(main())
