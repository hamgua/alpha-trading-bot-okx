"""
参数阈值集中配置模块（唯一事实来源 / Single Source of Truth）

所有可配置的参数阈值必须集中在此文件中定义，其他模块通过 import 引用。
如需修改任何阈值，仅需修改此文件中的常量值。

约定：
- OVERSOLD / OVERBOUGHT 为基础超买超卖检测阈值（RSI 经典定义）
- *_REBOUND / *_HIGH / *_RISK 为不同语义层级的派生阈值
- BUY_* / SELL_* 为买卖条件相关阈值
- 命名格式：{领域}_{语义}_{修饰符}

使用方式：
    from alpha_trading_bot.config.thresholds import RSI_OVERSOLD, RSI_OVERBOUGHT
"""

# ============================================================
# 基础超买超卖阈值（RSI 经典定义）
# ============================================================

# RSI 超卖阈值（默认 30）
# 用途: RSI < 30 表示超卖，可能反弹
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_oversold (第64行)
#   - ai/adaptive/strategy_library.py: MeanReversionStrategy analyze() (第245行)
#   - ai/config_manager.py: BuyConditionsConfig.oversold_rsi_max -> RSI_BUY_OVERSOLD_MAX
#   - ai/config_manager.py: TrendDetectionConfig.rsi_oversold (第135行)
#   - ai/trend_reversal_detector.py: TrendReversalConfig.rsi_oversold (第61行)
#   - ai/prompt_builder.py: PromptConfig.oversold_rsi_threshold (第31行)
#   - ai/adaptive/rules_engine.py: RsiRule 超卖检测 (第284行)
RSI_OVERSOLD = 30

# RSI 超买阈值（默认 70）
# 用途: RSI > 70 表示超买，可能回调
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_overbought (第65行)
#   - ai/adaptive/strategy_library.py: MeanReversionStrategy analyze() (第261行)
#   - ai/adaptive/strategy_selector.py: _detect_regime() 超买检测 (第114行)
#   - ai/adaptive/rules_engine.py: RsiRule 超买检测 (第312行)
#   - ai/fusion/consensus_boosted.py: 卖出偏好 RSI 超买触发 (第554行)
RSI_OVERBOUGHT = 70

# 中性区间下界（默认 40）
# 用途: RSI >= 40 视为中性区域
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_neutral_low (第66行)
#   - ai/adaptive/rules_engine.py: RsiRule 偏低检测 (第298行)
RSI_NEUTRAL_LOW = 40

# 中性区间上界（默认 60）
# 用途: RSI <= 60 视为中性区域
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_neutral_high (第67行)
RSI_NEUTRAL_HIGH = 60

# ============================================================
# 策略相关派生阈值
# ============================================================

# 趋势跟踪策略 RSI 买入范围下界（默认 35）
# 用途: 上升趋势中 RSI 回调至 35-60 区间视为买入机会，35 表示避免极度超卖区域
# 引用方:
#   - ai/adaptive/strategy_library.py: TrendFollowingStrategy RSI 回调买入 (第172行)
RSI_TREND_BUY_MIN = 35

# 趋势跟踪策略 RSI 买入范围上界（默认 60）
# 用途: 上升趋势中 RSI 回调至 35-60 区间视为买入机会
# 引用方:
#   - ai/adaptive/strategy_library.py: TrendFollowingStrategy RSI 回调买入 (第172行)
RSI_TREND_BUY_MAX = 60

# 趋势跟踪策略 RSI 卖出范围下界（默认 40）
# 用途: 下降趋势中 RSI 反弹至 40-70 区间视为卖出机会
# 引用方:
#   - ai/adaptive/strategy_library.py: TrendFollowingStrategy RSI 反弹卖出 (第189行)
RSI_TREND_SELL_MIN = 40

# ============================================================
# 融合策略动态阈值
# ============================================================

# RSI 超卖区域阈值（融合策略，默认 35，比基础超卖保守）
# 用途: RSI < 35 时降低买入阈值更容易抄底
# 引用方:
#   - ai/fusion/consensus_boosted.py: 动态阈值 RSI 超卖区域检测 (第679行)
RSI_OVERSOLD_REBOUND = 35

