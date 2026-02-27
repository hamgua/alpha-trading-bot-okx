"""
状态持久化管理器

功能：
1. 持仓状态持久化（保存到项目根目录/data/trading_state/）
2. 止损单ID持久化
3. 程序崩溃后状态恢复
4. 交易历史记录

存储格式：JSON文件
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class PositionState:
    """持仓状态（用于持久化）"""

    symbol: str
    side: str
    amount: float
    entry_price: float
    unrealized_pnl: float = 0.0
    stop_order_id: Optional[str] = None
    last_stop_price: float = 0.0  # 上次设置的止损价
    updated_at: str = ""


@dataclass
class TradingState:
    """完整交易状态"""

    position: Optional[PositionState] = None
    last_trade_time: str = ""
    total_trades: int = 0
    daily_pnl: float = 0.0
    version: str = "1.0"


class StatePersistence:
    """
    状态持久化管理器

    使用方式：
        persistence = StatePersistence()
        persistence.save_position(position_data)
        persistence.load_state()
    """

    # 默认数据目录（项目根目录/data/trading_state/）
    DEFAULT_DATA_DIR = Path(__file__).parent.parent.parent / "data" / "trading_state"

    def __init__(self, data_dir: Optional[Path] = None):
        """
        初始化持久化管理器

        Args:
            data_dir: 数据存储目录，默认为项目根目录/data/trading_state/
        """
        self.data_dir = Path(data_dir) if data_dir else self.DEFAULT_DATA_DIR
        self.state_file = self.data_dir / "trading_state.json"
        self.history_file = self.data_dir / "trade_history.json"
        self.backup_dir = self.data_dir / "backups"

        # 确保目录存在
        self._ensure_directories()

        # 内存中的状态
        self._state: Optional[TradingState] = None

        logger.info(f"[持久化] 数据目录: {self.data_dir}")

    def _ensure_directories(self) -> None:
        """确保所有必要的目录都存在"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        logger.debug(f"[持久化] 目录已创建: {self.data_dir}")

    def save_position(
        self,
        symbol: str,
        side: str,
        amount: float,
        entry_price: float,
        stop_order_id: Optional[str] = None,
        unrealized_pnl: float = 0.0,
        last_stop_price: float = 0.0,
    ) -> bool:
        """
        保存持仓状态

        Args:
            symbol: 交易对
            side: 方向 (long/short)
            amount: 数量
            entry_price: 入场价
            stop_order_id: 止损单ID
            unrealized_pnl: 未实现盈亏

        Returns:
            是否保存成功
        """
        try:
            # 加载现有状态
            state = self.load_state()

            # 更新持仓
            state.position = PositionState(
                symbol=symbol,
                side=side,
                amount=amount,
                entry_price=entry_price,
                unrealized_pnl=unrealized_pnl,
                stop_order_id=stop_order_id,
                last_stop_price=last_stop_price,
                updated_at=datetime.now().isoformat(),
            )
            state.last_trade_time = datetime.now().isoformat()
            state.total_trades += 1

            # 保存到文件
            self._save_state(state)

            logger.info(
                f"[持久化] 持仓状态已保存: {symbol} {side} {amount}@{entry_price}"
            )
            return True

        except Exception as e:
            logger.error(f"[持久化] 保存持仓状态失败: {e}")
            return False

    def clear_position(self) -> bool:
        """
        清空持仓状态

        Returns:
            是否清除成功
        """
        try:
            state = self.load_state()

            # 创建备份
            if state.position:
                self._create_backup(state)
                logger.info(f"[持久化] 创建备份: 持仓 {state.position.symbol} 已平仓")

            # 清空持仓
            state.position = None
            self._save_state(state)

            logger.info("[持久化] 持仓状态已清空")
            return True

        except Exception as e:
            logger.error(f"[持久化] 清空持仓状态失败: {e}")
            return False

    def update_stop_order(self, stop_order_id: Optional[str]) -> bool:
        """
        更新止损单ID

        Args:
            stop_order_id: 止损单ID

        Returns:
            是否更新成功
        """
        try:
            state = self.load_state()

            if state.position:
                state.position.stop_order_id = stop_order_id
                state.position.updated_at = datetime.now().isoformat()
                self._save_state(state)
                logger.info(f"[持久化] 止损单已更新: {stop_order_id}")
                return True
            else:
                logger.warning("[持久化] 无持仓，无法更新止损单")
                return False

        except Exception as e:
            logger.error(f"[持久化] 更新止损单失败: {e}")
            return False

    def load_state(self) -> TradingState:
        """
        加载交易状态

        Returns:
            TradingState对象
        """
        if self._state is not None:
            return self._state

        try:
            if self.state_file.exists():
                with open(self.state_file, "r", encoding="utf-8") as f:
                    data = json.load(f)

                # 解析持仓状态
                position = None
                if data.get("position"):
                    pos_data = data["position"]
                    position = PositionState(
                        symbol=pos_data.get("symbol", ""),
                        side=pos_data.get("side", ""),
                        amount=pos_data.get("amount", 0),
                        entry_price=pos_data.get("entry_price", 0),
                        unrealized_pnl=pos_data.get("unrealized_pnl", 0),
                        stop_order_id=pos_data.get("stop_order_id"),
                        last_stop_price=pos_data.get("last_stop_price", 0),
                        updated_at=pos_data.get("updated_at", ""),
                    )

                self._state = TradingState(
                    position=position,
                    last_trade_time=data.get("last_trade_time", ""),
                    total_trades=data.get("total_trades", 0),
                    daily_pnl=data.get("daily_pnl", 0.0),
                    version=data.get("version", "1.0"),
                )

                if position:
                    logger.info(
                        f"[持久化] 加载已有持仓: {position.symbol} {position.side} "
                        f"{position.amount}@{position.entry_price}"
                    )
                else:
                    logger.info("[持久化] 加载状态: 无持仓")

                return self._state

        except Exception as e:
            logger.warning(f"[持久化] 加载状态失败: {e}, 使用空状态")

        # 返回空状态
        self._state = TradingState()
        return self._state

    def _save_state(self, state: TradingState) -> None:
        """
        保存状态到文件

        Args:
            state: TradingState对象
        """
        # 先写入临时文件，再重命名（原子操作）
        temp_file = self.state_file.with_suffix(".tmp")

        data = {
            "position": asdict(state.position) if state.position else None,
            "last_trade_time": state.last_trade_time,
            "total_trades": state.total_trades,
            "daily_pnl": state.daily_pnl,
            "version": state.version,
            "saved_at": datetime.now().isoformat(),
        }

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 原子重命名
        temp_file.replace(self.state_file)

        # 更新内存缓存
        self._state = state

    def _create_backup(self, state: TradingState) -> None:
        """
        创建状态备份

        Args:
            state: 要备份的状态
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_file = self.backup_dir / f"state_{timestamp}.json"

        data = {
            "position": asdict(state.position) if state.position else None,
            "last_trade_time": state.last_trade_time,
            "total_trades": state.total_trades,
            "daily_pnl": state.daily_pnl,
            "version": state.version,
            "backup_at": datetime.now().isoformat(),
        }

        with open(backup_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        # 清理旧备份（保留最近10个）
        self._cleanup_old_backups(keep=10)

    def _cleanup_old_backups(self, keep: int = 10) -> None:
        """
        清理旧备份文件

        Args:
            keep: 保留的备份数量
        """
        backups = sorted(self.backup_dir.glob("state_*.json"))
        for old_backup in backups[:-keep]:
            old_backup.unlink()
            logger.debug(f"[持久化] 删除旧备份: {old_backup.name}")

    # ==================== 交易历史记录 ====================

    def record_trade(
        self,
        trade_type: str,
        symbol: str,
        side: str,
        amount: float,
        price: float,
        pnl: float = 0.0,
        reason: str = "",
    ) -> bool:
        """
        记录交易历史

        Args:
            trade_type: 交易类型 (open/close)
            symbol: 交易对
            side: 方向
            amount: 数量
            price: 价格
            pnl: 盈亏
            reason: 原因

        Returns:
            是否记录成功
        """
        try:
            # 加载现有历史
            history = self._load_history()

            # 添加新记录
            record = {
                "timestamp": datetime.now().isoformat(),
                "type": trade_type,
                "symbol": symbol,
                "side": side,
                "amount": amount,
                "price": price,
                "pnl": pnl,
                "reason": reason,
            }
            history.append(record)

            # 保存
            self._save_history(history)

            logger.info(
                f"[持久化] 记录交易: {trade_type} {symbol} {side} {amount}@{price}"
            )
            return True

        except Exception as e:
            logger.error(f"[持久化] 记录交易失败: {e}")
            return False

    def _load_history(self) -> List[Dict[str, Any]]:
        """加载交易历史"""
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, list):
                        return data
        except Exception as e:
            logger.warning(f"[持久化] 加载交易历史失败: {e}")

        return []
        """加载交易历史"""
        try:
            if self.history_file.exists():
                with open(self.history_file, "r", encoding="utf-8") as f:
                    return json.load(f)
        except Exception as e:
            logger.warning(f"[持久化] 加载交易历史失败: {e}")

        return []

    def _save_history(self, history: List[Dict[str, Any]]) -> None:
        """保存交易历史"""
        temp_file = self.history_file.with_suffix(".tmp")

        with open(temp_file, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

        temp_file.replace(self.history_file)

    def get_recent_trades(self, limit: int = 50) -> List[Dict[str, Any]]:
        """
        获取最近的交易记录

        Args:
            limit: 最大返回数量

        Returns:
            交易记录列表
        """
        history = self._load_history()
        return history[-limit:] if history else []

    def get_state_summary(self) -> Dict[str, Any]:
        """
        获取状态摘要

        Returns:
            状态摘要字典
        """
        state = self.load_state()
        history = self._load_history()

        return {
            "has_position": state.position is not None,
            "position": asdict(state.position) if state.position else None,
            "total_trades": state.total_trades,
            "daily_pnl": state.daily_pnl,
            "history_count": len(history),
            "data_dir": str(self.data_dir),
        }


def create_state_persistence(data_dir: Optional[Path] = None) -> StatePersistence:
    """创建持久化管理器实例"""
    return StatePersistence(data_dir)
