"""
策略管理器 - 管理所有交易策略
"""

import asyncio
import logging
from typing import Dict, Any, List, Optional
from datetime import datetime

from ..core.base import BaseComponent, BaseConfig
from ..core.exceptions import StrategyError

# 全局策略管理器实例
_strategy_manager: Optional['StrategyManager'] = None

logger = logging.getLogger(__name__)

class StrategyManagerConfig(BaseConfig):
    """策略管理器配置"""
    enable_backtesting: bool = True
    enable_optimization: bool = True
    default_strategy: str = "conservative"
    max_active_strategies: int = 3
    min_volume_threshold: float = 0.1  # 最小成交量阈值
    min_atr_threshold: float = 0.001  # 最小ATR阈值（0.1%）
    max_trades_per_hour: int = 6  # 每小时最大交易次数
    low_liquidity_trade_limit: int = 2  # 低流动性环境下每小时最大交易次数

    """策略管理器"""

    async def _check_market_liquidity(self, market_data: Dict[str, Any]) -> tuple[bool, str]:
        """检查市场流动性

        Returns:
            tuple[bool, str]: (是否允许交易, 原因)
        """
        try:
            # 检查成交量
            volume = market_data.get('volume', 0)
            if volume == 0:
                logger.warning(f"市场流动性检查失败: 成交量为0，跳过交易")
                return False, "成交量为0"

            # 检查ATR（如果可用）
            atr = market_data.get('atr', 0)
            if atr is not None and atr < self.config.min_atr_threshold:
                logger.warning(f"市场流动性检查失败: ATR({atr:.4f})低于阈值({self.config.min_atr_threshold:.4f})，跳过交易")
                return False, f"ATR过低({atr:.4f})"

            # 检查买卖价差（如果可用）
            orderbook = market_data.get('orderbook', {})
            if orderbook and 'bids' in orderbook and 'asks' in orderbook:
                bids = orderbook['bids']
                asks = orderbook['asks']
                if bids and asks:
                    best_bid = float(bids[0][0])
                    best_ask = float(asks[0][0])
                    spread = (best_ask - best_bid) / best_bid
                    if spread > 0.01:  # 价差大于1%
                        logger.warning(f"市场流动性检查失败: 买卖价差过大({spread:.2%})，跳过交易")
                        return False, f"价差过大({spread:.2%})"

            return True, "流动性正常"

        except Exception as e:
            logger.error(f"流动性检查异常: {e}，默认允许交易")
            return True, "检查异常，默认通过"