# RSI 超买区域阈值（融合策略，默认 65，比基础超买保守）
# 用途: RSI > 65 时降低卖出阈值更容易获利了结
# 引用方:
#   - ai/fusion/consensus_boosted.py: 动态阈值 RSI 超买区域检测 (第687行)
RSI_OVERBOUGHT_REBOUND = 65

# ============================================================
# 风险控制相关阈值
# ============================================================

# 风险超买阈值（默认 80）
# 用途: RSI >= 80 视为高风险超买，触发卖出/风控
# 引用方:
#   - ai/config_manager.py: SellConditionsConfig.risk_rsi_overbought (第103行)
#   - ai/dynamic_sell_condition.py: DynamicSellConfig.risk_rsi_overbought (第56行)
RSI_RISK_OVERBOUGHT = 80

# 止盈 RSI 阈值（默认 75）
# 用途: RSI >= 75 视为止盈参考信号
# 引用方:
#   - ai/config_manager.py: SellConditionsConfig.take_profit_rsi_threshold (第100行)
#   - ai/dynamic_sell_condition.py: SellConditions.take_profit_rsi_threshold (第53行)
RSI_TAKE_PROFIT = 75

# 高风险 RSI 阈值（默认 75）
# 用途: RSI >= 75 视为高风险区域
# 引用方:
#   - ai/config_manager.py: SellConditionsConfig.risk_rsi_high (第104行)
#   - ai/dynamic_sell_condition.py: SellConditions.risk_rsi_high (第57行)
RSI_RISK_HIGH = 75

# ============================================================
# 策略选择相关阈值
# ============================================================

# 策略选择器超卖阈值（默认 35）
# 用途: _detect_regime() 中判断超卖市场状态
# 引用方:
#   - ai/adaptive/strategy_selector.py: _detect_regime() 超卖检测 (第112行)
RSI_SELECTOR_OVERSOLD = 35

# ============================================================
# 买入条件相关阈值
# ============================================================

# 常规模式 RSI 上限（默认 65）
# 用途: 常规买入条件中 RSI 不能超过此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.regular_rsi_max (第61行)
#   - ai/adaptive_buy_condition.py: BuyConditions.regular_rsi_max (第40行)
RSI_BUY_REGULAR_MAX = 65

# 超卖模式 RSI 上限（默认 30）
# 用途: 超卖买入模式 RSI 必须低于此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.oversold_rsi_max (第68行)
#   - ai/adaptive_buy_condition.py: BuyConditions.oversold_rsi_max (第47行)
RSI_BUY_OVERSOLD_MAX = 30

# 支撑模式 RSI 上限（默认 35）
# 用途: 强势支撑买入模式 RSI 必须低于此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.support_rsi_max (第77行)
#   - ai/adaptive_buy_condition.py: BuyConditions.support_rsi_max (第56行)
RSI_BUY_SUPPORT_MAX = 35

# 确认模式 RSI 上限（默认 55）
# 用途: 趋势确认买入模式 RSI 必须低于此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.confirmation_rsi_max (第84行)
#   - ai/adaptive_buy_condition.py: BuyConditions.confirmation_rsi_max (第63行)
RSI_BUY_CONFIRM_MAX = 55

# ============================================================
# 卖出/止损相关阈值
# ============================================================

# 止损百分比（默认 0.5%）
# 用途: 新开仓浮亏超过此百分比触发止损
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.stop_loss_percent (第46行)
#   - ai/config_manager.py: SellConditionsConfig.stop_loss_percent (第93行)
SELL_STOP_LOSS_PERCENT = 0.005

# 盈利后止损百分比（默认 0.2%）
# 用途: 有盈利后浮亏超过此百分比触发止损
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.stop_loss_profit_percent (第47行)
#   - ai/config_manager.py: SellConditionsConfig.stop_loss_profit_percent (第94行)
SELL_STOP_LOSS_PROFIT_PERCENT = 0.002

# 止损价容错（默认 0.1%）
# 用途: 止损价与当前价的容差范围
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.stop_loss_tolerance_percent (第48行)
SELL_STOP_LOSS_TOLERANCE_PERCENT = 0.0001

# 止盈百分比（默认 0.6%）
# 用途: 浮盈达到此百分比触发止盈
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.take_profit_percent (第51行)
#   - ai/config_manager.py: SellConditionsConfig.take_profit_percent (第98行)
SELL_TAKE_PROFIT_PERCENT = 0.006

