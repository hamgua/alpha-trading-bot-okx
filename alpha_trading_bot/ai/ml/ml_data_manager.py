"""
ML 数据管理器

功能：
- 从数据库获取历史交易数据
- 连接 ai_signals 和 trades 表
- 为 ML 模型准备训练数据
- 生成特征工程

作者：AI Trading System
日期：2026-02-14
"""

import logging
import sqlite3
import json
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
from dataclasses import dataclass
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class MLError:
    """ML错误信息"""

    error: str
    timestamp: str = None
    details: Dict[str, Any] = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now().isoformat()


class MLDataManager:
    """
    ML 数据管理器

    从数据库提取和预处理 ML 所需数据
    """

    def __init__(self, db_path: str = "data_json/trading_data.db"):
        """
        初始化数据管理器

        Args:
            db_path: 数据库路径
        """
        self.db_path = db_path

    def get_connection(self) -> sqlite3.Connection:
        """获取数据库连接"""
        return sqlite3.connect(self.db_path)

    def get_historical_trades(
        self, symbol: str = None, days: int = 30, status: str = "closed"
    ) -> List[Dict[str, Any]]:
        """
        获取历史交易记录

        Args:
            symbol: 交易对（可选）
            days: 获取多少天的数据
            status: 交易状态

        Returns:
            List[Dict]: 交易记录列表
        """
        try:
            with self.get_connection() as conn:
                query = """
                    SELECT * FROM trades
                    WHERE status = :status
                    AND timestamp >= datetime('now', '-' || :days || ' days')
                """
                params = {"status": status, "days": days}

                if symbol:
                    query += " AND symbol = :symbol"
                    params["symbol"] = symbol

                query += " ORDER BY timestamp DESC"

                df = pd.read_sql(query, conn, params=params)
                return df.to_dict("records") if not df.empty else []

        except Exception as e:
            logger.error(f"[ML数据] 获取历史交易失败: {e}")
            return []

    def get_ai_signals_with_outcomes(
        self, days: int = 30, min_signals: int = 10
    ) -> List[Dict[str, Any]]:
        """
        获取 AI 信号及其对应的交易结果

        Args:
            days: 获取多少天的数据
            min_signals: 最少需要的信号数量

        Returns:
            List[Dict]: 信号列表，包含交易结果
        """
        try:
            with self.get_connection() as conn:
                # ai_signals 表已经包含 trade_result 和 pnl 字段
                query = """
                    SELECT * FROM ai_signals
                    WHERE timestamp >= datetime('now', '-' || :days || ' days')
                    ORDER BY timestamp DESC
                """
                df = pd.read_sql(query, conn, params={"days": days})

                if df.empty:
                    logger.warning(f"[ML数据] 过去{days}天无信号数据")
                    return []

                # 解析 trade_result
                if "trade_result" in df.columns:
                    # 有交易结果的信号
                    df["has_outcome"] = df["trade_result"].notna()

                # 按 provider 统计
                provider_counts = df.groupby("provider").size()
                logger.info(f"[ML数据] 信号分布: {provider_counts.to_dict()}")

                return df.to_dict("records")

        except Exception as e:
            logger.error(f"[ML数据] 获取AI信号失败: {e}")
            return []

    def calculate_provider_performance(
        self, signals: List[Dict]
    ) -> Dict[str, Dict[str, float]]:
        """
        计算各 AI 提供商的性能指标

        Args:
            signals: AI信号列表

        Returns:
            Dict: 各提供商的性能指标
        """
        if not signals:
            return {}

        df = pd.DataFrame(signals)

        performance = {}

        for provider in df["provider"].unique():
            provider_df = df[df["provider"] == provider]

            # 只看有交易结果的信号
            # ai_signals 表使用 'trade_result' 字段
            if "trade_result" in df.columns:
                closed_signals = provider_df[provider_df["trade_result"].notna()]
            else:
                closed_signals = provider_df

            if len(closed_signals) == 0:
                performance[provider] = {
                    "total_signals": len(provider_df),
                    "win_rate": 0.5,  # 无数据时默认
                    "avg_pnl": 0.0,
                    "sharpe_ratio": 0.0,
                    "max_drawdown": 0.0,
                    "profit_factor": 1.0,
                    "signal_count": len(provider_df),
                }
                continue

            # 计算性能指标
            wins = closed_signals[closed_signals["pnl"] > 0]
            losses = closed_signals[closed_signals["pnl"] <= 0]

            total = len(closed_signals)
            win_rate = len(wins) / total if total > 0 else 0.5

            avg_win = wins["pnl_percent"].mean() if len(wins) > 0 else 0
            avg_loss = abs(losses["pnl_percent"].mean()) if len(losses) > 0 else 0.01

            # 盈亏比
            profit_factor = (
                (avg_win * len(wins)) / (avg_loss * len(losses))
                if (avg_loss * len(losses)) > 0
                else 1.0
            )

            # 夏普比率近似
            pnl_series = closed_signals["pnl_percent"].dropna()
            sharpe = pnl_series.mean() / pnl_series.std() if pnl_series.std() > 0 else 0

            # 最大回撤
            cumulative = pnl_series.cumsum()
            peak = cumulative.cummax()
            drawdown = (cumulative - peak).min()
            max_drawdown = abs(drawdown) if drawdown < 0 else 0

            performance[provider] = {
                "total_signals": len(provider_df),
                "win_rate": win_rate,
                "avg_pnl": pnl_series.mean() if len(pnl_series) > 0 else 0,
                "sharpe_ratio": sharpe,
                "max_drawdown": max_drawdown,
                "profit_factor": profit_factor,
                "signal_count": len(provider_df),
                "closed_count": len(closed_signals),
            }

        return performance

    def get_market_features(
        self, symbol: str = "BTC/USDT", periods: int = 100
    ) -> pd.DataFrame:
        """
        获取市场特征数据（用于 ML 训练）

        Args:
            symbol: 交易对
            periods: 获取多少根K线

        Returns:
            DataFrame: 市场特征数据
        """
        try:
            with self.get_connection() as conn:
                query = """
                    SELECT * FROM market_data
                    WHERE symbol = :symbol
                    ORDER BY timestamp DESC
                    LIMIT :periods
                """
                df = pd.read_sql(
                    query, conn, params={"symbol": symbol, "periods": periods}
                )

                if df.empty:
                    logger.warning(f"[ML数据] 无市场数据 for {symbol}")
                    return pd.DataFrame()

                # 特征工程
                if "close" in df.columns:
                    # 收益率
                    df["returns"] = df["close"].pct_change()

                    # 移动平均
                    df["ma_5"] = df["close"].rolling(5).mean()
                    df["ma_20"] = df["close"].rolling(20).mean()
                    df["ma_ratio"] = df["close"] / df["ma_20"]

                    # 波动率
                    df["volatility"] = df["returns"].rolling(10).std()

                    # RSI
                    delta = df["close"].diff()
                    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                    rs = gain / loss.replace(0, np.nan)
                    df["rsi"] = 100 - (100 / (rs + 1))

                    # 价格位置
                    df["price_position"] = (
                        df["close"] - df["close"].rolling(20).min()
                    ) / (
                        df["close"].rolling(20).max()
                        - df["close"].rolling(20).min()
                        + 0.001
                    )

                # 删除NaN
                df = df.dropna()

                return df

        except Exception as e:
            logger.error(f"[ML数据] 获取市场特征失败: {e}")
            return pd.DataFrame()

    def get_training_data(
        self, min_trades: int = 50, days: int = 60
    ) -> Tuple[pd.DataFrame, pd.Series, Dict[str, Any]]:
        """
        获取 ML 训练数据

        Args:
            min_trades: 最少需要的交易数
            days: 获取多少天的数据

        Returns:
            Tuple[DataFrame, Series, Dict]: 特征、标签、元信息
        """
        # 获取信号和结果
        signals = self.get_ai_signals_with_outcomes(days=days)

        if len(signals) < min_trades:
            logger.warning(f"[ML数据] 信号不足: {len(signals)} < {min_trades}")
            return pd.DataFrame(), pd.Series(), {}

        df = pd.DataFrame(signals)

        # 只保留有交易结果的信号
        if "trade_result" in df.columns:
            df = df[df["trade_result"].notna()].copy()
        elif "trade_status" in df.columns:
            df = df[df["trade_status"] == "closed"].copy()

        if len(df) < min_trades:
            logger.warning(f"[ML数据] 有结果的信号不足: {len(df)} < {min_trades}")
            return pd.DataFrame(), pd.Series(), {}

        # 构建特征
        features = pd.DataFrame()

        # 置信度
        features["confidence"] = df["confidence"]

        #  Provider one-hot 编码
        for provider in df["provider"].unique():
            features[f"provider_{provider}"] = (df["provider"] == provider).astype(int)

        # 时间特征
        if "timestamp" in df.columns:
            timestamps = pd.to_datetime(df["timestamp"])
            features["hour"] = timestamps.dt.hour
            features["dayofweek"] = timestamps.dt.dayofweek

        # 标签：1=盈利, 0=亏损
        labels = (df["pnl"] > 0).astype(int)

        # 计算性能统计
        performance = self.calculate_provider_performance(signals)

        info = {
            "total_samples": len(df),
            "providers": list(performance.keys()),
            "performance": performance,
            "date_range": {
                "start": df["timestamp"].min() if len(df) > 0 else None,
                "end": df["timestamp"].max() if len(df) > 0 else None,
            },
        }

        return features, labels, info

    def save_model_weights(self, weights: Dict[str, float], source: str = "ml") -> bool:
        """
        保存模型权重到数据库

        Args:
            weights: 权重字典
            source: 权重来源

        Returns:
            bool: 是否成功
        """
        try:
            with self.get_connection() as conn:
                cursor = conn.cursor()

                for provider, weight in weights.items():
                    cursor.execute(
                        """
                        INSERT INTO model_weights (provider, weight, source, timestamp)
                        VALUES (?, ?, ?, ?)
                    """,
                        (provider, weight, source, datetime.now().isoformat()),
                    )

                conn.commit()
                logger.info(f"[ML数据] 保存权重成功: {weights}")
                return True

        except Exception as e:
            logger.error(f"[ML数据] 保存权重失败: {e}")
            return False

    def get_optimized_weights(self, window_days: int = 30) -> Dict[str, float]:
        """
        获取基于历史表现优化的权重

        Args:
            window_days: 分析窗口天数

        Returns:
            Dict: 优化后的权重
        """
        signals = self.get_ai_signals_with_outcomes(days=window_days)

        if not signals:
            # 默认权重
            return {"deepseek": 0.5, "kimi": 0.5}

        performance = self.calculate_provider_performance(signals)

        # 基于性能计算权重
        total_score = 0
        scores = {}

        for provider, metrics in performance.items():
            # 综合评分：胜率 * 0.4 + 夏普 * 0.3 + 盈利因子 * 0.3
            score = (
                metrics["win_rate"] * 0.4
                + max(0, metrics["sharpe_ratio"]) * 0.3
                + min(metrics["profit_factor"], 3) / 3 * 0.3
            )
            scores[provider] = score
            total_score += score

        # 归一化为权重
        if total_score > 0:
            weights = {p: s / total_score for p, s in scores.items()}
        else:
            weights = {p: 1.0 / len(scores) for p in scores}

        return weights


# 便捷函数
def get_ml_data_manager(db_path: str = "data_json/trading_data.db") -> MLDataManager:
    """获取 ML 数据管理器实例"""
    return MLDataManager(db_path)
