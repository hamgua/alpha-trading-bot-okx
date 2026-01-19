"""
配置数据模型
"""

from enum import Enum
from dataclasses import dataclass
from typing import Dict, Any, Optional, List


class ConfigSection(Enum):
    """配置段枚举"""

    EXCHANGE = "exchange"
    TRADING = "trading"
    STRATEGIES = "strategies"
    RISK = "risk"
    AI = "ai"
    SYSTEM = "system"


@dataclass
class ConfigValidationResult:
    """配置验证结果"""

    is_valid: bool
    errors: list[str]
    warnings: list[str]


@dataclass
class ExchangeConfig:
    """交易所配置"""

    exchange: str = "okx"
    api_key: str = ""
    secret: str = ""
    password: str = ""
    sandbox: bool = False
    symbol: str = "BTC/USDT:USDT"
    timeframe: str = "5m"
    contract_size: float = 0.01


@dataclass
class TradingConfig:
    """交易配置"""

    test_mode: bool = True
    max_position_size: float = 0.01  # 默认0.01张（符合OKX实际要求）
    min_trade_amount: float = 0.01  # 最小交易量0.01张（符合OKX实际要求）
    leverage: int = 10  # 10倍杠杆，符合用户要求
    cycle_minutes: int = 15
    random_offset_enabled: bool = True  # 是否启用随机时间偏移
    random_offset_range: int = 180  # 随机偏移范围（秒），默认±3分钟
    alphapulse_only_mode: bool = False  # AlphaPulse独立运行模式
    margin_mode: str = "cross"
    position_mode: str = "one_way"
    allow_short_selling: bool = False


@dataclass
class StrategyConfig:
    """策略配置"""

    investment_type: str = (
        "conservative"  # 投资策略类型: conservative/moderate/aggressive
    )
    profit_lock_enabled: bool = True
    sell_signal_enabled: bool = True
    buy_signal_enabled: bool = True
    consolidation_protection_enabled: bool = True
    smart_tp_sl_enabled: bool = True
    limit_order_enabled: bool = True
    price_crash_protection_enabled: bool = True

    # 止盈止损总开关
    take_profit_enabled: bool = True
    stop_loss_enabled: bool = True

    # 止盈止损模式
    take_profit_mode: str = "smart"  # normal:普通模式, smart:智能模式
    stop_loss_mode: str = "smart"  # normal:普通模式, smart:智能模式

    # 普通模式配置（固定值）
    normal_take_profit_percent: float = 0.06  # 普通模式止盈百分比
    normal_stop_loss_percent: float = 0.02  # 普通模式止损百分比 - 从0.5%提高到2%

    # 智能模式-固定模式配置
    smart_fixed_take_profit_percent: float = 0.06  # 智能固定模式止盈百分比
    smart_fixed_stop_loss_percent: float = (
        0.02  # 智能固定模式止损百分比 - 从0.5%提高到2%
    )

    # 智能模式-多级模式配置
    smart_multi_take_profit_levels: Optional[List[float]] = None  # 多级止盈级别列表
    smart_multi_take_profit_ratios: Optional[List[float]] = None  # 各级止盈的平仓比例

    # 利润锁定配置
    enable_profit_lock: bool = True  # 是否启用利润锁定
    profit_lock_threshold: float = 0.05  # 利润锁定阈值

    # 自适应止损配置
    adaptive_stop_loss_enabled: bool = True  # 是否启用自适应止损
    up_trend_stop_loss: float = 0.015  # 上升趋势止损百分比 - 从0.2%提高到1.5%
    down_trend_stop_loss: float = 0.025  # 下降趋势止损百分比 - 从1%提高到2.5%

    # 止盈策略配置
    profit_taking_strategy: str = (
        "single_level"  # 止盈策略：'single_level' 单级，'multi_level' 多级
    )
    profit_taking_levels: Optional[List[float]] = None  # 多级止盈的级别列表


@dataclass
class RiskConfig:
    """风险控制配置"""

    max_daily_loss: float = 100.0
    max_position_risk: float = 0.05
    stop_loss_enabled: bool = True
    take_profit_enabled: bool = True
    trailing_stop_enabled: bool = True
    trailing_distance: float = 0.015  # 追踪距离（百分比）
    trailing_stop_loss_enabled: bool = True  # 是否启用追踪止损
    trailing_stop_loss_mode: str = (
        "entry_based"  # 追踪模式：'entry_based'（基于入场价）或 'fixed'（固定距离）
    )

    # 动态仓位管理配置
    enable_dynamic_position_sizing: bool = True  # 是否启用动态仓位管理
    max_risk_per_trade: float = 0.02  # 每笔交易最大风险（2%）
    min_position_size: float = 0.01  # 最小仓位（合约数）
    max_position_size: float = 10.0  # 最大仓位（合约数）
    position_sizing_strategy: str = (
        "kelly"  # 仓位策略：'fixed', 'kelly', 'volatility', 'risk_parity'
    )
    kelly_fraction: float = 0.25  # 凯利分数（使用1/4凯利降低风险）
    volatility_threshold_low: float = 0.01  # 低波动阈值（1%）
    volatility_threshold_high: float = 0.03  # 高波动阈值（3%）

    # 交易成本分析配置
    enable_cost_analysis: bool = True  # 启用成本分析
    account_tier: str = "regular"  # 账户等级（regular, vip1, vip2, vip3, vip4）
    min_profit_threshold: float = 0.002  # 最小盈利阈值（0.2%）
    cost_analysis_window_days: int = 30  # 成本分析窗口（天）
    max_acceptable_slippage_bps: int = 10  # 最大可接受滑点（基点）


@dataclass
class AIConfig:
    """AI配置"""

    use_multi_ai: bool = False
    cache_duration: int = 900
    timeout: int = 30
    max_retries: int = 2
    min_confidence_threshold: float = 0.3
    ai_provider: str = "kimi"
    fallback_enabled: bool = True
    # AI模型配置
    models: Optional[Dict[str, str]] = None
    # AI融合配置
    use_multi_ai_fusion: bool = True
    ai_default_provider: str = "deepseek"
    ai_fusion_providers: Optional[List[str]] = None
    ai_fusion_weights: Optional[Dict[str, float]] = None
    ai_fusion_strategy: str = "weighted"  # consensus/weighted/majority/confidence
    ai_fusion_threshold: float = 0.6
    # 动态缓存配置
    enable_dynamic_cache: bool = True  # 是否启用动态缓存
    dynamic_cache_config: Optional[Dict[str, Any]] = None  # 动态缓存配置参数
    # 信号优化配置
    enable_signal_optimization: bool = True  # 是否启用信号优化
    signal_optimization_config: Optional[Dict[str, Any]] = None  # 信号优化配置


@dataclass
class NetworkConfig:
    """网络配置"""

    proxy_enabled: bool = False
    http_proxy: Optional[str] = None
    https_proxy: Optional[str] = None
    timeout: int = 30
    max_retries: int = 3
    retry_delay: int = 1


@dataclass
class SystemConfig:
    """系统配置"""

    max_history_length: int = 100
    log_level: str = "INFO"
    monitoring_enabled: bool = True
    web_interface_enabled: bool = False
    web_port: int = 8501
