#!/usr/bin/env python3
"""OKX 沙盒（模拟盘）冒烟测试 —— 用 bot 自己的 ExchangeClient 自开自平。

背景: OKX 私有接口（含沙盒）有 IP 白名单，仅生产服务器（140.206.177.114）可达，
本脚本必须在生产容器内执行；本地只做语法/导入自验，不实际执行。

原理: TEST_MODE=true → ExchangeClient.initialize() → ccxt set_sandbox_mode(True)
（OKX 模拟盘通过 x-simulated-trading:1 请求头启用），只动 demo 账户，不碰真实资金。
ExchangeClient.create_order 在 TEST_MODE=true 时会跳过真实下单（本地模拟单保护）；
本脚本在确认底层 ccxt 已锁定模拟盘端点后关闭该本地保护开关，让订单走 bot 自己的
下单链路（OrderService → OKX 模拟盘下单接口）。

流程:
  0. 幂等收尾: 启动先查 BTC-USDT-SWAP 持仓，如有上次残留仓位先市价平掉
  1. 从 .env 读 OKX 凭据（路径参数化，默认依次 /app/.env → ./.env → 仓库根 .env）
  2. ExchangeClient(TEST_MODE=true) 初始化 + 沙盒双重校验 + set_leverage(10)
  3. 下 0.02 张市价买单（BTC/USDT:USDT, buy, market）→ 轮询至成交（≤20s）
  4. 验证成交张数=0.02 → 立即下 0.02 张市价卖单（reduceOnly）平仓 → 轮询至完成
  5. 收尾: 查持仓确认归零，打印摘要（订单 id / 成交均价 / 手续费 / 保证金占用）

失败语义 / 退出码:
  0 = 冒烟通过（开平闭环完成，无残留持仓）
  1 = 验证失败（未成交 / 部分成交 / 平仓失败）；退出前必已尝试清掉残留仓位
  2 = 环境类问题（403 IP 白名单 / 凭据错误 / 模拟盘未开通 / 余额不足），打印指引
  3 = 残留仓位未能平掉（需人工立即处理，勿盲目重跑）

服务器执行（生产容器内）:
  docker exec <容器名> python3 /app/scripts/okx_sandbox_smoke.py

本地自验（不实际执行，本地私有接口 403）:
  python3 -c "import ast; ast.parse(open('scripts/okx_sandbox_smoke.py').read())"
  black --check scripts/okx_sandbox_smoke.py
"""

import asyncio
import logging
import os
import sys
import time
from typing import TYPE_CHECKING
from typing import Any, Dict, List, Optional

if TYPE_CHECKING:  # 仅类型提示用，运行时不导入 bot 依赖
    from alpha_trading_bot.exchange.client import ExchangeClient
    from alpha_trading_bot.exchange.models.orders import OrderResult

INST_ID = "BTC-USDT-SWAP"
SYMBOL = "BTC/USDT:USDT"
LEVERAGE = 10
CONTRACTS = 0.02  # 0.02 张 ≈ $17 名义（ctVal=0.01 BTC, BTC≈$8.5万）, 10x 保证金 ≈ $1.7
POLL_TIMEOUT = 20.0  # 单笔订单等待终态上限（秒）
POLL_INTERVAL = 0.5  # 订单状态轮询间隔（秒）
CLOSE_ATTEMPTS = 3  # 残留仓位幂等收尾最大平仓尝试次数

CANDIDATE_ENVS = [
    sys.argv[1] if len(sys.argv) > 1 else "/app/.env",
    "/app/.env",
    ".env",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
]
ENV_PATH = next((p for p in CANDIDATE_ENVS if os.path.isfile(p)), CANDIDATE_ENVS[0])


def load_env(path: str) -> Dict[str, str]:
    """解析 .env 文件（与 okx_readonly_check.py 同款规则，支持行内 # 注释）。"""
    if not os.path.isfile(path):
        raise SystemExit(
            f"找不到 .env 文件: {path}（用法: python3 scripts/okx_sandbox_smoke.py <env路径>）"
        )
    vals: Dict[str, str] = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.split("#", 1)[0].strip()
    return vals


