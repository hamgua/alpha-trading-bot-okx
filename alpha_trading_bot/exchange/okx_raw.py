"""OKX 原始接口辅助函数，避免 ccxt unified API 隐式 load_markets。"""

from typing import Any, Dict, List, Optional

from .models.orders import OrderStatus


def okx_inst_id_from_symbol(symbol: str) -> str:
    """将 ccxt symbol 转换为 OKX instId。"""
    normalized = symbol.strip()
    if "/" not in normalized:
        return normalized.replace("/", "-").replace(":", "-")

    pair, _, contract_suffix = normalized.partition(":")
    base, quote = pair.split("/", 1)
    if contract_suffix:
        return f"{base}-{quote}-SWAP"
    return f"{base}-{quote}"


def get_callable(exchange: Any, snake_name: str, camel_name: str):
    """按 ccxt 新旧命名风格获取 OKX raw 方法。"""
    method = getattr(exchange, snake_name, None)
    if method is None:
        method = getattr(exchange, camel_name, None)
    return method if callable(method) else None


def to_float(value: Any, default: float = 0.0) -> float:
    """安全转 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def ensure_okx_success(response: Dict[str, Any], operation: str) -> None:
    """检查 OKX raw 响应顶层 code。"""
    if str(response.get("code", "0")) != "0":
        raise RuntimeError(f"OKX {operation} failed: {response}")


def first_data(response: Dict[str, Any]) -> Dict[str, Any]:
    """取 OKX raw 响应第一条 data。"""
    data = response.get("data") or []
    return data[0] if data else {}


def format_okx_number(value: float) -> str:
    """格式化 OKX 请求里的数字，避免 0.100000 这类尾零。"""
    return f"{value:.12g}"


def okx_order_status(state: Optional[str]) -> OrderStatus:
    """将 OKX 订单状态转换为项目订单状态。"""
    status_map = {
        "live": OrderStatus.OPEN,
        "partially_filled": OrderStatus.OPEN,
        "filled": OrderStatus.CLOSED,
        "canceled": OrderStatus.CANCELED,
        "cancelled": OrderStatus.CANCELED,
        "mmp_canceled": OrderStatus.CANCELED,
        "rejected": OrderStatus.REJECTED,
    }
    return status_map.get((state or "").lower(), OrderStatus.UNKNOWN)


def parse_okx_order(
    raw: Dict[str, Any],
    symbol: str,
    requested_amount: float = 0.0,
) -> Dict[str, Any]:
    """解析 OKX 普通订单为 OrderService 可消费的 dict。"""
    order_id = raw.get("ordId") or raw.get("id") or ""
    state = raw.get("state") or raw.get("status")
    amount = to_float(raw.get("sz"), requested_amount)
    filled = to_float(raw.get("accFillSz"), to_float(raw.get("fillSz"), 0.0))
    remaining = max(amount - filled, 0.0) if amount else 0.0

    return {
        "id": str(order_id),
        "status": okx_order_status(state).value,
        "symbol": symbol,
        "side": raw.get("side", ""),
        "type": raw.get("ordType", ""),
        "amount": amount,
        "filled": filled,
        "remaining": remaining,
        "average": to_float(raw.get("avgPx")),
        "info": raw,
    }


def parse_okx_orders(response: Dict[str, Any], symbol: str) -> List[Dict[str, Any]]:
    """解析 OKX 普通订单列表。"""
    ensure_okx_success(response, "orders")
    return [parse_okx_order(raw, symbol) for raw in response.get("data") or []]


def parse_okx_algo_orders(
    response: Dict[str, Any], symbol: str
) -> List[Dict[str, Any]]:
    """解析 OKX 算法单列表。"""
    ensure_okx_success(response, "algo orders")
    orders = []
    for raw in response.get("data") or []:
        algo_id = raw.get("algoId") or raw.get("id") or ""
        orders.append(
            {
                "id": str(algo_id),
                "status": okx_order_status(raw.get("state")).value,
                "symbol": symbol,
                "type": raw.get("ordType", "conditional"),
                "info": raw,
            }
        )
    return orders
