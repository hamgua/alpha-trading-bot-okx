"""启动日志降噪回归测试。"""

import logging

from alpha_trading_bot.ai.adaptive_buy_condition import AdaptiveBuyCondition
from alpha_trading_bot.ai.high_price_buy_optimizer import HighPriceBuyOptimizer
from alpha_trading_bot.ai.integrator import IntegratedSignalResult
from alpha_trading_bot.ai.market_structure import MarketStructureAnalyzer
from alpha_trading_bot.ai.signal_optimizer import SignalOptimizer
from alpha_trading_bot.ai.sustained_decline_detector import SustainedDeclineDetector
from alpha_trading_bot.core.managers.market_regime_manager import MarketRegimeManager
from alpha_trading_bot.core.managers.parameter_manager import ParameterManager
from alpha_trading_bot.core.state_persistence import StatePersistence


def test_module_initialization_diagnostics_are_debug_logs(caplog):
    """普通模块初始化诊断不应占用启动INFO日志。"""
    with caplog.at_level(logging.INFO):
        AdaptiveBuyCondition()
        SignalOptimizer()
        HighPriceBuyOptimizer()
        SustainedDeclineDetector()
        MarketStructureAnalyzer()

    messages = [record.getMessage() for record in caplog.records]
    noisy_markers = [
        "[自适应买入条件] 初始化完成",
        "[信号优化器] 初始化完成",
        "[高位买入优化器] 初始化完成",
        "[持续下跌检测器] 初始化完成",
        "[市场结构分析器] 初始化完成",
    ]

    assert not any(
        marker in message for marker in noisy_markers for message in messages
    )


def test_state_persistence_startup_audit_remains_info(tmp_path, caplog):
    """持久化路径属于启动审计日志，仍需保留INFO可见性。"""
    with caplog.at_level(logging.INFO):
        StatePersistence(str(tmp_path))

    assert any("[持久化] 数据目录:" in record.getMessage() for record in caplog.records)


def test_ai_signal_confidence_trace_is_debug_but_summary_remains_info(caplog):
    """AI集成多行置信度追踪降噪，最终摘要仍保留。"""
    result = IntegratedSignalResult(
        original_signal="hold",
        original_confidence=0.6,
        final_signal="HOLD",
        final_confidence=0.63,
    )
    confidence_history = [
        (0, "原始", 0.6),
        (1, "AdaptiveBuy", 0.6),
        (2, "SignalOptimizer", 0.63),
        (5, "最终", 0.63),
    ]

    with caplog.at_level(logging.INFO):
        result.log_confidence_trace(confidence_history)

    messages = [record.getMessage() for record in caplog.records]
    assert not any("[信号诊断] 置信度变化流程:" in message for message in messages)
    assert not any("[0] 原始:" in message for message in messages)
    assert any("[AI信号集成]" in message for message in messages)


def test_parameter_manager_reuses_injected_performance_tracker():
    """参数管理器复用外部绩效追踪器，避免启动重复加载历史。"""
    from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceTracker

    performance_tracker = PerformanceTracker(data_dir="/tmp/unused-test-trades")
    manager = ParameterManager(performance_tracker=performance_tracker)

    assert manager._param_manager.performance_tracker is performance_tracker


def test_market_regime_manager_reuses_injected_performance_tracker():
    """市场状态管理器复用外部绩效追踪器，避免构造时重复加载历史。"""
    from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceTracker

    performance_tracker = PerformanceTracker(data_dir="/tmp/unused-test-trades")
    manager = MarketRegimeManager(performance_tracker=performance_tracker)

    assert manager._performance_tracker is performance_tracker