def guide_for_error(text: Any) -> str:
    """把 OKX 报错（消息/错误码）映射为可操作指引。"""
    t = str(text)
    if "403" in t or "401" in t:
        return (
            "疑似 IP 白名单拦截（OKX 私有接口含沙盒仅生产服务器 140.206.177.114 可达）；"
            "请改在生产容器内执行: docker exec <容器名> python3 /app/scripts/okx_sandbox_smoke.py"
        )
    if "50110" in t:
        return (
            "无效 API Key: 请检查 .env 的 OKX_API_KEY（需为已开通模拟交易的 demo key）"
        )
    if "50111" in t:
        return "API 密码（passphrase）错误: 请检查 .env 的 OKX_PASSWORD"
    if "50113" in t:
        return "签名错误: 请检查 .env 的 OKX_SECRET"
    if "50119" in t or "50134" in t or "timestamp" in t.lower():
        return "时间戳偏差: 请同步服务器系统时间（NTP）后重试"
    if "51000" in t or "51008" in t or "51115" in t:
        return "余额不足: 演示账户 USDT 不足，请先在 OKX 网页（模拟交易页）给 demo 账户充值"
    if "51023" in t:
        return "杠杆未设置: 本脚本下单前会自动设置 10x，请检查 demo 账户杠杆权限后重试"
    if "51025" in t:
        return "持仓中不可调杠杆: 本脚本启动时会幂等平掉残留仓位，请重跑"
    if "51105" in t:
        return (
            f"下单张数低于最小张数: 本脚本用 {CONTRACTS} 张，请检查 {INST_ID} 的 minSz"
        )
    low = t.lower()
    if "simulated" in low or "demo" in low or "mock" in low:
        return (
            "模拟盘未开通 / API Key 无模拟交易权限: "
            "请先在 OKX 网页开通模拟盘，并使用模拟交易页签创建的 demo API Key"
        )
    return f"未知错误，请对照 OKX 官方错误码文档处理: {t[:300]}"


def fail_env(msg: str, guidance: Optional[str] = None) -> int:
    """环境类失败：打印指引后以退出码 2 结束（不残留仓位场景）。"""
    print(f"[SMOKE][ENV] {msg}")
    print(f"[SMOKE][ENV] 指引: {guidance or guide_for_error(msg)}")
    return 2


async def raw_positions(client: "ExchangeClient") -> List[Dict[str, Any]]:
    """查 BTC-USDT-SWAP 原始持仓列表（无持仓返回空列表）。"""
    from alpha_trading_bot.exchange.okx_raw import ensure_okx_success, get_callable

    method = get_callable(
        client.exchange, "private_get_account_positions", "privateGetAccountPositions"
    )
    if method is None:
        raise RuntimeError("OKX 持仓接口不可用")
    loop = asyncio.get_running_loop()
    response = await loop.run_in_executor(None, lambda: method({"instId": INST_ID}))
    ensure_okx_success(response, "positions")
    return response.get("data") or []


async def raw_order_detail(client: "ExchangeClient", order_id: str) -> Dict[str, Any]:
    """查订单原始详情（含 fee/avgPx/accFillSz），失败返回 {}（摘要降级，不中断）。"""
    from alpha_trading_bot.exchange.okx_raw import first_data, get_callable

    if not order_id:
        return {}
    method = get_callable(
        client.exchange, "private_get_trade_order", "privateGetTradeOrder"
    )
    if method is None:
        return {}
    try:
        loop = asyncio.get_running_loop()
        response = await loop.run_in_executor(
            None, lambda: method({"instId": INST_ID, "ordId": order_id})
        )
    except Exception as e:
        print(f"[SMOKE] 查询订单详情 {order_id} 失败（不影响主流程）: {e}")
        return {}
    return first_data(response) if isinstance(response, dict) else {}


async def fetch_price(client: "ExchangeClient") -> float:
    """取 BTC/USDT 最新价（公共接口，用于保证金占用预估）。"""
    if client.exchange is None:
        raise RuntimeError("exchange client 未初始化")
    exchange = client.exchange
    loop = asyncio.get_running_loop()
    ticker = await loop.run_in_executor(None, lambda: exchange.fetch_ticker(SYMBOL))
    last = float(ticker.get("last") or 0)
    if last <= 0:
        raise RuntimeError("获取 BTC/USDT 最新价失败")
    return last


async def poll_order(client: "ExchangeClient", order_id: str) -> "OrderResult":
    """轮询订单状态至终态或 POLL_TIMEOUT 秒，返回最新 OrderResult。"""
    deadline = time.monotonic() + POLL_TIMEOUT
    result = await client.get_order_status(order_id, SYMBOL)
    while not result.is_terminal and time.monotonic() < deadline:
        await asyncio.sleep(POLL_INTERVAL)
        result = await client.get_order_status(order_id, SYMBOL)
    return result


