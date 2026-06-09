"""
AI配置管理器

功能：
- 统一管理所有AI相关配置
- 支持YAML配置
- 支持环境变量覆盖
- 支持配置热重载

作者：AI Trading System
日期：2026-02-04
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass, field
from datetime import datetime

from alpha_trading_bot.config.thresholds import (
    RSI_BUY_REGULAR_MAX,
    RSI_BUY_OVERSOLD_MAX,
    RSI_BUY_SUPPORT_MAX,
    RSI_BUY_CONFIRM_MAX,
    RSI_RISK_OVERBOUGHT,
    RSI_RISK_HIGH,
    RSI_TAKE_PROFIT,
    RSI_OVERSOLD,
)

logger = logging.getLogger(__name__)


@dataclass
class AIConfig:
    """AI核心配置

    推荐融合方案: DeepSeek(0.55) + Gemini(0.45)
    理由: DeepSeek Thinking推理深入 + Gemini多时间框架分析互补
    """

    mode: str = "fusion"
    default_provider: str = "deepseek"
    fusion_providers: list = field(
        default_factory=lambda: ["deepseek", "gemini"]
    )
    fusion_strategy: str = "consensus_boosted"
    fusion_threshold: float = 0.5
    fusion_weights: dict = field(
        default_factory=lambda: {"deepseek": 0.55, "gemini": 0.45}
    )


@dataclass
class BuyConditionsConfig:
    """买入条件配置"""

    # 常规模式
    regular_trend_strength_min: float = 0.2
    regular_rsi_max: float = RSI_BUY_REGULAR_MAX
    regular_bb_position_max: float = 0.65
    regular_adx_min: float = 15
    regular_momentum_min: float = 0.005

    # 超卖反弹模式
    oversold_enabled: bool = True
    oversold_rsi_max: float = RSI_BUY_OVERSOLD_MAX
    oversold_momentum_min: float = 0.005
    oversold_trend_strength_min: float = 0.1
    oversold_bb_position_max: float = 0.45
    oversold_position_factor: float = 0.5

    # 强势支撑模式
    support_enabled: bool = True
    support_price_position_max: float = 0.20
    support_rsi_max: float = RSI_BUY_SUPPORT_MAX
    support_momentum_min: float = 0.003
    support_position_factor: float = 0.7

    # 趋势确认模式
    confirmation_enabled: bool = True
    confirmation_consecutive_up: int = 3
    confirmation_rsi_max: float = RSI_BUY_CONFIRM_MAX
    confirmation_position_factor: float = 0.8


@dataclass
class SellConditionsConfig:
    """卖出条件配置"""

    # 止损
    stop_loss_percent: float = 0.02
    stop_loss_profit_percent: float = 0.01
    stop_loss_tolerance_percent: float = 0.001

    # 止盈
    take_profit_percent: float = 0.06
    take_profit_partial_percent: float = 0.04
    take_profit_rsi_threshold: float = RSI_TAKE_PROFIT

    # 风险规避
    risk_rsi_overbought: float = RSI_RISK_OVERBOUGHT
    risk_rsi_high: float = RSI_RISK_HIGH
    risk_bb_position_max: float = 0.90
    risk_bb_position_high: float = 0.85
    risk_trend_down_strength: float = 0.4
    risk_macd_negative: float = -0.002
    risk_drawdown_percent: float = 0.01

    # 减仓
    partial_sell_enabled: bool = True
    partial_sell_factor: float = 0.5


@dataclass
class FusionConfig:
    """融合配置"""

    strategy: str = "consensus_boosted"
    threshold: float = 0.5
    consensus_boost_full: float = 1.3
    consensus_boost_partial: float = 1.15
    default_confidence: int = 70


@dataclass
class TrendDetectionConfig:
    """趋势检测配置"""

    periods: list = field(default_factory=lambda: [10, 20, 50])
    reversal_enabled: bool = True
    reversal_window: int = 3
    reversal_momentum_threshold: float = 0.008
    rsi_oversold: float = RSI_OVERSOLD
    rsi_rebound_threshold: float = 3
    price_position_low: float = 0.25


@dataclass
class SignalOptimizerConfig:
    """信号优化器配置"""

    confidence_floor: float = 0.40
    confidence_ceiling: float = 0.95
    rapid_change_threshold: float = 0.3
    smoothing_window: int = 3
    smoothing_enabled: bool = True
    volatility_adjustment: bool = True
    high_volatility_threshold: float = 0.03
    consecutive_limit: int = 3
    cooldown_period: int = 2


@dataclass
class BacktestConfigConfig:
    """回测配置"""

    initial_capital: float = 10000
    position_size: float = 0.1
    stop_loss_percent: float = 0.02
    take_profit_percent: float = 0.06
    min_confidence_threshold: float = 0.5
    fee_percent: float = 0.001


class AIConfigManager:
    """
    AI配置管理器

    功能：
    1. 统一管理所有AI相关配置
    2. 支持YAML配置
    3. 支持环境变量覆盖
    4. 支持配置热重载
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        初始化配置管理器

        Args:
            config_path: YAML配置文件路径
        """
        self.config_path = config_path
        self._load_default_config()

        # 如果有配置文件，尝试加载
        if config_path and os.path.exists(config_path):
            self.load_from_yaml(config_path)
        else:
            logger.info("[配置管理器] 未找到配置文件，使用默认配置")

        # 应用环境变量覆盖
        self._apply_env_overrides()

        logger.info(f"[配置管理器] 初始化完成")

    def _load_default_config(self) -> None:
        """加载默认配置"""
        self.ai = AIConfig()
        self.buy_conditions = BuyConditionsConfig()
        self.sell_conditions = SellConditionsConfig()
        self.fusion = FusionConfig()
        self.trend_detection = TrendDetectionConfig()
        self.signal_optimizer = SignalOptimizerConfig()
        self.backtest = BacktestConfigConfig()

    def load_from_yaml(self, path: str) -> bool:
        """
        从YAML文件加载配置

        Args:
            path: YAML文件路径

        Returns:
            bool: 是否加载成功
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                config_data = yaml.safe_load(f)

            if not config_data:
                logger.warning(f"[配置管理器] 配置文件为空: {path}")
                return False

            # 解析各部分配置
            if "ai" in config_data:
                self._parse_ai_config(config_data["ai"])

            if "buy_conditions" in config_data:
                self._parse_buy_conditions(config_data["buy_conditions"])

            if "sell_conditions" in config_data:
                self._parse_sell_conditions(config_data["sell_conditions"])

            if "fusion" in config_data:
                self._parse_fusion_config(config_data["fusion"])

            if "trend_detection" in config_data:
                self._parse_trend_detection(config_data["trend_detection"])

            if "signal_optimizer" in config_data:
                self._parse_signal_optimizer(config_data["signal_optimizer"])

            if "backtest" in config_data:
                self._parse_backtest_config(config_data["backtest"])

            logger.info(f"[配置管理器] 从YAML加载配置成功: {path}")
            return True

        except Exception as e:
            logger.error(f"[配置管理器] 加载配置失败: {e}")
            return False

    def _parse_ai_config(self, data: Dict[str, Any]) -> None:
        """解析AI配置"""
        if "mode" in data:
            self.ai.mode = data["mode"]
        if "default_provider" in data:
            self.ai.default_provider = data["default_provider"]
        if "fusion_providers" in data:
            self.ai.fusion_providers = data["fusion_providers"]
        if "fusion_strategy" in data:
            self.ai.fusion_strategy = data["fusion_strategy"]
        if "fusion_threshold" in data:
            self.ai.fusion_threshold = float(data["fusion_threshold"])
        if "fusion_weights" in data:
            self.ai.fusion_weights = data["fusion_weights"]

    def _parse_buy_conditions(self, data: Dict[str, Any]) -> None:
        """解析买入条件配置"""
        for key, value in data.items():
            if hasattr(self.buy_conditions, key):
                setattr(self.buy_conditions, key, value)

    def _parse_sell_conditions(self, data: Dict[str, Any]) -> None:
        """解析卖出条件配置"""
        for key, value in data.items():
            if hasattr(self.sell_conditions, key):
                setattr(self.sell_conditions, key, value)

    def _parse_fusion_config(self, data: Dict[str, Any]) -> None:
        """解析融合配置"""
        for key, value in data.items():
            if hasattr(self.fusion, key):
                setattr(self.fusion, key, value)

    def _parse_trend_detection(self, data: Dict[str, Any]) -> None:
        """解析趋势检测配置"""
        for key, value in data.items():
            if hasattr(self.trend_detection, key):
                setattr(self.trend_detection, key, value)

    def _parse_signal_optimizer(self, data: Dict[str, Any]) -> None:
        """解析信号优化器配置"""
        for key, value in data.items():
            if hasattr(self.signal_optimizer, key):
                setattr(self.signal_optimizer, key, value)

    def _parse_backtest_config(self, data: Dict[str, Any]) -> None:
        """解析回测配置"""
        for key, value in data.items():
            if hasattr(self.backtest, key):
                setattr(self.backtest, key, value)

    def _apply_env_overrides(self) -> None:
        """应用环境变量覆盖"""
        env_mappings = {
            "AI_MODE": ("ai", "mode"),
            "AI_DEFAULT_PROVIDER": ("ai", "default_provider"),
            "AI_FUSION_PROVIDERS": ("ai", "fusion_providers"),
            "AI_FUSION_STRATEGY": ("ai", "fusion_strategy"),
            "AI_FUSION_THRESHOLD": ("ai", "fusion_threshold"),
            "AI_BUY_TREND_STRENGTH": ("buy_conditions", "regular_trend_strength_min"),
            "AI_BUY_RSI_THRESHOLD": ("buy_conditions", "regular_rsi_max"),
            "AI_SELL_STOP_LOSS": ("sell_conditions", "stop_loss_percent"),
            "AI_SELL_TAKE_PROFIT": ("sell_conditions", "take_profit_percent"),
        }

        for env_key, (config_attr, _) in env_mappings.items():
            value = os.getenv(env_key)
            if value is not None:
                self._set_nested_attr(config_attr, env_key, value)

    def _set_nested_attr(self, attr_path: str, env_key: str, value: str) -> None:
        """设置嵌套属性"""
        parts = attr_path.split(".")
        obj = self

        for part in parts[:-1]:
            if hasattr(obj, part):
                obj = getattr(obj, part)

        final_attr = parts[-1]
        if hasattr(obj, final_attr):
            # 类型转换
            current_value = getattr(obj, final_attr)
            if isinstance(current_value, bool):
                setattr(obj, final_attr, value.lower() in ["true", "1", "yes"])
            elif isinstance(current_value, float):
                setattr(obj, final_attr, float(value))
            elif isinstance(current_value, int):
                setattr(obj, final_attr, int(value))
            else:
                setattr(obj, final_attr, value)

            logger.info(
                f"[配置管理器] 环境变量覆盖: {env_key} -> {attr_path} = {value}"
            )

    def save_to_yaml(self, path: str) -> bool:
        """
        保存配置到YAML文件

        Args:
            path: 输出路径

        Returns:
            bool: 是否保存成功
        """
        try:
            config_data = {
                "ai": {
                    "mode": self.ai.mode,
                    "default_provider": self.ai.default_provider,
                    "fusion_providers": self.ai.fusion_providers,
                    "fusion_strategy": self.ai.fusion_strategy,
                    "fusion_threshold": self.ai.fusion_threshold,
                    "fusion_weights": self.ai.fusion_weights,
                },
                "buy_conditions": self._dataclass_to_dict(self.buy_conditions),
                "sell_conditions": self._dataclass_to_dict(self.sell_conditions),
                "fusion": self._dataclass_to_dict(self.fusion),
                "trend_detection": self._dataclass_to_dict(self.trend_detection),
                "signal_optimizer": self._dataclass_to_dict(self.signal_optimizer),
                "backtest": self._dataclass_to_dict(self.backtest),
            }

            with open(path, "w", encoding="utf-8") as f:
                yaml.dump(config_data, f, allow_unicode=True, indent=2)

            logger.info(f"[配置管理器] 保存配置成功: {path}")
            return True

        except Exception as e:
            logger.error(f"[配置管理器] 保存配置失败: {e}")
            return False

    def _dataclass_to_dict(self, obj) -> Dict[str, Any]:
        """将dataclass转换为字典"""
        result = {}
        for field_name, field_value in obj.__dataclass_fields__.items():
            value = getattr(obj, field_name)
            if hasattr(value, "__dataclass_fields__"):
                result[field_name] = self._dataclass_to_dict(value)
            elif isinstance(value, list):
                result[field_name] = value
            elif isinstance(value, (int, float, str, bool)):
                result[field_name] = value
        return result

    def get_config_summary(self) -> Dict[str, Any]:
        """获取配置摘要"""
        return {
            "ai": {
                "mode": self.ai.mode,
                "default_provider": self.ai.default_provider,
                "fusion_providers": self.ai.fusion_providers,
                "fusion_strategy": self.ai.fusion_strategy,
                "fusion_threshold": self.ai.fusion_threshold,
            },
            "buy_conditions": {
                "regular_trend_strength_min": self.buy_conditions.regular_trend_strength_min,
                "regular_rsi_max": self.buy_conditions.regular_rsi_max,
                "oversold_enabled": self.buy_conditions.oversold_enabled,
                "oversold_rsi_max": self.buy_conditions.oversold_rsi_max,
                "support_enabled": self.buy_conditions.support_enabled,
                "confirmation_enabled": self.buy_conditions.confirmation_enabled,
            },
            "sell_conditions": {
                "stop_loss_percent": self.sell_conditions.stop_loss_percent,
                "take_profit_percent": self.sell_conditions.take_profit_percent,
                "partial_sell_enabled": self.sell_conditions.partial_sell_enabled,
            },
            "fusion": {
                "strategy": self.fusion.strategy,
                "threshold": self.fusion.threshold,
                "consensus_boost_full": self.fusion.consensus_boost_full,
            },
            "trend_detection": {
                "reversal_enabled": self.trend_detection.reversal_enabled,
                "rsi_oversold": self.trend_detection.rsi_oversold,
            },
            "signal_optimizer": {
                "confidence_floor": self.signal_optimizer.confidence_floor,
                "smoothing_enabled": self.signal_optimizer.smoothing_enabled,
                "volatility_adjustment": self.signal_optimizer.volatility_adjustment,
            },
            "backtest": {
                "initial_capital": self.backtest.initial_capital,
                "position_size": self.backtest.position_size,
            },
        }

    def print_config_summary(self) -> None:
        """打印配置摘要"""
        summary = self.get_config_summary()
        print("\n" + "=" * 60)
        print("AI配置摘要")
        print("=" * 60)

        for section, values in summary.items():
            print(f"\n[{section}]")
            for key, value in values.items():
                if isinstance(value, float):
                    if value < 1:
                        print(f"  {key}: {value:.2%}")
                    else:
                        print(f"  {key}: {value}")
                elif isinstance(value, list):
                    print(f"  {key}: {value}")
                else:
                    print(f"  {key}: {value}")

        print("\n" + "=" * 60)

    def reload(self) -> bool:
        """重新加载配置"""
        self._load_default_config()

        if self.config_path and os.path.exists(self.config_path):
            return self.load_from_yaml(self.config_path)

        self._apply_env_overrides()
        return True


def load_ai_config(config_path: Optional[str] = None) -> AIConfigManager:
    """
    加载AI配置

    Args:
        config_path: YAML配置文件路径

    Returns:
        AIConfigManager: 配置管理器实例
    """
    return AIConfigManager(config_path)


def create_default_config(path: str) -> bool:
    """
    创建默认配置文件

    Args:
        path: 输出路径

    Returns:
        bool: 是否创建成功
    """
    manager = AIConfigManager()
    return manager.save_to_yaml(path)
