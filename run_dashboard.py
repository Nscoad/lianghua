"""启动本地看板服务器 + Cloudflare Tunnel 穿透"""
import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PORT = 5000
URL_FILE = os.path.join(os.path.dirname(__file__), "data", "cloudflare_url.txt")


def _wait_url_saver(app):
    """等 cloudflared URL 就绪后写入文件"""
    from flask_cloudflared import get_cloudflared_url
    for _ in range(60):  # 最多等 60 秒
        url = get_cloudflared_url()
        if url:
            with open(URL_FILE, "w") as f:
                f.write(url + "\n")
            print(f"\n  🌐 Cloudflare Tunnel: {url}")
            print(f"  {'=' * 50}\n")
            return
        time.sleep(1)
    print("\n  ⚠ Cloudflare Tunnel 未就绪")


if __name__ == "__main__":
    from web_dashboard.app import app
    import flask_cloudflared

    # 套上 cloudflared 隧道
    flask_cloudflared.run_with_cloudflared(app)

    # 后台线程等 URL 就绪
    threading.Thread(target=_wait_url_saver, args=(app,), daemon=True).start()

    print(f"  [看板] http://localhost:{PORT}")
    app.run(host="0.0.0.0", port=PORT, debug=False)
