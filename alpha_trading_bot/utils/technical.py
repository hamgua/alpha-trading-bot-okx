"""
技术指标计算模块
提供ATR、布林带、ADX、RSI、MACD等常用技术指标的计算
"""

import numpy as np
from typing import List, Optional, Tuple, Dict, Any, Sequence
import logging
from .price_calculator import PriceCalculator

logger = logging.getLogger(__name__)


class TechnicalIndicators:
    """技术指标计算器"""

    @staticmethod
    def calculate_atr(
        high: List[float], low: List[float], close: List[float], period: int = 14
    ) -> List[float]:
        """
        计算平均真实波幅（ATR）

        Args:
            high: 最高价列表
            low: 最低价列表
            close: 收盘价列表
            period: 计算周期，默认14

        Returns:
            ATR值列表
        """
        try:
            if len(high) < period or len(low) < period or len(close) < period:
                return [0.0] * len(close)

            # 计算真实波幅（TR）
            tr_values = []
            for i in range(1, len(close)):
                high_low = high[i] - low[i]
                high_close = abs(high[i] - close[i - 1])
                low_close = abs(low[i] - close[i - 1])
                tr = max(high_low, high_close, low_close)
                tr_values.append(tr)

            # 前period-1个值用简单平均
            atr_values = [0.0] * period
            if len(tr_values) >= period:
                initial_atr = np.mean(tr_values[:period])
                atr_values[period - 1] = float(initial_atr)

                # 计算后续ATR值（使用平滑公式）
                for i in range(period, len(tr_values)):
                    atr = (atr_values[i - 1] * (period - 1) + tr_values[i]) / period
                    atr_values.append(atr)

            return atr_values

        except Exception as e:
            logger.error(f"计算ATR失败: {e}")
            return [0.0] * len(close)

    @staticmethod
    def calculate_bollinger_bands(
        close: List[float], period: int = 20, num_std: float = 2.0
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        计算布林带

        Args:
            close: 收盘价列表
            period: 计算周期，默认20
            num_std: 标准差倍数，默认2.0

        Returns:
            (中轨, 上轨, 下轨)
        """
        try:
            if len(close) < period:
                return (
                    [close[0]] * len(close),
                    [close[0]] * len(close),
                    [close[0]] * len(close),
                )

            middle_band = []
            upper_band = []
            lower_band = []

            for i in range(period - 1, len(close)):
                # 计算SMA
                sma = np.mean(close[i - period + 1 : i + 1])
                # 计算标准差
                std = np.std(close[i - period + 1 : i + 1])

                middle_band.append(sma)
                upper_band.append(sma + num_std * std)
                lower_band.append(sma - num_std * std)

            # 前period-1个值用第一个计算值填充
            if middle_band:
                first_middle = middle_band[0]
                first_upper = upper_band[0]
                first_lower = lower_band[0]

                middle_band = [first_middle] * (period - 1) + middle_band
                upper_band = [first_upper] * (period - 1) + upper_band
                lower_band = [first_lower] * (period - 1) + lower_band
            else:
                middle_band = [close[0]] * len(close)
                upper_band = [close[0]] * len(close)
                lower_band = [close[0]] * len(close)

            return middle_band, upper_band, lower_band

        except Exception as e:
            logger.error(f"计算布林带失败: {e}")
            return (
                [close[0]] * len(close),
                [close[0]] * len(close),
                [close[0]] * len(close),
            )

    @staticmethod
    def calculate_adx(
        high: List[float], low: List[float], close: List[float], period: int = 14
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        计算ADX（平均趋向指数）

        Args:
            high: 最高价列表
            low: 最低价列表
            close: 收盘价列表
            period: 计算周期，默认14

        Returns:
            (ADX值列表, +DI值列表, -DI值列表)
        """
        try:
            if (
                len(high) < period * 2
                or len(low) < period * 2
                or len(close) < period * 2
            ):
                zero_list = [0.0] * len(close)
                return zero_list, zero_list.copy(), zero_list.copy()

            # 计算TR、+DM、-DM
            tr_values = []
            plus_dm_values = []
            minus_dm_values = []

            for i in range(1, len(close)):
                # TR
                high_low = high[i] - low[i]
                high_close = abs(high[i] - close[i - 1])
                low_close = abs(low[i] - close[i - 1])
                tr = max(high_low, high_close, low_close)
                tr_values.append(tr)

                # +DM
                up_move = high[i] - high[i - 1]
                down_move = low[i - 1] - low[i]
                if up_move > down_move and up_move > 0:
                    plus_dm = up_move
                else:
                    plus_dm = 0
                plus_dm_values.append(plus_dm)

                # -DM
                if down_move > up_move and down_move > 0:
                    minus_dm = down_move
                else:
                    minus_dm = 0
                minus_dm_values.append(minus_dm)

            # 计算平滑值
            atr_values = [0.0] * period
            plus_di_values = [0.0] * period
            minus_di_values = [0.0] * period
            dx_values = [0.0] * period

            if len(tr_values) >= period:
                # 初始值
                initial_atr = np.mean(tr_values[:period])
                initial_plus_dm = np.mean(plus_dm_values[:period])
                initial_minus_dm = np.mean(minus_dm_values[:period])

                atr_values[period - 1] = float(initial_atr)
                plus_dm_smooth = initial_plus_dm
                minus_dm_smooth = initial_minus_dm

                # 计算后续值
                for i in range(period, len(tr_values)):
                    # 平滑TR
                    atr = (atr_values[i - 1] * (period - 1) + tr_values[i]) / period
                    atr_values.append(atr)

                    # 平滑+DM和-DM
                    plus_dm_smooth = (
                        plus_dm_smooth * (period - 1) + plus_dm_values[i]
                    ) / period
                    minus_dm_smooth = (
                        minus_dm_smooth * (period - 1) + minus_dm_values[i]
                    ) / period

                    # 计算+DI和-DI
                    plus_di = 100 * plus_dm_smooth / atr if atr > 0 else 0
                    minus_di = 100 * minus_dm_smooth / atr if atr > 0 else 0

                    plus_di_values.append(plus_di)
                    minus_di_values.append(minus_di)

                    # 计算DX
                    diff = abs(plus_di - minus_di)
                    sum_val = plus_di + minus_di
                    dx = 100 * diff / sum_val if sum_val > 0 else 0
                    dx_values.append(dx)

            # 计算ADX（DX的平滑）
            adx_values = [0.0] * (period * 2 - 1)
            plus_di_full = [0.0] * len(close)
            minus_di_full = [0.0] * len(close)

            if len(dx_values) >= period:
                initial_adx = np.mean(dx_values[period - 1 : period * 2 - 1])
                adx_values[period * 2 - 2] = float(initial_adx)

                for i in range(period * 2 - 1, len(dx_values)):
                    adx = (adx_values[i - 1] * (period - 1) + dx_values[i]) / period
                    adx_values.append(adx)

            # 填充 +DI 和 -DI 的完整列表
            # 前 period 个值用 0 填充
            # 从 period 开始使用计算的值
            for i in range(len(plus_di_values)):
                idx = i + period
                if idx < len(close):
                    plus_di_full[idx] = plus_di_values[i]
                    minus_di_full[idx] = minus_di_values[i]

            return adx_values, plus_di_full, minus_di_full

        except Exception as e:
            logger.error(f"计算ADX失败: {e}")
            zero_list = [0.0] * len(close)
            return zero_list, zero_list.copy(), zero_list.copy()

    @staticmethod
    def calculate_rsi(close: List[float], period: int = 14) -> List[float]:
        """
        计算RSI（相对强弱指数）

        Args:
            close: 收盘价列表
            period: 计算周期，默认14

        Returns:
            RSI值列表
        """
        try:
            if len(close) < period + 1:
                return [50.0] * len(close)

            gains = []
            losses = []

            # 计算价格变化
            for i in range(1, len(close)):
                change = close[i] - close[i - 1]
                if change > 0:
                    gains.append(change)
                    losses.append(0)
                else:
                    gains.append(0)
                    losses.append(-change)

            rsi_values = [50.0] * period

            if len(gains) >= period:
                # 初始平均收益和损失
                avg_gain = np.mean(gains[:period])
                avg_loss = np.mean(losses[:period])

                for i in range(period, len(gains)):
                    # 平滑计算
                    avg_gain = (avg_gain * (period - 1) + gains[i]) / period
                    avg_loss = (avg_loss * (period - 1) + losses[i]) / period

                    # 计算RSI
                    if avg_loss == 0:
                        rsi = 100.0
                    else:
                        rs = avg_gain / avg_loss
                        rsi = 100 - (100 / (1 + rs))

                    rsi_values.append(rsi)

            return rsi_values

        except Exception as e:
            logger.error(f"计算RSI失败: {e}")
            return [50.0] * len(close)

    @staticmethod
    def calculate_macd(
        close: List[float],
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
    ) -> Tuple[List[float], List[float], List[float]]:
        """
        计算MACD

        Args:
            close: 收盘价列表
            fast_period: 快速EMA周期，默认12
            slow_period: 慢速EMA周期，默认26
            signal_period: 信号线周期，默认9

        Returns:
            (MACD线, 信号线, 柱状图)
        """
        try:
            if len(close) < slow_period + signal_period:
                return [0.0] * len(close), [0.0] * len(close), [0.0] * len(close)

            # 计算EMA
            fast_ema = TechnicalIndicators.calculate_ema(close, fast_period)
            slow_ema = TechnicalIndicators.calculate_ema(close, slow_period)

            # 计算MACD线
            macd_line = []
            for i in range(len(slow_ema)):
                if i < len(fast_ema):
                    macd = fast_ema[i] - slow_ema[i]
                    macd_line.append(macd)
                else:
                    macd_line.append(0.0)

            # 计算信号线（MACD的EMA）
            signal_line = TechnicalIndicators.calculate_ema(macd_line, signal_period)

            # 计算柱状图
            histogram = []
            for i in range(len(macd_line)):
                if i < len(signal_line):
                    hist = macd_line[i] - signal_line[i]
                    histogram.append(hist)
                else:
                    histogram.append(0.0)

            return macd_line, signal_line, histogram

        except Exception as e:
            logger.error(f"计算MACD失败: {e}")
            return [0.0] * len(close), [0.0] * len(close), [0.0] * len(close)

    @staticmethod
    def calculate_sma(close: List[float], period: int) -> List[float]:
        """
        计算简单移动平均线（SMA）

        Args:
            close: 收盘价列表
            period: 计算周期

        Returns:
            SMA值列表
        """
        try:
            if len(close) < period:
                return [close[0]] * len(close)

            sma_values = []
            for i in range(period - 1, len(close)):
                sma = np.mean(close[i - period + 1 : i + 1])
                sma_values.append(sma)

            # 前period-1个值用第一个SMA值填充
            if sma_values:
                first_sma = sma_values[0]
                sma_values = [first_sma] * (period - 1) + sma_values
            else:
                sma_values = [close[0]] * len(close)

            return sma_values

        except Exception as e:
            logger.error(f"计算SMA失败: {e}")
            return [close[0]] * len(close)

    @staticmethod
    def calculate_ema(close: List[float], period: int) -> List[float]:
        """
        计算指数移动平均线（EMA）

        Args:
            close: 收盘价列表
            period: 计算周期

        Returns:
            EMA值列表
        """
        try:
            if len(close) < period:
                return [close[0]] * len(close)

            ema_values = []
            # 初始EMA用SMA计算
            initial_ema = np.mean(close[:period])
            ema_values.append(initial_ema)

            # EMA平滑系数
            multiplier = 2 / (period + 1)

            # 计算后续EMA值
            for i in range(period, len(close)):
                ema = (close[i] - ema_values[-1]) * multiplier + ema_values[-1]
                ema_values.append(ema)

            # 前period-1个值用初始EMA填充
            ema_values = [initial_ema] * (period - 1) + ema_values

            return ema_values

        except Exception as e:
            logger.error(f"计算EMA失败: {e}")
            return [close[0]] * len(close)

    @staticmethod
    def calculate_trend_analysis(
        close: List[float],
        periods: List[int] = [10, 20, 50],
        price_position: float = 50.0,
    ) -> Dict[str, Any]:
        """
        计算趋势分析 - 集成价格位置权重

        Args:
            close: 收盘价列表
            periods: 趋势分析周期列表，默认[10, 20, 50]
            price_position: 当前价格位置百分比(0-100)，用于调整趋势权重

        Returns:
            趋势分析结果字典
        """
        try:
            if len(close) < max(periods):
                return {
                    "overall_trend": "neutral",
                    "trend_strength": 0.0,
                    "trend_consensus": 0.0,
                    "trend_details": {},
                }

            trend_scores = {}
            current_price = close[-1]

            # 价格位置权重因子 - 平衡趋势和价格位置
            # 高位时降低趋势权重，避免在高位过度追涨
            # 低位时保持趋势权重，不错过低位机会
            if price_position >= 90:  # 极高位
                price_weight_factor = 0.6  # 大幅降低趋势权重
            elif price_position >= 80:  # 高位
                price_weight_factor = 0.7
            elif price_position >= 70:  # 偏高
                price_weight_factor = 0.8
            elif price_position <= 10:  # 极低位
                price_weight_factor = 1.2  # 增加趋势权重，积极捕捉低位机会
            elif price_position <= 20:  # 低位
                price_weight_factor = 1.1
            elif price_position <= 30:  # 偏低
                price_weight_factor = 1.05
            else:  # 中性区域
                price_weight_factor = 1.0

            trend_scores = {}
            current_price = close[-1]

            # 计算每个周期的趋势
            for period in periods:
                if len(close) >= period:
                    # 计算移动平均线
                    ma = TechnicalIndicators.calculate_sma(close, period)
                    current_ma = ma[-1]

                    # 计算斜率（价格变化率）
                    start_price = close[-period]
                    price_change = (current_price - start_price) / start_price

                    # 计算相对于均线的位置
                    ma_distance = (current_price - current_ma) / current_ma

                    # 综合趋势评分 (-1 到 1)
                    trend_score = 0

                    # 基于价格变化的趋势（优化敏感度 - 避免过度交易）
                    if price_change > 0.01:  # 上涨超过1.0% (降低阈值)
                        trend_score += 0.5
                    elif price_change > 0.008:  # 上涨0.8-1.0% (提高阈值)
                        trend_score += 0.35
                    elif price_change > 0.005:  # 上涨0.5-0.8% (提高阈值)
                        trend_score += 0.25
                    elif price_change > 0.003:  # 上涨0.3-0.5% (提高阈值)
                        trend_score += 0.15  # 降低权重
                    elif price_change > 0.001:  # 上涨0.1-0.3% (仅小幅加分)
                        trend_score += 0.08  # 大幅降低权重
                    elif price_change > 0:  # 微涨0-0.05%
                        trend_score += 0.08
                    elif price_change < -0.01:  # 下跌超过1.0%
                        trend_score -= 0.5
                    elif price_change < -0.008:  # 下跌0.8-1.0% (提高阈值)
                        trend_score -= 0.35
                    elif price_change < -0.005:  # 下跌0.5-0.8% (提高阈值)
                        trend_score -= 0.25
                    elif price_change < -0.003:  # 下跌0.3-0.5% (提高阈值)
                        trend_score -= 0.15  # 降低权重
                    elif price_change < -0.001:  # 下跌0.1-0.3% (仅小幅扣分)
                        trend_score -= 0.08  # 大幅降低权重
                    elif price_change < 0:  # 微跌0-0.05%
                        trend_score -= 0.08

                    # 基于均线位置的趋势
                    if ma_distance > 0.02:  # 价格在均线上方2%
                        trend_score += 0.3
                    elif ma_distance > 0:  # 价格在均线上方
                        trend_score += 0.1
                    elif ma_distance < -0.02:  # 价格在均线下方2%
                        trend_score -= 0.3
                    elif ma_distance < 0:  # 价格在均线下方
                        trend_score -= 0.1

                    # 基于更高时间框架的趋势一致性
                    if len(close) >= period * 2:
                        longer_ma = TechnicalIndicators.calculate_sma(close, period * 2)
                        if current_ma > longer_ma[-1] and trend_score > 0:
                            trend_score += 0.2  # 强化上升趋势
                        elif current_ma < longer_ma[-1] and trend_score < 0:
                            trend_score -= 0.2  # 强化下降趋势

                    trend_scores[f"ma_{period}"] = max(
                        -1, min(1, trend_score)
                    )  # 限制在-1到1之间

            # 计算总体趋势共识
            if trend_scores:
                trend_values = list(trend_scores.values())
                trend_consensus = np.mean(trend_values)

                # 应用价格位置权重到趋势共识
                adjusted_consensus = trend_consensus * price_weight_factor

                # 确定总体趋势方向（基于调整后的共识）
                if adjusted_consensus > 0.25:  # 强上涨趋势
                    overall_trend = "strong_uptrend"
                elif adjusted_consensus > 0.08:  # 中等上涨趋势
                    overall_trend = "uptrend"
                elif adjusted_consensus < -0.25:  # 强下跌趋势
                    overall_trend = "strong_downtrend"
                elif adjusted_consensus < -0.08:  # 中等下跌趋势
                    overall_trend = "downtrend"
                else:
                    overall_trend = "neutral"

                # 计算调整后的趋势强度
                trend_strength = min(abs(adjusted_consensus) * 1.2, 0.9)

                # 如果时间框架之间分歧很大，降低强度
                if len(trend_values) > 1:
                    max_diff = max(trend_values) - min(trend_values)
                    if max_diff > 1.0:  # 分歧很大
                        trend_strength *= 0.5

                # 记录价格位置对趋势的影响
                if price_weight_factor != 1.0:
                    logger.debug(
                        f"趋势分析：价格位置权重因子={price_weight_factor}, 原始共识={trend_consensus:.3f}, 调整后共识={adjusted_consensus:.3f}"
                    )

                return {
                    "overall_trend": overall_trend,
                    "trend_strength": trend_strength,
                    "trend_consensus": trend_consensus,
                    "trend_details": trend_scores,
                }
            else:
                return {
                    "overall_trend": "neutral",
                    "trend_strength": 0.0,
                    "trend_consensus": 0.0,
                    "trend_details": {},
                }

        except Exception as e:
            logger.error(f"计算趋势分析失败: {e}")
            return {
                "overall_trend": "neutral",
                "trend_strength": 0.0,
                "trend_consensus": 0.0,
                "trend_details": {},
            }

    @staticmethod
    def calculate_all_indicators(market_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        计算所有技术指标

        Args:
            market_data: 包含OHLCV数据的字典

        Returns:
            包含所有计算结果的字典
        """
        try:
            # 使用新的键名获取OHLCV数据
            close = market_data.get("close_prices", [])
            high = market_data.get("high_prices", [])
            low = market_data.get("low_prices", [])

            if not close or len(close) < 50:
                return {}

            result = {}

            # 价格位置
            if len(close) > 0:
                current_price = close[-1]
                recent_high = max(close[-20:]) if len(close) >= 20 else max(close)
                recent_low = min(close[-20:]) if len(close) >= 20 else min(close)
                result["price_position"] = (
                    (current_price - recent_low) / (recent_high - recent_low)
                    if recent_high != recent_low
                    else 0.5
                )

            # SMA
            if len(close) >= 20:
                result["sma_20"] = TechnicalIndicators.calculate_sma(close, 20)[-1]
            if len(close) >= 50:
                result["sma_50"] = TechnicalIndicators.calculate_sma(close, 50)[-1]

            # EMA
            if len(close) >= 20:
                result["ema_20"] = TechnicalIndicators.calculate_ema(close, 20)[-1]

            # ATR
            if len(high) >= 14 and len(low) >= 14 and len(close) >= 14:
                result["atr"] = TechnicalIndicators.calculate_atr(high, low, close, 14)[
                    -1
                ]

            # 布林带
            if len(close) >= 20:
                bb_middle, bb_upper, bb_lower = (
                    TechnicalIndicators.calculate_bollinger_bands(close, 20)
                )
                result["bb_upper"] = bb_upper[-1]
                result["bb_middle"] = bb_middle[-1]
                result["bb_lower"] = bb_lower[-1]

            # RSI
            if len(close) >= 14:
                rsi_values = TechnicalIndicators.calculate_rsi(close, 14)
                result["rsi"] = rsi_values[-1]

            # ADX
            if len(high) >= 28 and len(low) >= 28 and len(close) >= 28:
                adx_values = TechnicalIndicators.calculate_adx(high, low, close, 14)
                result["adx"] = adx_values[-1]

            # MACD
            if len(close) >= 35:
                macd, signal, histogram = TechnicalIndicators.calculate_macd(close)
                result["macd"] = macd[-1]
                result["macd_signal"] = signal[-1]
                result["macd_histogram"] = histogram[-1]

            # 波动率
            if len(close) >= 30:
                returns = [
                    (close[i] - close[i - 1]) / close[i - 1]
                    for i in range(1, len(close))
                ]
                volatility_30d = (
                    np.std(returns[-30:]) * np.sqrt(365)
                    if len(returns) >= 30
                    else np.std(returns) * np.sqrt(365)
                )
                result["volatility_30d"] = volatility_30d

            # 趋势分析 - 集成价格位置权重
            if len(close) >= 50:
                # 获取综合价格位置（如果之前已计算）或使用默认值
                composite_position = (
                    result.get("price_position", 0.5) * 100
                )  # 转换为0-100范围
                trend_data = TechnicalIndicators.calculate_trend_analysis(
                    close, [10, 20, 50], composite_position
                )
                result["trend_analysis"] = trend_data

            return result

        except Exception as e:
            logger.error(f"计算所有技术指标失败: {e}")
            return {}
