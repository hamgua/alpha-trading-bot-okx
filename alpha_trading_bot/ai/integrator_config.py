"""集成器配置"""

from typing import Optional


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
