"""
资金费率追踪 — 从币安查询资金费率历史和当期费率，记录到 funding_records 表
"""
import hashlib
import hmac
import time
import urllib.parse

import requests as _requests

from config import get_futures_config, USE_TESTNET
from core.client import _TIME_OFFSET
from utils.db import insert_funding_record

# 测试网不支持 income API，标记只提示一次
_TESTNET_WARNED = False


def _signed_get(path: str, params: dict | None = None) -> list | dict:
    """发起带签名的币安 API GET 请求"""
    cfg = get_futures_config()
    params = params or {}
    params["timestamp"] = int((time.time() + _TIME_OFFSET) * 1000)
    query = urllib.parse.urlencode(params)
    signature = hmac.new(
        cfg["api_secret"].encode(), query.encode(), hashlib.sha256
    ).hexdigest()
    params["signature"] = signature

    url = f"{cfg['base_url']}{path}"
    try:
        resp = _requests.get(
            url,
            headers={"X-MBX-APIKEY": cfg["api_key"], "User-Agent": "Mozilla/5.0"},
            params=params,
            timeout=10,
        )
        if resp.status_code == 200:
            return resp.json()
        # 测试网可能不支持 funding income API
        if resp.status_code in (400, 404):
            return []
        print(f"[资金费率] {path} 返回 {resp.status_code}: {resp.text[:200]}")
        return []
    except Exception as e:
        print(f"[资金费率] {path} 请求失败: {e}")
        return []


def check_and_record_funding(symbol: str | None = None, position_qty: float = 0) -> float:
    """
    查询该币种的资金费率收入流水，将新记录写入 funding_records 表。
    返回本次查询到的新增资金费支出总和（正=支出，负=收入）。

    实盘可用，测试网不支持此 API 会静默跳过。
    """
    global _TESTNET_WARNED
    if USE_TESTNET:
        if not _TESTNET_WARNED:
            print("[资金费率] 测试网不支持 income API，跳过资金费率追踪")
            _TESTNET_WARNED = True
        return 0.0
    params = {"incomeType": "FUNDING_FEE", "limit": 10}
    if symbol:
        params["symbol"] = symbol

    data = _signed_get("/fapi/v1/income", params)
    if not isinstance(data, list) or not data:
        return 0.0

    # 查询已有记录的 time 去重
    from utils.db import _get_trade_conn

    conn = _get_trade_conn()
    existing = set()
    for row in conn.execute(
        "SELECT time FROM funding_records"
    ).fetchall():
        existing.add(row["time"])

    total_new = 0.0
    for item in data:
        record_time = _fmt_income_time(item.get("time", 0))
        if record_time in existing:
            continue

        payment = float(item.get("income", 0))  # 正=支出，负=收入
        qty = float(item.get("qty", position_qty))
        insert_funding_record({
            "time": record_time,
            "symbol": item.get("symbol", symbol or ""),
            "side": "LONG" if float(item.get("qty", 0)) >= 0 else "SHORT",
            "funding_rate": float(item.get("fundingRate", 0)),
            "payment": round(payment, 4),
            "mark_price": float(item.get("markPrice", 0)),
            "position_qty": abs(qty),
        })
        total_new += payment
        existing.add(record_time)

    return round(total_new, 4)


def _fmt_income_time(ts_ms: int) -> str:
    """将毫秒时间戳转为 ISO 格式字符串"""
    if not ts_ms:
        from datetime import datetime as dt
        return dt.now().isoformat()
    from datetime import datetime as dt, timezone
    return dt.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat()