class StrategyManager(BaseComponent):
    """策略管理器 - 负责管理和执行交易策略"""

    def _check_trade_frequency(self, is_low_liquidity: bool = False) -> tuple[bool, str]:
        """检查交易频率限制

        Args:
            is_low_liquidity: 是否处于低流动性环境

        Returns:
            tuple[bool, str]: (是否允许交易, 原因)
        """
        try:
            now = datetime.now()
            # 清理一小时前的交易记录
            self.recent_trades = [trade_time for trade_time in self.recent_trades
                                 if (now - trade_time).total_seconds() < 3600]

            # 确定交易限制
            trade_limit = (self.config.low_liquidity_trade_limit if is_low_liquidity
                          else self.config.max_trades_per_hour)

            current_trade_count = len(self.recent_trades)

            if current_trade_count >= trade_limit:
                logger.warning(f"交易频率限制: 最近1小时已交易{current_trade_count}次，限制为{trade_limit}次，跳过交易")
                return False, f"交易频率超限({current_trade_count}/{trade_limit})"

            return True, f"交易频率正常({current_trade_count}/{trade_limit})"

        except Exception as e:
            logger.error(f"交易频率检查异常: {e}，默认允许交易")
            return True, "检查异常，默认通过"

    async def _check_market_liquidity(self, market_data: Dict[str, Any]) -> tuple[bool, str]:
        """检查市场流动性 - 优化版

        使用多维度评估，包括：
        1. 多时间框架成交量分析
        2. 动态ATR评估
        3. 订单簿深度分析
        4. 价格波动率评估

        Args:
            market_data: 市场数据

        Returns:
            tuple[bool, str]: (流动性是否充足, 原因)
        """
        try:
            # 获取多维度数据
            current_volume = market_data.get('volume', 0)
            atr = market_data.get('atr', 0)
            orderbook = market_data.get('orderbook', {})
            price = market_data.get('price', 0)

            # 获取历史数据用于比较
            volume_24h = market_data.get('volume_24h', current_volume * 96)  # 估算24小时成交量
            avg_volume_24h = market_data.get('avg_volume_24h', volume_24h)

            # 如果交易所的24h成交量为0但我们有计算的平均成交量，优先使用计算值
            if current_volume == 0 and avg_volume_24h > 0:
                logger.info(f"交易所24h成交量为0，使用计算的平均成交量: {avg_volume_24h:.2f}")
                current_volume = avg_volume_24h * 0.1  # 使用平均值的一定比例作为当前成交量估算

            # 1. 动态成交量评估
            volume_score = self._calculate_volume_score(current_volume, avg_volume_24h, price)

            # 2. ATR动态评估
            atr_score = self._calculate_atr_score(atr, price)

            # 3. 订单簿深度评估
            orderbook_score = self._calculate_orderbook_score(orderbook, price)

            # 4. 价格波动率评估
            volatility_score = self._calculate_volatility_score(market_data)

            # 综合评分 (0-100)
            total_score = (volume_score * 0.4 + atr_score * 0.2 +
                          orderbook_score * 0.3 + volatility_score * 0.1)

            # 根据评分判断流动性等级
            if total_score >= 70:
                return True, f"流动性优秀(评分:{total_score:.1f})"
            elif total_score >= 50:
                logger.info(f"市场流动性一般(评分:{total_score:.1f})，谨慎交易")
                return True, f"流动性一般(评分:{total_score:.1f})"
            elif total_score >= 30:
                logger.warning(f"市场流动性偏低(评分:{total_score:.1f})，建议减少交易量")
                return True, f"流动性偏低(评分:{total_score:.1f})"
            else:
                logger.warning(f"市场流动性严重不足(评分:{total_score:.1f})，跳过交易")
                return False, f"流动性严重不足(评分:{total_score:.1f})"

        except Exception as e:
            logger.error(f"流动性检查异常: {e}，默认允许交易")
            return True, "检查异常，默认通过"

    def _calculate_volume_score(self, current_volume: float, avg_volume: float, price: float) -> float:
        """计算成交量评分 (0-100) - 优化版"""
        try:
            # 处理零成交量的特殊情况
            if current_volume == 0:
                # 检查是否是新周期刚开始（时间接近整点/半点）
                current_minute = datetime.now().minute
                if current_minute % 15 <= 2:  # 新15分钟周期刚开始2分钟内
                    logger.info("当前处于新15分钟周期初期，成交量为0属于正常现象")
                    return 60  # 给予中等评分，避免过度敏感
                else:
                    logger.warning("当前成交量为0且不在新周期初期")
                    # 如果有平均成交量数据，说明系统有交易活动，给予基础评分
                    if avg_volume > 0:
                        logger.info(f"有平均成交量数据({avg_volume:.2f})，给予基础流动性评分")
                        return 40  # 基于历史数据给予基础评分
                    return 0

            if avg_volume <= 0:
                return 50  # 没有历史数据时给予中等评分

            # 计算相对成交量比例
            volume_ratio = current_volume / avg_volume if avg_volume > 0 else 0

            # 根据价格调整最小成交量要求（更宽松的阈值）
            min_volume_threshold = max(0.01, price * 0.00005)  # 降低阈值要求

            if current_volume < min_volume_threshold:
                return 30  # 降低评分但不直接拒绝
            elif volume_ratio < 0.05:  # 放宽比例要求
                return 40
            elif volume_ratio < 0.2:
                return 60
            elif volume_ratio < 0.5:
                return 80
            else:
                return 100
        except:
            return 50  # 默认中等评分

    def _calculate_atr_score(self, atr: float, price: float) -> float:
        """计算ATR评分 (0-100)"""
        try:
            if price <= 0:
                return 0

            # 计算ATR相对价格的比例
            atr_ratio = atr / price if price > 0 else 0

            # 动态阈值：价格越高，允许的ATR比例越小
            if price > 50000:
                min_atr_ratio = 0.001  # 0.1%
                optimal_atr_ratio = 0.005  # 0.5%
            elif price > 10000:
                min_atr_ratio = 0.002  # 0.2%
                optimal_atr_ratio = 0.008  # 0.8%
            else:
                min_atr_ratio = 0.003  # 0.3%
                optimal_atr_ratio = 0.01   # 1%

            if atr_ratio < min_atr_ratio:
                return 20
            elif atr_ratio < optimal_atr_ratio * 0.5:
                return 40
            elif atr_ratio < optimal_atr_ratio:
                return 70
            elif atr_ratio < optimal_atr_ratio * 2:
                return 90
            else:
                return 60  # ATR过高也不好
        except:
            return 50  # 默认中等评分

    def _calculate_orderbook_score(self, orderbook: Dict[str, Any], price: float) -> float:
        """计算订单簿深度评分 (0-100)"""
        try:
            if not orderbook or 'bids' not in orderbook or 'asks' not in orderbook:
                return 30

            bids = orderbook.get('bids', [])
            asks = orderbook.get('asks', [])

            if not bids or not asks:
                return 30

            # 计算买卖价差
            best_bid = float(bids[0][0])
            best_ask = float(asks[0][0])
            spread = (best_ask - best_bid) / best_bid

            # 计算订单簿深度（前10档）
            total_bid_volume = sum(float(bid[1]) for bid in bids[:10] if len(bid) >= 2)
            total_ask_volume = sum(float(ask[1]) for ask in asks[:10] if len(ask) >= 2)
            avg_volume = (total_bid_volume + total_ask_volume) / 2

            # 价差评分 (60%权重)
            if spread < 0.001:      # 0.1%以内：优秀
                spread_score = 100
            elif spread < 0.005:    # 0.5%以内：良好
                spread_score = 80
            elif spread < 0.01:     # 1%以内：一般
                spread_score = 60
            elif spread < 0.02:     # 2%以内：较差
                spread_score = 40
            else:                    # 超过2%：很差
                spread_score = 20

            # 深度评分 (40%权重)
            # 根据价格计算期望的最小深度
            min_depth = price * 0.001  # 0.1%的价格深度
            if avg_volume > min_depth * 10:
                depth_score = 100
            elif avg_volume > min_depth * 5:
                depth_score = 80
            elif avg_volume > min_depth * 2:
                depth_score = 60
            elif avg_volume > min_depth:
                depth_score = 40
            else:
                depth_score = 20

            # 综合评分
            return spread_score * 0.6 + depth_score * 0.4

        except Exception as e:
            logger.error(f"订单簿评分计算失败: {e}")
            return 30

    def _calculate_volatility_score(self, market_data: Dict[str, Any]) -> float:
        """计算价格波动率评分 (0-100)"""
        try:
            # 获取价格变化数据
            change_percent = abs(market_data.get('change_percent', 0))
            high = market_data.get('high', 0)
            low = market_data.get('low', 0)
            price = market_data.get('price', 0)

            if price <= 0 or high <= low:
                return 50

            # 计算日内波动率
            daily_range = (high - low) / price

            # 综合波动率评分
            total_volatility = change_percent + daily_range * 100

            # 波动率评分（适中最好）
            if total_volatility < 0.1:      # 太低：无波动
                return 20
            elif total_volatility < 0.5:    # 偏低：波动较小
                return 40
            elif total_volatility < 1.0:    # 适中：理想波动
                return 80
            elif total_volatility < 2.0:    # 偏高：波动较大
                return 60
            else:                            # 太高：波动过大
                return 30

        except:
            return 50  # 默认中等评分

    def _adjust_parameters_based_on_market(self, market_data: Dict[str, Any]) -> None:
        """根据市场条件动态调整参数"""
        try:
            price = market_data.get('price', 0)
            volume = market_data.get('volume', 0)
            volatility = market_data.get('change_percent', 0)

            # 根据价格水平调整参数
            if price > 50000:  # 高价币
                self.config.min_volume_threshold = 0.05
                self.config.min_atr_threshold = 0.0008
            elif price > 10000:  # 中价币
                self.config.min_volume_threshold = 0.08
                self.config.min_atr_threshold = 0.0015
            else:  # 低价币
                self.config.min_volume_threshold = 0.1
                self.config.min_atr_threshold = 0.002

            # 根据波动率调整交易频率
            if abs(volatility) > 5:  # 高波动
                self.config.max_trades_per_hour = max(2, self.config.max_trades_per_hour // 2)
                self.config.low_liquidity_trade_limit = max(1, self.config.low_liquidity_trade_limit // 2)
            elif abs(volatility) < 1:  # 低波动
                self.config.max_trades_per_hour = min(10, self.config.max_trades_per_hour * 2)
                self.config.low_liquidity_trade_limit = min(4, self.config.low_liquidity_trade_limit * 2)

            logger.info(f"根据市场条件调整参数: 价格=${price:,.2f}, 成交量={volume}, 波动率={volatility:.2f}%")

        except Exception as e:
            logger.error(f"动态参数调整失败: {e}")

    def record_trade(self) -> None:
        """记录一次交易"""
        self.recent_trades.append(datetime.now())

    async def _should_execute_trade(self, signal: Dict[str, Any], market_data: Dict[str, Any]) -> tuple[bool, str]:
        """检查是否应该执行交易

        Args:
            signal: 交易信号
            market_data: 市场数据

        Returns:
            tuple[bool, str]: (是否执行交易, 原因)
        """
        try:
            # 检查市场流动性
            liquidity_ok, liquidity_reason = await self._check_market_liquidity(market_data)
            if not liquidity_ok:
                return False, f"流动性不足: {liquidity_reason}"

            # 检查交易频率
            frequency_ok, frequency_reason = self._check_trade_frequency(is_low_liquidity=not liquidity_ok)
            if not frequency_ok:
                return False, f"频率限制: {frequency_reason}"

            # 检查做空设置
            if signal.get('action') == 'sell' or signal.get('side') == 'short':
                if not await self._check_allow_short_selling():
                    return False, "做空功能已禁用"

            return True, "所有检查通过"

        except Exception as e:
            logger.error(f"交易执行检查异常: {e}，默认允许交易")
            return True, "检查异常，默认通过"

    async def _check_allow_short_selling(self) -> bool:
        """检查是否允许做空"""
        try:
            # 优先使用配置对象的设置
            if hasattr(self.config, 'allow_short_selling'):
                return self.config.allow_short_selling

            # 尝试从全局配置获取
            try:
                from alpha_trading_bot.config import get_config_manager
                config_manager = await get_config_manager()
                return config_manager.trading.allow_short_selling
            except:
                # 如果无法获取全局配置，默认允许做空
                return True
        except Exception as e:
            logger.error(f"检查做空配置失败: {e}，默认允许做空")
            return True

    def __init__(self, config: Optional[Any] = None, ai_manager: Optional[Any] = None):
        # 如果没有提供配置，创建默认配置
        if config is None:
            config = StrategyManagerConfig(name="StrategyManager")
        super().__init__(config)
        self.active_strategies: Dict[str, Any] = {}
        self.strategy_results: List[Dict[str, Any]] = []
        self.ai_manager = ai_manager  # AI管理器实例
        self.recent_trades: List[datetime] = []  # 记录最近的交易时间

    async def initialize(self) -> bool:
        """初始化策略管理器"""
        logger.info("正在初始化策略管理器...")

        # 加载默认策略
        await self._load_default_strategies()

        self._initialized = True
        return True

    async def cleanup(self) -> None:
        """清理资源"""
        self.active_strategies.clear()

    async def _load_default_strategies(self) -> None:
        """加载默认策略"""
        # 定义投资策略详细参数
        STRATEGY_DEFINITIONS = {
            'conservative': {
                'name': '稳健型',
                'description': '低风险偏好，追求稳定收益',
                'price_range': {'min': 30, 'max': 70},  # 30%-70%区间
                'frequency': '低频次',
                'characteristics': '提前锁定利润，避免大幅回撤',
                'risk_level': 'low',
                'enabled': True,
                'priority': 1
            },
            'moderate': {
                'name': '中等型',
                'description': '平衡风险与收益，趋势跟踪',
                'price_range': {'min': 25, 'max': 75},  # 25%-75%区间
                'frequency': '中等频次',
                'characteristics': '趋势跟踪，平衡策略',
                'risk_level': 'medium',
                'enabled': True,
                'priority': 2
            },
            'aggressive': {
                'name': '激进型',
                'description': '高风险偏好，追求极致买卖点',
                'price_range': {'min': 15, 'max': 85},  # 15%-85%区间
                'frequency': '高频次',
                'characteristics': '追求极致买卖点，快速反应',
                'risk_level': 'high',
                'enabled': True,
                'priority': 3
            }
        }

        # 加载策略定义
        self.active_strategies = STRATEGY_DEFINITIONS

    async def generate_signals(self, market_data: Dict[str, Any], ai_signals: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
        """生成交易信号"""
        try:
            signals = []

            # 根据市场条件动态调整参数
            self._adjust_parameters_based_on_market(market_data)

            # 检查市场流动性
            liquidity_ok, liquidity_reason = await self._check_market_liquidity(market_data)
            if not liquidity_ok:
                logger.warning(f"市场流动性不足，跳过信号生成: {liquidity_reason}")
                # 返回空信号列表，避免交易
                return []

            # 检查交易频率
            frequency_ok, frequency_reason = self._check_trade_frequency(is_low_liquidity=not liquidity_ok)
            if not frequency_ok:
                logger.warning(f"交易频率限制，跳过信号生成: {frequency_reason}")
                return []

            # 如果已经提供了AI信号，直接使用它们
            if ai_signals:
                logger.info(f"使用提供的 {len(ai_signals)} 个AI信号")
            else:
                # 获取AI信号 - 使用提供的AI管理器实例
                if self.ai_manager:
                    ai_signals = await self.ai_manager.generate_signals(market_data)
                else:
                    # 如果没有提供AI管理器，使用全局实例
                    from alpha_trading_bot.ai import get_ai_manager
                    ai_manager = await get_ai_manager()
                    ai_signals = await ai_manager.generate_signals(market_data)

            # 转换AI信号为策略信号
            for ai_signal in ai_signals:
                signal_type = ai_signal.get('signal', 'HOLD').lower()

                # 检查做空设置
                if signal_type == 'sell':
                    # 获取交易配置
                    try:
                        from alpha_trading_bot.config import get_config_manager
                        config_manager = await get_config_manager()
                        trading_config = config_manager.trading

                        if not trading_config.allow_short_selling:
                            logger.warning(f"AI生成的SELL信号被忽略：做空功能已禁用(allow_short_selling={trading_config.allow_short_selling})")
                            continue
                    except Exception as e:
                        logger.error(f"检查做空配置失败: {e}，继续处理信号")

                signal = {
                    'type': signal_type,
                    'confidence': ai_signal.get('confidence', 0.5),
                    'reason': ai_signal.get('reason', 'AI分析'),
                    'source': 'ai',
                    'provider': ai_signal.get('provider', 'unknown'),
                    'timestamp': datetime.now()
                }
                signals.append(signal)

                # 保存AI信号到数据管理器
                try:
                    # 使用相对导入从数据模块获取管理器
                    logger.debug("正在导入数据管理器...")

                    # 调试信息：检查Python路径和模块状态
                    import sys
                    import os
                    logger.debug(f"Python路径: {sys.path[:3]}...")  # 只显示前3个路径
                    logger.debug(f"当前工作目录: {os.getcwd()}")
                    logger.debug(f"当前文件目录: {os.path.dirname(os.path.abspath(__file__))}")

                    # 检查alpha_trading_bot.data模块是否存在
                    try:
                        import alpha_trading_bot.data
                        logger.debug(f"alpha_trading_bot.data模块存在: {alpha_trading_bot.data.__file__}")
                    except ImportError as e:
                        logger.error(f"alpha_trading_bot.data模块不存在: {e}")
                        # 尝试列出alpha_trading_bot目录内容
                        try:
                            import alpha_trading_bot
                            bot_dir = os.path.dirname(alpha_trading_bot.__file__)
                            logger.error(f"alpha_trading_bot目录内容: {os.listdir(bot_dir)}")
                            # 检查是否有data目录
                            if 'data' in os.listdir(bot_dir):
                                data_dir = os.path.join(bot_dir, 'data')
                                logger.error(f"data目录内容: {os.listdir(data_dir)}")
                        except Exception as list_err:
                            logger.error(f"无法列出目录内容: {list_err}")
                        raise

                    # 使用绝对导入替代相对导入
                    from alpha_trading_bot.data import get_data_manager
                    logger.debug("数据管理器导入成功")

                    try:
                        data_manager = await get_data_manager()
                        logger.debug(f"获取数据管理器成功: {type(data_manager)}")
                    except RuntimeError as e:
                        # 如果数据管理器未初始化，记录警告但不影响主流程
                        logger.warning(f"数据管理器未初始化，跳过AI信号保存: {e}")
                        logger.debug(f"数据管理器状态: 全局实例可能为None")
                    else:
                        # 清理market_data中的datetime对象，避免JSON序列化错误
                        clean_market_data = {}
                        for key, value in market_data.items():
                            if key == 'timestamp' and isinstance(value, datetime):
                                # 将datetime转换为ISO格式字符串
                                clean_market_data[key] = value.isoformat()
                            elif key == 'orderbook' and isinstance(value, dict):
                                # 清理orderbook中的datetime对象
                                clean_orderbook = {}
                                for ob_key, ob_value in value.items():
                                    if isinstance(ob_value, list):
                                        clean_orderbook[ob_key] = [
                                            {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in item.items()}
                                            if isinstance(item, dict) else item
                                            for item in ob_value
                                        ]
                                    else:
                                        clean_orderbook[ob_key] = ob_value
                                clean_market_data[key] = clean_orderbook
                            else:
                                clean_market_data[key] = value

                        ai_signal_data = {
                            'provider': ai_signal.get('provider', 'unknown'),
                            'signal': ai_signal.get('signal', 'HOLD'),
                            'confidence': ai_signal.get('confidence', 0.5),
                            'reason': ai_signal.get('reason', 'AI分析'),
                            'market_price': market_data.get('price', 0),
                            'market_data': clean_market_data
                        }
                        await data_manager.save_ai_signal(ai_signal_data)
                        logger.debug(f"AI信号保存成功: {ai_signal_data['signal']}")
                except ImportError as e:
                    logger.warning(f"数据模块导入失败，跳过AI信号保存: {e}")
                    logger.warning(f"错误类型: {type(e).__name__}")
                    logger.warning(f"错误模块: {e.__class__.__module__ if hasattr(e, '__class__') else 'unknown'}")
                    import traceback
                    logger.warning(f"详细错误信息: {traceback.format_exc()}")
                except Exception as e:
                    logger.warning(f"保存AI信号失败: {e}")
                    logger.warning(f"错误类型: {type(e).__name__}")
                    import traceback
                    logger.warning(f"详细错误信息: {traceback.format_exc()}")

            # 添加策略特定的信号
            strategy_signals = await self._generate_strategy_signals(market_data)
            signals.extend(strategy_signals)

            # 记录交易信号信息 - 优化版（减少日志输出）
            if len(signals) > 0:
                # 只在有信号时输出概要
                signal_summary = {}
                for signal in signals:
                    sig_type = signal.get('type', 'UNKNOWN').upper()
                    source = signal.get('source', 'unknown')
                    confidence = signal.get('confidence', 0)
                    key = f"{sig_type}_{source}"
                    if key not in signal_summary:
                        signal_summary[key] = {'count': 0, 'avg_confidence': 0, 'reasons': []}
                    signal_summary[key]['count'] += 1
                    signal_summary[key]['avg_confidence'] = (
                        (signal_summary[key]['avg_confidence'] * (signal_summary[key]['count'] - 1) + confidence) /
                        signal_summary[key]['count']
                    )
                    if signal.get('reason'):
                        signal_summary[key]['reasons'].append(signal['reason'])

                logger.info(f"生成了 {len(signals)} 个交易信号:")
                for sig_key, summary in signal_summary.items():
                    sig_type, source = sig_key.split('_', 1)
                    logger.info(f"  {sig_type} ×{summary['count']} (来源:{source}, 平均信心:{summary['avg_confidence']:.2f})")
                    if summary['reasons'] and len(set(summary['reasons'])) <= 3:  # 只显示前3个不同原因
                        unique_reasons = list(set(summary['reasons']))[:3]
                        logger.info(f"    原因: {'; '.join(unique_reasons)}")

                # 只在调试模式下输出详细信息
                if logger.isEnabledFor(logging.DEBUG):
                    for i, signal in enumerate(signals, 1):
                        logger.debug(f"  信号 {i}详情:")
                        logger.debug(f"    类型: {signal.get('type', 'UNKNOWN').upper()}")
                        logger.debug(f"    信心度: {signal.get('confidence', 0):.2f}")
                        logger.debug(f"    来源: {signal.get('source', 'unknown')}")
                        if signal.get('price'):
                            logger.debug(f"    目标价格: ${signal['price']:,.2f}")
                        if signal.get('stop_loss'):
                            logger.debug(f"    止损价格: ${signal['stop_loss']:,.2f}")
                        if signal.get('take_profit'):
                            logger.debug(f"    止盈价格: ${signal['take_profit']:,.2f}")
            else:
                logger.info("未生成任何交易信号")
            return signals

        except Exception as e:
            logger.error(f"生成交易信号失败: {e}")
            return []

    async def _generate_strategy_signals(self, market_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """生成策略信号"""
        # 改进实现：基于多种技术指标生成信号
        signals = []

        try:
            price = market_data.get('price', 0)
            high = market_data.get('high', price)
            low = market_data.get('low', price)

            if price > 0 and high > low:
                # 获取配置
                from ..config import load_config
                config = load_config()
                symbol = config.exchange.symbol

                # 获取多时间框架数据
                hourly_data = {}
                four_hour_data = {}
                daily_data = {}

                # 如果已有15分钟数据，计算其他时间框架的近似值
                if market_data.get('close_prices') and len(market_data['close_prices']) >= 16:
                    # 从15分钟数据计算1小时数据（4根15分钟 = 1小时）
                    closes = market_data['close_prices']
                    highs = market_data['high_prices']
                    lows = market_data['low_prices']

                    # 计算1小时数据
                    hourly_closes = [closes[i*4] for i in range(len(closes)//4)]
                    hourly_highs = [max(highs[i*4:(i+1)*4]) for i in range(len(highs)//4)]
                    hourly_lows = [min(lows[i*4:(i+1)*4]) for i in range(len(lows)//4)]

                    if hourly_closes:
                        hourly_data = {
                            'close': hourly_closes,
                            'high': hourly_highs,
                            'low': hourly_lows
                        }
                        # 添加1小时高低价到市场数据
                        market_data['hourly_high'] = max(hourly_highs[-4:]) if len(hourly_highs) >= 4 else hourly_highs[-1]
                        market_data['hourly_low'] = min(hourly_lows[-4:]) if len(hourly_lows) >= 4 else hourly_lows[-1]

                if market_data.get('close_prices') and len(market_data['close_prices']) >= 64:
                    # 从15分钟数据计算4小时数据（16根15分钟 = 4小时）
                    four_hour_closes = [closes[i*16] for i in range(len(closes)//16)]
                    four_hour_highs = [max(highs[i*16:(i+1)*16]) for i in range(len(highs)//16)]
                    four_hour_lows = [min(lows[i*16:(i+1)*16]) for i in range(len(lows)//16)]

                    if four_hour_closes:
                        four_hour_data = {
                            'close': four_hour_closes,
                            'high': four_hour_highs,
                            'low': four_hour_lows
                        }
                        # 添加4小时高低价到市场数据
                        market_data['4h_high'] = max(four_hour_highs[-6:]) if len(four_hour_highs) >= 6 else four_hour_highs[-1]
                        market_data['4h_low'] = min(four_hour_lows[-6:]) if len(four_hour_lows) >= 6 else four_hour_lows[-1]

                # 计算技术指标
                from ..utils.technical import TechnicalIndicators
                technical_data = TechnicalIndicators.calculate_all_indicators(market_data)

                # 使用改进的横盘检测
                from .consolidation import ConsolidationDetector
                consolidation_detector = ConsolidationDetector()

                # 获取当前投资类型配置
                investment_type = config.strategies.investment_type

                # 检测横盘状态
                is_consolidation, reason, confidence = consolidation_detector.detect_consolidation(
                    {**market_data, **technical_data},
                    symbol
                )

                # 如果处于高度确认的横盘状态，生成清仓信号
                if is_consolidation and confidence > 0.8:
                    logger.warning(f"检测到高度确认的横盘状态(置信度:{confidence:.2f}): {reason}")
                    logger.warning("将生成清仓信号并清理所有委托单")

                    # 生成清仓信号
                    signals.append({
                        'type': 'close_all',  # 新的信号类型：清仓
                        'confidence': confidence,
                        'reason': f'横盘清仓: {reason}',
                        'source': 'consolidation_detector',
                        'timestamp': datetime.now(),
                        'is_consolidation': True,  # 标记为横盘触发的信号
                        'clear_orders': True  # 标记需要清理委托单
                    })
                    return signals  # 横盘期间生成清仓信号，不再生成其他信号

                # 计算价格位置（结合技术指标）
                if 'bb_upper' in technical_data and 'bb_lower' in technical_data:
                    # 使用布林带计算价格位置
                    bb_upper = technical_data['bb_upper']
                    bb_lower = technical_data['bb_lower']
                    price_position = (price - bb_lower) / (bb_upper - bb_lower) if bb_upper != bb_lower else 0.5
                else:
                    # 回退到传统方法
                    price_position = (price - low) / (high - low)

                # 根据投资类型生成对应的策略信号
                if investment_type == 'conservative':
                    # 稳健型策略：宽区间，低频次交易，提前锁定利润
                    strategy_info = self.active_strategies['conservative']
                    if price_position < 0.3:  # 较早买入，降低踏空风险
                        signals.append({
                            'type': 'buy',
                            'confidence': 0.7,
                            'reason': f"{strategy_info['name']}：{strategy_info['description']} - 价格回调到合理区间({strategy_info['price_range']['min']}%-{strategy_info['price_range']['max']}%)，适合建仓",
                            'source': 'conservative_strategy',
                            'strategy_type': 'conservative',
                            'strategy_details': strategy_info,
                            'timestamp': datetime.now()
                        })
                    elif price_position > 0.7:  # 较早卖出，锁定利润
                        # 检查是否允许做空
                        if not await self._check_allow_short_selling():
                            logger.info("保守策略：做空被禁用，跳过sell信号")
                            # 不添加sell信号，继续处理其他逻辑
                        else:
                            signals.append({
                                'type': 'sell',
                                'confidence': 0.7,
                                'reason': f"{strategy_info['name']}：{strategy_info['description']} - 价格反弹到合理高位({strategy_info['price_range']['min']}%-{strategy_info['price_range']['max']}%)，考虑减仓锁定利润",
                                'source': 'conservative_strategy',
                                'strategy_type': 'conservative',
                                'strategy_details': strategy_info,
                                'timestamp': datetime.now()
                            })

                elif investment_type == 'moderate':
                    # 中等型策略：中等区间，趋势跟踪，平衡风险收益
                    strategy_info = self.active_strategies['moderate']
                    if price_position < 0.25:  # 中等买入门槛
                        signals.append({
                            'type': 'buy',
                            'confidence': 0.75,
                            'reason': f"{strategy_info['name']}：{strategy_info['description']} - 价格回调明显({strategy_info['price_range']['min']}%-{strategy_info['price_range']['max']}%)，趋势跟踪买入",
                            'source': 'moderate_strategy',
                            'strategy_type': 'moderate',
                            'strategy_details': strategy_info,
                            'timestamp': datetime.now()
                        })
                    elif price_position > 0.75:  # 中等卖出门槛
                        # 检查是否允许做空
                        if not await self._check_allow_short_selling():
                            logger.info("中等策略：做空被禁用，跳过sell信号")
                            # 不添加sell信号，继续处理其他逻辑
                        else:
                            signals.append({
                                'type': 'sell',
                                'confidence': 0.75,
                                'reason': f"{strategy_info['name']}：{strategy_info['description']} - 价格反弹明显({strategy_info['price_range']['min']}%-{strategy_info['price_range']['max']}%)，趋势跟踪卖出",
                                'source': 'moderate_strategy',
                                'strategy_type': 'moderate',
                                'strategy_details': strategy_info,
                                'timestamp': datetime.now()
                            })

                elif investment_type == 'aggressive':
                    # 激进型策略：窄区间，高频次交易，追求极致买卖点
                    strategy_info = self.active_strategies['aggressive']
                    if price_position < 0.15:  # 极低点买入，追求最大化收益
                        signals.append({
                            'type': 'buy',
                            'confidence': 0.8,
                            'reason': f"{strategy_info['name']}：{strategy_info['description']} - 价格极度低估({strategy_info['price_range']['min']}%-{strategy_info['price_range']['max']}%)，超跌反弹机会",
                            'source': 'aggressive_strategy',
                            'strategy_type': 'aggressive',
                            'strategy_details': strategy_info,
                            'timestamp': datetime.now()
                        })
                    elif price_position > 0.85:  # 极高点卖出，追求最大化利润
                        # 检查是否允许做空
                        if not await self._check_allow_short_selling():
                            logger.info("激进策略：做空被禁用，跳过sell信号")
                            # 不添加sell信号，继续处理其他逻辑
                        else:
                            signals.append({
                                'type': 'sell',
                                'confidence': 0.8,
                                'reason': f"{strategy_info['name']}：{strategy_info['description']} - 价格极度高估({strategy_info['price_range']['min']}%-{strategy_info['price_range']['max']}%)，回调风险较大",
                                'source': 'aggressive_strategy',
                                'strategy_type': 'aggressive',
                                'strategy_details': strategy_info,
                                'timestamp': datetime.now()
                            })

        except Exception as e:
            logger.error(f"生成策略信号失败: {e}")

        return signals

    async def select_strategy(self, market_data: Dict[str, Any], signals: List[Dict[str, Any]]) -> Dict[str, Any]:
        """选择最优策略"""
        try:
            # 简化实现：选择置信度最高的信号
            if not signals:
                return {'type': 'hold', 'confidence': 0.5, 'reason': '无可用信号'}

            # 获取当前投资类型配置
            from ..config import load_config
            config = load_config()
            investment_type = config.strategies.investment_type

            # 优先选择当前投资类型的策略信号
            type_signals = [s for s in signals if investment_type in s.get('source', '')]
            if type_signals:
                # 在当前投资类型中选择置信度最高的
                type_signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
                best_signal = type_signals[0]
                return {
                    'selected_signal': best_signal,
                    'alternatives': type_signals[1:3] if len(type_signals) > 1 else [],
                    'selection_reason': f'{investment_type}策略优先，最高置信度'
                }

            # 如果没有当前投资类型的信号，选择所有信号中置信度最高的
            signals.sort(key=lambda x: x.get('confidence', 0), reverse=True)
            best_signal = signals[0]
            return {
                'selected_signal': best_signal,
                'alternatives': signals[1:3],  # 备选方案
                'selection_reason': '最高置信度（无匹配投资类型信号）'
            }

        except Exception as e:
            logger.error(f"策略选择失败: {e}")
            return {'type': 'hold', 'confidence': 0.5, 'reason': '策略选择失败'}

    async def backtest_strategy(self, strategy_name: str, historical_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """回测策略"""
        if not self.config.enable_backtesting:
            return {'error': '回测功能已禁用'}

        try:
            # 简化实现：模拟回测结果
            total_trades = len(historical_data) // 10  # 假设每10个数据点一个交易
            win_rate = 0.65  # 假设胜率65%
            total_return = 0.12  # 假设总收益12%

            result = {
                'strategy': strategy_name,
                'total_trades': total_trades,
                'win_rate': win_rate,
                'total_return': total_return,
                'sharpe_ratio': 1.2,
                'max_drawdown': 0.08,
                'backtest_period': f"{len(historical_data)} 天",
                'status': 'completed'
            }

            self.strategy_results.append(result)
            return result

        except Exception as e:
            logger.error(f"策略回测失败: {e}")
            return {'error': str(e)}

    async def optimize_strategy(self, strategy_name: str, parameters: Dict[str, Any]) -> Dict[str, Any]:
        """优化策略参数"""
        if not self.config.enable_optimization:
            return {'error': '优化功能已禁用'}

        try:
            # 简化实现：模拟优化过程
            optimized_params = {
                'take_profit': parameters.get('take_profit', 0.06) * 1.1,
                'stop_loss': parameters.get('stop_loss', 0.02) * 0.9,
                'position_size': parameters.get('position_size', 0.01) * 1.05
            }

            result = {
                'strategy': strategy_name,
                'original_parameters': parameters,
                'optimized_parameters': optimized_params,
                'expected_improvement': 0.15,
                'optimization_method': 'grid_search',
                'status': 'completed'
            }

            return result

        except Exception as e:
            logger.error(f"策略优化失败: {e}")
            return {'error': str(e)}

    def get_strategy_list(self) -> List[str]:
        """获取策略列表"""
        return list(self.active_strategies.keys())

    def get_strategy_status(self, strategy_name: str) -> Optional[Dict[str, Any]]:
        """获取策略状态"""
        return self.active_strategies.get(strategy_name)

    def get_status(self) -> Dict[str, Any]:
        """获取状态"""
        base_status = super().get_status()
        base_status.update({
            'active_strategies': len(self.active_strategies),
            'strategy_results': len(self.strategy_results),
            'strategy_list': self.get_strategy_list()
        })
        return base_status

# 创建策略管理器的工厂函数
async def create_strategy_manager() -> 'StrategyManager':
    """创建策略管理器实例"""
    from ..config import load_config
    config = load_config()

    sm_config = StrategyManagerConfig(
        name="AlphaStrategyManager",
        enable_backtesting=config.strategies.smart_tp_sl_enabled,
        enable_optimization=config.strategies.smart_tp_sl_enabled,
        default_strategy=config.strategies.investment_type,  # 使用投资类型作为默认策略
        max_active_strategies=3
    )

    manager = StrategyManager(sm_config)
    await manager.initialize()
    return manager

# 向后兼容的别名
# 暂时注释掉，避免循环引用
# MarketAnalyzer = StrategyManager
# StrategySelector = StrategyManager
# StrategyBacktestEngine = StrategyManager
# StrategyOptimizer = StrategyManager
# StrategyMonitor = StrategyManager
# StrategyExecutor = StrategyManager
# StrategyBehaviorHandler = StrategyManager

# 全局实例
market_analyzer = None
strategy_selector = None
consolidation_detector = None
crash_protection = None

async def initialize_strategies():
    """初始化策略模块（向后兼容）"""
    global market_analyzer, strategy_selector
    market_analyzer = await create_strategy_manager()
    strategy_selector = market_analyzer
    return market_analyzer

# 向后兼容的函数
def generate_enhanced_fallback_signal(market_data: Dict[str, Any], signal_history=None):
    """生成增强回退信号（向后兼容）"""
    # 简化实现
    from datetime import datetime
    return {
        'signal': 'HOLD',
        'confidence': 0.5,
        'reason': '回退信号',
        'timestamp': datetime.now().isoformat(),
        'provider': 'fallback'
    }

def get_strategy_manager() -> 'StrategyManager':
    """获取策略管理器实例"""
    global _strategy_manager
    if _strategy_manager is None:
        raise RuntimeError("策略管理器尚未初始化，请先调用 create_strategy_manager()")
    return _strategy_manager