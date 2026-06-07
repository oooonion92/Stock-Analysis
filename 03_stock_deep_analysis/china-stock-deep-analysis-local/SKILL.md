---
name: china-stock-deep-analysis
description: Use when performing deep analysis of China-related equities, especially A-share, Hong Kong-listed Chinese companies, Chinese ADRs, sector comparison, investment decision comparison, valuation analysis, risk review, discovering comparable stocks, or producing beginner-friendly beautiful HTML stock dashboards and optional PDF exports.
---

# China Stock Deep Analysis

中国股票深度分析 skill。目标：**专业判断 + 小白一眼看懂 + 金融终端级 HTML 决策看板**。

适用：A股、港股中资股、中概股 ADR；支持单股研究、多股对比、同行筛选、估值决策、买入/持有/卖出观察框架、HTML 看板输出。

## Default Behavior

当用户说“分析/深度分析/对比/有没有更优选择/还能买吗/买卖点/做看板”时：

1. 先查数据、再下判断；不要凭记忆给实时价格、公告、财报或监管信息。
2. 默认生成 HTML 看板，必须落到稳定工作区：`/root/.openclaw/workspace/outputs/stock_XXXXXX_YYYYMMDD.html`（港股/ADR 可用代码主体，如 `stock_00700_20260511.html`）。**不要把最终附件放在 `/tmp`、`mktemp` 临时目录或会话临时目录。**
3. Telegram/聊天最终默认只发：**一句话结论 + 真实存在的 HTML 附件指令**。附件指令必须是最终回复里的独立一行，格式为 `MEDIA:` 紧跟 HTML 的绝对路径；不要把示例 `MEDIA:` 行写进解释性文字，避免系统误触发。
4. 发最终回复前必须执行 `test -s <html_path>` 或等价检查；只有文件存在且非空才允许写附件指令。
5. PDF 仅在用户明确要求“PDF/打印/导出PDF”时额外生成；PDF 禁用浏览器默认页眉页脚。
6. 用户说“快速看下XXX/简单看下XXX”时进入**快速模式**：跳过完整同行对比，只输出核心卡、K线、评分、风险和数据可信度。
7. 如果 HTML 附件发送失败，立即用 `message` 工具按 Telegram 文档附件重发：`action=send`、`channel=telegram`、`target=<当前 chat_id>`、`media=<html_path>`、`filename=<basename>.html`、`caption=一句话结论`；重发后最终回复 `NO_REPLY`。必要时生成 PNG/PDF 备用。
8. 除非用户明确“只要文字”，不要只发长文字分析。

## Core Principles

- 默认中文；专业但小白友好，每个关键术语尽量给一句白话解释。
- 必须声明：公开信息研究，不构成投资建议。
- 避免绝对荐股；使用“观察/确认/减仓警戒/失效条件”等条件化语言。
- 结论必须回答：**现在怎么看？该等什么？什么情况要小心？有没有更优选择？**
- AI 必须主动判断行业，选择适配模板；不要套用通用模板敷衍。

## References

按需读取，避免把细则塞进 SKILL.md：

- `references/dashboard_schema.md`：HTML 看板 JSON 字段、K线/同行结构。
- `references/scoring_model.md`：评分权重、行业可调逻辑。
- `references/industry_templates.md`：券商、银行、制造、科技、消费医药、周期资源等行业指标。
- `scripts/generate_stock_dashboard.py`：**首选完整流水线入口**，串联抓数据→评分→自动同行→博弈→渲染→验收，避免漏步骤。
- `scripts/fetch_a_share.py`：A股/港股/ADR 基础行情/F10/K线快速抓取。
- `scripts/scoring_model.py`：数据转 dashboard JSON 的基础脚本。
- `scripts/auto_comparables.py`：自动识别行业并逐只拉取同行行情/F10，生成 `comparables`/`better_choices`。
- `scripts/render_dashboard.py`：HTML 看板渲染器。
- `scripts/debate_engine.py`：外部 LLM 多智能体博弈引擎；LLM 不可用时自动规则兜底，禁止空白。
- `scripts/merge_debate.py`：把 AI-native 博弈 JSON 合并进 dashboard。
- `references/ai_native_debate.md`：当外部 LLM 不可用或用户要求“你自己推演”时，OpenClaw 主模型直接生成六角色博弈 JSON 的规范。

## Data Trust Model

数据可信度分级：

- **A级**：公司公告、交易所、巨潮资讯、港交所披露易、SEC、年报/季报原文。财报、分红、减持、诉讼、重组、监管事项以此为准。
- **B级**：东方财富/F10/DataCenter、同花顺、雪球、腾讯财经、Yahoo Finance、Sina 行情等聚合数据。可用于快速分析，关键结论需交叉验证。
- **C级**：新闻、研报、行业报告。只作线索。
- **D级**：传闻、论坛、自媒体。不得作为结论依据。

