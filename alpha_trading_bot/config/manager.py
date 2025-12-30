"""
配置管理器 - 统一管理所有配置
"""

import os
from typing import Dict, Any, Optional
from dotenv import load_dotenv

from .models import (
    ConfigValidationResult,
    ExchangeConfig,
    TradingConfig,
    StrategyConfig,
    RiskConfig,
    AIConfig,
    SystemConfig,
    NetworkConfig
)

from ..utils import get_logger

logger = get_logger(__name__)

# 加载环境变量
load_dotenv()

class ConfigManager:
    """配置管理器"""

    def __init__(self):
        """初始化配置管理器"""
        self._exchange = self._load_exchange_config()
        self._trading = self._load_trading_config()
        self._strategies = self._load_strategy_config()
        self._risk = self._load_risk_config()
        self._ai = self._load_ai_config()
        self._system = self._load_system_config()
        self._network = self._load_network_config()

        # 验证配置
        validation_result = self._validate_config()
        if not validation_result.is_valid:
            # 在非测试环境下才抛出错误
            import sys
            if 'pytest' not in sys.modules:
                raise ValueError(f"配置验证失败: {validation_result.errors}")
            else:
                # 测试环境下只记录警告
                logger.warning(f"配置验证失败: {validation_result.errors}")

    def _load_exchange_config(self) -> ExchangeConfig:
        """加载交易所配置"""
        return ExchangeConfig(
            exchange='okx',
            api_key=os.getenv('OKX_API_KEY', ''),
            secret=os.getenv('OKX_SECRET', ''),
            password=os.getenv('OKX_PASSWORD', ''),
            sandbox=os.getenv('OKX_SANDBOX', 'false').lower() == 'true',
            symbol='BTC/USDT:USDT',
            timeframe='5m',
            contract_size=0.01
        )

    def _load_trading_config(self) -> TradingConfig:
        """加载交易配置"""
        return TradingConfig(
            test_mode=os.getenv('TEST_MODE', 'true').lower() == 'true',
            max_position_size=float(os.getenv('MAX_POSITION_SIZE', '0.01')),
            min_trade_amount=float(os.getenv('MIN_TRADE_AMOUNT', '0.0005')),
            leverage=int(os.getenv('LEVERAGE', '10')),
            cycle_minutes=int(os.getenv('CYCLE_MINUTES', '15')),
            random_offset_enabled=os.getenv('RANDOM_OFFSET_ENABLED', 'true').lower() == 'true',
            random_offset_range=int(os.getenv('RANDOM_OFFSET_RANGE', '180')),
            margin_mode='cross',
            position_mode='one_way',
            allow_short_selling=os.getenv('ALLOW_SHORT_SELLING', 'false').lower() == 'true'
        )

    def _load_strategy_config(self) -> StrategyConfig:
        """加载策略配置 - 根据投资类型自动设置止盈止损"""
        investment_type = os.getenv('INVESTMENT_TYPE', 'conservative')

        # 验证投资类型
        valid_types = ['conservative', 'moderate', 'aggressive']
        if investment_type not in valid_types:
            logger.warning(f"无效的投资类型 '{investment_type}'，使用默认值 'conservative'")
            investment_type = 'conservative'

        # 根据投资类型设置止盈止损百分比（预设配置）
        if investment_type == 'conservative':
            take_profit_percent = 0.06  # 6% 止盈
            stop_loss_percent = 0.005   # 0.5% 止损
            description = "稳健型策略 - 低波动，追求稳健收益"
        elif investment_type == 'moderate':
            take_profit_percent = 0.08  # 8% 止盈
            stop_loss_percent = 0.01    # 1% 止损
            description = "中等型策略 - 平衡风险与收益"
        elif investment_type == 'aggressive':
            take_profit_percent = 0.12  # 12% 止盈
            stop_loss_percent = 0.02    # 2% 止损
            description = "激进型策略 - 高风险高收益"

        logger.info(f"策略配置: 投资类型={investment_type} - {description}")

        # 加载止盈止损配置
        take_profit_env = os.getenv('TAKE_PROFIT_ENABLED', 'true')
        stop_loss_env = os.getenv('STOP_LOSS_ENABLED', 'true')
        logger.info(f"调试 - 环境变量原始值: TAKE_PROFIT_ENABLED={take_profit_env}, STOP_LOSS_ENABLED={stop_loss_env}")
        take_profit_enabled = take_profit_env.lower() == 'true'
        stop_loss_enabled = stop_loss_env.lower() == 'true'
        take_profit_mode = os.getenv('TAKE_PROFIT_MODE', 'smart').lower()
        stop_loss_mode = os.getenv('STOP_LOSS_MODE', 'smart').lower()

        # 根据模式和投资类型加载具体配置
        investment_type_prefix = investment_type.upper()

        # 普通模式配置
        normal_tp_key = f'{investment_type_prefix}_NORMAL_TP_PERCENT'
        normal_sl_key = f'{investment_type_prefix}_NORMAL_SL_PERCENT'
        normal_take_profit_percent = float(os.getenv(normal_tp_key, str(take_profit_percent * 100))) / 100
        normal_stop_loss_percent = float(os.getenv(normal_sl_key, str(stop_loss_percent * 100))) / 100

        # 智能模式-固定模式配置
        smart_fixed_tp_key = f'{investment_type_prefix}_SMART_FIXED_TP_PERCENT'
        smart_fixed_sl_key = f'{investment_type_prefix}_SMART_FIXED_SL_PERCENT'
        smart_fixed_take_profit_percent = float(os.getenv(smart_fixed_tp_key, str(take_profit_percent * 100))) / 100
        smart_fixed_stop_loss_percent = float(os.getenv(smart_fixed_sl_key, str(stop_loss_percent * 100))) / 100

        # 智能模式-多级模式配置
        smart_multi_levels_key = f'{investment_type_prefix}_SMART_MULTI_TP_LEVELS'
        smart_multi_ratios_key = f'{investment_type_prefix}_SMART_MULTI_TP_RATIOS'
        smart_multi_levels_str = os.getenv(smart_multi_levels_key, '3,6,10')
        smart_multi_ratios_str = os.getenv(smart_multi_ratios_key, '0.3,0.3,0.4')

        try:
            smart_multi_take_profit_levels = [float(x.strip()) / 100 for x in smart_multi_levels_str.split(',')]
            smart_multi_take_profit_ratios = [float(x.strip()) for x in smart_multi_ratios_str.split(',')]

            # 验证比例总和为1.0
            if abs(sum(smart_multi_take_profit_ratios) - 1.0) > 0.001:
                logger.warning(f"多级止盈比例总和不为1.0，当前总和: {sum(smart_multi_take_profit_ratios)}")
                # 根据投资类型使用默认比例
                if investment_type == 'conservative':
                    smart_multi_take_profit_ratios = [0.6, 0.3, 0.1]  # 保守型：前期多平仓
                elif investment_type == 'aggressive':
                    smart_multi_take_profit_ratios = [0.2, 0.3, 0.5]  # 激进型：后期多平仓
                else:
                    smart_multi_take_profit_ratios = [0.4, 0.3, 0.3]  # 中等型：平衡配置
        except ValueError:
            logger.warning(f"解析多级止盈配置失败，使用{investment_type}默认值")
            if investment_type == 'conservative':
                smart_multi_take_profit_levels = [0.02, 0.05, 0.08]  # 2%, 5%, 8%
                smart_multi_take_profit_ratios = [0.6, 0.3, 0.1]     # 60%, 30%, 10%
            elif investment_type == 'aggressive':
                smart_multi_take_profit_levels = [0.05, 0.10, 0.15]  # 5%, 10%, 15%
                smart_multi_take_profit_ratios = [0.2, 0.3, 0.5]     # 20%, 30%, 50%
            else:  # moderate
                smart_multi_take_profit_levels = [0.03, 0.06, 0.10]  # 3%, 6%, 10%
                smart_multi_take_profit_ratios = [0.4, 0.3, 0.3]     # 40%, 30%, 30%

        # 记录配置信息
        logger.info(f"止盈止损配置: 止盈启用={take_profit_enabled}, 止损启用={stop_loss_enabled}")
        logger.info(f"止盈模式={take_profit_mode}, 止损模式={stop_loss_mode}")

        if take_profit_enabled:
            if take_profit_mode == 'normal':
                logger.info(f"普通模式止盈: {normal_take_profit_percent*100:.0f}%")
            else:  # smart mode
                logger.info(f"智能模式-固定止盈: {smart_fixed_take_profit_percent*100:.0f}%")
                logger.info(f"智能模式-多级止盈: {[f'{l*100:.0f}%' for l in smart_multi_take_profit_levels]}")

        if stop_loss_enabled:
            if stop_loss_mode == 'normal':
                logger.info(f"普通模式止损: {normal_stop_loss_percent*100:.0f}%")
            else:  # smart mode
                logger.info(f"智能模式-固定止损: {smart_fixed_stop_loss_percent*100:.0f}%")

        # 通用配置
        enable_profit_lock = os.getenv('ENABLE_PROFIT_LOCK', 'true').lower() == 'true'
        profit_lock_threshold = float(os.getenv('PROFIT_LOCK_THRESHOLD', '0.05'))

        return StrategyConfig(
            investment_type=investment_type,
            profit_lock_enabled=True,
            sell_signal_enabled=True,
            buy_signal_enabled=True,
            consolidation_protection_enabled=True,
            smart_tp_sl_enabled=os.getenv('SMART_TP_SL_ENABLED', 'true').lower() == 'true',
            limit_order_enabled=os.getenv('LIMIT_ORDER_ENABLED', 'true').lower() == 'true',
            price_crash_protection_enabled=True,
            # 止盈止损总开关
            take_profit_enabled=take_profit_enabled,
            stop_loss_enabled=stop_loss_enabled,
            # 止盈止损模式
            take_profit_mode=take_profit_mode,
            stop_loss_mode=stop_loss_mode,
            # 普通模式配置
            normal_take_profit_percent=normal_take_profit_percent,
            normal_stop_loss_percent=normal_stop_loss_percent,
            # 智能模式-固定模式配置
            smart_fixed_take_profit_percent=smart_fixed_take_profit_percent,
            smart_fixed_stop_loss_percent=smart_fixed_stop_loss_percent,
            # 智能模式-多级模式配置
            smart_multi_take_profit_levels=smart_multi_take_profit_levels,
            smart_multi_take_profit_ratios=smart_multi_take_profit_ratios,
            # 利润锁定配置
            enable_profit_lock=enable_profit_lock,
            profit_lock_threshold=profit_lock_threshold,
            # 自适应止损配置
            adaptive_stop_loss_enabled=os.getenv('ADAPTIVE_STOP_LOSS_ENABLED', 'true').lower() == 'true',
            up_trend_stop_loss=float(os.getenv('UP_TREND_STOP_LOSS', '0.002')),
            down_trend_stop_loss=float(os.getenv('DOWN_TREND_STOP_LOSS', '0.01')),
            # 止盈策略配置
            profit_taking_strategy='multi_level' if smart_multi_take_profit_levels else 'single_level',
            profit_taking_levels=smart_multi_take_profit_levels
        )

    def _load_risk_config(self) -> RiskConfig:
        """加载风险控制配置"""
        return RiskConfig(
            max_daily_loss=float(os.getenv('MAX_DAILY_LOSS', '100')),
            max_position_risk=float(os.getenv('MAX_POSITION_RISK', '0.05')),
            stop_loss_enabled=True,
            take_profit_enabled=True,
            trailing_stop_enabled=True,
            trailing_distance=0.015
        )

    def _load_ai_config(self) -> AIConfig:
        """加载AI配置"""
        # 解析AI融合提供商列表
        fusion_providers_str = os.getenv('AI_FUSION_PROVIDERS', 'deepseek,kimi')
        fusion_providers = [p.strip() for p in fusion_providers_str.split(',') if p.strip()]

        # 解析AI融合权重
        fusion_weights_str = os.getenv('AI_FUSION_WEIGHTS', '')
        fusion_weights = {}
        if fusion_weights_str:
            try:
                for item in fusion_weights_str.split(','):
                    if ':' in item:
                        provider, weight = item.split(':', 1)
                        fusion_weights[provider.strip()] = float(weight.strip())
            except ValueError:
                logger.warning(f"AI融合权重格式错误: {fusion_weights_str}")

        # 构建AI模型配置
        models = {
            'kimi': os.getenv('KIMI_API_KEY', ''),
            'deepseek': os.getenv('DEEPSEEK_API_KEY', ''),
            'qwen': os.getenv('QWEN_API_KEY', ''),
            'openai': os.getenv('OPENAI_API_KEY', '')
        }
        # 过滤掉空的API密钥
        models = {k: v for k, v in models.items() if v}

        # 获取AI模式配置
        ai_mode = os.getenv('AI_MODE', 'fusion')

        # 根据AI模式设置相应的配置
        if ai_mode == 'fusion':
            use_multi_ai = True
            use_multi_ai_fusion = True
        else:  # single mode
            use_multi_ai = False
            use_multi_ai_fusion = False

        return AIConfig(
            use_multi_ai=use_multi_ai,
            cache_duration=int(os.getenv('AI_CACHE_DURATION', '900')),
            timeout=int(os.getenv('AI_TIMEOUT', '30')),
            max_retries=int(os.getenv('AI_MAX_RETRIES', '2')),
            min_confidence_threshold=float(os.getenv('AI_MIN_CONFIDENCE', '0.3')),
            ai_provider=os.getenv('AI_DEFAULT_PROVIDER', 'deepseek'),  # 使用新的AI_DEFAULT_PROVIDER
            fallback_enabled=os.getenv('AI_FALLBACK_ENABLED', 'true').lower() == 'true',
            models=models,
            # AI融合配置
            use_multi_ai_fusion=use_multi_ai_fusion,
            ai_default_provider=os.getenv('AI_DEFAULT_PROVIDER', 'deepseek'),
            ai_fusion_providers=fusion_providers,
            ai_fusion_weights=fusion_weights if fusion_weights else None,
            ai_fusion_strategy=os.getenv('AI_FUSION_STRATEGY', 'weighted'),
            ai_fusion_threshold=float(os.getenv('AI_FUSION_THRESHOLD', '0.6'))
        )

    def _load_system_config(self) -> SystemConfig:
        """加载系统配置"""
        return SystemConfig(
            max_history_length=100,
            log_level=os.getenv('LOG_LEVEL', 'INFO'),
            monitoring_enabled=True,
            web_interface_enabled=os.getenv('WEB_ENABLED', 'false').lower() == 'true',
            web_port=int(os.getenv('WEB_PORT', '8501'))
        )

    def _load_network_config(self) -> NetworkConfig:
        """加载网络配置"""
        return NetworkConfig(
            proxy_enabled=os.getenv('PROXY_ENABLED', 'false').lower() == 'true',
            http_proxy=os.getenv('HTTP_PROXY'),
            https_proxy=os.getenv('HTTPS_PROXY'),
            timeout=int(os.getenv('NETWORK_TIMEOUT', '30')),
            max_retries=int(os.getenv('NETWORK_MAX_RETRIES', '3')),
            retry_delay=int(os.getenv('NETWORK_RETRY_DELAY', '1'))
        )

    def _validate_config(self) -> ConfigValidationResult:
        """验证配置"""
        errors = []
        warnings = []

        # 验证交易所配置
        if not self._exchange.api_key:
            errors.append("缺少OKX API密钥")
        if not self._exchange.secret:
            errors.append("缺少OKX密钥")
        if not self._exchange.password:
            errors.append("缺少OKX交易密码")

        # 验证交易配置
        if self._trading.max_position_size <= 0:
            errors.append("最大仓位必须大于0")
        if self._trading.leverage <= 0:
            errors.append("杠杆倍数必须大于0")

        return ConfigValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )

    @property
    def exchange(self) -> ExchangeConfig:
        """获取交易所配置"""
        return self._exchange

    @property
    def trading(self) -> TradingConfig:
        """获取交易配置"""
        return self._trading

    @property
    def strategies(self) -> StrategyConfig:
        """获取策略配置"""
        return self._strategies

    @property
    def risk(self) -> RiskConfig:
        """获取风险控制配置"""
        return self._risk

    @property
    def ai(self) -> AIConfig:
        """获取AI配置"""
        return self._ai

    @property
    def system(self) -> SystemConfig:
        """获取系统配置"""
        return self._system

    @property
    def network(self) -> NetworkConfig:
        """获取网络配置"""
        return self._network

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return {
            'exchange': self._exchange.__dict__,
            'trading': self._trading.__dict__,
            'strategies': self._strategies.__dict__,
            'risk': self._risk.__dict__,
            'ai': self._ai.__dict__,
            'system': self._system.__dict__,
            'network': self._network.__dict__
        }

# 全局配置实例
_config_manager = None

def load_config() -> ConfigManager:
    """加载配置管理器"""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager