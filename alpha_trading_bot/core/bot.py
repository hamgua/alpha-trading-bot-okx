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
from typing import Any, Dict, Optional

from ..config.models import Config
from ..utils.observability import record_live_guard_block
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

        # 计算止损价
        stop_price = self.position_manager.calculate_stop_price(current_price)

        logger.info(
            f"[止损恢复] 创建止损单: 止损价={stop_price}, 数量={position.amount}"
        )

        try:
            stop_order_id = await self._exchange.create_stop_loss(
                symbol=self.config.exchange.symbol,
                side="sell",
                amount=position.amount,
                stop_price=stop_price,
            )
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
        tp_price = self._calculate_take_profit_price(entry_price, position.amount)
        if tp_price <= 0:
            return

        logger.warning(
            f"[止盈恢复] 有持仓但无止盈单，重建: 止盈价={tp_price}, 数量={position.amount}"
        )
        try:
            tp_order_id = await self._exchange.create_take_profit(
                symbol=self.config.exchange.symbol,
                side="sell",
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

        logger.info(f"[交易决策] 当前价格: {current_price}")

        # 4. 获取AI信号
        signal: Optional[str] = None
        try:
            logger.info("[AI信号] 正在获取交易信号...")
            signal = await self._ai_client.get_signal(market_data)
            signal = SignalProcessor.process(signal)
            logger.info(f"[AI信号] 原始信号: {signal}")

            # 执行层置信度门禁（P0-1）：取最终置信度（0-1），解析失败→None（门禁不生效）
            final_conf_raw = market_data.get("final_confidence")
            try:
                final_confidence: Optional[float] = (
                    float(final_conf_raw) if final_conf_raw is not None else None
                )
            except (TypeError, ValueError):
                final_confidence = None

            # 5. 处理信号
            execution_result = await self._execute_signal(
                signal, current_price, has_position, final_confidence
            )

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

    async def _execute_signal(
        self,
        signal: str,
        current_price: float,
        has_position: bool,
        final_confidence: Optional[float] = None,
    ) -> ExecutionResult:
        """执行信号

        final_confidence: 信号最终置信度（0-1）。非 None 时执行层置信度门禁生效：
        - BUY + 无持仓: 低于 min_confidence_open → 禁止开仓（P0-1）
        - SELL + 有持仓: 低于 min_confidence_close → 禁止平仓（仓位由止损单保护）
        None（旧 3 参调用路径）：门禁不生效并 WARNING 提示（零回归）。
        """
        logger.info(
            f"[信号执行] 开始处理信号: {signal}, 当前价格: {current_price}, "
            f"持仓状态: {'有持仓' if has_position else '无持仓'}"
        )

        # 执行层置信度门禁（2026-10-08 手续费出血修复 / P0-1）：
        # 低置信度往返单的成本 ≈ 11.5bp，而 54-67% 置信度信号的毛利 ≈ 0，
        # 只放行有把握（>= 门禁）的开/平仓，其余交给止损/止盈单管理。
        if final_confidence is None:
            if signal in ("BUY", "SELL"):
                logger.warning(
                    "[信号执行] 未提供置信度 (final_confidence=None)，"
                    "置信度门禁本轮不生效（旧调用路径）"
                )
        elif signal == "BUY" and not has_position:
            min_conf = self.config.trading.min_confidence_open
            if min_conf > 0 and final_confidence < min_conf:
                logger.info(
                    "[信号执行] BUY信号 + 置信度 %.2f < 门禁 %.2f -> 禁止开仓 "
                    "(P0-1 置信度门禁)",
                    final_confidence,
                    min_conf,
                )
                return ExecutionResult(
                    "blocked_low_confidence",
                    f"buy_conf={final_confidence:.2f}<min={min_conf:.2f}",
                )
        elif signal == "SELL" and has_position:
            min_conf = self.config.trading.min_confidence_close
            if min_conf > 0 and final_confidence < min_conf:
                logger.info(
                    "[信号执行] SELL信号 + 置信度 %.2f < 门禁 %.2f -> 禁止平仓 "
                    "(P0-1 置信度门禁，仓位由止损单保护)",
                    final_confidence,
                    min_conf,
                )
                return ExecutionResult(
                    "blocked_low_confidence",
                    f"sell_conf={final_confidence:.2f}<min={min_conf:.2f}",
                )

        if signal == "BUY":
            if not has_position:
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
                logger.info("[信号执行] BUY信号 + 无持仓 -> 执行开仓")
                await self._open_position(current_price)
                return ExecutionResult("open_long", f"price={current_price}")
            logger.info("[信号执行] BUY信号 + 有持仓 -> 更新止损")
            await self._update_stop_loss(current_price)
            return ExecutionResult("update_stop")

        if signal == "HOLD":
            if has_position:
                logger.info("[信号执行] HOLD信号 + 有持仓 -> 更新止损")
                await self._update_stop_loss(current_price)
                return ExecutionResult("update_stop")
            logger.info("[信号执行] HOLD信号 + 无持仓 -> 不操作")
            logger.info(
                "[机会评估] 当前为HOLD信号，系统持续监控中。如需更多交易机会，可考虑: "
                "1)缩短CYCLE_MINUTES 2)切换AI_FUSION模式 3)调整INVESTMENT_TYPE=aggressive"
            )
            return ExecutionResult("none")

        if signal == "SELL":
            if has_position:
                logger.info("[信号执行] SELL信号 + 有持仓 -> 执行平仓")
                await self._close_position(current_price)
                return ExecutionResult("close", f"price={current_price}")
            logger.info("[信号执行] SELL信号 + 无持仓 -> 不操作")
            return ExecutionResult("none")

        logger.warning(f"[信号执行] 未知信号: {signal}")
        return ExecutionResult("error", f"unknown_signal={signal}")

    async def _apply_risk_backcheck(self, price: float, amount: float) -> float:
        """单笔风险反查（P1）：止损触发时的预期亏损 ≤ 账户 risk_per_trade_max。

        止损距离 d 取 StopLossManager 入场式止损同一口径（stop_loss_percent），
        避免双套止损价口径。预期亏损按真实名义计算（张数 × ctVal × 价格，
        经 ExchangeClient.calculate_notional_usdt）；合约规格不可用时回退旧公式
        （amount×price×d，张数当 BTC 数量，高估亏损 → 保守方向）。余额无效/
        获取失败时跳过反查（不阻断开仓，与回撤总闸的"跳过"语义一致；此时风险
        由止损单本身兜底）。

        Args:
            price: 当前入场价格。
            amount: 原始可开合约数（张）。

        Returns:
            反查后的合约数（张）；未触发反查时原样返回 amount。
        """
        d = self.config.stop_loss.stop_loss_percent
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

    def _calculate_take_profit_price(self, entry_price: float, amount: float) -> float:
        """计算多头止盈价（P1-3，standard bot 1-2R 止盈单）。

        TP 距离 = 止损距离 × max(take_profit_rr_multiple, take_profit_min_rr_ratio)
        （R/R 下限不变式复用既有 take_profit_min_rr_ratio，默认 2R）。
        take_profit_rr_multiple <= 0（禁用）或名义低于 take_profit_min_notional
        时返回 0.0；名义计算失败 → fail-open（照挂，默认阈值 0 本就不拦）。
        """
        mult = self.config.stop_loss.take_profit_rr_multiple
        if mult <= 0 or entry_price <= 0 or amount <= 0:
            return 0.0
        stop_dist = self.config.stop_loss.stop_loss_percent
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
        return entry_price * (1 + tp_dist)

    async def _open_position(self, price: float) -> None:
        """开仓 - 根据余额动态计算交易量

        止损保护：如果止损单创建失败，立即市价平仓，不允许无止损持仓。
        """
        logger.info(f"[开仓] 开始开仓流程, 当前价格: {price}")

        live_allowed, reason = self.config.check_live_trading_preconditions()
        if not live_allowed:
            logger.warning(f"[实盘闸门] 拒绝开仓: {reason}")
            record_live_guard_block()
            return

        # P1 回撤总闸纵深防线（周期级检查之外的兜底）
        if self._drawdown_status is not None and self._drawdown_status.halted:
            logger.warning(
                "[开仓] 回撤总闸生效，拒绝新开仓（回撤 %.1f%%）",
                self._drawdown_status.drawdown * 100,
            )
            return

        amount = await self._exchange.calculate_max_contracts(
            price, self.config.exchange.leverage
        )

        if amount <= 0:
            logger.warning("[开仓] 无法计算有效交易量，取消开仓")
            return

        # P1 单笔风险反查：止损触发预期亏损 ≤ 账户 10%（超限缩仓，缩到最小 1 手以下则放弃）
        amount = await self._apply_risk_backcheck(price, amount)

        # 张数截断（ROUND_FLOOR 到 lotSz）：以真实张数下单；截断后低于最小张数
        # 则取消开仓（保守方向）。规格不可用时保持修正前行为（不截断，由下方
        # amount < 0.01 检查兜底，绝不放大仓位）。
        try:
            amount = self._exchange.normalize_order_size(amount)
        except ValueError:
            logger.warning("[开仓] 张数截断后低于最小张数，取消开仓 (原 %.4f)", amount)
            return
        except RuntimeError:
            logger.warning("[开仓] 合约规格不可用，跳过张数截断（保守回退）")

        if amount < 0.01:
            logger.warning(
                "[开仓] 风险反查后仓位 %.4f 张 < 最小 0.01 张，取消开仓", amount
            )
            return

        logger.info(
            f"[开仓] 计算可开合约数: {amount} 张 (杠杆: {self.config.exchange.leverage}x)"
        )

        order_id = await self._exchange.create_order(
            symbol=self.config.exchange.symbol,
            side="buy",
            amount=amount,
            price=None,
        )

        if not order_id:
            logger.error("[开仓] 开仓订单创建失败，取消后续操作")
            return

        # TEST_MODE 模拟订单检测
        from ..exchange.client import ExchangeClient

        if ExchangeClient.is_simulated_order(order_id):
            logger.info(
                f"[模拟交易] ✅ TEST_MODE模拟开仓成功: "
                f"价格={price}, 数量={amount}张, 杠杆={self.config.exchange.leverage}x, "
                f"模拟订单ID={order_id}"
            )
            logger.info(
                f"[模拟交易] 提示: 切换实盘需设置 TEST_MODE=false + "
                f"REAL_TRADING_CONFIRMED=true + RUNTIME_ENVIRONMENT=prod"
            )
            return

        logger.info(f"[开仓] 订单创建成功: 订单ID={order_id}")

        self.position_manager.update_position(
            amount, price, self.config.exchange.symbol
        )

        stop_price = self.position_manager.calculate_stop_price(price)
        logger.info(
            f"[止损计算] 入场价={price}, 止损价={stop_price:.1f} (由PositionManager统一计算)"
        )

        stop_order_id = await self._exchange.create_stop_loss(
            symbol=self.config.exchange.symbol,
            side="sell",
            amount=amount,
            stop_price=stop_price,
        )

        if stop_order_id:
            self.position_manager.set_stop_order(stop_order_id, stop_price)
            logger.info(
                f"[开仓] 开仓完成 - 价格:{price}, 数量:{amount}张, 止损:{stop_price}"
            )
            # P1-3 止盈单（standard bot）：止损单就绪后挂 1-2R 止盈，
            # 交易所侧由止损/止盈单兜底仓位。失败不回滚仓位（止损单兜底，
            # 安全不变式保持）。数量与止损单同一截断值（同一 amount）。
            tp_price = self._calculate_take_profit_price(price, amount)
            if tp_price > 0:
                try:
                    tp_order_id = await self._exchange.create_take_profit(
                        symbol=self.config.exchange.symbol,
                        side="sell",
                        amount=amount,
                        take_profit_price=tp_price,
                    )
                except Exception as e:
                    logger.warning(f"[止盈保护] 止盈单创建异常（止损单兜底）: {e}")
                    tp_order_id = None
                if tp_order_id:
                    self.position_manager.set_take_profit_order(tp_order_id, tp_price)
                    logger.info(
                        "[开仓] 止盈单已创建: ID=%s, 止盈价:%s (R倍数=%.1f, P1-3)",
                        tp_order_id,
                        tp_price,
                        self.config.stop_loss.take_profit_rr_multiple,
                    )
                else:
                    logger.warning(
                        "[止盈保护] 止盈单创建失败: 仓位由止损单兜底，不回滚"
                    )
        else:
            logger.critical(
                f"[止损保护] 止损单创建失败！立即市价平仓保护资金安全。"
                f"开仓订单={order_id}, 数量={amount}张"
            )
            try:
                close_order_id = await self._exchange.create_order(
                    symbol=self.config.exchange.symbol,
                    side="sell",
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

    async def _get_existing_stop_order_id(self) -> Optional[str]:
        """查询交易所中现有的止损单ID（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return None
        return await self._stop_loss_manager.get_existing_stop_order_id()

    async def _update_stop_loss(self, current_price: float) -> None:
        """更新止损订单（委托给StopLossManager）"""
        if self._stop_loss_manager is None:
            return
        await self._stop_loss_manager.update_stop_loss(current_price)

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
        logger.info(f"[平仓] 开始平仓流程, 当前价格: {price}, 数量: {amount}张")

        order_id = await self._exchange.create_order(
            symbol=self.config.exchange.symbol,
            side="sell",
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