# 分批止盈百分比（默认 0.4%）
# 用途: 部分止盈的浮盈目标
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.take_profit_partial_percent (第52行)
#   - ai/config_manager.py: SellConditionsConfig.take_profit_partial_percent (第99行)
SELL_TAKE_PROFIT_PARTIAL_PERCENT = 0.004

# 风险规避布林带位置上限（默认 90%）
# 用途: 布林带位置 > 90% 视为严重超买
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.risk_bb_position_max (第58行)
#   - ai/config_manager.py: SellConditionsConfig.risk_bb_position_max (第105行)
SELL_RISK_BB_POSITION_MAX = 0.90

# 风险规避布林带位置上界（默认 85%）
# 用途: 布林带位置 > 85% 视为偏高
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.risk_bb_position_high (第59行)
SELL_RISK_BB_POSITION_HIGH = 0.85

# 趋势转空强度阈值（默认 0.4）
# 用途: 趋势强度 >= 0.4 且方向向下时视为明确转空
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.risk_trend_down_strength (第60行)
#   - ai/config_manager.py: SellConditionsConfig.risk_trend_down_strength (第107行)
SELL_RISK_TREND_DOWN_STRENGTH = 0.4

# MACD 转空阈值（默认 -0.002）
# 用途: MACD 柱状图 <= -0.002 视为转空信号
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.risk_macd_negative (第61行)
SELL_RISK_MACD_NEGATIVE = -0.002

# 浮盈回撤百分比阈值（默认 1%）
# 用途: 浮盈回撤到 1% 以下时触发风险规避
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.risk_drawdown_percent (第62行)
SELL_RISK_DRAWDOWN_PERCENT = 0.01

# 减仓比例（默认 50%）
# 用途: 部分减仓时卖出的仓位比例
# 引用方:
#   - ai/dynamic_sell_condition.py: SellConditions.partial_sell_factor (第66行)
SELL_PARTIAL_FACTOR = 0.5

# ============================================================
# 常规买入条件阈值
# ============================================================

# 常规模式趋势强度下限（默认 0.2）
# 用途: 常规买入需要趋势强度 >= 此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.regular_trend_strength_min (第60行)
#   - ai/adaptive_buy_condition.py: BuyConditions.regular_trend_strength_min (第39行)
BUY_REGULAR_TREND_STRENGTH_MIN = 0.2

# 常规模式布林带位置上限（默认 65%）
# 用途: 常规买入需要布林带位置 < 此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.regular_bb_position_max (第62行)
#   - ai/adaptive_buy_condition.py: BuyConditions.regular_bb_position_max (第41行)
BUY_REGULAR_BB_POSITION_MAX = 0.65

# 常规模式 ADX 下限（默认 15）
# 用途: 常规买入需要 ADX >= 此值（有趋势）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.regular_adx_min (第63行)
#   - ai/adaptive_buy_condition.py: BuyConditions.regular_adx_min (第42行)
BUY_REGULAR_ADX_MIN = 15

# 常规模式动量下限（默认 0.5%）
# 用途: 常规买入需要 1h 涨幅 >= 此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.regular_momentum_min (第64行)
#   - ai/adaptive_buy_condition.py: BuyConditions.regular_momentum_min (第43行)
BUY_REGULAR_MOMENTUM_MIN = 0.005

# 超卖反弹模式动量阈值（默认 0.5%）
# 用途: 超卖反弹需要动量 >= 此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.oversold_momentum_min (第69行)
#   - ai/adaptive_buy_condition.py: BuyConditions.oversold_momentum_min (第48行)
BUY_OVERSOLD_MOMENTUM_MIN = 0.005

# 超卖反弹模式趋势强度下限（默认 0.1）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.oversold_trend_strength_min (第70行)
#   - ai/adaptive_buy_condition.py: BuyConditions.oversold_trend_strength_min (第49行)
BUY_OVERSOLD_TREND_STRENGTH_MIN = 0.1

# 超卖反弹模式布林带位置上限（默认 45%）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.oversold_bb_position_max (第71行)
#   - ai/adaptive_buy_condition.py: BuyConditions.oversold_bb_position_max (第50行)
BUY_OVERSOLD_BB_POSITION_MAX = 0.45

