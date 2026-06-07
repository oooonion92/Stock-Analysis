# AI-native Multi-agent Debate

Use this when `debate_engine.py` returns `fallback: true`, when external LLM API credentials are unavailable, or when the user asks for "你自己多智能体推演".

Goal: the main OpenClaw assistant performs the six-role debate directly using the dashboard JSON, without requiring `OPENAI_API_KEY`/`OPENAI_BASE_URL`.

## Required inputs

Read the generated dashboard JSON (`stock_work/XXXXXX_dash.json`) after quote/F10/Kline/peer comparables have been merged. Base the debate only on available data:

- title/code/market/industry/date
- summary/metrics
- kline and signal_chart/trade_plan
- scores/score_notes
- risks/catalysts
- comparables/better_choices/peer_errors
- warnings/data_sources

## Six roles

Generate exactly six votes:

1. 舆情分析师：题材热度、新闻/板块关注度、叙事强弱。
2. 游资分析师：短线资金偏好、容量、成交额、板块轮动、是否适合接力。
3. 风控分析师：财务质量、现金流、估值泡沫、公告/监管/减持/异常K线。
4. 技术分析师：K线、均线、支撑压力、量价关系、趋势状态。
5. 筹码分析师：套牢/获利盘、上方压力区、换手、是否容易拉升。
6. 大单异动监控师：成交活跃度、放量/缩量、资金分歧；若没有真实逐笔/大单数据，必须明示“未接入逐笔数据，按成交/K线保守判断”。

## Output JSON schema

Only produce a JSON object compatible with `render_dashboard.py`:

```json
{
  "votes": [
    {
      "id": "sentiment",
      "emoji": "📰",
      "name": "舆情分析师",
      "direction": "看涨|看跌|中性|中性偏多|中性偏空|偏多|偏空",
      "confidence": 0,
      "one_liner": "≤50字",
      "reasoning": "3-5句，≤220字"
    }
  ],
  "bull_count": 0,
  "bear_count": 0,
  "neutral_count": 0,
  "direction": "看涨|看跌|中性|中性偏谨慎|中性偏乐观",
  "confidence": 0,
  "bull_pct": 0,
  "bear_pct": 0,
  "summary": "3-5句综合裁定，必须说明多空核心分歧",
  "action": "一句话操作框架，条件化，不得荐股",
  "key_level": "支撑/修复/压力/失效位",
  "ai_native": true,
  "model_note": "OpenClaw主模型多角色推演；非外部API脚本调用"
}
```

Counting rules:

- `bull_count`: directions containing 看涨/偏多/中性偏多.
- `bear_count`: directions containing 看跌/偏空/中性偏空.
- `neutral_count`: the rest.
- `bull_pct`/`bear_pct`: should reflect both count and confidence; not necessarily sum to 100 if neutral exists, but must be 0-100.

## Quality bar

- Do not write generic role text. Every role must cite at least one concrete data point, level, score, warning, peer comparison, or risk from the dashboard JSON.
- If a data source is missing, say so; do not invent龙虎榜/大单/研报/公告 details.
- Final `summary/action/key_level` must be non-empty.
- Add `ai_native: true` so future audits can distinguish this from external LLM and rule fallback.

## Merge procedure

After producing the JSON, merge it into dashboard and re-render:

```bash
python3 scripts/merge_debate.py --dashboard stock_work/XXXXXX_dash.json --debate stock_work/XXXXXX_ai_debate.json
python3 scripts/render_dashboard.py --input stock_work/XXXXXX_dash.json --out-html outputs/stock_XXXXXX_YYYYMMDD.html
```

Then validate:

```bash
test -s outputs/stock_XXXXXX_YYYYMMDD.html
python3 - <<'PY'
import json
p='stock_work/XXXXXX_dash.json'
d=json.load(open(p))
debate=d.get('debate') or {}
assert debate.get('votes') and len(debate['votes']) == 6
assert debate.get('summary') and debate.get('action') and debate.get('key_level')
assert debate.get('ai_native') or debate.get('fallback') is not True
print('ai-native debate ok')
PY
```
