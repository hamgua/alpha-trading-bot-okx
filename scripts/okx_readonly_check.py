#!/usr/bin/env python3
"""OKX 只读诊断：余额/持仓/成交/订单历史 + BTC-USDT-SWAP 合约规格。

仅调用只读接口（balance/positions/fills/orders-history/public），不下任何单。
凭据从 .env 读取，不回显。

用法: python3 scripts/okx_readonly_check.py [env路径]
  - 容器内: /app/.env（默认）；主机上: 传入 .env 实际路径
  - 优先使用 ccxt（与 bot 同款客户端），无 ccxt 时退回原生 urllib

诊断 403 时脚本会打印响应体错误码，常见码：
  50110=无效 API key, 50113=签名错误, 50119=时间戳错误,
  50134=时间戳偏差, 1010/403 空体=通常 IP 白名单拦截
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

CANDIDATE_ENVS = [
    sys.argv[1] if len(sys.argv) > 1 else "/app/.env",
    "/app/.env",
    ".env",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
]
ENV_PATH = next((p for p in CANDIDATE_ENVS if os.path.isfile(p)), CANDIDATE_ENVS[0])


def load_env(path):
    if not os.path.isfile(path):
        raise SystemExit(
            f"找不到 .env 文件: {path}（用法: python3 scripts/okx_readonly_check.py <env路径>）"
        )
    vals = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            vals[k.strip()] = v.split("#", 1)[0].strip()
    return vals


env = load_env(ENV_PATH)
print(f"env 文件: {ENV_PATH}")
print(f"API Key: {env['OKX_API_KEY'][:4]}****(masked)")

fmt_ts = lambda ms: datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime(
    "%Y-%m-%d %H:%M:%S"
)


def run_with_ccxt():
    import ccxt  # noqa: 容器内有

    ex = ccxt.okx(
        {
            "apiKey": env["OKX_API_KEY"],
            "secret": env["OKX_SECRET"],
            "password": env["OKX_PASSWORD"],
            "enableRateLimit": True,
            "timeout": 20000,
        }
    )

    print("\n=== 账户余额 (ccxt) ===")
    bal = ex.fetch_balance()
    print(f"总权益(USD): {bal.get('USDT', {}).get('total')}")
    print(f"  可用: {bal.get('USDT', {}).get('free')}")
    info = bal.get("info", {})
    if isinstance(info, dict) and info.get("data"):
        print(f"  totalEq: {info['data'][0].get('totalEq')}")

    print("\n=== 当前持仓 (SWAP) ===")
    try:
        positions = ex.fetch_positions(["BTC-USDT-SWAP"])
    except Exception:
        positions = ex.fetch_positions()
    positions = [p for p in positions if float(p.get("contracts") or 0) > 0]
    if not positions:
        print("(无持仓)")
    for p in positions:
        print(
            f"  {p['symbol']} {p.get('side')}: 张数={p.get('contracts')} "
            f"开仓均价={p.get('entryPrice')} 杠杆={p.get('leverage')} "
            f"未实现盈亏={p.get('unrealizedPnl')}"
        )

    print("\n=== 近期成交记录 (limit 50) ===")
    fills = ex.fetch_my_trades(limit=50)
    if not fills:
        print("(无任何成交记录)")
    for f_ in fills:
        raw = f_.get("info", {})
        print(
            f"  {fmt_ts(f_['timestamp'])}Z {raw.get('instId', f_.get('symbol'))} "
            f"{f_['side']} 张数={raw.get('sz', f_.get('amount'))} "
            f"价格={f_['price']} 手续费={raw.get('fee')}"
        )

    print("\n=== 近期订单 (SWAP, limit 50) ===")
    try:
        orders = ex.fetch_orders(symbol="BTC/USDT:USDT", limit=50)
    except Exception as e:
        print(f"(fetch_orders 失败: {e})")
        orders = []
    if not orders:
        print("(无订单历史)")
    for o in orders:
        raw = o.get("info", {})
        print(
            f"  {fmt_ts(o['timestamp'])}Z {raw.get('instId', o.get('symbol'))} "
            f"{o['side']} sz={raw.get('sz', o.get('amount'))} 均价={raw.get('avgPx')} "
            f"状态={o['status']} tdMode={raw.get('tdMode')}"
        )

    print("\n=== BTC-USDT-SWAP 合约规格 ===")
    m = ex.fetch_market("BTC/USDT:USDT")
    contract_size = m.get("contractSize")
    limits = m.get("limits", {})
    print(f"  contractSize(ctVal)={contract_size} BTC/张")
    print(
        f"  min={limits.get('amount', {}).get('min')} "
        f"lot={limits.get('amount', {}).get('precision')} "
        f"(amount=张数)"
    )
    if contract_size:
        min_sz = limits.get("amount", {}).get("min") or 0.01
        notional = float(contract_size) * float(min_sz) * 85100
        print(f"  → 最小下单 {min_sz} 张 ≈ {notional:.2f} USDT 名义 (按 BTC≈85100)")
        print(f"  → 10x 杠杆保证金 ≈ {notional / 10:.2f} USDT")


def run_with_urllib():
    BASES = ["https://www.okx.com", "https://aws.okx.com"]

    def sign(ts, method, path, body=""):
        msg = f"{ts}{method}{path}{body}"
        mac = hmac.new(env["OKX_SECRET"].encode(), msg.encode(), hashlib.sha256)
        return base64.b64encode(mac.digest()).decode()

    def get(base, path):
        now = datetime.now(timezone.utc)
        ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
        req = urllib.request.Request(
            base + path,
            headers={
                "OK-ACCESS-KEY": env["OKX_API_KEY"],
                "OK-ACCESS-SIGN": sign(ts, "GET", path),
                "OK-ACCESS-TIMESTAMP": ts,
                "OK-ACCESS-PASSPHRASE": env["OKX_PASSWORD"],
                "Content-Type": "application/json",
                "User-Agent": "ccxt/4.4.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read().decode())
        except urllib.error.HTTPError as e:
            body = e.read().decode(errors="replace")
            raise RuntimeError(f"{base} {path} → HTTP {e.code}: {body}")

    for base in BASES:
        try:
            probe = get(base, "/api/v5/account/balance")
        except RuntimeError as e:
            print(f"\n[urllib 诊断] {e}")
            continue
        print(f"\n[urllib 诊断] {base} 可用，继续...")

        print("\n=== 账户余额 ===")
        for d in probe.get("data", []):
            print(f"总权益: {d.get('totalEq')} USD")
        break
    else:
        raise SystemExit("两个域名均 403/失败，见上方诊断输出")

    print("\n=== BTC-USDT-SWAP 合约规格 ===")
    inst = get(base, "/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP")
    for i in inst.get("data", []):
        print(
            f"  ctVal={i.get('ctVal')} BTC/张, lotSz={i.get('lotSz')}, "
            f"minSz={i.get('minSz')}"
        )
        if i.get("ctVal"):
            notional = float(i["ctVal"]) * float(i.get("minSz", 0.01)) * 85100
            print(
                f"  → 最小下单 {i.get('minSz')} 张 ≈ {notional:.2f} USDT 名义, "
                f"10x 保证金 ≈ {notional / 10:.2f} USDT"
            )
    print("\n(urllib 模式只查余额+规格；成交/订单请优先用 ccxt 模式重跑)")


print("\n--- 优先尝试 ccxt（与 bot 同款客户端） ---")
try:
    import ccxt  # noqa: F401

    run_with_ccxt()
except ImportError:
    print("(未安装 ccxt，退回 urllib 模式)")
    run_with_urllib()
except Exception as e:
    print(f"ccxt 模式失败: {type(e).__name__}: {e}")
    print("--- 退回 urllib 诊断模式 ---")
    run_with_urllib()
