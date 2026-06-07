# Dashboard JSON Schema

股票 HTML 看板标准 JSON。渲染器必须尽量只依赖此结构。

## Top-level

- title: 股票名
- code: 代码
- market: 市场
- industry: 行业/主题
- date: 数据日期
- verdict: 一句话结论
- action: 当前动作：观察/等突破/谨慎持有/减仓警戒/回避
- risk_level: 低/中/高/极高
- score: 综合评分 0-10
- summary: 3-5 条短结论
- company_tearsheet: 公司一页纸，报告首页使用
- investment_thesis: 买方判断层，核心逻辑、正反证据、差异化观点和跟踪点
- catalyst_timeline: 30/60/90 天催化剂时间轴
- position_view: 仓位/动作视图，综合基本面、催化、技术和风险
- thesis_tracker: 投资逻辑跟踪器，记录逻辑是否成立、增强/削弱证据和复核触发条件
- valuation: 投行估值层，可比估值、情景区间、核心假设和自洽检查
- metrics: 核心数据卡
- kline: K线数组
- signal_chart: 买卖信号位
- trade_plan: 买入/持有/卖出/失效/仓位
- scores: 评分拆解
- business: 业务结构
- finance_trend / financials / financial_trend: 财务趋势表（周期、营收、净利、ROE、现金流、点评）
- risks: 风险；优先使用结构化对象，支持 level/text/mitigation
- catalysts: 催化剂
- comparables: 同行对比
- current_compare: 当前标的对比行
- data_sources: 数据可信度
- glossary: 术语小抄

## kline item

```json
{"date":"2026-05-11","open":8.24,"high":8.64,"low":8.21,"close":8.55,"volume":99892747,"ma5":8.24,"ma20":8.27,"ma60":8.65}
```

## comparable item

```json
{"name":"华泰证券","code":"601688","price":"19.37","valuation":"PE 9.97","score":"8.1","advantage":"...","risk":"...","scene":"..."}
```

## company_tearsheet

```json
{
  "business": "公司做什么",
  "industry_position": "行业位置/跟踪角色",
  "model": "商业模式或盈利来源",
  "key_metrics": ["PE/PB", "ROE", "现金流"],
  "why_now": "为什么现在值得看",
  "data_quality": "数据口径提示"
}
```

## investment_thesis

```json
{
  "core_thesis": "核心投资逻辑",
  "evidence_for": ["增强逻辑的证据"],
  "evidence_against": ["削弱逻辑的证据"],
  "variant_view": "与市场常规看法的差异点",
  "what_to_watch": ["下一步跟踪什么"]
}
```

## catalyst_timeline item

```json
{"window":"30天","event":"板块成交或政策催化","impact":"偏正面","confidence":"中","watch":"需要验证的信号"}
```

## position_view

```json
{
  "stance": "观察/小仓/加仓/减仓/回避",
  "size_hint": "仓位级别说明",
  "rationale": ["基本面、催化、技术、风险的综合理由"],
  "upgrade_triggers": ["提高暴露条件"],
  "downgrade_triggers": ["降低暴露条件"]
}
```

## valuation

```json
{
  "method": "comps-first",
  "comps_valuation": {"current": "PE/PB", "peer_context": "同行口径说明"},
  "valuation_range": {"bear": "...", "base": "...", "bull": "..."},
  "scenario_sensitivity": [
    {"scenario":"悲观","assumption":"...","price_view":"...","risk":"..."}
  ],
  "assumptions": ["估值假设"],
  "audit_flags": ["自洽检查提示"]
}
```
