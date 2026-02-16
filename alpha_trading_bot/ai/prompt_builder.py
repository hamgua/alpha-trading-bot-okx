"""
Prompt构建器 - 专业的加密货币量化交易Prompt
"""

from typing import Dict, Any, Optional


class PromptBuilder:
    """构建AI交易决策Prompt - 差异化系统"""

    # ============== 基础阈值 ==============
    BUY_TREND_STRENGTH = 0.12
    BUY_RSI_THRESHOLD = 72
    BUY_BB_POSITION = 70
    BUY_ADX_THRESHOLD = 10

    # 卖出条件阈值 - 收紧以减少卖出
    SELL_RSI_THRESHOLD = 80  # 提高RSI阈值（原75），更难点卖出
    SELL_BB_POSITION = 90  # 提高布林带位置（原85）
    SELL_STOP_LOSS_PERCENT = 3.0  # 放宽止损（原2.0）

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
    DEEPSEEK_REBOUND_RSI_MAX = 58  # 反弹模式 RSI 上限

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

        # 计算综合价格位置
        price_position = market_data.get("composite_price_position", 0.5) * 100

        # 从market_data获取持仓信息
        position_info = market_data.get("position", {})
        pos_side = position_info.get("side", "none") if position_info else "none"
        pos_amount = position_info.get("amount", 0) if position_info else 0
        entry_price = position_info.get("entry_price", 0) if position_info else 0
        unrealized_pnl = position_info.get("unrealized_pnl", 0) if position_info else 0

        if entry_price > 0:
            pnl_percent = (current_price - entry_price) / entry_price * 100
        else:
            pnl_percent = 0

        # 判断是否处于暴跌/暴涨状态
        is_crashing = recent_drop < cls.CRASH_DROP_THRESHOLD
        is_rising = recent_rise > cls.SHORT_TERM_BUY_THRESHOLD

        # 超卖反弹模式判断
        is_oversold = (
            cls.OVERSOLD_REBOUND_ENABLED
            and rsi < cls.OVERSOLD_RSI_THRESHOLD
            and cls.OVERSOLD_MAX_DRAWDOWN < recent_drop < cls.OVERSOLD_MIN_DRAWDOWN
        )

        # Deepseek 低位反弹模式
        is_low_position = price_position < cls.DEEPSEEK_LOW_POSITION_THRESHOLD * 100
        is_deepseek_rebound = (
            provider == "deepseek"
            and cls.DEEPSEEK_REBOUND_MODE_ENABLED
            and is_low_position
            and cls.OVERSOLD_RSI_THRESHOLD <= rsi <= cls.DEEPSEEK_REBOUND_RSI_MAX
        )

        # Kimi 高波动风险提示
        is_kimi_high_volatility = (
            provider == "kimi" and atr_pct > 0.05  # ATR > 5%
        )

        return cls._format_prompt(
            pos_side=pos_side if pos_side != "none" else "无持仓",
            pos_amount=pos_amount,
            entry_price=entry_price,
            unrealized_pnl=unrealized_pnl,
            pnl_percent=pnl_percent,
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
        )

        return cls._format_prompt(
            pos_side=pos_side if pos_side != "none" else "无持仓",
            pos_amount=pos_amount,
            entry_price=entry_price,
            unrealized_pnl=unrealized_pnl,
            pnl_percent=pnl_percent,
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
            recent_rise=recent_rise,  # 新增
            is_crashing=is_crashing,
            is_rising=is_rising,  # 新增
            is_oversold=is_oversold,  # 新增：超卖反弹模式
        )

    @classmethod
    def _format_prompt(
        cls,
        pos_side: str,
        pos_amount: float,
        entry_price: float,
        unrealized_pnl: float,
        pnl_percent: float,
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
        # 差异化参数
        is_deepseek_rebound: bool = False,
        is_kimi_high_volatility: bool = False,
        provider: str = "default",
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
   - RSI 在 {cls.OVERSOLD_RSI_THRESHOLD}-{cls.DEEPSEEK_REBOUND_RSI_MAX} 区间
   - 可适当放宽买入条件，积极参与反弹行情
   - 趋势为 "up" 或 "neutral" 时，RSI < 58 即可考虑买入
   - 布林带位置 < 60%（原 < {cls.BUY_BB_POSITION}%）
   - 趋势强度 > 0.15 即可（原 > {cls.BUY_TREND_STRENGTH}）
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

        # 根据 provider 添加差异化提示
        provider_hint = ""
        if provider == "kimi":
            provider_hint = "【Kimi模式】在满足基本条件时应积极买入，长期持币收益更高"
        elif provider == "deepseek":
            provider_hint = "【Deepseek模式】低位区间应积极买入，把握反弹机会"

        return f"""你是一个专业的加密货币量化交易决策引擎。

【当前持仓状态】
- 持仓方向: {pos_side}
- 持仓数量: {pos_amount:.4f} 张
- 入场价格: {entry_price:.2f} USDT
- 当前浮盈: {unrealized_pnl:.2f} USDT ({pnl_percent:.2f}%)

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

{provider_hint}

【决策框架】

⚠️ 重要提醒：你是一个交易机器人，需要产生交易行为才能获利。
⚠️ 长期不交易会导致资金闲置，无法实现盈利目标。
⚠️ 在不确定时，倾向于买入比观望更好，因为：
   - 数字货币整体呈上涨趋势
   - 即使买入时机不佳，也可以通过后续操作解套
   - 观望永远没有收益

1. 买入条件（须同时满足）:
   - 趋势方向为 "up" 或 "neutral" 且 趋势强度 > {cls.BUY_TREND_STRENGTH}
   - RSI < {cls.BUY_RSI_THRESHOLD} （非超买区域）
   - MACD Histogram > 0 （多头动能）
   - 布林带位置 < {cls.BUY_BB_POSITION}% （价格在中轨下方）
   - ADX > {cls.BUY_ADX_THRESHOLD} （有趋势）
   - ⚠️ 1小时跌幅 > -2% 时，禁止买入！
   - ⚠️ 趋势方向为 "down" 时，禁止买入！

2. 超卖反弹模式（RSI < 30 且 1h跌幅在 -1.5% ~ -2.5% 区间）:
   - 可适当放宽买入条件，允许买入
   - 趋势强度要求降至 > 0.10（原 > {cls.BUY_TREND_STRENGTH}）
   - RSI < 35 即可（原 < {cls.BUY_RSI_THRESHOLD}）
   - 布林带位置 < 50%（原 < {cls.BUY_BB_POSITION}%）
   - ADX > 10 即可（原 > {cls.BUY_ADX_THRESHOLD}）
   - ⚠️ 仓位控制在正常仓位的 {cls.OVERSOLD_POSITION_FACTOR:.0%}
   - ⚠️ 1h跌幅 < -2.5% 时，禁止抄底
   - ⚠️ 暴跌期间（1h跌幅 > -2%）禁止开仓

3. 卖出/平仓条件（满足任一）:
   - RSI > {cls.SELL_RSI_THRESHOLD} 或 布林带位置 > {cls.SELL_BB_POSITION}%（超买）
   - MACD Histogram < 0（转空头）
   - 趋势方向转 "down"
   - 浮亏 > {cls.SELL_STOP_LOSS_PERCENT}%（触发止损）
   - ⚠️ 暴跌期间（1小时跌幅 > -2%），有持仓则优先考虑减仓或止损

4. 持仓观望条件:
   - 多指标信号冲突
   - 趋势强度 < {cls.WATCH_TREND_STRENGTH}
   - ADX < {cls.WATCH_ADX_THRESHOLD}（无明显趋势）
   - 布林带位置在 {cls.WATCH_BB_LOW}%-{cls.WATCH_BB_HIGH}%区间（震荡整理）
   - ATR > {cls.WATCH_ATR_THRESHOLD}%（高波动市场）
   - ⚠️ 暴跌期间，无论持仓还是空仓，都应保持观望

【风险控制优先级】
1. 绝不逆趋势交易（趋势为"down"时绝不买入）
2. 绝不追高（RSI>70不买）
3. 趋势减弱时优先保盈或减仓
4. 高波动市场（ATR>5%）降低仓位或观望
5. ⚠️ 暴跌保护：1小时跌幅 > -2% 时，禁止开仓，优先减仓
6. ⚠️ 超卖反弹模式需控制仓位为正常仓位的 {cls.OVERSOLD_POSITION_FACTOR:.0%}

【捕捉短期波动】
- 当1小时涨幅 > 1% 时，表明有短期上涨动量
- 可适当放宽买入条件，积极参与趋势行情
- 动量强劲时，RSI < 72 即可考虑买入（原70）
- 趋势强度 > 0.3 时，可适当忽略轻微超买信号

【超卖反弹模式】
- 当 RSI < 30 且 1h跌幅在 -1.5% ~ -2.5% 区间时，触发超卖反弹模式
- 允许在下跌趋势中尝试低吸，但需严格控制仓位
- 暴跌期间（1h跌幅 > -2%）仍禁止开仓

【强制输出要求】
⚠️ 你必须先在内心完成推理，然后只输出最终结果，不要输出任何推理过程！

最终输出格式（只输出这一行，不要有任何前缀或解释）：
buy | confidence: 75%
或
hold | confidence: 70%
或
sell | confidence: 80%

【置信度计算规则】（用于内心推理，不要输出）

买入置信度计算：
- 基础置信度：65%  # 适度提高（原60%，避免过高）
- +10% 趋势明确向上（strength > 0.25）
- +10% RSI < 60（低于中轴线）
- +10% MACD Histogram > 0（多头动能）
- +10% ADX > 15（有趋势）
- +10% 布林带位置 < 50%（价格在中轨下方）
- +10% 1小时涨幅 > 0.3%（短期上涨动量）
- +10% 持仓浮盈 > 2%（已有盈利保护）
- +15% 短期上涨动量强劲（1小时涨幅 > 1%）
- -15% 趋势为 "down"  # 保留惩罚
- -15% RSI > 72（超买）  # 保留惩罚（原70）
- -25% 1小时跌幅 < -2.5%（暴跌中禁止买入）  # 保留惩罚
- -10% ATR > 5%（高波动惩罚）  # 保留惩罚
- 置信度范围：50%-90%

超卖反弹置信度计算：
- 基础置信度：65%  # 提高基础置信度（原55%）
- +15% RSI < 25（极度超卖，反弹概率高）
- +10% 1h跌幅在 -1.5% ~ -2.5% 区间（接近支撑位）
- +10% MACD Histogram > -0.001（空头动能减弱）
- +10% 布林带位置 < 30%（接近下轨）
- +10% ADX > 15（有趋势动能）
- -10% 趋势方向为 "down"（逆势操作需谨慎）  # 降低惩罚（原-15%）
- -15% 1h跌幅 < -2.5%（可能继续下跌）  # 降低惩罚（原-20%）
- -15% ATR > 5%（高波动，风险较大）  # 降低惩罚（原-20%）
- 置信度范围：50%-90%

卖出置信度计算：
- 基础置信度：50%  # 降低基础卖出置信度（原55%）
- +10% 趋势明确向下（strength > 0.4）
- +10% RSI > 75（超买区域）
- +10% MACD Histogram < 0（空头动能）
- +10% ADX > 25（有趋势）
- +10% 布林带位置 > 75%（价格在中轨上方）
- +10% 持仓浮亏 > -3%（触发止损保护）  # 放宽（原-2%）
- -15% 趋势为 "up"  # 提高惩罚（原-20%）
- -15% RSI < 40（超卖区域）  # 提高惩罚（原-20%）
- 置信度范围：45%-90%

持有置信度计算：
- 基础置信度：45%  # 大幅降低基础持有置信度（原58%）
- +10% 多指标信号冲突
- +10% 趋势强度 < 0.20（无明显趋势）  # 放宽（原0.25）
- +10% ADX < 25（震荡市场）  # 放宽（原22）
- +10% ATR > 5%（高波动市场）
- +10% 持仓浮盈在 -2% ~ 3%之间  # 放宽（原-1%~2%）
- -10% 趋势明确且有持仓
- -10% 暴跌期间（1小时跌幅 > -2%）
- -15% 持仓浮盈 > 5%（有盈利应该考虑部分止盈）  # 新增惩罚
- 置信度范围：40%-80%  # 降低上限（原50%-90%）

示例：
hold | confidence: 75%
sell | confidence: 80%
buy | confidence: 65%"""


def build_prompt(market_data: Dict[str, Any], provider: str = "default") -> str:
    """构建AI交易决策Prompt - 便捷函数

    Args:
        market_data: 市场数据
        provider: AI 提供商（kimi/deepseek/default），影响 prompt 差异化

    Returns:
        格式化后的 prompt
    """
    return PromptBuilder.build(market_data, provider)
