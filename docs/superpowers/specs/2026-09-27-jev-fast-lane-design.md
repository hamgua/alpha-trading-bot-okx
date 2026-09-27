# Jev 快车道（Jev Fast Lane）设计

## Context

本项目当前的 AI 信号链路为：`AIClient.get_signal(market_data)` →
单 AI / 多 AI 融合调用 LLM（OpenAI 兼容 HTTP 文本接口）→ `parse_response`
文本解析 → `AISignalIntegrator` 本地优化/风控层 → 最终信号。

LLM 路径存在两个固有成本：

1. **延迟**：秒级起步（思考模式模型更慢），直接拉长每个交易循环的决策时间。
2. **脆弱性**：自然语言输出需要正则/JSON 兼容解析（`response_parser` 中
   大量兼容代码），置信度是模型自报值，校准性无保证。

TypeSafe 的 Jev（System One 模型，如 `jev-1.13.0`）是另一类模型：输入
`state`（状态快照）+ 带类型的原子问题（Choice / Score / Noul），直接返回
**结构化类型值 + 完整概率分布 + 由分布形状计算出的 `confidence`**。
官方标称延迟 70–500ms（40–200× 快于 LLM），按 input token 计费
（约 $0.042/M，输出免费），无自由文本输出。

Jev 官方文档明确推荐 **Confidence-Gated Routing** 模式：
高置信直接行动、中置信谨慎、低置信路由给另一个系统。
本设计将该模式落地为：**Jev 前置快车道做快捷结构化决策，
置信度不足或触发安全旗标时由现有 LLM 路径接管（级联，非并行）**，
且 Jev 账户故障（欠费/封停/网络）时自动熔断降级为纯 LLM 架构。

## Goal

在**不改动任何下游安全层**（`AISignalIntegrator`、风控、下单链路、
融合策略）的前提下，为 AI 信号获取增加一条可开关、可观测、可熔断的
Jev 快速车道：

- Jev 高置信 → 直接采用其结构化信号，跳过 LLM（省延迟 + 省成本）。
- Jev 低置信 / 风险旗标 / 超时 / 错误 → 升级 LLM 最终裁决，
  并把 Jev 初读（答案 + 概率分布）注入 LLM prompt 作为上下文。
- Jev 账户欠费 / 封停 / 瞬态故障 → 熔断器自动关闭快车道，
  全部流量走 LLM；故障恢复（如补缴后）自动探测恢复。
- 快车道默认关闭（`AI_FAST_LANE=off`），合入代码本身零行为变化；
  提供 `shadow` 观察模式用于验证 Jev 判断质量。

## Non-Goals（明确不做）

- 不修改 `AISignalIntegrator`、风控层、下单/持仓链路。
- 不修改融合策略（fusion strategies）。
- 不做 Jev 本地部署，仅使用托管 API（`https://api.typesafe.ai`）。
- Jev 不用于交易决策以外的场景（不做 prompt 优化、不做回测标注等）。
- 不引入 `typesafe-sdk` 等 vendor SDK（与项目现有惯例一致：
  通过 HTTP API 直连，不依赖官方 SDK）。
- 不改动 `VALID_SIGNALS` 词表（`buy/hold/sell/short`）与信号消费方接口。

## Architecture

```
market_data
   ▼
AIClient.get_signal()
   │  ① 缓存命中 → 直接返回（现状不变；Jev 位于缓存之下）
   │  ② [新增] fast_lane.decide(market_data)
   │      ├─ 未启用 / 无 Key / 熔断打开 → skipped
   │      ├─ 调用 TypeSafe API：state + 1 Choice + 2 Noul，一次请求
   │      └─ adopted（高置信且无风险旗标）
   │         或 escalated（低置信 / 风险旗标 / 超时 / 错误 / shadow）
   ▼  两条路径在此汇合，以下全部不变
original_signal → AISignalIntegrator.process() → 风控 → 缓存 → 返回
```

**关键不变式**：Jev 只替换"原始信号获取"一步；adopted 与 escalated
两条路径共用同一下游集成器与风控层；`AIClient.get_signal` 的对外
签名与返回语义不变。

### 新增包：`alpha_trading_bot/ai/jev/`

