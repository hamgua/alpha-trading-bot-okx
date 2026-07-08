"""
订单服务 - 下单、撤单、止损止盈
增强版：订单状态确认、部分成交处理
"""

import asyncio
import logging
from typing import Any, Dict, Optional

from .models.orders import OrderResult, OrderStatus, StopOrderResult
from .okx_raw import (
    ensure_okx_success,
    first_data,
    format_okx_number,
    get_callable,
    okx_inst_id_from_symbol,
    parse_okx_order,
)

logger = logging.getLogger(__name__)


class OrderService:
    """订单服务（带状态确认）"""

    POS_MODE_ONEWAY = "net_mode"
    POS_MODE_HEDGE = "long_short_mode"
    POS_MODE_UNKNOWN = "unknown"

    def __init__(self, exchange, symbol: str):
        self.exchange = exchange
        self.symbol = symbol
        self._stop_orders: Dict[str, str] = {}
        self._pos_mode: str = self.POS_MODE_UNKNOWN
        self._pos_mode_detected: bool = False

    def _detect_pos_mode(self) -> str:
        """查询 OKX 账户配置，识别持仓模式（one-way / hedge）。

        OKX API: GET /api/v5/account/config
        返回字段: posMode (long_short_mode | net_mode)

        检测失败时 fallback 到 one-way（posSide="net"），原因是 OKX 账户默认是
        单向持仓，且 "net" 是兼容性最强的取值。
        """
        if self._pos_mode_detected:
            return self._pos_mode
        try:
            method = get_callable(
                self.exchange,
                "private_get_account_config",
                "privateGetAccountConfig",
            )
            if method is None:
                logger.warning(
                    "[posMode] OKX 账户配置接口不可用，默认 one-way (posSide=net)"
                )
                self._pos_mode = self.POS_MODE_ONEWAY
            else:
                response = method()
                ensure_okx_success(response, "account config")
                raw = first_data(response) or {}
                pos_mode = raw.get("posMode", self.POS_MODE_ONEWAY)
                self._pos_mode = pos_mode
                logger.info(f"[posMode] OKX 账户持仓模式: {pos_mode}")
        except Exception as e:
            logger.warning(
                f"[posMode] 检测失败，fallback 到 one-way (posSide=net): {e}"
            )
            self._pos_mode = self.POS_MODE_ONEWAY
        finally:
            self._pos_mode_detected = True
        return self._pos_mode

    def _resolve_pos_side(self, side: str) -> str:
        """根据持仓模式生成正确的 posSide。

        Args:
            side: 订单方向（buy/sell）

        Returns:
            OKX 接受的 posSide:
              - one-way 模式: "net"
              - hedge 模式:   "long"（平多仓）或 "short"（平空仓）
        """
        pos_mode = self._detect_pos_mode()
        if pos_mode == self.POS_MODE_HEDGE:
            return "long" if side == "sell" else "short"
        return "net"

    def reset_pos_mode_cache(self) -> None:
        """重置 posMode 缓存（用于测试或模式切换后）。"""
        self._pos_mode = self.POS_MODE_UNKNOWN
        self._pos_mode_detected = False

    async def create_order(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> str:
        """创建订单（向后兼容，返回order_id）"""
        result = await self.create_order_with_status(
            symbol, side, amount, price, order_type
        )
        return result.order_id

    async def create_order_with_status(
        self,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float] = None,
        order_type: str = "market",
    ) -> OrderResult:
        """
        创建订单并返回完整状态

        Args:
            symbol: 交易对
            side: 方向 (buy/sell)
            amount: 数量
            price: 价格（限价单）
            order_type: 订单类型 (market/limit)

        Returns:
            OrderResult: 订单执行结果
        """
        logger.info(
            f"[订单创建] 提交订单: symbol={symbol}, side={side}, "
            f"type={order_type}, amount={amount}, price={price}"
        )

        try:
            method = get_callable(
                self.exchange, "private_post_trade_order", "privatePostTradeOrder"
            )
            if method is not None:
                order = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._create_order_direct(
                        method, symbol, side, amount, price, order_type
                    ),
                )
            else:
                raise RuntimeError("OKX raw order endpoint is unavailable")

            result = self._parse_order_response(order, amount)

            if result.is_rejected:
                logger.error(
                    f"[订单创建] 订单被拒绝: ID={result.order_id}, "
                    f"原因={result.error_message}"
                )
            elif result.is_partially_filled:
                logger.warning(
                    f"[订单创建] 部分成交: ID={result.order_id}, "
                    f"已成交={result.filled_amount}, 剩余={result.remaining_amount}"
                )
            else:
                logger.info(
                    f"[订单创建] 订单成功: ID={result.order_id}, "
                    f"状态={result.status.value}, 成交={result.filled_amount}"
                )

            return result

        except Exception as e:
            logger.error(f"[订单创建] 订单异常: {e}")
            return OrderResult(
                order_id="",
                status=OrderStatus.REJECTED,
                symbol=symbol,
                side=side,
                order_type=order_type,
                requested_amount=amount,
                filled_amount=0,
                remaining_amount=amount,
                average_price=0,
                error_message=str(e),
            )

    def _create_order_direct(
        self,
        method,
        symbol: str,
        side: str,
        amount: float,
        price: Optional[float],
        order_type: str,
    ) -> Dict[str, Any]:
        """绕过 ccxt load_markets，直接调用 OKX 普通下单接口。"""
        params = {
            "instId": okx_inst_id_from_symbol(symbol),
            "tdMode": "cross",
            "side": side,
            "ordType": order_type,
            "sz": format_okx_number(amount),
        }
        if order_type != "market" and price is not None:
            params["px"] = format_okx_number(price)

        response = method(params)
        self._ensure_okx_order_item_success(response, "place order")
        raw = first_data(response)
        raw.setdefault("state", "live")
        raw.setdefault("side", side)
        raw.setdefault("ordType", order_type)
        raw.setdefault("sz", params["sz"])
        if price is not None:
            raw.setdefault("avgPx", format_okx_number(price))
        return parse_okx_order(raw, symbol, amount)

    @staticmethod
    def _ensure_okx_order_item_success(
        response: Dict[str, Any], operation: str
    ) -> None:
        ensure_okx_success(response, operation)
        raw = first_data(response)
        if raw and str(raw.get("sCode", "0")) != "0":
            raise RuntimeError(f"OKX {operation} failed: {response}")

    def _parse_order_response(
        self, order: Dict, requested_amount: float
    ) -> OrderResult:
        """解析交易所订单响应"""
        if order is None:
            logger.warning("[订单解析] 订单响应为None，可能已执行")
            # 返回一个待确认的状态，让上层处理
            return OrderResult(
                order_id="",
                status=OrderStatus.OPEN,  # 假设订单已提交，等待确认
                symbol="",
                side="",
                order_type="market",
                requested_amount=requested_amount,
                filled_amount=0,
                remaining_amount=requested_amount,
                average_price=0,
                error_message="订单响应为None，可能已执行",
            )

        order_id = order.get("id", "") or ""
        status_str = (order.get("status") or "unknown").lower()
        symbol = order.get("symbol", "")
        side = order.get("side", "")
        order_type = order.get("type", "market")

        filled = float(order.get("filled", 0) or 0)
        remaining = float(order.get("remaining", 0) or 0)
        avg_price = float(order.get("average", 0) or 0)

        status_map = {
            "open": OrderStatus.OPEN,
            "closed": OrderStatus.CLOSED,
            "canceled": OrderStatus.CANCELED,
            "cancelled": OrderStatus.CANCELED,
            "rejected": OrderStatus.REJECTED,
            "expired": OrderStatus.EXPIRED,
        }
        status = status_map.get(status_str, OrderStatus.UNKNOWN)

        error_message = None
        error_code = None
        if status == OrderStatus.REJECTED:
            info = order.get("info", {})
            error_message = info.get("sMsg", "订单被拒绝")
            error_code = info.get("sCode", "")

        return OrderResult(
            order_id=str(order_id),
            status=status,
            symbol=symbol,
            side=side,
            order_type=order_type,
            requested_amount=requested_amount,
            filled_amount=filled,
            remaining_amount=remaining,
            average_price=avg_price,
            error_message=error_message,
            error_code=error_code,
        )

    async def create_stop_loss(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
    ) -> str:
        """创建止损单（向后兼容）"""
        result = await self.create_stop_loss_with_status(
            symbol, side, amount, stop_price
        )
        return result.order_id

    async def create_stop_loss_with_status(
        self,
        symbol: str,
        side: str,
        amount: float,
        stop_price: float,
    ) -> StopOrderResult:
        """
        创建止损单并返回状态

        Args:
            symbol: 交易对
            side: 方向
            amount: 数量
            stop_price: 止损价

        Returns:
            StopOrderResult: 止损单执行结果
        """
        logger.info(
            f"[止损单创建] 提交止损单: symbol={symbol}, side={side}, "
            f"amount={amount}, stop_price={stop_price}"
        )

        try:
            method = get_callable(
                self.exchange,
                "private_post_trade_order_algo",
                "privatePostTradeOrderAlgo",
            )
            if method is not None:
                order = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._create_algo_order_direct(
                        method,
                        symbol,
                        side,
                        amount,
                        {"slTriggerPx": stop_price, "slOrdPx": -1},
                    ),
                )
            else:
                raise RuntimeError("OKX raw algo order endpoint is unavailable")

            algo_id = order.get("info", {}).get("algoId", order.get("id", ""))
            self._stop_orders[str(stop_price)] = str(algo_id)

            logger.info(
                f"[止损单创建] 止损单成功: ID={algo_id}, 止损价={stop_price}, 数量={amount}"
            )

            return StopOrderResult(
                order_id=str(algo_id),
                stop_price=stop_price,
                amount=amount,
                status=OrderStatus.OPEN,
            )

        except Exception as e:
            logger.error(f"[止损单创建] 止损单失败: {e}")
            return StopOrderResult(
                order_id="",
                stop_price=stop_price,
                amount=amount,
                status=OrderStatus.REJECTED,
            )

    def _create_algo_order_direct(
        self,
        method,
        symbol: str,
        side: str,
        amount: float,
        trigger_params: Dict[str, float],
    ) -> Dict[str, Any]:
        """绕过 ccxt load_markets，直接调用 OKX 算法单接口。"""
        pos_side = self._resolve_pos_side(side)
        params = {
            "instId": okx_inst_id_from_symbol(symbol),
            "tdMode": "cross",
            "side": side,
            "ordType": "conditional",
            "sz": format_okx_number(amount),
            "reduceOnly": "true",
            "posSide": pos_side,
        }
        for key, value in trigger_params.items():
            params[key] = "-1" if value == -1 else format_okx_number(value)

        response = method(params)
        self._ensure_okx_order_item_success(response, "place algo order")
        raw = first_data(response)
        algo_id = raw.get("algoId") or raw.get("id") or ""
        return {"id": str(algo_id), "info": raw}

    async def create_take_profit(
        self,
        symbol: str,
        side: str,
        amount: float,
        take_profit_price: float,
    ) -> StopOrderResult:
        """
        创建止盈单

        Args:
            symbol: 交易对
            side: 方向
            amount: 数量
            take_profit_price: 止盈价

        Returns:
            StopOrderResult: 止盈单执行结果
        """
        logger.info(
            f"[止盈单创建] 提交止盈单: symbol={symbol}, side={side}, "
            f"amount={amount}, take_profit_price={take_profit_price}"
        )

        try:
            method = get_callable(
                self.exchange,
                "private_post_trade_order_algo",
                "privatePostTradeOrderAlgo",
            )
            if method is not None:
                order = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: self._create_algo_order_direct(
                        method,
                        symbol,
                        side,
                        amount,
                        {"tpTriggerPx": take_profit_price, "tpOrdPx": -1},
                    ),
                )
            else:
                raise RuntimeError("OKX raw algo order endpoint is unavailable")

            algo_id = order.get("info", {}).get("algoId", order.get("id", ""))
            self._stop_orders[str(take_profit_price)] = str(algo_id)

            logger.info(
                f"[止盈单创建] 止盈单成功: ID={algo_id}, 止盈价={take_profit_price}, 数量={amount}"
            )

            return StopOrderResult(
                order_id=str(algo_id),
                stop_price=take_profit_price,
                amount=amount,
                status=OrderStatus.OPEN,
            )

        except Exception as e:
            logger.error(f"[止盈单创建] 止盈单失败: {e}")
            return StopOrderResult(
                order_id="",
                stop_price=take_profit_price,
                amount=amount,
                status=OrderStatus.REJECTED,
                error_message=str(e),
            )

    async def cancel_order(self, order_id: str, symbol: str) -> tuple[bool, str]:
        """取消订单

        Returns:
            tuple: (success: bool, reason: str)
                - (True, "success") - 取消成功
                - (False, "already_gone") - 订单已成交/取消/不存在
                - (False, "failed") - 取消失败
        """
        try:
            logger.info(f"[订单取消] 取消订单: ID={order_id}, symbol={symbol}")
            method = get_callable(
                self.exchange,
                "private_post_trade_cancel_order",
                "privatePostTradeCancelOrder",
            )
            if method is not None:
                params = {
                    "instId": okx_inst_id_from_symbol(symbol),
                    "ordId": order_id,
                }
                await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._cancel_order_direct(method, params)
                )
            else:
                raise RuntimeError("OKX raw cancel-order endpoint is unavailable")
            logger.info(f"[订单取消] 订单取消成功: {order_id}")
            return (True, "success")
        except Exception as e:
            error_msg = str(e)
            # 订单已成交/取消/不存在时，取消失败是正常的，降低日志级别
            if (
                "51400" in error_msg
                or "does not exist" in error_msg
                or "filled" in error_msg
            ):
                logger.warning(f"[订单取消] 订单已不存在: {order_id}, 错误={error_msg}")
                return (False, "already_gone")
            else:
                logger.error(f"[订单取消] 取消订单失败: {order_id}, 错误={error_msg}")
                return (False, "failed")

    def _cancel_order_direct(self, method, params: Dict[str, str]) -> None:
        """绕过 ccxt load_markets，直接调用 OKX 普通撤单接口。"""
        response = method(params)
        self._ensure_okx_order_item_success(response, "cancel order")

    async def cancel_algo_order(self, algo_id: str, symbol: str) -> tuple[bool, str]:
        """取消算法单（止损单、止盈单等）

        Args:
            algo_id: 算法单ID (algoId)
            symbol: 交易对，如 BTC/USDT:USDT

        Returns:
            tuple: (success: bool, reason: str)
                - (True, "success") - 取消成功
                - (False, "already_gone") - 订单已成交/取消/不存在
                - (False, "failed") - 取消失败
        """
        try:
            # 转换交易对格式: BTC/USDT:USDT -> BTC-USDT-SWAP (期货合约格式)
            inst_id = okx_inst_id_from_symbol(symbol)

            logger.info(f"[算法单取消] 取消算法单: ID={algo_id}, instId={inst_id}")
            method = get_callable(
                self.exchange,
                "private_post_trade_cancel_algos",
                "privatePostTradeCancelAlgos",
            )
            if method is None:
                raise RuntimeError("OKX raw cancel-algos endpoint is unavailable")
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: method([{"instId": inst_id, "algoId": algo_id}]),
            )
            self._ensure_okx_order_item_success(response, "cancel algo order")
            logger.info(f"[算法单取消] 算法单取消成功: {algo_id}")
            return (True, "success")
        except Exception as e:
            error_msg = str(e)
            # 订单已成交/取消/不存在时，取消失败是正常的
            if (
                "51400" in error_msg
                or "does not exist" in error_msg
                or "filled" in error_msg
            ):
                logger.warning(
                    f"[算法单取消] 算法单已不存在: {algo_id}, 错误={error_msg}"
                )
                return (False, "already_gone")
            else:
                logger.error(
                    f"[算法单取消] 取消算法单失败: {algo_id}, 错误={error_msg}"
                )
                return (False, "failed")

    async def get_order_status(self, order_id: str, symbol: str) -> OrderResult:
        """
        查询订单状态

        Args:
            order_id: 订单ID
            symbol: 交易对

        Returns:
            OrderResult: 订单状态
        """
        try:
            method = get_callable(
                self.exchange, "private_get_trade_order", "privateGetTradeOrder"
            )
            if method is not None:
                params = {
                    "instId": okx_inst_id_from_symbol(symbol),
                    "ordId": order_id,
                }
                order = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: self._get_order_status_direct(method, params, symbol)
                )
            else:
                raise RuntimeError("OKX raw order-status endpoint is unavailable")
            return self._parse_order_response(order, order.get("amount", 0))
        except Exception as e:
            logger.error(f"[订单查询] 查询订单状态失败: {order_id}, 错误={e}")
            return OrderResult(
                order_id=order_id,
                status=OrderStatus.UNKNOWN,
                symbol=symbol,
                side="",
                order_type="",
                requested_amount=0,
                filled_amount=0,
                remaining_amount=0,
                average_price=0,
                error_message=str(e),
            )

    def _get_order_status_direct(
        self, method, params: Dict[str, str], symbol: str
    ) -> Dict[str, Any]:
        """绕过 ccxt load_markets，直接调用 OKX 订单详情接口。"""
        response = method(params)
        ensure_okx_success(response, "fetch order")
        raw = first_data(response)
        return parse_okx_order(raw, symbol)

    def get_stop_order_id(self, stop_price: float) -> Optional[str]:
        """获取止损单ID"""
        return self._stop_orders.get(str(stop_price))


def create_order_service(exchange, symbol: str) -> OrderService:
    """创建订单服务实例"""
    return OrderService(exchange, symbol)
