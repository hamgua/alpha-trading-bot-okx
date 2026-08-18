"""集成器配置"""

from typing import Optional
from dataclasses import dataclass


@dataclass
class SignalThresholdsConfig:
    """信号转换阈值配置"""

    # 趋势强度阈值
    strong_trend_strength: float = 0.25
    weak_trend_strength: float = 0.10
    strong_trend_rsi: float = 55
    strong_trend_position_max: float = 0.35
    strong_trend_drop_min: float = -1.2

    # 置信度配置
    confidence_floor: float = 0.30
    confidence_ceiling: float = 0.97
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
    # 当 SHORT 在 trend_non_down 时折扣后低于该 floor，避免被永久封印（task-card R1）。
    # 默认 0.40 与 VolatilityRule 的低波动 fusion_threshold 对齐，AI 仍能刚好穿过门禁。
    # 决策引擎 (decision_engine.py:174-182 / :577-633) 的 RSIRSI>40、short_rr≥0.6 等二次校验未去除。
    short_trend_up_penalty_floor: float = 0.40
    short_very_low_price_threshold: float = 0.20
    short_very_low_price_penalty: float = 0.6
    short_low_price_threshold: float = 0.35
    short_low_price_penalty: float = 0.8
    short_decline_boost: float = 1.2
    short_decline_boost_ceiling: float = 0.95

    # BTC级别阈值
    btc_high_threshold: float = 0.99
    btc_low_threshold: float = 0.01

    def __post_init__(self) -> None:
        """约束 floor/penalty 等安全敏感字段在合法区间内（防配置注入攻击 H1）。

        区间边界注释：
        - [0, 1] 区间的为乘积/比例系数（如 short_trend_up_penalty、btc_short_penalty），超出 1 会变成"加成"
        - [0, 5] 区间的为绝对阈值或 cap（如 short_decline_boost=1.2 表示 1.2 倍后的置信度）
        - 防御 NaN：value != value 时为 NaN
        """
        bounded_fields = {
            # 严格 [0, 1] 区间（折扣/比例）—— 不能反向加成
            "short_trend_up_penalty": (0.0, 1.0),
            "short_trend_up_penalty_floor": (0.0, 1.0),
            "short_very_low_price_threshold": (0.0, 1.0),
            "short_very_low_price_penalty": (0.0, 1.0),
            "short_low_price_threshold": (0.0, 1.0),
            "short_low_price_penalty": (0.0, 1.0),
            "btc_short_penalty": (0.0, 1.0),  # 折扣：>1 变加成（破坏语义）
            # [0, 5] 区间（允许加成/绝对阈值）—— 用于 boost 类倍数
            "btc_short_boost": (0.0, 5.0),  # 默认 1.15 = 加成 15%
            "btc_low_opportunity_boost": (0.0, 5.0),
            "btc_high_risk_penalty": (0.0, 1.0),
            "btc_high_risk_penalty_no_decline": (0.0, 1.0),
            "short_decline_boost": (0.0, 5.0),
            "short_decline_boost_ceiling": (0.0, 5.0),
        }
        for field_name, (lo, hi) in bounded_fields.items():
            value = getattr(self, field_name)
            if not (lo <= value <= hi) or value != value:  # NaN 检查
                raise ValueError(
                    f"{field_name} 必须在 [{lo}, {hi}] 区间内，实际值 {value}"
                )


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
