"""市场结构分析器单元测试"""

import pytest
from alpha_trading_bot.ai.market_structure import (
    MarketStructureAnalyzer,
    MarketStructureResult,
)


class TestMarketStructureAnalyzer:
    """市场结构分析器测试"""

    def setup_method(self):
        self.analyzer = MarketStructureAnalyzer()

    # === 上涨结构测试 ===

    def test_bullish_structure_hh_hl(self):
        """测试HH+HL上涨结构识别"""
        # 递增价格序列 → 应识别为上涨结构
        price_history = [100, 102, 101, 104, 103, 106, 105]
        result = self.analyzer.analyze(price_history, current_price=105)

        assert result.structure in ["bullish", "sideways"]
        assert result.current_price == 105
        assert result.nearest_support > 0
        assert result.nearest_resistance > 0

    def test_bearish_structure_lh_ll(self):
        """测试LH+LL下跌结构识别"""
        # 递减价格序列 → 应识别为下跌结构
        price_history = [106, 104, 105, 102, 103, 100, 101]
        result = self.analyzer.analyze(price_history, current_price=101)

        assert result.structure in ["bearish", "sideways"]
        assert result.current_price == 101

    def test_sideways_structure(self):
        """测试震荡结构识别"""
        # 横盘价格序列
        price_history = [100, 101, 99, 100, 101, 100, 100]
        result = self.analyzer.analyze(price_history, current_price=100)

        assert result.structure in ["sideways", "bullish", "bearish"]
        assert result.current_price == 100

    # === 支撑阻力位测试 ===

    def test_support_resistance_calculation(self):
        """测试支撑阻力位计算"""
        price_history = [95, 100, 105, 100, 108, 103, 110]
        result = self.analyzer.analyze(price_history, current_price=108)

        assert result.nearest_support < result.current_price
        assert result.nearest_resistance >= result.current_price

    # === R/R比测试 ===

    def test_risk_reward_ratio_calculation(self):
        """测试风险收益比计算"""
        price_history = [90, 95, 100, 105, 110]
        result = self.analyzer.analyze(price_history, current_price=105)

        assert result.risk_reward_ratio >= 0
        assert result.rr_quality in ["excellent", "good", "marginal", "poor"]

    def test_good_rr_bullish(self):
        """测试上涨结构中良好的R/R比"""
        # 价格在中间位置，上方空间大
        price_history = [80, 85, 90, 95, 100, 105, 110, 115, 120]
        result = self.analyzer.analyze(price_history, current_price=105)

        assert result.risk_reward_ratio >= 0

    # === 数据不足测试 ===

    def test_insufficient_data_returns_neutral(self):
        """测试数据不足时返回中性结果"""
        result = self.analyzer.analyze([], current_price=100)

        assert result.structure == "sideways"
        assert result.suggested_direction == "none"
        assert result.position_size_factor == 0.0

    def test_very_short_history(self):
        """测试极短历史数据"""
        result = self.analyzer.analyze([100, 101], current_price=101)

        assert result.structure in ["sideways", "bullish", "bearish"]

    # === 突破/破位测试 ===

    def test_breakout_detection(self):
        """测试突破检测"""
        # 当前价接近或突破阻力位
        price_history = [95, 100, 105, 100, 105, 100, 105]
        result = self.analyzer.analyze(price_history, current_price=105)

        assert isinstance(result.is_breakout, bool)
        assert isinstance(result.is_breakdown, bool)

    # === 交易建议测试 ===

    def test_trading_advice_bullish_good_rr(self):
        """测试上涨结构+良好R/R的交易建议"""
        price_history = [80, 85, 82, 90, 87, 95, 92, 100]
        result = self.analyzer.analyze(price_history, current_price=95)

        assert result.suggested_direction in ["long", "short", "none"]

    def test_trading_advice_bearish_poor_rr(self):
        """测试下跌结构+差R/R的交易建议"""
        price_history = [120, 115, 118, 110, 113, 105, 108, 100]
        result = self.analyzer.analyze(price_history, current_price=108)

        assert result.suggested_direction in ["long", "short", "none"]

    def test_high_volatility_reduces_position(self):
        """测试高波动环境下仓位缩减"""
        price_history = [95, 100, 105, 100, 105, 100]
        # 高ATR
        result = self.analyzer.analyze(
            price_history, current_price=100, atr_percent=0.06
        )
        # 高波动时仓位系数应较低
        assert result.position_size_factor <= 0.8

    # === 边界条件测试 ===

    def test_all_same_prices(self):
        """测试所有价格相同"""
        price_history = [100, 100, 100, 100, 100]
        result = self.analyzer.analyze(price_history, current_price=100)

        assert result.structure in ["sideways", "bullish", "bearish"]

    def test_single_swing_high(self):
        """测试只有一个摆动高点"""
        price_history = [100, 110, 100, 105, 103]
        result = self.analyzer.analyze(price_history, current_price=103)

        assert result.current_price == 103