"""ML优化任务模块

从 AdaptiveTradingBot 中提取的后台 ML 学习循环
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


class MLOptimizationTask:
    """ML优化任务管理器"""

    def __init__(
        self,
        bot_ref: Any,
        performance_tracker: Any,
        backtest_learner: Any,
        simple_learning: Any,
        weight_optimizer: Any,
    ):
        self._bot_ref = bot_ref
        self._performance_tracker = performance_tracker
        self._backtest_learner = backtest_learner
        self._simple_learning = simple_learning
        self._weight_optimizer = weight_optimizer

    async def run(self) -> None:
        """后台优化任务（每6小时运行一次ML学习）"""
        while self._bot_ref._running:
            try:
                await asyncio.sleep(3600)

                now_utc = datetime.now(timezone.utc)
                should_run = now_utc.hour in [0, 6, 12, 18] and now_utc.minute <= 5

                if not should_run:
                    continue

                logger.info("[ML学习] 开始后台优化任务...")

                metrics = self._performance_tracker.get_performance_metrics()
                daily_data = {
                    "trade_count": metrics.total_trades,
                    "win_rate": metrics.win_rate,
                    "total_pnl": metrics.total_pnl,
                }
                logger.info(
                    f"[ML学习] 当日数据: 交易次数={daily_data.get('trade_count', 0)}, "
                    f"胜率={daily_data.get('win_rate', 0):.2%}"
                )

                try:
                    backtest_result = self._backtest_learner.backtest_signals(
                        days=60, holding_hours=4, min_confidence=0.5
                    )

                    if backtest_result.total_signals > 0:
                        logger.info(
                            f"[ML学习] 回测结果: 信号数={backtest_result.total_signals}, "
                            f"胜率={backtest_result.win_rate:.2%}, "
                            f"平均收益={backtest_result.average_return:.2f}%"
                        )

                        for provider, stats in backtest_result.provider_stats.items():
                            logger.info(
                                f"[ML学习] {provider}: 胜率={stats.get('win_rate', 0):.2%}, "
                                f"平均收益={stats.get('average_return', 0):.2f}%"
                            )

                        backtest_weights = self._backtest_learner.learn_from_backtest()

                        if metrics.total_trades > 0:
                            trade_weights = self._simple_learning.learn_from_trades()
                            logger.info(f"[ML学习] 真实交易权重: {trade_weights}")

                        self._simple_learning.data_manager.save_model_weights(
                            backtest_weights, source="backtest_learn"
                        )

                        logger.info(f"[ML学习] 回测学习权重已保存: {backtest_weights}")
                    else:
                        logger.warning("[ML学习] 回测无结果，跳过回测学习")

                except Exception as e:
                    logger.warning(f"[ML学习] 回测学习失败: {e}")

                optimized_weights, confidence = (
                    self._weight_optimizer.get_optimized_weights()
                )
                logger.info(
                    f"[ML学习] 优化权重: {optimized_weights}, 置信度={confidence:.2f}"
                )

                if optimized_weights and confidence > 0.5:
                    try:
                        old_weights = getattr(
                            self._bot_ref.config.ai, "fusion_weights", {}
                        )
                        self._bot_ref.config.ai.fusion_weights = optimized_weights
                        logger.info(
                            f"[ML学习] 权重已应用: {old_weights} -> {optimized_weights}"
                        )
                    except Exception as e:
                        logger.warning(f"[ML学习] 应用权重失败: {e}")
                else:
                    logger.info(f"[ML学习] 跳过应用: 置信度={confidence:.2f} <= 0.5")

                logger.info("[ML学习] 后台优化任务完成")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[ML学习] 任务出错: {e}")