| 文件 | 职责 |
|---|---|
| `__init__.py` | 导出 `JevClient`、`JevFastLane`、`JevFastLaneConfig`、`FastLaneResult`、`JevQuestion` 等 |
| `config.py` | `JevFastLaneConfig`（dataclass + `from_env()`，对齐 `AIConfig.from_env` 模式） |
| `typesafe_client.py` | `JevClient`：aiohttp 异步直连 `POST {base_url}/v1/systemone` |
| `questions.py` | `build_state(market_data)` 与问题集定义 |
| `fast_lane.py` | `JevFastLane`：决策矩阵 + 熔断器 + shadow 模式 |

### `typesafe_client.py`

```python
@dataclass
class ChoiceAnswer:
    choice: str
    probabilities: Dict[str, float]
    confidence: float

@dataclass
class NoulAnswer:
    noul: float  # 0–1，"是"的概率

@dataclass
class SystemOneResponse:
    answers: Dict[str, Union[ChoiceAnswer, NoulAnswer]]

class TypeSafeAuthError(TradingBotException):   # 401/402：欠费/Key 无效/封停
class TypeSafeAPIError(TradingBotException):    # 429/5xx/4xx（非 401/402）
class TypeSafeTimeoutError(TradingBotException) # 超时
```

- `JevClient(config: JevFastLaneConfig)`，
  `async def system_one(self, state: str, questions: Dict[str, JevQuestion]) -> SystemOneResponse`
- 请求体：`{"model": config.model, "state": state, "questions": {...}}`，
  Header `Authorization: Bearer {api_key}`。
- `aiohttp.ClientTimeout(total=config.timeout_seconds)`。
- 重试：仅对 429/5xx 退避重试 2 次（对齐现有 `_call_ai_with_retry` 的
  指数退避模式）；401/402/超时不重试（直接分类抛出）。
- 响应解析：`answers` 下每个问题按 id 解析；`choice`/`score` 类型读
  `probabilities` + `confidence`；`noul` 类型读单值。解析失败抛
  `TypeSafeAPIError`（按错误处理，触发升级，不静默）。
- 日志：延迟、问题数、HTTP 状态；错误文本脱敏（复用
  `client.py` 的 `_redact_sensitive_text` 思路，避免泄露 Key）。

### `questions.py`

`build_state(market_data: Dict[str, Any]) -> str`：
把市场快照序列化成紧凑结构化文本（目标 400–600 tokens），字段取
`market_data` 现有键：

- 基础：`symbol`、`price`、`high`/`low`、`volume`、`change_percent`
- 技术面：`technical` 中的 `rsi`、`macd_hist`、`trend_direction`、
  `trend_strength`、`price_position`、布林带位置等已有指标
  （缺键则跳过，不报错）
- 动量：`recent_drop_percent`、`short_term_drop_percent`、
  `short_term_rise_percent`
- 持仓：`position`（存在时：方向、数量、入场价、已实现/未实现盈亏，
  有则取，无则略）
- 最近 K 线：`price_history` 尾部 20 根收盘价（供 Jev 观察短期形态）

问题集（一次请求问全，官方最佳实践；全部为原子问题）：

```python
JEV_QUESTIONS = {
    # 主问题：四选项对齐 VALID_SIGNALS
    "trade_decision": Choice(
        instructions="基于当前市场状态，给出交易方向",
        criteria={
            "buy":   "趋势与指标支持做多入场",
            "hold":  "无明确交易优势，观望",
            "sell":  "趋势与指标支持平仓/做空离场",
            "short": "明确看空信号，支持做空入场",
        },
    ),
    # 安全旗标：反转风险
    "is_high_risk_reversal": Noul(
        instructions="当前价格行为暗示即将发生急涨或急跌的反转风险",
    ),
    # 上下文旗标：震荡无方向
    "is_choppy_no_edge": Noul(
        instructions="市场处于无明确方向的震荡，缺乏交易优势",
    ),
}
```

问题文案集中在此文件，便于按 shadow 观察结果迭代调参。

### `fast_lane.py`

