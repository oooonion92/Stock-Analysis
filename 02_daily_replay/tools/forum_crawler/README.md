# Forum Crawler

用于从指定论坛抓取高手发言，并把原始证据保存到 `02_daily_replay/source_notes/crawled_forum_posts/`。

数据库：

```text
02_daily_replay/data/forum_watchlist.sqlite
```

当前试点：

- 站点：NGA
- 用户：`-阿狼-`
- 作者 ID：`150058`
- 目标：抓取回帖发言

## 1. 手动登录

先打开专用浏览器资料夹：

```powershell
cd "D:\Projects\Stock Analysis"
$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\02_daily_replay\tools\forum_crawler\login_nga.py
```

脚本会打开 Chrome。请在窗口里手动登录 NGA，确认能访问作者回帖页后，回到终端按 Enter 关闭浏览器。登录状态会保存到：

```text
02_daily_replay/tools/forum_crawler/browser_profile/
```

这个目录已加入 `.gitignore`，里面可能包含 cookie，不要分享。

## 2. 建立网站-高手跟踪库

第一次使用先登记 NGA 和 `-阿狼-`：

```powershell
cd "D:\Projects\Stock Analysis"
$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\02_daily_replay\tools\forum_crawler\add_watch_target.py init-nga
```

以后新增网站：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\add_watch_target.py site --name NGA --base-url https://bbs.nga.cn --site-type nga
```

以后新增高手：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\add_watch_target.py target --site NGA --name "-阿狼-" --user-id 150058 --target-type replies --style 短线 --pages 5
```

如果高手数量多，推荐维护 CSV 后批量导入。先从数据库导出一份 Excel 友好的 CSV：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\export_watch_targets_csv.py --output .\02_daily_replay\data\watch_targets.csv
```

这份 CSV 是带 BOM 的 UTF-8，Windows Excel 直接打开不应乱码。

CSV 表头：

```text
site,name,user_id,target_type,style,pages,profile_url,enabled,notes
```

示例：

```csv
site,name,user_id,target_type,style,pages,profile_url,enabled,notes
NGA,-阿狼-,150058,replies,短线,3,https://bbs.nga.cn/thread.php?searchpost=1&authorid=150058,1,首个试点目标
```

`style` 用来做学习分类，建议填：

```text
短线：情绪、主线、连板、套利、隔日预案为主
趋势：波段、机构趋势、容量票、中枢/均线承接为主
混合：两种风格都有，暂时不强分
未知：还没判断清楚
```

先检查不写入：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\import_watch_targets.py .\02_daily_replay\data\watch_targets.csv --dry-run
```

确认无误后写入数据库：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\import_watch_targets.py .\02_daily_replay\data\watch_targets.csv
```

查看当前跟踪目标：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\add_watch_target.py list
```

## 3. 按跟踪库自动抓取

对话触发工作流：

```text
当你说“收集今天的发言记录”时，Codex 会自动运行一键收集脚本：
1. 读取启用目标
2. 抓取回帖
3. 写入 SQLite 去重
4. 从数据库重新生成最近 3 天滚动汇总
5. 更新高手发言阅读看板
```

对应命令：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\collect_forum_posts.py
```

输出位置：

```text
02_daily_replay/data/forum_watchlist.sqlite
D:\OneDrive\Stock\Replies collect\最近3天汇总.md
D:\OneDrive\Stock\Replies collect\高手发言阅读看板.html
```

同一天可以运行多次。每次抓取只向 SQLite 新增尚未保存的发言，三日汇总则从数据库完整重建，因此中午和晚上的记录会合并显示，不依赖上一次 Markdown 文件的内容。

抓取所有启用目标：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\crawl_watchlist.py
```

只抓某一个高手：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\crawl_watchlist.py --site NGA --name=-阿狼- --pages 3
```

如果 NGA 提示 `(ERROR:2048) > 服务器忙,请稍后重试`，脚本会自动等待并重试。默认每页最多重试 5 次，也可以手动调高：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\crawl_watchlist.py --site NGA --name=-阿狼- --pages 3 --retries 10 --retry-delay 3
```

抓取结果会先进入 SQLite，并按帖子 ID、链接和内容哈希去重。

## 4. 导出高手发言