# 超卖反弹模式仓位系数（默认 0.5）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.oversold_position_factor (第72行)
#   - ai/adaptive_buy_condition.py: BuyConditions.oversold_position_factor (第51行)
BUY_OVERSOLD_POSITION_FACTOR = 0.5

# 强势支撑模式价格位置上限（默认 20%）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.support_price_position_max (第76行)
#   - ai/adaptive_buy_condition.py: BuyConditions.support_price_position_max (第55行)
BUY_SUPPORT_PRICE_POSITION_MAX = 0.20

# 强势支撑模式动量阈值（默认 0.3%）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.support_momentum_min (第78行)
#   - ai/adaptive_buy_condition.py: BuyConditions.support_momentum_min (第57行)
BUY_SUPPORT_MOMENTUM_MIN = 0.003

# 强势支撑模式仓位系数（默认 0.7）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.support_position_factor (第79行)
#   - ai/adaptive_buy_condition.py: BuyConditions.support_position_factor (第58行)
BUY_SUPPORT_POSITION_FACTOR = 0.7

# 趋势确认模式连续上涨周期数（默认 3）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.confirmation_consecutive_up (第83行)
#   - ai/adaptive_buy_condition.py: BuyConditions.confirmation_consecutive_up (第62行)
BUY_CONFIRMATION_CONSECUTIVE_UP = 3

# 趋势确认模式仓位系数（默认 0.8）
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.confirmation_position_factor (第85行)
#   - ai/adaptive_buy_condition.py: BuyConditions.confirmation_position_factor (第64行)
BUY_CONFIRMATION_POSITION_FACTOR = 0.8

# ============================================================
# 信号优化器阈值
# ============================================================

# 置信度下限（默认 0.30）
# 用途: 信号置信度的最低可接受值
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.confidence_floor (第62行)
#   - ai/config_manager.py: SignalOptimizerConfig.confidence_floor (第144行)
SIGNAL_CONFIDENCE_FLOOR = 0.30

# 置信度上限（默认 0.95）
# 用途: 信号置信度的最高值
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.confidence_ceiling (第63行)
#   - ai/config_manager.py: SignalOptimizerConfig.confidence_ceiling (第145行)
SIGNAL_CONFIDENCE_CEILING = 0.95

# 信号快速变化阈值（默认 0.25）
# 用途: 信号变化超过此值视为快速变化
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.rapid_change_threshold (第64行)
#   - ai/config_manager.py: SignalOptimizerConfig.rapid_change_threshold (第146行)
SIGNAL_RAPID_CHANGE_THRESHOLD = 0.25

# 平滑窗口大小（默认 2）
# 用途: 信号平滑处理的窗口大小
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.smoothing_window (第67行)
SIGNAL_SMOOTHING_WINDOW = 2

# 高波动判定阈值（默认 5%）
# 用途: ATR 百分比超过此值视为高波动
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.high_volatility_threshold (第72行)
#   - ai/config_manager.py: SignalOptimizerConfig.high_volatility_threshold (第150行)
SIGNAL_HIGH_VOLATILITY_THRESHOLD = 0.05

# 连续信号限制（默认 5）
# 用途: 允许的最大连续同一信号次数
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.consecutive_limit (第75行)
SIGNAL_CONSECUTIVE_LIMIT = 5

# 冷却期（默认 2 周期）
# 用途: 信号切换后的冷却周期数
# 引用方:
#   - ai/signal_optimizer.py: OptimizerConfig.cooldown_period (第76行)
#   - ai/config_manager.py: SignalOptimizerConfig.cooldown_period (第152行)
SIGNAL_COOLDOWN_PERIOD = 2

# ============================================================
# 融合策略阈值
# ============================================================

# 融合基础阈值（默认 0.50）
# 用途: 基础信号融合判决阈值
# 引用方:
#   - ai/config_manager.py: AIConfig.fusion_threshold (第49行)
#   - ai/adaptive/parameter_manager.py: AdaptiveConfig.base_fusion_threshold (第27行)
#   - ai/adaptive/rules_engine.py: 各规则 fusion_threshold 配置 (第108行起)
FUSION_BASE_THRESHOLD = 0.50

