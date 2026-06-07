from __future__ import annotations

import os
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[3]
PROFILE_DIR = Path(__file__).resolve().parent / "browser_profile"
NGA_URL = "https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058"


def find_browser() -> str:
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for candidate in candidates:
        if Path(candidate).exists():
            return candidate
    raise SystemExit("未找到 Chrome/Edge，请先安装浏览器。")


def main() -> int:
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    executable_path = find_browser()

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            executable_path=executable_path,
            headless=False,
            viewport={"width": 1400, "height": 950},
            locale="zh-CN",
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(NGA_URL, wait_until="domcontentloaded")
        print()
        print("请在打开的浏览器里手动登录 NGA。")
        print("确认作者回帖页能正常访问后，回到这里按 Enter 保存登录状态并关闭浏览器。")
        input()
        context.close()

    print(f"登录资料夹已保存：{PROFILE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
