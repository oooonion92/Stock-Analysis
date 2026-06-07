from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _u(text: str) -> str:
    return text.encode("ascii").decode("unicode_escape")


def _fmt_num(v: Any) -> str:
    try:
        n = float(v)
    except Exception:
        return str(v) if v is not None else "--"
    if n >= 100:
        return f"{n:.1f}"
    if n >= 10:
        return f"{n:.2f}"
    return f"{n:.3f}"


def _row(text: str) -> str:
    return f'<div class="mini-line"><span></span><b>{text}</b></div>'


def _rows(items: List[str]) -> str:
    return "".join(_row(x) for x in items)


def _source_rows(items: List[Dict[str, str]]) -> str:
    out = []
    for s in items:
        out.append(
            f'<div class="mini-line" id="src-{s["id"]}"><span></span>'
            f'<b>[{s["id"]}] {s["title"]}</b> <em>{s["date"]}</em> '
            f'<a href="{s["url"]}" target="_blank" rel="noreferrer">{_u(r"\u539f\u6587")}</a></div>'
        )
    return "".join(out)


def _http_get_json(url: str, params: Dict[str, Any], timeout: int = 12) -> Dict[str, Any]:
    qs = urlencode(params)
    req = Request(
        f"{url}?{qs}",
        headers={
            "User-Agent": "Mozilla/5.0",
            "Accept": "application/json,text/plain,*/*",
            "Referer": "https://so.eastmoney.com/",
        },
        method="GET",
    )
    with urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def _fetch_em_reports(code: str, page_size: int = 8) -> List[Dict[str, str]]:
    end = datetime.now().date()
    begin = end - timedelta(days=365)
    params = {
        "code": code,
        "industryCode": "*",
        "pageSize": str(page_size),
        "pageNo": "1",
        "beginTime": begin.strftime("%Y-%m-%d"),
        "endTime": end.strftime("%Y-%m-%d"),
        "qType": "0",
        "fields": "title,stockName,orgSName,publishDate,emRatingName,stockCode,infoCode",
    }
    try:
        obj = _http_get_json("https://reportapi.eastmoney.com/report/list", params)
    except Exception:
        return []
    out: List[Dict[str, str]] = []
    for x in obj.get("data") or []:
        info = str(x.get("infoCode") or "").strip()
        if not info:
            continue
        out.append(
            {
                "title": str(x.get("title") or "").strip(),
                "org": str(x.get("orgSName") or "").strip(),
                "rating": str(x.get("emRatingName") or "").strip(),
                "date": str(x.get("publishDate") or "").split(" ")[0],
                "url": f"https://data.eastmoney.com/report/info/{info}.html",
            }
        )
    return out


def _build_em_search_url(query: str) -> str:
    return "https://so.eastmoney.com/web/s?" + urlencode({"keyword": f"{query} 研报"})


def _report_signal_lines(reports: List[Dict[str, str]]) -> List[str]:
    if not reports:
        return [_u(r"\u7814\u62a5\u6837\u672c\u6682\u672a\u6293\u53d6\u6210\u529f\uff0c\u4ee5\u516c\u544a+\u8d22\u52a1\u6570\u636e\u4e3a\u4e3b\u3002")]
    buy = 0
    hold = 0
    kw_ai = 0
    kw_profit = 0
    for r in reports:
        rt = r.get("rating", "")
        tt = r.get("title", "")
        if any(k in rt for k in [_u(r"\u4e70\u5165"), _u(r"\u589e\u6301"), "Buy", "OUTPERFORM"]):
            buy += 1
        if any(k in rt for k in [_u(r"\u4e2d\u6027"), _u(r"\u6301\u6709"), _u(r"\u51cf\u6301"), "Neutral", "Hold"]):
            hold += 1
        if any(k in tt for k in ["AI", _u(r"\u7b97\u529b"), _u(r"\u9ad8\u901f"), _u(r"\u4ea4\u6362\u673a"), "HPC"]):
            kw_ai += 1
        if any(k in tt for k in [_u(r"\u76c8\u5229"), _u(r"\u4e1a\u7ee9"), _u(r"\u6bdb\u5229"), _u(r"\u589e\u957f"), _u(r"\u52a8\u80fd")]):
            kw_profit += 1
    n = len(reports)
    return [
        _u(r"\u8fd1\u4e00\u5e74\u6293\u53d6") + f"{n}" + _u(r"\u7bc7\u5238\u5546\u6837\u672c\uff1a\u4e70\u5165/\u589e\u6301") + f"{buy}" + _u(r"\u7bc7\uff0c\u4e2d\u6027/\u6301\u6709/\u51cf\u6301") + f"{hold}" + _u(r"\u7bc7\u3002"),
        _u(r"\u6807\u9898\u5173\u952e\u8bcd\u4e2d\uff0cAI/\u7b97\u529b/\u9ad8\u901f\u51fa\u73b0") + f"{kw_ai}" + _u(r"\u6b21\uff0c\u76c8\u5229/\u4e1a\u7ee9/\u589e\u957f\u51fa\u73b0") + f"{kw_profit}" + _u(r"\u6b21\u3002"),
    ]


