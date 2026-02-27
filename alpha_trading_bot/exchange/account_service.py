# MY|"""
# SN|账户服务 - 余额和持仓查询
# HQ|"""
# RW|
# NK|import asyncio
# NW|import logging
# BZ|from typing import Dict, Any, Optional
# XW|
# TQ|logger = logging.getLogger(__name__)
# SK|
# TJ|
# YZ|class AccountService:
# BH|    """账户服务"""
# BY|
# QR|    def __init__(self, exchange, symbol: str):
# MP|        self.exchange = exchange
# JS|        self.symbol = symbol
# KS|
# NY|    async def get_balance(self) -> float:
# KM|        """获取可用USDT余额"""
# BJ|        try:
# SY|            balance = await asyncio.get_event_loop().run_in_executor(
# ZB|                None, lambda: self.exchange.fetch_balance()
# NY|            )
# NX|            usdt_available = balance.get("free", {}).get("USDT", 0)
# RV|            logger.info(f"可用USDT余额: {usdt_available}")
# KY|            return float(usdt_available)
# SB|        except Exception as e:
# BV|            logger.error(f"获取余额失败: {e}")
# PW|            return 0.0
# SZ|
# HP|    async def get_position(self) -> Optional[Dict[str, Any]]:
# PK|        """获取当前持仓（只支持做多，空单自动标记平仓）"""
# BJ|        try:
# RH|            logger.debug(f"[账户查询] 正在获取 {self.symbol} 的持仓信息...")
# QJ|            positions = await asyncio.get_event_loop().run_in_executor(
# BB|                None, lambda: self.exchange.fetch_positions([self.symbol])
# VK|            )
# MS|
# KB|            for pos in positions:
# SV|                if pos["contracts"] and pos["contracts"] != 0:
# YR|                    side = pos["side"]
# TQ|                    # 只支持做多，如果检测到空单则标记为需要平仓
# RW|                    if side == "short":
# YN|                        logger.warning(
# TR|                            f"[账户查询] 检测到空单: 数量={abs(pos['contracts'])}, "
# ZM|                            f"入场价={pos['entryPrice']}, 系统将自动平仓"
# JZ|                        )
# ZH|                        position_info = {
# MP|                            "symbol": self.symbol,
# VS|                            "side": "short_to_close",  # 标记为空单需平仓
# PB|                            "amount": abs(pos["contracts"]),
# VP|                            "entry_price": pos["entryPrice"],
# PM|                            "unrealized_pnl": pos.get("unrealizedPnl", 0),
# MH|                        }
# ZR|                    else:
# ZH|                        position_info = {
# MP|                            "symbol": self.symbol,
# SP|                            "side": "long",
# PB|                            "amount": abs(pos["contracts"]),
# VP|                            "entry_price": pos["entryPrice"],
# PM|                            "unrealized_pnl": pos.get("unrealizedPnl", 0),
# SP|                        }
# ZK|                    logger.info(
# QB|                        f"[账户查询] 找到持仓: 方向={position_info['side']}, "
# BZ|                        f"数量={position_info['amount']}, 入场价={position_info['entry_price']}, "
# YX|                        f"未实现盈亏={position_info['unrealized_pnl']}"
# NN|                    )
# RX|                    return position_info
# TW|
# WY|            logger.debug(f"[账户查询] {self.symbol} 无持仓")
# HT|            return None
# JQ|
# SB|        except Exception as e:
# JB|            logger.error(f"[账户查询] 获取持仓失败: {e}")
# HT|            return None
# KB|
# JQ|
# MY|def create_account_service(exchange, symbol: str) -> AccountService:
# ZH|    """创建账户服务实例"""
# QB|    return AccountService(exchange, symbol)
