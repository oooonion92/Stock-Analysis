# Industry Research

这是 Stock Analysis 项目的深度行业研究子项目。

## 定位

本子项目负责把 Zotero 中收集的研报、文章、网页和资料，消化成自己的行业知识体系。

它位于研究链条上游：

```text
Zotero 资料收集 -> 深度行业研究 -> 个股分析 -> 每日复盘/交易预案
```

## 当前 Zotero 状态

- Zotero Desktop local API 已启用。
- API 地址：`http://127.0.0.1:23119`
- Zotero 本地库路径：`C:\Users\翀\Zotero`
- 当前已验证可读取 collection、tag 和条目。
- 现有 collection 示例：`PCB行业研究`
- 现有 tag 示例：`PCB`

## 子项目目标

把行业资料沉淀成可复用的研究成果：

- 行业总览
- 产业链图谱
- 上中下游关键环节
- 核心公司清单
- 供需格局
- 价格/产能/库存/技术路线
- 政策与产业趋势
- 催化剂和风险
- 投资逻辑和反证条件
- 可导入个股分析的行业模板

## 建议目录

```text
04_industry_research/
  README.md
  zotero_exports/        # 从 Zotero 导出的索引、全文、附件清单
  industries/            # 按行业沉淀研究成果
  templates/             # 行业研究模板
  tools/                 # Zotero 导入和资料整理工具
```

## Zotero 使用边界

- Zotero 负责收集和保存原始资料。
- 本项目只保存从资料中提炼出的结构化成果和必要索引。
- 不建议把大量原始 PDF 复制进 Git 仓库。
- 如需引用原文，应保存 Zotero item key、标题、来源 URL、日期和附件路径。

## 第一阶段最小工作流

1. 从 Zotero 读取某个 collection 或 tag。
2. 生成资料索引：标题、作者、年份、URL、Zotero item key、附件状态。
3. 对资料按主题聚类。
4. 生成行业研究初稿：
   - 行业核心矛盾
   - 产业链结构
   - 关键变量
   - 受益公司
   - 催化剂
   - 风险与反证
5. 把成熟结论同步给：
   - `03_stock_deep_analysis` 的行业模板
   - `02_daily_replay` 的热点/催化跟踪

## 新对话接力提示

如果在新 Codex 对话中继续深度行业研究，请先阅读：

```text
D:\Projects\Stock Analysis\README.md
D:\Projects\Stock Analysis\04_industry_research\README.md
```

然后根据目标行业或 Zotero collection 开始研究。
