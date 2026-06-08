from __future__ import annotations

import argparse
from pathlib import Path

from crawl_nga_author_replies import find_browser
from playwright.sync_api import sync_playwright


PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"
SITE_URLS = {
    "nga": "https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058",
    "xueqiu": "https://xueqiu.com/",
    "hupu": "https://my.hupu.com/89010186366175?tabKey=2",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="打开专用浏览器并手动登录网站。")
    parser.add_argument("--site", required=True, choices=sorted(SITE_URLS))
    parser.add_argument("--url", help="覆盖默认打开地址。")
    args = parser.parse_args()

    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    url = args.url or SITE_URLS[args.site]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=find_browser(),
            headless=False,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        print()
        print(f"请在打开的浏览器里手动登录：{args.site}")
        print("确认页面能正常访问后，回到这里按 Enter 保存登录状态并关闭浏览器。")
        input()
        context.close()

    print(f"登录资料夹已保存：{PROFILE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
