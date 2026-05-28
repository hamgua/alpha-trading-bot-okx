"""
精简版配置模型 - 支持单AI/多AI融合
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Protocol, Tuple, runtime_checkable


class ConfigurationError(Exception):
    """配置错误异常"""

    pass


@runtime_checkable
class ConfigUpdaterProtocol(Protocol):
    """配置更新器接口 - 用于消除循环依赖

    定义配置更新器必须实现的方法，支持运行时类型检查。
    ai/optimizer 模块应使用此接口而非具体实现。
    """

    def get(self, key: str, default: Optional[object] = None) -> object:
        """获取配置值

        Args:
            key: 配置键（使用点号分隔，如 "ai.fusion_threshold"）
            default: 默认值

        Returns:
            配置值
        """
        ...

    def set(
        self,
        key: str,
        value: object,
        reason: str = "",
        update_type: Optional[object] = None,
    ) -> bool:
        """设置配置值

        Args:
            key: 配置键
            value: 新值
            reason: 变更原因
            update_type: 更新类型

        Returns:
            是否成功
        """
        ...

    def apply_optimized_params(
        self, params: Dict[str, object], reason: str = ""
    ) -> bool:
        """应用优化后的参数

        Args:
            params: 优化后的参数字典
            reason: 变更原因

        Returns:
            是否成功
        """
        ...

    def update_strategy_weight(
        self,
        strategy_name: str,
        weight: float,
        enabled: bool = True,
    ) -> bool:
        """更新策略权重

        Args:
            strategy_name: 策略名称
            weight: 新权重
            enabled: 是否启用

        Returns:
            是否成功
        """
        ...


@dataclass
class ExchangeConfig:
    """交易所配置"""

    api_key: str = ""
    secret: str = ""
    password: str = ""
    symbol: str = "BTC/USDT:USDT"
    leverage: int = 5  # 安全默认值（从10降至5），用户可通过 OKX_LEVERAGE 环境变量覆盖
    max_position_usage: float = 0.30  # 单次开仓最大使用余额比例 (30%)

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        if not self.api_key:
            errors.append("OKX_API_KEY 未配置")
        if not self.secret:
            errors.append("OKX_SECRET 未配置")
        if not self.password:
            errors.append("OKX_PASSWORD 未配置")
        if self.leverage < 1 or self.leverage > 125:
            errors.append(f"杠杆倍数 {self.leverage} 不在有效范围 (1-125)")
        if self.max_position_usage <= 0 or self.max_position_usage > 1:
            errors.append(f"仓位使用比例 {self.max_position_usage} 不在有效范围 (0-1)")
        return errors


@dataclass
class TradingConfig:
    """交易配置"""

    cycle_minutes: int = 15
    random_offset_range: int = 180
    allow_short_selling: bool = True  # 是否允许做空
    test_mode: bool = True
    real_trading_confirmed: bool = False
    runtime_environment: str = "dev"

    VALID_RUNTIME_ENVIRONMENTS = ["dev", "test", "staging", "prod", "production"]
    LIVE_ALLOWED_ENVIRONMENTS = ["prod", "production"]

    def check_live_trading_preconditions(self) -> Tuple[bool, str]:
        """检查是否满足实盘前置条件。"""
        if self.test_mode:
            return False, "test_mode_enabled"
        if not self.real_trading_confirmed:
            return False, "real_trading_not_confirmed"
        if self.runtime_environment not in self.LIVE_ALLOWED_ENVIRONMENTS:
            return False, "runtime_environment_not_allowed"
        return True, "ok"

    @property
    def is_live_mode(self) -> bool:
        """是否为实盘模式。"""
        return not self.test_mode

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        if self.cycle_minutes < 1:
            errors.append(f"交易周期 {self.cycle_minutes} 必须大于0")
        if self.random_offset_range < 0:
            errors.append(f"随机偏移范围 {self.random_offset_range} 不能为负数")

        if self.runtime_environment not in self.VALID_RUNTIME_ENVIRONMENTS:
            errors.append(
                "运行环境 "
                f"'{self.runtime_environment}' 无效，可选: "
                f"{self.VALID_RUNTIME_ENVIRONMENTS}"
            )

        if not self.test_mode:
            allowed, reason = self.check_live_trading_preconditions()
            if not allowed:
                if reason == "real_trading_not_confirmed":
                    errors.append("实盘模式需要显式确认: REAL_TRADING_CONFIRMED=true")
                elif reason == "runtime_environment_not_allowed":
                    errors.append(
                        "实盘模式仅允许在受控环境运行: RUNTIME_ENVIRONMENT=prod|production"
                    )

        return errors


@dataclass
class AIConfig:
    """AI配置"""

    mode: str = "single"  # single=单AI, fusion=多AI融合
    default_provider: str = "deepseek"

    # 多AI融合配置
    fusion_providers: List[str] = field(default_factory=lambda: ["deepseek", "kimi"])
    fusion_strategy: str = "weighted"
    fusion_weights: Dict[str, float] = field(
        default_factory=lambda: {"deepseek": 0.5, "kimi": 0.5}
    )
    fusion_threshold: float = 0.5

    # 各提供商API Keys
    api_keys: Dict[str, str] = field(default_factory=dict)

    VALID_MODES = ["single", "fusion"]
    VALID_PROVIDERS = ["deepseek", "kimi", "openai", "qwen", "gemini", "minimax"]
    VALID_STRATEGIES = [
        "weighted",
        "majority",
        "consensus",
        "confidence",
        "consensus_boosted",
    ]

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        if self.mode not in self.VALID_MODES:
            errors.append(f"AI模式 '{self.mode}' 无效，可选: {self.VALID_MODES}")
        if self.default_provider not in self.VALID_PROVIDERS:
            errors.append(
                f"AI提供商 '{self.default_provider}' 无效，可选: {self.VALID_PROVIDERS}"
            )
        if self.fusion_strategy not in self.VALID_STRATEGIES:
            errors.append(
                f"融合策略 '{self.fusion_strategy}' 无效，可选: {self.VALID_STRATEGIES}"
            )
        if self.fusion_threshold < 0 or self.fusion_threshold > 1:
            errors.append(f"融合阈值 {self.fusion_threshold} 不在有效范围 (0-1)")

        invalid_fusion_providers = [
            provider
            for provider in self.fusion_providers
            if provider not in self.VALID_PROVIDERS
        ]
        if invalid_fusion_providers:
            errors.append(
                f"融合提供商无效: {invalid_fusion_providers}, 可选: {self.VALID_PROVIDERS}"
            )

        invalid_weight_keys = [
            provider
            for provider in self.fusion_weights.keys()
            if provider not in self.VALID_PROVIDERS
        ]
        if invalid_weight_keys:
            errors.append(f"融合权重包含未知provider: {invalid_weight_keys}")

        if self.mode == "fusion":
            if not self.fusion_providers:
                errors.append("fusion 模式下 AI_FUSION_PROVIDERS 不能为空")

            missing_weights = [
                provider
                for provider in self.fusion_providers
                if provider not in self.fusion_weights
            ]
            if missing_weights:
                errors.append(f"融合权重缺失 provider: {missing_weights}")

            total_weight = sum(self.fusion_weights.values())
            if total_weight <= 0:
                errors.append("融合权重总和必须大于0")
            elif abs(total_weight - 1.0) > 1e-6:
                errors.append(f"融合权重总和必须为1.0，当前为 {total_weight:.6f}")

        # 检查是否有可用的API Key
        has_key = any(self.api_keys.values())
        if not has_key:
            errors.append("未配置任何AI提供商的API Key")

        return errors

    @classmethod
    def from_env(cls) -> "AIConfig":
        import os

        fusion_providers_str = os.getenv("AI_FUSION_PROVIDERS", "deepseek,kimi")
        fusion_providers = [
            provider.strip()
            for provider in fusion_providers_str.split(",")
            if provider.strip()
        ]
        if not fusion_providers:
            fusion_providers = ["deepseek", "kimi"]

        fusion_weights_str = os.getenv("AI_FUSION_WEIGHTS", "deepseek:0.5,kimi:0.5")
        raw_fusion_weights: Dict[str, float] = {}
        for item in fusion_weights_str.split(","):
            if ":" in item:
                key, value = item.split(":", 1)
                provider = key.strip()
                if not provider:
                    continue
                try:
                    raw_fusion_weights[provider] = float(value.strip())
                except ValueError:
                    continue

        fusion_weights = cls._build_normalized_weights(
            fusion_providers=fusion_providers,
            raw_weights=raw_fusion_weights,
        )

        return cls(
            mode=os.getenv("AI_MODE", "single"),
            default_provider=os.getenv("AI_DEFAULT_PROVIDER", "deepseek"),
            fusion_providers=fusion_providers,
            fusion_strategy=os.getenv("AI_FUSION_STRATEGY", "weighted"),
            fusion_weights=fusion_weights,
            fusion_threshold=float(os.getenv("AI_FUSION_THRESHOLD", "0.6")),
            api_keys={
                "deepseek": os.getenv("DEEPSEEK_API_KEY", ""),
                "kimi": os.getenv("KIMI_API_KEY", ""),
                "openai": os.getenv("OPENAI_API_KEY", ""),
                "qwen": os.getenv("QWEN_API_KEY", ""),
                "gemini": os.getenv("GOOGLE_API_KEY", os.getenv("GEMINI_API_KEY", "")),
                "minimax": os.getenv("MINIMAX_API_KEY", ""),
            },
        )

    @staticmethod
    def _build_normalized_weights(
        fusion_providers: List[str], raw_weights: Dict[str, float]
    ) -> Dict[str, float]:
        """构建完整且归一化的 provider 权重。"""
        positive_weights = [
            weight
            for provider, weight in raw_weights.items()
            if provider in fusion_providers and weight > 0
        ]
        default_weight = (
            sum(positive_weights) / len(positive_weights) if positive_weights else 1.0
        )

        completed_weights: Dict[str, float] = {}
        for provider in fusion_providers:
            candidate = raw_weights.get(provider, default_weight)
            completed_weights[provider] = candidate if candidate > 0 else default_weight

        total_weight = sum(completed_weights.values())
        if total_weight <= 0:
            equal = 1.0 / len(fusion_providers)
            return {provider: equal for provider in fusion_providers}

        return {
            provider: value / total_weight
            for provider, value in completed_weights.items()
        }


@dataclass
class StopLossConfig:
    """止损配置"""

    stop_loss_percent: float = 0.0005  # 亏损时止损比例 (0.05%, 即建仓价99.95%)
    stop_loss_profit_percent: float = 0.0002  # 盈利时止损比例 (0.02%, 即建仓价99.98%)
    stop_loss_tolerance_percent: float = (
        0.001  # 止损价容错比例 (如 0.001 = 0.1%)
    )
    take_profit_percent: float = 0.06  # 止盈比例 (如 0.06 = 6%)
    # 智能止损模式：基于建仓价计算止损
    stop_loss_entry_based: bool = True  # 是否基于建仓价计算止损
    price_vs_entry_tolerance_percent: float = (
        0.001  # 当前价与建仓价容错 (0.1%, 低于此值不更新止损)
    )

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        if self.stop_loss_percent <= 0 or self.stop_loss_percent > 1:
            errors.append(f"止损比例 {self.stop_loss_percent} 不在有效范围 (0-1)")
        if self.stop_loss_profit_percent <= 0 or self.stop_loss_profit_percent > 1:
            errors.append(  
                f"盈利止损比例 {self.stop_loss_profit_percent} 不在有效范围 (0-1)"
            )
        if self.stop_loss_tolerance_percent < 0:
            errors.append(f"止损容错比例 {self.stop_loss_tolerance_percent} 不能为负数")
        if self.take_profit_percent <= 0 or self.take_profit_percent > 1:
            errors.append(f"止盈比例 {self.take_profit_percent} 不在有效范围 (0-1)")
        if self.price_vs_entry_tolerance_percent < 0:
            errors.append(
                f"建仓价容错比例 {self.price_vs_entry_tolerance_percent} 不能为负数"
            )
        return errors


@dataclass
class SystemConfig:
    """系统配置"""

    log_level: str = "INFO"  # 日志级别: DEBUG/INFO/WARNING/ERROR

    VALID_LOG_LEVELS = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        if self.log_level.upper() not in self.VALID_LOG_LEVELS:
            errors.append(
                f"日志级别 '{self.log_level}' 无效，可选: {self.VALID_LOG_LEVELS}"
            )
        return errors


@dataclass
class Config:
    """主配置"""

    exchange: ExchangeConfig = field(default_factory=ExchangeConfig)
    trading: TradingConfig = field(default_factory=TradingConfig)
    ai: AIConfig = field(default_factory=AIConfig)
    stop_loss: StopLossConfig = field(default_factory=StopLossConfig)
    system: SystemConfig = field(default_factory=SystemConfig)

    def validate(self) -> List[str]:
        """验证所有配置，返回错误列表"""
        errors = []
        errors.extend(self.exchange.validate())
        errors.extend(self.trading.validate())
        errors.extend(self.ai.validate())
        errors.extend(self.stop_loss.validate())
        errors.extend(self.system.validate())
        return errors

    def validate_or_raise(self) -> None:
        """验证配置，如果有错误则抛出异常"""
        errors = self.validate()
        if errors:
            raise ConfigurationError("配置错误:\n  - " + "\n  - ".join(errors))

    def check_live_trading_preconditions(self) -> Tuple[bool, str]:
        """检查实盘下单前置条件。"""
        allowed, reason = self.trading.check_live_trading_preconditions()
        if not allowed:
            return allowed, reason

        if (
            not self.exchange.api_key
            or not self.exchange.secret
            or not self.exchange.password
        ):
            return False, "exchange_credentials_incomplete"

        return True, "ok"

    @classmethod
    def from_env(cls) -> "Config":
        import os

        config = cls(
            exchange=ExchangeConfig(
                api_key=os.getenv("OKX_API_KEY", ""),
                secret=os.getenv("OKX_SECRET", ""),
                password=os.getenv("OKX_PASSWORD", ""),
                symbol=os.getenv("OKX_SYMBOL", "BTC/USDT:USDT"),
                leverage=int(os.getenv("OKX_LEVERAGE", "5")),
                max_position_usage=float(os.getenv("MAX_POSITION_USAGE", "0.30")),
            ),
            trading=TradingConfig(
                cycle_minutes=int(os.getenv("CYCLE_MINUTES", "15")),
                random_offset_range=int(os.getenv("RANDOM_OFFSET_RANGE", "180")),
                allow_short_selling=os.getenv("ALLOW_SHORT_SELLING", "true").lower()
                == "true",
                test_mode=os.getenv("TEST_MODE", "true").lower() == "true",
                real_trading_confirmed=os.getenv(
                    "REAL_TRADING_CONFIRMED", "false"
                ).lower()
                == "true",
                runtime_environment=os.getenv(
                    "RUNTIME_ENVIRONMENT", os.getenv("RUNTIME_ENV", "dev")
                ).lower(),
            ),
            ai=AIConfig.from_env(),
            stop_loss=StopLossConfig(
                stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", "0.0005")),
                stop_loss_profit_percent=float(
                    os.getenv("STOP_LOSS_PROFIT_PERCENT", "0.0002")
                ),
                take_profit_percent=float(os.getenv("TAKE_PROFIT_PERCENT", "0.06")),
                stop_loss_entry_based=os.getenv(
                    "STOP_LOSS_ENTRY_BASED", "true"
                ).lower()
                == "true",
                price_vs_entry_tolerance_percent=float(
                    os.getenv("PRICE_VS_ENTRY_TOLERANCE_PERCENT", "0.001")
                ),
            ),
            system=SystemConfig(
                log_level=os.getenv("LOG_LEVEL", "INFO"),
            ),
        )

        # 验证配置
        config.validate_or_raise()

        return config