# 融合一致性强化倍数（默认 1.25）
# 用途: 全部 AI 一致时信号放大倍数
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.consensus_boost_full (第46行)
#   - ai/config_manager.py: FusionConfig.consensus_boost_full (第122行)
FUSION_CONSENSUS_BOOST_FULL = 1.25

# 融合部分一致强化倍数（默认 1.20）
# 用途: 多数 AI 一致时信号放大倍数
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.consensus_boost_partial (第47行)
#   - ai/config_manager.py: FusionConfig.consensus_boost_partial (第123行)
FUSION_CONSENSUS_BOOST_PARTIAL = 1.20

# 融合默认置信度（默认 0.70）
# 用途: 融合信号的默认置信度
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.default_confidence (第48行)
#   - ai/config_manager.py: FusionConfig.default_confidence (第124行)
FUSION_DEFAULT_CONFIDENCE = 0.70

# 融合部分一致阈值（默认 0.40）
# 用途: 达到此比例视为部分一致
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.partial_consensus_threshold (第49行)
FUSION_PARTIAL_CONSENSUS_THRESHOLD = 0.40

# ============================================================
# 融合策略（consensus_boosted 专属）阈值
# ============================================================

# Kimi 买入反弹增强倍数（默认 1.3）
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.kimi_buy_rebound_boost (第50行)
FUSION_KIMI_BUY_REBOUND_BOOST = 1.3

# RSI 反弹下界（默认 28）
# 用途: 买入反弹模式的 RSI 下限
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.rsi_rebound_low (第51行)
FUSION_RSI_REBOUND_LOW = 28

# RSI 反弹上界（默认 75）
# 用途: 买入反弹模式的 RSI 上限
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.rsi_rebound_high (第52行)
FUSION_RSI_REBOUND_HIGH = 75

# RSI 高值压制（默认 78）
# 用途: RSI 超过此值压制买入倾向
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.rsi_high_suppression (第53行)
FUSION_RSI_HIGH_SUPPRESSION = 78

# 买入偏置系数（默认 1.0）
# 用途: 买入信号的全局偏置
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.buy_bias (第55行)
FUSION_BUY_BIAS = 1.0

# 卖出偏置系数（默认 1.15）
# 用途: 卖出信号的全局偏置
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.sell_bias (第56行)
FUSION_SELL_BIAS = 1.15

# 做空偏置系数（默认 1.2）
# 用途: 做空信号的全局偏置
# 引用方:
#   - ai/fusion/consensus_boosted.py: FusionConfig.short_bias (第57行)
FUSION_SHORT_BIAS = 1.2

# ============================================================
# Prompt 构建器阈值
# ============================================================

# Prompt 买入 RSI 阈值（默认 72）
# 用途: prompt 中判断非超买区域的 RSI 上限
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.buy_rsi_threshold (第16行)
PROMPT_BUY_RSI_THRESHOLD = 72

# Prompt 买入 ADX 阈值（默认 8）
# 用途: prompt 中判断有趋势的 ADX 下限
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.buy_adx_threshold (第18行)
PROMPT_BUY_ADX_THRESHOLD = 8

# Prompt 卖出 RSI 阈值（默认 75）
# 用途: prompt 中判断超买的 RSI 下限
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.sell_rsi_threshold (第19行)
PROMPT_SELL_RSI_THRESHOLD = 75

# Prompt 趋势强度阈值（默认 0.15）
# 用途: prompt 中判断观望/操作的趋势强度分界线
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.watch_trend_strength (第22行)
PROMPT_WATCH_TREND_STRENGTH = 0.15

# Prompt 观望 ADX 阈值（默认 30）
# 用途: prompt 中判断趋势存在的 ADX 阈值
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.watch_adx_threshold (第23行)
PROMPT_WATCH_ADX_THRESHOLD = 30

# Prompt 观望 ATR 阈值（默认 6.0%）
# 用途: prompt 中判断高波动的 ATR 阈值
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.watch_atr_threshold (第26行)
PROMPT_WATCH_ATR_THRESHOLD = 6.0

# Prompt 暴跌阈值（默认 -2%）
# 用途: 1小时跌幅 > -2% 视为暴跌
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.crash_drop_threshold (第27行)
PROMPT_CRASH_DROP_THRESHOLD = -0.02

