"""
采集层 — 从 X.com (Twitter) 获取热门动态（Selenium）

复用 Chrome 调试模式，通过已登录的浏览器抓取 X 首页信息流。
"""
import time
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from collector.square import CHROME_PORT, CHROME_PATH, CHROME_DRIVER_PATH, _inject_anti_detection


def get_x_feed(max_items: int = 10) -> list[str]:
    """
    接管 Chrome 浏览器，抓取 X.com 首页信息流

    要求 Chrome 已登录 X.com，否则可能只会看到登录页面。

    :param max_items: 获取的推文数量
    :return: 推文文本列表
    """
    chrome_options = Options()
    chrome_options.add_experimental_option("debuggerAddress", f"127.0.0.1:{CHROME_PORT}")
    chrome_options.binary_location = CHROME_PATH
    chrome_options.add_argument("--disable-blink-features=AutomationControlled")

    try:
        service = Service(CHROME_DRIVER_PATH)
        driver = webdriver.Chrome(service=service, options=chrome_options)

        driver.get("https://x.com/home")
        time.sleep(6)  # X 页面加载较慢，多等一会
        _inject_anti_detection(driver)
        time.sleep(3)

        # X 推文通常在 article 标签中，也尝试 data-testid="tweet"
        tweets = []
        seen = set()

        # 方法1：按 article 标签查找
        articles = driver.find_elements("tag name", "article")
        for article in articles:
            if len(tweets) >= max_items:
                break
            text = article.text.strip()
            if text and len(text) > 20 and text not in seen:
                seen.add(text)
                tweets.append(text)

        # 如果 article 方式没拿到足够数据，尝试按 data-testid 查找
        if len(tweets) < max_items:
            tweet_divs = driver.find_elements("css selector", "div[data-testid='tweet']")
            for div in tweet_divs:
                if len(tweets) >= max_items:
                    break
                text = div.text.strip()
                if text and len(text) > 20 and text not in seen:
                    seen.add(text)
                    tweets.append(text)

        if not tweets:
            print("[X采集] 未获取到推文，可能未登录 X.com 或页面结构已变更")
        else:
            print(f"[X采集] 获取到 {len(tweets)} 条推文")

        return tweets

    except Exception as e:
        print(f"获取 X.com 动态失败: {e}")
        return []