```python
@dataclass
class FastLaneResult:
    adopted: bool
    signal: Optional[str] = None          # adopted 时为 buy/hold/sell/short
    confidence: float = 0.0               # 主问题 Choice 的 confidence（主问题恒为 Choice，必有此值）
    probabilities: Dict[str, float] = field(default_factory=dict)
    jev_context: Optional[str] = None     # 升级 LLM 时注入 prompt 的初读摘要
    reason: str = ""                      # 见决策矩阵
    latency_ms: int = 0
```

`JevFastLane(config, client)`，另提供便捷构造 `JevFastLane.from_env()`（等价于
`JevFastLane(JevFastLaneConfig.from_env(), JevClient(...))`，供 `AIClient` 未显式注入时自建）。
`async def decide(self, market_data) -> FastLaneResult`

**决策矩阵**（按序判断，先命中先生效）：

| # | 条件 | 结果 | reason |
|---|---|---|---|
| 1 | `config.mode == "off"` 或无 `api_key` | 不采用 | `disabled` |
| 2 | 熔断器 OPEN | 不采用 | `circuit_open` |
| 3 | `mode == "shadow"` | 调用 Jev，**永不采用**，记录 adopted 本应是什么 | `shadow` |
| 4 | 调用异常（Timeout/APIError/AuthError） | 不采用 + 记录失败（驱动熔断） | `timeout` / `api_error` / `auth_error` |
| 5 | `is_high_risk_reversal > config.risk_noul_gate` | 不采用（安全旗标一票否决） | `risk_gate` |
| 6 | `choice == "hold"` 且 `confidence ≥ conf_hold` | 采用 HOLD | `adopt` |
| 7 | `choice == "buy"` 且 `confidence ≥ conf_buy` | 采用 BUY | `adopt` |
| 8 | `choice in ("sell","short")` 且 `confidence ≥ conf_sell` | 采用 | `adopt` |
| 9 | 其余 | 不采用 | `low_confidence` |

不采用时生成 `jev_context`（示例）：

```
[Jev初读] 倾向=BUY(置信0.62) 分布: buy=0.45/hold=0.35/sell=0.15/short=0.05
          反转风险=0.31 震荡无方向=0.60
          快车道置信度不足未能直接决策，请基于完整市场数据独立判断，
          不必与初读一致
```

### 熔断器（`fast_lane.py` 内 `_CircuitBreaker`）

状态机：`CLOSED → OPEN →(冷却到期)→ HALF-OPEN(单次探测) →
成功回 CLOSED / 失败再 OPEN`。

| 故障类型 | 触发条件 | 冷却 | 语义 |
|---|---|---|---|
| 欠费/封停（`TypeSafeAuthError`） | 单次即开 | `auth_cooldown_seconds`（默认 21600 = 6h） | 不做高频重试；冷却到期后自动探测，补缴/解封即自动恢复 |
| 瞬态（Timeout/APIError） | 连续 `failure_threshold`（默认 3）次 | `cooldown_seconds`（默认 600 = 10min） | 短暂网络抖动自动恢复 |

- 任意状态切换打 WARNING 日志，含触发原因（如
  `[Jev熔断] OPEN: 402 欠费/鉴权失败，冷却 6h`），账户欠费在日志中明确可见。
- 内存态，进程重启自动重置（bot 重启即全新状态，可接受）。
- 熔断期间 `decide()` 不发网络请求，直接返回 `circuit_open`。

### `config.py`

`JevFastLaneConfig`（dataclass），`from_env()` 读取（默认值即安全默认）：