强制校验：

- **行情必须双源**：A股优先腾讯 + 新浪/东方财富；港股优先腾讯/新浪港股 + Yahoo/港交所延迟行情；ADR 优先 Yahoo + Nasdaq/MarketWatch/公司 IR。价格/涨跌幅差异 >2% 时标记异常，说明可能延迟或口径不同。
- **财报口径**：估算值、TTM、预测值必须显著标注；重要财务结论优先公告/年报原文。
- **K线异常**：跳空或单日波动 >10%（或明显除权/停复牌/拆股）必须标记，并检查是否为复权、公告或数据源异常。
- **风险事件**：必须用公告/交易所/监管来源确认。
- HTML 必须有“数据可信度”模块，说明已交叉验证项与待确认项。

## Data Sources by Market

### A股

- 行情：腾讯 `qt.gtimg.cn`、新浪 `hq.sinajs.cn`、东方财富。
- 财报/F10：东方财富 DataCenter、巨潮资讯、交易所公告。
- K线：新浪/东方财富，必要时复核前复权/不复权口径。
- 同行：东方财富行业分类、申万/中证行业、F10 可比公司。

### 港股 HK

- 行情：腾讯港股、新浪港股、Yahoo Finance（`.HK`）、港交所延迟行情。
- 财报/公告：港交所披露易、公司 IR、年报/中报原文。
- 估值：PE/PB/股息率注意港币口径、市值币种、人民币业务换算。
- K线：Yahoo Finance / 新浪港股；注意除权除息、拆股、停牌。

### 中概股 / US ADR

- 行情：Yahoo Finance、Nasdaq、MarketWatch、公司 IR。
- 财报：SEC EDGAR 20-F/6-K、公司 IR、年报/季报 press release。
- 关键口径：GAAP vs Non-GAAP、ADS 与普通股换算、美元/人民币汇率、退市/审计监管风险。
- 同行：美股同赛道 + 港股/A股映射公司，估值口径必须统一。

## Analysis Workflow

### 1. 识别对象与目标

确认股票名/代码/市场/行业/用户目标。若名称模糊，先用搜索或行情源确认，不要猜代码。

### 2. 判断模式

- **快速模式**：用户说“快速看下/简单看下/大概看看”；输出核心结论、核心数据、K线、风险、数据可信度，不做完整同行深挖。
- **单股深度**：完整基本面 + 技术位 + 估值 + 风险 + 同行对比。
- **多股对比**：先统一口径，再排序；突出“谁更适合什么场景”。
- **投资决策比较**：明确资金偏好（稳健/成长/短线/分红/困境反转），按偏好给条件化选择。

### 3. 拉取与核验数据

**默认不要手工串零散脚本**，单股深度优先运行完整流水线：

```bash
python3 scripts/generate_stock_dashboard.py --code 002131 --json
```

可选参数：`--market auto|a|hk|us`、`--industry 科技`、`--catalyst-score 8`、`--quick`、`--no-debate`、`--date YYYYMMDD`。

流水线会自动完成：行情/估值/最新财报/主营/现金流/K线 → 评分 → 自动同行 → 多智能体博弈 → HTML 渲染 → 完整性验收。输出 JSON 里的 `html` 和 `media_line` 是最终附件路径。

必查：行情、估值、最新财报、主营结构、资产质量、现金流、K线 60-160 日、行业与同行。行情双源；财报重要结论尽量公告源复核。

**同行对比必填**：完整流水线会运行 `scripts/auto_comparables.py` 自动识别行业、选择同行、逐只拉取行情/F10财务，并把 `comparables`/`better_choices` 写回 dashboard JSON。若自动脚本失败，AI 才可手工查找 3-5 个同行可比公司（行情+估值+简评）填入 `comparables`。同行表不得为空（除非快速模式）；若部分同行抓取失败，必须在 `peer_errors`/数据可信度中明示。

### 4. 行业适配

主动判断行业并读取/应用 `references/industry_templates.md`。评分、风险、同行字段必须随行业变化：

- 金融看 PB、ROE、资产质量、分红、监管周期。
- 制造看订单、毛利率、存货/应收、产能、出海、现金流。
- 科技/AI 看收入增长、研发、客户质量、商业化、估值泡沫。
- 消费医药看品牌/渠道、政策、费用率、现金流、增长确定性。
- 周期资源看价格周期、库存、供需、吨盈利、分红和 PB。

### 5. 评分与判断

