"""
代理管理器 — 检测 Clash API 节点状态，连接不稳时自动切换节点
"""
import json
import socket
import threading
import time
import urllib.request
from dataclasses import dataclass, field
from typing import Any

# ==================== Clash API 发现 ====================

_CLASH_API_CACHE: dict[str, Any] = {}
_CLASH_API_CACHE_TTL = 60  # 发现一次后缓存60秒
_LAST_DISCOVERY = 0.0

# Clash 常见 API 端口（按优先级）
COMMON_PORTS = [9090, 9091, 9092, 7890, 54652]

# ==================== 配置 ====================

# 用于测速的目标（测试代理是否可用）
SPEED_TEST_URLS = [
    "https://fapi.binance.com/fapi/v1/time",
    "https://api.binance.com/api/v3/ping",
    "https://www.baidu.com",
]
SPEED_TEST_TIMEOUT = 5  # 单个节点测速超时（秒）

# 触发代理切换的连续失败次数
FAIL_THRESHOLD = 3

# 全自动切换周期（秒）
AUTO_CHECK_INTERVAL = 300  # 5分钟

# 统计信息
_stats = {"checks": 0, "switches": 0, "failures": 0, "last_switch": ""}


# ==================== Clash API 封装 ====================

def discover_clash_api() -> dict | None:
    """
    自动发现 Clash 外部控制器地址和密钥。
    扫描常见端口，尝试无密码 Bearer Token。
    返回 {"base_url": str, "secret": str} 或 None。
    """
    global _LAST_DISCOVERY
    now = time.time()
    if _LAST_DISCOVERY > 0 and now - _LAST_DISCOVERY < _CLASH_API_CACHE_TTL:
        return _CLASH_API_CACHE.get("api")

    # 先通过外部命令找到 clash 进程的监听端口
    _scan_from_process()

    for port in COMMON_PORTS:
        base = f"http://127.0.0.1:{port}"
        # 尝试无密码
        try:
            req = urllib.request.Request(f"{base}/version", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    _CLASH_API_CACHE["api"] = {"base_url": base, "secret": ""}
                    _LAST_DISCOVERY = time.time()
                    return _CLASH_API_CACHE["api"]
        except Exception:
            pass

        # 尝试 Bearer 空密码
        try:
            req = urllib.request.Request(f"{base}/version", method="GET")
            req.add_header("Authorization", "Bearer ")
            with urllib.request.urlopen(req, timeout=2) as resp:
                if resp.status == 200:
                    _CLASH_API_CACHE["api"] = {"base_url": base, "secret": ""}
                    _LAST_DISCOVERY = time.time()
                    return _CLASH_API_CACHE["api"]
        except Exception:
            pass

    _LAST_DISCOVERY = time.time()
    _CLASH_API_CACHE["api"] = None
    return None


def _scan_from_process():
    """从本地网络连接中扫描 clash 进程的 API 监听端口"""
    try:
        import subprocess
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if "LISTENING" not in line:
                continue
            parts = line.strip().split()
            if len(parts) < 5:
                continue
            # 提取地址和端口
            addr = parts[1] if len(parts) > 1 else ""
            if "127.0.0.1" not in addr and "0.0.0.0" not in addr:
                continue
            try:
                port = int(addr.split(":")[-1])
            except (ValueError, IndexError):
                continue
            if port not in COMMON_PORTS and 1024 < port < 65535:
                COMMON_PORTS.append(port)
    except Exception:
        pass


def _clash_api_get(path: str) -> dict | None:
    """向 Clash API 发送 GET 请求"""
    api = discover_clash_api()
    if not api:
        return None
    try:
        req = urllib.request.Request(f"{api['base_url']}{path}", method="GET")
        if api["secret"]:
            req.add_header("Authorization", f"Bearer {api['secret']}")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _clash_api_put(path: str, data: dict) -> bool:
    """向 Clash API 发送 PUT 请求（用于切换节点）"""
    api = discover_clash_api()
    if not api:
        return False
    try:
        body = json.dumps(data).encode()
        req = urllib.request.Request(
            f"{api['base_url']}{path}", data=body, method="PUT",
        )
        req.add_header("Content-Type", "application/json")
        if api["secret"]:
            req.add_header("Authorization", f"Bearer {api['secret']}")
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status in (200, 204)
    except Exception:
        return False


# ==================== 节点管理 ====================

@dataclass
class ProxyNode:
    """单个代理节点信息"""
    name: str
    type: str
    delay: int = -1       # 延迟(ms)，-1=未测
    alive: bool = False
    history: list = field(default_factory=list)


def get_all_proxies() -> dict[str, list[ProxyNode]]:
    """
    获取所有代理分组及节点列表
    返回: {"组名": [ProxyNode, ...], ...}
    """
    data = _clash_api_get("/proxies")
    if not data:
        return {}

    groups = {}
    for name, info in data.get("proxies", {}).items():
        if not isinstance(info, dict):
            continue
        node_type = info.get("type", "")
        if node_type in ("Selector", "URLTest", "Fallback"):
            # 这是代理组，获取其节点
            nodes = []
            for child in info.get("all", []):
                child_info = data.get("proxies", {}).get(child, {})
                if isinstance(child_info, dict) and child_info.get("type") in ("Shadowsocks", "VMess", "Trojan", "Hysteria2", "Hysteria", "VLESS", "TUIC", "Socks5", "Http", "Snell"):
                    node = ProxyNode(
                        name=child,
                        type=child_info.get("type", "Unknown"),
                        delay=child_info.get("history", [{}])[-1].get("delay", -1) if child_info.get("history") else -1,
                        alive=child_info.get("alive", False),
                    )
                    nodes.append(node)
            groups[name] = nodes
    return groups


def test_node_delay(node_name: str, url: str = None) -> int:
    """
    测试单个节点的延迟
    返回延迟(ms)，失败返回 -1
    """
    if url is None:
        url = SPEED_TEST_URLS[0]
    try:
        # 通过 Clash 代理访问测速 URL
        proxy_handler = urllib.request.ProxyHandler({"http": "127.0.0.1:7890", "https": "127.0.0.1:7890"})
        opener = urllib.request.build_opener(proxy_handler)
        start = time.time()
        with opener.open(url, timeout=SPEED_TEST_TIMEOUT) as resp:
            if resp.status == 200:
                elapsed = int((time.time() - start) * 1000)
                return elapsed
        return -1
    except Exception:
        return -1


def switch_proxy(group_name: str, node_name: str) -> bool:
    """切换到指定代理节点"""
    result = _clash_api_put(f"/proxies/{group_name}", {"name": node_name})
    if result:
        global _stats
        _stats["switches"] += 1
        _stats["last_switch"] = f"{group_name} → {node_name}"
        print(f"[代理] 已切换: {group_name} → {node_name}")
    return result


def find_best_node(group: str) -> str | None:
    """
    在指定代理组中找到延迟最低的节点
    返回节点名，没有可用节点返回 None
    """
    proxies = get_all_proxies()
    nodes = proxies.get(group, [])
    if not nodes:
        return None

    best = None
    best_delay = float("inf")

    for node in nodes:
        if not node.alive and node.delay <= 0:
            continue
        delay = node.delay if node.delay > 0 else test_node_delay(node.name)
        if 0 < delay < best_delay:
            best_delay = delay
            best = node.name

    return best


# ==================== 自动切换逻辑 ====================

def auto_switch_if_needed(consecutive_failures: int = 0) -> bool:
    """
    检测代理是否正常，不正常则自动切换到最佳节点。
    返回 True=已切换, False=未切换。
    """
    if consecutive_failures < FAIL_THRESHOLD:
        return False

    # 先测一下当前代理是否真的有问题
    delay = test_node_delay("__current__")
    if delay > 0 and delay < 5000:
        # 当前代理还能用
        return False

    api = discover_clash_api()
    if not api:
        return False

    # 获取第一个代理组并找到最佳节点
    proxies = get_all_proxies()
    for group_name in proxies:
        if group_name in ("GLOBAL", "Proxy", "Auto"):
            best = find_best_node(group_name)
            if best:
                print(f"[代理] 检测到网络问题，自动切换到 {best}")
                return switch_proxy(group_name, best)

    return False


def _check_and_switch():
    """后台线程：每隔 AUTO_CHECK_INTERVAL 检查并自动切换"""
    fail_count = 0
    while True:
        time.sleep(AUTO_CHECK_INTERVAL)
        delay = test_node_delay("__auto__")
        _stats["checks"] += 1
        if delay < 0:
            fail_count += 1
            _stats["failures"] += 1
            auto_switch_if_needed(fail_count)
        else:
            fail_count = 0


# ==================== 对外接口 ====================

def start_auto_check():
    """启动后台自动检测线程"""
    thread = threading.Thread(target=_check_and_switch, daemon=True)
    thread.start()
    print("[代理] 自动检测已启动（每5分钟检查一次）")


def check_and_switch_now() -> bool:
    """立即进行一次代理检测和切换"""
    delay = test_node_delay("__manual__")
    if delay > 0 and delay < 3000:
        print(f"[代理] 当前节点正常（延迟 {delay}ms）")
        return False
    return auto_switch_if_needed(FAIL_THRESHOLD)


def get_proxy_status() -> dict:
    """获取代理状态摘要"""
    api = discover_clash_api()
    delay = test_node_delay("__status__")
    return {
        "api_available": api is not None,
        "current_delay_ms": delay if delay > 0 else None,
        "stats": _stats,
    }
