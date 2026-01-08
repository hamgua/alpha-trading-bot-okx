"""
AI信号融合模块 - 融合多个AI提供商的信号
"""

import asyncio
import logging
import numpy as np
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger(__name__)

class AIFusion:
    """AI信号融合器"""

    def __init__(self):
        self.fusion_weights = {
            'confidence': 0.4,      # 置信度权重
            'provider_reliability': 0.3,  # 提供商可靠性权重
            'signal_consensus': 0.2,      # 信号一致性权重
            'time_decay': 0.1       # 时间衰减权重
        }
        self.provider_scores = {
            'kimi': 0.85,
            'deepseek': 0.80,
            'qwen': 0.82,
            'openai': 0.78,
            'fallback': 0.60
        }

    async def fuse_signals(self, signals: List[Dict[str, Any]],
                          strategy: str = 'weighted',
                          threshold: float = 0.6,
                          weights: Optional[Dict[str, float]] = None,
                          fusion_providers: Optional[List[str]] = None,
                          market_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """融合多个AI信号"""
        try:
            if not signals:
                return None

            if len(signals) == 1:
                # 只有一个信号，直接返回
                return signals[0]

            logger.info(f"融合 {len(signals)} 个AI信号，策略: {strategy}")

            # 应用提供商偏差纠正（增强版）
            if market_context:
                signals = self._apply_provider_bias_correction(signals, market_context)

            # 根据策略选择融合方法
            if strategy == 'consensus':
                return await self._fuse_by_consensus(signals, threshold, market_context)
            elif strategy == 'majority':
                return await self._fuse_by_majority(signals, threshold, market_context)
            elif strategy == 'confidence':
                return await self._fuse_by_confidence(signals, market_context)
            else:  # weighted
                return await self._fuse_by_weighted(signals, weights, fusion_providers, market_context)

        except Exception as e:
            logger.error(f"融合AI信号失败: {e}")
            return None

    def _calculate_consensus(self, signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """计算信号一致性"""
        try:
            # 统计信号分布
            signal_counts = {'BUY': 0, 'SELL': 0, 'HOLD': 0}
            total_confidence = 0.0

            for signal in signals:
                sig = signal.get('signal', 'HOLD')
                confidence = signal.get('confidence', 0.5)

                if sig in signal_counts:
                    signal_counts[sig] += 1
                    total_confidence += confidence

            total_signals = len(signals)
            dominant_signal = max(signal_counts, key=signal_counts.get)
            dominant_count = signal_counts[dominant_signal]
            consensus_score = dominant_count / total_signals

            # 计算平均置信度
            avg_confidence = total_confidence / total_signals if total_signals > 0 else 0.5

            return {
                'dominant_signal': dominant_signal,
                'dominant_count': dominant_count,
                'consensus_score': consensus_score,
                'signal_distribution': signal_counts,
                'average_confidence': avg_confidence
            }

        except Exception as e:
            logger.error(f"计算信号一致性失败: {e}")
            return {
                'dominant_signal': 'HOLD',
                'dominant_count': 0,
                'consensus_score': 0.0,
                'signal_distribution': {'BUY': 0, 'SELL': 0, 'HOLD': 0},
                'average_confidence': 0.5
            }

    def _calculate_fused_scores(self, signals: List[Dict[str, Any]], consensus: Dict[str, Any]) -> Dict[str, float]:
        """计算融合分数"""
        try:
            fused_scores = {'BUY': 0.0, 'SELL': 0.0, 'HOLD': 0.0}

            for signal in signals:
                sig = signal.get('signal', 'HOLD')
                confidence = signal.get('confidence', 0.5)
                provider = signal.get('provider', 'unknown')

                # 提供商可靠性分数
                provider_score = self.provider_scores.get(provider, 0.5)

                # 时间衰减分数（假设信号按时间顺序提供）
                time_decay = 1.0  # 简化实现

                # 计算加权分数
                weighted_score = (
                    confidence * self.fusion_weights['confidence'] +
                    provider_score * self.fusion_weights['provider_reliability'] +
                    consensus['consensus_score'] * self.fusion_weights['signal_consensus'] +
                    time_decay * self.fusion_weights['time_decay']
                )

                fused_scores[sig] += weighted_score

            return fused_scores

        except Exception as e:
            logger.error(f"计算融合分数失败: {e}")
            return {'BUY': 0.0, 'SELL': 0.0, 'HOLD': 0.0}

    def _determine_final_signal(self, fused_scores: Dict[str, float], signals: List[Dict[str, Any]]) -> str:
        """确定最终信号"""
        try:
            # 获取最高分数的信号
            max_score = max(fused_scores.values())
            candidate_signals = [sig for sig, score in fused_scores.items() if score == max_score]

            if len(candidate_signals) == 1:
                return candidate_signals[0]
            else:
                # 如果有多个信号分数相同，选择置信度最高的
                best_signal = 'HOLD'
                best_confidence = 0.0

                for signal in signals:
                    sig = signal.get('signal', 'HOLD')
                    confidence = signal.get('confidence', 0.5)

                    if sig in candidate_signals and confidence > best_confidence:
                        best_signal = sig
                        best_confidence = confidence

                return best_signal

        except Exception as e:
            logger.error(f"确定最终信号失败: {e}")
            return 'HOLD'

    def _calculate_fused_confidence(self, signals: List[Dict[str, Any]], consensus: Dict[str, Any]) -> float:
        """计算融合置信度"""
        try:
            # 基础置信度（平均置信度）
            avg_confidence = consensus['average_confidence']

            # 一致性奖励
            consensus_bonus = consensus['consensus_score'] * 0.2

            # 提供商可靠性加权
            total_reliability = 0.0
            total_signals = len(signals)

            for signal in signals:
                provider = signal.get('provider', 'unknown')
                confidence = signal.get('confidence', 0.5)
                reliability = self.provider_scores.get(provider, 0.5)

                total_reliability += reliability * confidence

            avg_reliability = total_reliability / total_signals if total_signals > 0 else 0.5
            reliability_bonus = (avg_reliability - 0.5) * 0.1

            # 计算最终置信度
            final_confidence = avg_confidence + consensus_bonus + reliability_bonus

            # 确保置信度在合理范围内
            return max(0.0, min(1.0, final_confidence))

        except Exception as e:
            logger.error(f"计算融合置信度失败: {e}")
            return 0.5

    def _build_fusion_reason(self, signals: List[Dict[str, Any]], consensus: Dict[str, Any], final_signal: str) -> str:
        """构建融合理由"""
        try:
            # 获取信号分布
            distribution = consensus['signal_distribution']
            total = sum(distribution.values())

            # 构建理由
            reasons = []

            # 添加一致性信息
            if consensus['consensus_score'] > 0.7:
                reasons.append(f"高度一致 ({consensus['consensus_score']:.0%})")
            elif consensus['consensus_score'] > 0.5:
                reasons.append(f"基本一致 ({consensus['consensus_score']:.0%})")
            else:
                reasons.append(f"分歧较大 ({consensus['consensus_score']:.0%})")

            # 添加信号分布
            signal_parts = []
            for sig, count in distribution.items():
                if count > 0:
                    percentage = count / total * 100
                    signal_parts.append(f"{sig}: {count} ({percentage:.0f}%)")

            if signal_parts:
                reasons.append("分布: " + ", ".join(signal_parts))

            # 添加平均置信度
            reasons.append(f"平均置信度: {consensus['average_confidence']:.0%}")

            # 添加提供商信息
            providers = [s.get('provider', 'unknown') for s in signals]
            if providers:
                reasons.append(f"提供商: {', '.join(set(providers))}")

            return "; ".join(reasons)

        except Exception as e:
            logger.error(f"构建融合理由失败: {e}")
            return f"AI融合分析 ({len(signals)} 个信号)"

    def update_provider_score(self, provider: str, score: float) -> None:
        """更新提供商评分"""
        if provider in self.provider_scores:
            # 平滑更新评分
            old_score = self.provider_scores[provider]
            new_score = old_score * 0.9 + score * 0.1
            self.provider_scores[provider] = new_score
            logger.info(f"更新 {provider} 评分: {old_score:.2f} -> {new_score:.2f}")

    def get_provider_scores(self) -> Dict[str, float]:
        """获取提供商评分"""
        return self.provider_scores.copy()

    def _apply_trend_filtering(self, fused_scores: Dict[str, float], signals: List[Dict[str, Any]],
                              market_context: Dict[str, Any]) -> Dict[str, float]:
        """应用趋势过滤 - 关键修复"""
        try:
            # 获取市场趋势信息
            trend_direction = market_context.get('trend_direction', 'neutral')
            trend_strength = market_context.get('trend_strength', 'normal')

            # 只在强势趋势中应用过滤
            if trend_strength in ['strong', 'extreme']:
                # 强势下跌趋势中，抑制买入信号
                if trend_direction == 'down' and fused_scores.get('BUY', 0) > 0:
                    # 将买入信号降级为HOLD
                    buy_score = fused_scores['BUY']
                    fused_scores['HOLD'] = fused_scores.get('HOLD', 0) + buy_score * 0.7  # 70%转为HOLD
                    fused_scores['BUY'] = buy_score * 0.3  # 保留30%的买入倾向
                    logger.warning(f"趋势过滤：强势下跌趋势中抑制买入信号 (BUY: {buy_score:.2f} -> {fused_scores['BUY']:.2f})")

                # 强势上涨趋势中，抑制卖出信号
                elif trend_direction == 'up' and fused_scores.get('SELL', 0) > 0:
                    sell_score = fused_scores['SELL']
                    fused_scores['HOLD'] = fused_scores.get('HOLD', 0) + sell_score * 0.7
                    fused_scores['SELL'] = sell_score * 0.3
                    logger.warning(f"趋势过滤：强势上涨趋势中抑制卖出信号 (SELL: {sell_score:.2f} -> {fused_scores['SELL']:.2f})")

            return fused_scores

        except Exception as e:
            logger.error(f"趋势过滤失败: {e}")
            return fused_scores

    def _apply_provider_bias_correction(self, signals: List[Dict[str, Any]],
                                       market_context: Dict[str, Any]) -> List[Dict[str, Any]]:
        """应用提供商偏差纠正 - 增强版"""
        try:
            trend_direction = market_context.get('trend_direction', 'neutral')
            trend_strength = market_context.get('trend_strength', 'normal')

            corrected_signals = []

            for signal in signals:
                provider = signal.get('provider', 'unknown')
                confidence = signal.get('confidence', 0.5)
                signal_type = signal.get('signal', 'HOLD')

                # QWEN特定的偏差纠正
                if provider == 'qwen':
                    # QWEN在下跌趋势中容易给出过度乐观的买入信号
                    if (trend_direction == 'down' and trend_strength in ['strong', 'extreme'] and
                        signal_type == 'BUY' and confidence > 0.8):
                        # 降低置信度
                        new_confidence = confidence * 0.6
                        signal['confidence'] = new_confidence
                        signal['original_confidence'] = confidence
                        signal['bias_correction'] = 'QWEN下跌趋势买入抑制'
                        logger.warning(f"QWEN偏差纠正：下跌趋势中买入信号置信度 {confidence:.2f} -> {new_confidence:.2f}")

                    # QWEN在上涨趋势中可能过度乐观
                    elif (trend_direction == 'up' and trend_strength in ['strong', 'extreme'] and
                          signal_type == 'SELL' and confidence > 0.8):
                        new_confidence = confidence * 0.7
                        signal['confidence'] = new_confidence
                        signal['original_confidence'] = confidence
                        signal['bias_correction'] = 'QWEN上涨趋势卖出抑制'
                        logger.warning(f"QWEN偏差纠正：上涨趋势中卖出信号置信度 {confidence:.2f} -> {new_confidence:.2f}")

                # DeepSeek特定的处理（通常更保守）
                elif provider == 'deepseek':
                    # DeepSeek在趋势明确时可能过于保守
                    if (trend_strength in ['strong', 'extreme'] and
                        signal_type == 'HOLD' and confidence > 0.7):
                        # 稍微降低HOLD的置信度，让其他信号有更多机会
                        signal['confidence'] = confidence * 0.9
                        signal['original_confidence'] = confidence
                        signal['bias_correction'] = 'DeepSeek趋势期HOLD调整'

                corrected_signals.append(signal)

            # 应用最大置信度限制，防止过度自信
            for signal in corrected_signals:
                if signal.get('confidence', 0) > 0.85:
                    original_conf = signal['confidence']
                    signal['confidence'] = 0.85
                    signal['original_confidence'] = original_conf
                    signal['confidence_capped'] = '超过最大置信度限制'
                    logger.debug(f"置信度限制：{original_conf:.2f} -> 0.85")

            return corrected_signals

        except Exception as e:
            logger.error(f"提供商偏差纠正失败: {e}")
            return signals

    async def _fuse_by_consensus(self, signals: List[Dict[str, Any]], threshold: float) -> Optional[Dict[str, Any]]:
        """共识策略：所有模型达成一致才行动"""
        try:
            consensus = self._calculate_consensus(signals)

            # 如果共识度达到阈值，返回主导信号
            if consensus['consensus_score'] >= threshold:
                dominant_signal = consensus['dominant_signal']

                # 找到该信号的平均置信度
                signal_confidences = [
                    s.get('confidence', 0.5) for s in signals
                    if s.get('signal', 'HOLD') == dominant_signal
                ]
                avg_confidence = sum(signal_confidences) / len(signal_confidences) if signal_confidences else 0.5

                return {
                    'signal': dominant_signal,
                    'confidence': avg_confidence,
                    'reason': f"共识策略：{consensus['consensus_score']:.0%}模型支持{dominant_signal}",
                    'timestamp': datetime.now().isoformat(),
                    'provider': 'fusion',
                    'fused_signals': len(signals),
                    'consensus_score': consensus['consensus_score'],
                    'individual_signals': signals
                }
            else:
                # 未达成共识，返回HOLD
                return {
                    'signal': 'HOLD',
                    'confidence': 0.5,
                    'reason': f"未达成共识（{consensus['consensus_score']:.0%} < {threshold:.0%}）",
                    'timestamp': datetime.now().isoformat(),
                    'provider': 'fusion',
                    'fused_signals': len(signals),
                    'consensus_score': consensus['consensus_score'],
                    'individual_signals': signals
                }

        except Exception as e:
            logger.error(f"共识融合失败: {e}")
            return None

    async def _fuse_by_majority(self, signals: List[Dict[str, Any]], threshold: float) -> Optional[Dict[str, Any]]:
        """多数表决策略"""
        try:
            consensus = self._calculate_consensus(signals)
            total_signals = len(signals)

            # 检查是否有信号获得多数支持
            for signal_type, count in consensus['signal_distribution'].items():
                if count / total_signals >= threshold:
                    # 找到该信号的平均置信度
                    signal_confidences = [
                        s.get('confidence', 0.5) for s in signals
                        if s.get('signal', 'HOLD') == signal_type
                    ]
                    avg_confidence = sum(signal_confidences) / len(signal_confidences) if signal_confidences else 0.5

                    return {
                        'signal': signal_type,
                        'confidence': avg_confidence,
                        'reason': f"多数表决：{count}/{total_signals}模型支持{signal_type}",
                        'timestamp': datetime.now().isoformat(),
                        'provider': 'fusion',
                        'fused_signals': len(signals),
                        'consensus_score': count / total_signals,
                        'individual_signals': signals
                    }

            # 没有任何信号达到阈值，返回HOLD
            return {
                'signal': 'HOLD',
                'confidence': 0.5,
                'reason': "未形成多数意见",
                'timestamp': datetime.now().isoformat(),
                'provider': 'fusion',
                'fused_signals': len(signals),
                'consensus_score': consensus['consensus_score'],
                'individual_signals': signals
            }

        except Exception as e:
            logger.error(f"多数表决融合失败: {e}")
            return None

    async def _fuse_by_confidence(self, signals: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """置信度优先策略"""
        try:
            # 选择置信度最高的信号
            best_signal = max(signals, key=lambda x: x.get('confidence', 0))

            return {
                'signal': best_signal.get('signal', 'HOLD'),
                'confidence': best_signal.get('confidence', 0.5),
                'reason': f"置信度优先：{best_signal.get('provider', 'unknown')}提供最高置信度信号",
                'timestamp': datetime.now().isoformat(),
                'provider': 'fusion',
                'fused_signals': len(signals),
                'best_provider': best_signal.get('provider', 'unknown'),
                'individual_signals': signals
            }

        except Exception as e:
            logger.error(f"置信度优先融合失败: {e}")
            return None

    async def _fuse_by_weighted(self, signals: List[Dict[str, Any]],
                               weights: Optional[Dict[str, float]] = None,
                               fusion_providers: Optional[List[str]] = None,
                               market_context: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """加权平均策略 - 添加趋势过滤"""
        try:
            # 使用提供的权重或默认权重
            if weights:
                self.set_fusion_weights(weights)

            # 1. 分析信号一致性
            consensus = self._calculate_consensus(signals)

            # 2. 计算融合分数
            fused_scores = self._calculate_fused_scores(signals, consensus)

            # 3. 应用趋势过滤（关键修复）
            if market_context:
                fused_scores = self._apply_trend_filtering(fused_scores, signals, market_context)

            # 4. 确定最终信号
            final_signal = self._determine_final_signal(fused_scores, signals)

            # 5. 计算融合置信度
            final_confidence = self._calculate_fused_confidence(signals, consensus)

            # 6. 构建结果，包含趋势信息
            result = {
                'signal': final_signal,
                'confidence': final_confidence,
                'reason': self._build_fusion_reason(signals, consensus, final_signal),
                'timestamp': datetime.now().isoformat(),
                'provider': 'fusion',
                'fused_signals': len(signals),
                'consensus_score': consensus['consensus_score'],
                'individual_signals': signals
            }

            # 添加趋势过滤信息到原因中
            if market_context and final_signal != consensus['dominant_signal']:
                trend_info = market_context.get('trend_direction', 'unknown')
                trend_strength = market_context.get('trend_strength', 'normal')
                result['reason'] += f"; 趋势过滤({trend_info}:{trend_strength})已应用"

            logger.info(f"加权融合完成: {final_signal} (置信度: {final_confidence:.2f})")
            return result

        except Exception as e:
            logger.error(f"加权融合失败: {e}")
            return None

    def set_fusion_weights(self, weights: Dict[str, float]) -> None:
        """设置融合权重"""
        # 验证权重和为1
        total_weight = sum(weights.values())
        if abs(total_weight - 1.0) > 0.01:
            logger.warning(f"融合权重和不等于1: {total_weight}")

        self.fusion_weights.update(weights)
        logger.info(f"更新融合权重: {weights}")

# 创建AI融合器的工厂函数
def create_ai_fusion() -> AIFusion:
    """创建AI融合器实例"""
    return AIFusion()