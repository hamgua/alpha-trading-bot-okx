"""跳过交易机会审计。"""

import json
import logging
from datetime import datetime, timezone
from numbers import Number
from typing import Any, Dict

logger = logging.getLogger(__name__)


class OpportunityAuditor:
    """构建和记录跳过交易时的机会诊断。"""

    def build_skip_record(
        self,
        ai_signal: str,
        selected: Any,
        decision: Dict[str, Any],
        market_data: Dict[str, Any],
        has_position: bool,
    ) -> Dict[str, Any]:
        """构建可 JSON 序列化的跳过机会记录。"""
        technical = market_data.get("technical", {})
        record = {
            "event": "skip_opportunity",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "decision_reason": str(decision.get("reason", "")),
            "ai_signal": str(ai_signal),
            "strategy_signal": str(getattr(selected, "signal", "")),
            "strategy_type": self._stringify(getattr(selected, "strategy_type", "")),
            "strategy_confidence": self._float(getattr(selected, "confidence", 0)),
            "has_position": bool(has_position),
            "price": self._float(market_data.get("price")),
            "market_structure": str(market_data.get("market_structure", "")),
            "market_structure_direction": str(
                market_data.get("market_structure_direction", "")
            ),
            "risk_reward_ratio": self._float(market_data.get("risk_reward_ratio")),
            "short_risk_reward_ratio": self._float(
                market_data.get("short_risk_reward_ratio")
            ),
            "final_confidence": self._float(market_data.get("final_confidence")),
            "min_trade_confidence": self._float(
                market_data.get("min_trade_confidence")
            ),
            "technical": {
                "rsi": self._float(technical.get("rsi")),
                "atr_percent": self._float(technical.get("atr_percent")),
                "trend_strength": self._float(technical.get("trend_strength")),
            },
        }
        record["opportunity_flags"] = self._build_opportunity_flags(
            record, has_position
        )
        return record

    def log_skip(
        self,
        ai_signal: str,
        selected: Any,
        decision: Dict[str, Any],
        market_data: Dict[str, Any],
        has_position: bool,
    ) -> None:
        """记录跳过机会审计日志。"""
        record = self.build_skip_record(
            ai_signal=ai_signal,
            selected=selected,
            decision=decision,
            market_data=market_data,
            has_position=has_position,
        )
        logger.info(
            "[机会审计] %s",
            json.dumps(record, ensure_ascii=False, sort_keys=True),
        )

    def _build_opportunity_flags(
        self, record: Dict[str, Any], has_position: bool
    ) -> Dict[str, bool]:
        market_structure = record["market_structure"]
        market_direction = record["market_structure_direction"]
        rr_ratio = record["risk_reward_ratio"]
        short_rr_ratio = record["short_risk_reward_ratio"]
        technical = record["technical"]
        rsi = technical["rsi"]
        atr_percent = technical["atr_percent"]

        long_candidate = (
            not has_position
            and market_structure != "bearish"
            and rr_ratio >= 1.0
            and atr_percent < 0.55
        )
        short_candidate = (
            not has_position
            and (market_structure == "bearish" or market_direction == "short")
            and short_rr_ratio >= 1.2
            and atr_percent < 0.55
            and rsi > 40
        )
        return {
            "long_candidate": long_candidate,
            "short_candidate": short_candidate,
        }

    def _float(self, value: Any) -> float:
        if isinstance(value, Number):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _stringify(self, value: Any) -> str:
        enum_value = getattr(value, "value", None)
        if enum_value is not None:
            return str(enum_value)
        return str(value)
