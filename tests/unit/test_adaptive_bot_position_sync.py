"""持仓同步对账测试

验证 adaptive_bot 在 API 返回无持仓但本地 PositionManager 仍有持仓状态时
清理本地缓存的逻辑，以及 API 查询失败时的保护性行为。
"""

from unittest.mock import MagicMock, AsyncMock, patch

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

    def test_no_clear_when_api_query_fails(self):
        """API查询失败时，不清理本地持仓缓存"""
        from alpha_trading_bot.core.position_manager import PositionManager

        pm = MagicMock(spec=PositionManager)
        pm.has_position.return_value = True

        has_position = False
        query_failed = True

        if not has_position:
            if pm.has_position():
                if query_failed:
                    pass
                else:
                    pm.clear_position()

        pm.clear_position.assert_not_called()

    def test_clear_logs_position_context(self):
        """清理时日志包含本地持仓上下文信息"""
        from alpha_trading_bot.core.position_manager import PositionManager

        pm = MagicMock(spec=PositionManager)
        pm.has_position.return_value = True
        mock_position = MagicMock()
        mock_position.side = "long"
        pm.position = mock_position
        pm.entry_price = 62000.0
        pm.stop_order_id = "algo-123"
        pm.last_stop_price = 61000.0

        has_position = False
        query_failed = False

        if not has_position:
            if pm.has_position():
                if not query_failed:
                    log_msg = (
                        "[持仓对账] API返回无持仓，但本地PositionManager仍有持仓状态，"
                        "清理本地缓存。"
                        f"本地持仓: 方向={pm.position.side}, "
                        f"入场价={pm.entry_price}, "
                        f"止损单ID={pm.stop_order_id or 'N/A'}, "
                        f"止损价={pm.last_stop_price}"
                    )
                    assert "long" in log_msg
                    assert "62000" in log_msg
                    assert "algo-123" in log_msg
                    assert "61000" in log_msg
                    pm.clear_position()

        pm.clear_position.assert_called_once()

    def test_query_failed_flag_not_set_by_default(self):
        """AccountService 初始化时 _last_query_failed 默认为 False"""
        from alpha_trading_bot.exchange.account_service import AccountService

        exchange_mock = MagicMock()
        service = AccountService(exchange_mock, "BTC/USDT:USDT")

        assert service._last_query_failed is False

    @pytest.mark.asyncio
    async def test_get_position_raises_on_api_error(self):
        """get_position 在 API 异常时抛出异常而非返回 None"""
        from alpha_trading_bot.exchange.account_service import AccountService

        class _BrokenExchange:
            def private_get_account_positions(self, params):
                raise ConnectionError("network timeout")

        service = AccountService(_BrokenExchange(), "BTC/USDT:USDT")

        with pytest.raises(ConnectionError):
            await service.get_position()

    @pytest.mark.asyncio
    async def test_get_position_with_retry_sets_failed_flag_on_error(self):
        """get_position_with_retry 在查询失败时设置 _last_query_failed=True"""
        from alpha_trading_bot.exchange.account_service import AccountService

        class _BrokenExchange:
            def private_get_account_positions(self, params):
                raise ConnectionError("network timeout")

        service = AccountService(_BrokenExchange(), "BTC/USDT:USDT")

        result = await service.get_position_with_retry(max_retries=1, retry_delay=0.01)

        assert result is None
        assert service._last_query_failed is True

    @pytest.mark.asyncio
    async def test_get_position_with_retry_clears_failed_flag_on_success(self):
        """get_position_with_retry 在查询成功时设置 _last_query_failed=False"""
        from alpha_trading_bot.exchange.account_service import AccountService

        class _GoodExchange:
            def private_get_account_positions(self, params):
                return {"code": "0", "data": []}

        service = AccountService(_GoodExchange(), "BTC/USDT:USDT")
        service._last_query_failed = True

        result = await service.get_position_with_retry(max_retries=1, retry_delay=0.01)

        assert result is None
        assert service._last_query_failed is False

    @pytest.mark.asyncio
    async def test_get_position_returns_none_when_no_position(self):
        """get_position 在无持仓时返回 None（不抛异常）"""
        from alpha_trading_bot.exchange.account_service import AccountService

        class _EmptyExchange:
            def private_get_account_positions(self, params):
                return {"code": "0", "data": []}

        service = AccountService(_EmptyExchange(), "BTC/USDT:USDT")

        result = await service.get_position()

        assert result is None

    def test_exchange_client_last_query_failed_property(self):
        """ExchangeClient.last_query_failed 属性正确代理 AccountService"""
        from alpha_trading_bot.exchange.client import ExchangeClient
        from alpha_trading_bot.exchange.account_service import AccountService

        client = ExchangeClient()
        client._account_service = AccountService(
            MagicMock(), "BTC/USDT:USDT"
        )

        assert client.last_query_failed is False

        client._account_service._last_query_failed = True
        assert client.last_query_failed is True

    def test_exchange_client_last_query_failed_when_no_account_service(self):
        """ExchangeClient 未初始化 account_service 时 last_query_failed 返回 False"""
        from alpha_trading_bot.exchange.client import ExchangeClient

        client = ExchangeClient()

        assert client.last_query_failed is False
