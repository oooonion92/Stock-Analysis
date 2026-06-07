#!/usr/bin/env python3
"""Multi-agent debate engine for stock analysis.

Usage:
  debate_engine.py --input dash.json --out debate.json [--model MODEL]

Input : dashboard JSON (from scoring_model.py / manual).
Output: debate JSON with per-analyst verdicts and final arbitration.

The engine defines 6 analyst roles, builds a structured prompt for each,
calls the LLM once per role (sequentially — safe for rate limits), then
runs a final arbiter prompt that synthesises all votes into a verdict.

The output JSON is designed to plug directly into render_dashboard.py's
`debate` field.
"""
import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

# Prefer the skill-local virtualenv when the script is launched with system
# python. Debian/PEP668 often prevents installing optional LLM SDKs into the
# system interpreter, so we keep openai/litellm isolated in ../.venv.
_SKILL_DIR = Path(__file__).resolve().parents[1]
_VENV_PY = _SKILL_DIR / ".venv" / "bin" / "python"
if _VENV_PY.exists() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), *sys.argv])

# ---------------------------------------------------------------------------
# Role definitions
# ---------------------------------------------------------------------------

ROLES = [
    {
        "id": "sentiment",
        "emoji": "📰",
        "name": "舆情分析师",
        "focus": "新闻舆情、社交媒体情绪、板块热度、市场恐慌贪婪指数",
        "system": (
            "你是一名 A 股舆情分析师，擅长解读新闻事件、社交媒体情绪、"
            "板块热度和市场恐慌贪婪指数。你的判断基于信息面和情绪面，"
            "不依赖技术指标或基本面数据。"
        ),
    },
    {
        "id": "hot_money",
        "emoji": "🦈",
        "name": "游资分析师",
        "focus": "龙虎榜、游资席位、涨停复盘、板块轮动、短线资金博弈",
        "system": (
            "你是一名 A 股游资/短线分析师，擅长解读龙虎榜数据、"
            "游资席位、涨停复盘、板块轮动和短线资金博弈。"
            "你关注的是短线情绪和资金行为，而非长期基本面。"
        ),
    },
    {
        "id": "risk",
        "emoji": "🛡️",
        "name": "风控分析师",
        "focus": "限售解禁、减持、诉讼、财务风险、估值泡沫、止损位",
        "system": (
            "你是一名资深风控分析师，擅长识别限售解禁、股东减持、"
            "诉讼/监管、财务粉饰、估值泡沫和流动性风险。"
            "你的职责是找出所有可能的风险点并量化风险等级。"
        ),
    },
    {
        "id": "technical",
        "emoji": "📊",
        "name": "技术分析师",
        "focus": "K线形态、均线系统、MACD/RSI/KDJ、量价关系、支撑阻力",
        "system": (
            "你是一名 A 股技术分析师，擅长 K 线形态、均线系统、"
            "MACD/RSI/KDJ/布林带、量价关系、支撑阻力位判断。"
            "你只基于价格和成交量数据做判断。"
        ),
    },
    {
        "id": "chip",
        "emoji": "🧩",
        "name": "筹码分析师",
        "focus": "筹码分布、主力持仓、换手率、获利盘比例、股东结构",
        "system": (
            "你是一名筹码分析师，擅长分析筹码分布、主力持仓变化、"
            "换手率趋势、获利盘/套牢盘比例和股东结构变化。"
            "你关注的是筹码博弈和主力行为。"
        ),
    },
    {
        "id": "big_order",
        "emoji": "⚡",
        "name": "大单异动监控师",
        "focus": "大单净流入/流出、主力资金动向、异常成交、资金情绪",
        "system": (
            "你是一名大单异动监控师，擅长分析大单净流入/流出、"
            "超大单/大单/中单/小单资金分布、异常成交放量/缩量、"
            "主力资金进出节奏。你只关注资金面信号。"
        ),
    },
]

