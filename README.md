# Stock Analysis

这个项目按三个常用子项目重新整理：

- `01_chanlun_sandbox/`: 缠论互动沙盘，双击根目录或本目录里的 `启动缠论沙盒.bat` 后打开 `http://127.0.0.1:8765/`。
- `02_daily_replay/`: 每日复盘材料、复盘计划和 HTML 看板。生成工具在 `02_daily_replay/tools/chanlun_replay_plan.py`。
- `03_stock_deep_analysis/`: 个股基本面和走势分析本地技能包，核心目录是 `03_stock_deep_analysis/china-stock-deep-analysis-local/`。
- `04_industry_research/`: 深度行业研究，承接 Zotero 资料并沉淀行业知识体系。
- `docs/`: 旧项目说明和交接记录。
- `tools/`: 后续放项目级维护脚本。

默认行情数据仍读取：

```text
D:\OneDrive\Stock\details
```

常用命令：

```powershell
cd "D:\Projects\Stock Analysis"
.\启动缠论沙盒.bat

.\01_chanlun_sandbox\start_chanlun_sandbox.ps1

$py = "$env:USERPROFILE\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
& $py .\02_daily_replay\tools\chanlun_replay_plan.py --json
```
