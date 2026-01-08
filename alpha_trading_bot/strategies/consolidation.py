"""
改进的横盘检测模块
基于多种技术指标的横盘状态识别
"""

import numpy as np
from typing import Dict, Any, Tuple, Optional
from datetime import datetime, timedelta
import logging

logger = logging.getLogger(__name__)

# 币种特异性横盘参数（基于波动率调整）
CONSOLIDATION_PARAMS = {
    'BTC/USDT': {
        'atr_threshold': 0.015,      # 1.5%
        'bb_width_threshold': 0.03,  # 3%
        'adx_threshold': 25,         # ADX小于25视为无趋势
        'min_duration_hours': 6,     # 最少6小时确认
        'price_range_threshold': 0.04 # 4%的价格区间
    },
    'ETH/USDT': {
        'atr_threshold': 0.02,       # 2%
        'bb_width_threshold': 0.035, # 3.5%
        'adx_threshold': 25,
        'min_duration_hours': 6,
        'price_range_threshold': 0.05
    },
    'SHIB/USDT': {
        'atr_threshold': 0.05,       # 5%（山寨币波动更大）
        'bb_width_threshold': 0.08,  # 8%
        'adx_threshold': 30,
        'min_duration_hours': 4,
        'price_range_threshold': 0.10
    },
    'DEFAULT': {
        'atr_threshold': 0.025,      # 2.5%
        'bb_width_threshold': 0.04,  # 4%
        'adx_threshold': 25,
        'min_duration_hours': 6,
        'price_range_threshold': 0.06
    }
}

