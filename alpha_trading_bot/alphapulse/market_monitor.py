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

    # BUY信号触发条件及权重
    BUY_SIGNALS = {
        "rsi_oversold": {"threshold": 30, "weight": 0.20, "check": lambda v: v < 30},
        "rsi_weak": {"threshold": 40, "weight": 0.15, "check": lambda v: v < 40},
        "bb_bottom": {"threshold": 10, "weight": 0.15, "check": lambda v: v < 10},
        "bb_lower_zone": {"threshold": 25, "weight": 0.10, "check": lambda v: v < 25},
        "macd_crossover_up": {"weight": 0.10, "check": lambda v: v > 0},
        "adx_strong_up": {"threshold": 25, "weight": 0.10, "check": lambda v: v > 25},
        "price_low_24h": {"threshold": 20, "weight": 0.10, "check": lambda v: v < 20},
        "price_low_7d": {"threshold": 25, "weight": 0.05, "check": lambda v: v < 25},
        "volatility_high": {
            "threshold": 0.5,
            "weight": 0.05,
            "check": lambda v: v > 0.5,
        },
    }

    # SELL信号触发条件及权重
    SELL_SIGNALS = {
        "rsi_overbought": {"threshold": 70, "weight": 0.20, "check": lambda v: v > 70},
        "rsi_strong": {"threshold": 60, "weight": 0.15, "check": lambda v: v > 60},
        "bb_top": {"threshold": 90, "weight": 0.15, "check": lambda v: v > 90},
        "bb_upper_zone": {"threshold": 75, "weight": 0.10, "check": lambda v: v > 75},
        "macd_crossover_down": {"weight": 0.10, "check": lambda v: v < 0},
        "adx_strong_down": {"threshold": 25, "weight": 0.10, "check": lambda v: v > 25},
        "price_high_24h": {"threshold": 80, "weight": 0.10, "check": lambda v: v > 80},
        "price_high_7d": {"threshold": 75, "weight": 0.05, "check": lambda v: v > 75},
        "volatility_high": {
            "threshold": 0.5,
            "weight": 0.05,
            "check": lambda v: v > 0.5,
        },
    }

    def __init__(
        self,
        exchange_client,
        config: AlphaPulseConfig,
        data_manager: DataManager = None,
    ):
        """
        初始化市场监控系统

        Args:
            exchange_client: 交易所客户端
            config: AlphaPulse配置
            data_manager: 数据管理器（可选）
        """
        self.exchange_client = exchange_client
        self.config = config
        self.data_manager = data_manager or DataManager(
            max_ohlcv_bars=config.max_ohlcv_bars,
            max_indicator_history=config.max_indicator_history,
        )

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
        """启动监控"""
        if self._running:
            logger.warning("MarketMonitor 已在运行")
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

            # 获取K线数据 (使用15分钟周期)
            ohlcv = await self.exchange_client.fetch_ohlcv(symbol, "15m", limit=100)

            if not ohlcv:
                logger.warning(f"⚠️ 获取K线数据失败: {symbol}")
                return

            logger.info(
                f"📥 {symbol} 获取到 {len(ohlcv)} 根K线, 最新价格: {ohlcv[-1][4]:.2f}"
            )

            # 更新数据管理器
            for bar in ohlcv:
                await self.data_manager.update_ohlcv(symbol, "15m", bar)

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

            # 计算ATR
            high_low_data = list(zip(highs, lows))
            atr_list = self.tech_indicators.calculate_atr(
                high_low_data, period=params["atr_period"]
            )
            atr = atr_list[-1] if atr_list else 0
            atr_percent = (atr / current_price * 100) if current_price > 0 else 0

            # 计算RSI
            rsi = self.tech_indicators.calculate_rsi(
                closes, period=params["rsi_period"]
            )

            # 计算MACD
            macd, macd_signal, macd_hist = self.tech_indicators.calculate_macd(
                closes,
                fast_period=params["macd_fast"],
                slow_period=params["macd_slow"],
                signal_period=params["macd_signal"],
            )

            # 计算ADX
            adx_result = self.tech_indicators.calculate_adx(
                highs, lows, closes, period=params["adx_period"]
            )
            adx = adx_result.get("adx", 0) if adx_result else 0
            plus_di = adx_result.get("plus_di", 0) if adx_result else 0
            minus_di = adx_result.get("minus_di", 0) if adx_result else 0

            # 计算布林带
            bb_result = self.tech_indicators.calculate_bollinger_bands(
                closes, period=params["bb_period"], std_dev=params["bb_std"]
            )
            bb_upper = bb_result.get("upper", current_price)
            bb_lower = bb_result.get("lower", current_price)
            bb_middle = bb_result.get("middle", current_price)

            # 计算布林带位置
            bb_position = (
                ((current_price - bb_lower) / (bb_upper - bb_lower) * 100)
                if bb_upper != bb_lower
                else 50.0
            )
            bb_position = max(0, min(100, bb_position))

            # 趋势分析
            trend_analysis = await self.data_manager.get_trend_analysis(
                symbol, "15m", 20
            )

            return TechnicalIndicatorResult(
                symbol=symbol,
                timeframe="15m",
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
            # 检查冷却时间
            now = time.time()
            last_signal = self._last_signal_time.get(symbol, 0)
            if now - last_signal < self._cooldown_seconds:
                return None

            # 计算分数
            buy_score, buy_triggers = self._calculate_score(
                result, self.BUY_SIGNALS, "buy"
            )
            sell_score, sell_triggers = self._calculate_score(
                result, self.SELL_SIGNALS, "sell"
            )

            # 确定信号类型
            signal_type = "hold"
            should_trade = False
            confidence = 0.0
            message = ""

            if buy_score >= self.config.buy_threshold and sell_score < 0.3:
                signal_type = "buy"
                should_trade = True
                confidence = buy_score
                message = f"BUY信号触发 (分数: {buy_score:.2f}), 触发因素: {', '.join(buy_triggers)}"

            elif sell_score >= self.config.sell_threshold and buy_score < 0.3:
                signal_type = "sell"
                should_trade = True
                confidence = sell_score
                message = f"SELL信号触发 (分数: {sell_score:.2f}), 触发因素: {', '.join(sell_triggers)}"

            else:
                # 不满足交易条件
                if abs(buy_score - sell_score) < 0.1:
                    message = f"市场震荡, 买卖力量均衡 (BUY: {buy_score:.2f}, SELL: {sell_score:.2f})"
                else:
                    direction = "BUY" if buy_score > sell_score else "SELL"
                    higher = max(buy_score, sell_score)
                    message = f"{direction}分数不足 ({higher:.2f} < {self.config.buy_threshold})"

            if should_trade:
                self._last_signal_time[symbol] = now
                logger.info(f"AlphaPulse信号: {symbol} - {message}")

            return SignalCheckResult(
                should_trade=should_trade,
                signal_type=signal_type,
                buy_score=buy_score,
                sell_score=sell_score,
                confidence=confidence,
                triggers=buy_triggers if signal_type == "buy" else sell_triggers,
                indicator_result=result,
                message=message,
            )

        except Exception as e:
            logger.error(f"检查交易信号失败 {symbol}: {e}")
            return None

    def _calculate_score(
        self,
        result: TechnicalIndicatorResult,
        signal_config: Dict,
        signal_type: str,
    ) -> Tuple[float, List[str]]:
        """计算信号分数"""
        score = 0.0
        triggers = []

        # RSI checks - handle rsi_oversold and rsi_weak keys
        for key in signal_config:
            if key.startswith("rsi_"):
                cfg = signal_config[key]
                if cfg["check"](result.rsi):
                    score += cfg["weight"]
                    if key == "rsi_oversold":
                        triggers.append(f"RSI超卖 {result.rsi:.1f}")
                    elif key == "rsi_weak":
                        triggers.append(f"RSI偏弱 {result.rsi:.1f}")

        # 布林带位置
        for key in signal_config:
            if key.startswith("bb_"):
                cfg = signal_config[key]
                if signal_type == "buy":
                    if result.bb_position < cfg["threshold"]:
                        score += cfg["weight"]
                        if key == "bb_bottom":
                            triggers.append(f"布林带底部 {result.bb_position:.1f}%")
                        elif key == "bb_lower_zone":
                            triggers.append(f"布林带低位区间 {result.bb_position:.1f}%")
                else:
                    if result.bb_position > 100 - cfg["threshold"]:
                        score += cfg["weight"]
                        if key == "bb_top":
                            triggers.append(f"布林带顶部 {result.bb_position:.1f}%")
                        elif key == "bb_upper_zone":
                            triggers.append(f"布林带高位区间 {result.bb_position:.1f}%")

        # MACD柱状图
        for key in signal_config:
            if key.startswith("macd_"):
                cfg = signal_config[key]
                if signal_type == "buy" and result.macd_histogram > 0:
                    score += cfg["weight"]
                    triggers.append(f"MACD柱状图转正 {result.macd_histogram:.4f}")
                elif signal_type == "sell" and result.macd_histogram < 0:
                    score += cfg["weight"]
                    triggers.append(f"MACD柱状图转负 {result.macd_histogram:.4f}")

        # ADX
        for key in signal_config:
            if key.startswith("adx_"):
                cfg = signal_config[key]
                if result.adx > cfg["threshold"]:
                    score += cfg["weight"]
                    direction = "上涨" if signal_type == "buy" else "下跌"
                    triggers.append(f"ADX趋势明确 {result.adx:.1f} ({direction})")

        # 价格位置
        for key in signal_config:
            if key.startswith("price_"):
                cfg = signal_config[key]
                if signal_type == "buy":
                    if result.price_position_24h < cfg["threshold"]:
                        score += cfg["weight"]
                        triggers.append(f"24h低位 {result.price_position_24h:.1f}%")
                else:
                    if result.price_position_24h > cfg["threshold"]:
                        score += cfg["weight"]
                        triggers.append(f"24h高位 {result.price_position_24h:.1f}%")

        # 波动率
        for key in signal_config:
            if key.startswith("volatility_"):
                cfg = signal_config[key]
                if result.atr_percent > cfg["threshold"]:
                    score += cfg["weight"]
                    triggers.append(f"高波动率 {result.atr_percent:.2f}%")

        return score, triggers

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

        # 获取最新K线数据
        ohlcv = await self.data_manager.get_ohlcv(symbol, "15m", limit=100)
        logger.info(f"📊 [{symbol}] 获取到 {len(ohlcv) if ohlcv else 0} 根K线数据")

        if not ohlcv:
            logger.info(f"📥 [{symbol}] 本地无数据，从交易所获取...")
            # 需要从交易所获取
            ohlcv = await self.exchange_client.fetch_ohlcv(symbol, "15m", limit=100)
            if ohlcv:
                logger.info(f"📥 [{symbol}] 交易所返回 {len(ohlcv)} 根K线")
                for bar in ohlcv:
                    await self.data_manager.update_ohlcv(symbol, "15m", bar)
            else:
                logger.warning(f"❌ [{symbol}] 无法获取K线数据")
                return None

        # 计算指标
        logger.info(f"🔢 [{symbol}] 正在计算技术指标...")
        indicator_result = await self._calculate_indicators(symbol, ohlcv)

        if not indicator_result:
            logger.warning(f"❌ [{symbol}] 指标计算失败")
            return None

        logger.info(
            f"✅ [{symbol}] 指标计算完成: RSI={indicator_result.rsi:.1f}, BB={indicator_result.bb_position:.1f}%, ADX={indicator_result.adx:.1f}"
        )

        # 更新指标存储
        snapshot = indicator_result.to_indicator_snapshot()
        await self.data_manager.update_indicator(symbol, snapshot)

        # 检查信号
        logger.info(f"🎯 [{symbol}] 正在检查交易信号...")
        result = await self._check_signals(symbol, indicator_result)

        if result:
            logger.info(
                f"✅ [{symbol}] 信号检查完成: should_trade={result.should_trade}, signal={result.signal_type}"
            )
        else:
            logger.info(f"⚠️ [{symbol}] 信号检查返回None")

        return result
