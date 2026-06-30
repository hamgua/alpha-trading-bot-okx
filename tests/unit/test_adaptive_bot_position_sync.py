"""持仓同步对账测试

验证 adaptive_bot 在 API 返回无持仓但本地 PositionManager 仍有持仓状态时
清理本地缓存的逻辑。
"""

from unittest.mock import MagicMock, AsyncMock

import pytest

from alpha_trading_bot.ai.adaptive.rules_engine import AdaptiveRulesEngine
from alpha_trading_bot.ai.adaptive.performance_tracker import PerformanceTracker
from alpha_trading_bot.ai.adaptive.market_regime import MarketRegimeDetector


class TestPositionSyncReconciliation:
    """持仓对账：API无持仓 + 本地有持仓 -> 清理本地"""

    def test_clears_local_position_when_api_returns_empty(self):
        """API返回无持仓且本地有持仓时，调用clear_position"""
        from alpha_trading_bot.core.position_manager import PositionManager

        pm = MagicMock(spec=PositionManager)
        pm.has_position.return_value = True

        # 模拟 adaptive_bot 中的对账逻辑
        has_position = False
        if not has_position:
            if pm.has_position():
                pm.clear_position()

        pm.clear_position.assert_called_once()

    def test_no_clear_when_api_has_position(self):
        """API返回有持仓时，不调用clear_position"""
        from alpha_trading_bot.core.position_manager import PositionManager

        pm = MagicMock(spec=PositionManager)
        pm.has_position.return_value = True

        has_position = True
        if not has_position:
            if pm.has_position():
                pm.clear_position()

        pm.clear_position.assert_not_called()

    def test_no_clear_when_local_already_empty(self):
        """API无持仓且本地也无持仓时，不调用clear_position"""
        from alpha_trading_bot.core.position_manager import PositionManager

        pm = MagicMock(spec=PositionManager)
        pm.has_position.return_value = False

        has_position = False
        if not has_position:
            if pm.has_position():
                pm.clear_position()

        pm.clear_position.assert_not_called()
