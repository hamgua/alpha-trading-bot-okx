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
        self._last_valid_ticker: Dict[str, Any] = {}

    def validate_price_data(self, price: float, source: str = "unknown") -> bool:
        if price <= 0:
            logger.warning(f"无效价格数据: {price}, 来源: {source}")
            return False
        if price > 1000000:
            logger.warning(f"异常价格数据: {price}, 来源: {source}")
            return False
        return True

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
            if ticker and ticker.get("last", 0) > 0:
                self._last_valid_ticker = ticker
            return ticker
        except Exception as e:
            logger.error(f"获取ticker失败: {e}")
            return self._last_valid_ticker if self._last_valid_ticker else {}

    async def get_market_data(self) -> Dict[str, Any]:
        """获取市场数据 - 包含技术指标"""
        ticker = await self.get_ticker()
        current_price = ticker.get("last", 0) if ticker else 0

        if not self.validate_price_data(current_price, "ticker"):
            current_price = self._last_valid_ticker.get("last", 0)
            if not self.validate_price_data(current_price, "last_valid_ticker"):
                logger.warning("价格数据无效，使用 0")

        ohlcv = await self.get_ohlcv(limit=100)

        closes = [c[4] for c in ohlcv] if ohlcv else []
        highs = [c[2] for c in ohlcv] if ohlcv else []
        lows = [c[3] for c in ohlcv] if ohlcv else []

        from ..utils.technical import calculate_all_indicators

        technical_data = {}
        if len(closes) >= 50:
            technical_data = calculate_all_indicators(closes, highs, lows, closes)

        recent_drop = self._calculate_recent_drop(closes)
        short_term_drop = self._calculate_short_term_drop(closes)
        short_term_rise = self._calculate_short_term_rise(closes)
        hourly_changes = self._calculate_hourly_changes(closes)

        return {
            "symbol": self.symbol,
            "price": ticker.get("last", 0),
            "high": ticker.get("high", 0),
            "low": ticker.get("low", 0),
            "volume": ticker.get("baseVolume", 0),
            "change_percent": ticker.get("percentage", 0),
            "technical": technical_data,
            "recent_drop_percent": recent_drop,
            "short_term_drop_percent": short_term_drop,
            "short_term_rise_percent": short_term_rise,
            "price_history": closes,
            "hourly_changes": hourly_changes,
        }

    def _calculate_recent_drop(self, closes: List[float]) -> float:
        if len(closes) < 2:
            return 0.0

        recent_prices = closes[-2:]
        if len(recent_prices) >= 2:
            start_price = recent_prices[0]
            end_price = recent_prices[-1]
            if start_price > 0:
                drop_percent = (end_price - start_price) / start_price
                return drop_percent

        return 0.0

    def _calculate_short_term_drop(self, closes: List[float]) -> float:
        if len(closes) < 4:
            return 0.0

        start_price = closes[-4]
        end_price = closes[-1]

        if start_price > 0:
            drop_percent = (end_price - start_price) / start_price
            return drop_percent

        return 0.0

    def _calculate_short_term_rise(self, closes: List[float]) -> float:
        if len(closes) < 4:
            return 0.0

        start_price = closes[-4]
        end_price = closes[-1]

        if start_price > 0:
            rise_percent = (end_price - start_price) / start_price
            return rise_percent

        return 0.0

    def _calculate_hourly_changes(self, closes: List[float]) -> List[float]:
        if len(closes) < 2:
            return []
        changes = []
        for i in range(1, len(closes)):
            if closes[i - 1] > 0:
                change = (closes[i] - closes[i - 1]) / closes[i - 1]
                changes.append(change)
        return changes

    def calculate_1h_drop(self, ohlcv: List[List[float]]) -> float:
        if not ohlcv or len(ohlcv) < 2:
            return 0.0

        latest_candle = ohlcv[-1]
        open_price = latest_candle[1]
        close_price = latest_candle[4]

        if open_price > 0:
            return (close_price - open_price) / open_price

        return 0.0

    async def calculate_max_contracts(
        self, price: float, leverage: int, get_balance_func,
        max_position_usage: float = 0.30,
    ) -> float:
        """根据余额和杠杆计算最大可开合约数

        Args:
            price: 当前价格
            leverage: 杠杆倍数
            get_balance_func: 获取余额的异步函数
            max_position_usage: 最大使用余额比例 (默认30%)

        Returns:
            可开合约数量
        """
        try:
            balance = await get_balance_func()
            if balance <= 0:
                logger.warning("余额为0，无法开仓")
                return 0.0

            safe_balance = balance * max_position_usage
            max_contracts = (safe_balance * leverage) / price

            contracts = float(f"{max_contracts:.4f}")

            if contracts < 0.01:
                logger.warning(f"计算所得合约数 {contracts} 小于最小单位0.01，无法交易")
                return 0.0

            logger.info(
                f"最大可开合约数: {contracts} "
                f"(余额:{balance} USDT, 使用比例:{max_position_usage * 100:.0f}%, "
                f"杠杆:{leverage}x, 价格:{price})"
            )
            return contracts

        except Exception as e:
            logger.error(f"计算最大合约数失败: {e}")
            return 0.0


def create_market_data_service(exchange, symbol: str) -> MarketDataService:
    """创建市场数据服务实例"""
    return MarketDataService(exchange, symbol)
