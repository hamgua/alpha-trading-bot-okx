"""Stop-loss posSide 修复测试

回归测试 OKX 账户持仓模式（one-way / hedge）对 posSide 字段的影响。

根因：
- v3.120.231 引入 posSide="long"/"short" 假设 hedge mode
- 用户 OKX 账户是 one-way mode，posSide 必须为 "net"
- 错误码 51000 "Parameter posSide error" 持续出现
- 修复：检测 posMode 动态选择 posSide
"""
from unittest.mock import MagicMock

import pytest

from alpha_trading_bot.exchange.order_service import OrderService


def _make_service(pos_mode=None, pos_mode_detected=True):
    """构造 OrderService，可选预设 posMode。"""
    exchange = MagicMock()
    svc = OrderService(exchange, "BTC/USDT:USDT")
    if pos_mode is not None:
        svc._pos_mode = pos_mode
        svc._pos_mode_detected = pos_mode_detected
    return svc


# ============================================================
# _resolve_pos_side 单元测试
# ============================================================


class TestResolvePosSide:
    """posSide 解析：one-way / hedge 模式"""

    def test_one_way_sell_returns_net(self):
        """one-way 模式下 sell → posSide=net"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_ONEWAY)
        assert svc._resolve_pos_side("sell") == "net"

    def test_one_way_buy_returns_net(self):
        """one-way 模式下 buy → posSide=net"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_ONEWAY)
        assert svc._resolve_pos_side("buy") == "net"

    def test_hedge_sell_returns_long(self):
        """hedge 模式下 sell (平多仓) → posSide=long"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_HEDGE)
        assert svc._resolve_pos_side("sell") == "long"

    def test_hedge_buy_returns_short(self):
        """hedge 模式下 buy (平空仓) → posSide=short"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_HEDGE)
        assert svc._resolve_pos_side("buy") == "short"

    def test_unknown_pos_mode_falls_back_to_net(self):
        """未知 posMode fallback 到 one-way (posSide=net)"""
        svc = _make_service(
            pos_mode=OrderService.POS_MODE_UNKNOWN,
            pos_mode_detected=True,
        )
        assert svc._resolve_pos_side("sell") == "net"
        assert svc._resolve_pos_side("buy") == "net"


# ============================================================
# _detect_pos_mode 单元测试
# ============================================================


class TestDetectPosMode:
    """OKX 账户 posMode 检测"""

    def test_detect_hedge_mode(self):
        """OKX 返回 long_short_mode → 检测为 HEDGE"""
        exchange = MagicMock()
        exchange.private_get_account_config = MagicMock(
            return_value={"code": "0", "data": [{"posMode": "long_short_mode"}]}
        )
        svc = OrderService(exchange, "BTC/USDT:USDT")
        mode = svc._detect_pos_mode()
        assert mode == OrderService.POS_MODE_HEDGE

    def test_detect_one_way_mode(self):
        """OKX 返回 net_mode → 检测为 ONEWAY"""
        exchange = MagicMock()
        exchange.private_get_account_config = MagicMock(
            return_value={"code": "0", "data": [{"posMode": "net_mode"}]}
        )
        svc = OrderService(exchange, "BTC/USDT:USDT")
        mode = svc._detect_pos_mode()
        assert mode == OrderService.POS_MODE_ONEWAY

    def test_detect_failure_falls_back_to_one_way(self):
        """OKX 抛异常 → fallback 到 ONEWAY"""
        exchange = MagicMock()
        exchange.private_get_account_config = MagicMock(
            side_effect=Exception("network error")
        )
        svc = OrderService(exchange, "BTC/USDT:USDT")
        mode = svc._detect_pos_mode()
        assert mode == OrderService.POS_MODE_ONEWAY

    def test_detect_empty_data_falls_back_to_one_way(self):
        """OKX 返回空 data → fallback 到 ONEWAY"""
        exchange = MagicMock()
        exchange.private_get_account_config = MagicMock(
            return_value={"code": "0", "data": []}
        )
        svc = OrderService(exchange, "BTC/USDT:USDT")
        mode = svc._detect_pos_mode()
        assert mode == OrderService.POS_MODE_ONEWAY

    def test_detect_non_zero_code_falls_back_to_one_way(self):
        """OKX 返回错误码 → fallback 到 ONEWAY"""
        exchange = MagicMock()
        exchange.private_get_account_config = MagicMock(
            return_value={"code": "50001", "msg": "internal error"}
        )
        svc = OrderService(exchange, "BTC/USDT:USDT")
        mode = svc._detect_pos_mode()
        assert mode == OrderService.POS_MODE_ONEWAY

    def test_detect_caches_result(self):
        """第二次检测不应调用 OKX API（缓存）"""
        exchange = MagicMock()
        exchange.private_get_account_config = MagicMock(
            return_value={"code": "0", "data": [{"posMode": "long_short_mode"}]}
        )
        svc = OrderService(exchange, "BTC/USDT:USDT")
        svc._detect_pos_mode()
        first_calls = exchange.private_get_account_config.call_count
        svc._detect_pos_mode()
        second_calls = exchange.private_get_account_config.call_count
        assert first_calls == 1
        assert second_calls == 1  # 未增加

    def test_method_unavailable_falls_back_to_one_way(self):
        """ccxt 不暴露接口时 fallback 到 ONEWAY"""
        exchange = MagicMock()
        # 设置两个属性都为 None
        exchange.private_get_account_config = None
        exchange.privateGetAccountConfig = None
        svc = OrderService(exchange, "BTC/USDT:USDT")
        mode = svc._detect_pos_mode()
        assert mode == OrderService.POS_MODE_ONEWAY


