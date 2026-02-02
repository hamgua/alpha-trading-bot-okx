"""
Prompt构建器 - 专业的加密货币量化交易Prompt
"""

from typing import Dict, Any


class PromptBuilder:
    """构建AI交易决策Prompt"""

    # 买入条件阈值
    BUY_TREND_STRENGTH = 0.3
    BUY_RSI_THRESHOLD = 65
    BUY_BB_POSITION = 60
    BUY_ADX_THRESHOLD = 20

    # 卖出条件阈值
    SELL_RSI_THRESHOLD = 75
    SELL_BB_POSITION = 85
    SELL_STOP_LOSS_PERCENT = 2.0

    # 观望条件阈值
    WATCH_TREND_STRENGTH = 0.3
    WATCH_ADX_THRESHOLD = 25
    WATCH_BB_LOW = 40
    WATCH_BB_HIGH = 60
    WATCH_ATR_THRESHOLD = 3.0

    # 暴跌保护阈值
    CRASH_DROP_THRESHOLD = -0.02  # 1小时跌幅 > -2% 视为暴跌

    @classmethod
    def build(cls, market_data: Dict[str, Any]) -> str:
        """构建完整的Prompt"""
        technical = market_data.get("technical", {})
        current_price = market_data.get("price", 0)
        recent_drop = market_data.get("recent_drop_percent", 0)

        # 提取关键指标，带默认值
        rsi = technical.get("rsi", 50)
        macd = technical.get("macd", 0)
        macd_hist = technical.get("macd_histogram", 0)
        adx = technical.get("adx", 0)
        atr_pct = technical.get("atr_percent", 0)
        bb_pos = technical.get("bb_position", 0.5) * 100
        trend_dir = technical.get("trend_direction", "neutral")
        trend_strength = technical.get("trend_strength", 0)

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

        # 判断是否处于暴跌状态
        is_crashing = recent_drop < cls.CRASH_DROP_THRESHOLD

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
            is_crashing=is_crashing,
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
    ) -> str:
        """格式化Prompt"""
        crash_warning = (
            "⚠️ 警告：检测到1小时内价格大幅下跌，谨慎操作！" if is_crashing else ""
        )

        return f"""你是一个专业的加密货币量化交易决策引擎。

【当前持仓状态】
- 持仓方向: {pos_side}
- 持仓数量: {pos_amount:.4f} 张
- 入场价格: {entry_price:.2f} USDT
- 当前浮盈: {unrealized_pnl:.2f} USDT ({pnl_percent:.2f}%)

【当前市场状态】（所有指标基于1小时周期计算）
- 当前价格: {current_price:.2f}
- 1小时涨跌幅: {recent_drop * 100:.2f}% {"⚠️ 警惕下跌趋势" if recent_drop < -0.01 else ""}
- RSI: {rsi:.1f} （>70超买, <30超卖, 50为中性）
- MACD: {macd:.2f}, Histogram: {macd_hist:+.4f} （>0多头动能, <0空头动能）
- ADX: {adx:.1f} （<25无趋势, 25-50有趋势, >50强趋势）
- ATR: {atr_pct:.2f}% （波动率，>3%高波动需谨慎）
- 布林带位置: {bb_pos:.1f}% （<20超卖, >80超买, 50为中轨）
- 趋势方向: {trend_dir}
- 趋势强度: {trend_strength:.2f} （0-1，>0.3为有效趋势）

{crash_warning}

【决策框架】

1. 买入条件（须同时满足）:
   - 趋势方向为 "up" 且 趋势强度 > {cls.BUY_TREND_STRENGTH}
   - RSI < {cls.BUY_RSI_THRESHOLD} （非超买区域）
   - MACD Histogram > 0 （多头动能）
   - 布林带位置 < {cls.BUY_BB_POSITION}% （价格在中轨下方）
   - ADX > {cls.BUY_ADX_THRESHOLD} （有趋势）
   - ⚠️ 1小时跌幅 > -2% 时，禁止买入！
   - ⚠️ 趋势方向为 "down" 时，禁止买入！

2. 卖出/平仓条件（满足任一）:
   - RSI > {cls.SELL_RSI_THRESHOLD} 或 布林带位置 > {cls.SELL_BB_POSITION}%（超买）
   - MACD Histogram < 0（转空头）
   - 趋势方向转 "down"
   - 浮亏 > {cls.SELL_STOP_LOSS_PERCENT}%（触发止损）
   - ⚠️ 暴跌期间（1小时跌幅 > -2%），有持仓则优先考虑减仓或止损

3. 持仓观望条件:
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
4. 高波动市场（ATR>3%）降低仓位或观望
5. ⚠️ 暴跌保护：1小时跌幅 > -2% 时，禁止开仓，优先减仓

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
- 基础置信度：50%
- +10% 趋势明确向上（strength > 0.5）
- +10% RSI < 40（超卖区域）
- +10% MACD Histogram > 0（多头动能）
- +10% ADX > 25（有趋势）
- +10% 布林带位置 < 30%（价格在中轨下方）
- +10% 1小时跌幅 > -1%（近期无大跌）
- +10% 持仓浮盈 > 2%（已有盈利保护）
- -20% 趋势为 "down"
- -20% RSI > 65（接近超买）
- -30% 1小时跌幅 < -2%（暴跌中禁止买入）
- 置信度范围：50%-95%

卖出置信度计算：
- 基础置信度：50%
- +10% 趋势明确向下（strength > 0.5）
- +10% RSI > 70（超买区域）
- +10% MACD Histogram < 0（空头动能）
- +10% ADX > 25（有趋势）
- +10% 布林带位置 > 70%（价格在中轨上方）
- +10% 持仓浮亏 > -2%（触发止损保护）
- -20% 趋势为 "up"
- -20% RSI < 35（超卖区域）
- 置信度范围：50%-95%

持有置信度计算：
- 基础置信度：50%
- +10% 多指标信号冲突
- +10% 趋势强度 < 0.3（无明显趋势）
- +10% ADX < 25（震荡市场）
- +10% ATR > 3%（高波动市场）
- +10% 持仓浮盈在 -1% ~ 2%之间
- -10% 趋势明确且有持仓
- -10% 暴跌期间（1小时跌幅 > -2%）
- 置信度范围：50%-90%

示例：
hold | confidence: 75%
sell | confidence: 80%
buy | confidence: 65%"""


def build_prompt(market_data: Dict[str, Any]) -> str:
    """便捷函数"""
    return PromptBuilder.build(market_data)
