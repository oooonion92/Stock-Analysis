from __future__ import annotations

import argparse

from crawl_nga_author_replies import crawl as crawl_nga_replies
from crawl_hupu_user_replies import crawl as crawl_hupu_replies
from crawl_xueqiu_user_posts import crawl as crawl_xueqiu_posts
from forum_db import (
    connect,
    finish_run,
    insert_posts,
    list_enabled_targets,
    mark_target_crawled,
    start_run,
)


def crawl_target(conn, target, args) -> tuple[int, int]:
    site_type = target["site_type"]
    target_type = target["target_type"]
    pages = args.pages if args.pages is not None else int(target["crawl_pages"])

    run_id = start_run(conn, int(target["site_id"]), int(target["id"]), pages)
    try:
        if site_type == "nga" and target_type in ("replies", "both"):
            records = crawl_nga_replies(
                author_id=str(target["external_user_id"]),
                author_name=str(target["display_name"]),
                pages=pages,
                delay=args.delay,
                retries=args.retries,
                retry_delay=args.retry_delay,
                headless=not args.headed,
            )
        elif site_type == "xueqiu" and target_type in ("feed", "posts", "both", "replies"):
            records = crawl_xueqiu_posts(
                user_id_or_url=str(target["external_user_id"] or target["profile_url"]),
                author_name=str(target["display_name"]),
                pages=pages,
                delay=args.delay,
                headless=not args.headed,
            )
        elif site_type == "hupu" and target_type in ("replies", "both"):
            records = crawl_hupu_replies(
                user_id_or_url=str(target["profile_url"] or target["external_user_id"]),
                author_name=str(target["display_name"]),
                pages=pages,
                delay=args.delay,
                headless=not args.headed,
            )
        else:
            raise RuntimeError(f"暂不支持的站点/目标类型：{site_type}/{target_type}")

        posts_new = insert_posts(conn, int(target["site_id"]), int(target["id"]), records)
        mark_target_crawled(conn, int(target["id"]))
        finish_run(conn, run_id, "success", posts_found=len(records), posts_new=posts_new)
        return len(records), posts_new
    except Exception as exc:
        finish_run(conn, run_id, "failed", error_message=str(exc))
        raise


def main() -> int:
    parser = argparse.ArgumentParser(description="按数据库中的启用目标自动抓取高手发言。")
    parser.add_argument("--site", help="只抓指定网站名，例如 NGA。")
    parser.add_argument("--name", help="只抓指定高手显示名。")
    parser.add_argument("--pages", type=int, help="覆盖数据库中的抓取页数。")
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--retries", type=int, default=5)
    parser.add_argument("--retry-delay", type=float, default=3.0)
    parser.add_argument("--headed", action="store_true", help="显示浏览器窗口，便于排查登录状态。")
    args = parser.parse_args()

    with connect() as conn:
        targets = list_enabled_targets(conn)
        if args.site:
            targets = [target for target in targets if target["site_name"] == args.site]
        if args.name:
            targets = [target for target in targets if target["display_name"] == args.name]

        if not targets:
            print("没有找到启用的抓取目标。")
            return 0

        total_found = 0
        total_new = 0
        for target in targets:
            print(f"开始抓取：{target['site_name']} / {target['display_name']} ({target['external_user_id']})")
            found, new = crawl_target(conn, target, args)
            total_found += found
            total_new += new
            print(f"完成：找到 {found} 条，新增 {new} 条")

    print(f"全部完成：找到 {total_found} 条，新增 {total_new} 条")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