async def ensure_flat(client: "ExchangeClient", stage: str) -> bool:
    """幂等收尾：如有 BTC-USDT-SWAP 残留仓位，市价 reduceOnly 平仓直至确认归零。

    确认归零返回 True；平仓尝试达 CLOSE_ATTEMPTS 次后仓位仍在（或持仓查询持续
    失败无法确认）返回 False，调用方以退出码 3 结束（需人工介入）。
    """
    from alpha_trading_bot.exchange.models.orders import OrderIntent
    from alpha_trading_bot.exchange.okx_raw import to_float

    attempts = 0
    while True:
        try:
            positions = await raw_positions(client)
        except Exception as e:
            print(f"[SMOKE][{stage}] 持仓查询失败（第 {attempts + 1} 次）: {e}")
            if attempts >= CLOSE_ATTEMPTS:
                return False
            attempts += 1
            await asyncio.sleep(1.0)
            continue

        pos = next((p for p in positions if to_float(p.get("pos")) != 0.0), None)
        if pos is None:
            return True
        if attempts >= CLOSE_ATTEMPTS:
            return False

        attempts += 1
        contracts = abs(to_float(pos.get("pos")))
        side = "sell" if to_float(pos.get("pos")) > 0 else "buy"
        direction = "多头" if side == "sell" else "空头"
        print(
            f"[SMOKE][{stage}] 检测到残留仓位 {contracts} 张（{direction}），"
            f"市价平仓（第 {attempts}/{CLOSE_ATTEMPTS} 次）"
        )
        result = await client.create_order_with_status(
            SYMBOL, side, contracts, None, "market", OrderIntent.REDUCE
        )
        if not result.order_id or result.is_rejected:
            print(
                f"[SMOKE][{stage}] 平仓单失败: {result.error_message or result.error_code}"
            )
            await asyncio.sleep(1.0)
            continue
        final = await poll_order(client, result.order_id)
        if final.filled_amount >= contracts - 1e-9:
            print(f"[SMOKE][{stage}] 残留仓位平仓成交: 订单 {result.order_id}")
        else:
            print(
                f"[SMOKE][{stage}] 平仓单未完全成交: {final.filled_amount}/{contracts}，"
                f"复查后继续收尾"
            )
        await asyncio.sleep(0.5)


async def snapshot_margin(client: "ExchangeClient") -> Dict[str, Any]:
    """持仓期间保证金占用快照（摘要用）：名义 / imr / 原始 margin 字段。"""
    from alpha_trading_bot.exchange.okx_raw import to_float

    out: Dict[str, Any] = {
        "notional": None,
        "imr": None,
        "margin": None,
        "entry": None,
        "mark": None,
    }
    try:
        positions = await raw_positions(client)
    except Exception as e:
        print(f"[SMOKE] 保证金快照查询失败（不影响主流程）: {e}")
        return out
    for p in positions:
        pos = to_float(p.get("pos"))
        if pos == 0.0:
            continue
        ct_val = float(client.instrument_spec.contract_value)
        mark = to_float(p.get("markPx"))
        out.update(
            {
                "notional": abs(pos) * ct_val * mark if mark > 0 else None,
                "imr": to_float(p.get("imr")) or None,
                "margin": to_float(p.get("margin")) or None,
                "entry": to_float(p.get("avgPx")) or None,
                "mark": mark or None,
            }
        )
        break
    return out


async def abort_with_cleanup(client: "ExchangeClient", code: int, msg: str) -> int:
    """失败退出前幂等清仓（保证绝不留仓），返回退出码。"""
    print(f"[SMOKE][FAIL] {msg}")
    if not await ensure_flat(client, "失败收尾"):
        print(
            "[SMOKE][严重] 残留仓位未能平掉，请立即人工处理！"
            "（勿盲目重跑；用 scripts/okx_readonly_check.py 查仓位）"
        )
        return 3
    return code