class ConsolidationDetector:
    """改进的横盘检测器"""

    def __init__(self):
        self.consolidation_history = {}
        self.multi_timeframe_data = {}

    def detect_consolidation(self, market_data: Dict[str, Any], symbol: str = 'BTC/USDT') -> Tuple[bool, str, float]:
        """
        检测市场是否处于横盘状态 - 添加趋势感知

        Args:
            market_data: 市场数据，包含价格、成交量等信息
            symbol: 交易对符号

        Returns:
            (是否横盘, 原因说明, 置信度)
        """
        try:
            # 获取币种特异性参数
            params = CONSOLIDATION_PARAMS.get(symbol, CONSOLIDATION_PARAMS['DEFAULT'])

            # 动态参数调整：根据市场波动率调整阈值
            params = self._adjust_params_by_volatility(market_data, params)

            # 检查趋势强度 - 新增
            trend_direction = market_data.get('trend_direction', 'neutral')
            trend_strength = market_data.get('trend_strength', 'normal')

            # 在强势趋势中提高检测阈值或禁用
            if trend_strength in ['strong', 'extreme']:
                # 在强势趋势中，横盘检测应该更困难
                params['atr_threshold'] = params['atr_threshold'] * 0.7  # 收紧ATR阈值
                params['adx_threshold'] = params['adx_threshold'] * 1.2  # 提高ADX要求
                logger.info(f"检测到{trend_strength}趋势，提高横盘检测难度")

            # 1. 基础数据检查
            if not self._validate_market_data(market_data):
                return False, "市场数据不完整", 0.0

            # 2. 多时间框架分析
            consolidation_score = self._multi_timeframe_analysis(market_data, symbol)

            # 3. 技术指标分析
            technical_score = self._technical_indicators_analysis(market_data, params)

            # 4. 波动率分析
            volatility_score = self._volatility_analysis(market_data, params)

            # 5. 成交量分析
            volume_score = self._volume_analysis(market_data)

            # 6. 综合评分（调整权重：增加成交量权重）
            final_score = (
                consolidation_score * 0.25 +  # 降低多时间框架权重
                technical_score * 0.25 +
                volatility_score * 0.25 +
                volume_score * 0.25  # 增加成交量权重至25%
            )

            # 7. 趋势感知调整 - 新增
            if trend_strength in ['strong', 'extreme']:
                # 在强势趋势中，降低横盘评分
                final_score = final_score * 0.7
                logger.info(f"{trend_strength}趋势下，横盘评分调整为{final_score:.2f}")

            # 8. 生成结果
            # 根据趋势强度调整阈值
            if trend_strength in ['strong', 'extreme']:
                threshold = 0.7  # 强势趋势需要更高评分
            else:
                threshold = 0.5  # 正常阈值

            is_consolidation = final_score > threshold
            confidence = min(final_score, 0.95)
            reason = self._generate_reason(final_score, consolidation_score, technical_score, volatility_score)

            # 增强日志：显示详细评分和阈值对比
            logger.info(f"横盘检测结果: {is_consolidation}")
            logger.info(f"📊 综合评分详情:")
            logger.info(f"   最终评分: {final_score:.3f} (阈值: 0.5)")
            logger.info(f"   多时间框架评分: {consolidation_score:.3f} (权重: 25%)")
            logger.info(f"   技术指标评分: {technical_score:.3f} (权重: 25%)")
            logger.info(f"   波动率评分: {volatility_score:.3f} (权重: 25%)")
            logger.info(f"   成交量评分: {volume_score:.3f} (权重: 25%)")

            # 如果评分低，显示具体原因
            if final_score < 0.5:
                low_score_reasons = []
                if consolidation_score < 0.5:
                    low_score_reasons.append(f"价格未处于中间区域 ({consolidation_score:.2f} < 0.5)")
                if technical_score < 0.5:
                    low_score_reasons.append(f"技术指标显示有趋势 ({technical_score:.2f} < 0.5)")
                if volatility_score < 0.5:
                    low_score_reasons.append(f"波动率较高 ({volatility_score:.2f} < 0.5)")
                if volume_score < 0.5:
                    low_score_reasons.append(f"成交量异常 ({volume_score:.2f} < 0.5)")

                if low_score_reasons:
                    logger.info(f"❌ 低评分原因: {'; '.join(low_score_reasons)}")

                # 显示具体的阈值比较结果
                logger.info(f"评分 {final_score:.2f} < 0.5 (阈值)，判定为非横盘状态")
            else:
                logger.info(f"✅ 评分 {final_score:.2f} ≥ 0.5 (阈值)，判定为横盘状态")

            logger.info(f"横盘检测结果: {is_consolidation}, 评分: {final_score:.2f}, 原因: {reason}")

            return is_consolidation, reason, confidence

        except Exception as e:
            logger.error(f"横盘检测失败: {e}")
            return False, f"检测失败: {str(e)}", 0.0

    def _adjust_params_by_volatility(self, market_data: Dict[str, Any], params: Dict[str, float]) -> Dict[str, float]:
        """根据市场波动率动态调整参数"""
        try:
            # 获取ATR波动率
            technical_data = market_data.get('technical_data', {})
            atr_pct = float(technical_data.get('atr_pct', 0))

            # 低波动率环境（ATR < 1.5%）
            if atr_pct < 1.5:
                # 降低横盘检测阈值，更容易识别横盘
                adjusted_params = params.copy()
                adjusted_params['atr_threshold'] *= 1.2  # 增加20%，适应低波动
                adjusted_params['bb_width_threshold'] *= 0.8  # 降低20%，更容易识别横盘
                adjusted_params['price_range_threshold'] *= 0.7  # 降低30%，适应窄幅波动
                logger.debug(f"低波动率环境检测：ATR={atr_pct:.2f}%，调整横盘参数")
                return adjusted_params

            # 高波动率环境（ATR > 3%）
            elif atr_pct > 3.0:
                # 提高横盘检测阈值，避免误判
                adjusted_params = params.copy()
                adjusted_params['atr_threshold'] *= 0.8  # 降低20%
                adjusted_params['bb_width_threshold'] *= 1.2  # 增加20%
                adjusted_params['price_range_threshold'] *= 1.3  # 增加30%
                logger.debug(f"高波动率环境检测：ATR={atr_pct:.2f}%，调整横盘参数")
                return adjusted_params

            # 正常波动率环境
            return params

        except Exception as e:
            logger.warning(f"动态参数调整失败: {e}，使用默认参数")
            return params

    def _validate_market_data(self, market_data: Dict[str, Any]) -> bool:
        """验证市场数据完整性"""
        required_fields = ['price', 'high', 'low', 'volume', 'timestamp']
        for field in required_fields:
            if field not in market_data or market_data[field] is None:
                return False
        return True

    def _multi_timeframe_analysis(self, market_data: Dict[str, Any], symbol: str) -> float:
        """多时间框架分析"""
        try:
            current_price = float(market_data['price'])

            # 获取多时间框架数据
            multi_timeframe = market_data.get('multi_timeframe', {})

            scores = []
            weights = []

            # 15分钟框架（主时间框架）
            if '15m' in multi_timeframe and len(multi_timeframe['15m']) >= 20:
                ohlcv_15m = multi_timeframe['15m'][-20:]  # 最近20根K线
                high_15m = max(candle[2] for candle in ohlcv_15m)
                low_15m = min(candle[3] for candle in ohlcv_15m)
                position_15m = (current_price - low_15m) / (high_15m - low_15m) if high_15m != low_15m else 0.5
                score_15m = 1.0 - abs(position_15m - 0.5) * 2
                scores.append(score_15m)
                weights.append(0.4)  # 主时间框架权重最高

            # 1小时框架
            if '1h' in multi_timeframe and len(multi_timeframe['1h']) >= 20:
                ohlcv_1h = multi_timeframe['1h'][-20:]
                high_1h = max(candle[2] for candle in ohlcv_1h)
                low_1h = min(candle[3] for candle in ohlcv_1h)
                position_1h = (current_price - low_1h) / (high_1h - low_1h) if high_1h != low_1h else 0.5
                score_1h = 1.0 - abs(position_1h - 0.5) * 2
                scores.append(score_1h)
                weights.append(0.35)

            # 4小时框架
            if '4h' in multi_timeframe and len(multi_timeframe['4h']) >= 15:
                ohlcv_4h = multi_timeframe['4h'][-15:]
                high_4h = max(candle[2] for candle in ohlcv_4h)
                low_4h = min(candle[3] for candle in ohlcv_4h)
                position_4h = (current_price - low_4h) / (high_4h - low_4h) if high_4h != low_4h else 0.5
                score_4h = 1.0 - abs(position_4h - 0.5) * 2
                scores.append(score_4h)
                weights.append(0.25)

            # 如果没有多时间框架数据，使用日线数据
            if not scores:
                daily_high = float(market_data['high'])
                daily_low = float(market_data['low'])
                daily_position = (current_price - daily_low) / (daily_high - daily_low) if daily_high != daily_low else 0.5
                daily_score = 1.0 - abs(daily_position - 0.5) * 2
                return daily_score

            # 加权平均
            total_weight = sum(weights)
            weighted_score = sum(score * weight for score, weight in zip(scores, weights)) / total_weight

            return weighted_score

        except Exception as e:
            logger.error(f"多时间框架分析失败: {e}")
            logger.warning("多时间框架分析异常，返回基础分数0.3")
            return 0.3  # 异常时给基础分数

    def _technical_indicators_analysis(self, market_data: Dict[str, Any], params: Dict[str, float]) -> float:
        """技术指标分析"""
        try:
            score = 0.0
            has_indicators = False

            # 1. ADX趋势强度分析
            if 'adx' in market_data:
                has_indicators = True
                adx = float(market_data['adx'])
                if adx < params['adx_threshold']:  # ADX小于阈值视为无趋势
                    score += 0.3
                    logger.debug(f"ADX评分: +0.3 (ADX={adx} < {params['adx_threshold']})")
                elif adx < params['adx_threshold'] + 5:
                    score += 0.15
                    logger.debug(f"ADX评分: +0.15 (ADX={adx} 接近阈值)")
            else:
                logger.debug("ADX指标缺失，跳过ADX评分")

            # 2. RSI中性区域分析
            if 'rsi' in market_data:
                has_indicators = True
                rsi = float(market_data['rsi'])
                if 40 <= rsi <= 60:  # RSI中性区域
                    score += 0.3
                    logger.debug(f"RSI评分: +0.3 (RSI={rsi} 在40-60区间)")
                elif 35 <= rsi <= 65:
                    score += 0.15
                    logger.debug(f"RSI评分: +0.15 (RSI={rsi} 在35-65区间)")
            else:
                logger.debug("RSI指标缺失，跳过RSI评分")

            # 3. MACD柱状图分析
            if 'macd_histogram' in market_data:
                has_indicators = True
                histogram = float(market_data['macd_histogram'])
                if abs(histogram) < 0.1:  # MACD柱状图接近0
                    score += 0.2
                    logger.debug(f"MACD评分: +0.2 (柱状图={histogram} 接近0)")
                elif abs(histogram) < 0.2:
                    score += 0.1
                    logger.debug(f"MACD评分: +0.1 (柱状图={histogram} 较小)")
            else:
                logger.debug("MACD柱状图缺失，跳过MACD评分")

            # 4. 价格与均线关系
            if 'sma_20' in market_data and 'sma_50' in market_data:
                has_indicators = True
                sma_20 = float(market_data['sma_20'])
                sma_50 = float(market_data['sma_50'])
                price = float(market_data['price'])

                # 价格在均线附近徘徊
                if abs(price - sma_20) / price < 0.01 and abs(sma_20 - sma_50) / sma_20 < 0.005:
                    score += 0.2
                    logger.debug(f"价格均线评分: +0.2 (价格接近SMA20)")
            else:
                logger.debug("SMA20或SMA50缺失，跳过均线评分")

            # 如果没有可用的技术指标，给出基础分数
            if not has_indicators:
                logger.warning("没有可用的技术指标，使用基础分数0.3")
                score = 0.3  # 基础横盘概率
            else:
                logger.debug(f"技术指标总分: {score:.2f}")

            # 限制最大分数为0.8（避免完美分数）
            return min(score, 0.8)

        except Exception as e:
            logger.error(f"技术指标分析失败: {e}")
            logger.warning("技术指标分析异常，返回基础分数0.2")
            return 0.2  # 异常时给基础分数

    def _volatility_analysis(self, market_data: Dict[str, Any], params: Dict[str, float]) -> float:
        """波动率分析"""
        try:
            score = 0.0
            has_volatility_data = False
            current_price = float(market_data['price'])

            # 1. ATR分析
            if 'atr' in market_data:
                has_volatility_data = True
                atr = float(market_data['atr'])
                atr_ratio = atr / current_price

                if atr_ratio < params['atr_threshold']:
                    score += 0.4
                    logger.debug(f"ATR评分: +0.4 (ATR比率={atr_ratio:.4f} < {params['atr_threshold']})")
                elif atr_ratio < params['atr_threshold'] * 1.5:
                    score += 0.2
                    logger.debug(f"ATR评分: +0.2 (ATR比率={atr_ratio:.4f} 接近阈值)")
            else:
                logger.debug("ATR数据缺失，跳过ATR评分")

            # 2. 布林带宽度分析
            if 'bb_upper' in market_data and 'bb_lower' in market_data:
                has_volatility_data = True
                bb_upper = float(market_data['bb_upper'])
                bb_lower = float(market_data['bb_lower'])
                bb_width = (bb_upper - bb_lower) / current_price

                if bb_width < params['bb_width_threshold']:
                    score += 0.4
                    logger.debug(f"布林带评分: +0.4 (带宽={bb_width:.4f} < {params['bb_width_threshold']})")
                elif bb_width < params['bb_width_threshold'] * 1.5:
                    score += 0.2
                    logger.debug(f"布林带评分: +0.2 (带宽={bb_width:.4f} 接近阈值)")
            else:
                logger.debug("布林带数据缺失，跳过布林带评分")

            # 3. 历史波动率比较
            if 'volatility_30d' in market_data:
                has_volatility_data = True
                current_vol = float(market_data['volatility_30d'])
                if current_vol < 0.3:  # 低于30%视为低波动
                    score += 0.2
                    logger.debug(f"历史波动率评分: +0.2 (波动率={current_vol:.2f} < 0.3)")
            else:
                logger.debug("历史波动率数据缺失，跳过波动率评分")

            # 如果没有波动率数据，给出基础分数
            if not has_volatility_data:
                logger.warning("没有可用的波动率数据，使用基础分数0.3")
                score = 0.3  # 基础横盘概率
            else:
                logger.debug(f"波动率分析总分: {score:.2f}")

            return min(score, 0.8)

        except Exception as e:
            logger.error(f"波动率分析失败: {e}")
            logger.warning("波动率分析异常，返回基础分数0.2")
            return 0.2  # 异常时给基础分数

    def _volume_analysis(self, market_data: Dict[str, Any]) -> float:
        """成交量分析"""
        try:
            score = 0.0
            has_volume_data = False

            if 'volume' in market_data and 'avg_volume_24h' in market_data:
                has_volume_data = True
                current_volume = float(market_data['volume'])
                avg_volume = float(market_data['avg_volume_24h'])

                # 成交量萎缩通常伴随横盘
                volume_ratio = current_volume / avg_volume if avg_volume > 0 else 1.0

                if 0.5 <= volume_ratio <= 1.5:  # 正常成交量
                    score += 0.3
                    logger.debug(f"成交量评分: +0.3 (成交量比={volume_ratio:.2f} 正常)")
                elif volume_ratio < 0.5:  # 成交量萎缩
                    score += 0.4
                    logger.debug(f"成交量评分: +0.4 (成交量比={volume_ratio:.2f} 萎缩)")
                elif volume_ratio > 2.0:  # 异常放量但价格不动
                    score += 0.1  # 可能是变盘前兆，降低横盘评分
                    logger.debug(f"成交量评分: +0.1 (成交量比={volume_ratio:.2f} 异常放量)")
            else:
                logger.debug("成交量数据缺失，跳过成交量评分")

            # 如果没有成交量数据，给出基础分数
            if not has_volume_data:
                logger.warning("没有可用的成交量数据，使用基础分数0.3")
                score = 0.3  # 基础横盘概率
            else:
                logger.debug(f"成交量分析总分: {score:.2f}")

            return score

        except Exception as e:
            logger.error(f"成交量分析失败: {e}")
            logger.warning("成交量分析异常，返回基础分数0.2")
            return 0.2  # 异常时给基础分数

    def _generate_reason(self, final_score: float, consolidation_score: float,
                        technical_score: float, volatility_score: float) -> str:
        """生成横盘原因说明"""
        reasons = []

        if consolidation_score > 0.6:
            reasons.append("价格处于多时间框架的中间区域")

        if technical_score > 0.5:
            reasons.append("技术指标显示无明确趋势")

        if volatility_score > 0.5:
            reasons.append("市场波动率较低")

        if final_score > 0.8:
            reason_level = "高度确认"
        elif final_score > 0.6:
            reason_level = "中度确认"
        else:
            reason_level = "轻度确认"

        if reasons:
            return f"{reason_level}横盘: {'; '.join(reasons)}"
        else:
            return f"横盘评分: {final_score:.2f}"

    def get_consolidation_strength(self, market_data: Dict[str, Any]) -> float:
        """获取横盘强度（0-1）"""
        is_consolidation, _, confidence = self.detect_consolidation(market_data)
        return confidence if is_consolidation else 0.0

    def predict_breakout_direction(self, market_data: Dict[str, Any]) -> str:
        """预测横盘突破方向"""
        try:
            # 基于订单簿、资金流向等预测突破方向
            # 这是一个简化的实现，实际可以更复杂

            if 'order_book_imbalance' in market_data:
                imbalance = float(market_data['order_book_imbalance'])
                if imbalance > 0.1:
                    return "UP"
                elif imbalance < -0.1:
                    return "DOWN"

            # 默认基于价格位置判断
            current_price = float(market_data['price'])
            high = float(market_data['high'])
            low = float(market_data['low'])
            position = (current_price - low) / (high - low)

            if position > 0.6:
                return "UP"
            elif position < 0.4:
                return "DOWN"
            else:
                return "UNCERTAIN"

        except Exception:
            return "UNCERTAIN"