# Prompt 短期买入阈值（默认 1%）
# 用途: 短期涨幅 > 1% 视为积极信号
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.short_term_buy_threshold (第28行)
PROMPT_SHORT_TERM_BUY_THRESHOLD = 0.01

# Prompt DeepSeek 低位阈值（默认 35%）
# 用途: DeepSeek 判断低位反弹的价格位置阈值
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.deepseek_low_position_threshold (第37行)
PROMPT_DEEPSEEK_LOW_POSITION_THRESHOLD = 0.35

# Prompt DeepSeek 反弹模式 RSI 上限（默认 65）
# 引用方:
#   - ai/prompt_builder.py: PromptConfig.deepseek_rebound_rsi_max (第39行)
PROMPT_DEEPSEEK_REBOUND_RSI_MAX = 65

# ============================================================
# 优化版 Prompt（prompt_optimizer）阈值
# ============================================================

# 强趋势阈值（默认 0.6）
# 用途: 趋势强度 >= 0.6 视为强趋势
# 引用方:
#   - ai/prompt_optimizer.py: PromptConfig.strong_trend_threshold (第30行)
PROMPT_OPT_STRONG_TREND_THRESHOLD = 0.6

# 弱趋势阈值（默认 0.3）
# 用途: 趋势强度 < 0.3 视为弱趋势/无趋势
# 引用方:
#   - ai/prompt_optimizer.py: PromptConfig.weak_trend_threshold (第31行)
PROMPT_OPT_WEAK_TREND_THRESHOLD = 0.3

# 强动量阈值（默认 0.5%）
# 用途: 动量变化 >= 0.5% 视为强动量
# 引用方:
#   - ai/prompt_optimizer.py: PromptConfig.strong_momentum_threshold (第34行)
PROMPT_OPT_STRONG_MOMENTUM_THRESHOLD = 0.005

# 弱动量阈值（默认 0.2%）
# 用途: 动量变化 >= 0.2% 视为弱动量
# 引用方:
#   - ai/prompt_optimizer.py: PromptConfig.weak_momentum_threshold (第35行)
PROMPT_OPT_WEAK_MOMENTUM_THRESHOLD = 0.002

# ============================================================
# 市场环境检测阈值（MarketRegimeConfig）
# ============================================================

# 回看蜡烛数（默认 20）
# 用途: 市场环境检测的蜡烛回看数量
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.lookback_candles (第57行)
REGIME_LOOKBACK_CANDLES = 20

# 强上升趋势阈值（默认 0.5）
# 用途: 趋势强度 >= 0.5 视为强上升趋势
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.trend_strong_up (第58行)
REGIME_TREND_STRONG_UP = 0.5

# 弱上升趋势阈值（默认 0.2）
# 用途: 趋势强度 >= 0.2 视为弱上升趋势
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.trend_weak_up (第59行)
REGIME_TREND_WEAK_UP = 0.2

# 强下降趋势阈值（默认 -0.5）
# 用途: 趋势强度 <= -0.5 视为强下降趋势
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.trend_strong_down (第60行)
REGIME_TREND_STRONG_DOWN = -0.5

# 弱下降趋势阈值（默认 -0.2）
# 用途: 趋势强度 <= -0.2 视为弱下降趋势
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.trend_weak_down (第61行)
REGIME_TREND_WEAK_DOWN = -0.2

# 高波动阈值（默认 3%）
# 用途: ATR >= 3% 视为高波动
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.volatility_high (第62行)
REGIME_VOLATILITY_HIGH = 0.03

# 低波动阈值（默认 1.5%）
# 用途: ATR <= 1.5% 视为低波动
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.volatility_low (第63行)
REGIME_VOLATILITY_LOW = 0.015

# ============================================================
# 风险控制阈值（RiskManagerConfig）
# ============================================================

# 硬止损百分比（默认 5%）
# 用途: 绝对底线的硬止损
# 引用方:
#   - ai/adaptive/risk_manager.py: RiskConfig.hard_stop_loss_percent (第40行)
RISK_HARD_STOP_LOSS_PERCENT = 0.05

# 盈利时硬止损百分比（默认 3%）
# 用途: 盈利后的绝对硬止损
# 引用方:
#   - ai/adaptive/risk_manager.py: RiskConfig.hard_stop_loss_profit_percent (第41行)
RISK_HARD_STOP_LOSS_PROFIT_PERCENT = 0.03

