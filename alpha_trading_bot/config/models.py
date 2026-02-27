"""
精简版配置模型 - 支持单AI/多AI融合
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional


class ConfigurationError(Exception):
    """配置错误异常"""

    pass


@dataclass
class ExchangeConfig:
    """交易所配置"""

    api_key: str = ""
    secret: str = ""
    password: str = ""
    symbol: str = "BTC/USDT:USDT"
    leverage: int = 10

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
        return errors


@dataclass
class TradingConfig:
    """交易配置"""

    cycle_minutes: int = 15
    random_offset_range: int = 180

    def validate(self) -> List[str]:
        """验证配置，返回错误列表"""
        errors = []
        if self.cycle_minutes < 1:
            errors.append(f"交易周期 {self.cycle_minutes} 必须大于0")
        if self.random_offset_range < 0:
            errors.append(f"随机偏移范围 {self.random_offset_range} 不能为负数")
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
    VALID_PROVIDERS = ["deepseek", "kimi", "openai", "qwen"]
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
            p.strip() for p in fusion_providers_str.split(",") if p.strip()
        ]

        fusion_weights_str = os.getenv("AI_FUSION_WEIGHTS", "deepseek:0.5,kimi:0.5")
        fusion_weights = {}
        for item in fusion_weights_str.split(","):
            if ":" in item:
                k, v = item.split(":")
                fusion_weights[k.strip()] = float(v.strip())

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
            },
        )


@dataclass
class StopLossConfig:
    """止损配置"""

    stop_loss_percent: float = 0.005  # 亏损时止损比例 (如 0.005 = 0.5%)
    stop_loss_profit_percent: float = 0.002  # 盈利时止损比例 (如 0.002 = 0.2%)
    stop_loss_tolerance_percent: float = (
        0.001  # 止损价容错比例 (如 0.001 = 0.1%, 约77美元对于BTC)
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
            raise ConfigurationError(f"配置错误:\n  - " + "\n  - ".join(errors))

    @classmethod
    def from_env(cls) -> "Config":
        import os

        config = cls(
            exchange=ExchangeConfig(
                api_key=os.getenv("OKX_API_KEY", ""),
                secret=os.getenv("OKX_SECRET", ""),
                password=os.getenv("OKX_PASSWORD", ""),
                symbol=os.getenv("OKX_SYMBOL", "BTC/USDT:USDT"),
                leverage=int(os.getenv("OKX_LEVERAGE", "10")),
            ),
            trading=TradingConfig(
                cycle_minutes=int(os.getenv("CYCLE_MINUTES", "15")),
                random_offset_range=int(os.getenv("RANDOM_OFFSET_RANGE", "180")),
            ),
            ai=AIConfig.from_env(),
            stop_loss=StopLossConfig(
                stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", "0.005")),
                stop_loss_profit_percent=float(
                    os.getenv("STOP_LOSS_PROFIT_PERCENT", "0.002")
                ),
            ),
            system=SystemConfig(
                log_level=os.getenv("LOG_LEVEL", "INFO"),
            ),
        )

        # 验证配置
        config.validate_or_raise()

        return config
