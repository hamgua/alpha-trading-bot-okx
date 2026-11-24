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
    order_confirm_timeout_seconds: float = 5.0
    order_confirm_poll_interval_seconds: float = 0.25
    # 24h 涨幅(%)上限：超过该值时禁止新开空单（逆势做空 R/R 极差，
    # 2026-09-18 日志: +5.22% 大阳线日逆势做空 -1.02% 止损）。
    # 0=关闭门禁。
    short_entry_max_daily_change: float = 1.5
    # ---- P1 风控与决策日志（2026-10-04 双向交易 spec）----
    decision_journal_enabled: bool = True  # 决策日志开关（DECISION_JOURNAL）
    risk_drawdown_halt: float = 0.30  # 回撤停机阈值：权益相对高水位回撤≥30% 禁止新开仓
    risk_per_trade_max: float = 0.10  # 单笔风险上限：止损触发预期亏损 ≤ 账户 10%
    risk_resume: bool = False  # 手动恢复：RISK_RESUME=true 或 1 + 重启后清除停机状态
    # ---- 执行层置信度门禁（2026-10-08 手续费出血修复 / P0-1）----
    # BUY 开仓 / SELL 平仓仅在最终置信度 >= 门禁时执行（0=关闭该门禁）。
    # 证据: 4 天 8 个往返信号毛利 +$0.0005 / 手续费 -$0.1351；8 笔 SELL
    # 平仓最终置信度 54-67%（全部 <0.75）直接触发市价平仓，8 笔 BUY
    # 开仓全部为 LLM hold 翻转（最终 51-79%）。执行层此前零门禁。
    min_confidence_open: float = 0.65
    min_confidence_close: float = 0.60
    # ---- 每日新开仓上限（2026-11 底部捕获配套 / 成本防护）----
    # 门禁下调 (0.75→0.65) 后配套的成本控制: 每日最多新开仓 N 笔 (0=关闭)。
    # 手续费出血的根源是高频 churn, 而非单笔开仓; 限频 + 置信度门禁
    # 双保险, 比单一高门禁更精细 (高门禁曾导致 55k 底部 6 天零交易)。
    daily_open_limit: int = 2
    # ---- 超卖抄底独立通道（2026-11 底部捕获 / P1-5）----
    # RSI≤rsi_max 且价格位于 24h 低点 near_low_pct 以内 → 技术独立触发
    # 抄底 (固定置信度 + 半仓 + 每日最多 1 次), 绕过 AI 置信度门禁。
    # 回放: 11-21 14:14 RSI=16.2 / 55647=24h 最低区, 原流水线 5 层折扣后
    # 66.5% < 0.75 被拦, 错过 55.6k→60.7k (+9.1%) 反弹。
    # 仅保留: 回撤总闸 / 平仓冷却 / 每日开仓上限 / 实盘闸门。
    oversold_buy_enabled: bool = True
    oversold_buy_rsi_max: float = 20.0
    oversold_buy_near_low_pct: float = 0.01  # 价格 ≤ 24h低点×(1+1%)
    oversold_buy_confidence: float = 0.70  # 通道固定置信度 (仅用于审计日志)
    oversold_buy_position_factor: float = 0.5  # 半仓
    oversold_buy_daily_limit: int = 1  # 每日最多触发次数
    # 1h 动量守卫（2026-11-24 回放 / P1-6）: 1h 涨跌幅 ≤ 该值时跳过抄底
    # (动量仍在崩塌、接飞刀)。回放 11-24 11:03: 1h +0.12% 通过。
    oversold_buy_min_1h_change: float = -0.05
    # ---- R/R 感知动态开仓门禁（2026-11-24 日志回放 / P0-3）----
    # 方向一致的结构 R/R ≥ gate_relief_rr_min 时, 开仓置信度门禁放宽
    # gate_relief_amount (下限 gate_relief_floor)。依据: 两天回放 217 周期
    # 最终置信度 46-72% (均值 58.5%), 固定 0.65 门禁仅 15/217 通过且全为
    # HOLD; 高 R/R  setups 应放行 55-64% 犹豫带置信度。
    gate_relief_rr_min: float = 2.0
    gate_relief_amount: float = 0.10
    gate_relief_floor: float = 0.50
    # ---- 亏损态平仓门禁下移（2026-11-24 13:43-14:15 回放 / P0-A）----
    # 持仓浮亏 (UPL < 0) 时, 平仓门禁下移 close_relief_amount
    # (下限 close_relief_floor)。回放: 浮亏 -0.21%/-0.43% 时 AI 连续三次
    # SELL (最终 51%/55%/57%) 全被 0.60 门禁拦截, 直到 AI 原始置信度 78%
    # (最终 60.0%) 才放行, 吃满 -0.42% 阴跌 (账户 -1.3%)。放宽只作用于
    # "离场": 重开仍受 post_close_cooldown 约束, 不引入 churn。
    close_relief_amount: float = 0.10
    close_relief_floor: float = 0.40
    # ---- 高潮做空独立通道（2026-11-24 日志回放 / P0-2）----
    # "Climax top 做空": 价格贴近 24h 高点 + 1h RSI 超买 + 做空 R/R ≥ 阈值
    # → 独立规则开空 (半仓, 每日 N 次), 与超卖抄底通道对称 (顶部捕获)。
    # 回放依据: 11-23 22:00-23:57 做空 R/R 3.0-7.1 (excellent), RSI(1h) 67-78,
    # 价格处 24h 高点区, 随后 11-24 62.8k→59.5k (-5.3%) 两天主跌段;
    # 误报排除: 11-23 02:14 做空 R/R=4.36 但 RSI≈50 (<65), 实际随后涨 5.6%, 正确排除。
    climax_short_enabled: bool = True
    climax_short_rr_min: float = 2.5
    climax_short_rsi_min: float = 65.0  # 1h RSI 超买门槛
    climax_short_near_high_pct: float = 0.02  # 价格 ≥ 24h高点×(1-2%)
    climax_short_position_factor: float = 0.5  # 半仓
    climax_short_daily_limit: int = 1  # 每日最多触发次数
    # ---- 平仓后冷却（2026-10-08 手续费出血修复 / P0-2）----
    # 平仓后 N 分钟内禁止重新开仓（0=关闭），斩断"平仓后 5 分钟即重开"
    # 式 churn（证据: T3→T4 间隔 5 分钟，T7 持仓仅 4.4 分钟）。
    post_close_cooldown_minutes: int = 30

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
        if self.order_confirm_timeout_seconds <= 0:
            errors.append("订单确认超时必须大于0")
        if self.order_confirm_poll_interval_seconds <= 0:
            errors.append("订单确认轮询间隔必须大于0")
        if self.short_entry_max_daily_change < 0:
            errors.append(
                "short_entry_max_daily_change "
                f"({self.short_entry_max_daily_change}) 不能为负数 (0=关闭门禁)"
            )
        if not 0 < self.risk_drawdown_halt < 1:
            errors.append(
                f"risk_drawdown_halt ({self.risk_drawdown_halt}) 不在有效范围 (0-1)"
            )
        if not 0 < self.risk_per_trade_max <= 1:
            errors.append(
                f"risk_per_trade_max ({self.risk_per_trade_max}) 不在有效范围 (0-1]"
            )
        if (
            self.order_confirm_poll_interval_seconds
            > self.order_confirm_timeout_seconds
        ):
            errors.append("订单确认轮询间隔不能大于确认超时")

        if not 0 <= self.min_confidence_open <= 1:
            errors.append(
                f"min_confidence_open ({self.min_confidence_open}) 不在有效范围 [0-1]"
            )
        if not 0 <= self.min_confidence_close <= 1:
            errors.append(
                f"min_confidence_close ({self.min_confidence_close}) 不在有效范围 [0-1]"
            )
        if self.daily_open_limit < 0:
            errors.append(
                f"daily_open_limit ({self.daily_open_limit}) 不能为负数 (0=关闭)"
            )
        if not 0 < self.oversold_buy_rsi_max <= 100:
            errors.append(
                f"oversold_buy_rsi_max ({self.oversold_buy_rsi_max}) "
                "不在有效范围 (0-100]"
            )
        if not 0 <= self.oversold_buy_near_low_pct <= 0.2:
            errors.append(
                f"oversold_buy_near_low_pct ({self.oversold_buy_near_low_pct}) "
                "不在有效范围 [0-0.2]"
            )
        if not 0 < self.oversold_buy_position_factor <= 1:
            errors.append(
                f"oversold_buy_position_factor ({self.oversold_buy_position_factor}) "
                "不在有效范围 (0-1]"
            )
        if self.oversold_buy_daily_limit < 0:
            errors.append(
                f"oversold_buy_daily_limit ({self.oversold_buy_daily_limit}) "
                "不能为负数"
            )
        if not 0 <= self.post_close_cooldown_minutes <= 1440:
            errors.append(
                f"post_close_cooldown_minutes ({self.post_close_cooldown_minutes}) "
                "不在有效范围 [0-1440]"
            )
        if not 0 < self.gate_relief_rr_min <= 10:
            errors.append(
                f"gate_relief_rr_min ({self.gate_relief_rr_min}) "
                "不在有效范围 (0-10]"
            )
        if not 0 <= self.gate_relief_amount <= 0.5:
            errors.append(
                f"gate_relief_amount ({self.gate_relief_amount}) "
                "不在有效范围 [0-0.5]"
            )
        if not 0 <= self.gate_relief_floor <= 1:
            errors.append(
                f"gate_relief_floor ({self.gate_relief_floor}) "
                "不在有效范围 [0-1]"
            )
        if not 0 <= self.close_relief_amount <= 0.5:
            errors.append(
                f"close_relief_amount ({self.close_relief_amount}) "
                "不在有效范围 [0-0.5]"
            )
        if not 0 <= self.close_relief_floor <= 1:
            errors.append(
                f"close_relief_floor ({self.close_relief_floor}) "
                "不在有效范围 [0-1]"
            )
        if not -0.5 <= self.oversold_buy_min_1h_change <= 0:
            errors.append(
                f"oversold_buy_min_1h_change ({self.oversold_buy_min_1h_change}) "
                "不在有效范围 [-0.5-0]"
            )
        if not 0 < self.climax_short_rr_min <= 10:
            errors.append(
                f"climax_short_rr_min ({self.climax_short_rr_min}) "
                "不在有效范围 (0-10]"
            )
        if not 0 < self.climax_short_rsi_min <= 100:
            errors.append(
                f"climax_short_rsi_min ({self.climax_short_rsi_min}) "
                "不在有效范围 (0-100]"
            )
        if not 0 < self.climax_short_near_high_pct <= 0.2:
            errors.append(
                f"climax_short_near_high_pct ({self.climax_short_near_high_pct}) "
                "不在有效范围 (0-0.2]"
            )
        if not 0 < self.climax_short_position_factor <= 1:
            errors.append(
                f"climax_short_position_factor ({self.climax_short_position_factor}) "
                "不在有效范围 (0-1]"
            )
        if self.climax_short_daily_limit < 0:
            errors.append(
                f"climax_short_daily_limit ({self.climax_short_daily_limit}) "
                "不能为负数"
            )

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

    # 降级reasoning信号BUY阻断开关(kill-switch)：
    # 当信号来自 reasoning_content 提取(降级)且终态为 BUY 时，降为 HOLD。
    # true=启用阻断(默认)；false=关闭(等同现状)。
    # dream 2026-09-09-okx-loss-optimization / C3（根因 R5: 降级信号泄漏开多）。
    block_degraded_buy: bool = True

    VALID_MODES = ["single", "fusion"]
    VALID_PROVIDERS = [
        "deepseek",
        "kimi",
        "openai",
        "qwen",
        "gemini",
        "minimax",
        "qwen38",
    ]
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
            block_degraded_buy=os.getenv("AI_BLOCK_DEGRADED_BUY", "true").lower()
            == "true",
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
                # 自建 ninfer 服务不校验 key，默认占位即可
                "qwen38": os.getenv("QWEN38_API_KEY", "sk-anything"),
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
    stop_loss_tolerance_percent: float = 0.001  # 止损价容错比例 (如 0.001 = 0.1%)
    take_profit_percent: float = 0.008  # 止盈比例 (如 0.008 = 0.8%)
    take_profit_min_notional: float = 0.0  # 启用止盈单的最小名义金额，0 表示不限制
    take_profit_mode: str = "adaptive"  # adaptive=ATR/支撑阻力止盈, fixed=固定比例
    take_profit_atr_multiplier: float = 1.5  # 自适应止盈 ATR 倍数
    take_profit_min_percent: float = 0.004  # 自适应止盈最小距离
    take_profit_max_percent: float = 0.02  # 自适应止盈最大距离
    take_profit_structure_buffer_percent: float = 0.001  # 支撑/阻力前置缓冲
    take_profit_partial_ratio: float = 0.5  # 第一止盈使用的仓位比例
    take_profit_min_amount: float = 0.01  # 止盈单最小数量，低于时退回全仓
    min_profit_to_tighten_stop_percent: float = 0.001  # 收紧止损前的最小浮盈比例
    # 浮盈低于此比例时不更新追踪止损，0=不启用(向后兼容)。建议人工设为 0.003 以跳过低于手续费的"虚假浮盈"
    min_net_profit_to_close_percent: float = 0.003
    # 智能止损模式：基于建仓价计算止损
    stop_loss_entry_based: bool = True  # 是否基于建仓价计算止损
    price_vs_entry_tolerance_percent: float = (
        0.001  # 当前价与建仓价容错 (0.1%, 低于此值不更新止损)
    )
    # OKX 止损触发价 tick size（用于比较新/旧止损价时对齐精度，
    # 避免 OKX 把 62501.4225 截为 62501.4 后误判 "新值更紧" 造成每周期重复取消+重建算法单）
    stop_loss_tick_tolerance: float = 0.1
    # 止盈订单 R/R 下限：最终止盈距离 ≥ 止损距离 × 本系数。
    # 0=关闭保护(等同现状)；>0=强制挂单 R/R ≥ 系数（默认 1.0 保证 R/R 不倒挂）。
    # dream 2026-09-09-okx-loss-optimization / C1（根因 R1: TP/SL R/R 倒挂）。
    take_profit_min_rr_ratio: float = 1.0
    # 止盈外扩的波动率上限：外扩后 TP 距离不超过 k×ATR 距离。
    # 低波动市 (ATR 远小于 SL 距离) 时把外扩目标收回到可达位置，
    # 避免把 0.3% 的自然止盈拉到 6×ATR 导致利润无法兑现（09-13 日志根因 R2）。
    # 0=关闭 cap（恢复 C1 单向外扩行为）；默认 4.0。
    # dream 2026-09-14-okx-loss-round2 / P2（根因 R2: 低波动市 TP 不可达）。
    take_profit_max_atr_multiplier: float = 4.0
    # 全仓止盈回退时的目标拉近比例：分批止盈数量低于最小张数退回全仓止盈时，
    # 止盈目标 = 入场价 ∓ 原距离×本比例。1.0=保持原目标（默认，修复 30 天日志
    # 中 57/57 笔 TP 距离被砍半导致 R/R 结构性倒挂的问题）；0.5=旧行为（拉近一半）。
    # 2026-09-20 loss-structure-fix / R1。
    take_profit_full_amount_pull_ratio: float = 1.0
    # 单边 taker 手续费率（OKX VIP0 默认 0.05%），用于手续费感知的出场门禁：
    # 追踪止损仅在"锁定净浮盈 ≥ 2×往返手续费"后才收紧，避免 0.1~0.3% 的
    # 手续费级"虚假盈利"被提前落袋。
    # 2026-09-20 loss-structure-fix / R2。
    taker_fee_rate: float = 0.0005
    # 止盈单 R 倍数（standard bot，2026-10-08 手续费出血修复 / P1-3）：
    # TP 距离 = 止损距离 × max(本值, take_profit_min_rr_ratio)。
    # 默认 2.0 = 2R（止损 0.5% → TP 1.0%）；0 = 不挂止盈单。
    # 注: .env 的 TAKE_PROFIT_PERCENT(12R) 只被 adaptive 模式消费，standard
    # 此前从不下止盈单，本字段是其唯一开关。
    take_profit_rr_multiple: float = 2.0

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
        if self.take_profit_min_notional < 0:
            errors.append(
                f"止盈最小名义金额 {self.take_profit_min_notional} 不能为负数"
            )
        if self.take_profit_mode not in ["adaptive", "fixed"]:
            errors.append(
                f"止盈模式 '{self.take_profit_mode}' 无效，可选: adaptive, fixed"
            )
        if self.take_profit_atr_multiplier <= 0:
            errors.append(f"止盈ATR倍数 {self.take_profit_atr_multiplier} 必须大于0")
        if self.take_profit_min_percent < 0:
            errors.append(f"止盈最小距离 {self.take_profit_min_percent} 不能为负数")
        if self.take_profit_max_percent <= 0:
            errors.append(f"止盈最大距离 {self.take_profit_max_percent} 必须大于0")
        if self.take_profit_max_percent < self.take_profit_min_percent:
            errors.append("止盈最大距离不能小于最小距离")
        if self.take_profit_structure_buffer_percent < 0:
            errors.append(
                f"止盈结构缓冲 {self.take_profit_structure_buffer_percent} 不能为负数"
            )
        if self.take_profit_partial_ratio <= 0 or self.take_profit_partial_ratio > 1:
            errors.append(
                f"止盈分批比例 {self.take_profit_partial_ratio} 不在有效范围 (0-1]"
            )
        if self.take_profit_min_amount < 0:
            errors.append(f"止盈最小数量 {self.take_profit_min_amount} 不能为负数")
        if self.min_profit_to_tighten_stop_percent < 0:
            errors.append(
                "止损收紧最小盈利比例 "
                f"{self.min_profit_to_tighten_stop_percent} 不能为负数"
            )
        if self.price_vs_entry_tolerance_percent < 0:
            errors.append(
                f"建仓价容错比例 {self.price_vs_entry_tolerance_percent} 不能为负数"
            )
        if self.min_net_profit_to_close_percent < 0:
            errors.append(
                f"min_net_profit_to_close_percent "
                f"{self.min_net_profit_to_close_percent} 不能为负数"
            )
        if self.stop_loss_tick_tolerance < 0:
            errors.append(
                f"stop_loss_tick_tolerance "
                f"{self.stop_loss_tick_tolerance} 不能为负数"
            )
        if self.take_profit_min_rr_ratio < 0:
            errors.append(
                f"止盈R/R下限 {self.take_profit_min_rr_ratio} 不能为负数 (0=关闭保护)"
            )
        if self.take_profit_max_atr_multiplier < 0:
            errors.append(
                f"take_profit_max_atr_multiplier "
                f"({self.take_profit_max_atr_multiplier}) "
                "不能为负数 (0=关闭cap)"
            )
        if (
            self.take_profit_full_amount_pull_ratio <= 0
            or self.take_profit_full_amount_pull_ratio > 1
        ):
            errors.append(
                f"全仓止盈拉近比例 {self.take_profit_full_amount_pull_ratio} "
                "不在有效范围 (0,1] (1.0=保持原目标)"
            )
        if self.taker_fee_rate < 0 or self.taker_fee_rate > 0.05:
            errors.append(f"taker手续费率 {self.taker_fee_rate} 不在有效范围 [0, 0.05)")
        if self.take_profit_rr_multiple < 0:
            errors.append(
                f"take_profit_rr_multiple ({self.take_profit_rr_multiple}) "
                "不能为负数 (0=不挂止盈单)"
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
                short_entry_max_daily_change=float(
                    os.getenv("SHORT_ENTRY_MAX_DAILY_CHANGE", "1.5")
                ),
                order_confirm_timeout_seconds=float(
                    os.getenv("ORDER_CONFIRM_TIMEOUT_SECONDS", "5")
                ),
                order_confirm_poll_interval_seconds=float(
                    os.getenv("ORDER_CONFIRM_POLL_INTERVAL_SECONDS", "0.25")
                ),
                decision_journal_enabled=os.getenv("DECISION_JOURNAL", "true").lower()
                == "true",
                risk_drawdown_halt=float(os.getenv("RISK_DRAWDOWN_HALT", "0.30")),
                risk_per_trade_max=float(os.getenv("RISK_PER_TRADE_MAX", "0.10")),
                risk_resume=os.getenv("RISK_RESUME", "false").lower() in ("true", "1"),
                min_confidence_open=float(os.getenv("MIN_CONFIDENCE_OPEN", "0.65")),
                min_confidence_close=float(os.getenv("MIN_CONFIDENCE_CLOSE", "0.60")),
                daily_open_limit=int(os.getenv("DAILY_OPEN_LIMIT", "2")),
                oversold_buy_enabled=os.getenv("OVERSOLD_BUY_ENABLED", "true").lower()
                == "true",
                oversold_buy_rsi_max=float(os.getenv("OVERSOLD_BUY_RSI_MAX", "20.0")),
                oversold_buy_near_low_pct=float(
                    os.getenv("OVERSOLD_BUY_NEAR_LOW_PCT", "0.01")
                ),
                oversold_buy_confidence=float(
                    os.getenv("OVERSOLD_BUY_CONFIDENCE", "0.70")
                ),
                oversold_buy_position_factor=float(
                    os.getenv("OVERSOLD_BUY_POSITION_FACTOR", "0.5")
                ),
                oversold_buy_daily_limit=int(
                    os.getenv("OVERSOLD_BUY_DAILY_LIMIT", "1")
                ),
                oversold_buy_min_1h_change=float(
                    os.getenv("OVERSOLD_BUY_MIN_1H_CHANGE", "-0.05")
                ),
                gate_relief_rr_min=float(os.getenv("GATE_RELIEF_RR_MIN", "2.0")),
                gate_relief_amount=float(
                    os.getenv("GATE_RELIEF_AMOUNT", "0.10")
                ),
                gate_relief_floor=float(os.getenv("GATE_RELIEF_FLOOR", "0.50")),
                close_relief_amount=float(os.getenv("CLOSE_RELIEF_AMOUNT", "0.10")),
                close_relief_floor=float(os.getenv("CLOSE_RELIEF_FLOOR", "0.40")),
                climax_short_enabled=os.getenv(
                    "CLIMAX_SHORT_ENABLED", "true"
                ).lower()
                == "true",
                climax_short_rr_min=float(os.getenv("CLIMAX_SHORT_RR_MIN", "2.5")),
                climax_short_rsi_min=float(
                    os.getenv("CLIMAX_SHORT_RSI_MIN", "65.0")
                ),
                climax_short_near_high_pct=float(
                    os.getenv("CLIMAX_SHORT_NEAR_HIGH_PCT", "0.02")
                ),
                climax_short_position_factor=float(
                    os.getenv("CLIMAX_SHORT_POSITION_FACTOR", "0.5")
                ),
                climax_short_daily_limit=int(
                    os.getenv("CLIMAX_SHORT_DAILY_LIMIT", "1")
                ),
                post_close_cooldown_minutes=int(
                    os.getenv("POST_CLOSE_COOLDOWN_MINUTES", "30")
                ),
            ),
            ai=AIConfig.from_env(),
            stop_loss=StopLossConfig(
                stop_loss_percent=float(os.getenv("STOP_LOSS_PERCENT", "0.0005")),
                stop_loss_profit_percent=float(
                    os.getenv("STOP_LOSS_PROFIT_PERCENT", "0.0002")
                ),
                take_profit_percent=float(os.getenv("TAKE_PROFIT_PERCENT", "0.008")),
                take_profit_min_notional=float(
                    os.getenv("TAKE_PROFIT_MIN_NOTIONAL", "0")
                ),
                take_profit_mode=os.getenv("TAKE_PROFIT_MODE", "adaptive").lower(),
                take_profit_atr_multiplier=float(
                    os.getenv("TAKE_PROFIT_ATR_MULTIPLIER", "1.5")
                ),
                take_profit_min_percent=float(
                    os.getenv("TAKE_PROFIT_MIN_PERCENT", "0.004")
                ),
                take_profit_max_percent=float(
                    os.getenv("TAKE_PROFIT_MAX_PERCENT", "0.02")
                ),
                take_profit_structure_buffer_percent=float(
                    os.getenv("TAKE_PROFIT_STRUCTURE_BUFFER_PERCENT", "0.001")
                ),
                take_profit_partial_ratio=float(
                    os.getenv("TAKE_PROFIT_PARTIAL_RATIO", "0.5")
                ),
                take_profit_min_amount=float(
                    os.getenv("TAKE_PROFIT_MIN_AMOUNT", "0.01")
                ),
                min_profit_to_tighten_stop_percent=float(
                    os.getenv("MIN_PROFIT_TO_TIGHTEN_STOP_PERCENT", "0.001")
                ),
                stop_loss_entry_based=os.getenv("STOP_LOSS_ENTRY_BASED", "true").lower()
                == "true",
                price_vs_entry_tolerance_percent=float(
                    os.getenv("PRICE_VS_ENTRY_TOLERANCE_PERCENT", "0.001")
                ),
                min_net_profit_to_close_percent=float(
                    os.getenv("MIN_NET_PROFIT_TO_CLOSE_PERCENT", "0")
                ),
                take_profit_full_amount_pull_ratio=float(
                    os.getenv("TAKE_PROFIT_FULL_AMOUNT_PULL_RATIO", "1.0")
                ),
                taker_fee_rate=float(os.getenv("TAKER_FEE_RATE", "0.0005")),
                stop_loss_tick_tolerance=float(
                    os.getenv("STOP_LOSS_TICK_TOLERANCE", "0.1")
                ),
                take_profit_min_rr_ratio=float(
                    os.getenv("TAKE_PROFIT_MIN_RR_RATIO", "1.0")
                ),
                take_profit_max_atr_multiplier=float(
                    os.getenv("TAKE_PROFIT_MAX_ATR_MULTIPLIER", "4.0")
                ),
                take_profit_rr_multiple=float(
                    os.getenv("TAKE_PROFIT_RR_MULTIPLE", "2.0")
                ),
            ),
            system=SystemConfig(
                log_level=os.getenv("LOG_LEVEL", "INFO"),
            ),
        )

        # 验证配置
        config.validate_or_raise()

        return config