# 最大仓位百分比（默认 10%）
# 用途: 单次最大仓位占账户比例
# 引用方:
#   - ai/adaptive/risk_manager.py: RiskConfig.max_position_percent (第49行)
#   - core/managers/risk_manager.py: (第60行)
RISK_MAX_POSITION_PERCENT = 0.1

# 最小仓位百分比（默认 2%）
# 用途: 单次最小仓位占账户比例
# 引用方:
#   - ai/adaptive/risk_manager.py: RiskConfig.min_position_percent (第50行)
RISK_MIN_POSITION_PERCENT = 0.02

# 熔断阈值（默认 3%）
# 用途: 日内亏损超过此值触发熔断
# 引用方:
#   - ai/adaptive/risk_manager.py: RiskConfig.circuit_breaker_threshold (第55行)
#   - core/managers/risk_manager.py: (第50行)
RISK_CIRCUIT_BREAKER_THRESHOLD = 0.03

# 熔断冷却小时数（默认 4 小时）
# 用途: 熔断触发后需等待的小时数
# 引用方:
#   - ai/adaptive/risk_manager.py: RiskConfig.circuit_breaker_cooldown_hours (第56行)
RISK_CIRCUIT_BREAKER_COOLDOWN_HOURS = 4

# ============================================================
# 趋势检测阈值（TrendDetectionConfig）
# ============================================================

# 趋势检测周期（默认 [10, 20, 50]）
# 用途: 多时间框架趋势分析使用的周期
# 引用方:
#   - ai/config_manager.py: TrendDetectionConfig.periods (第131行)
TREND_DETECTION_PERIODS = [10, 20, 50]

# 趋势反转窗口（默认 3）
# 用途: 检测趋势反转的窗口期
# 引用方:
#   - ai/config_manager.py: TrendDetectionConfig.reversal_window (第133行)
TREND_REVERSAL_WINDOW = 3

# 趋势反转动量阈值（默认 0.8%）
# 用途: 反转检测的动量阈值
# 引用方:
#   - ai/config_manager.py: TrendDetectionConfig.reversal_momentum_threshold (第134行)
#   - ai/trend_reversal_detector.py: TrendReversalConfig.momentum_threshold (第62行)
TREND_REVERSAL_MOMENTUM_THRESHOLD = 0.008

# RSI 反弹检测阈值（默认 3）
# 用途: RSI 反弹幅度超过此值视为有效反弹
# 引用方:
#   - ai/config_manager.py: TrendDetectionConfig.rsi_rebound_threshold (第136行)
#   - ai/trend_reversal_detector.py: TrendReversalConfig.rsi_rebound_threshold (第64行)
TREND_RSI_REBOUND_THRESHOLD = 3

# 价格位置低位阈值（默认 25%）
# 引用方:
#   - ai/config_manager.py: TrendDetectionConfig.price_position_low (第137行)
TREND_PRICE_POSITION_LOW = 0.25

# ============================================================
# 持续下跌检测阈值（SustainedDeclineConfig）
# ============================================================

# 轻度下跌阈值（默认 3.0%）
# 用途: 累积跌幅 >= 3% 视为轻度下跌
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.mild_decline_threshold (第75行)
DECLINE_MILD_THRESHOLD = 3.0

# 中度下跌阈值（默认 5.0%）
# 用途: 累积跌幅 >= 5% 视为中度下跌
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.moderate_decline_threshold (第76行)
DECLINE_MODERATE_THRESHOLD = 5.0

# 严重下跌阈值（默认 8.0%）
# 用途: 累积跌幅 >= 8% 视为严重下跌
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.severe_decline_threshold (第77行)
DECLINE_SEVERE_THRESHOLD = 8.0

# 最小下跌持续小时数（默认 2.0 小时）
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.min_decline_hours (第80行)
DECLINE_MIN_HOURS = 2.0

# 最小连续下跌周期数（默认 3）
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.min_consecutive_down (第83行)
DECLINE_MIN_CONSECUTIVE_DOWN = 3

# 最小下跌占比（默认 0.6）
# 用途: 下跌周期数占总周期数的比例下限
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.min_down_ratio (第84行)
DECLINE_MIN_DOWN_RATIO = 0.6