默认 7 项总分 10：行业景气度、公司竞争力、财务质量、成长确定性、估值性价比、催化剂强度、风险可控性。行业可调权重，但必须展示评分拆解和白话解释。详细规则见 `references/scoring_model.md`。

### 6. 买入 / 持有 / 卖出观察框架

输出条件化框架，不做确定性指令：

- 观察买入区：支撑/估值/缩量企稳。
- 右侧确认区：突破关键位、放量、板块共振、财报改善。
- 持有条件：趋势未破、逻辑未证伪、财务未恶化。
- 减仓警戒区：高位滞涨、反弹到压力位、题材退潮。
- 失效/止损线：跌破关键支撑、财报证伪、现金流恶化、公告风险。

每个信号必须标注依据：技术/基本面/估值/资金题材/风险。

### 7. 多智能体博弈（默认开启）

完整流水线会自动运行博弈引擎；若手工分步，完成数据拉取、评分、同行合并后运行：

```bash
python3 scripts/debate_engine.py --input dash.json --out debate.json [--model MODEL]
```

**首选质量策略**：如果 `debate_engine.py` 输出 `fallback: true`，不要直接接受规则兜底作为最终深度报告。应读取 `references/ai_native_debate.md`，由当前 OpenClaw 主模型基于 `dash.json` 直接生成六角色博弈 JSON，保存为 `stock_work/XXXXXX_ai_debate.json`，再用 `scripts/merge_debate.py` 合并并重渲染。规则兜底只作为最低保底，不作为默认最终稿。

博弈引擎会用 6 个独立角色（舆情、游资、风控、技术、筹码、大单异动）分别分析并投票，最终由裁定者汇总博弈结论。输出 JSON 包含：
- `votes`：每个角色的 `direction/confidence/one_liner/reasoning`
- `direction/confidence/bull_pct/bear_pct`：最终裁定
- `summary/action/key_level`：综合结论

然后把 `debate.json` 内容合并到 `dash.json` 的 `debate` 字段，再交给 `render_dashboard.py` 渲染。看板会自动显示「⚖️ 多智能体博弈裁定」区域。

如果用户说“不要博弈/跳过博弈”，可以不运行 debate_engine，`debate` 字段为空时渲染器会自动跳过。

博弈模型默认用环境变量 `DEBATE_MODEL`，未设置时回退到 `gpt-4.1-mini`。可通过 `--model` 覆盖。若 `openai/litellm/API` 不可用，`debate_engine.py` 会输出带 `fallback: true` 的规则版六角色裁定；随后必须优先改用 AI-native 主模型推演覆盖，最终 HTML 仍必须有 `votes/summary/action/key_level`，不得空白。

## Multi-stock Comparison Workflow

用于“X 和 Y 哪个好”“帮我筛几个同类”“这几只怎么排”。

1. **统一口径**：同一日期、同一币种/汇率、同一估值口径（TTM/静态/预测）、同一复权口径。
2. **分类定位**：把股票分成稳健分红、成长弹性、主题弹性、困境反转、防守配置等角色。
3. **行业适配评分**：每只股票用所属行业模板评分，不强行用一个通用模板。
4. **相对结论**：输出“首选/备选/观察/回避”及适合人群，而不是只排总分。
5. **HTML 表格**：当前用户关心标的置顶或高亮；多股对比页必须有综合雷达/评分环、估值-成长象限、风险热力卡。
6. **缺数据处理**：缺关键财报或行情时标注，不允许用空数据强排。

## HTML Dashboard Guidance

默认交付 HTML，不是 PDF。目标是**金融终端级、手机友好、3 秒定结论**。

### 固定信息架构

1. Hero 决策区：股票名/代码/日期、结论、动作、风险、综合评分。
2. 小白速读：3-5 条短结论，回答“干嘛的/贵不贵/为什么涨跌/看什么”。
3. K线 + 信号：K线、成交量、MA5/20/60、支撑/压力/现价/失效线。
4. 交易观察地图：观察买入、右侧确认、持有条件、减仓警戒、失效条件。
5. 核心数据卡：价格、市值、PE/PB/PS、营收、净利、ROE、现金流等。
6. 评分拆解：综合评分 + 7项环形/卡片式拆解 + 白话解释。
7. 财务趋势：年报/季报关键指标趋势。
8. 业务结构：收入占比、毛利率、利润贡献。
9. 风险热力卡：高/中/低风险与跟踪方式。
10. 同行/多股对比：当前标的高亮，字段按行业适配。
11. 数据可信度：来源、等级、是否双源校验、异常提示。
12. 术语小抄：PE、PB、ROE、扣非、右侧确认等。

