#!/usr/bin/env python3
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
from typing import Any, Dict, List


def e(x: Any) -> str:
    return html.escape("" if x is None else str(x))


def arr(x: Any) -> List[Any]:
    return x if isinstance(x, list) else []


def safe_name(code: str, name: str) -> str:
    s = str(name or "").strip()
    # If mojibake markers appear, prefer code-only to avoid visual noise.
    if "�" in s or "鍒" in s or "鈥" in s:
        return str(code)
    return s or str(code)


def render(d: Dict[str, Any]) -> str:
    title = safe_name(d.get("code", ""), d.get("title", ""))
    code = d.get("code", "")
    industry = d.get("industry", "未识别")
    market = d.get("market", "")
    score = d.get("score", "-")
    action = d.get("action", "观察")
    risk = d.get("risk_level", "中")
    summary = [str(x) for x in arr(d.get("summary"))][:6]
    metrics = arr(d.get("metrics"))[:8]
    trade = d.get("trade_plan") or {}
    peers = arr(d.get("comparables"))[:8]

    metric_html = "".join(
        f"<div class='card'><div class='k'>{e(m.get('label'))}</div><div class='v'>{e(m.get('value'))}</div><div class='d'>{e(m.get('delta'))}</div></div>"
        for m in metrics
    )
    summary_html = "".join(f"<li>{e(s)}</li>" for s in summary)
    peer_html = "".join(
        f"<tr><td>{e(p.get('code'))}</td><td>{e(safe_name(p.get('code',''), p.get('name','')))}</td><td>{e(p.get('score'))}</td><td>{e(p.get('valuation'))}</td><td>{e(p.get('scene'))}</td></tr>"
        for p in peers
    )

    def li(key: str) -> str:
        return "".join(f"<li>{e(x)}</li>" for x in arr(trade.get(key)))

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width,initial-scale=1" />
  <title>{e(title)} {e(code)} 看板</title>
  <style>
    body{{margin:0;background:#f4f7fb;color:#10243e;font-family:"PingFang SC","Microsoft YaHei","Segoe UI",sans-serif}}
    .wrap{{max-width:1120px;margin:16px auto;padding:0 12px 28px}}
    .hero{{background:linear-gradient(135deg,#0c2f68,#0f6aa8);color:#fff;border-radius:18px;padding:18px}}
    .hero h1{{margin:0 0 8px;font-size:38px}}
    .muted{{opacity:.88}}
    .pill{{display:inline-block;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.18);margin-right:8px;margin-top:8px}}
    .grid{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin-top:12px}}
    .card{{background:#fff;border:1px solid #e3ebf6;border-radius:12px;padding:12px}}
    .k{{font-size:12px;color:#5f738f}}
    .v{{font-size:30px;font-weight:700;margin-top:4px}}
    .d{{font-size:12px;color:#5f738f;margin-top:4px}}
    .sec{{background:#fff;border:1px solid #e3ebf6;border-radius:12px;padding:12px;margin-top:12px}}
    h2{{margin:0 0 8px;font-size:20px}}
    ul{{margin:6px 0 0 20px}}
    table{{width:100%;border-collapse:collapse;font-size:13px}}
    th,td{{border-top:1px solid #edf1f7;padding:8px;text-align:left}}
    th{{background:#f7faff}}
    @media (max-width:900px){{.grid{{grid-template-columns:1fr 1fr}}}}
    @media (max-width:640px){{.grid{{grid-template-columns:1fr}} .hero h1{{font-size:30px}}}}
  </style>
</head>
<body>
  <div class="wrap">
    <div class="hero">
      <div class="muted">China Stock Visual Dashboard</div>
      <h1>{e(title)} {e(code)}</h1>
      <div class="muted">{e(industry)} · {e(market)}</div>
      <div class="pill">当前动作：{e(action)}</div>
      <div class="pill">风险等级：{e(risk)}</div>
      <div class="pill">评分：{e(score)}/10</div>
    </div>

    <div class="sec">
      <h2>一句话摘要</h2>
      <ul>{summary_html}</ul>
    </div>

    <div class="grid">{metric_html}</div>

    <div class="sec">
      <h2>交易观察框架</h2>
      <b>左侧观察</b><ul>{li('buy_left')}</ul>
      <b>右侧确认</b><ul>{li('buy_right')}</ul>
      <b>持有条件</b><ul>{li('hold')}</ul>
      <b>止损条件</b><ul>{li('stop')}</ul>
    </div>

    <div class="sec">
      <h2>可比公司（细分行业优先）</h2>
      <table>
        <thead><tr><th>代码</th><th>名称</th><th>评分</th><th>估值</th><th>场景</th></tr></thead>
        <tbody>{peer_html}</tbody>
      </table>
    </div>
  </div>
</body>
</html>
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--out-html", required=True)
    a = ap.parse_args()
    d = json.loads(Path(a.input).read_text(encoding="utf-8"))
    Path(a.out_html).write_text(render(d), encoding="utf-8")


if __name__ == "__main__":
    main()