# ============================================================
# _create_algo_order_direct 集成测试
# ============================================================


class TestCreateAlgoOrderDirect:
    """_create_algo_order_direct 中的 posSide 参数"""

    def test_one_way_mode_sends_pos_side_net(self):
        """one-way 模式下提交 stop-loss 时 posSide=net"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_ONEWAY)
        method = MagicMock(
            return_value={"code": "0", "data": [{"algoId": "algo-001"}]}
        )
        svc._create_algo_order_direct(
            method,
            "BTC/USDT:USDT",
            "sell",
            0.01,
            {"slTriggerPx": 65000, "slOrdPx": -1},
        )
        call_params = method.call_args[0][0]
        assert call_params["posSide"] == "net"
        assert call_params["side"] == "sell"
        assert call_params["reduceOnly"] == "true"

    def test_hedge_mode_sell_sends_pos_side_long(self):
        """hedge 模式下 sell 平多仓时 posSide=long"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_HEDGE)
        method = MagicMock(
            return_value={"code": "0", "data": [{"algoId": "algo-002"}]}
        )
        svc._create_algo_order_direct(
            method,
            "BTC/USDT:USDT",
            "sell",
            0.01,
            {"slTriggerPx": 65000, "slOrdPx": -1},
        )
        call_params = method.call_args[0][0]
        assert call_params["posSide"] == "long"

    def test_hedge_mode_buy_sends_pos_side_short(self):
        """hedge 模式下 buy 平空仓时 posSide=short"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_HEDGE)
        method = MagicMock(
            return_value={"code": "0", "data": [{"algoId": "algo-003"}]}
        )
        svc._create_algo_order_direct(
            method,
            "BTC/USDT:USDT",
            "buy",
            0.01,
            {"tpTriggerPx": 70000, "tpOrdPx": -1},
        )
        call_params = method.call_args[0][0]
        assert call_params["posSide"] == "short"

    def test_stop_loss_trigger_price_formatting(self):
        """止损单 slTriggerPx 正确格式化"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_ONEWAY)
        method = MagicMock(
            return_value={"code": "0", "data": [{"algoId": "algo-004"}]}
        )
        svc._create_algo_order_direct(
            method,
            "BTC/USDT:USDT",
            "sell",
            0.01,
            {"slTriggerPx": 65432.123456, "slOrdPx": -1},
        )
        call_params = method.call_args[0][0]
        assert "slTriggerPx" in call_params
        assert call_params["slOrdPx"] == "-1"


# ============================================================
# reset_pos_mode_cache 测试
# ============================================================


class TestResetPosModeCache:
    """缓存重置"""

    def test_reset_clears_cache(self):
        """reset_pos_mode_cache 应清除缓存"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_HEDGE)
        svc.reset_pos_mode_cache()
        assert svc._pos_mode == OrderService.POS_MODE_UNKNOWN
        assert svc._pos_mode_detected is False


# ============================================================
# create_stop_loss_with_status 端到端测试
# ============================================================


@pytest.mark.asyncio
class TestCreateStopLossEndToEnd:
    """完整的 create_stop_loss 流程"""

    async def test_one_way_account_succeeds(self):
        """one-way 账户成功创建止损单"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_ONEWAY)
        svc.exchange.private_post_trade_order_algo = MagicMock(
            return_value={"code": "0", "data": [{"algoId": "algo-success"}]}
        )
        result = await svc.create_stop_loss_with_status(
            "BTC/USDT:USDT", "sell", 0.01, 65000
        )
        assert result.order_id == "algo-success"
        assert result.status.value == "open"

        call_params = svc.exchange.private_post_trade_order_algo.call_args[0][0]
        assert call_params["posSide"] == "net"

    async def test_hedge_account_succeeds(self):
        """hedge 账户成功创建止损单"""
        svc = _make_service(pos_mode=OrderService.POS_MODE_HEDGE)
        svc.exchange.private_post_trade_order_algo = MagicMock(
            return_value={"code": "0", "data": [{"algoId": "algo-hedge"}]}
        )
        result = await svc.create_stop_loss_with_status(
            "BTC/USDT:USDT", "sell", 0.01, 65000
        )
        assert result.order_id == "algo-hedge"

        call_params = svc.exchange.private_post_trade_order_algo.call_args[0][0]
        assert call_params["posSide"] == "long"