| 字段 | env | 默认 | 说明 |
|---|---|---|---|
| `mode` | `AI_FAST_LANE` | `off` | `off`/`shadow`/`on` |
| `api_key` | `TYPESAFE_API_KEY` | `""` | 空 Key + `on` 模式时按 `disabled` 处理并 WARNING |
| `model` | `TYPESAFE_MODEL` | `jev-1.13.0` | 官方建议 pin 固定版本 |
| `base_url` | `TYPESAFE_BASE_URL` | `https://api.typesafe.ai` | |
| `timeout_seconds` | `JEV_TIMEOUT` | `5.0` | 快车道总超时，超时即升级 LLM |
| `conf_buy` | `JEV_CONF_BUY` | `0.75` | BUY 采用所需最低置信度 |
| `conf_sell` | `JEV_CONF_SELL` | `0.75` | SELL/SHORT 采用所需最低置信度 |
| `conf_hold` | `JEV_CONF_HOLD` | `0.50` | HOLD 采用所需最低置信度（安全默认动作，可更低） |
| `risk_noul_gate` | `JEV_RISK_NOUL_GATE` | `0.70` | 反转风险 Noul 超过此值强制升级 LLM |
| `failure_threshold` | `JEV_CB_FAILURES` | `3` | 瞬态故障连续 N 次后熔断 |
| `cooldown_seconds` | `JEV_CB_COOLDOWN` | `600` | 瞬态故障熔断冷却（秒） |
| `auth_cooldown_seconds` | `JEV_CB_AUTH_COOLDOWN` | `21600` | 欠费/鉴权失败熔断冷却（秒） |

## Integration Points

### `AIClient`（`alpha_trading_bot/ai/client.py`）

1. `__init__` 增加可选参数 `fast_lane: Optional[JevFastLane] = None`：
   传入则用；未传入时若 `AI_FAST_LANE` 非 `off` 则按 env 自建
   （`JevFastLane.from_env()`），否则为 `None`（行为与现状完全一致）。
2. `get_signal` 在缓存检查之后、LLM 分支之前插入：

   ```python
   if self._fast_lane is not None:
       fast_result = await self._fast_lane.decide(market_data)
       if fast_result.adopted:
           original_signal, original_confidence = fast_result.signal, fast_result.confidence
           logger.info(f"[AI快车道] Jev 采用: {original_signal} "
                       f"(置信={fast_result.confidence:.2f}, {fast_result.latency_ms}ms)")
       else:
           original_signal, original_confidence = await self._get_llm_signal(
               market_data, jev_context=fast_result.jev_context
           )
   else:
       original_signal, original_confidence = await self._get_llm_signal(market_data)
   ```

3. 现有 `if mode == "single" ... else fusion` 分支抽成私有方法
   `_get_llm_signal(market_data, jev_context: Optional[str] = None) -> Tuple[str, float]`，
   内部把 `jev_context` 透传给 `_get_single_signal` / `_get_fusion_signal`
   → `_call_ai` → `build_prompt`。
4. `get_metrics()` 增加快车道计数：`fast_lane_adopted` /
   `fast_lane_escalated` / `fast_lane_errors` / `circuit_open`（布尔或计数）。
5. 信号分布统计：adopted 时 `log_signal_distribution(signal, source="jev")`
   （现有函数已支持任意 source 字符串）。

### `prompt_builder.py`

`PromptBuilder.build(market_data, provider, jev_context: Optional[str] = None)`
与便捷函数 `build_prompt(..., jev_context=None)` 增加可选参数。
`jev_context` 非空时在 prompt 尾部追加：

```
## 快速模型初读（仅供参考，请独立判断）
{jev_context}
```

默认 `None` 时 prompt 输出与现状逐字节一致（现有测试零破坏）。

### 缓存

- `SignalCache` 逻辑不变；Jev 位于缓存之下（缓存命中不调 Jev 也不调 LLM）。
- adopted 路径产出的最终信号照常写入现有缓存（缓存键由市场状态派生，
  对信号来源无感知）。

### 可观测性

- 日志（统一前缀，便于 grep）：
  - `[Jev快车道] 采用/升级/跳过: ...`（每次 decide 一条，含 reason 与延迟）
  - `[Jev熔断] OPEN/CLOSED/HALF-OPEN: 原因`
- `AIClient.get_metrics()` 快车道计数（接入现有 metrics 输出）。
- 信号分布统计新增 `jev` source（复用现有
  `log_signal_distribution_summary`）。

## Error Handling

| 场景 | 行为 |
|---|---|
| `TypeSafeAuthError`（401/402） | 熔断 OPEN（6h 冷却）→ 升级 LLM；日志 WARNING 标明"欠费/鉴权失败" |
| `TypeSafeTimeoutError` / `TypeSafeAPIError` | 计入连续失败；达阈值熔断 OPEN（10min）；当次升级 LLM |
| 响应解析失败 | 按 `TypeSafeAPIError` 处理 |
| `mode=on` 但无 Key | `decide()` 直接返回 `disabled` + 一次性 WARNING，不发起请求 |
| 熔断 HALF-OPEN 探测成功 | 回 CLOSED，恢复快车道 |
| 熔断 HALF-OPEN 探测失败 | 重新 OPEN（按失败类型选择冷却时长） |
| 任何 Jev 侧异常 | 一律不阻塞交易循环：最坏情况 = 现有纯 LLM 行为 |

