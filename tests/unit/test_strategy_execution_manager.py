"""
StrategyExecutionManager.analyze_and_select 代理方法测试

覆盖场景：
1. 正常路径：analyze_and_select 正确委托给 _strategy_selector
2. 异常路径：_strategy_selector 抛出异常时正确传播
3. 权限路径：无持仓时 position_data 默认为 None
4. 边界条件：market_data 为空字典
5. 回归测试：返回值字段兼容 adaptive_bot.py 的使用方式
"""

import pytest
from unittest.mock import MagicMock, patch

from alpha_trading_bot.core.managers.strategy_manager import StrategyExecutionManager


@pytest.fixture
def manager():
    """创建 StrategyExecutionManager 实例"""
    return StrategyExecutionManager()


@pytest.fixture
def mock_selected_strategy():
    """模拟 SelectedStrategy 返回值"""
    from alpha_trading_bot.ai.adaptive.strategy_selector import SelectedStrategy

    return SelectedStrategy(
        strategy_type="trend_following",
        signal="buy",
        confidence=0.75,
        weight=1.0,
        source="strategy",
        reasons=["优先策略: trend_following (置信度: 75.00%)", "市场状态: strong_trend"],
        market_conditions={"regime": "strong_trend"},
    )


class TestAnalyzeAndSelectProxy:
    """测试 analyze_and_select 代理方法"""

    def test_analyze_and_select_exists(self, manager: StrategyExecutionManager):
        """验证 analyze_and_select 方法存在于 StrategyExecutionManager"""
        assert hasattr(manager, "analyze_and_select"), (
            "StrategyExecutionManager 应该有 analyze_and_select 方法"
        )
        assert callable(manager.analyze_and_select), (
            "analyze_and_select 应该是可调用的方法"
        )

    def test_analyze_and_select_delegates_to_selector(
        self, manager: StrategyExecutionManager, mock_selected_strategy
    ):
        """验证 analyze_and_select 正确委托给 _strategy_selector"""
        manager._strategy_selector.analyze_and_select = MagicMock(
            return_value=mock_selected_strategy
        )

        market_data = {"technical": {"rsi": 55, "trend_strength": 0.3}}
        result = manager.analyze_and_select(market_data, {})

        manager._strategy_selector.analyze_and_select.assert_called_once_with(
            market_data, {}
        )
        assert result is mock_selected_strategy

    def test_analyze_and_select_with_none_position(
        self, manager: StrategyExecutionManager, mock_selected_strategy
    ):
        """验证 position_data 为 None 时正确传递"""
        manager._strategy_selector.analyze_and_select = MagicMock(
            return_value=mock_selected_strategy
        )

        market_data = {"technical": {"rsi": 40}}
        result = manager.analyze_and_select(market_data, None)

        manager._strategy_selector.analyze_and_select.assert_called_once_with(
            market_data, None
        )
        assert result is mock_selected_strategy

    def test_analyze_and_select_default_position_none(
        self, manager: StrategyExecutionManager, mock_selected_strategy
    ):
        """验证 position_data 默认值为 None"""
        manager._strategy_selector.analyze_and_select = MagicMock(
            return_value=mock_selected_strategy
        )

        market_data = {"technical": {"rsi": 40}}
        result = manager.analyze_and_select(market_data)

        manager._strategy_selector.analyze_and_select.assert_called_once_with(
            market_data, None
        )

    def test_analyze_and_select_empty_market_data(
        self, manager: StrategyExecutionManager, mock_selected_strategy
    ):
        """边界条件：market_data 为空字典"""
        manager._strategy_selector.analyze_and_select = MagicMock(
            return_value=mock_selected_strategy
        )

        result = manager.analyze_and_select({}, {})
        assert result is mock_selected_strategy

    def test_return_value_fields_compatible(
        self, manager: StrategyExecutionManager, mock_selected_strategy
    ):
        """回归测试：返回值字段与 adaptive_bot.py 使用方式兼容"""
        manager._strategy_selector.analyze_and_select = MagicMock(
            return_value=mock_selected_strategy
        )

        result = manager.analyze_and_select({}, {})

        # adaptive_bot.py 使用的字段
        assert hasattr(result, "strategy_type"), "缺少 strategy_type 字段"
        assert hasattr(result, "signal"), "缺少 signal 字段"
        assert hasattr(result, "confidence"), "缺少 confidence 字段"
        assert hasattr(result, "reasons"), "缺少 reasons 字段"

        assert isinstance(result.strategy_type, str)
        assert isinstance(result.signal, str)
        assert isinstance(result.confidence, float)
        assert isinstance(result.reasons, list)

    def test_analyze_and_select_propagates_exception(
        self, manager: StrategyExecutionManager
    ):
        """异常路径：_strategy_selector 抛出异常时正确传播"""
        manager._strategy_selector.analyze_and_select = MagicMock(
            side_effect=ValueError("策略选择失败")
        )

        with pytest.raises(ValueError, match="策略选择失败"):
            manager.analyze_and_select({})


class TestStrategyExecutionManagerInit:
    """测试 StrategyExecutionManager 初始化"""

    def test_init_creates_strategy_selector(self, manager: StrategyExecutionManager):
        """验证初始化时创建了 _strategy_selector"""
        assert hasattr(manager, "_strategy_selector"), (
            "应该有 _strategy_selector 属性"
        )

    def test_init_creates_strategy_library(self, manager: StrategyExecutionManager):
        """验证初始化时创建了 _strategy_library"""
        assert hasattr(manager, "_strategy_library"), (
            "应该有 _strategy_library 属性"
        )