# 最大允许反弹百分比（默认 1.5%）
# 用途: 持续下跌中允许的单次最大反弹幅度
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.max_rebound_threshold (第87行)
DECLINE_MAX_REBOUND_THRESHOLD = 1.5

# 轻度下跌 BUY 置信度惩罚（默认 0.15）
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.buy_confidence_penalty_mild (第90行)
DECLINE_BUY_CONFIDENCE_PENALTY_MILD = 0.15

# 中度下跌 BUY 置信度惩罚（默认 0.30）
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.buy_confidence_penalty_moderate
DECLINE_BUY_CONFIDENCE_PENALTY_MODERATE = 0.30

# 严重下跌 BUY 置信度惩罚（默认 0.50）
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.buy_confidence_penalty_severe
DECLINE_BUY_CONFIDENCE_PENALTY_SEVERE = 0.50

# 持续下跌 BUY 阻断阈值（默认完全阻断 0.0）
# 用途: BUY 信号置信度低于此值转为 HOLD
# 引用方:
#   - ai/sustained_decline_detector.py: SustainedDeclineConfig.buy_block_threshold
DECLINE_BUY_BLOCK_THRESHOLD = 0.0

# ============================================================
# 价格位置 & BTC 检测阈值
# ============================================================

# BTC 高位阈值（默认 0.99）
# 用途: 距离 24h 高点 1% 以内视为高位
# 引用方:
#   - ai/btc_price_detector.py: BTCPriceDetectorConfig.high_threshold (第44行)
#   - ai/integrator_config.py: SignalThresholdsConfig.btc_high_threshold (第52行)
BTC_HIGH_THRESHOLD = 0.99

# BTC 低位阈值（默认 0.03）
# 用途: 距离 24h 低点 3% 以内视为低位
# 引用方:
#   - ai/btc_price_detector.py: BTCPriceDetectorConfig.low_threshold (第49行)
#   - ai/integrator_config.py: SignalThresholdsConfig.btc_low_threshold (第53行)
BTC_LOW_THRESHOLD = 0.03

# BTC 相对高位阈值（默认 0.85）
# 用途: 价格在区间 85% 位置以上视为高位
# 引用方:
#   - ai/btc_price_detector.py: BTCPriceDetectorConfig.relative_high_threshold (第53行)
BTC_RELATIVE_HIGH_THRESHOLD = 0.85

# BTC 相对中位阈值（默认 0.70）
# 用途: 价格在区间 70% 位置以上视为中高位
# 引用方:
#   - ai/btc_price_detector.py: BTCPriceDetectorConfig.relative_mid_threshold (第52行)
BTC_RELATIVE_MID_THRESHOLD = 0.70

# BTC 高位风险惩罚（默认 0.35）
# 引用方:
#   - ai/integrator_config.py: SignalThresholdsConfig.btc_high_risk_penalty (第36行)
BTC_HIGH_RISK_PENALTY = 0.35

# BTC 低位机会加成（默认 1.15）
# 引用方:
#   - ai/integrator_config.py: SignalThresholdsConfig.btc_low_opportunity_boost (第38行)
BTC_LOW_OPPORTUNITY_BOOST = 1.15

# ============================================================
# 投资决策 R/R 阈值
# ============================================================

# 保守型 R/R 最低阈值（默认 0.8）
# 引用方:
#   - core/decision_engine.py: INVESTMENT_RR_THRESHOLDS.conservative (第21行)
RR_CONSERVATIVE_MIN = 0.8

# 中等型 R/R 最低阈值（默认 1.0）
# 引用方:
#   - core/decision_engine.py: INVESTMENT_RR_THRESHOLDS.moderate (第22行)
RR_MODERATE_MIN = 1.0

# 激进型 R/R 最低阈值（默认 0.6）
# 引用方:
#   - core/decision_engine.py: INVESTMENT_RR_THRESHOLDS.aggressive (第23行)
RR_AGGRESSIVE_MIN = 0.6

# 良好 R/R 比（默认 2.0）
# 引用方:
#   - core/decision_engine.py: GOOD_RR_RATIO (第26行)
#   - ai/market_structure.py: StructureAnalyzerConfig.good_rr (第82行)
RR_GOOD_RATIO = 2.0