## Testing

TDD，全部 mock 外部依赖（aiohttp / TypeSafe API / LLM HTTP）。

1. `tests/unit/test_jev_typesafe_client.py`
   - 请求体构造（model/state/questions 正确序列化）
   - Choice / Noul 响应解析（含概率分布、confidence）
   - 错误分类：401/402 → AuthError；429/5xx → APIError（且重试 2 次）；
     超时 → TimeoutError；401 不重试
   - Key 脱敏不出现在日志
2. `tests/unit/test_jev_questions.py`
   - `build_state` 包含 price/rsi/trend/持仓等关键键；缺键不报错
   - 问题集结构：1 个 Choice（4 选项）+ 2 个 Noul
3. `tests/unit/test_jev_fast_lane.py`（决策矩阵全覆盖）
   - HIGH 置信 BUY/SELL/SHORT/HOLD → adopted
   - 低置信 → escalated + `jev_context` 非空且含概率分布
   - `is_high_risk_reversal` 超阈 → `risk_gate` 升级（即使主问题高置信）
   - shadow 模式 → 永不 adopted
   - `off`/无 Key → `disabled`，无网络调用
   - 熔断 OPEN → `circuit_open`，无网络调用
4. `tests/unit/test_jev_circuit_breaker.py`
   - 连续 N 次瞬态失败 → OPEN；冷却期内不请求
   - AuthError 单次 → OPEN（6h）
   - HALF-OPEN 探测成功 → CLOSED；失败 → 再 OPEN
5. `tests/unit/test_ai_client_fast_lane.py`（集成）
   - adopted：LLM HTTP 不被调用，下游 integrator 正常处理 Jev 信号
   - escalated：LLM 被调用且 prompt 含 `[Jev初读]` 上下文
   - 缓存命中：Jev 与 LLM 均不被调用
   - `fast_lane=None`：行为与现状完全一致（回归）
6. `tests/unit/test_prompt_builder_jev_context.py`
   - `jev_context=None`：prompt 与现状一致
   - 非空：追加"快速模型初读"小节

## Rollout

1. **Phase 0 — 合入**：`AI_FAST_LANE=off`（默认）。代码上线零行为变化，
   全量测试 + mypy 通过。
2. **Phase 1 — shadow 观察期**：`AI_FAST_LANE=shadow` + 配置真实 Key。
   Jev 每次都被调用并记录"本应如何判"，决策仍全部走 LLM。
   观察指标：Jev 与 LLM 一致率、Jev 延迟 p50/p99、`risk_gate` 触发率、
   欠费/错误率。用 `log_signal_distribution`（source=jev）与 LLM source
   对比。
3. **Phase 2 — 上线快车道**：观察期数据支持后 `AI_FAST_LANE=on`，
   初始保守阈值（BUY/SELL ≥0.75）。监控 `get_metrics()` 快车道计数。
4. **随时回退**：`AI_FAST_LANE=off`（或清空 Key）即回到纯 LLM 架构；
   Jev 账户故障时熔断器自动完成同等回退。

## References

- Jev / System One 介绍：https://docs.typesafe.ai/introduction
- Quick Start（SDK 与 `system_one` 用法）：https://docs.typesafe.ai/introduction/quickstart
- Choice / Score / Noul 原语：https://docs.typesafe.ai/primitives
- Confidence 与三段式用法：https://docs.typesafe.ai/confidence
- 架构模式（Confidence-Gated Routing 等）：https://docs.typesafe.ai/patterns
- HTTP API：`POST https://api.typesafe.ai/v1/systemone`
- 模型版本：pin `jev-1.13.0`（`jev-latest` 为移动指针，默认不用）
- 计费：按 input token（约 $0.042/M），输出免费；单次决策约 700 tokens ≈ $0.00003