```powershell
& $py .\02_daily_replay\tools\forum_crawler\export_posts.py --site NGA --name=-阿狼- --format md
```

导出某个站点所有启用目标：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\export_posts.py --site NGA --format both
```

输出类似：

```text
02_daily_replay/source_notes/crawled_forum_posts/nga/-阿狼-_150058_posts.md
```

## 5. 单用户调试命令

如果只想绕过数据库，直接调试 NGA 抓取器：

```powershell
cd "D:\Projects\Stock Analysis"
$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\02_daily_replay\tools\forum_crawler\crawl_nga_author_replies.py --pages 3
```

调高重试次数：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\crawl_nga_author_replies.py --pages 3 --retries 10 --retry-delay 3
```

输出：

```text
02_daily_replay/source_notes/crawled_forum_posts/nga/author_150058_replies.jsonl
02_daily_replay/source_notes/crawled_forum_posts/nga/author_150058_replies.md
```

## 6. 低频抓取原则

- 先小样本验证，默认每页间隔 2 秒。
- 只抓自己有权限访问的内容。
- 保留原文链接和抓取时间，后续精炼时能追溯依据。
- NGA 的结构化接口会把中文正文弄坏，所以当前脚本使用普通网页 DOM 文本解析。
- Markdown 使用带 BOM 的 UTF-8 写出，便于 Windows 本地工具识别中文。

## 7. 雪球关注流

雪球已经登记为独立站点，默认目标是登录后首页的关注流：

```text
站点：雪球
目标：关注流
user_id：following
target_type：feed
分类：混合
```

第一次使用前，先用专用浏览器资料夹登录雪球。确认首页标题变成“我的首页 - 雪球”，并且能看到自己的账号与关注流后，登录态会保存在：

```text
02_daily_replay/tools/forum_crawler/browser_profile/
```

后续说“收集今天的发言记录”时，雪球关注流会和 NGA 目标一起进入一键收集流程。也可以只收雪球：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\collect_forum_posts.py --site 雪球 --pages 2 --export-format both
```

输出位置：

```text
02_daily_replay/source_notes/crawled_forum_posts/xueqiu/混合/关注流_following_posts.md
02_daily_replay/source_notes/crawled_forum_posts/xueqiu/混合/关注流_following_posts.jsonl
```

抓取原则：只读取你登录后有权限访问的首页关注流接口，并保留原文链接、发布时间和抓取时间；未登录首页的热点/推荐卡片不会作为关注流入库。

## 8. 虎扑个人回帖

虎扑已经登记为独立站点，当前试点目标：

```text
站点：虎扑
目标：希夏邦驴
user_id：89010186366175
target_type：replies
分类：短线
profile_url：https://my.hupu.com/89010186366175?tabKey=2
```

虎扑个人中心需要登录。第一次使用前，先用专用浏览器资料夹登录虎扑，并确认目标个人页能看到回帖列表。

只收虎扑：

```powershell
& $py .\02_daily_replay\tools\forum_crawler\collect_forum_posts.py --site 虎扑 --pages 2 --export-format both
```

输出位置：

```text
02_daily_replay/source_notes/crawled_forum_posts/hupu/短线/希夏邦驴_89010186366175_posts.md
02_daily_replay/source_notes/crawled_forum_posts/hupu/短线/希夏邦驴_89010186366175_posts.jsonl
```

说明：虎扑个人页的原帖链接由前端处理，当前版本优先保存个人页来源链接、回帖正文、引用内容、主贴标题、板块和发布时间。

## 9. 云端阅读入口

跟踪清单和可读导出默认放在 OneDrive：

```text
D:\OneDrive\Stock\Replies collect\
```

主要入口：

```text
D:\OneDrive\Stock\Replies collect\watch_targets.csv
D:\OneDrive\Stock\Replies collect\最近3天汇总.md
D:\OneDrive\Stock\Replies collect\高手发言阅读看板.html
```

日常维护只改云端 `watch_targets.csv`。执行一键收集时，脚本会先把云端清单同步进本地 SQLite，再抓取并刷新三日汇总和阅读看板。完整历史只保存在 SQLite 中，避免 OneDrive 产生大量重复导出文件；SQLite 仍留在项目目录里，避免同步锁库。
