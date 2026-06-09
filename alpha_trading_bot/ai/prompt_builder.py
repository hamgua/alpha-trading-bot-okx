"""
Prompt构建器 - 专业的加密货币量化交易Prompt
"""

from typing import Dict, Any, Optional
from dataclasses import dataclass

from alpha_trading_bot.config.thresholds import RSI_BUY_OVERSOLD_MAX


@dataclass
class PromptConfig:
    """Prompt构建器配置（供未来迁移使用）"""

    buy_trend_strength: float = 0.12
    buy_rsi_threshold: float = 72
    buy_bb_position: float = 70
    buy_adx_threshold: float = 8
    sell_rsi_threshold: float = 75
    sell_bb_position: float = 80
    sell_stop_loss_percent: float = 2.5
    watch_trend_strength: float = 0.15
    watch_adx_threshold: float = 30
    watch_bb_low: float = 30
    watch_bb_high: float = 70
    watch_atr_threshold: float = 6.0
    crash_drop_threshold: float = -0.02
    short_term_buy_threshold: float = 0.01
    momentum_buy_boost: float = 0.15
    oversold_rebound_enabled: bool = True
    oversold_rsi_threshold: float = RSI_BUY_OVERSOLD_MAX
    oversold_max_drawdown: float = 0.015
    oversold_min_drawdown: float = 0.025
    oversold_position_factor: float = 0.3
    kimi_atr_risk_multiplier: float = 1.5
    kimi_conservative_buy: bool = True
    deepseek_low_position_threshold: float = 0.35
    deepseek_rebound_mode_enabled: bool = True
    deepseek_rebound_rsi_max: float = 65


