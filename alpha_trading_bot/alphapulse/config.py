"""
AlphaPulse 配置模块
"""

import os
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class AlphaPulseConfig:
    """
    AlphaPulse 引擎配置类

    所有配置项都可以通过环境变量覆盖
    """

    # ========== 引擎控制 ==========
    enabled: bool = field(default=True)
    """是否启用AlphaPulse引擎"""

    monitor_interval: int = field(default=60)
    """监控间隔秒数"""

    use_ai_validation: bool = field(default=True)
    """是否使用AI验证信号"""

    # ========== 监控模式 ==========
    primary_mode: bool = field(default=True)
    """监控为主模式: true=监控触发主流程, false=主流程按周期运行"""

    # ========== 触发阈值 ==========
    buy_threshold: float = field(default=0.65)
    """BUY信号触发阈值 (0.0-1.0)"""

    sell_threshold: float = field(default=0.65)
    """SELL信号触发阈值 (0.0-1.0)"""

    min_ai_confidence: float = field(default=0.70)
    """AI最小置信度"""

    cooldown_minutes: int = field(default=15)
    """同方向交易冷却时间（分钟）"""

    # ========== 后备模式 ==========
    fallback_cron_enabled: bool = field(default=True)
    """启用后备15分钟定时任务"""

    # ========== 技术指标参数 ==========
    atr_period: int = field(default=14)
    """ATR周期"""

    rsi_period: int = field(default=14)
    """RSI周期"""

    macd_fast: int = field(default=12)
    """MACD快线周期"""

    macd_slow: int = field(default=26)
    """MACD慢线周期"""

    macd_signal: int = field(default=9)
    """MACD信号线周期"""

    adx_period: int = field(default=14)
    """ADX周期"""

    bb_period: int = field(default=20)
    """布林带周期"""

    bb_std: float = field(default=2.0)
    """布林带标准差倍数"""

    # ========== 交易对配置 ==========
    symbols: list = field(default_factory=lambda: ["BTC/USDT:USDT"])
    """监控的交易对列表"""

    # ========== 数据存储配置 ==========
    max_ohlcv_bars: int = field(default=200)
    """最大存储的OHLCV K线数量"""

    max_indicator_history: int = field(default=100)
    """最大存储的指标历史数量"""

    @classmethod
    def from_env(cls) -> "AlphaPulseConfig":
        """
        从环境变量加载配置

        环境变量格式: ALPHA_PULSE_<UPPER_CASE_NAME>
        例如: ALPHA_PULSE_ENABLED, ALPHA_PULSE_MONITOR_INTERVAL
        """
        # 引擎控制
        enabled = os.getenv("ALPHA_PULSE_ENABLED", "true").lower() == "true"
        monitor_interval = int(os.getenv("ALPHA_PULSE_INTERVAL", "60"))
        use_ai = os.getenv("ALPHA_PULSE_USE_AI", "true").lower() == "true"

        # 监控模式
        primary_mode = os.getenv("ALPHA_PULSE_PRIMARY_MODE", "true").lower() == "true"

        # 触发阈值
        buy_threshold = float(os.getenv("ALPHA_PULSE_BUY_THRESHOLD", "0.65"))
        sell_threshold = float(os.getenv("ALPHA_PULSE_SELL_THRESHOLD", "0.65"))
        min_confidence = float(os.getenv("ALPHA_PULSE_MIN_CONFIDENCE", "0.70"))
        cooldown = int(os.getenv("ALPHA_PULSE_COOLDOWN_MINUTES", "15"))

        # 后备模式
        fallback_enabled = os.getenv("FALLBACK_CRON_ENABLED", "true").lower() == "true"

        # 技术指标参数
        atr_period = int(os.getenv("INDICATOR_ATR_PERIOD", "14"))
        rsi_period = int(os.getenv("INDICATOR_RSI_PERIOD", "14"))
        macd_fast = int(os.getenv("INDICATOR_MACD_FAST", "12"))
        macd_slow = int(os.getenv("INDICATOR_MACD_SLOW", "26"))
        macd_signal = int(os.getenv("INDICATOR_MACD_SIGNAL", "9"))
        adx_period = int(os.getenv("INDICATOR_ADX_PERIOD", "14"))
        bb_period = int(os.getenv("INDICATOR_BB_PERIOD", "20"))
        bb_std = float(os.getenv("INDICATOR_BB_STD", "2.0"))

        # 交易对配置
        symbols_str = os.getenv("ALPHA_PULSE_SYMBOLS", "BTC/USDT:USDT")
        symbols = [s.strip() for s in symbols_str.split(",")]

        # 数据存储配置
        max_ohlcv = int(os.getenv("ALPHA_PULSE_MAX_OHLCV_BARS", "200"))
        max_indicator = int(os.getenv("ALPHA_PULSE_MAX_INDICATOR_HISTORY", "100"))

        return cls(
            enabled=enabled,
            monitor_interval=monitor_interval,
            use_ai_validation=use_ai,
            primary_mode=primary_mode,
            buy_threshold=buy_threshold,
            sell_threshold=sell_threshold,
            min_ai_confidence=min_confidence,
            cooldown_minutes=cooldown,
            fallback_cron_enabled=fallback_enabled,
            atr_period=atr_period,
            rsi_period=rsi_period,
            macd_fast=macd_fast,
            macd_slow=macd_slow,
            macd_signal=macd_signal,
            adx_period=adx_period,
            bb_period=bb_period,
            bb_std=bb_std,
            symbols=symbols,
            max_ohlcv_bars=max_ohlcv,
            max_indicator_history=max_indicator,
        )

    def get_indicator_params(self) -> dict:
        """获取技术指标参数"""
        return {
            "atr_period": self.atr_period,
            "rsi_period": self.rsi_period,
            "macd_fast": self.macd_fast,
            "macd_slow": self.macd_slow,
            "macd_signal": self.macd_signal,
            "adx_period": self.adx_period,
            "bb_period": self.bb_period,
            "bb_std": self.bb_std,
        }

    def get_thresholds(self) -> dict:
        """获取触发阈值配置"""
        return {
            "buy_threshold": self.buy_threshold,
            "sell_threshold": self.sell_threshold,
            "min_ai_confidence": self.min_ai_confidence,
            "cooldown_minutes": self.cooldown_minutes,
        }