ARBITER_SYSTEM = (
    "你是一名首席投资策略师，负责汇总 6 位分析师的独立投票，"
    "进行博弈裁定，给出最终方向判断和综合信心度。"
    "你必须客观权衡多空分歧，不偏不倚。"
)

# ---------------------------------------------------------------------------
# LLM call helper (uses OpenAI-compatible API via env vars)
# ---------------------------------------------------------------------------

def _call_llm(messages, model=None, max_tokens=1200, temperature=0.3):
    """Call LLM via litellm (if available) or raw OpenAI SDK."""
    model = model or os.environ.get("DEBATE_MODEL", "gpt-4.1-mini")

    try:
        from litellm import completion
        resp = completion(model=model, messages=messages,
                          max_tokens=max_tokens, temperature=temperature)
        return resp.choices[0].message.content.strip()
    except ImportError:
        pass

    try:
        import openai
        client = openai.OpenAI(
            api_key=os.environ.get("OPENAI_API_KEY", ""),
            base_url=os.environ.get("OPENAI_BASE_URL"),
        )
        resp = client.chat.completions.create(
            model=model, messages=messages,
            max_tokens=max_tokens, temperature=temperature,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        return f"[LLM call failed: {e}]"


# ---------------------------------------------------------------------------
# Analyst prompt builder
# ---------------------------------------------------------------------------

def _build_analyst_prompt(role, data):
    """Build user prompt for a single analyst role."""
    title = data.get("title", "")
    code = data.get("code", "")
    market = data.get("market", "A股")
    date = data.get("date", "")
    price_info = ""
    for m in (data.get("metrics") or []):
        label = m.get("label", "")
        if any(k in label for k in ["现价", "价格", "收盘"]):
            price_info += f"  {label}: {m.get('value', '—')}"
        if any(k in label for k in ["涨跌", "市值", "PE", "PB", "成交", "换手"]):
            price_info += f"  {label}: {m.get('value', '—')}"

    kline_summary = ""
    klines = data.get("kline") or []
    if klines:
        last5 = klines[-5:]
        kline_summary = "最近5日K线: " + " | ".join(
            f"{k.get('date','')}: O{k.get('open','')}/H{k.get('high','')}/L{k.get('low','')}/C{k.get('close','')}/V{k.get('volume','')}"
            for k in last5
        )

    verdict = data.get("verdict", "")
    summary = "\n".join(f"- {s}" for s in (data.get("summary") or []))
    risks = "\n".join(
        f"- [{r.get('level','中')}] {r.get('text','')}"
        for r in (data.get("risks") or []) if isinstance(r, dict)
    ) or "暂无风险数据"

    signal = data.get("signal_chart") or {}
    signal_text = ", ".join(f"{k}={v}" for k, v in signal.items() if v is not None) if signal else "暂无"

    return f"""请对以下股票给出你的独立判断。

## 股票信息
- 股票: {title} ({code}), 市场: {market}, 日期: {date}
- {price_info}
- 信号位: {signal_text}

## 摘要
{summary}

## 风险
{risks}

## K线
{kline_summary}

## 你的分析角度
你是 **{role['name']}**，专注于 **{role['focus']}**。

## 输出格式 (严格JSON)
请只输出以下 JSON，不要输出其他内容：
```json
{{
  "direction": "看涨" 或 "看跌" 或 "中性",
  "confidence": 0-100的整数,
  "one_liner": "一句话核心判断(≤50字)",
  "reasoning": "3-5句分析理由(≤200字)"
}}
```"""


def _build_arbiter_prompt(votes, data):
    """Build the final arbiter prompt from all votes."""
    title = data.get("title", "")
    code = data.get("code", "")

    vote_text = ""
    for v in votes:
        emoji_dir = {"看涨": "🟢", "看跌": "🔴", "中性": "🟡"}.get(v["direction"], "⚪")
        vote_text += f"- {v['emoji']} {v['name']}: {emoji_dir}{v['direction']}(信心{v['confidence']}) — {v['one_liner']}\n"

    bull = sum(1 for v in votes if v["direction"] == "看涨")
    bear = sum(1 for v in votes if v["direction"] == "看跌")
    neutral = sum(1 for v in votes if v["direction"] == "中性")

    return f"""你是首席策略师。以下是 6 位分析师对 **{title}({code})** 的独立投票：

{vote_text}

投票统计: 看涨×{bull} 看跌×{bear} 中性×{neutral}

## 任务
综合博弈裁定。

## 输出格式 (严格JSON)
```json
{{
  "direction": "看涨" 或 "看跌" 或 "中性",
  "confidence": 0-100,
  "bull_pct": 0-100,
  "bear_pct": 0-100,
  "summary": "3-5句综合裁定理由(≤300字)",
  "action": "一句话操作建议(≤80字)",
  "key_level": "关键止损/止盈参考(≤50字)"
}}
```"""


# ---------------------------------------------------------------------------
# JSON extraction helper
# ---------------------------------------------------------------------------

def _extract_json(text):
    """Try to parse JSON from LLM output, tolerating markdown fences."""
    # Try raw parse first
    try:
        return json.loads(text)
    except Exception:
        pass
    # Try extracting from ```json ... ```
    m = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.S)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    # Try first { ... }
    m = re.search(r'\{[^{}]*\}', text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


# ---------------------------------------------------------------------------
# Deterministic fallback engine
# ---------------------------------------------------------------------------

def _num(x, default=None):
    try:
        if x is None or x == "":
            return default
        return float(str(x).replace("亿", "").replace("元", "").replace("%", ""))
    except Exception:
        return default


def _metric_value(data, keywords):
    for m in data.get("metrics") or []:
        label = m.get("label", "")
        if any(k in label for k in keywords):
            return m.get("value"), m.get("delta", "")
    return None, ""


def _latest_kline(data):
    kl = data.get("kline") or []
    return kl[-1] if kl else {}


def _fallback_vote(role, data):
    """Evidence-based rule vote used when LLM calls fail or return empty content."""
    summary = " ".join(str(x) for x in (data.get("summary") or []))
    risks = " ".join(str(r.get("text", r)) for r in (data.get("risks") or []))
    last = _latest_kline(data)
    close = _num(last.get("close"))
    ma20 = _num(last.get("ma20"))
    ma60 = _num(last.get("ma60"))
    ma120 = _num(last.get("ma120"))
    price, price_delta = _metric_value(data, ["最新价", "现价", "价格"])
    mcap, _ = _metric_value(data, ["市值"])
    pepb, _ = _metric_value(data, ["PE", "PB"])
    neg_profit = any(k in summary + risks for k in ["亏", "净利同比-", "净利下滑", "增收不增利", "现金流"])
    hot_theme = any(k in (data.get("industry", "") + summary + data.get("verdict", "")) for k in ["AI", "科技", "传媒", "营销", "机器人", "短剧", "算力", "半导体"])
    below_ma = close and ((ma20 and close < ma20) or (ma60 and close < ma60))

    rid = role["id"]
    if rid == "sentiment":
        if hot_theme and not neg_profit:
            direction, conf = "看涨", 60
            one = "题材热度提供情绪溢价。"
        elif hot_theme and neg_profit:
            direction, conf = "中性", 56
            one = "题材有关注度，但业绩压力压制情绪。"
        else:
            direction, conf = "中性", 52
            one = "舆情催化不够明确，先看板块共振。"
        reason = f"行业/摘要显示{data.get('industry','相关赛道')}属性；若题材升温会带来弹性，但公开财务摘要和风险项仍需同步验证。"
    elif rid == "hot_money":
        direction, conf = ("中性", 54) if hot_theme else ("中性", 50)
        one = "有流动性才有短线博弈，弱趋势里不宜追涨。"
        reason = f"市值/成交参考：{mcap or '未取到'}，价格信息：{price or '未取到'} {price_delta or ''}。短线资金通常等放量突破关键位再提高仓位。"
    elif rid == "risk":
        direction, conf = ("看跌", 68) if neg_profit else ("中性", 55)
        one = "财务质量和事件风险是首要约束。" if neg_profit else "暂未看到压倒性硬风险，仍需跟踪公告。"
        reason = f"风险线索：{risks[:180] or '暂无明确风险项'}。若现金流、利润率或公告风险恶化，估值弹性会被压缩。"
    elif rid == "technical":
        if below_ma:
            direction, conf = "看跌", 62
            one = "价格低于关键均线，趋势修复前偏弱。"
        else:
            direction, conf = "中性", 55
            one = "趋势未明显破坏，但仍需量价确认。"
        reason = f"最近K线收盘{close or '—'}，MA20={ma20 or '—'}，MA60={ma60 or '—'}，MA120={ma120 or '—'}；关键均线决定右侧确认强弱。"
    elif rid == "chip":
        direction, conf = ("中性", 56) if below_ma else ("中性", 52)
        one = "上方均线和前期成交区可能形成筹码压力。"
        reason = "若反弹到前期密集成交区放量滞涨，说明解套盘压力较大；若缩量企稳再放量突破，筹码结构才算改善。"
    else:  # big_order
        direction, conf = "中性", 50
        one = "未接入逐笔/大单数据，按成交活跃度保持中性。"
        reason = "当前脚本未拉取真实大单净流入，只能依据成交额、涨跌和K线位置做保守判断；需结合盘中资金流进一步确认。"

    return {
        "id": role["id"], "emoji": role["emoji"], "name": role["name"],
        "direction": direction, "confidence": conf,
        "one_liner": one, "reasoning": reason,
        "fallback": True,
    }


def _fallback_debate(data, failed_votes=None):
    votes = [_fallback_vote(role, data) for role in ROLES]
    bull_count = sum(1 for v in votes if v["direction"] == "看涨")
    bear_count = sum(1 for v in votes if v["direction"] == "看跌")
    neutral_count = len(votes) - bull_count - bear_count
    last = _latest_kline(data)
    close = _num(last.get("close"))
    ma20 = _num(last.get("ma20")); ma60 = _num(last.get("ma60")); ma120 = _num(last.get("ma120"))
    kl = data.get("kline") or []
    lows = [_num(k.get("low")) for k in kl[-60:] if _num(k.get("low")) is not None]
    highs = [_num(k.get("high")) for k in kl[-60:] if _num(k.get("high")) is not None]
    support = round(min(lows), 2) if lows else "关键支撑"
    resistance_candidates = [x for x in [ma120, ma20, ma60, max(highs) if highs else None] if x]
    resistance = round(min([x for x in resistance_candidates if not close or x >= close] or resistance_candidates), 2) if resistance_candidates else "关键压力"
    summary_bits = []
    if bull_count:
        summary_bits.append("多方主要看题材热度、流动性和短线弹性")
    if bear_count:
        summary_bits.append("空方主要看财务质量、现金流/利润压力和均线压制")
    if not summary_bits:
        summary_bits.append("多空证据都不够压倒性，属于等待确认的分歧状态")
    direction = "看涨" if bull_count >= 3 and bear_count <= 1 else "看跌" if bear_count >= 3 and bull_count <= 1 else "中性"
    confidence = 58 + abs(bull_count - bear_count) * 4
    return {
        "votes": votes,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "neutral_count": neutral_count,
        "direction": direction,
        "confidence": min(confidence, 76),
        "bull_pct": round(bull_count / len(votes) * 100),
        "bear_pct": round(bear_count / len(votes) * 100),
        "summary": f"规则版六角色裁定：{data.get('title','该股')}当前为{direction}。" + "；".join(summary_bits) + "。由于LLM不可用，本段由本地规则按行情、财务、风险和K线自动生成。",
        "action": "先观察，等右侧确认；若跌破关键支撑或财务继续恶化，应降低预期。",
        "key_level": f"支撑{support}；修复/压力{resistance}。",
        "fallback": True,
        "fallback_reason": "LLM debate unavailable or returned empty/failed outputs; generated deterministic rule-based debate instead.",
    }


def _is_failed_vote(vote):
    text = (vote.get("one_liner", "") + " " + vote.get("reasoning", "")).lower()
    return (not vote.get("one_liner")) or "分析失败" in vote.get("one_liner", "") or "llm call failed" in text


# ---------------------------------------------------------------------------
# Main engine
# ---------------------------------------------------------------------------

def run_debate(data, model=None):
    """Run the full 6-analyst debate + arbiter.

    Returns dict suitable for dashboard JSON `debate` field.
    """
    votes = []
    for role in ROLES:
        prompt = _build_analyst_prompt(role, data)
        messages = [
            {"role": "system", "content": role["system"]},
            {"role": "user", "content": prompt},
        ]
        raw = _call_llm(messages, model=model)
        parsed = _extract_json(raw)
        if parsed:
            vote = {
                "id": role["id"],
                "emoji": role["emoji"],
                "name": role["name"],
                "direction": parsed.get("direction", "中性"),
                "confidence": int(parsed.get("confidence", 50)),
                "one_liner": parsed.get("one_liner", ""),
                "reasoning": parsed.get("reasoning", ""),
            }
        else:
            vote = {
                "id": role["id"],
                "emoji": role["emoji"],
                "name": role["name"],
                "direction": "中性",
                "confidence": 50,
                "one_liner": "分析失败",
                "reasoning": raw[:200],
            }
        votes.append(vote)
        # Brief pause to respect rate limits
        time.sleep(0.5)

    # If every/most role calls failed, return deterministic local analysis instead
    # of an empty dashboard section. This protects stock reports when optional
    # OpenAI/litellm dependencies or API credentials are unavailable.
    if len([v for v in votes if _is_failed_vote(v)]) >= 3:
        return _fallback_debate(data, failed_votes=votes)

    # Arbiter
    arbiter_prompt = _build_arbiter_prompt(votes, data)
    arbiter_raw = _call_llm(
        [{"role": "system", "content": ARBITER_SYSTEM},
         {"role": "user", "content": arbiter_prompt}],
        model=model, max_tokens=800,
    )
    arbiter = _extract_json(arbiter_raw) or {}

    bull_count = sum(1 for v in votes if v["direction"] == "看涨")
    bear_count = sum(1 for v in votes if v["direction"] == "看跌")
    neutral_count = sum(1 for v in votes if v["direction"] == "中性")

    result = {
        "votes": votes,
        "bull_count": bull_count,
        "bear_count": bear_count,
        "neutral_count": neutral_count,
        "direction": arbiter.get("direction", "中性"),
        "confidence": arbiter.get("confidence", 50),
        "bull_pct": arbiter.get("bull_pct", round(bull_count / max(len(votes), 1) * 100)),
        "bear_pct": arbiter.get("bear_pct", round(bear_count / max(len(votes), 1) * 100)),
        "summary": arbiter.get("summary", ""),
        "action": arbiter.get("action", ""),
        "key_level": arbiter.get("key_level", ""),
    }
    if not result["summary"] or not result["action"] or not result["key_level"]:
        return _fallback_debate(data, failed_votes=votes)
    return result


def main():
    ap = argparse.ArgumentParser(description="Multi-agent stock debate engine")
    ap.add_argument("--input", required=True, help="Dashboard JSON path")
    ap.add_argument("--out", required=True, help="Output debate JSON path")
    ap.add_argument("--model", default=None, help="LLM model override")
    a = ap.parse_args()

    data = json.load(open(a.input, encoding="utf-8"))
    result = run_debate(data, model=a.model)
    Path(a.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"debate": a.out, "direction": result["direction"],
                       "confidence": result["confidence"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
