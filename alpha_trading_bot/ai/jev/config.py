"""
Jev 快车道配置

从环境变量读取（对齐 AIConfig.from_env 模式）。
off/shadow/on 三档模式；默认 off 保证合入后零行为变化。
"""

import os
from dataclasses import dataclass
from typing import List


@dataclass
class JevFastLaneConfig:
    """Jev (TypeSafe System One) 快车道配置"""

    # off=关闭 / shadow=只观察(永不采用) / on=启用快车道
    mode: str = "off"
    api_key: str = ""
    # 官方建议 pin 固定版本，避免 jev-latest 移动指针漂移
    model: str = "jev-1.13.0"
    base_url: str = "https://api.typesafe.ai"

    # 快车道总超时（秒）；超时即升级 LLM
    timeout_seconds: float = 5.0

    # 非对称置信度阈值 (0-1)：BUY/SELL/SHORT 高门槛，HOLD 可更低
    conf_buy: float = 0.75
    conf_sell: float = 0.75
    conf_hold: float = 0.50

    # 安全旗标：反转风险 Noul 超过此值强制升级 LLM
    risk_noul_gate: float = 0.70

    # 熔断器
    failure_threshold: int = 3  # 连续瞬态失败 N 次后打开
    cooldown_seconds: int = 600  # 瞬态故障熔断冷却（秒）
    auth_cooldown_seconds: int = 21600  # 欠费/鉴权失败熔断冷却（秒，6h）

    VALID_MODES = ("off", "shadow", "on")

    def validate(self) -> List[str]:
        """验证配置，返回错误列表（空列表=有效）。"""
        errors: List[str] = []
        if self.mode not in self.VALID_MODES:
            errors.append(
                f"Jev快车道模式 '{self.mode}' 无效，可选: {list(self.VALID_MODES)}"
            )
        if self.timeout_seconds <= 0:
            errors.append(f"JEV_TIMEOUT {self.timeout_seconds} 必须 > 0")
        for name, value in (
            ("conf_buy", self.conf_buy),
            ("conf_sell", self.conf_sell),
            ("conf_hold", self.conf_hold),
        ):
            if not 0.0 < value <= 1.0:
                errors.append(f"{name} {value} 不在有效范围 (0, 1]")
        if not 0.0 < self.risk_noul_gate < 1.0:
            errors.append(f"risk_noul_gate {self.risk_noul_gate} 不在有效范围 (0, 1)")
        if self.failure_threshold < 1:
            errors.append(f"failure_threshold {self.failure_threshold} 必须 >= 1")
        if self.cooldown_seconds <= 0 or self.auth_cooldown_seconds <= 0:
            errors.append("熔断冷却秒数必须 > 0")
        return errors

    @classmethod
    def from_env(cls) -> "JevFastLaneConfig":
        """从环境变量读取（对齐 AIConfig.from_env 模式）。"""
        return cls(
            mode=os.getenv("AI_FAST_LANE", "off").strip().lower(),
            api_key=os.getenv("TYPESAFE_API_KEY", "").strip(),
            model=os.getenv("TYPESAFE_MODEL", "jev-1.13.0").strip() or "jev-1.13.0",
            base_url=os.getenv("TYPESAFE_BASE_URL", "https://api.typesafe.ai").rstrip(
                "/"
            ),
            timeout_seconds=float(os.getenv("JEV_TIMEOUT", "5.0")),
            conf_buy=float(os.getenv("JEV_CONF_BUY", "0.75")),
            conf_sell=float(os.getenv("JEV_CONF_SELL", "0.75")),
            conf_hold=float(os.getenv("JEV_CONF_HOLD", "0.50")),
            risk_noul_gate=float(os.getenv("JEV_RISK_NOUL_GATE", "0.70")),
            failure_threshold=int(os.getenv("JEV_CB_FAILURES", "3")),
            cooldown_seconds=int(os.getenv("JEV_CB_COOLDOWN", "600")),
            auth_cooldown_seconds=int(os.getenv("JEV_CB_AUTH_COOLDOWN", "21600")),
        )