class PromptBuilder:
    """构建AI交易决策Prompt - 差异化系统"""

    _config: Optional["PromptConfig"] = None

    @classmethod
    def set_config(cls, config: "PromptConfig") -> None:
        """设置全局配置（可选）"""
        cls._config = config

    @classmethod
    def _cfg(cls) -> "PromptConfig":
        """获取配置，优先使用设置的配置，否则返回默认值"""
        if cls._config is not None:
            return cls._config
        return PromptConfig()

    # ============== 基础阈值 ==============
    BUY_TREND_STRENGTH = 0.12
    BUY_RSI_THRESHOLD = 72
    BUY_BB_POSITION = 70
    BUY_ADX_THRESHOLD = 8

    SELL_RSI_THRESHOLD = 75  # 降低RSI阈值，更容易卖出
    SELL_BB_POSITION = 80  # 降低布林带位置，更容易卖出
    SELL_STOP_LOSS_PERCENT = 2.5  # 收紧止损

    # 观望条件阈值 - 收紧以减少观望
    WATCH_TREND_STRENGTH = 0.15  # 降低趋势强度阈值（原0.2）
    WATCH_ADX_THRESHOLD = 30  # 提高ADX阈值（原25）
    WATCH_BB_LOW = 30  # 放宽布林带低位（原35）
    WATCH_BB_HIGH = 70  # 放宽布林带高位（原65）
    WATCH_ATR_THRESHOLD = 6.0  # 提高波动率阈值（原5.0）

    # 暴跌保护阈值
    CRASH_DROP_THRESHOLD = -0.02  # 1小时跌幅 > -2% 视为暴跌

    # 短期波动捕捉阈值
    SHORT_TERM_BUY_THRESHOLD = 0.01
    MOMENTUM_BUY_BOOST = 0.15

    # 超卖反弹模式配置
    OVERSOLD_REBOUND_ENABLED = True
    OVERSOLD_RSI_THRESHOLD = 30
    OVERSOLD_MAX_DRAWDOWN = 0.015
    OVERSOLD_MIN_DRAWDOWN = 0.025
    OVERSOLD_POSITION_FACTOR = 0.3

    # ============== 差异化配置 ==============
    # Kimi：更保守，追加风险提示
    KIMI_ATR_RISK_MULTIPLIER = 1.5  # ATR 风险乘数
    KIMI_CONSERVATIVE_BUY = True  # Kimi 买入更保守

    # Deepseek：更容易出 buy，追加低位反弹模式
    DEEPSEEK_LOW_POSITION_THRESHOLD = 0.35  # 35% 以下为低位
    DEEPSEEK_REBOUND_MODE_ENABLED = True  # 启用低位反弹模式
    DEEPSEEK_REBOUND_RSI_MAX = 65  # 反弹模式 RSI 上限（原58，放宽以覆盖更多反弹场景）

    @classmethod
    def build(cls, market_data: Dict[str, Any], provider: str = "default") -> str:
        """构建完整的Prompt - 差异化系统

        Args:
            market_data: 市场数据
            provider: AI 提供商（kimi/deepseek/default）
        """
        technical = market_data.get("technical", {})
        current_price = market_data.get("price", 0)
        recent_drop = market_data.get("recent_drop_percent", 0)
        recent_rise = market_data.get("recent_rise_percent", 0)

        # 提取关键指标
        rsi = technical.get("rsi", 50)
        macd = technical.get("macd", 0)
        macd_hist = technical.get("macd_histogram", 0)
        adx = technical.get("adx", 0)
        atr_pct = technical.get("atr_percent", 0)
        bb_pos = technical.get("bb_position", 0.5) * 100
        trend_dir = technical.get("trend_direction", "neutral")
        trend_strength = technical.get("trend_strength", 0)

        price_history = market_data.get("price_history", [])
        if len(price_history) >= 7:
            low = min(price_history[:7])
            high = max(price_history[:7])
            if high > low:
                price_position = (current_price - low) / (high - low) * 100
            else:
                price_position = 50.0
        else:
            price_position = 50.0

        # 从market_data获取持仓信息
        position_info = market_data.get("position", {})
        pos_side = position_info.get("side", "none") if position_info else "none"
        pos_amount = position_info.get("amount", 0) if position_info else 0
        entry_price = position_info.get("entry_price", 0) if position_info else 0
        unrealized_pnl = position_info.get("unrealized_pnl", 0) if position_info else 0
        pnl_percent = position_info.get("pnl_percent", 0) if position_info else 0
        duration_hours = position_info.get("duration_hours", 0) if position_info else 0
        health = position_info.get("health", "none") if position_info else "none"
        highest_price = position_info.get("highest_price", 0) if position_info else 0
        lowest_price = position_info.get("lowest_price", 0) if position_info else 0

        # 获取市场结构信息（由 integrator 附加到 market_data）
        mkt_structure = market_data.get("market_structure", "")
        mkt_direction = market_data.get("market_structure_direction", "")
        mkt_rr = market_data.get("risk_reward_ratio", 0)
        mkt_support = market_data.get("nearest_support", 0)
        mkt_resistance = market_data.get("nearest_resistance", 0)
        mkt_pos_factor = market_data.get("position_size_factor", 0)

        # 判断是否处于暴跌/暴涨状态
        cfg = cls._cfg()
        is_crashing = recent_drop < cfg.crash_drop_threshold
        is_rising = recent_rise > cfg.short_term_buy_threshold

        # 超卖反弹模式判断
        is_oversold = (
            cfg.oversold_rebound_enabled
            and rsi < cfg.oversold_rsi_threshold
            and cfg.oversold_max_drawdown < recent_drop < cfg.oversold_min_drawdown
        )

        # Deepseek 低位反弹模式
        is_low_position = price_position < cfg.deepseek_low_position_threshold * 100
        is_deepseek_rebound = (
            provider == "deepseek"
            and cfg.deepseek_rebound_mode_enabled
            and is_low_position
            and cfg.oversold_rsi_threshold <= rsi <= cfg.deepseek_rebound_rsi_max
        )

        # Kimi 高波动风险提示
        is_kimi_high_volatility = provider == "kimi" and atr_pct > 0.05  # ATR > 5%

        # 暴跌反弹行情提示
        crash_bounce_guide = ""
        if price_history and len(price_history) >= 2:
            hist_high = max(price_history)
            hist_low = min(price_history)
            if hist_high > 0:
                drop_pct = (hist_high - current_price) / hist_high
                if drop_pct > 0.12:
                    crash_bounce_guide = f"""
跌{drop_pct:.1%}）。在此类大跌后的首次企稳阶段，策略上可考虑：
   - 【暴跌反弹买入】：跌幅>15%，RSI从低位回升至30-60区间，波动率正常→积极关注买入机会
   - 【超跌反弹做空】：反弹至阻力位附近遇阻，可考虑反弹高位做空
   - ⚠️ 仍处于整体下跌趋势时，反弹做多需快进快出，及时止盈
   - 密切关注市场结构是否从下跌(bearish)转为震荡(sideways)，这是企稳信号
"""

        return cls._format_prompt(
            pos_side=pos_side if pos_side != "none" else "无持仓",
            pos_amount=pos_amount,
            entry_price=entry_price,
            unrealized_pnl=unrealized_pnl,
            pnl_percent=pnl_percent,
            duration_hours=duration_hours,
            health=health,
            highest_price=highest_price,
            lowest_price=lowest_price,
            current_price=current_price,
            rsi=rsi,
            macd=macd,
            macd_hist=macd_hist,
            adx=adx,
            atr_pct=atr_pct,
            bb_pos=bb_pos,
            trend_dir=trend_dir,
            trend_strength=trend_strength,
            recent_drop=recent_drop,
            recent_rise=recent_rise,
            is_crashing=is_crashing,
            is_rising=is_rising,
            is_oversold=is_oversold,
            is_deepseek_rebound=is_deepseek_rebound,
            is_kimi_high_volatility=is_kimi_high_volatility,
            provider=provider,
            mkt_structure=mkt_structure,
            mkt_direction=mkt_direction,
            mkt_rr=mkt_rr,
            mkt_support=mkt_support,
            mkt_resistance=mkt_resistance,
            mkt_pos_factor=mkt_pos_factor,
            crash_bounce_guide=crash_bounce_guide,
        )

    @classmethod
    def _format_prompt(
        cls,
        pos_side: str,
        pos_amount: float,
        entry_price: float,
        unrealized_pnl: float,
        pnl_percent: float,
        duration_hours: float,
        health: str,
        highest_price: float,
        lowest_price: float,
        current_price: float,
        rsi: float,
        macd: float,
        macd_hist: float,
        adx: float,
        atr_pct: float,
        bb_pos: float,
        trend_dir: str,
        trend_strength: float,
        recent_drop: float,
        is_crashing: bool,
        recent_rise: float = 0.0,
        is_rising: bool = False,
        is_oversold: bool = False,
        is_deepseek_rebound: bool = False,
        is_kimi_high_volatility: bool = False,
        provider: str = "default",
        mkt_structure: str = "",
        mkt_direction: str = "",
        mkt_rr: float = 0.0,
        mkt_support: float = 0.0,
        mkt_resistance: float = 0.0,
        mkt_pos_factor: float = 0.0,
        crash_bounce_guide: str = "",
    ) -> str:
        """格式化Prompt - 差异化系统"""
        crash_warning = (
            "⚠️ 警告：检测到1小时内价格大幅下跌，谨慎操作！" if is_crashing else ""
        )
        rise_boost = "📈 检测到短期上涨动量，可考虑积极参与！" if is_rising else ""
        oversold_rebound = (
            "🎯 检测到超卖区域（RSI<30），可考虑超卖反弹策略！" if is_oversold else ""
        )

        # Deepseek 低位反弹模式提示
        deepseek_rebound_warning = ""
        if is_deepseek_rebound:
            deepseek_rebound_warning = f"""
🎯 【Deepseek低位反弹模式】已触发：
   - 价格位置 < 35%（低位区间）
   - RSI 在 {cls._cfg().oversold_rsi_threshold:.0f}-{cls._cfg().deepseek_rebound_rsi_max:.0f} 区间
   - 可适当放宽买入条件，积极参与反弹行情
   - 趋势为 "up" 或 "neutral" 时，RSI < {cls._cfg().deepseek_rebound_rsi_max:.0f} 即可考虑买入
   - 布林带位置 < 60%（原 < {cls._cfg().buy_bb_position:.0f}%）
   - 趋势强度 > 0.15 即可（原 > {cls._cfg().buy_trend_strength}）
"""

        # Kimi 高波动风险提示
        kimi_volatility_warning = ""
        if is_kimi_high_volatility:
            kimi_volatility_warning = f"""
⚠️ 【Kimi高波动警示】已触发：
   - ATR = {atr_pct:.1%}（高波动环境）
   - 建议降低买入置信度 15%
   - 建议观望或极小仓位操作
"""

        # 构建市场结构信息字符串
        mkt_structure_info = ""
        if mkt_structure and mkt_direction:
            mkt_structure_info = f"""
【市场结构分析】（基于摆动高/低点自动分析）
- 结构类型: {mkt_structure}（bullish=上涨, bearish=下跌, sideways=震荡）
- 建议方向: {mkt_direction}（long=做多, short=做空, none=观望）
- 支撑位: {mkt_support:.2f}
- 阻力位: {mkt_resistance:.2f}
- 风险收益比(R/R): {mkt_rr:.2f}（>2.0为良好，>3.0为优质）
- 建议仓位系数: {mkt_pos_factor:.2f}
"""

        # 暴跌反弹行情提示（在 build() 中已预计算，直接使用传入的 crash_bounce_guide）
        #
        provider_hint = ""
        if provider == "kimi":
            provider_hint = "【Kimi模式】在满足基本条件时应积极买入，长期持币收益更高"
        elif provider == "deepseek":
            provider_hint = "【Deepseek模式】低位区间应积极买入，把握反弹机会"

        return f"""你是一位拥有10年加密货币交易经验的资深交易员，精通技术分析、市场结构研判和风险管理。你的交易哲学是：耐心等待最佳入场时机，精准出击；宁缺毋滥，不符合风险收益比的交易坚决不做；让利润奔跑，亏损果断止损。

【当前持仓状态】
- 持仓方向: {pos_side}
- 持仓数量: {pos_amount:.4f} 张
- 入场价格: {entry_price:.2f} USDT
- 当前浮盈: {unrealized_pnl:.2f} USDT ({pnl_percent:.2f}%)
- 持仓时长: {duration_hours:.1f} 小时
- 持仓健康度: {health} {'⚠️ 亏损持仓过久，优先考虑止损' if health == 'stale' else '📈 盈利持仓可继续持有' if health == 'profitable' else ''}
{"- 持仓期间最高价: " + f"{highest_price:.2f}" if highest_price > 0 else ""}
{"- 持仓期间最低价: " + f"{lowest_price:.2f}" if lowest_price > 0 else ""}

【当前市场状态】（所有指标基于1小时周期计算）
- 当前价格: {current_price:.2f}
- 1小时涨跌幅: {recent_drop * 100:.2f}% {"⚠️ 警惕下跌趋势" if recent_drop < -0.01 else ""}
- 1小时涨幅: {recent_rise * 100:.2f}% {"📈 短期上涨动量" if is_rising else ""}
- RSI: {rsi:.1f} （>70超买, <30超卖, 50为中性）
- MACD: {macd:.2f}, Histogram: {macd_hist:+.4f} （>0多头动能, <0空头动能）
- ADX: {adx:.1f} （<25无趋势, 25-50有趋势, >50强趋势）
- ATR: {atr_pct:.2f}% （波动率，>5%极高波动需极度谨慎）
- 布林带位置: {bb_pos:.1f}% （<20超卖, >80超买, 50为中轨）
- 趋势方向: {trend_dir}
- 趋势强度: {trend_strength:.2f} （0-1，>0.2为有效趋势）

{crash_warning}
{oversold_rebound}
{rise_boost}
{deepseek_rebound_warning}
{kimi_volatility_warning}
{mkt_structure_info}
{crash_bounce_guide}

{provider_hint}

【交易员决策框架】

⚠️ 信号类型说明：
   - BUY（买入）：确认上涨结构+合理R/R比，做多开仓
   - SELL（卖出）：持仓风险增加或结构破位，平仓离场
   - SHORT（做空）：确认下跌结构+合理R/R比，做空开仓
   - HOLD（观望）：趋势不明朗或R/R比不足，耐心等待

⚠️ 交易员决策优先级（必须按此顺序思考）：
   1. 先看市场结构 → 判断是上涨结构(HH+HL)、下跌结构(LH+LL)还是震荡
   2. 再看风险收益比 → 潜在收益必须是风险的2倍以上才值得入场
   3. 然后看持仓状态 → 有持仓时优先管理风险
   4. 最后看入场时机 → 等待确认信号，不追涨杀跌

⚠️ 资深交易员核心原则：
   - 顺势而为：上涨结构只做多，下跌结构只做空；结构方向为"short"时优先考虑做空
   - 风险收益比门禁：R/R < 2:1 的交易不做
   - 耐心等待：不在信号出现的第一时间入场，等待回踩确认
   - 止损坚决：结构破位立即离场，不抱幻想
   - 让利润奔跑：盈利仓位用移动止盈保护，不轻易止盈

1. 买入条件（BUY，无持仓+上涨趋势时）:
    趋势方向为 "up" 或 "neutral" 且 趋势强度 > {cls._cfg().buy_trend_strength}
    RSI < {cls._cfg().buy_rsi_threshold:.0f} （非超买区域）
    MACD Histogram > 0 （多头动能）
    布林带位置 < {cls._cfg().buy_bb_position:.0f}% （价格在中轨下方）
    ADX > {cls._cfg().buy_adx_threshold:.0f} （有趋势）
    ⚠️ 1小时跌幅 > -2% 时，禁止买入！
    ⚠️ 趋势方向为 "down" 时，禁止买入！

【追加买入场景】（以下情况也可考虑买入，适当放宽条件）:
    【动量买入】：1小时涨幅 > 0.5% 且 RSI < 75 → 可买入
    【低位买入】：价格位置 < 30% 且 RSI < 78 → 可买入
    【突破买入】：1小时涨幅 > 1% 且 趋势向上 → 可买入
    【超跌买入】：1小时跌幅 > -1.5% 且 RSI < 35 → 可买入

【交易员专业入场模式】（以下场景是资深交易员最青睐的入场时机）:
    【回调买入】（黄金入场点）：上涨趋势中价格回调到支撑位附近，RSI从高位回落至45-55区间，MACD仍为正值 → 这是最佳入场时机，风险最低收益最高
    【突破回踩买入】：价格突破前期高点后回踩确认，回踩不破前高且成交量配合 → 趋势确认后入场，胜率最高
    【结构确认买入】：出现HH(Higher High)+HL(Higher Low)上涨结构，当前价格在最近低点之上 → 顺势入场，结构保护

2. 超卖反弹模式（RSI < {cls._cfg().oversold_rsi_threshold:.0f} 且 1h跌幅在 -1.5% ~ -2.5% 区间）:
   - 可适当放宽买入条件，允许买入
   - 趋势强度要求降至 > 0.10（原 > {cls._cfg().buy_trend_strength}）
   - RSI < 35 即可（原 < {cls._cfg().buy_rsi_threshold:.0f}）
   - 布林带位置 < 50%（原 < {cls._cfg().buy_bb_position:.0f}%）
   - ADX > 10 即可（原 > {cls._cfg().buy_adx_threshold:.0f}）
   - ⚠️ 仓位控制在正常仓位的 {cls._cfg().oversold_position_factor:.0%}
   - ⚠️ 1小时跌幅 < -2.5% 时，禁止抄底
   - ⚠️ 暴跌期间（1小时跌幅 > -2%），禁止开仓
   - ⚠️ 暴跌期间（1小时跌幅 > -2%），有持仓则优先考虑减仓或止损

3. 做空条件（无持仓时，满足任一可考虑做空，使用 short 信号输出）:

   【模式A：高位反转做空】（适用于震荡或反弹后的高点）
   - 趋势方向为 "down" 且 趋势强度 > 0.15（明确下跌趋势）
   - RSI > {cls._cfg().sell_rsi_threshold:.0f}（超买区域，可做空）
   - 布林带位置 > {cls._cfg().sell_bb_position:.0f}%（价格在中轨上方，可做空）
   - MACD Histogram < -0.001（空头动能）
   - ⚠️ 禁止逆势做空（趋势为"up"时绝不做空）
   - ⚠️ 禁止在支撑位做空（价格位置 < 30%）

   【模式B：下跌趋势做空】（适用于持续下跌趋势中，这是重点！）
   - 趋势方向为 "down" 且 趋势强度 > 0.20（较强下跌趋势）
   - 累积跌幅 > 3%
   - 持续下跌时间 > 2小时
   - RSI 在 40-70 区间（不要求超买，下跌趋势中超卖是正常的）
   - ⚠️ 禁止逆势做空（趋势为"up"时绝不做空）
   - ⚠️ 不禁止在低位做空（下跌趋势中低位做空是顺势）
   - ⚠️ 但如果价格位置 < 15%（极低位）需谨慎，可能接近反弹

【追加做空场景】（以下情况也可考虑做空，适当放宽条件）:
   【高位做空】：价格位置 > 70% 且 RSI > 72 → 可做空
   【动量做空】：1小时跌幅 > -0.5% 且 趋势向下 → 可做空
   【MACD做空】：MACD < 0 且 MACD 继续下行 → 可做空
   【ADX强势做空】：ADX > 25 且 趋势向下 → 可做空

4. 卖出/平仓条件（SELL，有持仓时触发平仓）:

   【强制平仓】（止损/止盈，优先最高）
    - 持仓浮亏 > 2%（触发止损）
    - 持仓浮盈 > 6%（达到止盈目标）

   【风险平仓】（指标达到危险区域）
    - RSI > 80（严重超买，可能反转）
    - 布林带位置 > 90%（价格触及上轨，风险较大）
    - 趋势明确转空（direction="down" 且 strength > 0.4）
    - 持仓浮盈回撤 > 1%（从盈利转为亏损前自动平仓）

【保守平仓】（可选，根据风险偏好）
     - RSI > 75（超买区域）
     - 布林带位置 > 80%
     - MACD Histogram < -0.002（动能转空）
     - 1小时涨幅 > 1.5%（短期大幅上涨后回落风险）

    【交易员专业退出模式】
     - 【结构破位退出】：上涨结构被破坏（跌破前一个Higher Low），这是最关键的卖出信号，必须果断离场
     - 【移动止盈】：持仓浮盈 > 3%时，将止损上移至入场价以上，确保盈利单不变成亏损单
     - 【趋势减弱退出】：连续上涨后趋势强度从 >0.3 降至 <0.15，动能衰竭，考虑获利了结


5. 观望条件（HOLD，趋势不明朗时）:
    - 多指标信号冲突
    - 趋势强度 < 0.15
    - ADX < 30（无明显趋势）
    - 布林带位置在 30%-70% 区间
    - ATR > 6%（高波动市场）
    - ⚠️ 暴跌期间，无论持仓还是空仓，都应保持观望

【风险控制优先级】
1. 绝不逆趋势交易（趋势为"down"时绝不买入）
2. 风险收益比不足不入场（潜在收益/风险 < 2:1 时不出BUY/SHORT信号）
3. 绝不追高（RSI>70不买）
4. 趋势减弱时优先保盈或减仓
5. 高波动市场（ATR>5%）降低仓位或观望
6. ⚠️ 暴跌保护：1小时跌幅 > -2% 时，禁止开仓，优先减仓
7. ⚠️ 超卖反弹模式需控制仓位为正常仓位的 {cls.OVERSOLD_POSITION_FACTOR:.0%}
8. 结构破位必须止损（跌破前低时立即卖出，不抱幻想）

【捕捉短期波动】
- 当1小时涨幅 > 1% 时，表明有短期上涨动量
- 可适当放宽买入条件，积极参与趋势行情
- 动量强劲时，RSI < 72 即可考虑买入（原70）
- 趋势强度 > 0.3 时，可适当忽略轻微超买信号

【超卖反弹模式】
- 当 RSI < 30 且 1h跌幅在 -1.5% ~ -2.5% 区间时，触发超卖反弹模式
- ⚠️ 注意：超卖反弹模式仅在趋势不为"down"时有效
- ⚠️ 下跌趋势中（趋势为"down"）禁止触发超卖反弹买入
- 暴跌期间（1h跌幅 > -2%）仍禁止开仓

【强制输出要求】
⚠️ 你必须先在内心完成推理，然后只输出最终结果，不要输出任何推理过程！

最终输出格式（只输出这一行，不要有任何前缀或解释）：
buy | confidence: 75%

或：
hold | confidence: 70%

或：
sell | confidence: 80%

或：
short | confidence: 75%

【置信度计算指引】（用于内心推理参考，不要输出）
根据以下因素加权调整：
- 趋势方向与市场结构一致 → +10%~+15%
- RSI在有利区间（buy:<60, sell/short:>70） → +10%
- MACD方向支持 → +10%
- ADX > 15（有趋势） → +10%
- ATR > 5%（高波动） → -10%~-15%
- 1小时跌幅 > 2%（快速下跌） → -15%~-25%
- 趋势与决策方向相反 → -15%
- 置信度范围：BUY/SHORT 50%-90%, HOLD 25%-65%"""


def build_prompt(market_data: Dict[str, Any], provider: str = "default") -> str:
    """构建AI交易决策Prompt - 便捷函数

    Args:
        market_data: 市场数据
        provider: AI 提供商(kimi/deepseek/default)

    Returns:
        格式化后的 prompt
    """
    return PromptBuilder.build(market_data, provider)
