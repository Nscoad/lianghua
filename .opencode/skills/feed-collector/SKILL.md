---
name: "feed-collector"
description: 当用户要求"获取最新市场动态""爬取广场数据""看币安广场有什么消息""检查采集状态""刷新市场情绪数据""最常搜索""X.com""Twitter"时必须使用。本 skill 用 Selenium 从币安广场（关注页+主页热门）和 X.com 爬取动态并存入 JSON，供 AI 摘要分析使用。
---

# 数据采集层 — 多源市场情绪采集

从币安广场（Binance Square）关注页 + 主页热门 + X.com 三个数据源爬取最新动态，供趋势采集循环（每30分钟）做 AI 摘要和微信推送。关注页采集由快捞循环调度调用。

## 适用场景

- 用户要求"看看今天广场上在说什么"、"有什么热点消息"
- 用户要求"刷新一下市场数据"、"采集最新动态"
- 用户要求"检查一下采集器运行状态"、"看看爬虫工作正常吗"
- 趋势采集循环自动调用（每30分钟）获取市场动态素材
- 用户提到"市场情绪"、"散户情绪"、"币安广场"等关键词

## 安全约定

- Chrome 浏览器必须以调试模式启动（端口 9555）
- 必须已登录币安账号（通过 Chrome 手动登录）
- 不采集敏感信息，只爬取公开动态文本
- 超过 1 小时的动态自动删除，不积压数据

## 输入输出

输入：采集数量参数（max_items，默认 10 条）

输出：
- 返回 `{fetched, added, total}` 采集统计
- 数据存储到 `data/square_feeds.json`
- 存储格式：`[{text, fetched_at, analyzed, analyzed_at}]`

## 推荐命令

```python
from collector.feed_collector import collect_and_store
from collector.trend_collector import collect_trends

# 采集关注页最新动态
result = collect_and_store(max_items=10, skip_chrome_check=False)
print(f"采集 {result['fetched']} 条，新增 {result['added']} 条，共 {result['total']} 条")

# 趋势采集（广场热门 + X.com）
trends = collect_trends(max_items_per_source=10)
```

## 前置条件

Chrome 必须以调试模式启动，并已登录币安：

```bash
# scheduler.py 会自动执行以下启动命令
start chrome.exe --remote-debugging-port=9555 --user-data-dir="%LOCALAPPDATA%\Google\Chrome\User Data"
```

## 文件位置

| 文件 | 说明 |
|------|------|
| `collector/square.py` | 币安广场爬虫（关注页 + 主页热门） |
| `collector/x_collector.py` | X.com 爬虫 |
| `collector/feed_collector.py` | 广场关注页采集 + 去重存储 |
| `collector/trend_collector.py` | 30分钟周期趋势采集（广场热门 + X.com） |

## 导出函数

| 函数 | 说明 | 返回值 |
|------|------|--------|
| `get_square_following_feed(max_items=5)` | 爬取广场关注页最新动态 | `list[str]` |
| `get_square_trending_feed(max_items=10)` | 爬取广场主页热门/推荐动态 | `list[str]` |
| `get_x_feed(max_items=10)` | 爬取 X.com 首页推文 | `list[str]` |
| `collect_and_store(max_items=10, skip_chrome_check=False)` | 广场关注页采集 + 去重存储 | `dict{fetched, added, total}` |
| `collect_trends(max_items_per_source=10)` | 30分钟周期采集（广场热门 + X.com） | `dict{source: {fetched, added}}` |

## 执行流程

### 关注页采集（由快捞循环调度调用）

1. **检查 Chrome 调试端口**：确认 Chrome 已在 9555 端口以调试模式运行
2. **启动 Selenium 连接**：通过 `Remote WebDriver` 连接 Chrome
3. **导航到币安广场关注页**：加载关注动态列表
4. **提取动态文本**：解析页面元素，提取每条动态的文本内容
5. **去重和存储**：与已有数据对比，新增动态追加到 `square_feeds.json`
6. **清理过期数据**：删除超过 1 小时的旧动态
7. **返回统计结果**：`{fetched, added, total}`

### 趋势采集（每30分钟，独立线程）

1. **币安广场主页热门**：获取"最常搜索6小时"等趋势币种信息
2. **X.com 首页推文**：获取 Twitter 上的热门讨论
3. **合并存储**：统一存入 `square_feeds.json`，按文本去重
4. **AI 摘要**：采集完成后由 `run_feed_summary()` 生成摘要并发微信通知

## 质量标准

- 根据动态文本**精确去重**（尾部数字变化视为不同内容）
- 超过 **1 小时**的动态自动删除，避免数据积压
- 采集失败时返回错误信息，不阻塞调用方
- Chrome 未启动时，`skip_chrome_check=False` 会报错提醒用户

## 测试

```python
from collector.square import ensure_chrome_debug
print(f"Chrome 调试模式: {ensure_chrome_debug()}")
```
