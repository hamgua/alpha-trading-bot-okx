"""集成器配置"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class SignalThresholdsConfig:
    """信号转换阈值配置"""

    # 趋势强度阈值
    strong_trend_strength: float = 0.30
    weak_trend_strength: float = 0.15
    strong_trend_rsi: float = 55
    strong_trend_position_max: float = 0.30
    strong_trend_drop_min: float = -1.5

    # 置信度配置
    confidence_floor: float = 0.35
    confidence_ceiling: float = 0.95
    confidence_dual_confirm: float = 0.65
    confidence_sustained: float = 0.60
    confidence_general: float = 0.55
    confidence_base: float = 0.50

    # 价格位置阈值
    price_position_low: float = 0.20
    price_position_high: float = 0.80
    price_position_too_low: float = 0.30

    # 短期变动阈值
    short_term_rise: float = 1.5
    short_term_drop: float = -1.5

    # BTC检测惩罚/加成系数
    btc_high_risk_penalty: float = 0.35
    btc_high_risk_penalty_no_decline: float = 0.30
    btc_low_opportunity_boost: float = 1.15
    btc_short_penalty: float = 0.7
    btc_short_boost: float = 1.15

    # SHORT信号处理系数
    short_trend_up_penalty: float = 0.7
    short_very_low_price_threshold: float = 0.20
    short_very_low_price_penalty: float = 0.6
    short_low_price_threshold: float = 0.35
    short_low_price_penalty: float = 0.8
    short_decline_boost: float = 1.2
    short_decline_boost_ceiling: float = 0.95

    # BTC级别阈值
    btc_high_threshold: float = 0.99
    btc_low_threshold: float = 0.01


class IntegrationConfig:
    """集成器配置"""

    def __init__(
        self,
        enable_adaptive_buy: bool = True,
        enable_signal_optimizer: bool = True,
        enable_high_price_filter: bool = True,
        enable_btc_detector: bool = True,
        enable_sustained_decline_detector: bool = True,
        adaptive_buy_config: Optional[object] = None,
        signal_optimizer_config: Optional[object] = None,
        high_price_config: Optional[object] = None,
        btc_detector_config: Optional[object] = None,
        sustained_decline_config: Optional[object] = None,
    ):
        self.enable_adaptive_buy = enable_adaptive_buy
        self.enable_signal_optimizer = enable_signal_optimizer
        self.enable_high_price_filter = enable_high_price_filter
        self.enable_btc_detector = enable_btc_detector
        self.enable_sustained_decline_detector = enable_sustained_decline_detector
        self.adaptive_buy_config = adaptive_buy_config
        self.signal_optimizer_config = signal_optimizer_config
        self.high_price_config = high_price_config
        self.btc_detector_config = btc_detector_config
        self.sustained_decline_config = sustained_decline_config
