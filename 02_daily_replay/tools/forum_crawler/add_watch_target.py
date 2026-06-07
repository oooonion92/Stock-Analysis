from __future__ import annotations

import argparse

from forum_db import connect, list_targets, upsert_site, upsert_target


def add_nga_defaults() -> None:
    with connect() as conn:
        upsert_site(
            conn,
            name="NGA",
            base_url="https://bbs.nga.cn",
            site_type="nga",
            login_required=True,
            enabled=True,
            notes="NGA 玩家社区，当前通过手动登录态抓取作者回帖页。",
        )
        upsert_target(
            conn,
            site_name="NGA",
            display_name="-阿狼-",
            external_user_id="150058",
            profile_url="https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058",
            target_type="replies",
            style="未知",
            enabled=True,
            crawl_pages=3,
            notes="首个试点目标：抓取回帖发言。",
        )


def main() -> int:
    parser = argparse.ArgumentParser(description="登记需要跟踪的网站和高手用户。")
    subparsers = parser.add_subparsers(dest="command", required=True)

    site_parser = subparsers.add_parser("site", help="新增或更新网站")
    site_parser.add_argument("--name", required=True)
    site_parser.add_argument("--base-url", required=True)
    site_parser.add_argument("--site-type", required=True)
    site_parser.add_argument("--no-login-required", action="store_true")
    site_parser.add_argument("--disabled", action="store_true")
    site_parser.add_argument("--notes", default="")

    target_parser = subparsers.add_parser("target", help="新增或更新高手用户")
    target_parser.add_argument("--site", required=True)
    target_parser.add_argument("--name", required=True)
    target_parser.add_argument("--user-id", required=True)
    target_parser.add_argument("--profile-url", default="")
    target_parser.add_argument("--target-type", default="replies", choices=["replies", "topics", "posts", "feed", "both"])
    target_parser.add_argument("--style", default="未知", choices=["短线", "趋势", "混合", "未知"])
    target_parser.add_argument("--pages", type=int, default=3)
    target_parser.add_argument("--interval-minutes", type=int, default=1440)
    target_parser.add_argument("--disabled", action="store_true")
    target_parser.add_argument("--notes", default="")

    subparsers.add_parser("init-nga", help="登记 NGA 和 -阿狼- 试点目标")
    subparsers.add_parser("list", help="列出已登记目标")

    args = parser.parse_args()

    if args.command == "init-nga":
        add_nga_defaults()
        print("已登记 NGA 和 -阿狼-。")
        return 0

    with connect() as conn:
        if args.command == "site":
            site_id = upsert_site(
                conn,
                name=args.name,
                base_url=args.base_url,
                site_type=args.site_type,
                login_required=not args.no_login_required,
                enabled=not args.disabled,
                notes=args.notes,
            )
            print(f"已保存网站：{args.name} (id={site_id})")
        elif args.command == "target":
            target_id = upsert_target(
                conn,
                site_name=args.site,
                display_name=args.name,
                external_user_id=args.user_id,
                profile_url=args.profile_url,
                target_type=args.target_type,
                style=args.style,
                enabled=not args.disabled,
                crawl_pages=args.pages,
                crawl_interval_minutes=args.interval_minutes,
                notes=args.notes,
            )
            print(f"已保存跟踪目标：{args.name} (id={target_id})")
        elif args.command == "list":
            rows = list_targets(conn)
            if not rows:
                print("暂无跟踪目标。")
            for row in rows:
                enabled = "启用" if row["enabled"] else "停用"
                print(
                    f"[{enabled}] {row['site_name']} / {row['display_name']} "
                    f"user_id={row['external_user_id']} type={row['target_type']} style={row['style']} pages={row['crawl_pages']}"
                )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