async def run_smoke(env: Dict[str, str]) -> int:
    """冒烟主流程，返回进程退出码（见模块 docstring 退出码表）。"""
    from alpha_trading_bot.exchange.client import ExchangeClient
    from alpha_trading_bot.exchange.models.orders import OrderIntent

    client = ExchangeClient(
        api_key=env["OKX_API_KEY"],
        secret=env["OKX_SECRET"],
        password=env["OKX_PASSWORD"],
        symbol=SYMBOL,
        test_mode=True,
    )

    # 1) 初始化: TEST_MODE=true → ccxt set_sandbox_mode(True) → OKX 模拟盘端点
    try:
        await client.initialize()
    except Exception as e:
        return fail_env(f"ExchangeClient 初始化失败: {e}")

    # 2) 沙盒双重校验: 底层 ccxt 必须确实带模拟盘头，否则拒绝下单（防误实盘）
    headers = getattr(client.exchange, "headers", None) or {}
    options = getattr(client.exchange, "options", None) or {}
    if headers.get("x-simulated-trading") != "1" or not options.get("sandboxMode"):
        return fail_env(
            "沙盒模式校验失败（x-simulated-trading=1 / sandboxMode 缺失），拒绝下单",
            "请确认以 TEST_MODE=true 初始化，且 ccxt 版本支持 OKX 模拟盘",
        )
    print("[SMOKE] 沙盒模式已确认: x-simulated-trading=1（仅 OKX 模拟盘 / demo 账户）")

    # ExchangeClient.create_order 在 TEST_MODE=true 时跳过真实下单（本地模拟单保护）；
    # 底层 client 已锁定模拟盘端点，此处关闭本地保护开关，让订单走 bot 自己的下单链路
    client.test_mode = False

    # 3) 幂等收尾: 上次运行残留的 BTC-USDT-SWAP 仓位先平掉
    if not await ensure_flat(client, "启动清仓"):
        print(
            "[SMOKE][严重] 启动清仓失败（持仓查询失败或平仓失败），"
            "无法确认无残留仓位，退出（退出码 3），请人工处理"
        )
        return 3

    # 4) 余额与保证金充足性
    balance = await client.get_balance()
    if balance <= 0:
        return fail_env(
            "demo 账户可用 USDT 余额为 0（或余额查询失败）",
            "请先在 OKX 网页开通模拟盘（模拟交易页）并为 demo 账户充值",
        )
    try:
        price = await fetch_price(client)
    except Exception as e:
        return fail_env(f"获取行情失败: {e}")
    ct_val = float(client.instrument_spec.contract_value)
    notional_need = CONTRACTS * ct_val * price
    margin_need = notional_need / LEVERAGE * 1.2  # 含 20% 缓冲
    print(
        f"[SMOKE] demo 余额: {balance:.4f} USDT | 价格: {price:.2f} | "
        f"ctVal: {ct_val} BTC/张"
    )
    if balance < margin_need:
        return fail_env(
            f"余额不足: {balance:.4f} USDT < 所需保证金约 {margin_need:.4f} USDT",
            (
                f"0.02 张 ≈ {notional_need:.2f} USDT 名义 @ {LEVERAGE}x（含 20% 缓冲），"
                "请先给 demo 账户充值"
            ),
        )

    # 5) 设置杠杆 10x（交叉保证金）
    try:
        await client.set_leverage(LEVERAGE, SYMBOL)
        print(f"[SMOKE] 杠杆已设置: {LEVERAGE}x（cross）")
    except Exception as e:
        return await abort_with_cleanup(client, 2, f"设置杠杆 {LEVERAGE}x 失败: {e}")

    # 6) 下 0.02 张市价买单 → 轮询至成交（≤20s）
    buy = await client.create_order_with_status(
        SYMBOL, "buy", CONTRACTS, None, "market", OrderIntent.OPEN
    )
    if not buy.order_id:
        return await abort_with_cleanup(
            client, 1, f"买单提交失败: {buy.error_message or '未知错误'}"
        )
    if buy.is_rejected:
        return await abort_with_cleanup(
            client,
            2,
            f"买单被拒: {buy.error_message or ''} (错误码 {buy.error_code or 'n/a'})",
        )
    print(
        f"[SMOKE] 买单已提交: 订单 {buy.order_id}，轮询至终态（≤{POLL_TIMEOUT:.0f}s）..."
    )
    buy = await poll_order(client, buy.order_id)
    if buy.filled_amount < CONTRACTS - 1e-9:
        detail = await raw_order_detail(client, buy.order_id)
        return await abort_with_cleanup(
            client,
            1,
            (
                f"买单未完全成交: 状态={buy.status.value}, "
                f"成交={buy.filled_amount}/{CONTRACTS} 张, "
                f"avgPx={detail.get('avgPx', buy.average_price or 'n/a')}, "
                f"错误={buy.error_message or 'n/a'}"
            ),
        )
    buy_detail = await raw_order_detail(client, buy.order_id)
    buy_fee = buy_detail.get("fee", "n/a")
    buy_avg = buy_detail.get("avgPx") or buy.average_price
    print(
        f"[SMOKE] 买单成交: {buy.filled_amount} 张, 均价 {buy_avg}, 手续费 {buy_fee} USDT"
    )

    # 7) 保证金占用快照（持仓期间）
    snap = await snapshot_margin(client)

    # 8) 立即下 0.02 张市价卖单（reduceOnly）平仓 → 轮询至完成
    sell = await client.create_order_with_status(
        SYMBOL, "sell", CONTRACTS, None, "market", OrderIntent.REDUCE
    )
    if not sell.order_id or sell.is_rejected:
        return await abort_with_cleanup(
            client,
            1,
            f"平仓单失败: {sell.error_message or sell.error_code or '未知错误'}",
        )
    print(
        f"[SMOKE] 平仓单已提交: 订单 {sell.order_id}，轮询至终态（≤{POLL_TIMEOUT:.0f}s）..."
    )
    sell = await poll_order(client, sell.order_id)
    if sell.filled_amount < CONTRACTS - 1e-9:
        return await abort_with_cleanup(
            client,
            1,
            f"平仓单未完全成交: 状态={sell.status.value}, 成交={sell.filled_amount} 张",
        )
    sell_detail = await raw_order_detail(client, sell.order_id)
    sell_fee = sell_detail.get("fee", "n/a")
    sell_avg = sell_detail.get("avgPx") or sell.average_price
    print(
        f"[SMOKE] 平仓成交: {sell.filled_amount} 张, 均价 {sell_avg}, 手续费 {sell_fee} USDT"
    )

    # 9) 收尾验证: 持仓必须归零
    try:
        flat = all(float(p.get("pos") or 0) == 0.0 for p in await raw_positions(client))
    except Exception as e:
        flat = False
        print(f"[SMOKE] 收尾持仓查询失败: {e}")
    if not flat:
        return await abort_with_cleanup(client, 3, "收尾验证: 平仓后仍有残留仓位")

    # 10) 结果摘要
    notional = snap.get("notional")
    imr = snap.get("imr")
    est_margin = notional * imr if (notional is not None and imr is not None) else None
    print("")
    print("=" * 62)
    print("OKX 沙盒冒烟测试 —— 结果摘要")
    print("=" * 62)
    print("模式:        OKX 模拟盘（x-simulated-trading=1, 仅 demo 账户）")
    print(f"杠杆:        {LEVERAGE}x (cross) | ctVal={ct_val} BTC/张")
    print(
        f"买单:        id={buy.order_id}, 成交 {buy.filled_amount} 张, "
        f"均价 {buy_avg}, 手续费 {buy_fee} USDT"
    )
    print(
        f"平仓卖单:    id={sell.order_id}, 成交 {sell.filled_amount} 张, "
        f"均价 {sell_avg}, 手续费 {sell_fee} USDT"
    )
    if notional is not None:
        print(f"保证金占用:  名义 {notional:.2f} USDT @ 峰值价 {snap.get('mark')}")
        if est_margin is not None:
            pct = est_margin / balance * 100 if balance > 0 else None
            pct_s = f"（≈余额的 {pct:.1f}%）" if pct is not None else ""
            print(f"            imr={imr}, 估算保证金 {est_margin:.4f} USDT {pct_s}")
        raw_m = snap.get("margin")
        if raw_m is not None:
            print(f"            持仓原始 margin 字段: {raw_m} USDT")
    else:
        print("保证金占用:  快照不可用（不影响开平验证结论）")
    print("残留持仓:    0（已确认归零）")
    print("结果:        ✅ 冒烟通过（开平闭环完成，无残留仓位）")
    print("=" * 62)
    return 0


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    env = load_env(ENV_PATH)
    missing = [
        k for k in ("OKX_API_KEY", "OKX_SECRET", "OKX_PASSWORD") if not env.get(k)
    ]
    if missing:
        return fail_env(f".env 缺少必需凭据: {', '.join(missing)}", "请在 .env 补全")
    print(f"env 文件: {ENV_PATH}")
    print(f"API Key: {env['OKX_API_KEY'][:4]}****(masked)")

    # 延迟导入 bot 模块: 保证本脚本文件在缺少依赖的环境（本地自验）下也可被解析
    try:
        import ccxt  # noqa: F401

        from alpha_trading_bot.exchange.client import ExchangeClient  # noqa: F401
    except ImportError as e:
        return fail_env(
            f"缺少运行依赖: {e}",
            "请在生产容器内执行（需安装 ccxt 与 alpha_trading_bot 包）",
        )

    print(
        f"[SMOKE] 目标: {SYMBOL} 市价买入 {CONTRACTS} 张 → 验证 → 市价平仓（自开自平）"
    )
    try:
        return asyncio.run(run_smoke(env))
    except KeyboardInterrupt:
        print("[SMOKE] 用户中断（Ctrl-C）；如已开仓请重跑本脚本（启动时幂等清仓）")
        return 1


if __name__ == "__main__":
    sys.exit(main())
