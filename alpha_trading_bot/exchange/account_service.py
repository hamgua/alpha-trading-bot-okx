"""
账户服务 - 余额和持仓查询
"""

import asyncio
import logging
from typing import Dict, Any, Optional

from .okx_raw import (
    ensure_okx_success,
    get_callable,
    okx_inst_id_from_symbol,
    to_float,
)

logger = logging.getLogger(__name__)


class AccountService:
    """账户服务"""

    def __init__(self, exchange, symbol: str, allow_short_selling: bool = True):
        self.exchange = exchange
        self.symbol = symbol
        self.allow_short_selling = allow_short_selling  # 是否允许做空
        self._last_position_state: Optional[Dict[str, Any]] = None  # 上一次持仓状态
        # 标记最后一次 get_position_with_retry 查询是否失败
        # True=查询失败(网络/API异常), False=查询成功(无论有无持仓)
        # 调用方可通过此标记区分"无持仓"和"查询失败"，避免误清理本地缓存
        self._last_query_failed: bool = False

    async def get_balance(self) -> float:
        """获取可用USDT余额"""
        try:
            method = get_callable(
                self.exchange,
                "private_get_account_balance",
                "privateGetAccountBalance",
            )
            if method is not None:
                usdt_available = await asyncio.get_running_loop().run_in_executor(
                    None, lambda: self._get_okx_usdt_balance(method({"ccy": "USDT"}))
                )
            else:
                raise RuntimeError("OKX raw account balance endpoint is unavailable")
            logger.info(f"可用USDT余额: {usdt_available}")
            return float(usdt_available)
        except Exception as e:
            logger.error(f"获取余额失败: {e}")
            return 0.0

    @staticmethod
    def _get_okx_usdt_balance(response: Dict[str, Any]) -> float:
        ensure_okx_success(response, "account balance")
        for account in response.get("data") or []:
            for detail in account.get("details") or []:
                if detail.get("ccy") == "USDT":
                    return to_float(
                        detail.get("availEq"),
                        to_float(
                            detail.get("availBal"), to_float(detail.get("cashBal"))
                        ),
                    )
        return 0.0

    async def get_position_with_retry(
        self, max_retries: int = 3, retry_delay: float = 1.0
    ) -> Optional[Dict[str, Any]]:
        """
        获取持仓（带重试机制）

        优化逻辑：只有当 API 返回与上一次状态不同时才额外验证
        - 上次有持仓 → 本次无持仓：触发额外验证（避免 API 延迟误判）
        - 上次无持仓 → 本次无持仓：直接确认（无需验证）
        - 上次有持仓 → 本次有持仓：直接返回

        _last_query_failed 属性标记本次查询是否因异常而失败：
        - True: 查询失败，返回值 None 不可信，调用方不应据此清理本地持仓
        - False: 查询成功，返回值 None 表示交易所确实无持仓
        """
        # 第一次查询
        try:
            result = await self.get_position()
            self._last_query_failed = False
        except Exception as e:
            logger.error(f"[账户查询] 获取持仓失败: {e}")
            self._last_query_failed = True
            return None

        current_has_position = result is not None
        last_has_position = self._last_position_state is not None

        # 检查状态是否有变化
        if current_has_position != last_has_position:
            old_state = "有持仓" if last_has_position else "无持仓"
            new_state = "有持仓" if current_has_position else "无持仓"
            logger.warning(
                f"[账户查询] 持仓状态变化: {old_state} → {new_state}，进行验证..."
            )

            # 额外验证 2 次
            for verify_attempt in range(2):
                await asyncio.sleep(retry_delay)
                try:
                    verify_result = await self.get_position()
                    if verify_result is not None:
                        logger.info("[账户查询] 验证成功，持仓确认")
                        self._last_position_state = verify_result
                        self._last_query_failed = False
                        return verify_result
                except Exception as e:
                    logger.warning(f"[账户查询] 验证失败: {e}")
                    self._last_query_failed = True

            logger.warning("[账户查询] 验证多次仍不一致，以本次API返回为准")
            self._last_query_failed = False

        # 更新状态
        self._last_position_state = result

        if result is None:
            logger.debug(f"[账户查询] {self.symbol} 无持仓")
        else:
            logger.info(
                f"[账户查询] 找到持仓: 方向={result['side']}, "
                f"数量={result['amount']}, 入场价={result['entry_price']}"
            )

        return result

    async def get_position(self) -> Optional[Dict[str, Any]]:
        """获取当前持仓（只支持做多，空单自动标记平仓）

        Raises:
            Exception: OKX API 调用失败时向上传播异常，调用方需自行捕获。
                       返回 None 表示交易所确认无持仓。
        """
        logger.debug(f"[账户查询] 正在获取 {self.symbol} 的持仓信息...")
        method = get_callable(
            self.exchange,
            "private_get_account_positions",
            "privateGetAccountPositions",
        )
        if method is not None:
            positions = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: self._parse_okx_positions(
                    method({"instId": okx_inst_id_from_symbol(self.symbol)})
                ),
            )
        else:
            raise RuntimeError("OKX raw positions endpoint is unavailable")

        for pos in positions:
            if pos["contracts"] and pos["contracts"] != 0:
                side = pos["side"]
                if side == "short":
                    if not self.allow_short_selling:
                        logger.warning(
                            f"[账户查询] 检测到空单(禁止做空): 数量={abs(pos['contracts'])}, "
                            f"入场价={pos['entryPrice']}, 系统将自动平仓"
                        )
                        position_info = {
                            "symbol": self.symbol,
                            "side": "short_to_close",
                            "amount": abs(pos["contracts"]),
                            "entry_price": pos["entryPrice"],
                            "unrealized_pnl": pos.get("unrealizedPnl", 0),
                        }
                    else:
                        logger.info(
                            f"[账户查询] 检测到空单(允许做空): 数量={abs(pos['contracts'])}, "
                            f"入场价={pos['entryPrice']}, 正常持有"
                        )
                        position_info = {
                            "symbol": self.symbol,
                            "side": "short",
                            "amount": abs(pos["contracts"]),
                            "entry_price": pos["entryPrice"],
                            "unrealized_pnl": pos.get("unrealizedPnl", 0),
                        }
                else:
                    position_info = {
                        "symbol": self.symbol,
                        "side": "long",
                        "amount": abs(pos["contracts"]),
                        "entry_price": pos["entryPrice"],
                        "unrealized_pnl": pos.get("unrealizedPnl", 0),
                    }
                logger.info(
                    f"[账户查询] 找到持仓: 方向={position_info['side']}, "
                    f"数量={position_info['amount']}, "
                    f"入场价={position_info['entry_price']}, "
                    f"未实现盈亏={position_info['unrealized_pnl']}"
                )
                return position_info

        logger.debug(f"[账户查询] {self.symbol} 无持仓")
        return None

    def _parse_okx_positions(self, response: Dict[str, Any]) -> list:
        ensure_okx_success(response, "positions")
        positions = []
        for raw in response.get("data") or []:
            contracts = to_float(raw.get("pos"))
            if contracts == 0:
                continue
            raw_side = raw.get("posSide")
            side = raw_side if raw_side and raw_side != "net" else None
            if side is None:
                side = "short" if contracts < 0 else "long"
            positions.append(
                {
                    "symbol": self.symbol,
                    "side": side,
                    "contracts": contracts,
                    "entryPrice": to_float(raw.get("avgPx")),
                    "unrealizedPnl": to_float(raw.get("upl")),
                    "info": raw,
                }
            )
        return positions


def create_account_service(
    exchange, symbol: str, allow_short_selling: bool = True
) -> AccountService:
    """创建账户服务实例"""
    return AccountService(exchange, symbol, allow_short_selling)
