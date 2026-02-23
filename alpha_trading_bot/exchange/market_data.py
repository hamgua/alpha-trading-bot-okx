"""
市场数据服务 - K线和技术指标
"""

import asyncio
import logging
from typing import Dict, Any, List

logger = logging.getLogger(__name__)


class MarketDataService:
    """市场数据服务"""

    def __init__(self, exchange, symbol: str):
        self.exchange = exchange
        self.symbol = symbol

    async def get_ohlcv(
        self, timeframe: str = "1h", limit: int = 100
    ) -> List[List[float]]:
        """获取K线数据"""
        try:
            ohlcv = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: self.exchange.fetch_ohlcv(self.symbol, timeframe, limit=limit),
            )
            return ohlcv
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return []

    async def get_ticker(self) -> Dict[str, Any]:
        """获取 ticker 数据"""
        try:
            ticker = await asyncio.get_event_loop().run_in_executor(
                None, lambda: self.exchange.fetch_ticker(self.symbol)
            )
            return ticker
        except Exception as e:
            logger.error(f"获取ticker失败: {e}")
            return {}

    async def get_market_data(self) -> Dict[str, Any]:
        """获取市场数据 - 包含技术指标"""
        ticker = await self.get_ticker()

        # 获取K线数据计算技术指标
        ohlcv = await self.get_ohlcv(limit=100)

        # 提取价格序列
        closes = [c[4] for c in ohlcv] if ohlcv else []
        highs = [c[2] for c in ohlcv] if ohlcv else []
        lows = [c[3] for c in ohlcv] if ohlcv else []

        # 计算技术指标
        from ..utils.technical import calculate_all_indicators

        technical_data = {}
        if len(closes) >= 50:
            technical_data = calculate_all_indicators(closes, highs, lows, closes)

        # 计算1小时跌幅
        recent_drop = self._calculate_recent_drop(closes)

        return {
            "symbol": self.symbol,
            "price": ticker.get("last", 0),
            "high": ticker.get("high", 0),
            "low": ticker.get("low", 0),
            "volume": ticker.get("baseVolume", 0),
            "change_percent": ticker.get("percentage", 0),
            "technical": technical_data,
            "recent_drop_percent": recent_drop,
        }

    def _calculate_recent_drop(self, closes: List[float]) -> float:
        """
        计算近期跌幅（1小时内）

        Args:
            closes: 收盘价列表（最新在最后）

        Returns:
            跌幅比例（负数表示下跌），0表示无法计算
        """
        if len(closes) < 2:
            return 0.0

        # 取最近1小时的数据（1小时周期 = 1根K线）
        # 取最近2根K线计算跌幅
        recent_prices = closes[-2:]
        if len(recent_prices) >= 2:
            start_price = recent_prices[0]
            end_price = recent_prices[-1]
            if start_price > 0:
                drop_percent = (end_price - start_price) / start_price
                return drop_percent

        return 0.0

    def calculate_1h_drop(self, ohlcv: List[List[float]]) -> float:
        """
        计算1小时跌幅

        Args:
            ohlcv: K线数据

        Returns:
            跌幅比例（负数表示下跌）
        """
        if not ohlcv or len(ohlcv) < 2:
            return 0.0

        # 最新K线的开盘价 vs 当前价格
        latest_candle = ohlcv[-1]
        open_price = latest_candle[1]
        close_price = latest_candle[4]

        if open_price > 0:
            return (close_price - open_price) / open_price

        return 0.0

    async def calculate_max_contracts(
        self, price: float, leverage: int, get_balance_func
    ) -> float:
        """
        根据余额和杠杆计算最大可开合约数

        Args:
            price: 当前价格
            leverage: 杠杆倍数
            get_balance_func: 获取余额的函数
        """
        try:
            balance = await get_balance_func()
            if balance <= 0:
                logger.warning("余额为0，无法开仓")
                return 0.0

            # OKX永续合约: BTC/USDT:USDT 最小交易单位为 0.001 张
            # 计算公式: 合约数 = (余额 * 杠杆) / 价格
            # 保留5%缓冲避免爆仓
            safe_balance = balance * 0.95
            max_contracts = (safe_balance * leverage) / price

            # 保留4位小数精度，确保小于0.001的数不会被错误地四舍五入为0
            contracts = float(f"{max_contracts:.4f}")

            # 确保不低于最小交易单位
            if contracts < 0.001:
                logger.warning(f"计算所得合约数 {contracts} 小于最小单位0.001")
                return 0.0

            logger.info(
                f"最大可开合约数: {contracts} (余额:{balance} USDT, 杠杆:{leverage}x, 价格:{price})"
            )
            return contracts

        except Exception as e:
            logger.error(f"计算最大合约数失败: {e}")
            return 0.0


def create_market_data_service(exchange, symbol: str) -> MarketDataService:
    """创建市场数据服务实例"""
    return MarketDataService(exchange, symbol)
