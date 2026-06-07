# Stock Deep Analysis

这是 Stock Analysis 项目的个股基本面和走势分析子项目。

## 当前状态

- 核心本地技能包位于 `china-stock-deep-analysis-local/`。
- 该技能包包含分析说明、脚本、行业模板、评分模型、仪表盘 schema 和自动同行数据。
- 当前脚本已做过轻量语法检查，核心 Python 文件可以正常编译。

## 核心目录

- `china-stock-deep-analysis-local/SKILL.md`: 个股深度分析工作流说明。
- `china-stock-deep-analysis-local/scripts/`: 抓数、评分、同行比较、博弈推演和 HTML 看板生成脚本。
- `china-stock-deep-analysis-local/references/`: 行业模板、评分模型、看板字段和 AI-native debate 说明。
- `china-stock-deep-analysis-local/scripts/stock_work/auto_peers/`: 已缓存的同行样本数据。

## 常用入口

完整个股分析优先看：

```text
china-stock-deep-analysis-local/SKILL.md
china-stock-deep-analysis-local/scripts/generate_stock_dashboard.py
```

分步排查时常看：

```text
china-stock-deep-analysis-local/scripts/fetch_a_share.py
china-stock-deep-analysis-local/scripts/scoring_model.py
china-stock-deep-analysis-local/scripts/auto_comparables.py
china-stock-deep-analysis-local/scripts/render_dashboard.py
```

## 修改指引

- 改分析流程和默认交付口径：优先看 `SKILL.md`。
- 改数据抓取：优先看 `scripts/fetch_a_share.py`。
- 改评分和结论框架：优先看 `scripts/scoring_model.py` 与 `references/scoring_model.md`。
- 改同行比较：优先看 `scripts/auto_comparables.py`。
- 改 HTML 看板：优先看 `scripts/render_dashboard.py` 和 `references/dashboard_schema.md`。

## 新对话接力提示

如果在新 Codex 对话中继续个股分析，请先阅读：

```text
D:\Projects\Stock Analysis\README.md
D:\Projects\Stock Analysis\03_stock_deep_analysis\README.md
D:\Projects\Stock Analysis\03_stock_deep_analysis\china-stock-deep-analysis-local\SKILL.md
```

然后再根据目标修改脚本、模板或分析输出。
