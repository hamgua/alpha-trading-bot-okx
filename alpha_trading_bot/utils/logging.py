"""
日志工具模块
"""

import logging
import sys
from typing import Optional
from datetime import datetime

def setup_logging(
    level: str = 'INFO',
    log_file: Optional[str] = None,
    format_string: Optional[str] = None
) -> None:
    """
    设置日志配置

    Args:
        level: 日志级别 (DEBUG, INFO, WARNING, ERROR)
        log_file: 日志文件路径，为None时不写文件
        format_string: 日志格式字符串
    """
    # 默认格式 - 匹配参考日志格式
    if format_string is None:
        format_string = '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s'

    # 创建logger
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper()))

    # 清除现有handler
    logger.handlers.clear()

    # 控制台handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(getattr(logging, level.upper()))
    console_formatter = logging.Formatter(format_string)
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 文件handler
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(getattr(logging, level.upper()))
        file_formatter = logging.Formatter(format_string)
        file_handler.setFormatter(file_formatter)
        logger.addHandler(file_handler)

def get_logger(name: str) -> logging.Logger:
    """
    获取logger实例

    Args:
        name: logger名称

    Returns:
        logging.Logger: logger实例
    """
    return logging.getLogger(name)

class EnhancedLogger:
    """增强型日志记录器，提供更详细的日志格式"""

    def __init__(self, name: str):
        self.logger = get_logger(name)

    def _format_message(self, emoji: str, title: str, details: dict = None, reason: str = None) -> str:
        """格式化日志消息"""
        message = f"{emoji} {title}"

        if details:
            detail_items = []
            for key, value in details.items():
                if isinstance(value, float):
                    # 格式化浮点数
                    if "rate" in key.lower() or "percent" in key.lower():
                        detail_items.append(f"{key}={value:.2f}%")
                    elif "confidence" in key.lower():
                        detail_items.append(f"{key}={value:.2f}")
                    else:
                        detail_items.append(f"{key}={value:.4f}")
                else:
                    detail_items.append(f"{key}={value}")

            if detail_items:
                message += f" ({', '.join(detail_items)})"

        if reason:
            message += f" - {reason}"

        return message

    def info_cycle_start(self, cycle: int, current_time: str):
        """记录交易周期开始"""
        self.logger.info("=" * 60)
        self.logger.info(f"🔄 第 {cycle} 轮交易周期开始")
        self.logger.info(f"⏰ 当前时间: {current_time}")
        self.logger.info("=" * 60)

    def info_market_data(self, price: float, period: str, change_percent: float,
                        last_kline_time: str = None):
        """记录市场数据"""
        if last_kline_time:
            self.logger.info(f"上一个K线时间: {last_kline_time}")
        self.logger.info(f"BTC当前价格: ${price:,.2f}")
        self.logger.info(f"数据周期: {period}")
        self.logger.info(f"价格变化: {change_percent:+.2f}% (基于上一个{period}周期K线)")

    def info_market_analysis(self, atr_volatility: float, trend_strength: float,
                           volatility_level: str, price_change: float):
        """记录市场状态分析"""
        self.logger.info("📊 市场状态分析:")
        self.logger.info(f"   - ATR波动率: {atr_volatility:.2f}%")
        self.logger.info(f"   - 趋势强度: {trend_strength:.1f}")
        self.logger.info(f"   - 波动率级别: {volatility_level}")
        self.logger.info(f"   - 价格变化: {price_change:+.2f}%")

    def info_ai_providers(self, providers: list, config_providers: str):
        """记录AI提供商信息"""
        self.logger.info(f"使用AI提供商: {providers} (配置: {config_providers})")

    def info_ai_parallel_request(self, providers: list):
        """记录并行AI请求"""
        self.logger.info(f"🚀 并行获取多AI信号: {providers}")

    def info_ai_timeout_optimization(self, provider: str, timeout_multiplier: float):
        """记录AI超时优化"""
        self.logger.info(f"⏰ {provider} 性能优秀，超时时间优化: {timeout_multiplier}x")

    def info_ai_api_call(self, provider: str, url: str, model: str):
        """记录AI API调用"""
        self.logger.info(f"调用{provider} API: URL={url}, Model={model}")

    def info_ai_performance_stats(self, provider: str, success_rate: float,
                                avg_response_time: float, total_requests: int):
        """记录AI性能统计"""
        self.logger.info(f"📊 {provider} 超时统计更新: 成功率={success_rate:.2f}, "
                        f"平均响应={avg_response_time:.1f}s, 总请求={total_requests}")

    def info_cycle_complete(self, cycle: int, execution_time: float,
                           total_signals: int, executed_trades: int,
                           next_execution_time: str, wait_time: str):
        """记录交易周期完成"""
        self.logger.info("=" * 60)
        self.logger.info(f"✅ 第 {cycle} 轮交易周期完成")
        self.logger.info(f"⏱️  执行耗时: {execution_time:.2f}秒")
        self.logger.info(f"📊 信号统计: 生成 {total_signals} 个信号，执行 {executed_trades} 笔交易")
        self.logger.info(f"⏰ 下次执行时间: {next_execution_time}")
        self.logger.info(f"⏰ 等待 {wait_time} 到下一个15分钟整点执行...")
        self.logger.info("=" * 60)

    def info_ai_signal_success(self, provider: str, signal: str, confidence: float):
        """记录AI信号成功"""
        self.logger.info(f"✅ {provider.upper()} 成功: {signal} (信心: {confidence:.1f})")

    def info_ai_fusion_stats(self, success_count: int, fail_count: int,
                           total_providers: list, success_providers: list):
        """记录AI融合统计"""
        self.logger.info(f"📊 多AI信号获取统计: 成功={success_count}, 失败={fail_count}")
        self.logger.info(f"✅ 成功提供商: {success_providers if success_providers else '无'}")
        self.logger.info(f"📊 全局性能: 总请求={len(total_providers)}, "
                        f"失败率={fail_count/len(total_providers)*100:.2f}%")

    def info_ai_signal_diversity(self, diversity_score: float, signal_distribution: dict,
                               avg_confidence: float, std_confidence: float):
        """记录AI信号多样性分析"""
        self.logger.info("📊 【AI信号多样性分析】")
        self.logger.info(f"   多样性分数: {diversity_score:.2f} (0-1，越高越多样)")
        self.logger.info(f"   信号分布: BUY={signal_distribution.get('BUY', 0)}, "
                        f"SELL={signal_distribution.get('SELL', 0)}, "
                        f"HOLD={signal_distribution.get('HOLD', 0)}")
        self.logger.info(f"   信心均值: {avg_confidence:.2f}，标准差: {std_confidence:.2f}")

        # 判断是否过度一致
        is_overly_consistent = diversity_score < 0.3 and std_confidence < 0.1
        needs_intervention = is_overly_consistent

        self.logger.info(f"   是否过度一致: {'❌ 是' if is_overly_consistent else '✅ 否'}")
        self.logger.info(f"   需要干预: {'✅ 是' if needs_intervention else '✅ 否'}")

    def info_ai_voting_stats(self, voting_stats: dict):
        """记录投票统计"""
        self.logger.info(f"🗳️ 投票统计: "
                        f"BUY={voting_stats.get('BUY', 0)}, "
                        f"SELL={voting_stats.get('SELL', 0)}, "
                        f"HOLD={voting_stats.get('HOLD', 0)}")

    def info_ai_confidence_distribution(self, confidence_dist: dict):
        """记录信心分布"""
        self.logger.info(f"📈 信心分布: "
                        f"BUY={confidence_dist.get('BUY', 0.00):.2f}, "
                        f"SELL={confidence_dist.get('SELL', 0.00):.2f}, "
                        f"HOLD={confidence_dist.get('HOLD', 0.00):.2f}")

    def info_ai_dynamic_adjustment(self, rsi: float, atr: float, trend: str):
        """记录动态信心调整"""
        self.logger.info(f"📊 动态信心调整: BUY×0.85, SELL×0.85, HOLD×1.50")
        self.logger.info(f"📊 调整原因: RSI={rsi:.1f}, ATR={atr:.2f}%, 趋势={trend}")

    def info_ai_final_decision(self, decision: str, confidence: float, adjustment_factor: float):
        """记录最终AI决策"""
        self.logger.info(f"🎯 保守决策: {decision} (信心: {confidence:.2f}, 调整因子: {adjustment_factor:.2f})")

    def info_ai_consensus_adjustment(self, original_confidence: float, consensus_score: float):
        """记录共识度调整"""
        self.logger.info(f"⚖️ 共识度调整: 原始信心 × {consensus_score:.2f} = {original_confidence * consensus_score:.2f}")

    def info_ai_consistency_score(self, success_rates: list, mean_rate: float,
                                std_rate: float, final_score: float):
        """记录一致性得分"""
        self.logger.info(f"📊 一致性得分计算: 成功率={success_rates}, 均值={mean_rate:.2f}, "
                        f"标准差={std_rate:.2f}, 最终得分={final_score:.2f}")

    def info_trading_decision(self, action: str, price: float, size: float,
                            reason: str, confidence: float):
        """记录交易决策"""
        self.logger.info(f"💰 交易决策: {action} @ ${price:,.2f}")
        self.logger.info(f"   数量: {size} BTC, 信心: {confidence:.2f}")
        self.logger.info(f"   原因: {reason}")

    def info_position_update(self, position_type: str, size: float, avg_price: float,
                           pnl: float, pnl_percent: float):
        """记录仓位更新"""
        self.logger.info(f"📍 仓位更新: {position_type} {size} BTC")
        self.logger.info(f"   平均价格: ${avg_price:,.2f}")
        self.logger.info(f"   盈亏: ${pnl:,.2f} ({pnl_percent:+.2f}%)")

    def info_risk_assessment(self, risk_level: str, risk_score: float,
                           max_position_size: float, current_exposure: float):
        """记录风险评估"""
        self.logger.info(f"⚠️ 风险评估: 等级={risk_level}, 分数={risk_score:.2f}")
        self.logger.info(f"   最大仓位: {max_position_size}, 当前敞口: {current_exposure:.2f}")

    def info_system_status(self, cpu_usage: float, memory_usage: float,
                         disk_usage: float, network_latency: float):
        """记录系统状态"""
        self.logger.info("🔧 系统状态:")
        self.logger.info(f"   CPU使用率: {cpu_usage:.1f}%")
        self.logger.info(f"   内存使用率: {memory_usage:.1f}%")
        self.logger.info(f"   磁盘使用率: {disk_usage:.1f}%")
        self.logger.info(f"   网络延迟: {network_latency:.0f}ms")


class LoggerMixin:
    """日志混入类"""

    @property
    def logger(self) -> logging.Logger:
        """获取logger"""
        # 使用完整的模块路径和类名，确保日志记录器名称一致性
        module_path = self.__class__.__module__
        class_name = self.__class__.__name__
        if module_path and module_path != '__main__':
            logger_name = f"{module_path}.{class_name}"
        else:
            logger_name = class_name
        return get_logger(logger_name)

    @property
    def enhanced_logger(self) -> EnhancedLogger:
        """获取增强型logger"""
        # 使用完整的模块路径和类名，确保日志记录器名称一致性
        module_path = self.__class__.__module__
        class_name = self.__class__.__name__
        if module_path and module_path != '__main__':
            logger_name = f"{module_path}.{class_name}"
        else:
            logger_name = class_name
        return EnhancedLogger(logger_name)