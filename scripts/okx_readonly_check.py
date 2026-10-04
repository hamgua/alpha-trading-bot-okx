#!/usr/bin/env python3
"""OKX 只读诊断：余额/持仓/近期成交/订单历史 + BTC-USDT-SWAP 合约规格。

仅调用只读 GET 接口，不下任何单。凭据从 .env 读取，不回显。
用法: python3 scripts/okx_readonly_check.py [env路径]  (默认依次尝试 /app/.env、./.env、
仓库根 .env；在服务器主机或容器内均可运行)
"""

import base64
import hashlib
import hmac
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone

CANDIDATE_ENVS = [
    sys.argv[1] if len(sys.argv) > 1 else "/app/.env",
    "/app/.env",
    ".env",
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"),
]
ENV_PATH = next((p for p in CANDIDATE_ENVS if os.path.isfile(p)), CANDIDATE_ENVS[0])
BASE = "https://www.okx.com"


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
            v = v.split("#", 1)[0].strip()
            vals[k.strip()] = v
    return vals


env = load_env(ENV_PATH)
print(f"env 文件: {ENV_PATH}")
key = env["OKX_API_KEY"]
secret = env["OKX_SECRET"]
passphrase = env["OKX_PASSWORD"]
print(f"API Key: {key[:4]}****(masked)")


def sign(ts, method, path, body=""):
    msg = f"{ts}{method}{path}{body}"
    mac = hmac.new(secret.encode(), msg.encode(), hashlib.sha256)
    return base64.b64encode(mac.digest()).decode()


def get(path):
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"
    req = urllib.request.Request(
        BASE + path,
        headers={
            "OK-ACCESS-KEY": key,
            "OK-ACCESS-SIGN": sign(ts, "GET", path),
            "OK-ACCESS-TIMESTAMP": ts,
            "OK-ACCESS-PASSPHRASE": passphrase,
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())


# 1) 余额
print("\n=== 账户余额 ===")
bal = get("/api/v5/account/balance")
for d in bal.get("data", []):
    print(f"总权益: {d.get('totalEq')} USD")
    for det in d.get("details", []):
        if float(det.get("eq", 0) or 0) > 0:
            print(
                f"  {det['ccy']}: 权益={det.get('eq')} "
                f"可用={det.get('availBal')} 未实现={det.get('uPnl')}"
            )

# 2) 当前持仓
print("\n=== 当前持仓 (SWAP) ===")
pos = get("/api/v5/account/positions?instType=SWAP")
if not pos.get("data"):
    print("(无持仓)")
for p in pos.get("data", []):
    print(
        f"  {p['instId']} {p.get('posSide')}: 张数={p.get('pos')} "
        f"开仓均价={p.get('avgPx')} 杠杆={p.get('lever')} 未实现盈亏={p.get('uPnl')}"
    )

# 3) 近期成交（含手动单）
print("\n=== 近期成交记录 (limit 50, 含现货/合约全部) ===")
fills = get("/api/v5/trade/fills?limit=50")
if not fills.get("data"):
    print("(无任何成交记录)")
for f_ in fills.get("data", []):
    ts = datetime.fromtimestamp(f_["ts"] / 1000, tz=timezone.utc)
    print(
        f"  {ts.strftime('%Y-%m-%d %H:%M:%S')}Z {f_['instId']} {f_['side']} "
        f"张数={f_['sz']} 价格={f_['px']} 类型={f_.get('execType','-')} "
        f"手续费={f_.get('fee')}"
    )

# 4) 近期订单
print("\n=== 近期订单 (limit 50) ===")
orders = get("/api/v5/trade/orders-history?instType=SWAP&limit=50")
if not orders.get("data"):
    print("(无 SWAP 订单历史)")
for o in orders.get("data", []):
    ts = datetime.fromtimestamp(o["uTime"] / 1000, tz=timezone.utc)
    print(
        f"  {ts.strftime('%Y-%m-%d %H:%M:%S')}Z {o['instId']} {o['side']} "
        f"sz={o['sz']} 均价={o.get('avgPx','-')} 状态={o['state']} "
        f"类型={o.get('tdMode','-')}/{o.get('ordType','-')}"
    )

# 5) 合约规格（公开接口）
print("\n=== BTC-USDT-SWAP 合约规格 ===")
inst = get("/api/v5/public/instruments?instType=SWAP&instId=BTC-USDT-SWAP")
for i in inst.get("data", []):
    ct_val = i.get("ctVal")
    lot_sz = i.get("lotSz")
    min_sz = i.get("minSz")
    print(f"  ctVal={ct_val} BTC/张, lotSz={lot_sz}, minSz={min_sz}")
    if ct_val:
        notional_001 = float(ct_val) * float(min_sz)
        print(f"  → 最小下单 {min_sz} 张 = {notional_001:.5f} BTC")
        print(
            f"  → 10x 杠杆最小保证金 ≈ {notional_001 * 85100 / 10:.2f} USDT"
            f" (按 BTC≈85100 估算)"
        )
