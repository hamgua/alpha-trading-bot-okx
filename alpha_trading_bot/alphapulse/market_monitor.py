"""
AlphaPulse 市场监控系统
持续监控市场状态，实时计算技术指标
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from ..utils.technical import TechnicalIndicators
from .config import AlphaPulseConfig
from .data_manager import DataManager, IndicatorSnapshot, TrendDirection

logger = logging.getLogger(__name__)


@dataclass
class TechnicalIndicatorResult:
    """技术指标计算结果"""

    # 基础数据
    symbol: str
    timeframe: str
    timestamp: datetime

    # 价格数据
    current_price: float
    high_24h: float
    low_24h: float
    high_7d: float
    low_7d: float

    # 位置百分比
    price_position_24h: float  # 0-100%
    price_position_7d: float  # 0-100%

    # 技术指标
    atr: float = 0.0
    atr_percent: float = 0.0
    rsi: float = 50.0
    macd: float = 0.0
    macd_signal: float = 0.0
    macd_histogram: float = 0.0
    adx: float = 0.0
    plus_di: float = 0.0
    minus_di: float = 0.0
    bb_upper: float = 0.0
    bb_lower: float = 0.0
    bb_middle: float = 0.0
    bb_position: float = 50.0  # 0-100%

    # 趋势分析
    trend_direction: str = TrendDirection.UNKNOWN.value
    trend_strength: float = 0.0

    # 原始数据
    ohlcv_data: List[List] = field(default_factory=list)

    def to_indicator_snapshot(self) -> IndicatorSnapshot:
        """转换为指标快照"""
        return IndicatorSnapshot(
            timestamp=self.timestamp,
            symbol=self.symbol,
            timeframe=self.timeframe,
            current_price=self.current_price,
            high_24h=self.high_24h,
            low_24h=self.low_24h,
            high_7d=self.high_7d,
            low_7d=self.low_7d,
            price_position_24h=self.price_position_24h,
            price_position_7d=self.price_position_7d,
            atr=self.atr,
            atr_percent=self.atr_percent,
            rsi=self.rsi,
            macd=self.macd,
            macd_signal=self.macd_signal,
            macd_histogram=self.macd_histogram,
            adx=self.adx,
            plus_di=self.plus_di,
            minus_di=self.minus_di,
            bb_upper=self.bb_upper,
            bb_lower=self.bb_lower,
            bb_middle=self.bb_middle,
            bb_position=self.bb_position,
            trend_direction=self.trend_direction,
            trend_strength=self.trend_strength,
            ohlcv_data=self.ohlcv_data,
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "symbol": self.symbol,
            "timeframe": self.timeframe,
            "timestamp": self.timestamp.isoformat(),
            "current_price": self.current_price,
            "high_24h": self.high_24h,
            "low_24h": self.low_24h,
            "high_7d": self.high_7d,
            "low_7d": self.low_7d,
            "price_position_24h": self.price_position_24h,
            "price_position_7d": self.price_position_7d,
            "atr": self.atr,
            "atr_percent": self.atr_percent,
            "rsi": self.rsi,
            "macd": self.macd,
            "macd_signal": self.macd_signal,
            "macd_histogram": self.macd_histogram,
            "adx": self.adx,
            "plus_di": self.plus_di,
            "minus_di": self.minus_di,
            "bb_upper": self.bb_upper,
            "bb_lower": self.bb_lower,
            "bb_middle": self.bb_middle,
            "bb_position": self.bb_position,
            "trend_direction": self.trend_direction,
            "trend_strength": self.trend_strength,
        }


@dataclass
class SignalCheckResult:
    """信号检查结果"""

    should_trade: bool
    signal_type: str  # "buy", "sell", "hold"
    buy_score: float
    sell_score: float
    confidence: float
    triggers: List[str]  # 触发信号的原因
    indicator_result: TechnicalIndicatorResult
    message: str


class MarketMonitor:
    """
    市场监控系统

    功能:
    - 持续获取K线数据
    - 计算技术指标
    - 检测交易信号
    - 存储历史数据
    """

    # 单一分数交易信号配置（范围: -1.0 到 1.0）
    # 正值=偏多, 负值=偏空, 0=中性
    # BUY: score >= 0.3, SELL: score <= -0.3, HOLD: -0.3 < score < 0.3
    TRADE_SIGNALS = {
        # RSI: (RSI - 50) / 50 → -1 (极弱) 到 1 (极强)
        "rsi": {
            "weight": 0.20,
            "factor": lambda rsi: (rsi - 50) / 50,  # -1 到 1
        },
        # 布林带位置: (BB - 50) / 50 → -1 (底部) 到 1 (顶部)
        "bb_position": {
            "weight": 0.15,
            "factor": lambda bb: (bb - 50) / 50,  # -1 到 1
        },
        # MACD柱状图: 归一化到 -1 到 1
        "macd": {
            "weight": 0.15,
            "factor": lambda macd: max(-1, min(1, macd / 50)),  # 假设最大50
        },
        # ADX趋势强度: +ve 放大信号强度
        "adx": {
            "weight": 0.10,
            "factor": lambda adx: min(1, (adx - 20) / 30),  # 20以下=0, 50以上=1
        },
        # 24h价格位置: (Pos - 50) / 50 → -1 到 1
        "price_position_24h": {
            "weight": 0.20,
            "factor": lambda pos: (pos - 50) / 50,  # -1 到 1
        },
        # 7d价格位置: (Pos - 50) / 50 → -1 到 1
        "price_position_7d": {
            "weight": 0.10,
            "factor": lambda pos: (pos - 50) / 50,  # -1 到 1
        },
        # 波动率: 波动率越高，信号越可靠
        "volatility": {
            "weight": 0.10,
            "factor": lambda atr: min(1, atr / 1.0),  # 1%以上=1
        },
    }

    # 信号阈值配置
    BUY_THRESHOLD = 0.30  # 分数 >= 0.3 → BUY
    SELL_THRESHOLD = -0.30  # 分数 <= -0.3 → SELL

    def __init__(
        self,
        exchange_client,
        config: AlphaPulseConfig,
        data_manager=None,
        on_signal=None,
    ):
        """
        初始化市场监控系统

        Args:
            exchange_client: 交易所客户端
            config: AlphaPulse配置
            data_manager: 数据管理器（可选）
            on_signal: 信号回调函数（可选）
        """
        self.exchange_client = exchange_client
        self.config = config
        self.data_manager = data_manager or DataManager(
            max_ohlcv_bars=config.max_ohlcv_bars,
            max_indicator_history=config.max_indicator_history,
        )
        self.on_signal = on_signal  # 信号回调

        # 技术指标计算器
        self.tech_indicators = TechnicalIndicators()

        # 监控状态
        self._running = False
        self._monitor_task = None
        self._last_check_time = {}

        # 交易信号缓存（避免重复触发）
        self._last_signal_time = {}
        self._cooldown_seconds = config.cooldown_minutes * 60

        # 初始化交易对
        for symbol in config.symbols:
            asyncio.create_task(self.data_manager.initialize_symbol(symbol))

    async def start(self):
        """启动监控 - 增强版：防止重复启动"""
        # 双重检查防止重复启动
        if (
            self._running
            and self._monitor_task is not None
            and not self._monitor_task.done()
        ):
            logger.warning("MarketMonitor 已在运行，跳过重复启动")
            return

        self._running = True

        logger.info(
            f"MarketMonitor 已启动, 监控间隔: {self.config.monitor_interval}秒, "
            f"交易对: {self.config.symbols}"
        )

        # 启动监控任务
        self._monitor_task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        """停止监控"""
        self._running = False

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass

        await self.data_manager.cleanup()
        logger.info("MarketMonitor 已停止")

    async def _monitor_loop(self):
        """监控主循环"""
        while self._running:
            try:
                logger.info(
                    f"🔄 AlphaPulse 监控周期开始 (间隔: {self.config.monitor_interval}秒)"
                )

                for symbol in self.config.symbols:
                    logger.info(f"📊 开始监控: {symbol}")
                    await self._update_symbol(symbol)
                    await asyncio.sleep(1)  # 避免API请求过快

                logger.info(f"✅ AlphaPulse 监控周期完成，等待下一次...")

                # 等待下一次监控
                await asyncio.sleep(self.config.monitor_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"监控循环错误: {e}")
                await asyncio.sleep(5)  # 错误后短暂等待

    async def _update_symbol(self, symbol: str):
        """更新单个交易对数据"""
        try:
            logger.debug(f"📥 获取 {symbol} K线数据...")

            # 获取K线数据 (使用5分钟周期)
            ohlcv = await self.exchange_client.fetch_ohlcv(symbol, "5m", limit=100)

            if not ohlcv:
                logger.warning(f"⚠️ 获取K线数据失败: {symbol}")
                return

            logger.info(
                f"📥 {symbol} 获取到 {len(ohlcv)} 根K线, 最新价格: {ohlcv[-1][4]:.2f}"
            )

            # 更新数据管理器
            for bar in ohlcv:
                await self.data_manager.update_ohlcv(symbol, "5m", bar)

            # 计算技术指标
            indicator_result = await self._calculate_indicators(symbol, ohlcv)

            if indicator_result:
                # 保存指标快照
                snapshot = indicator_result.to_indicator_snapshot()
                await self.data_manager.update_indicator(symbol, snapshot)

                # 日志输出关键指标
                logger.info(
                    f"📊 {symbol} 指标: "
                    f"价格={indicator_result.current_price:.2f}, "
                    f"RSI={indicator_result.rsi:.1f}, "
                    f"BB位置={indicator_result.bb_position:.1f}%, "
                    f"MACD={indicator_result.macd_histogram:.4f}, "
                    f"ADX={indicator_result.adx:.1f}, "
                    f"24h位置={indicator_result.price_position_24h:.1f}%, "
                    f"趋势={indicator_result.trend_direction}"
                )

                # 检查交易信号
                signal_result = await self._check_signals(symbol, indicator_result)

                if signal_result:
                    if signal_result.should_trade:
                        logger.info(
                            f"🎯 {symbol} 信号: {signal_result.signal_type.upper()} "
                            f"(置信度: {signal_result.confidence:.2f}, 分数: BUY={signal_result.buy_score:.2f}/SELL={signal_result.sell_score:.2f})"
                        )
                    else:
                        logger.info(f"💤 {symbol} 无信号: {signal_result.message}")

                    # 调用回调函数（无论是否有有效信号，都更新检查时间）
                    if self.on_signal:
                        # 创建简化的信号对象供回调使用
                        class SimpleSignal:
                            def __init__(
                                self,
                                symbol,
                                signal_type,
                                confidence,
                                message,
                                execution_params=None,
                                ai_result=None,
                                market_data=None,
                            ):
                                self.symbol = symbol
                                self.signal_type = signal_type
                                self.confidence = confidence
                                self.reasoning = message
                                self.execution_params = execution_params or {}
                                self.ai_result = ai_result
                                self.market_data = market_data or {}

                        callback_signal = SimpleSignal(
                            symbol,
                            signal_result.signal_type,
                            signal_result.confidence,
                            signal_result.message,
                            market_data={"indicators": signal_result.indicator_result},
                        )
                        try:
                            self.on_signal(callback_signal)
                        except Exception as e:
                            logger.warning(f"⚠️ 信号回调执行失败: {e}")

        except Exception as e:
            logger.error(f"❌ 更新交易对数据失败 {symbol}: {e}")

    async def _calculate_indicators(
        self, symbol: str, ohlcv: List[List]
    ) -> Optional[TechnicalIndicatorResult]:
        """计算技术指标"""
        try:
            if len(ohlcv) < 50:
                logger.warning(f"K线数据不足: {symbol}, 仅有 {len(ohlcv)} 根")
                return None

            # 提取数据
            timestamps = [d[0] for d in ohlcv]
            opens = [d[1] for d in ohlcv]
            highs = [d[2] for d in ohlcv]
            lows = [d[3] for d in ohlcv]
            closes = [d[4] for d in ohlcv]
            volumes = [d[5] for d in ohlcv]

            current_price = closes[-1]

            # 获取价格区间
            price_range = await self.data_manager.get_price_range(symbol)
            high_24h = price_range["high_24h"]
            low_24h = price_range["low_24h"]
            high_7d = price_range["high_7d"]
            low_7d = price_range["low_7d"]

            # 计算位置百分比
            pos_24h = self.data_manager.get_price_position(
                current_price, high_24h, low_24h
            )
            pos_7d = self.data_manager.get_price_position(
                current_price, high_7d, low_7d
            )

            # 获取参数
            params = self.config.get_indicator_params()

            # 计算ATR (需要 high, low, close 分开的列表)
            atr_list = self.tech_indicators.calculate_atr(
                highs, lows, closes, period=params["atr_period"]
            )
            atr = atr_list[-1] if atr_list else 0
            atr_percent = (atr / current_price * 100) if current_price > 0 else 0

            # 计算RSI (返回列表，取最后一个值)
            rsi_list = self.tech_indicators.calculate_rsi(
                closes, period=params["rsi_period"]
            )
            rsi = rsi_list[-1] if rsi_list else 50.0

            # 计算MACD (返回三个列表，取最后一个值)
            macd_list, macd_signal_list, macd_hist_list = (
                self.tech_indicators.calculate_macd(
                    closes,
                    fast_period=params["macd_fast"],
                    slow_period=params["macd_slow"],
                    signal_period=params["macd_signal"],
                )
            )
            macd = macd_list[-1] if macd_list else 0.0
            macd_signal = macd_signal_list[-1] if macd_signal_list else 0.0
            macd_hist = macd_hist_list[-1] if macd_hist_list else 0.0

            # 计算ADX (返回列表，取最后一个值)
            adx_list = self.tech_indicators.calculate_adx(
                highs, lows, closes, period=params["adx_period"]
            )
            adx = adx_list[-1] if adx_list else 0.0
            plus_di = 0.0
            minus_di = 0.0

            # 计算布林带 (返回元组: (上轨, 中轨, 下轨))
            bb_upper_list, bb_middle_list, bb_lower_list = (
                self.tech_indicators.calculate_bollinger_bands(
                    closes, period=params["bb_period"], num_std=params["bb_std"]
                )
            )
            bb_upper = bb_upper_list[-1] if bb_upper_list else current_price
            bb_lower = bb_lower_list[-1] if bb_lower_list else current_price
            bb_middle = bb_middle_list[-1] if bb_middle_list else current_price

            # 计算布林带位置
            bb_position = (
                ((current_price - bb_lower) / (bb_upper - bb_lower) * 100)
                if bb_upper != bb_lower
                else 50.0
            )
            bb_position = max(0, min(100, bb_position))

            # 趋势分析
            trend_analysis = await self.data_manager.get_trend_analysis(
                symbol, "5m", 20
            )

            return TechnicalIndicatorResult(
                symbol=symbol,
                timeframe="5m",
                timestamp=datetime.now(),
                current_price=current_price,
                high_24h=high_24h,
                low_24h=low_24h,
                high_7d=high_7d,
                low_7d=low_7d,
                price_position_24h=pos_24h,
                price_position_7d=pos_7d,
                atr=atr,
                atr_percent=atr_percent,
                rsi=rsi,
                macd=macd,
                macd_signal=macd_signal,
                macd_histogram=macd_hist,
                adx=adx,
                plus_di=plus_di,
                minus_di=minus_di,
                bb_upper=bb_upper,
                bb_lower=bb_lower,
                bb_middle=bb_middle,
                bb_position=bb_position,
                trend_direction=trend_analysis.get(
                    "direction", TrendDirection.UNKNOWN.value
                ),
                trend_strength=trend_analysis.get("strength", 0),
                ohlcv_data=ohlcv,
            )

        except Exception as e:
            logger.error(f"计算技术指标失败 {symbol}: {e}")
            return None

    async def _check_signals(
        self, symbol: str, result: TechnicalIndicatorResult
    ) -> Optional[SignalCheckResult]:
        """检查交易信号"""
        try:
            # 计算单一交易分数
            trade_score, triggers, details = self._calculate_trade_score(result)

            # 转换为 0-1 范围的置信度用于返回
            # score 范围 -1 到 1，转换为 0 到 1
            confidence = (trade_score + 1) / 2

            # 确定信号类型
            signal_type = "hold"
            should_trade = False
            message = ""

            if trade_score >= self.BUY_THRESHOLD:
                # 分数 >= 0.3 → BUY
                signal_type = "buy"
                should_trade = True
                message = f"BUY信号触发 (分数: {trade_score:.2f}), 触发因素: {', '.join(triggers)}"
            elif trade_score <= self.SELL_THRESHOLD:
                # 分数 <= -0.3 → SELL
                signal_type = "sell"
                should_trade = True
                message = f"SELL信号触发 (分数: {trade_score:.2f}), 触发因素: {', '.join(triggers)}"
            else:
                # -0.3 < score < 0.3 → HOLD
                signal_type = "hold"
                if trade_score > 0:
                    message = f"市场偏多但信号不足 (分数: {trade_score:.2f}, 需 >= {self.BUY_THRESHOLD})"
                elif trade_score < 0:
                    message = f"市场偏空但信号不足 (分数: {trade_score:.2f}, 需 <= {self.SELL_THRESHOLD})"
                else:
                    message = f"市场中性 (分数: {trade_score:.2f})"

            # 检查冷却时间（仅对BUY/SELL信号生效）
            now = time.time()
            if should_trade:
                last_signal = self._last_signal_time.get(symbol, 0)
                if now - last_signal < self._cooldown_seconds:
                    # 在冷却期内，信号类型降级为HOLD
                    should_trade = False
                    signal_type = "hold"
                    message = (
                        f"信号冷却中 ({self._cooldown_seconds // 60}分钟内不重复触发)"
                    )
                    logger.info(
                        f"💤 {symbol} 冷却中 - 跳过BUY/SELL触发 (剩余{int(self._cooldown_seconds - (now - last_signal))}秒)"
                    )

            if should_trade:
                self._last_signal_time[symbol] = now

            # 记录所有信号（BUY/SELL/HOLD）
            if signal_type == "hold":
                logger.info(
                    f"💤 {symbol} HOLD信号 (分数: {trade_score:.2f}, 置信度: {confidence:.2f})"
                )
            else:
                logger.info(f"AlphaPulse信号: {symbol} - {message}")

            # 计算 buy_score 和 sell_score 用于返回（兼容旧接口）
            buy_score = max(0, trade_score)
            sell_score = max(0, -trade_score)

            return SignalCheckResult(
                should_trade=should_trade,
                signal_type=signal_type,
                buy_score=buy_score,
                sell_score=sell_score,
                confidence=confidence,
                triggers=triggers if signal_type != "hold" else [],
                indicator_result=result,
                message=message,
            )

        except Exception as e:
            logger.error(f"检查交易信号失败 {symbol}: {e}")
            return None

    def _calculate_trade_score(
        self, result: TechnicalIndicatorResult
    ) -> Tuple[float, List[str], Dict[str, float]]:
        """
        计算单一交易分数（范围: -1.0 到 1.0）

        Returns:
            score: 分数（-1.0 到 1.0）
            triggers: 触发的因素列表
            details: 各指标贡献详情
        """
        score = 0.0
        triggers = []
        details = {}

        # RSI: (RSI - 50) / 50 → -1 (极弱) 到 1 (极强)
        rsi_factor = (result.rsi - 50) / 50
        rsi_contribution = rsi_factor * self.TRADE_SIGNALS["rsi"]["weight"]
        score += rsi_contribution
        details["RSI"] = rsi_factor
        if abs(rsi_factor) > 0.1:
            if rsi_factor < 0:
                triggers.append(f"RSI偏弱 {result.rsi:.1f}")
            else:
                triggers.append(f"RSI偏强 {result.rsi:.1f}")

        # BB位置: (BB - 50) / 50 → -1 (底部) 到 1 (顶部)
        bb_factor = (result.bb_position - 50) / 50
        bb_contribution = bb_factor * self.TRADE_SIGNALS["bb_position"]["weight"]
        score += bb_contribution
        details["BB位置"] = bb_factor
        if abs(bb_factor) > 0.2:
            if bb_factor < 0:
                triggers.append(f"布林带底部 {result.bb_position:.1f}%")
            else:
                triggers.append(f"布林带顶部 {result.bb_position:.1f}%")

        # MACD: 归一化到 -1 到 1
        macd_factor = max(-1, min(1, result.macd_histogram / 50))
        macd_contribution = macd_factor * self.TRADE_SIGNALS["macd"]["weight"]
        score += macd_contribution
        details["MACD"] = macd_factor
        if abs(macd_factor) > 0.1:
            if macd_factor < 0:
                triggers.append(f"MACD柱状图转负 {result.macd_histogram:.4f}")
            else:
                triggers.append(f"MACD柱状图转正 {result.macd_histogram:.4f}")

        # ADX: 趋势强度因子 (0 到 1)
        adx_factor = max(0, min(1, (result.adx - 20) / 30))
        adx_contribution = adx_factor * self.TRADE_SIGNALS["adx"]["weight"]
        score += adx_contribution
        details["ADX"] = adx_factor
        if adx_factor > 0.1:
            triggers.append(f"ADX趋势明确 {result.adx:.1f}")

        # 24h价格位置: (Pos - 50) / 50 → -1 到 1
        pos_24h_factor = (result.price_position_24h - 50) / 50
        pos_24h_contribution = (
            pos_24h_factor * self.TRADE_SIGNALS["price_position_24h"]["weight"]
        )
        score += pos_24h_contribution
        details["24h位置"] = pos_24h_factor
        if abs(pos_24h_factor) > 0.2:
            if pos_24h_factor < 0:
                triggers.append(f"24h低位 {result.price_position_24h:.1f}%")
            else:
                triggers.append(f"24h高位 {result.price_position_24h:.1f}%")

        # 7d价格位置: (Pos - 50) / 50 → -1 到 1
        pos_7d_factor = (result.price_position_7d - 50) / 50
        pos_7d_contribution = (
            pos_7d_factor * self.TRADE_SIGNALS["price_position_7d"]["weight"]
        )
        score += pos_7d_contribution
        details["7d位置"] = pos_7d_factor
        if abs(pos_7d_factor) > 0.2:
            if pos_7d_factor < 0:
                triggers.append(f"7d低位 {result.price_position_7d:.1f}%")
            else:
                triggers.append(f"7d高位 {result.price_position_7d:.1f}%")

        # 波动率: 波动率越高，信号越可靠
        volatility_factor = min(1, result.atr_percent / 1.0)
        volatility_contribution = (
            volatility_factor * self.TRADE_SIGNALS["volatility"]["weight"]
        )
        score += volatility_contribution
        details["波动率"] = volatility_factor
        if volatility_factor > 0.3:
            triggers.append(f"波动率 {result.atr_percent:.2f}%")

        return score, triggers, details

    async def get_latest_indicator(
        self, symbol: str
    ) -> Optional[TechnicalIndicatorResult]:
        """获取最新技术指标"""
        snapshot = await self.data_manager.get_latest_indicator(symbol)
        if snapshot:
            return TechnicalIndicatorResult(
                symbol=snapshot.symbol,
                timeframe=snapshot.timeframe,
                timestamp=snapshot.timestamp,
                current_price=snapshot.current_price,
                high_24h=snapshot.high_24h,
                low_24h=snapshot.low_24h,
                high_7d=snapshot.high_7d,
                low_7d=snapshot.low_7d,
                price_position_24h=snapshot.price_position_24h,
                price_position_7d=snapshot.price_position_7d,
                atr=snapshot.atr,
                atr_percent=snapshot.atr_percent,
                rsi=snapshot.rsi,
                macd=snapshot.macd,
                macd_signal=snapshot.macd_signal,
                macd_histogram=snapshot.macd_histogram,
                adx=snapshot.adx,
                plus_di=snapshot.plus_di,
                minus_di=snapshot.minus_di,
                bb_upper=snapshot.bb_upper,
                bb_lower=snapshot.bb_lower,
                bb_middle=snapshot.bb_middle,
                bb_position=snapshot.bb_position,
                trend_direction=snapshot.trend_direction,
                trend_strength=snapshot.trend_strength,
            )
        return None

    async def manual_check(self, symbol: str) -> Optional[SignalCheckResult]:
        """手动检查信号（用于后备模式调用）"""
        logger.info(f"🔍 [{symbol}] 开始检查信号...")

        # 获取最新K线数据 - 添加超时和日志
        logger.info(f"📊 [{symbol}] 正在从本地获取K线数据...")
        try:
            ohlcv = await asyncio.wait_for(
                self.data_manager.get_ohlcv(symbol, "5m", limit=100), timeout=5.0
            )
            logger.info(
                f"📊 [{symbol}] 本地获取完成: {len(ohlcv) if ohlcv else 0} 根K线数据"
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ [{symbol}] get_ohlcv 超时，使用空数据")
            ohlcv = []

        if not ohlcv:
            logger.info(f"📥 [{symbol}] 本地无数据，从交易所获取...")
            # 需要从交易所获取
            try:
                ohlcv = await asyncio.wait_for(
                    self.exchange_client.fetch_ohlcv(symbol, "5m", limit=100),
                    timeout=25.0,  # 剩余25秒给交易所
                )
                if ohlcv:
                    logger.info(f"📥 [{symbol}] 交易所返回 {len(ohlcv)} 根K线")
                    # 批量更新K线数据，添加超时保护
                    logger.info(f"💾 [{symbol}] 正在更新K线数据...")
                    for i, bar in enumerate(ohlcv):
                        try:
                            await asyncio.wait_for(
                                self.data_manager.update_ohlcv(symbol, "5m", bar),
                                timeout=2.0,  # 每根K线最多2秒
                            )
                            if (i + 1) % 25 == 0:
                                logger.info(
                                    f"💾 [{symbol}] 已更新 {i + 1}/{len(ohlcv)} 根K线"
                                )
                        except asyncio.TimeoutError:
                            logger.warning(
                                f"⚠️ [{symbol}] update_ohlcv 第{i + 1}根超时，跳过"
                            )
                    logger.info(f"💾 [{symbol}] K线数据更新完成")
                else:
                    logger.warning(f"❌ [{symbol}] 无法获取K线数据")
                    return None
            except asyncio.TimeoutError:
                logger.error(f"❌ [{symbol}] fetch_ohlcv 超时")
                return None

        # 计算指标 - 添加超时保护
        logger.info(f"🔢 [{symbol}] 正在计算技术指标...")
        try:
            indicator_result = await asyncio.wait_for(
                self._calculate_indicators(symbol, ohlcv),
                timeout=20.0,  # 指标计算最多20秒
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ [{symbol}] _calculate_indicators 超时")
            return None

        if not indicator_result:
            logger.warning(f"❌ [{symbol}] 指标计算失败")
            return None

        logger.info(
            f"✅ [{symbol}] 指标计算完成: RSI={indicator_result.rsi:.1f}, BB={indicator_result.bb_position:.1f}%, ADX={indicator_result.adx:.1f}"
        )

        # 更新指标存储 - 添加超时保护
        snapshot = indicator_result.to_indicator_snapshot()
        try:
            await asyncio.wait_for(
                self.data_manager.update_indicator(symbol, snapshot),
                timeout=5.0,  # 最多5秒
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ [{symbol}] update_indicator 超时，跳过")

        # 检查信号 - 添加超时保护
        logger.info(f"🎯 [{symbol}] 正在检查交易信号...")
        try:
            result = await asyncio.wait_for(
                self._check_signals(symbol, indicator_result),
                timeout=10.0,  # 最多10秒
            )
        except asyncio.TimeoutError:
            logger.warning(f"⚠️ [{symbol}] _check_signals 超时")
            return None

        if result:
            logger.info(
                f"✅ [{symbol}] 信号检查完成: should_trade={result.should_trade}, signal={result.signal_type}"
            )
        else:
            logger.info(f"⚠️ [{symbol}] 信号检查返回None")

        return result
