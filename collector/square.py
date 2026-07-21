"""
采集层 — 从币安广场获取关注动态（Selenium）
"""
import os
import socket
import subprocess
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# ==================== Chrome 路径配置 ====================
CHROME_PORT = 9555
CHROME_PATH = r"D:\chrome-win64\chrome.exe"
CHROME_DRIVER_PATH = r"E:/PyProject/chromedriver-win64/chromedriver.exe"
CHROME_USER_DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "chrome-debug")
# =========================================================


def _is_port_open(port: int) -> bool:
    """检测端口是否已被占用"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(("127.0.0.1", port)) == 0
    except:
        return False


def ensure_chrome_debug() -> bool:
    """
    确保 Chrome 调试模式已启动
    1. 检测 9555 端口
    2. 未启动则自动拉起 Chrome（带反侦察参数）
    3. 等待 10 秒后二次验证
    :return: True=可用, False=启动失败
    """
    if _is_port_open(CHROME_PORT):
        print(f"[OK] Chrome 调试模式已运行 (端口 {CHROME_PORT})")
        return True

    print(f"[启动] Chrome 调试模式未启动，正在自动启动...")

    if not os.path.isfile(CHROME_PATH):
        print(f"[错误] 未找到 Chrome: {CHROME_PATH}")
        return False

    if not os.path.exists(CHROME_USER_DATA):
        os.makedirs(CHROME_USER_DATA)

    try:
        subprocess.Popen(
            [
                CHROME_PATH,
                f"--remote-debugging-port={CHROME_PORT}",
                f"--user-data-dir={CHROME_USER_DATA}",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-blink-features=AutomationControlled",
                "--excludeSwitches=enable-automation",
                "--useAutomationExtension=false",
                "--disable-infobars",
                "--disable-background-networking",
            ],
            shell=False,
        )
        for i in range(10):
            time.sleep(1)
            if _is_port_open(CHROME_PORT):
                print(f"[OK] Chrome 调试模式已成功启动 (端口 {CHROME_PORT})")
                return True
            print(f"   等待 Chrome 启动... ({i+1}/10)")

        print("[错误] Chrome 启动超时，请手动运行：")
        print(f"   {CHROME_PATH} --remote-debugging-port={CHROME_PORT} --user-data-dir=\"{CHROME_USER_DATA}\"")
        return False
    except Exception as e:
        print(f"[错误] Chrome 启动失败: {e}")
        return False


def _inject_anti_detection(driver):
    """注入反侦察 CDP 补丁"""
    try:
        driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {
            "source": """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                const getParameter = WebGLRenderingContext.prototype.getParameter;
                WebGLRenderingContext.prototype.getParameter = function(parameter) {
                    if (parameter === 37445) return 'Intel Inc.';
                    if (parameter === 37446) return 'Intel(R) UHD Graphics 630';
                    if (parameter === 3379) return 'Google Inc. (Intel)';
                    return getParameter.apply(this, arguments);
                };
                Object.defineProperty(navigator, 'languages', {
                    get: () => ['zh-CN', 'zh', 'en', 'en-GB', 'en-US']
                });
            """
        })
    except Exception as e:
        print(f"   反侦察补丁注入失败: {e}")


def _scrape_page(driver, url: str, max_items: int, source_label: str) -> list[str]:
    """通用页面抓取：导航 → 等待 → 提取元素"""
    try:
        driver.get(url)
        time.sleep(5)
        _inject_anti_detection(driver)
        time.sleep(2)
        feed_elements = driver.find_elements(By.CSS_SELECTOR, "div[class*=content]")
        feed_data = []
        seen = set()
        for element in feed_elements:
            if len(feed_data) >= max_items:
                break
            text_content = element.text.strip()
            if text_content and len(text_content) > 30 and text_content not in seen:
                seen.add(text_content)
                feed_data.append(text_content)
        return feed_data
    except Exception as e:
        print(f"获取{source_label}动态失败: {e}")
        return []


def get_square_following_feed(max_items: int = 5) -> list[str]:
    """
    接管 Chrome 浏览器，抓取广场关注页最新推文
    :param max_items: 获取的动态数量
    :return: 推文文本列表
    """
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_PORT}")
    chrome_options.binary_location = CHROME_PATH
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service(CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return _scrape_page(driver, "https://www.binance.com/zh-CN/square?tab=Following", max_items, "广场关注")
    except Exception as e:
        print(f"获取广场关注动态失败: {e}")
        return []


def get_square_trending_feed(max_items: int = 10) -> list[str]:
    """
    接管 Chrome 浏览器，抓取广场主页热门/推荐动态
    (用于获取"最常搜索6小时"等趋势信息)

    :param max_items: 获取的动态数量
    :return: 动态文本列表
    """
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_PORT}")
    chrome_options.binary_location = CHROME_PATH
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service(CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)
        return _scrape_page(driver, "https://www.binance.com/zh-CN/square", max_items, "广场热门")
    except Exception as e:
        print(f"获取广场热门动态失败: {e}")
        return []
