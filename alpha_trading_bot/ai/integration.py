"""
AI Integration Module - 集成所有 ML 模块到现有系统
"""

import asyncio
import logging
from typing import Dict, Any, Optional, List
from datetime import datetime

from .ml.prompt_optimizer import (
    OptimizedPromptBuilder,
    MarketContext,
    MarketRegime,
    build_optimized_prompt,
)
from .ml.trend_detector import EnhancedTrendDetector, TrendState, detect_market_trend
from .ml.adaptive_fusion import AdaptiveFusionStrategy, FusionConfig
from .ml.weight_optimizer import WeightOptimizer
from .ml.performance_tracker import PerformanceTracker
from .ml.monitoring_dashboard import MonitoringDashboard, AlertManager

logger = logging.getLogger(__name__)


class AIIntegrationManager:
    """AI 集成管理器 - 整合所有 ML 模块"""

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

        # 初始化核心组件
        self.prompt_builder = OptimizedPromptBuilder()
        self.trend_detector = EnhancedTrendDetector(
            sma_short=self.config.get("sma_short", 5),
            sma_long=self.config.get("sma_long", 20),
        )
        self.fusion_strategy = AdaptiveFusionStrategy(
            FusionConfig(mode=self.config.get("fusion_mode", "moderate"))
        )

        # 初始化优化组件
        self.weight_optimizer = WeightOptimizer()
        self.performance_tracker = PerformanceTracker()
        self.monitoring = MonitoringDashboard()
        self.alert_manager = AlertManager()

        # 状态追踪
        self.current_regime: Optional[MarketRegime] = None
        self.current_trend: Optional[TrendState] = None
        self.last_signal_time: Optional[datetime] = None

        # 加载已优化的权重
        self.weight_optimizer.load_weights()

    def update_price(self, price: float):
        """更新价格数据"""
        self.trend_detector.add_price(price)
        self.current_trend = self.trend_detector.detect_trend()

    def analyze_market(self, market_data: Dict[str, Any]) -> MarketContext:
        """分析市场状态"""
        if "price" in market_data:
            self.update_price(market_data["price"])

        if self.current_trend:
            context = MarketContext(
                regime=self._trend_to_regime(self.current_trend),
                momentum_percent=self.current_trend.momentum,
                trend_strength=self.current_trend.strength,
                confidence=self.current_trend.confidence,
            )
            self.current_regime = context.regime
            return context

        # 如果没有价格数据，使用默认分析
        return self._analyze_from_data(market_data)

    def _trend_to_regime(self, trend: TrendState) -> MarketRegime:
        """将趋势状态转换为市场状态"""
        if trend.direction.value == "up":
            return (
                MarketRegime.STRONG_UPTREND
                if trend.strength > 0.6
                else MarketRegime.WEAK_UPTREND
            )
        elif trend.direction.value == "down":
            return (
                MarketRegime.STRONG_DOWNTREND
                if trend.strength > 0.6
                else MarketRegime.WEAK_DOWNTREND
            )
        return MarketRegime.SIDEWAYS

    def _analyze_from_data(self, market_data: Dict[str, Any]) -> MarketContext:
        """从市场数据中分析"""
        technical = market_data.get("technical", {})
        trend_dir = technical.get("trend_direction", "neutral")
        trend_strength = technical.get("trend_strength", 0.5)

        if trend_dir == "up":
            if trend_strength > 0.6:
                regime = MarketRegime.STRONG_UPTREND
            else:
                regime = MarketRegime.WEAK_UPTREND
        elif trend_dir == "down":
            if trend_strength > 0.6:
                regime = MarketRegime.STRONG_DOWNTREND
            else:
                regime = MarketRegime.WEAK_DOWNTREND
        else:
            regime = MarketRegime.SIDEWAYS

        return MarketContext(regime=regime)

    def build_prompt(self, market_data: Dict[str, Any]) -> str:
        """构建优化后的 Prompt"""
        context = self.analyze_market(market_data)
        return self.prompt_builder.build(market_data, context)

    def fuse_signals(
        self, signals: List[Dict[str, Any]], market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """融合 AI 信号"""
        context = self.analyze_market(market_data)
        momentum = context.momentum_percent if context else 0.0

        # 获取趋势上下文
        trend_context = {}
        if self.current_trend:
            trend_context = {
                "trend_direction": self.current_trend.direction.value,
                "trend_strength": self.current_trend.strength,
                "momentum": self.current_trend.momentum,
            }

        result = self.fusion_strategy.fuse(signals, trend_context, momentum)

        # 记录到监控系统
        self.monitoring.record_metric("signal_confidence", result.get("confidence", 0))
        self.monitoring.record_metric("fusion_threshold", result.get("threshold", 0.5))

        return result

    def record_signal_outcome(
        self,
        provider: str,
        signal: str,
        confidence: int,
        market_data: Dict[str, Any],
        outcome: str,
        price_return: float,
    ):
        """记录信号结果用于优化"""
        context = self.analyze_market(market_data)

        # 记录到性能追踪
        self.performance_tracker.record_signal(
            provider=provider,
            signal=signal,
            confidence=confidence,
            regime=context.regime.value,
            price=market_data.get("price", 0),
        )

        # 更新结果
        self.performance_tracker.update_outcome(
            provider=provider,
            timestamp=datetime.now().isoformat(),
            outcome=outcome,
            price=market_data.get("price", 0),
        )

        # 记录权重优化器
        self.weight_optimizer.record_signal_outcome(
            regime=context.regime.value,
            provider=provider,
            signal=signal,
            confidence=confidence,
            market_outcome=outcome,
            price_return=price_return,
        )

    def optimize_weights(self) -> Dict[str, Dict[str, float]]:
        """优化 AI 权重"""
        return self.weight_optimizer.optimize_weights()

    def get_monitoring_summary(self) -> Dict:
        """获取监控摘要"""
        return self.monitoring.get_dashboard_summary()

    def check_alerts(
        self, win_rate: float, loss_streak: int, api_failure: float
    ) -> List[str]:
        """检查告警"""
        return self.alert_manager.check_alerts(win_rate, loss_streak, api_failure)

    def get_status_report(self) -> Dict:
        """获取完整状态报告"""
        trend_info = {}
        if self.current_trend:
            trend_info = {
                "direction": self.current_trend.direction.value,
                "strength": self.current_trend.strength,
                "momentum": self.current_trend.momentum,
                "confidence": self.current_trend.confidence,
            }

        return {
            "timestamp": datetime.now().isoformat(),
            "regime": self.current_regime.value if self.current_regime else "unknown",
            "trend": trend_info,
            "weights": self.weight_optimizer.current_weights,
            "monitoring": self.get_monitoring_summary(),
        }


class EnhancedAIClient:
    """增强版 AI 客户端 - 集成 ML 模块"""

    def __init__(self, config: Optional[Dict] = None):
        self.manager = AIIntegrationManager(config)

        # 原有客户端兼容
        from .client import AIClient as OriginalClient

        self.original_client = OriginalClient()

    async def get_signal(
        self, market_data: Dict[str, Any], use_optimized: bool = True
    ) -> Dict[str, Any]:
        """获取交易信号"""

        # 步骤1: 分析市场状态
        market_context = self.manager.analyze_market(market_data)
        logger.info(f"[AI集成] 市场状态: {market_context.regime.value}")

        # 步骤2: 构建 Prompt
        if use_optimized:
            prompt = self.manager.build_prompt(market_data)
            logger.info("[AI集成] 使用优化版 Prompt")
        else:
            from .prompt_builder import build_prompt

            prompt = build_prompt(market_data)
            logger.info("[AI集成] 使用原版 Prompt")

        # 步骤3: 调用 AI 获取信号
        # 这里调用原有的 AI client
        signal_info = await self._call_ai_with_prompt(prompt, market_data)

        # 步骤4: 融合信号 (如果有多个 AI)
        if isinstance(signal_info, list):
            fused = self.manager.fuse_signals(signal_info, market_data)
            return {
                "signal": fused.get("signal", "hold"),
                "confidence": fused.get("confidence", 50),
                "regime": market_context.regime.value,
                "threshold": fused.get("threshold", 0.5),
                "scores": fused.get("scores", {}),
                "optimized": use_optimized,
            }

        return {
            "signal": signal_info.get("signal", "hold"),
            "confidence": signal_info.get("confidence", 50),
            "regime": market_context.regime.value,
            "optimized": use_optimized,
        }

    async def _call_ai_with_prompt(
        self, prompt: str, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用 AI API"""
        # 这里集成原有的 AI 调用逻辑
        try:
            from .providers import get_provider_config
            from .response_parser import parse_response
            import aiohttp

            provider = "deepseek"  # 默认提供商
            config = get_provider_config(provider)

            data = {
                "model": config["model"],
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 100,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    config["base_url"],
                    headers={"Authorization": f"Bearer {config.get('api_key', '')}"},
                    json=data,
                    timeout=60,
                ) as response:
                    result = await response.json()
                    content = result["choices"][0]["message"]["content"]
                    signal, confidence = parse_response(content)

                    return {
                        "signal": signal,
                        "confidence": confidence,
                        "provider": provider,
                    }

        except Exception as e:
            logger.error(f"AI调用失败: {e}")
            return {"signal": "hold", "confidence": 50, "provider": "error"}

    def get_integration_status(self) -> Dict:
        """获取集成状态"""
        return self.manager.get_status_report()


# 便捷函数
def create_enhanced_client(config: Optional[Dict] = None) -> EnhancedAIClient:
    """创建增强版 AI 客户端"""
    return EnhancedAIClient(config)


async def get_optimized_signal(
    market_data: Dict[str, Any], config: Optional[Dict] = None
) -> Dict[str, Any]:
    """便捷函数：获取优化后的信号"""
    client = EnhancedAIClient(config)
    return await client.get_signal(market_data, use_optimized=True)