def _extract_report_themes(reports: List[Dict[str, str]]) -> Dict[str, int]:
    themes = {"ai_compute": 0, "capacity": 0, "profitability": 0}
    for r in reports:
        tt = r.get("title", "")
        if any(k in tt for k in ["AI", _u(r"\u7b97\u529b"), _u(r"\u9ad8\u901f"), _u(r"\u4ea4\u6362\u673a"), "HPC"]):
            themes["ai_compute"] += 1
        if any(k in tt for k in [_u(r"\u4ea7\u80fd"), _u(r"\u6269\u4ea7"), _u(r"\u91ca\u653e"), _u(r"\u4ea4\u4ed8")]):
            themes["capacity"] += 1
        if any(k in tt for k in [_u(r"\u76c8\u5229"), _u(r"\u4e1a\u7ee9"), _u(r"\u6bdb\u5229"), _u(r"\u589e\u957f"), _u(r"\u52a8\u80fd")]):
            themes["profitability"] += 1
    return themes


def _pick_value(dash: Dict[str, Any], key: str, default: str = "--") -> str:
    for m in dash.get("metrics") or []:
        if str(m.get("label", "")) == key:
            return str(m.get("value") or default)
    return default


def _build_deep_insight(dash: Dict[str, Any]) -> Dict[str, Any]:
    code = str(dash.get("code", "")).strip()
    name = str(dash.get("title", "")).strip() or code
    industry = str(dash.get("industry", "")).strip() or _u(r"\u672a\u77e5\u884c\u4e1a")
    score = _fmt_num(dash.get("score"))
    action = str(dash.get("action", "")).strip() or _u(r"\u89c2\u5bdf")
    risk = str(dash.get("risk_level", "")).strip() or _u(r"\u4e2d")
    price = _pick_value(dash, _u(r"\u6700\u65b0\u4ef7"))
    pe_pb = _pick_value(dash, "PE / PB")
    latest_profit = _pick_value(dash, _u(r"\u6700\u65b0\u51c0\u5229"))
    roe = _pick_value(dash, "ROE")

    comp_names = []
    for c in (dash.get("comparables") or [])[:3]:
        n = str(c.get("name", "")).strip()
        if n:
            comp_names.append(n)
    peers_text = _u(r"\u3001").join(comp_names) if comp_names else _u(r"\u53ef\u6bd4\u516c\u53f8")

    biz_items = dash.get("business") or []
    main_biz = biz_items[0] if biz_items else {}
    main_biz_name = str(main_biz.get("name") or _u(r"\u4e3b\u8425\u4e1a\u52a1"))
    main_biz_share = str(main_biz.get("share") or "--")
    main_biz_margin = str(main_biz.get("margin") or "--")

    reports = _fetch_em_reports(code)
    report_signal = _report_signal_lines(reports)
    report_themes = _extract_report_themes(reports)

    sources = [
        {"id": "R1", "title": _u(r"\u4e1c\u65b9\u8d22\u5bcc\uff1a") + f"{code}" + _u(r" + \u7814\u62a5\uff08\u4ee3\u7801\u68c0\u7d22\uff09"), "date": _u(r"\u6301\u7eed\u8ddf\u8e2a"), "url": _build_em_search_url(code)},
        {"id": "R2", "title": _u(r"\u4e1c\u65b9\u8d22\u5bcc\uff1a") + f"{name}" + _u(r" + \u7814\u62a5\uff08\u540d\u79f0\u68c0\u7d22\uff09"), "date": _u(r"\u6301\u7eed\u8ddf\u8e2a"), "url": _build_em_search_url(name)},
        {"id": "R3", "title": _u(r"\u5de8\u6f6e\u8d44\u8baf\uff1a") + f"{code}" + _u(r" \u516c\u544a\u4e0e\u5b9a\u671f\u62a5\u544a"), "date": _u(r"\u6301\u7eed\u8ddf\u8e2a"), "url": f"http://www.cninfo.com.cn/new/fulltextSearch?keyWord={code}"},
        {"id": "R4", "title": _u(r"\u4e1c\u65b9\u8d22\u5bcc DataCenter\uff1a\u8d22\u52a1\u4e0eF10\u6570\u636e"), "date": _u(r"\u5b9e\u65f6"), "url": "https://datacenter-web.eastmoney.com/api/data/v1/get"},
        {"id": "R5", "title": _u(r"\u96ea\u7403\uff1a") + f"{name}" + _u(r" + \u7814\u62a5/\u6df1\u5ea6\u8ba8\u8bba"), "date": _u(r"\u6301\u7eed\u8ddf\u8e2a"), "url": f"https://xueqiu.com/k?q={name}"},
    ]
    for i, r in enumerate(reports[:4], start=6):
        sources.append({"id": f"R{i}", "title": f'{r.get("org", "")}：{r.get("title", "")}', "date": r.get("date", ""), "url": r.get("url", "")})

    thesis = [
        f"{name}" + _u(r"\u5728") + industry + _u(r"\u8d5b\u9053\u4e2d\uff0c\u5f53\u524d\u7ed3\u8bba\u662f\u201c") + action + _u(r"\u201d\uff0c\u7efc\u5408\u5206") + score + _u(r"/10\uff0c\u98ce\u9669\u7b49\u7ea7") + risk + _u(r"\u3002\u8fd9\u662f\u8981\u770b\u4ea7\u4e1a\u9636\u6bb5\u548c\u4e1a\u7ee9\u5151\u73b0\u7684\u6807\u7684\u3002") + '<a href="#src-R1" class="tone">[R1]</a><a href="#src-R2" class="tone">[R2]</a>',
        _u(r"\u73b0\u4ef7\u7ea6") + price + _u(r"\uff0cPE/PB\u7ea6") + pe_pb + _u(r"\uff0c\u6700\u65b0\u51c0\u5229") + latest_profit + _u(r"\uff0cROE") + roe + _u(r"\u3002\u6838\u5fc3\u662f\u5229\u6da6\u7387\u3001\u73b0\u91d1\u6d41\u4e0e\u666f\u6c14\u662f\u5426\u540c\u6b65\u3002") + '<a href="#src-R3" class="tone">[R3]</a>',
        _u(r"\u540c\u884c\u5bf9\u7167\u4f18\u5148\u53c2\u8003") + peers_text + _u(r"\u3002\u540c\u884c\u82e5\u66f4\u5feb\u9a8c\u8bc1\u76c8\u5229\u4fee\u590d\uff0c\u5f53\u524d\u6807\u7684\u9700\u8981\u66f4\u5f3a\u7684\u50ac\u5316\u4fe1\u53f7\u3002") + '<a href="#src-R4" class="tone">[R4]</a><a href="#src-R5" class="tone">[R5]</a>',
        _u(r"\u4ea7\u4e1a\u5730\u4f4d\u53ef\u89c1\u5ea6\uff1a\u4e3b\u4e1a\u300c") + main_biz_name + _u(r"\u300d\u5360\u6536\u5165\u7ea6") + f"{main_biz_share}%" + _u(r"\uff0c\u6bdb\u5229\u7387") + main_biz_margin + _u(r"\u3002\u5176\u4f18\u52bf\u4e0d\u5728\u591a\u4e1a\u52a1\uff0c\u800c\u5728\u4e3b\u8d5b\u9053\u6df1\u8015\u3002") + '<a href="#src-R3" class="tone">[R3]</a>',
        report_signal[0] + '<a href="#src-R1" class="tone">[R1]</a><a href="#src-R2" class="tone">[R2]</a>',
        report_signal[1] + '<a href="#src-R1" class="tone">[R1]</a><a href="#src-R2" class="tone">[R2]</a>',
    ]

    structure = [
        _u(r"\u4ea7\u4e1a\u9636\u6bb5\uff1a\u5148\u5224\u65ad") + industry + _u(r"\u662f\u4e0a\u884c\u52a0\u901f\u3001\u51fa\u6e05\u4fee\u590d\u8fd8\u662f\u4e0b\u884c\u627f\u538b\u3002\u9636\u6bb5\u5224\u65ad\u662f\u4f30\u503c\u7684\u524d\u63d0\u3002") + '<a href="#src-R1" class="tone">[R1]</a><a href="#src-R2" class="tone">[R2]</a>',
        _u(r"\u884c\u4e1a\u5730\u4f4d\uff1a\u4ece\u5ba2\u6237\u7ed3\u6784\u3001\u4ea7\u54c1\u6e17\u900f\u7387\u3001\u6bdb\u5229\u7387\u97e7\u6027\u3001\u73b0\u91d1\u6d41\u8d28\u91cf\u56db\u7ef4\u6253\u5206\u3002") + '<a href="#src-R3" class="tone">[R3]</a><a href="#src-R4" class="tone">[R4]</a>',
        _u(r"\u7814\u62a5\u4e3b\u7ebf\u63d0\u70bc\uff1aAI/\u7b97\u529b/\u9ad8\u901f") + str(report_themes["ai_compute"]) + _u(r"\u6b21\uff0c\u4ea7\u80fd/\u4ea4\u4ed8") + str(report_themes["capacity"]) + _u(r"\u6b21\uff0c\u76c8\u5229/\u4e1a\u7ee9") + str(report_themes["profitability"]) + _u(r"\u6b21\uff0c\u53ef\u63d0\u70bc\u4e3a\u201c\u9ad8\u7aef\u5361\u4f4d + \u4ea7\u80fd\u4ea4\u4ed8 + \u4e1a\u7ee9\u9a8c\u8bc1\u201d\u3002") + '<a href="#src-R1" class="tone">[R1]</a><a href="#src-R6" class="tone">[R6]</a>',
    ]

    watch = [
        _u(r"\u7b49\u4ec0\u4e48\uff1a\u4e24\u5230\u4e09\u4e2a\u62a5\u544a\u671f\u8fde\u7eed\u9a8c\u8bc1\u6536\u5165/\u5229\u6da6/\u73b0\u91d1\u6d41\u540c\u5411\u6539\u5584\uff0cK\u7ebf\u5b8c\u6210\u53f3\u4fa7\u786e\u8ba4\u3002") + '<a href="#src-R3" class="tone">[R3]</a><a href="#src-R4" class="tone">[R4]</a>',
        _u(r"\u8b66\u60d5\u4ec0\u4e48\uff1a\u5229\u6da6\u4fee\u590d\u4f46\u73b0\u91d1\u6d41\u80cc\u79bb\uff0c\u6216\u540c\u884c\u5df2\u8d70\u5f31\u800c\u672c\u80a1\u53ea\u9760\u60c5\u7eea\u652f\u6491\u3002") + '<a href="#src-R4" class="tone">[R4]</a><a href="#src-R5" class="tone">[R5]</a>',
        _u(r"\u8bc1\u4f2a\u6761\u4ef6\uff1a\u540e\u7eed\u516c\u544a/\u5b9a\u671f\u62a5\u544a\u663e\u793a\u9ad8\u589e\u957f\u4e0d\u53ef\u6301\u7eed\uff0c\u6216\u4ea7\u4e1a\u94fe\u4ef7\u683c\u518d\u6b21\u6076\u5316\u3002") + '<a href="#src-R1" class="tone">[R1]</a><a href="#src-R3" class="tone">[R3]</a>',
    ]

    deep_summary = (
        f"{name}" + _u(r"\u5728") + industry + _u(r"\u7684\u5b9a\u4f4d\uff0c\u672c\u8d28\u4e0a\u662f\u201c\u4e3b\u8d5b\u9053\u6df1\u8015 + \u4ea7\u80fd\u4ea4\u4ed8 + \u4e1a\u7ee9\u9a8c\u8bc1\u201d\u7684\u6210\u957f\u578b\u6807\u7684\u3002")
        + _u(r"\u4ece\u7814\u62a5\u4e3b\u7ebf\u770b\uff0c\u5e02\u573a\u5173\u6ce8\u70b9\u5df2\u7ecf\u4ece\u9898\u6750\u53d9\u4e8b\uff0c\u8f6c\u5411\u201c\u666f\u6c14\u80fd\u5426\u7a7f\u900f\u5230\u76c8\u5229\u548c\u73b0\u91d1\u6d41\u201d\u7684\u9a8c\u8bc1\u3002")
        + _u(r"\u6838\u5fc3\u4f18\u52bf\u4e0d\u662f\u62a5\u8868\u4e00\u6b21\u6027\u8df3\u5347\uff0c\u800c\u662f\u4e3b\u4e1a\u96c6\u4e2d\u5ea6\u9ad8\uff08")
        + f"{main_biz_name} {main_biz_share}%"
        + _u(r"\uff09\u4e14\u6bdb\u5229\u7387\u53ef\u7ef4\u6301\uff08")
        + main_biz_margin
        + _u(r"\uff09\u3002")
        + _u(r"\u5f53\u524d\u9636\u6bb5\u6700\u5173\u952e\u7684\u8ddf\u8e2a\u662f\uff1a\u672a\u6765\u4e24\u5230\u4e09\u4e2a\u62a5\u544a\u671f\u91cc\uff0c\u6536\u5165\u3001\u5229\u6da6\u3001\u73b0\u91d1\u6d41\u662f\u5426\u7ee7\u7eed\u540c\u5411\u6539\u5584\uff0c\u540c\u65f6\u540c\u884c\u76f8\u5bf9\u5f3a\u5f31\u662f\u5426\u7ef4\u6301\u3002")
        + _u(r"\u5982\u679c\u51fa\u73b0\u201c\u5229\u6da6\u4fee\u590d\u4f46\u73b0\u91d1\u6d41\u80cc\u79bb\u201d\u6216\u201c\u540c\u884c\u666e\u904d\u8d70\u5f31\u800c\u672c\u80a1\u53ea\u9760\u60c5\u7eea\u652f\u6491\u201d\uff0c\u8fd9\u4e2a\u903b\u8f91\u5c31\u8981\u964d\u7ea7\u3002")
    )

    return {
        "title": _u(r"\u884c\u4e1a/\u7814\u62a5\u6df1\u5ea6\u6d1e\u5bdf"),
        "subtitle": _u(r"\u4ea7\u4e1a\u9636\u6bb5 + \u516c\u53f8\u5730\u4f4d + \u72ec\u95e8\u80fd\u529b + \u8bc1\u4f2a\u6761\u4ef6"),
        "deep_summary": deep_summary,
        "sources": sources,
        "thesis": thesis,
        "structure": structure,
        "watch": watch,
    }


