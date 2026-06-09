"""
RSI 阈值集中配置模块

所有 RSI 相关阈值的唯一事实来源 (Single Source of Truth)。
如需修改 RSI 阈值，仅需修改此文件中的常量值。

约定：
- OVERSOLD / OVERBOUGHT 为基础超买超卖检测阈值（RSI 经典定义）
- *_REBOUND / *_HIGH / *_RISK 为不同语义层级的派生阈值

使用方式：
    from alpha_trading_bot.config.thresholds import RSI_OVERSOLD, RSI_OVERBOUGHT
"""

# ============================================================
# 基础超买超卖阈值（RSI 经典定义）
# ============================================================

# RSI 超卖阈值（默认 30）
# 用途: RSI < 30 表示超卖，可能反弹
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_oversold (第57行)
#   - ai/adaptive/strategy_library.py: MeanReversionStrategy oversold_threshold (第287行), analyze() (第238行)
#   - ai/config_manager.py: BuyConditionsConfig.oversold_rsi_max (第57行)
#   - ai/config_manager.py: TrendDetectionConfig.rsi_oversold (第124行)
#   - ai/trend_reversal_detector.py: TrendReversalConfig.rsi_oversold (第61行)
#   - ai/prompt_builder.py: PromptConfig.oversold_rsi_threshold (第29行)
#   - ai/adaptive/rules_engine.py: RsiRule 超卖检测 (第284行)
RSI_OVERSOLD = 30

# RSI 超买阈值（默认 70）
# 用途: RSI > 70 表示超买，可能回调
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_overbought (第58行)
#   - ai/adaptive/strategy_library.py: MeanReversionStrategy overbought_threshold (第288行), analyze() (第254行)
#   - ai/adaptive/strategy_selector.py: _detect_regime() 超买检测 (第114行)
#   - ai/adaptive/rules_engine.py: RsiRule 超买检测 (第312行)
#   - ai/fusion/consensus_boosted.py: 卖出偏好 RSI 超买触发 (第554行)
RSI_OVERBOUGHT = 70

# 中性区间下界（默认 40）
# 用途: RSI >= 40 视为中性区域
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_neutral_low (第59行)
#   - ai/adaptive/rules_engine.py: RsiRule 偏低检测 (第298行)
RSI_NEUTRAL_LOW = 40

# 中性区间上界（默认 60）
# 用途: RSI <= 60 视为中性区域
# 引用方:
#   - ai/adaptive/market_regime.py: MarketRegimeConfig.rsi_neutral_high (第60行)
RSI_NEUTRAL_HIGH = 60

# ============================================================
# 策略相关派生阈值
# ============================================================

# 趋势跟踪策略 RSI 买入范围下界（默认 35）
# 用途: 上升趋势中 RSI 回调至 35-60 区间视为买入机会，35 表示避免极度超卖区域
# 引用方:
#   - ai/adaptive/strategy_library.py: TrendFollowingStrategy RSI 回调买入 (第165行)
RSI_TREND_BUY_MIN = 35

# 趋势跟踪策略 RSI 买入范围上界（默认 60）
# 用途: 上升趋势中 RSI 回调至 35-60 区间视为买入机会
# 引用方:
#   - ai/adaptive/strategy_library.py: TrendFollowingStrategy RSI 回调买入 (第165行)
RSI_TREND_BUY_MAX = 60

# 趋势跟踪策略 RSI 卖出范围下界（默认 40）
# 用途: 下降趋势中 RSI 反弹至 40-70 区间视为卖出机会
# 引用方:
#   - ai/adaptive/strategy_library.py: TrendFollowingStrategy RSI 反弹卖出 (第182行)
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
#   - ai/config_manager.py: SellConditionsConfig.risk_rsi_overbought (第92行)
#   - ai/dynamic_sell_condition.py: DynamicSellConfig.risk_rsi_overbought (第49行)
RSI_RISK_OVERBOUGHT = 80

# 止盈 RSI 阈值（默认 75）
# 用途: RSI >= 75 视为止盈参考信号
# 引用方:
#   - ai/config_manager.py: SellConditionsConfig.take_profit_rsi_threshold (第89行)
RSI_TAKE_PROFIT = 75

# 高风险 RSI 阈值（默认 75）
# 用途: RSI >= 75 视为高风险区域
# 引用方:
#   - ai/config_manager.py: SellConditionsConfig.risk_rsi_high (第93行)
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
#   - ai/config_manager.py: BuyConditionsConfig.regular_rsi_max (第50行)
RSI_BUY_REGULAR_MAX = 65

# 超卖模式 RSI 上限（默认 30）
# 用途: 超卖买入模式 RSI 必须低于此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.oversold_rsi_max (第57行)
RSI_BUY_OVERSOLD_MAX = 30

# 支撑模式 RSI 上限（默认 35）
# 用途: 强势支撑买入模式 RSI 必须低于此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.support_rsi_max (第66行)
RSI_BUY_SUPPORT_MAX = 35

# 确认模式 RSI 上限（默认 55）
# 用途: 趋势确认买入模式 RSI 必须低于此值
# 引用方:
#   - ai/config_manager.py: BuyConditionsConfig.confirmation_rsi_max (第73行)
RSI_BUY_CONFIRM_MAX = 55