# 本地入口支持文件

这个目录存放高手发言工具的本地启动支持文件。

日常双击入口放在项目主目录：

- `D:\Projects\Stock Analysis\一键收集高手发言.bat`
- `D:\Projects\Stock Analysis\打开高手发言阅读中心.bat`
- `D:\Projects\Stock Analysis\发布高手看板数据.bat`

这里的 `.bat` 文件由主目录入口调用，不建议移到 OneDrive。OneDrive 只保留数据文件和可读导出，避免多电脑同步把启动脚本路径改坏。

日常顺序：先双击“一键收集高手发言”，确认收集完成后，再双击“发布高手看板数据”。发布工具只上传已经校验通过的 `experts-data.json`，不会重新抓取网站。

稳定支持文件使用 ASCII 文件名，降低 Windows/OneDrive 编码问题：

- `collect_forum_posts_local.bat`
- `open_expert_reader_local.bat`
- `publish_expert_dashboard_local.bat`
- `publish_expert_dashboard.ps1`
