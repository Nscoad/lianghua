"""
币安 API 客户端管理 — 时间同步、限流、错误处理
"""
import time
import requests as _requests
from binance_common.configuration import ConfigurationRestAPI
from binance_sdk_derivatives_trading_usds_futures import DerivativesTradingUsdsFutures
from config import get_futures_config

_LAST_SYNC = 0
_TIME_OFFSET = 0.0  # 本地时间与币安服务器时间差值（秒），本地慢为正


def _fetch_server_time() -> float:
    """获取币安服务器时间戳（毫秒）"""
    try:
        resp = _requests.get(
            "https://fapi.binance.com/fapi/v1/time",
            timeout=5,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        if resp.status_code == 200:
            return resp.json()["serverTime"] / 1000.0
    except Exception:
        pass
    return 0


def _sync_system_time():
    """校准本地时间偏移（每60秒限频一次）"""
    global _LAST_SYNC, _TIME_OFFSET
    now = time.time()
    if now - _LAST_SYNC < 60:
        return False
    _LAST_SYNC = now
    try:
        server_ts = _fetch_server_time()
        if server_ts > 0:
            _TIME_OFFSET = server_ts - time.time()
            print(f"[时间同步] 本地与币安服务器时差 {_TIME_OFFSET*1000:.0f}ms")
            if abs(_TIME_OFFSET) > 1:
                print("  -> 已记录偏移，后续请求自动补偿")
            return True
        print("[时间同步] 获取服务器时间失败，跳过")
        return False
    except Exception as e:
        print(f"[时间同步] 异常: {e}")
        return False


def _is_timestamp_error(e) -> bool:
    """判断是否为 -1021 时间戳错误"""
    err = str(e)
    return "-1021" in err or "Timestamp" in err


def _recover_client():
    """重新初始化客户端（时间同步后调用）"""
    global client
    client = get_client()


def get_client():
    cfg = get_futures_config()
    config = ConfigurationRestAPI(
        api_key=cfg["api_key"],
        api_secret=cfg["api_secret"],
        base_path=cfg["base_url"],
        compression=False,
        timeout=10000,
    )
    return DerivativesTradingUsdsFutures(config_rest_api=config)


client = get_client()

# 全局API限流：相邻请求至少间隔200ms
_cache: dict = {}
_last_api_time = 0.0


def _rate_limit():
    """确保两次API调用之间至少间隔200ms"""
    global _last_api_time
    now = time.time()
    elapsed = now - _last_api_time
    if elapsed < 0.2:
        time.sleep(0.2 - elapsed)
    _last_api_time = time.time()


def _handle_api_error(e, context: str):
    """
    处理API错误，遇到时间戳错误时自动修复
    返回 True=已处理重试完成, False=未处理返回None
    """
    if not _is_timestamp_error(e):
        print(f"{context}: {e}")
        return None

    print(f"[API] {context} 失败: 时间戳错误，自动恢复中...")
    _sync_system_time()
    time.sleep(1)
    _recover_client()
    return True