### 视觉规则

- **首屏 3 秒定结论**：Hero 区必须一眼看出“结论 + 动作 + 风险 + 分数”，不要让用户下滑才知道观点。
- **金融终端级质感**：深色渐变 hero、玻璃拟态卡片、细边框、柔和阴影、专业青绿/蓝紫/琥珀点缀。
- **深色模式优先**：背景可用深蓝/墨黑渐变；卡片用半透明玻璃层；正文保证高对比度。
- **微交互**：数据卡 hover 上浮、评分环加载动画、风险卡轻微 glow、锚点平滑滚动；动画克制不花哨。
- **K线信号**：支撑/阻力/买入观察/减仓区必须用半透明色块区间渲染，不能只有虚线；异常跳空要有醒目标记。
- **评分展示**：综合评分和分项评分优先用环形图/仪表环，不用普通进度条堆满页面。
- **风险展示**：使用醒目的热力卡片，高风险红色优先级最高，包含“怎么跟踪/缓释”。
- **导航栏**：顶部目录锚点；当前位置高亮（scroll spy 效果）；移动端横向滚动。
- **少文字多结构**：每张卡最多 3 条短句；长分析拆成卡片、表格、信号轴。
- **手机优先**：窄屏单列，表格横向滚动，关键结论不要被图表挤下首屏。
- 禁止：论文式长段落、密集长表、低对比灰字、花哨无意义装饰。

## Mandatory Completion Gate

最终回复前必须完成以下验收，失败就继续修复，不能把半成品发给用户：

```bash
test -s /root/.openclaw/workspace/outputs/stock_XXXXXX_YYYYMMDD.html
python3 - <<'PY'
import json, sys
p='stock_work/XXXXXX_dash.json'
d=json.load(open(p))
assert d.get('summary') and d.get('metrics') and d.get('kline') and d.get('risks')
assert d.get('comparables'), 'missing comparables'
debate=d.get('debate') or {}
assert debate.get('votes') and debate.get('summary') and debate.get('action') and debate.get('key_level'), 'missing debate'
print('dashboard ok')
PY
```

如果使用 `generate_stock_dashboard.py`，它已内置基础验收；仍需看命令成功退出且返回 `ok: true`。若返回 `debate_fallback: true`，应继续执行 AI-native 博弈覆盖后再最终交付，除非用户明确接受规则兜底。

## Output Rules

- 默认最终回复：一句话结论 + HTML 附件。附件指令必须单独成行，使用真实存在的绝对路径：`MEDIA:` + `/root/.openclaw/workspace/outputs/stock_XXXXXX_YYYYMMDD.html`。
- **禁止**在最终回复里放不存在的示例附件路径；解释格式时写成 `M E D I A:` 或用内联代码说明，不能单独成行触发。
- Telegram 默认不要贴长文；长内容放 HTML 文档附件。
- 发出附件指令前必须验证：`test -s "$html_path"`。如果文件不存在、为空、或仍在 `/tmp`，先复制/重生成到 `/root/.openclaw/workspace/outputs/`。
- 如果收到/发现 `Media failed`：不要重复发同一条 `MEDIA:`；改用 `message` 工具按文档附件发送当前 HTML。主动用 message 工具发送文件后，最终回复 `NO_REPLY`。
- HTML 文件名：`stock_XXXXXX_YYYYMMDD.html`。
- 快速模式也要生成 HTML，但可省略完整同行对比。

## Quality Checklist

提交前检查：

- 是否优先运行 `generate_stock_dashboard.py` 完整流水线？若没有，是否说明原因并手工完成同等步骤？
- 是否查了最新行情/财报/K线？行情是否双源，差异 >2% 是否标异常？
- 财报/估值是否标明口径；估算值是否显著标注？
- K线是否检查跳空/异常波动/复权口径？
- 是否主动判断行业并应用行业模板？
- 单股深度是否已运行 `auto_comparables.py` 或等价自动同行拉取？同行表是否真实来自逐只行情/F10数据，而不是静态占位？
- 单股深度是否包含同行对比；多股对比是否统一口径并说明适合场景？
- 是否给出买入/持有/卖出/失效条件及依据？
- 是否有多智能体博弈 `votes/summary/action/key_level`，且不是空白？若 `debate_fallback: true`，是否已读取 `references/ai_native_debate.md` 并用 OpenClaw 主模型生成 AI-native 博弈覆盖？
- 是否有评分拆解、风险热力卡、数据可信度模块和术语解释？
- HTML 首屏是否 3 秒能看懂结论？视觉是否达到金融终端级？
- 是否避免确定性荐股口吻，并声明不构成投资建议？
