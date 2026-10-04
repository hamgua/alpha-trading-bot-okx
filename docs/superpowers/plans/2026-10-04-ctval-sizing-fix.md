# 计划：ctVal 仓位单位修正（小余额可交易）

**日期**: 2026-10-04
**分支**: `fix/ctval-sizing`
**背景**: 生产账户 $7.295 无法开仓——`calculate_max_contracts` 公式
`余额×0.30×10/价格` 的量纲是 **BTC 数量**，但被当作 OKX 的 `sz`（张数，
1 张 = ctVal 0.01 BTC）直接下单。结果：(a) 小余额下公式结果 <0.01 最小
张数 → 永远开不了仓（9/28 两次 BUY 失败根因）；(b) 大余额下真实仓位 ≈
设计意图的 1/100（"30%×10x" 实际只用了 3% 余额保证金）。用户约束：
**不做大额入金，以 ~$7 小余额调教系统** → 必须修正单位让 bot 在小额
余额下能开 0.01-0.03 张。

## 关键事实（已核实）

- OKX BTC-USDT-SWAP 实测规格：ctVal=0.01 BTC/张，lotSz=0.01，minSz=0.01
  （0.01 张 ≈ $8.51 名义，10x 保证金 ≈ $0.85）
- `InstrumentSpec.normalize_size`：**ROUND_FLOOR** 截断到 lotSz，
  低于 minSz 抛 ValueError（安全方向）
- `client.instrument_spec` 属性：未初始化抛 RuntimeError
- `client.calculate_notional_usdt(amount, price)`：张数→真实名义 USDT
- `adaptive_bot` 消费同一个 `client.calculate_max_contracts`
  （adaptive_bot.py:1684，作为"账户容量张数"）→ 修正后语义对齐其
  R3/R4 修复的设计意图（容量=真实张数），adaptive 无需改动
- 账户实况：$7.295 余额、无持仓、生产环境零成交

## 修正后行为（验收基准）

- $7.295 @ BTC≈$85100：名义上限 $21.89 → 0.0257 张 → **截断 0.02 张**
  （$17.0 名义，保证金 $1.70 = 余额 23%；5bp 止损预期亏损 $0.0085）
- $1000：→ 3.52 张（$2996 名义，保证金 $299.6 ≈ 30%×1000，设计意图恢复）
- 规格不可用（public 接口失败）：**回退旧公式 + WARNING**（保守：
  小额下不开仓，绝不开错仓）
- 回撤总闸/单笔 10% 风控：在真实名义下生效（P1 反查同步修正）

## 任务

### Task 1 — 核心换算（market_data 语义 + client 单位转换）

**文件**: `alpha_trading_bot/exchange/market_data.py`,
`alpha_trading_bot/exchange/client.py`

1. `MarketDataService.calculate_max_contracts`：
   - docstring 明确返回**最大可交易 BTC 数量**（= 余额×usage×leverage÷价格），
     非张数；张数换算由 ExchangeClient 负责
   - 移除错误的 `contracts < 0.01` 检查（BTC 数量与张数最小单位混比；
     最小张数检查移到 client 层换算之后）；保留 balance≤0 分支
2. `ExchangeClient.calculate_max_contracts`（client.py:210，standard 与
   adaptive bot 共同入口）：
   ```
   btc_amount = await market_data.calculate_max_contracts(...)
   try:
       spec = self.instrument_spec          # RuntimeError 若未初始化
       contracts = float(f"{btc_amount / float(spec.contract_value):.4f}")
       contracts = self.normalize_order_size(contracts)   # ROUND_FLOOR
       if contracts < float(spec.minimum_size):
           logger.warning("可开张数 %.4f < 最小 %.4f，无法交易", ...)
           return 0.0
       logger.info("最大可开合约数: %.4f 张 (名义 %.2f USDT, ...)", ...)
       return contracts
   except (RuntimeError, ValueError) as e:
       logger.warning("合约规格不可用，回退旧仓位公式（保守）: %s", e)
       return btc_amount   # 旧行为
   ```
   - 日志必须含**真实名义 USDT**（spec.notional_usdt），便于调教期核对
3. 测试（tests/unit/test_contract_sizing.py，新文件）：
   - $7.295@85100 → 0.02 张（完整链路：0.0257 计算 → 截断 0.02）
   - 0.009 张场景（更小余额）→ 0.0（minSz 检查）
   - $1000 → 3.52 张（名义 ≈$2996，设计意图恢复）
   - spec=None → 返回旧公式值 + WARNING（mock instrument_spec 抛
     RuntimeError）
   - 真实 InstrumentSpec（ctVal=0.01, lotSz=0.01, minSz=0.01）构造，
     不用 mock 数学

### Task 2 — P1 反查名义修正 + standard bot 张数截断

**文件**: `alpha_trading_bot/core/bot.py`

1. `_apply_risk_backcheck(price, amount)`：
   - expected_loss 用真实名义：`notional = self._exchange.
     calculate_notional_usdt(amount, price)`；`expected_loss =
     notional × d`；缩仓公式 `amount = max_loss / (notional_per_unit × d)`
     其中 notional_per_unit = spec 单张名义（ctVal×price）
   - 规格不可用（RuntimeError/ValueError）→ 回退旧公式
     （amount×price×d，高估亏损 → 保守方向）+ WARNING
2. `_open_position`：风险反查之后、create_order 之前插入：
   ```
   try:
       amount = self._exchange.normalize_order_size(amount)
   except ValueError:
       logger.warning("[开仓] 张数截断后低于最小张数，取消开仓 (原 %.4f)", amount)
       return
   ```
   （保留既有 `amount < 0.01` 检查作纵深）
3. 测试（tests/unit/test_bot_risk_backcheck.py 追加）：
   - $7.295/0.02 张/5bp 止损：expected_loss $0.0085 ≤ $0.73 → 通过不缩
     （当前旧公式会误缩到放弃——本测试钉死修正）
   - 宽止损超限 → 按真实名义缩仓（数值断言）
   - spec 不可用回退（保守值断言 + WARNING）
   - _open_position：0.0257 → create_order 收到 sz=0.02（mock 断言参数）
   - _open_position：0.009 → 截断 0.00 → 取消（create_order 未调用）

### Task 3 — 全量回归 + 沙盒冒烟

1. 全量 pytest（基线 1096 + 新增，零回归）/ mypy（209 零新增）/ black
2. TEST_MODE 沙盒冒烟（OKX demo，TEST_MODE=true → ccxt 沙盒端点）：
   用 bot 的 exchange client `set_leverage(10)` + `create_order`
   （BTC/USDT:USDT buy 0.02 market）→ 断言订单被 demo 接受 →
   立即平掉（sell 0.02）→ 无残留持仓。demo 账户不可用时记录并降级
   （以单测为证据，不阻塞）
3. 报告：修正前后对照表（$7.295 / $100 / $1000 三档仓位、保证金、
   名义）

## 不变式

1. 正常路径（规格可用）：仓位 = 截断(余额×usage×leverage÷price÷ctVal)，
   保证金占用 ≤ usage×余额（30%）
2. 规格不可用：行为与修正前完全一致（保守回退，不引入新行为）
3. 所有风控（回撤总闸/单笔 10%/止损）语义不变，仅名义基准变真实
4. 零测试回归；mypy 零新增

## 明确不做

- 不动 adaptive_bot（其消费同一 client 入口，语义自动对齐）
- 不动 OKX 参数（杠杆 10x、usage 0.30 保持用户选择）
- 不动 prompt/信号层（P4 范畴）