def enrich_html_with_research_insight(html_path: Path, dash: Dict[str, Any]) -> None:
    html = html_path.read_text(encoding="utf-8", errors="ignore")
    data = _build_deep_insight(dash)

    section = f"""
<section class="section" id="insight">
  <div class="section-title"><h2>{data["title"]}</h2><small>{data["subtitle"]}</small></div>
  <div class="card">
    <h2>深度结论（300-600字）</h2>
    <p style="line-height:1.9;font-size:15px;margin:8px 0 12px;">{data["deep_summary"]}<a href="#src-R1" class="tone">[R1]</a><a href="#src-R2" class="tone">[R2]</a><a href="#src-R3" class="tone">[R3]</a></p>
    <div class="mini-line"><span></span><b>核心判断：{_u(r"\u4ece\u201c\u9898\u6750\u53d9\u4e8b\u201d\u8f6c\u5411\u201c\u4e1a\u7ee9\u9a8c\u8bc1\u201d\uff0c\u9002\u5408\u6761\u4ef6\u5316\u8ddf\u8e2a\u800c\u4e0d\u662f\u9759\u6001\u62bc\u6ce8\u3002")}</b></div>
    <div class="mini-line"><span></span><b>等什么信号：{_u(r"\u8de8\u5b63\u5ea6\u7684\u6536\u5165-\u5229\u6da6-\u73b0\u91d1\u6d41\u5171\u632f\uff0c\u5916\u52a0\u540c\u884c\u76f8\u5bf9\u5f3a\u5f31\u4fdd\u6301\u3002")}</b></div>
    <div class="mini-line"><span></span><b>警惕什么：{_u(r"\u73b0\u91d1\u6d41\u80cc\u79bb\u3001\u4ea7\u4e1a\u94fe\u4ef7\u683c\u518d\u6076\u5316\u3001\u540c\u884c\u9886\u5148\u6307\u6807\u8f6c\u5f31\u3002")}</b></div>
  </div>
  <div class="card neutral" style="margin-top:12px;">
    <h2>来源索引</h2>{_source_rows(data["sources"])}
  </div>
</section>
"""

    html = re.sub(r'<section class="section" id="insight">[\s\S]*?</section>\s*', "", html)
    if "</nav>" in html and "#source" in html and "#insight" not in html:
        html = html.replace('href="#source">', 'href="#insight">洞察</a><a href="#source">', 1)
    if 'id="source"' in html:
        html = html.replace('<section class="section grid g2" id="source">', section + '\n<section class="section grid g2" id="source">', 1)
    else:
        html += section
    html_path.write_text(html, encoding="utf-8")
