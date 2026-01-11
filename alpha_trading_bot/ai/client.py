"""
AI客户端 - 处理与多个AI提供商的通信
"""

import asyncio
import aiohttp
import json
import time
import logging
import random
from typing import Dict, Any, Optional
from datetime import datetime

from ..core.exceptions import AIProviderError, NetworkError, RateLimitError
from ..utils.price_calculator import PriceCalculator

logger = logging.getLogger(__name__)


def api_retry(provider_name: str, timeout_config: dict):
    """API重试装饰器 - 统一的退避策略"""

    def decorator(func):
        async def wrapper(*args, **kwargs):
            max_retries = timeout_config["max_retries"]
            base_delay = timeout_config["retry_base_delay"]

            for attempt in range(max_retries):
                try:
                    # 动态调整超时时间
                    current_timeout = timeout_config["total_timeout"] * (
                        1 + attempt * 0.2
                    )

                    # 创建新的market_data副本，更新超时时间
                    if "market_data" in kwargs:
                        kwargs["timeout_override"] = current_timeout

                    return await func(*args, **kwargs)

                except RateLimitError as e:
                    # 速率限制 - 指数退避
                    wait_time = base_delay * (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"{provider_name} API速率限制，{wait_time:.1f}秒后重试 (第{attempt + 1}次)"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise

                except asyncio.TimeoutError as e:
                    # 超时 - 指数退避
                    wait_time = base_delay * (2**attempt) + random.uniform(0, 1)
                    logger.warning(
                        f"{provider_name} API请求超时，{wait_time:.1f}秒后重试 (第{attempt + 1}次)"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise NetworkError(f"{provider_name} API请求超时，已重试多次")

                except NetworkError as e:
                    # 网络错误 - 线性退避
                    wait_time = base_delay * (attempt + 1) + random.uniform(0, 0.5)
                    logger.warning(
                        f"{provider_name} API网络错误，{wait_time:.1f}秒后重试 (第{attempt + 1}次)"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise

                except Exception as e:
                    # 其他异常 - 线性退避
                    wait_time = base_delay * (attempt + 1) + random.uniform(0, 0.5)
                    logger.warning(
                        f"{provider_name} API调用失败: {str(e)[:100]}，{wait_time:.1f}秒后重试 (第{attempt + 1}次)"
                    )
                    if attempt < max_retries - 1:
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        raise NetworkError(f"{provider_name} API调用失败: {str(e)}")

            return None

        return wrapper

    return decorator


class AIClient:
    """AI客户端 - 支持多个AI提供商"""

    def __init__(self):
        self.providers = {}
        self.timeout_config = {
            "deepseek": {
                "connection_timeout": 10.0,
                "response_timeout": 20.0,
                "total_timeout": 35.0,
                "retry_base_delay": 3.0,
                "max_retries": 3,
                "performance_score": 0.75,
            },
            "kimi": {
                "connection_timeout": 6.0,
                "response_timeout": 10.0,
                "total_timeout": 18.0,
                "retry_base_delay": 2.5,
                "max_retries": 3,
                "performance_score": 0.80,
            },
            "qwen": {
                "connection_timeout": 5.0,
                "response_timeout": 8.0,
                "total_timeout": 15.0,
                "retry_base_delay": 2.0,
                "max_retries": 3,
                "performance_score": 0.85,
            },
            "openai": {
                "connection_timeout": 10.0,
                "response_timeout": 15.0,
                "total_timeout": 25.0,
                "retry_base_delay": 4.0,
                "max_retries": 2,
                "performance_score": 0.70,
            },
        }
        self.session = None

    async def initialize(self) -> bool:
        """初始化AI客户端"""
        try:
            # 创建HTTP会话
            timeout = aiohttp.ClientTimeout(total=60)
            connector = aiohttp.TCPConnector(
                limit=100,
                limit_per_host=30,
                ttl_dns_cache=300,
                use_dns_cache=True,
                keepalive_timeout=30,
            )
            self.session = aiohttp.ClientSession(
                timeout=timeout,
                connector=connector,
                headers={"User-Agent": "AlphaTradingBot/3.0"},
            )

            # 加载提供商配置
            from ..config import load_config

            config = load_config()
            self.providers = config.ai.models

            logger.info(f"AI客户端初始化成功，配置 {len(self.providers)} 个提供商")
            return True

        except Exception as e:
            logger.error(f"AI客户端初始化失败: {e}")
            return False

    async def cleanup(self) -> None:
        """清理资源"""
        if self.session:
            logger.info(f"正在关闭AI客户端会话...")
            await self.session.close()
            self.session = None
            logger.info(f"AI客户端会话已关闭")

    async def generate_signal(
        self, provider: str, market_data: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        """生成AI信号"""
        try:
            if provider not in self.providers:
                raise AIProviderError(f"未知的AI提供商: {provider}")

            api_key = self.providers[provider]
            if not api_key:
                raise AIProviderError(f"提供商 {provider} 未配置API密钥")

            # 调试：检查market_data结构
            logger.debug(f"生成AI信号 - 提供商: {provider}")
            logger.debug(
                f"Market data类型检查 - price: {type(market_data.get('price'))}, "
                f"high: {type(market_data.get('high'))}, "
                f"low: {type(market_data.get('low'))}, "
                f"volume: {type(market_data.get('volume'))}"
            )

            # 构建提示词 - 根据提供商选择不同的prompt策略
            composite_price_position = 50.0  # 默认价格位置
            if provider in ["kimi", "deepseek"]:
                # 对于高级提供商，使用增强的prompt
                prompt, composite_price_position = self._build_enhanced_prompt(
                    provider, market_data
                )
            else:
                # 其他提供商使用标准prompt
                prompt, composite_price_position = self._build_trading_prompt(
                    market_data
                )

            # 将综合价格位置添加到市场数据中，供后续使用
            market_data["composite_price_position"] = composite_price_position

            # 根据提供商调用不同的API
            if provider == "kimi":
                return await self._call_kimi(api_key, prompt, market_data)
            elif provider == "deepseek":
                return await self._call_deepseek(api_key, prompt, market_data)
            elif provider == "qwen":
                return await self._call_qwen(api_key, prompt, market_data)
            elif provider == "openai":
                return await self._call_openai(api_key, prompt, market_data)
            else:
                raise AIProviderError(f"不支持的提供商: {provider}")

        except Exception as e:
            logger.error(f"生成AI信号失败 ({provider}): {e}")
            if isinstance(e, (NetworkError, RateLimitError)):
                raise
            raise AIProviderError(f"生成信号失败: {str(e)}")

    def _build_trading_prompt(self, market_data: Dict[str, Any]) -> str:
        """构建增强的交易提示词 - 参考alpha-pilot-bot的先进设计"""

        # 基础市场数据
        price = float(market_data.get("price", 0))

        # 使用当日最高最低价格（标量值）
        daily_high = float(market_data.get("high", price))
        daily_low = float(market_data.get("low", price))
        volume = float(market_data.get("volume", 0))

        # 24小时价格区间数据
        high_24h = daily_high  # 24小时最高价
        low_24h = daily_low  # 24小时最低价
        range_24h = high_24h - low_24h  # 24小时价格区间
        amplitude_24h = (
            (range_24h / price * 100) if price > 0 else 0
        )  # 24小时振幅百分比

        # 7日价格区间数据
        high_7d = float(market_data.get("high_7d", high_24h))  # 7日最高价，回退到24小时
        low_7d = float(market_data.get("low_7d", low_24h))  # 7日最低价，回退到24小时
        range_7d = high_7d - low_7d  # 7日价格区间
        amplitude_7d = (range_7d / price * 100) if price > 0 else 0  # 7日振幅百分比

        # 使用统一的价格位置计算器
        price_position_result = PriceCalculator.calculate_price_position(
            current_price=price,
            daily_high=daily_high,
            daily_low=daily_low,
            high_24h=high_24h,
            low_24h=low_24h,
            high_7d=high_7d,
            low_7d=low_7d,
        )

        # 向后兼容：保持原有变量名
        price_position = price_position_result.daily_position
        price_position_24h = price_position_result.position_24h
        price_position_7d = price_position_result.position_7d
        composite_price_position = price_position_result.composite_position

        # 综合振幅因子分析（结合24小时和7日）
        amplitude_level = "正常"
        if amplitude_24h < 2.0 and amplitude_7d < 5.0:
            amplitude_level = "低振幅（可能即将突破）"
        elif amplitude_24h > 4.0 or amplitude_7d > 10.0:
            amplitude_level = "高振幅（情绪激烈）"
        else:
            amplitude_level = "中振幅（正常波动）"

        # 计算价格变化
        price_change_pct = float(market_data.get("price_change_pct", 0))

        # 获取价格历史记录（修复变量定义）
        price_history = market_data.get("price_history", [])
        recent_changes = []
        cumulative_change = 0.0
        consecutive_up = 0
        consecutive_down = 0

        if price_history and len(price_history) >= 5:
            # 计算最近5个周期的变化
            recent_changes = price_history[-5:]
            if len(recent_changes) >= 2:
                # 累积变化（从最早的价格到当前价格）
                cumulative_change = (
                    (price - recent_changes[0]) / recent_changes[0] * 100
                )

            # 统计连续同向变化
            for i in range(len(recent_changes) - 1, 0, -1):
                current = recent_changes[i]
                previous = recent_changes[i - 1]
                change = (current - previous) / previous * 100

                if change > 0:
                    consecutive_up += 1
                    consecutive_down = 0
                elif change < 0:
                    consecutive_down += 1
                    consecutive_up = 0
                else:
                    break

        # 获取技术指标数据（如果有）
        technical_data = market_data.get("technical_data", {})
        rsi = float(technical_data.get("rsi", 50))
        macd = technical_data.get("macd", "N/A")
        ma_status = technical_data.get("ma_status", "N/A")
        atr_pct = float(technical_data.get("atr_pct", 0))

        # 获取趋势分析（从technical_data中获取新的趋势分析）
        trend_analysis = technical_data.get("trend_analysis", {})
        if trend_analysis:
            overall_trend = trend_analysis.get("overall_trend", "neutral")
            trend_strength = trend_analysis.get("trend_strength", 0.0)
            trend_consensus = trend_analysis.get("trend_consensus", 0.0)
            trend_details = trend_analysis.get("trend_details", {})

            # 将趋势强度转换为描述性文字
            if trend_strength > 0.7:
                strength_desc = "极强"
            elif trend_strength > 0.5:
                strength_desc = "强"
            elif trend_strength > 0.3:
                strength_desc = "中等"
            else:
                strength_desc = "弱"

            # 将趋势方向转换为中文
            if overall_trend == "strong_uptrend":
                trend_desc = f"强势上涨 (强度: {strength_desc})"
            elif overall_trend == "uptrend":
                trend_desc = f"上涨 (强度: {strength_desc})"
            elif overall_trend == "strong_downtrend":
                trend_desc = f"强势下跌 (强度: {strength_desc})"
            elif overall_trend == "downtrend":
                trend_desc = f"下跌 (强度: {strength_desc})"
            else:
                trend_desc = f"震荡 (强度: {strength_desc})"
        else:
            # 回退到旧的格式
            old_trend_analysis = market_data.get("trend_analysis", {})
            overall_trend = old_trend_analysis.get("overall", "震荡")
            trend_strength_str = old_trend_analysis.get("strength", "normal")
            # 将字符串强度转换为数值
            strength_map = {"strong": 0.7, "medium": 0.5, "weak": 0.3, "normal": 0.5}
            trend_strength = strength_map.get(trend_strength_str, 0.5)
            trend_desc = f"{overall_trend} ({trend_strength_str})"
            trend_consensus = 0.0

        # 构建技术指标状态（优化阈值）
        rsi_status = (
            "超卖"
            if rsi < 30
            else "偏低"
            if rsi < 40
            else "超买"
            if rsi > 70
            else "正常"
        )

        # 检测市场状态
        is_high_volatility = atr_pct > 3.0
        is_consolidation = (
            atr_pct < 1.5
            and abs(price_change_pct) < 4
            and price_position > 25
            and price_position < 75
        )

        # 构建市场情绪（优化阈值）
        if rsi < 30:
            sentiment = "📉 极度恐慌，可能反弹"
        elif rsi < 40:
            sentiment = "📉 偏低，关注反弹机会"
        elif rsi > 70:
            sentiment = "📈 极度贪婪，可能回调"
        elif rsi > 60:
            sentiment = "📈 偏高，注意回调风险"
        elif is_consolidation:
            sentiment = "➡️ 震荡观望，等待方向"
        else:
            sentiment = "😐 相对平衡"

        # 构建动态风控提示（基于趋势强度）
        if trend_strength > 0.5:
            # 强趋势市场 - 放宽风控标准
            if price_position > 90:
                risk_hint = "⚠️ 强趋势中高位: 90%以上需谨慎，但趋势良好可适度放宽"
            elif price_position > 80:
                risk_hint = "✅ 强趋势中正常高位: 多头市场特征，正常操作"
            else:
                risk_hint = "✅ 强趋势中低位: 积极寻找买入机会"
        elif trend_strength > 0.3:
            # 中等趋势 - 标准风控
            if is_consolidation:
                risk_hint = "⚠️ 震荡市: 缩小止盈止损范围，降低仓位"
            elif is_high_volatility:
                risk_hint = "⚠️ 高波动: 扩大止损范围，谨慎操作"
            else:
                risk_hint = "✅ 正常波动: 标准止盈止损设置"
        else:
            # 弱趋势 - 严格风控
            if price_position > 85:
                risk_hint = "🚨 弱趋势中高位: 严格控制风险，避免追高"
            elif rsi > 65:
                risk_hint = "🚨 弱趋势中高RSI: 超买区域，谨慎买入"
            else:
                risk_hint = "⚠️ 弱趋势: 保持谨慎，严格止损"

        # 构建增强的prompt
        prompt = f"""你是一个专业的加密货币交易员，擅长波段操作和趋势跟踪。请基于以下市场数据给出精准的交易建议：

【📊 核心市场数据】
当前价格: ${price:,.2f}
价格区间: ${daily_low:,.2f} - ${daily_high:,.2f}
价格位置: {price_position:.1f}% (相对当日区间)
24小时最高价: ${high_24h:,.2f}
24小时最低价: ${low_24h:,.2f}
24小时价格区间: ${range_24h:,.2f} USDT
24小时价格位置: {price_position_24h:.1f}% (相对24小时区间)
7日最高价: ${high_7d:,.2f}
7日最低价: ${low_7d:,.2f}
7日价格区间: ${range_7d:,.2f} USDT
7日价格位置: {price_position_7d:.1f}% (相对7日区间)
综合价格位置: {composite_price_position:.1f}% (24h:70% + 7d:30%)
24小时振幅: {amplitude_24h:.2f}%
7日振幅: {amplitude_7d:.2f}%
振幅状态: {amplitude_level}
价格变化: {price_change_pct:+.2f}%
累积变化: {cumulative_change:+.2f}% (最近5周期)
连续上涨: {consecutive_up} 次
连续下跌: {consecutive_down} 次
成交量: {volume:,.0f}
ATR波动率: {atr_pct:.2f}%

【🔧 技术分析】
RSI: {rsi:.1f} ({rsi_status})
MACD: {macd}
均线状态: {ma_status}
整体趋势: {trend_desc}
市场情绪: {sentiment}

 【⚡ 关键分析要求】
 1. 趋势检测优化：当趋势强度>0.5时才考虑趋势影响，避免过度敏感
 2. 合理波动识别：0.8%的单次涨幅和2.0%的累积涨幅才视为重要信号
 3. 价格位置优化：当价格从极低位（<20%）上涨时，1.0%的涨幅才视为积极信号
 4. 连续变化优化：连续5个周期同向变化且总幅度>1.5%才视为明确趋势
 5. 累积效应调整：5个周期内累计3.0%的涨幅才视为有意义的累积
 6. 突破触发提高：单次涨幅>1.2%或累积涨幅>3.0%才考虑买入信号

【⚠️ 风险控制】
{risk_hint}

【💡 决策框架 - 基于趋势强度的动态评估】
 - 强趋势市场（趋势强度>0.7）:
   - 价格位置<30%：极度低位，可考虑买入但需谨慎
   - 价格位置30-50%：相对低位，满足其他条件时可买入
   - 价格位置>80%：高风险，强制HOLD
   - RSI 65以下才考虑买入
   - 单次涨幅>1.5%或累积涨幅>3.0%：强烈买入信号

 - 中等趋势市场（趋势强度0.5-0.7）:
   - 价格位置<20%：极度低位，可考虑买入
   - 价格位置>70%：高风险区域，强制HOLD
   - RSI 60以下才考虑买入
   - 单次涨幅>1.2%或累积涨幅>2.5%：可考虑买入
   - 单次涨幅>1.8%或累积涨幅>4.0%：强烈买入信号

 - 弱趋势/震荡市场（趋势强度<0.5）:
   - 价格位置>60%：高风险，强制HOLD
   - RSI 55以下才考虑买入
   - 严格风控，1个风险因素即强制HOLD
   - 单次涨幅>2.0%或累积涨幅>4.0%才考虑买入
   - 必须等待更明确的信号，禁止对任何波动过度敏感

【📈 综合价格区间因子（24小时+7日）】
- 综合价格位置分析（权重：24小时70% + 7日30%）：
  - 位置<20%：相对低位，关注反弹机会
  - 位置20-40%：偏低位置，可考虑逐步建仓
  - 位置40-60%：中性位置，等待明确信号
  - 位置60-80%：偏高位置，谨慎追高
  - 位置>80%：相对高位，注意回调风险

- 多时间框架振幅分析：
  - 24小时低振幅（<2%）+ 7日低振幅（<5%）：市场极度收敛，大行情前兆
  - 24小时高振幅（>4%）或 7日高振幅（>10%）：情绪激烈，需要严格风控
  - 其他组合：正常波动，标准操作

- 区间突破信号（增强版）：
  - 突破24h最高价：短期强势信号
  - 突破7日最高价：中期强势信号，更可靠
  - 跌破24h最低价：短期弱势信号
  - 跌破7日最低价：中期弱势信号，更危险
  - 在双重区间内：关注两个区间的支撑/阻力作用

 - 特殊状态识别：
   - 24h和7日都在极低位（均<20%）：强烈关注，可能是底部区域
   - 24h和7日都在极高位（均>80%）：高度警惕，可能是顶部区域
   - 24h和7日位置差异大（>30%）：注意时间框架冲突，等待明确信号

 【🎯 特殊信号识别（极严格版）】
 - 低位反弹信号：价格位置<15% + 连续5次上涨 + RSI>35且上升 + 趋势强度>0.4
 - 突破确认信号：价格突破当日区间中轨 + 趋势强度>0.6 + 成交量放大
 - 累积效应信号：5个周期内累计涨幅>4.0%且无明显回调 + 趋势确认
 - 强力买入信号：单次2.5%涨幅 + 价格位置<30% + 趋势强度>0.5 = 强烈买入信号
 - 连续上涨信号：连续5周期上涨 + 总涨幅>3.0% = 买入信号
 - 历史累积信号：累积变化>4.0% + 连续上涨≥5次 + 趋势强度>0.6 = 强烈买入信号
 - 趋势反转信号：下跌趋势中，RSI>50且上升 + 价格突破前高 + 成交量放大

【🚨 暴跌保护机制】
- 早期预警：0.5%短期跌幅触发轻微预警，1.0%触发中等预警，1.5%触发严重预警
- 高价BTC特殊处理：价格>$50,000时，0.3%跌幅即触发早期预警（高价敏感度调整）
- 绝对跌幅保护：BTC>$50,000时，$500绝对跌幅即视为风险信号
- 暴跌信号：3%单日跌幅必须考虑卖出，2.5%止损保护自动触发
- 连续下跌：4个周期连续下跌且总跌幅>2% = 强烈卖出信号
- 加速下跌：跌幅逐周期扩大，总跌幅>1.5% = 危险信号
- 暴跌后策略：暴跌后等待至少3个周期确认底部，RSI<30才考虑抄底
- 止损纪律：严格设置止损，暴跌中不补仓，不逆势加仓
- 重新入场：暴跌后需满足：1)RSI脱离超卖 2)出现止跌信号 3)成交量放大 4)趋势强度回升

【⚠️ 下跌趋势中的严格规则】
- 下跌趋势中（趋势强度<-0.1）：必须等待RSI>40且连续上涨才考虑买入
- 强势下跌趋势中（趋势强度<-0.3）：禁止买入，只能等待趋势反转
- 下跌趋势中的买入条件：需要同时满足：1)RSI>35且上升 2)连续2次上涨 3)单次涨幅>0.5%
- 下跌趋势中的仓位控制：单次仓位不超过正常的50%
- 价格>$50,000时，百分比跌幅标准降低20-40%
- 关注绝对跌幅：$300-500的绝对跌幅比百分比更重要
- 早期预警更敏感：0.3%跌幅即开始关注（正常0.5%）
- 分批建仓间距缩小：高价时分批间隔从3周期减至2周期
- 止损设置更紧：从2.5%降至1.8%（$900-1000绝对值）

请以JSON格式回复，包含以下字段：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "详细分析理由（不少于50字）",
    "holding_time": "建议持仓时间",
    "risk": "风险提示和止损建议"
}}"""

        return prompt, composite_price_position

    def _build_enhanced_prompt(
        self, provider: str, market_data: Dict[str, Any]
    ) -> tuple[str, float]:
        """构建增强的AI提示词 - 参考alpha-pilot-bot的先进设计"""

        # 基础市场数据
        price = float(market_data.get("price", 0))
        daily_high = float(market_data.get("high", price))
        daily_low = float(market_data.get("low", price))
        volume = float(market_data.get("volume", 0))

        # 计算价格位置（相对当日高低位置）
        price_position = 50  # 默认中位
        if daily_high > daily_low:
            price_position = ((price - daily_low) / (daily_high - daily_low)) * 100

        # 24小时价格区间数据
        high_24h = daily_high  # 24小时最高价
        low_24h = daily_low  # 24小时最低价
        range_24h = high_24h - low_24h  # 24小时价格区间
        amplitude_24h = (
            (range_24h / price * 100) if price > 0 else 0
        )  # 24小时振幅百分比

        # 7日价格区间数据
        high_7d = float(market_data.get("high_7d", high_24h))  # 7日最高价，回退到24小时
        low_7d = float(market_data.get("low_7d", low_24h))  # 7日最低价，回退到24小时
        range_7d = high_7d - low_7d  # 7日价格区间
        amplitude_7d = (range_7d / price * 100) if price > 0 else 0  # 7日振幅百分比

        # 使用统一的价格位置计算器
        price_position_result = PriceCalculator.calculate_price_position(
            current_price=price,
            daily_high=daily_high,
            daily_low=daily_low,
            high_24h=high_24h,
            low_24h=low_24h,
            high_7d=high_7d,
            low_7d=low_7d,
        )

        # 向后兼容：保持原有变量名
        price_position = price_position_result.daily_position
        price_position_24h = price_position_result.position_24h
        price_position_7d = price_position_result.position_7d
        composite_price_position = price_position_result.composite_position

        # 计算价格变化
        price_change_pct = float(market_data.get("price_change_pct", 0))

        # 获取价格历史记录（修复变量定义）
        price_history = market_data.get("price_history", [])
        recent_changes = []
        cumulative_change = 0.0
        consecutive_up = 0
        consecutive_down = 0

        if price_history and len(price_history) >= 5:
            # 计算最近5个周期的变化
            recent_changes = price_history[-5:]
            if len(recent_changes) >= 2:
                # 累积变化（从最早的价格到当前价格）
                cumulative_change = (
                    (price - recent_changes[0]) / recent_changes[0] * 100
                )

            # 统计连续同向变化
            for i in range(len(recent_changes) - 1, 0, -1):
                current = recent_changes[i]
                previous = recent_changes[i - 1]
                change = (current - previous) / previous * 100

                if change > 0:
                    consecutive_up += 1
                    consecutive_down = 0
                elif change < 0:
                    consecutive_down += 1
                    consecutive_up = 0
                else:
                    break

        # 获取技术指标数据（如果有）
        technical_data = market_data.get("technical_data", {})
        rsi = float(technical_data.get("rsi", 50))
        macd = technical_data.get("macd", "N/A")
        ma_status = technical_data.get("ma_status", "N/A")
        atr_pct = float(technical_data.get("atr_pct", 0))

        # 获取趋势分析（从technical_data中获取新的趋势分析）
        trend_analysis = technical_data.get("trend_analysis", {})
        if trend_analysis:
            overall_trend = trend_analysis.get("overall_trend", "neutral")
            trend_strength = trend_analysis.get("trend_strength", 0.0)
            trend_consensus = trend_analysis.get("trend_consensus", 0.0)
            trend_details = trend_analysis.get("trend_details", {})

            # 将趋势强度转换为描述性文字
            if trend_strength > 0.7:
                strength_desc = "极强"
            elif trend_strength > 0.5:
                strength_desc = "强"
            elif trend_strength > 0.3:
                strength_desc = "中等"
            else:
                strength_desc = "弱"

            # 将趋势方向转换为中文
            if overall_trend == "strong_uptrend":
                trend_desc = f"强势上涨 (强度: {strength_desc})"
            elif overall_trend == "uptrend":
                trend_desc = f"上涨 (强度: {strength_desc})"
            elif overall_trend == "strong_downtrend":
                trend_desc = f"强势下跌 (强度: {strength_desc})"
            elif overall_trend == "downtrend":
                trend_desc = f"下跌 (强度: {strength_desc})"
            else:
                trend_desc = f"震荡 (强度: {strength_desc})"
        else:
            # 回退到旧的格式
            old_trend_analysis = market_data.get("trend_analysis", {})
            overall_trend = old_trend_analysis.get("overall", "震荡")
            trend_strength_str = old_trend_analysis.get("strength", "normal")
            # 将字符串强度转换为数值
            strength_map = {"strong": 0.7, "medium": 0.5, "weak": 0.3, "normal": 0.5}
            trend_strength = strength_map.get(trend_strength_str, 0.5)
            trend_desc = f"{overall_trend} ({trend_strength_str})"
            trend_consensus = 0.0

        # 构建技术指标状态（优化阈值）
        rsi_status = (
            "超卖"
            if rsi < 30
            else "偏低"
            if rsi < 40
            else "超买"
            if rsi > 70
            else "正常"
        )

        # 检测市场状态
        is_high_volatility = atr_pct > 3.0
        is_consolidation = (
            atr_pct < 1.5
            and abs(price_change_pct) < 4
            and price_position > 25
            and price_position < 75
        )

        # 构建市场情绪（优化阈值）
        if rsi < 30:
            sentiment = "📉 极度恐慌，可能反弹"
        elif rsi < 40:
            sentiment = "📉 偏低，关注反弹机会"
        elif rsi > 70:
            sentiment = "📈 极度贪婪，可能回调"
        elif rsi > 60:
            sentiment = "📈 偏高，注意回调风险"
        elif is_consolidation:
            sentiment = "➡️ 震荡观望，等待方向"
        else:
            sentiment = "😐 相对平衡"

        # 构建动态风控提示（基于趋势强度）
        if trend_strength > 0.5:
            # 强趋势市场 - 放宽风控标准
            if price_position > 90:
                risk_hint = "⚠️ 强趋势中高位: 90%以上需谨慎，但趋势良好可适度放宽"
            elif price_position > 80:
                risk_hint = "✅ 强趋势中正常高位: 多头市场特征，正常操作"
            else:
                risk_hint = "✅ 强趋势中低位: 积极寻找买入机会"
        elif trend_strength > 0.3:
            # 中等趋势 - 标准风控
            if is_consolidation:
                risk_hint = "⚠️ 震荡市: 缩小止盈止损范围，降低仓位"
            elif is_high_volatility:
                risk_hint = "⚠️ 高波动: 扩大止损范围，谨慎操作"
            else:
                risk_hint = "✅ 正常波动: 标准止盈止损设置"
        else:
            # 弱趋势 - 严格风控
            if price_position > 85:
                risk_hint = "🚨 弱趋势中高位: 严格控制风险，避免追高"
            elif rsi > 65:
                risk_hint = "🚨 弱趋势中高RSI: 超买区域，谨慎买入"
            else:
                risk_hint = "⚠️ 弱趋势: 保持谨慎，严格止损"

        # 提供商特定分析框架
        provider_frameworks = {
            "deepseek": f"""
【🎯 DEEPSEEK 技术深度分析框架】
1. 价格位置分析: 当前处于{price_position:.1f}%位置，结合支撑阻力判断关键点位
2. 技术形态识别: MACD交叉、均线金叉死叉、K线形态突破/反转信号
3. 博弈策略: 分析大资金动向，识别机构建仓/出货行为
4. 趋势跟踪: {overall_trend}趋势强度{abs(trend_strength):.2f}，ADX指标指引

交易风格: 波段操作，精准入场，技术指标驱动决策
""",
            "qwen": f"""
【🛡️ QWEN 风险管控分析框架】
1. 价格位置分析: 当前处于{price_position:.1f}%位置，重点关注高位风险
2. 风险识别: RSI超买预警({rsi:.1f})、价格位置风险评估
3. 动态风控: 根据价格位置调整止损标准，高位收紧风控
4. 趋势验证: {overall_trend}趋势中考虑回调风险和利润保护

交易风格: 稳健操作，风险优先，严格的风控纪律
""",
            "kimi": f"""
【📈 KIMI 短线分析框架】
1. 15分钟周期分析
2. RSI指标: {rsi:.1f} ({rsi_status})
3. 价格动能: {price_change_pct:+.2f}%
4. 支撑阻力: 基于价格位置判断

交易风格: 短线快进快出，严格止损
""",
        }

        # 获取提供商特定框架
        framework = provider_frameworks.get(provider, "")

        # 提供商特定关键分析要求
        if provider == "deepseek":
            analysis_requirements = """【⚡ DEEPSEEK 技术深度分析要求】
1. 技术指标优先级：MACD > 均线 > RSI，重点关注指标背离和共振信号
2. 形态识别强化：突破前高/前低、双底/双顶、头肩形态等经典技术形态
3. 成交量确认：任何信号都需要成交量放大作为支撑，缩量信号不可靠
4. 多周期验证：15分钟信号需与4小时趋势一致，避免逆势操作
5. 博弈分析：分析大资金动向，识别机构建仓/出货的关键点位
6. 精准入场：突破信号+成交量放大+技术指标共振才确认为有效信号"""
        elif provider == "qwen":
            analysis_requirements = """【🛡️ QWEN 风险管控分析要求】
1. 风险评估优先：任何信号首先评估潜在亏损幅度，最大回撤不能超过2%
2. 高位风险过滤：价格位置>70%时，买入信号自动降权0.2，>85%时禁止买入
3. 动态止损标准：基于价格位置调整止损，高位收紧至0.3%，低位放宽至1%
4. 仓位控制：单次操作不超过总资金的20%，分批建仓间距至少2周期
5. 趋势强度验证：弱趋势（强度<0.3）中只做SELL，不做BUY
6. 连续亏损保护：连续2次亏损后，下一笔操作信心度强制降低0.3"""
        else:
            analysis_requirements = """【⚡ 关键分析要求（优化版）】
1. 趋势确认优先：当趋势强度>0.25时才考虑趋势影响，避免过度敏感
2. 合理波动识别：0.3%的单次涨幅和0.5%的累积涨幅才视为重要信号
3. 价格位置优化：当价格从低位（<35%）上涨时，0.4%的涨幅才视为积极信号
4. 连续变化优化：连续3个周期同向变化且总幅度>0.4%才视为明确趋势
5. 累积效应调整：5个周期内累计0.7%的涨幅才视为有意义的累积
6. 突破触发提高：单次涨幅>0.8%或累积涨幅>1.0%才考虑买入信号"""

        # 构建增强的prompt
        prompt = f"""你是{provider.upper()} AI交易助手，{provider}以精准的市场分析和独特的交易视角著称。请基于以下市场数据给出专业的交易建议：

【📊 核心市场数据】
当前价格: ${price:,.2f}
价格区间: ${daily_low:,.2f} - ${daily_high:,.2f}
价格位置: {price_position:.1f}% (相对当日区间)
价格变化: {price_change_pct:+.2f}%
累积变化: {cumulative_change:+.2f}% (最近5周期)
连续上涨: {consecutive_up} 次
连续下跌: {consecutive_down} 次
成交量: {volume:,.0f}
ATR波动率: {atr_pct:.2f}%

【🔧 技术分析】
RSI: {rsi:.1f} ({rsi_status})
MACD: {macd}
均线状态: {ma_status}
整体趋势: {trend_desc}
市场情绪: {sentiment}

{framework}

{analysis_requirements}

【⚠️ 风险控制】
{risk_hint}

【💡 决策要点 - 基于趋势强度的动态评估】
- 价格相对位置: {price_position:.1f}% (0%=底部, 100%=顶部)
- 综合价格位置: {composite_price_position:.1f}% (24h:55% + 7d:45%)
- 技术指标状态: RSI {rsi_status}
- 波动率水平: {"高" if is_high_volatility else "低" if is_consolidation else "正常"}
- 趋势强度级别: {"强势" if trend_strength > 0.5 else "中等" if trend_strength > 0.3 else "弱势"}
- 价格位置因子: 价格越高买入信号越弱，价格越低买入信号越强
- 动态风控标准:
  * {"强趋势: 价格位置放宽至95%, RSI放宽至75, 单次涨幅>0.8%才考虑" if trend_strength > 0.5 else "中等趋势: 价格位置90%, RSI 70, 单次涨幅>0.6%才考虑" if trend_strength > 0.3 else "弱趋势: 价格位置85%, RSI 65, 单次涨幅>1.0%才考虑"}
- 建议操作: 基于趋势强度给出明确信号，弱趋势中严格控制买入条件

【🎯 特殊信号识别（优化版）】
- 低位反弹信号：价格位置<35% + 连续3次上涨 + RSI>35且上升 + 趋势强度>0.1
- 突破确认信号：价格突破当日区间中轨 + 趋势强度>0.25 + 成交量放大
- 累积效应信号：5个周期内累计涨幅>1.0%且无明显回调 + 趋势确认
- 超敏感信号：单次0.8%涨幅 + 价格位置<60% + 趋势强度>0.15 = 强烈买入信号
- 连续微涨信号：连续3周期上涨，总涨幅>0.5% = 买入信号
- 历史累积信号：累积变化>1.0% + 连续上涨≥3次 + 趋势强度>0.2 = 强烈买入信号
- 趋势反转信号：下跌趋势中，RSI>40且上升 + 价格突破前高 + 成交量放大

【🚨 暴跌保护机制】
- 早期预警：0.5%短期跌幅触发轻微预警，1.0%触发中等预警，1.5%触发严重预警
- 高价BTC特殊处理：价格>$50,000时，0.3%跌幅即触发早期预警（高价敏感度调整）
- 绝对跌幅保护：BTC>$50,000时，$500绝对跌幅即视为风险信号
- 暴跌信号：3%单日跌幅必须考虑卖出，2.5%止损保护自动触发
- 连续下跌：4个周期连续下跌且总跌幅>2% = 强烈卖出信号
- 加速下跌：跌幅逐周期扩大，总跌幅>1.5% = 危险信号
- 暴跌后策略：暴跌后等待至少3个周期确认底部，RSI<30才考虑抄底
- 止损纪律：严格设置止损，暴跌中不补仓，不逆势加仓
- 重新入场：暴跌后需满足：1)RSI脱离超卖 2)出现止跌信号 3)成交量放大 4)趋势强度回升

【⚠️ 下跌趋势中的严格规则】
- 下跌趋势中（趋势强度<-0.1）：必须等待RSI>40且连续上涨才考虑买入
- 强势下跌趋势中（趋势强度<-0.3）：禁止买入，只能等待趋势反转
- 下跌趋势中的买入条件：需要同时满足：1)RSI>35且上升 2)连续2次上涨 3)单次涨幅>0.5%
- 下跌趋势中的仓位控制：单次仓位不超过正常的50%
- 价格>$50,000时，百分比跌幅标准降低20-40%
- 关注绝对跌幅：$300-500的绝对跌幅比百分比更重要
- 早期预警更敏感：0.3%跌幅即开始关注（正常0.5%）
- 分批建仓间距缩小：高价时分批间隔从3周期减至2周期
- 止损设置更紧：从2.5%降至1.8%（$900-1000绝对值）

请以JSON格式回复，包含以下字段：
{{
    "signal": "BUY/SELL/HOLD",
    "confidence": 0.8,
    "reason": "详细分析理由（不少于50字）",
    "holding_time": "建议持仓时间",
    "risk": "风险提示和止损建议"
}}"""

        return prompt, composite_price_position

    async def _call_kimi_with_retry(
        self, api_key: str, prompt: str, market_data: Dict[str, Any], attempt: int = 0
    ) -> Dict[str, Any]:
        """Kimi API调用 - 带重试逻辑"""
        timeout_config = self.timeout_config["kimi"]
        max_retries = timeout_config["max_retries"]
        base_delay = timeout_config["retry_base_delay"]

        try:
            # 动态超时时间 - 随重试次数增加
            current_timeout = timeout_config["total_timeout"] * (1 + attempt * 0.2)

            result = await self._call_kimi_impl(
                api_key, prompt, market_data, current_timeout
            )
            return result

        except (RateLimitError, asyncio.TimeoutError, NetworkError) as e:
            if attempt < max_retries - 1:
                # 指数退避策略
                wait_time = base_delay * (2**attempt) + random.uniform(0, 1)
                logger.warning(
                    f"Kimi API调用失败: {str(e)[:50]}，{wait_time:.1f}秒后重试 (第{attempt + 2}次)"
                )
                await asyncio.sleep(wait_time)
                return await self._call_kimi_with_retry(
                    api_key, prompt, market_data, attempt + 1
                )
            else:
                raise NetworkError(f"Kimi API调用失败，已重试{max_retries}次: {str(e)}")

    async def _call_kimi_impl(
        self, api_key: str, prompt: str, market_data: Dict[str, Any], timeout: float
    ) -> Dict[str, Any]:
        """Kimi API实际调用实现"""
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "moonshot-v1-32k",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,
            "max_tokens": 800,
        }

        async with self.session.post(
            "https://api.moonshot.cn/v1/chat/completions",
            headers=headers,
            json=data,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            if response.status == 429:
                raise RateLimitError("Kimi API速率限制")
            elif response.status != 200:
                raise NetworkError(f"Kimi API错误: {response.status}")

            result = await response.json()
            content = result["choices"][0]["message"]["content"]

            return self._parse_ai_response(
                content, "kimi", market_data.get("composite_price_position", 50.0)
            )

    async def _call_kimi(
        self, api_key: str, prompt: str, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用Kimi API - 带增强重试机制"""
        return await self._call_kimi_with_retry(api_key, prompt, market_data)

    async def _call_deepseek(
        self, api_key: str, prompt: str, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用DeepSeek API"""
        timeout_config = self.timeout_config["deepseek"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "deepseek-chat",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.2,  # 降低随机性，保持一致性
            "max_tokens": 600,  # 适度增加，支持更详细分析
            "top_p": 0.95,  # 限制采样范围
            "frequency_penalty": 0.1,  # 减少重复
            "presence_penalty": 0.1,  # 鼓励新观点
        }

        try:
            async with self.session.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config["total_timeout"]),
            ) as response:
                if response.status == 429:
                    raise RateLimitError("DeepSeek API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"DeepSeek API错误: {response.status}")

                result = await response.json()
                content = result["choices"][0]["message"]["content"]

                return self._parse_ai_response(
                    content,
                    "deepseek",
                    market_data.get("composite_price_position", 50.0),
                )

        except asyncio.TimeoutError:
            raise NetworkError("DeepSeek API请求超时")
        except Exception as e:
            raise NetworkError(f"DeepSeek API调用失败: {e}")

    async def _call_qwen(
        self, api_key: str, prompt: str, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用Qwen API"""
        timeout_config = self.timeout_config["qwen"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "qwen-plus",  # 使用修复后的模型
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "你是一个专业的加密货币交易分析师，擅长技术分析和市场预测。请基于提供的市场数据给出准确的交易建议。",
                    },
                    {"role": "user", "content": prompt},
                ]
            },
            "parameters": {
                "temperature": 0.3,
                "max_tokens": 500,
                "top_p": 0.95,
                "result_format": "message",
            },
        }

        try:
            async with self.session.post(
                "https://dashscope.aliyuncs.com/api/v1/services/aigc/text-generation/generation",  # 使用原生端点
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config["total_timeout"]),
            ) as response:
                if response.status == 429:
                    raise RateLimitError("Qwen API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"Qwen API错误: {response.status}")

                result = await response.json()
                message = result["output"]["choices"][0]["message"]
                content = message.get("content", "")

                return self._parse_ai_response(
                    content, "qwen", market_data.get("composite_price_position", 50.0)
                )

        except asyncio.TimeoutError:
            raise NetworkError("Qwen API请求超时")
        except Exception as e:
            raise NetworkError(f"Qwen API调用失败: {e}")

    async def _call_openai(
        self, api_key: str, prompt: str, market_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """调用OpenAI API"""
        timeout_config = self.timeout_config["openai"]

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

        data = {
            "model": "gpt-3.5-turbo",
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.3,
            "max_tokens": 500,
        }

        try:
            async with self.session.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=data,
                timeout=aiohttp.ClientTimeout(total=timeout_config["total_timeout"]),
            ) as response:
                if response.status == 429:
                    raise RateLimitError("OpenAI API速率限制")
                elif response.status != 200:
                    raise NetworkError(f"OpenAI API错误: {response.status}")

                result = await response.json()
                content = result["choices"][0]["message"]["content"]

                return self._parse_ai_response(
                    content, "openai", market_data.get("composite_price_position", 50.0)
                )

        except asyncio.TimeoutError:
            raise NetworkError("OpenAI API请求超时")
        except Exception as e:
            raise NetworkError(f"OpenAI API调用失败: {e}")

    def _parse_ai_response(
        self, content: str, provider: str, composite_price_position: float = 50.0
    ) -> Dict[str, Any]:
        """解析AI响应"""
        try:
            # 尝试提取JSON
            import json
            import re

            # 查找JSON内容
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                json_str = json_match.group()
                ai_data = json.loads(json_str)

                # 验证必需字段
                signal = ai_data.get("signal", "HOLD").upper()
                confidence = float(ai_data.get("confidence", 0.5))
                reason = ai_data.get("reason", f"{provider} AI分析")
                holding_time = ai_data.get("holding_time", "15分钟")

                # 验证信号有效性
                if signal not in ["BUY", "SELL", "HOLD"]:
                    signal = "HOLD"

                # 验证置信度范围
                confidence = max(0.0, min(1.0, confidence))

                return {
                    "signal": signal,
                    "confidence": confidence,
                    "reason": reason,
                    "holding_time": holding_time,
                    "timestamp": datetime.now().isoformat(),
                    "provider": provider,
                    "raw_response": content,
                    "composite_price_position": composite_price_position,
                }
            else:
                # 如果没有JSON，尝试解析文本
                content_lower = content.lower()
                if "buy" in content_lower:
                    signal = "BUY"
                    confidence = 0.7
                elif "sell" in content_lower:
                    signal = "SELL"
                    confidence = 0.7
                else:
                    signal = "HOLD"
                    confidence = 0.5

                return {
                    "signal": signal,
                    "confidence": confidence,
                    "reason": f"{provider} AI建议: {content[:100]}...",
                    "holding_time": "15分钟",
                    "timestamp": datetime.now().isoformat(),
                    "provider": provider,
                    "raw_response": content,
                    "composite_price_position": composite_price_position,
                }

        except Exception as e:
            logger.error(f"解析AI响应失败: {e}")
            return {
                "signal": "HOLD",
                "confidence": 0.3,
                "reason": f"解析AI响应失败: {str(e)}",
                "holding_time": "15分钟",
                "timestamp": datetime.now().isoformat(),
                "provider": provider,
                "raw_response": content,
                "composite_price_position": composite_price_position,
            }
