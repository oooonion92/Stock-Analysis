#!/usr/bin/env python3
"""Render a self-contained China stock analysis dashboard.

The renderer intentionally stays offline-friendly: pure HTML/CSS/SVG/vanilla JS,
no CDN, and keeps the public CLI/schema compatible with the previous version.
"""
import argparse
import html
import json
import math
import os
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def e(x):
    return html.escape('' if x is None else str(x))


def arr(x):
    return x if isinstance(x, list) else []


def num(x, default=None):
    try:
        if x is None or x == '':
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except Exception:
        return default


def pct(v, digits=1):
    n = num(v)
    return '—' if n is None else f'{n:.{digits}f}%'


def short_lines(items, maxn=3):
    rows = arr(items)[:maxn]
    if not rows:
        return '<div class="muted">暂无</div>'
    return ''.join(f'<div class="mini-line"><span></span><b>{e(x)}</b></div>' for x in rows)


def tone_cls(t):
    return {'good': 'good', 'bad': 'bad', 'warn': 'warn', 'neutral': 'neutral'}.get(str(t or 'neutral'), 'neutral')


def score_color(score):
    s = num(score, 0)
    if s > 7:
        return '#10b981', 'green'
    if s > 5:
        return '#2563eb', 'blue'
    if s > 3:
        return '#f59e0b', 'orange'
    return '#ef4444', 'red'


def card_tone_from_text(text, default='neutral'):
    s = str(text or '')
    if any(k in s for k in ['风险', '失效', '减仓', '止损', '警戒', '跌破', '证伪']):
        return 'bad'
    if any(k in s for k in ['买入', '观察', '增长', '改善', '突破', '持有', '优势', '催化']):
        return 'good'
    if any(k in s for k in ['等待', '确认', '跟踪', '估值', '中性']):
        return 'neutral'
    return default


def ring_svg(score, size=148, stroke=13, label='综合评分', cls='hero-ring'):
    s = max(0, min(10, num(score, 0)))
    r = (size - stroke) / 2
    c = 2 * math.pi * r
    dash = c * s / 10
    color, name = score_color(s)
    center = size / 2
    return f'''<svg class="{cls} ring-{name}" viewBox="0 0 {size} {size}" role="img" aria-label="{e(label)} {s:.1f}分">
  <defs>
    <linearGradient id="ringGrad-{cls}-{name}" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0%" stop-color="#67e8f9"/><stop offset="45%" stop-color="{color}"/><stop offset="100%" stop-color="#a78bfa"/>
    </linearGradient>
    <filter id="ringGlow-{cls}" x="-30%" y="-30%" width="160%" height="160%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
  </defs>
  <circle class="ring-bg" cx="{center:.1f}" cy="{center:.1f}" r="{r:.1f}" fill="none" stroke="rgba(255,255,255,.20)" stroke-width="{stroke}"/>
  <circle class="ring-fg" cx="{center:.1f}" cy="{center:.1f}" r="{r:.1f}" fill="none" stroke="url(#ringGrad-{cls}-{name})" stroke-width="{stroke}" stroke-linecap="round" stroke-dasharray="{dash:.2f} {c:.2f}" transform="rotate(-90 {center:.1f} {center:.1f})" filter="url(#ringGlow-{cls})"/>
  <text x="50%" y="47%" text-anchor="middle" class="ring-score">{s:.1f}</text>
  <text x="50%" y="64%" text-anchor="middle" class="ring-label">/ 10</text>
</svg>'''


def mini_ring(score, idx=0, label='评分'):
    s = max(0, min(10, num(score, 0)))
    color, name = score_color(s)
    size, stroke = 64, 7
    r = (size - stroke) / 2
    c = 2 * math.pi * r
    dash = c * s / 10
    return f'''<svg class="mini-ring ring-{name}" viewBox="0 0 {size} {size}" aria-label="{e(label)} {s:.1f}分">
  <circle cx="32" cy="32" r="{r:.1f}" fill="none" stroke="#e8eef8" stroke-width="{stroke}"/>
  <circle cx="32" cy="32" r="{r:.1f}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-dasharray="{dash:.2f} {c:.2f}" transform="rotate(-90 32 32)"/>
  <text x="32" y="37" text-anchor="middle">{s:.1f}</text>
</svg>'''


def kline_chart(rows, signal_chart=None):
    rows = arr(rows)[-80:]
    if not rows:
        return '<div class="empty">暂无K线数据</div>'

    clean = []
    for r in rows:
        o, h, l, c = num(r.get('open')), num(r.get('high')), num(r.get('low')), num(r.get('close'))
        if None in (o, h, l, c):
            continue
        x = dict(r)
        x.update(open=o, high=h, low=l, close=c, volume=num(r.get('volume'), 0))
        clean.append(x)
    rows = clean[-80:]
    if not rows:
        return '<div class="empty">暂无K线数据</div>'

    W, H = 1040, 420
    pad_l, pad_r, pad_t, pad_b = 58, 28, 30, 48
    vol_h = 82
    plot_h = H - pad_t - pad_b - vol_h - 22
    highs = [r['high'] for r in rows]
    lows = [r['low'] for r in rows]
    sc = signal_chart or {}
    signal_vals = [num(sc.get(k)) for k in ['stop', 'buy_low', 'buy_high', 'current', 'confirm_low', 'confirm_high', 'resistance']]
    signal_vals = [v for v in signal_vals if v is not None]
    mx = max(highs + signal_vals)
    mn = min(lows + signal_vals)
    rng = mx - mn or max(mx * 0.08, 1)
    mx += rng * 0.06
    mn -= rng * 0.06
    rng = mx - mn or 1

    def y(v):
        return pad_t + (mx - float(v)) / rng * plot_h

    def band_rect(v1, v2, color, label, opacity='.13'):
        a, b = num(v1), num(v2)
        if a is None or b is None:
            return ''
        top, bottom = min(y(a), y(b)), max(y(a), y(b))
        if bottom < pad_t or top > pad_t + plot_h:
            return ''
        top = max(pad_t, top)
        bottom = min(pad_t + plot_h, bottom)
        h = max(6, bottom - top)
        return f'<rect x="{pad_l}" y="{top:.1f}" width="{W-pad_l-pad_r}" height="{h:.1f}" rx="10" fill="{color}" opacity="{opacity}"/><text x="{pad_l+12}" y="{top+17:.1f}" fill="{color}" font-size="12" font-weight="900">{e(label)}</text>'

    step = (W - pad_l - pad_r) / len(rows)
    cw = max(3.2, min(11, step * .58))
    maxvol = max([r.get('volume') or 0 for r in rows]) or 1
    vol_base = H - pad_b
    parts = [f'<svg class="kline-svg" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">']
    parts.append('''<defs>
      <linearGradient id="klineBg" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stop-color="#ffffff"/><stop offset="100%" stop-color="#f8fbff"/></linearGradient>
      <filter id="lastGlow" x="-70%" y="-70%" width="240%" height="240%"><feGaussianBlur stdDeviation="3" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs><rect x="0" y="0" width="1040" height="420" fill="url(#klineBg)" rx="22"/>''')

    for i in range(5):
        yy = pad_t + i * plot_h / 4
        val = mx - i * rng / 4
        parts.append(f'<line class="grid-line" x1="{pad_l}" y1="{yy:.1f}" x2="{W-pad_r}" y2="{yy:.1f}"/><text x="8" y="{yy+4:.1f}" font-size="11" fill="#64748b">{val:.2f}</text>')

    parts.append(band_rect(sc.get('buy_low'), sc.get('buy_high'), '#10b981', '观察买入区', '.14'))
    parts.append(band_rect(sc.get('confirm_low'), sc.get('confirm_high'), '#06b6d4', '突破确认区', '.13'))
    stop_v = num(sc.get('stop'))
    res_v = num(sc.get('resistance'))
    if stop_v is not None:
        parts.append(band_rect(stop_v, mn, '#ef4444', '失效警戒区', '.10'))
    if res_v is not None:
        parts.append(band_rect(res_v, mx, '#f59e0b', '压力/减仓观察区', '.10'))

    for key, label, col in [('stop', '失效', '#ef4444'), ('current', '现价', '#2563eb'), ('resistance', '压力', '#f59e0b')]:
        v = num(sc.get(key))
        if v is not None:
            yy = y(v)
            if pad_t - 8 <= yy <= pad_t + plot_h + 8:
                dash = '6 5' if key != 'current' else '0'
                width = '1.4' if key != 'current' else '2.2'
                parts.append(f'<line x1="{pad_l}" y1="{yy:.1f}" x2="{W-pad_r}" y2="{yy:.1f}" stroke="{col}" stroke-width="{width}" stroke-dasharray="{dash}" opacity=".80"/>')
                parts.append(f'<g><rect x="{W-pad_r-116}" y="{yy-18:.1f}" width="108" height="24" rx="12" fill="white" stroke="{col}"/><text x="{W-pad_r-62}" y="{yy-2:.1f}" text-anchor="middle" font-size="12" fill="{col}" font-weight="900">{label} {v:.2f}</text></g>')

    for ma, color in [('ma5', '#f59e0b'), ('ma20', '#2563eb'), ('ma60', '#8b5cf6')]:
        pts = []
        for i, r in enumerate(rows):
            v = num(r.get(ma))
            if v is not None:
                x = pad_l + i * step + step / 2
                pts.append(f'{x:.1f},{y(v):.1f}')
        if len(pts) > 1:
            parts.append(f'<polyline class="ma-line" points="{" ".join(pts)}" fill="none" stroke="{color}" stroke-width="2.2" stroke-linejoin="round" stroke-linecap="round"/>')

    for i, r in enumerate(rows):
        x = pad_l + i * step + step / 2
        o, c, h, l = r['open'], r['close'], r['high'], r['low']
        up = c >= o
        col = '#ef4444' if up else '#10b981'
        klass = ' candle-last' if i == len(rows) - 1 else ''
        parts.append(f'<line class="wick{klass}" x1="{x:.1f}" y1="{y(h):.1f}" x2="{x:.1f}" y2="{y(l):.1f}" stroke="{col}" stroke-width="1.35"/>')
        ry = min(y(o), y(c))
        rh = max(abs(y(o) - y(c)), 2.6)
        parts.append(f'<rect class="candle{klass}" x="{x-cw/2:.1f}" y="{ry:.1f}" width="{cw:.1f}" height="{rh:.1f}" fill="{col}" rx="1.8"/>')
        vh = (r.get('volume') or 0) / maxvol * vol_h
        parts.append(f'<rect class="volume-bar" x="{x-cw/2:.1f}" y="{vol_base-vh:.1f}" width="{cw:.1f}" height="{vh:.1f}" fill="{col}" opacity=".25" rx="1.5"/>')
        if i == len(rows) - 1:
            parts.append(f'<circle cx="{x:.1f}" cy="{y(c):.1f}" r="5.5" fill="white" stroke="{col}" stroke-width="2.6" filter="url(#lastGlow)"/>')

    # Date labels: first / quarter / middle / three-quarter / last, de-duplicated.
    label_idx = sorted(set([0, len(rows)//4, len(rows)//2, len(rows)*3//4, len(rows)-1]))
    for i in label_idx:
        date = str(rows[i].get('date') or '')[-5:] or str(i + 1)
        x = pad_l + i * step + step / 2
        parts.append(f'<line x1="{x:.1f}" y1="{vol_base+5}" x2="{x:.1f}" y2="{vol_base+10}" stroke="#cbd5e1"/><text x="{x:.1f}" y="{H-14}" text-anchor="middle" font-size="11" fill="#64748b">{e(date)}</text>')

    legend = [('MA5', '#f59e0b'), ('MA20', '#2563eb'), ('MA60', '#8b5cf6'), ('量能', '#94a3b8')]
    lx = pad_l
    for name, color in legend:
        parts.append(f'<circle cx="{lx}" cy="{H-30}" r="4" fill="{color}"/><text x="{lx+9}" y="{H-26}" font-size="11" fill="#64748b" font-weight="700">{name}</text>')
        lx += 62
    parts.append('</svg>')
    return ''.join(parts)


def signal_axis(chart):
    chart = chart or {}
    vals = [num(chart.get(k)) for k in ['stop', 'buy_low', 'buy_high', 'current', 'confirm_low', 'confirm_high', 'resistance']]
    vals = [v for v in vals if v is not None]
    if not vals:
        return '<div class="empty">暂无技术位</div>'
    mn, mx = min(vals), max(vals)
    pad = max((mx - mn) * .20, .1)
    mn -= pad
    mx += pad
    span = mx - mn or 1

    def pos(v):
        return max(0, min(100, (float(v) - mn) / span * 100))

    def marker(k, label, cls):
        v = num(chart.get(k))
        if v is None:
            return ''
        return f'<div class="sig-marker {cls}" style="left:{pos(v):.1f}%"><div class="sig-tag"><b>{label}</b><span>{v:.2f}</span></div></div>'

    def band(k1, k2, label, cls):
        a, b = num(chart.get(k1)), num(chart.get(k2))
        if a is None or b is None:
            return ''
        left = min(pos(a), pos(b))
        width = max(3.2, abs(pos(b) - pos(a)))
        return f'<div class="sig-band {cls}" style="left:{left:.1f}%;width:{width:.1f}%"><span>{label}</span></div>'

    return f'''<div class="sig">
      <div class="sig-zone sig-zone-danger" style="left:0;width:{pos(chart.get('stop') or mn):.1f}%"></div>
      {band('buy_low', 'buy_high', '观察买入', 'buy')}
      {band('confirm_low', 'confirm_high', '突破确认', 'confirm')}
      <div class="sig-axis"><i></i></div>
      {marker('stop', '失效', 'bad')}{marker('current', '现价', 'cur')}{marker('resistance', '压力', 'warn')}
    </div>'''


def metrics_html(metrics):
    icons = ['💰', '🏦', '📈', '🧾', '⚡', '🔍', '🌊', '⚠️']
    out = ''
    for i, m in enumerate(arr(metrics)[:8]):
        tone = tone_cls(m.get('tone'))
        out += f'''<div class="metric {tone}" style="--delay:{i*45}ms">
          <div class="ico">{icons[i % len(icons)]}</div><div><small>{e(m.get('label'))}</small><strong>{e(m.get('value'))}</strong><em>{e(m.get('delta'))}</em></div>
        </div>'''
    return out or '<div class="empty">暂无核心指标</div>'


def scores_html(scores):
    explain = {
        '行业景气度': '板块有没有风口，景气越高越容易顺风。',
        '公司竞争力': '公司强不强，护城河和市场地位是否稳。',
        '财务质量': '赚钱稳不稳，现金流和ROE是否健康。',
        '成长确定性': '未来能否继续增长，业绩兑现概率如何。',
        '估值性价比': '现在贵不贵，价格相对业绩是否划算。',
        '催化剂强度': '短期有没有推动股价的事件或预期。',
        '风险可控性': '坏情况是否容易识别、是否有明确失效线。',
    }
    out = ''
    for i, s in enumerate(arr(scores)):
        name = s.get('name') or s.get('label') or '评分'
        sc = max(0, min(10, num(s.get('score'), 0)))
        color, cname = score_color(sc)
        desc = s.get('desc') or s.get('explain') or explain.get(name, '分数越高，代表该维度越有优势。')
        out += f'''<div class="score-item score-{cname}" style="--accent:{color};--delay:{i*55}ms">
          <div class="score-copy"><b>{e(name)}</b><span>{e(desc)}</span></div>
          <div class="score-ring-wrap">{mini_ring(sc, i, name)}</div>
        </div>'''
    return out or '<div class="empty">暂无评分拆解</div>'


def summary_tiles(items):
    icons = ['✅', '🔍', '⚡', '⚠️', '📌']
    rows = arr(items)[:5]
    if not rows:
        return '<div class="muted">暂无摘要</div>'
    out = ''
    for i, x in enumerate(rows):
        tone = card_tone_from_text(x, 'neutral')
        out += f'<div class="summary-tile {tone}" style="--delay:{i*60}ms"><span>{icons[i % len(icons)]}</span><b>{e(x)}</b></div>'
    return out


def finance_trend_html(items):
    rows = arr(items)
    if not rows:
        return '<div class="empty">暂无财务趋势数据</div>'
    body = ''
    for r in rows[-6:]:
        tone = tone_cls(r.get('tone'))
        if any(k in r for k in ['revenue', 'profit', 'roe', 'cashflow']):
            body += f'<tr><td><b>{e(r.get("period") or r.get("label"))}</b></td><td>{e(r.get("revenue", "—"))}</td><td>{e(r.get("profit", "—"))}</td><td>{e(r.get("roe", "—"))}</td><td>{e(r.get("cashflow", "—"))}</td><td><em class="tone {tone}">{e(r.get("note", ""))}</em></td></tr>'
        else:
            body += f'<tr><td><b>{e(r.get("label"))}</b></td><td colspan="2">{e(r.get("value", "—"))}</td><td>{e(r.get("delta", "—"))}</td><td colspan="2"><em class="tone {tone}">{e(r.get("note", ""))}</em></td></tr>'
    return f'<div class="table-wrap"><table class="fin-table"><thead><tr><th>周期</th><th>营收</th><th>净利</th><th>ROE</th><th>现金流</th><th>一句话</th></tr></thead><tbody>{body}</tbody></table></div>'


def risk_heatmap_html(items):
    rows = arr(items)[:6]
    if not rows:
        rows = [{'level': '低', 'text': '暂无重大风险；仍需跟踪公告、财报和板块趋势。', 'mitigation': '保持数据更新，关键决策看公告。'}]
    out = ''
    for i, x in enumerate(rows):
        if isinstance(x, dict):
            level = str(x.get('level') or x.get('severity') or '中')
            text = x.get('text') or x.get('name') or x.get('risk') or ''
            note = x.get('mitigation') or x.get('note') or ''
        else:
            level, text, note = '中', str(x), ''
        cls = 'high' if level in ['高', '极高', 'high', 'High'] else ('low' if level in ['低', 'low', 'Low'] else 'mid')
        icon = '✕' if cls == 'high' else ('✓' if cls == 'low' else '!')
        out += f'''<div class="risk-card {cls}" style="--delay:{i*70}ms"><div class="risk-icon">{icon}</div>
          <strong>{e(level)}风险</strong><span>{e(text)}</span><small>{e(note)}</small></div>'''
    return out


def biz_html(items):
    colors = ['#10b981', '#06b6d4', '#f59e0b', '#8b5cf6', '#2563eb']
    out = ''
    for i, b in enumerate(arr(items)):
        share = max(0, min(100, num(b.get('share'), 0)))
        out += f'''<div class="biz"><div><b>{e(b.get('name'))}</b><span>{share:.1f}%</span></div>
          <div class="track"><i style="width:{share:.1f}%;background:{colors[i % len(colors)]}"></i></div>
          <small>收入 {e(b.get('revenue'))} · 毛利率 {e(b.get('margin'))}</small></div>'''
    return out or '<div class="empty">暂无业务结构数据</div>'


def comps_html(rows, current=None):
    all_rows = []
    if current:
        c = dict(current)
        c['is_current'] = True
        all_rows.append(c)
    all_rows.extend(arr(rows))
    if not all_rows:
        return '<div class="empty">暂无同行对比数据</div>'
    body = ''
    for c in all_rows[:8]:
        cls = ' class="current-row"' if c.get('is_current') else ''
        badge = '<i>当前</i>' if c.get('is_current') else ''
        body += f'<tr{cls}><td><b>{e(c.get("name"))}{badge}</b><span>{e(c.get("code"))}</span></td><td>{e(c.get("price", "—"))}</td><td>{e(c.get("valuation") or c.get("pepb") or "—")}</td><td><strong class="score-pill">{e(c.get("score", "—"))}</strong></td><td>{e(c.get("advantage"))}</td><td>{e(c.get("risk"))}</td><td><em>{e(c.get("scene"))}</em></td></tr>'
    return f'<div class="table-wrap"><table class="comp-table"><thead><tr><th>股票</th><th>现价</th><th>估值</th><th>评分</th><th>优势</th><th>风险</th><th>场景</th></tr></thead><tbody>{body}</tbody></table></div>'


def data_sources_html(items):
    if not arr(items):
        items = [
            {'name': '行情', 'source': '腾讯/新浪/东方财富', 'level': 'B', 'status': '建议双源校验'},
            {'name': '财报', 'source': 'F10/公告', 'level': 'A/B', 'status': '重要结论看公告'},
            {'name': 'K线', 'source': '新浪/东方财富', 'level': 'B', 'status': '可用于技术参考'},
        ]
    out = ''
    for i, x in enumerate(arr(items)):
        out += f'<div class="source" style="--delay:{i*50}ms"><em>{e(x.get("level"))}</em><b>{e(x.get("name"))}</b><span>{e(x.get("source"))}</span><small>{e(x.get("status"))}</small></div>'
    return out


def glossary_html(items):
    if not arr(items):
        items = [
            {'term': 'PE', 'desc': '市盈率，看价格相对利润贵不贵'},
            {'term': 'PB', 'desc': '市净率，券商/银行常用估值'},
            {'term': 'ROE', 'desc': '净资产收益率，看赚钱效率'},
            {'term': '扣非', 'desc': '扣掉一次性收益后的真实利润'},
            {'term': '右侧确认', 'desc': '等走势转强后再观察'},
        ]
    return ''.join(f'<div class="gloss"><b>{e(x.get("term"))}</b><span>{e(x.get("desc"))}</span></div>' for x in arr(items))


def key_value_lines(items):
    rows = []
    if isinstance(items, dict):
        rows = [f'{k}：{v}' for k, v in items.items() if v not in (None, '', [])]
    elif isinstance(items, list):
        rows = [str(x) for x in items if x not in (None, '')]
    return short_lines(rows, 6)


def tearsheet_html(tearsheet):
    t = tearsheet if isinstance(tearsheet, dict) else {}
    metrics = arr(t.get('key_metrics'))
    metric_html = ''.join(f'<span class="pill blue">{e(x)}</span>' for x in metrics[:6]) or '<span class="muted">暂无核心指标</span>'
    return f'''<section class="section grid g2" id="tearsheet">
<div class="card">
  <h2>公司一页纸</h2>
  <div class="mini-line"><span></span><b>{e(t.get('business') or '公司业务待补充')}</b></div>
  <div class="mini-line"><span></span><b>{e(t.get('industry_position') or '行业位置待补充')}</b></div>
  <div class="mini-line"><span></span><b>{e(t.get('model') or '商业模式待补充')}</b></div>
</div>
<div class="card neutral">
  <h2>关键指标与现在看点</h2>
  <div>{metric_html}</div>
  <div class="mini-line"><span></span><b>{e(t.get('why_now') or '等待财务、催化和技术结构共振。')}</b></div>
  <div class="mini-line"><span></span><b>{e(t.get('data_quality') or '关键结论仍需公告和交易所信息复核。')}</b></div>
</div>
</section>'''


def thesis_html(thesis):
    t = thesis if isinstance(thesis, dict) else {}
    return f'''<section class="section" id="thesis">
<div class="section-title"><h2>买方判断</h2><small>核心逻辑 + 正反证据 + 跟踪点</small></div>
<div class="grid g2">
  <div class="card good"><h2>核心 Thesis</h2><div class="mini-line"><span></span><b>{e(t.get('core_thesis') or '暂无核心逻辑')}</b></div><h2>增强证据</h2>{short_lines(t.get('evidence_for'), 5)}</div>
  <div class="card bad"><h2>削弱证据</h2>{short_lines(t.get('evidence_against'), 5)}<h2>差异化观点</h2><div class="mini-line"><span></span><b>{e(t.get('variant_view') or '暂无')}</b></div></div>
</div>
<div class="card neutral section"><h2>下一步跟踪</h2>{short_lines(t.get('what_to_watch'), 6)}</div>
</section>'''


def catalyst_timeline_html(items):
    rows = arr(items)
    if not rows:
        return '<div class="empty">暂无催化剂时间轴</div>'
    body = ''
    for x in rows:
        body += f'<tr><td><b>{e(x.get("window"))}</b></td><td>{e(x.get("event"))}</td><td><em class="tone {tone_cls("good" if "正" in str(x.get("impact")) else "neutral")}">{e(x.get("impact"))}</em></td><td>{e(x.get("confidence"))}</td><td>{e(x.get("watch"))}</td></tr>'
    return f'<div class="table-wrap"><table class="fin-table"><thead><tr><th>窗口</th><th>事件</th><th>影响</th><th>确定性</th><th>验证信号</th></tr></thead><tbody>{body}</tbody></table></div>'


def position_view_html(view, fallback_position=None):
    v = view if isinstance(view, dict) else {}
    stance = v.get('stance') or '观察'
    return f'''<section class="section grid g2" id="position">
<div class="card neutral">
  <h2>仓位 / 动作视图</h2>
  <div class="dh-dir">{e(stance)}</div>
  <div class="mini-line"><span></span><b>{e(v.get('size_hint') or '默认观察仓，等待更多证据。')}</b></div>
  {short_lines(v.get('rationale') or fallback_position, 5)}
</div>
<div class="card">
  <h2>提高暴露条件</h2>{short_lines(v.get('upgrade_triggers'), 5)}
  <h2>降低暴露条件</h2>{short_lines(v.get('downgrade_triggers'), 5)}
</div>
</section>'''


def thesis_tracker_html(tracker):
    t = tracker if isinstance(tracker, dict) else {}
    return f'''<section class="section grid g3" id="tracker">
<div class="card good"><h2>逻辑状态</h2><div class="mini-line"><span></span><b>{e(t.get('status') or '待验证')}</b></div></div>
<div class="card good"><h2>增强证据</h2>{short_lines(t.get('strengthening_evidence'), 4)}</div>
<div class="card bad"><h2>削弱证据</h2>{short_lines(t.get('weakening_evidence'), 4)}</div>
<div class="card neutral"><h2>复核触发</h2>{short_lines(t.get('next_review_triggers'), 5)}</div>
</section>'''


def valuation_html(valuation):
    v = valuation if isinstance(valuation, dict) else {}
    comps = v.get('comps_valuation') if isinstance(v.get('comps_valuation'), dict) else {}
    rng = v.get('valuation_range') if isinstance(v.get('valuation_range'), dict) else {}
    scenario_rows = arr(v.get('scenario_sensitivity'))
    body = ''
    for x in scenario_rows:
        sc = str(x.get('scenario') or '')
        tone = 'bad' if '悲' in sc else ('good' if '乐' in sc else 'neutral')
        body += f'<tr><td><em class="tone {tone}">{e(sc)}</em></td><td>{e(x.get("assumption"))}</td><td>{e(x.get("price_view"))}</td><td>{e(x.get("risk"))}</td></tr>'
    scenarios = f'<div class="table-wrap"><table class="fin-table"><thead><tr><th>情景</th><th>假设</th><th>价格/估值观察</th><th>风险</th></tr></thead><tbody>{body}</tbody></table></div>' if body else '<div class="empty">暂无情景敏感性</div>'
    return f'''<section class="section" id="valuation">
<div class="section-title"><h2>估值区间</h2><small>可比估值优先，DCF仅用于重点长期票</small></div>
<div class="grid g2">
  <div class="card"><h2>当前估值口径</h2><div class="mini-line"><span></span><b>{e(comps.get('current') or '暂无')}</b></div><div class="mini-line"><span></span><b>{e(comps.get('peer_context') or '同行估值待补充')}</b></div></div>
  <div class="card neutral"><h2>区间判断</h2>{key_value_lines(rng)}</div>
</div>
<div class="section card">{scenarios}</div>
<div class="grid g2 section"><div class="card neutral"><h2>核心假设</h2>{short_lines(v.get('assumptions'), 5)}</div><div class="card warn"><h2>模型审计提示</h2>{short_lines(v.get('audit_flags'), 5)}</div></div>
</section>'''


def get_css():
    """Dashboard CSS isolated from HTML for maintainability."""
    return r'''
:root{--ink:#12213f;--muted:#64748b;--line:#dfe8f5;--card:rgba(255,255,255,.78);--shadow:0 18px 42px rgba(30,56,96,.10);--green:#10b981;--red:#ef4444;--blue:#2563eb;--cyan:#06b6d4;--orange:#f59e0b;--purple:#8b5cf6}
*{box-sizing:border-box}html{scroll-behavior:smooth}body{margin:0;color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Microsoft YaHei",Arial,sans-serif;background:radial-gradient(circle at 8% 0,rgba(34,211,238,.18),transparent 28%),radial-gradient(circle at 90% 5%,rgba(139,92,246,.16),transparent 24%),linear-gradient(180deg,#edf5ff 0,#f5f8fd 42%,#fbfdff 100%);background-attachment:fixed}body:before{content:"";position:fixed;inset:0;pointer-events:none;z-index:-1;background-image:linear-gradient(rgba(15,23,42,.045) 1px,transparent 1px),linear-gradient(90deg,rgba(15,23,42,.045) 1px,transparent 1px),radial-gradient(circle,rgba(37,99,235,.12) 1px,transparent 1.4px);background-size:42px 42px,42px 42px,18px 18px;mask-image:linear-gradient(180deg,rgba(0,0,0,.72),rgba(0,0,0,.18))}.page{max-width:1180px;margin:0 auto;padding:18px}.nav{position:sticky;top:0;z-index:30;margin:0 -8px 14px;padding:9px 10px;display:flex;gap:8px;overflow-x:auto;scrollbar-width:none;background:rgba(241,247,255,.72);border:1px solid rgba(223,232,245,.7);border-radius:0 0 22px 22px;backdrop-filter:blur(16px) saturate(1.5);box-shadow:0 12px 34px rgba(15,23,42,.08)}.nav::-webkit-scrollbar{display:none}.nav a{white-space:nowrap;text-decoration:none;color:#1e3a8a;background:rgba(255,255,255,.72);border:1px solid rgba(203,213,225,.76);border-radius:999px;padding:8px 12px;font-size:12px;font-weight:900;transition:.22s}.nav a:hover,.nav a.active{color:white;background:linear-gradient(135deg,#2563eb,#06b6d4);border-color:transparent;box-shadow:0 10px 22px rgba(37,99,235,.22)}.hero{position:relative;overflow:hidden;border-radius:32px;padding:30px;color:white;background:radial-gradient(circle at 76% -10%,rgba(34,211,238,.54),transparent 34%),radial-gradient(circle at 100% 70%,rgba(168,85,247,.38),transparent 30%),linear-gradient(135deg,#071327 0,#0b2a59 44%,#0f766e 74%,#3b1d74 100%);box-shadow:0 28px 70px rgba(15,35,80,.30);isolation:isolate}.hero:before{content:"";position:absolute;inset:0;opacity:.20;background-image:radial-gradient(circle,rgba(255,255,255,.55) .7px,transparent .8px);background-size:8px 8px;mix-blend-mode:screen}.hero:after{content:"";position:absolute;inset:auto -20% -45% -20%;height:56%;background:radial-gradient(ellipse at center,rgba(20,184,166,.32),transparent 62%);filter:blur(28px);z-index:-1}.top{display:flex;justify-content:space-between;gap:24px;align-items:center;position:relative}.sub{opacity:.88;text-shadow:0 1px 10px rgba(0,0,0,.28);font-weight:650}.eyebrow{display:inline-flex;align-items:center;gap:8px;padding:6px 10px;border-radius:999px;background:rgba(255,255,255,.10);border:1px solid rgba(255,255,255,.20);font-size:12px;font-weight:900}h1{font-size:44px;line-height:1.05;margin:12px 0 8px;letter-spacing:-.05em}.verdict{font-size:21px;font-weight:1000;margin-top:14px;max-width:770px;line-height:1.45;color:#f8fdff;text-shadow:0 0 18px rgba(103,232,249,.42),0 2px 12px rgba(0,0,0,.28)}.hero-badges{display:flex;gap:9px;flex-wrap:wrap;margin-top:16px}.badge{padding:8px 12px;border-radius:999px;background:rgba(255,255,255,.14);border:1px solid rgba(255,255,255,.24);box-shadow:inset 0 1px 0 rgba(255,255,255,.18),0 10px 26px rgba(0,0,0,.10);backdrop-filter:blur(14px);font-weight:950;color:#fff}.hero-ring{flex:0 0 148px;width:148px;height:148px;overflow:visible}.ring-score{font-size:34px;font-weight:1000;fill:#fff;text-shadow:0 2px 10px rgba(0,0,0,.35)}.ring-label{font-size:13px;font-weight:800;fill:rgba(255,255,255,.76)}.ring-fg{animation:ringDraw 1.15s cubic-bezier(.2,.8,.2,1) both}.section{margin-top:20px}.section>h2,.card>h2{letter-spacing:-.025em}.section-title{display:flex;align-items:center;justify-content:space-between;gap:12px}.section-title small{color:#64748b;font-weight:800}.grid{display:grid;gap:14px}.g2{grid-template-columns:1fr 1fr}.g3{grid-template-columns:repeat(3,1fr)}.g4{grid-template-columns:repeat(4,1fr)}.card,.metric,.summary-tile,.source,.gloss{background:var(--card);border:1px solid rgba(223,232,245,.90);border-radius:22px;box-shadow:var(--shadow);backdrop-filter:blur(15px) saturate(1.15)}.card,.metric{padding:16px}.card{position:relative;overflow:hidden;animation:fadeInUp .55s ease both;transition:transform .24s ease,box-shadow .24s ease,border-color .24s ease}.card:hover,.metric:hover,.summary-tile:hover{transform:translateY(-3px);box-shadow:0 22px 52px rgba(30,56,96,.15)}.card:before,.metric:before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:linear-gradient(90deg,#2563eb,#06b6d4);opacity:.78}.card.good:before,.metric.good:before,.summary-tile.good:before{background:linear-gradient(90deg,#10b981,#67e8f9)}.card.bad:before,.metric.bad:before,.summary-tile.bad:before{background:linear-gradient(90deg,#ef4444,#f97316)}.card.warn:before,.metric.warn:before{background:linear-gradient(90deg,#f59e0b,#facc15)}h2{font-size:21px;margin:0 0 12px}.quick{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.quick .card b{display:block;font-size:15px;margin-bottom:6px}.quick .card span{font-size:13px;color:#526173;line-height:1.55}.summary-grid{display:grid;grid-template-columns:repeat(5,1fr);gap:10px}.summary-tile{position:relative;overflow:hidden;padding:14px;min-height:92px;animation:fadeInUp .55s ease both;animation-delay:var(--delay)}.summary-tile:before{content:"";position:absolute;inset:0 0 auto 0;height:3px;background:linear-gradient(90deg,#2563eb,#06b6d4)}.summary-tile span{font-size:22px;display:block;margin-bottom:8px}.summary-tile b{font-size:13px;line-height:1.5}.metric{position:relative;display:flex;gap:11px;overflow:hidden;animation:fadeInUp .55s ease both;animation-delay:var(--delay);transition:.24s}.metric .ico{font-size:25px;filter:drop-shadow(0 5px 10px rgba(37,99,235,.16))}.metric small,.metric em{display:block;color:#708099;font-size:11px;font-style:normal}.metric strong{display:block;font-size:21px;margin:4px 0}.metric.good{background:rgba(240,253,244,.76);border-color:#bbf7d0}.metric.warn{background:rgba(255,251,235,.80);border-color:#fde68a}.metric.bad{background:rgba(254,242,242,.80);border-color:#fecaca}.mini-line{position:relative;display:flex;gap:9px;align-items:flex-start;padding:10px 11px;border-radius:14px;background:rgba(246,249,253,.82);margin:7px 0;font-size:13px;line-height:1.48}.mini-line span{width:7px;height:7px;border-radius:50%;background:#06b6d4;margin-top:6px;box-shadow:0 0 0 4px rgba(6,182,212,.11)}.mini-line b{font-weight:720}.kline-svg{width:100%;height:420px;display:block;border-radius:22px}.grid-line{stroke:#e5edf7;stroke-width:1}.ma-line{filter:drop-shadow(0 1px 2px rgba(15,23,42,.12))}.candle-last{filter:url(#lastGlow)}.volume-bar{transition:opacity .2s}.sig{height:168px;position:relative;margin-top:4px}.sig-axis{position:absolute;left:4%;right:4%;top:88px;height:15px;border-radius:99px;background:rgba(226,232,240,.92);box-shadow:inset 0 2px 5px rgba(15,23,42,.10)}.sig-axis i{display:block;height:100%;border-radius:inherit;background:linear-gradient(90deg,#ef4444 0,#10b981 27%,#06b6d4 58%,#f59e0b 80%,#ef4444 100%);box-shadow:0 8px 22px rgba(37,99,235,.14)}.sig-zone{position:absolute;top:54px;height:70px;border-radius:18px;opacity:.15}.sig-zone-danger{background:#ef4444}.sig-band{position:absolute;top:56px;height:32px;border-radius:15px;text-align:center;font-weight:1000;font-size:12px;line-height:32px;box-shadow:0 8px 20px rgba(15,23,42,.08);overflow:hidden}.sig-band:after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.45),transparent);transform:translateX(-100%);animation:shine 3.2s infinite}.sig-band.buy{background:rgba(220,252,231,.92);color:#166534;border:1px solid #86efac}.sig-band.confirm{background:rgba(204,251,241,.94);color:#0f766e;border:1px solid #5eead4}.sig-marker{position:absolute;top:0;transform:translateX(-50%);text-align:center;min-width:70px}.sig-marker:after{content:"";display:block;width:0;height:0;margin:2px auto 0;border-left:7px solid transparent;border-right:7px solid transparent;border-top:8px solid #64748b}.sig-marker:before{content:"";position:absolute;left:50%;top:50px;width:2px;height:76px;background:#64748b;transform:translateX(-50%);opacity:.55}.sig-tag{padding:6px 8px;border-radius:13px;background:white;border:1px solid #dfe8f5;box-shadow:0 10px 22px rgba(15,23,42,.10)}.sig-marker b,.sig-marker span{display:block;font-size:11px}.sig-marker.cur .sig-tag{border-color:#2563eb;color:#1d4ed8}.sig-marker.cur:after{border-top-color:#2563eb}.sig-marker.cur:before{background:#2563eb;width:3px;animation:pulseLine 1.7s infinite}.sig-marker.bad .sig-tag{border-color:#ef4444;color:#b91c1c}.sig-marker.bad:after{border-top-color:#ef4444}.sig-marker.bad:before{background:#ef4444}.sig-marker.warn .sig-tag{border-color:#f59e0b;color:#92400e}.sig-marker.warn:after{border-top-color:#f59e0b}.sig-marker.warn:before{background:#f59e0b}.pill{padding:7px 11px;border-radius:99px;font-size:12px;font-weight:950;display:inline-block;margin:4px}.green{background:#dcfce7;color:#166534}.cyan{background:#ccfbf1;color:#0f766e}.blue{background:#dbeafe;color:#1d4ed8}.orange{background:#fef3c7;color:#92400e}.red{background:#fee2e2;color:#991b1b}.track{height:11px;background:#e9eef7;border-radius:99px;overflow:hidden}.track i{display:block;height:100%;border-radius:99px;background:linear-gradient(90deg,#6366f1,#22c55e)}.score-list{display:grid;grid-template-columns:1fr 1fr;gap:12px}.score-item{display:grid;grid-template-columns:1fr 70px;align-items:center;gap:12px;padding:12px;border:1px solid rgba(226,232,240,.92);border-radius:18px;background:rgba(255,255,255,.68);animation:fadeInUp .5s ease both;animation-delay:var(--delay);box-shadow:0 8px 20px rgba(30,56,96,.05)}.score-item{border-left:4px solid var(--accent)}.score-copy b{display:block;font-size:14px}.score-copy span{display:block;color:#64748b;font-size:12px;line-height:1.45;margin-top:4px}.mini-ring{width:64px;height:64px}.mini-ring text{font-size:15px;font-weight:1000;fill:#172554}.biz{margin:12px 0}.biz div:first-child{display:flex;justify-content:space-between;font-size:13px;margin-bottom:7px}.biz small{color:#718096}.risk-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:12px}.risk-card{position:relative;overflow:hidden;border-radius:20px;padding:15px;min-height:126px;font-size:12px;animation:fadeInUp .55s ease both;animation-delay:var(--delay);box-shadow:0 12px 28px rgba(30,56,96,.08)}.risk-card.high{color:#7f1d1d;background:linear-gradient(135deg,#fff1f2,#fee2e2);border:1px solid #fca5a5;animation:riskPulse 2.4s infinite}.risk-card.mid{color:#7c2d12;background:linear-gradient(135deg,#fff7ed,#fef3c7);border:1px solid #fdba74}.risk-card.low{color:#14532d;background:linear-gradient(135deg,#f0fdf4,#dcfce7);border:1px solid #86efac}.risk-icon{width:30px;height:30px;border-radius:50%;display:grid;place-items:center;font-weight:1000;background:rgba(255,255,255,.72);box-shadow:0 8px 18px rgba(15,23,42,.08)}.risk-card strong{display:block;margin:9px 0 5px;font-size:14px}.risk-card span,.risk-card small{display:block;line-height:1.5}.risk-card small{margin-top:7px;color:inherit;opacity:.78}.table-wrap{overflow-x:auto;border-radius:18px}.table-wrap::-webkit-scrollbar{height:8px}.table-wrap::-webkit-scrollbar-thumb{background:#cbd5e1;border-radius:99px}.comp-table,.fin-table{width:100%;min-width:920px;border-collapse:separate;border-spacing:0;background:rgba(255,255,255,.82);border:1px solid #dfe8f5;border-radius:18px;overflow:hidden;font-size:12px;box-shadow:0 10px 24px rgba(30,56,96,.06)}.comp-table th,.fin-table th{background:linear-gradient(180deg,#eff6ff,#eaf3ff);color:#334155;text-align:left;padding:11px;font-size:12px}.comp-table td,.fin-table td{padding:11px;border-top:1px solid #e8eef7;vertical-align:top}.fin-table tr:nth-child(even) td{background:#fbfdff}.tone{font-style:normal;border-radius:999px;padding:4px 8px;background:#eef4ff;color:#315fc2;font-weight:800}.tone.good{background:#dcfce7;color:#166534}.tone.warn{background:#fef3c7;color:#92400e}.tone.bad{background:#fee2e2;color:#991b1b}.comp-table tr.current-row td{background:linear-gradient(90deg,#ecfeff,#f0f9ff)}.comp-table td b{display:block}.comp-table td i{font-style:normal;font-size:9px;background:#06b6d4;color:white;border-radius:99px;padding:2px 6px;margin-left:5px}.comp-table td span{display:block;color:#64748b;font-size:10px}.comp-table em{font-style:normal;font-size:10px;background:#eef4ff;color:#315fc2;border-radius:99px;padding:4px 7px}.score-pill{display:inline-flex;min-width:40px;justify-content:center;padding:5px 8px;border-radius:99px;background:linear-gradient(135deg,#dcfce7,#dbeafe);font-weight:1000}.source,.gloss{padding:13px;position:relative;overflow:hidden;animation:fadeInUp .5s ease both;animation-delay:var(--delay)}.source b,.gloss b{display:block}.source span,.gloss span,.source small{display:block;color:#64748b;font-size:12px;margin-top:4px;line-height:1.45}.source em{float:right;background:#eef4ff;color:#315fc2;border-radius:999px;padding:3px 8px;font-style:normal;font-weight:1000}.footer{font-size:12px;color:#738096;margin:20px 0 6px;line-height:1.7}.empty,.muted{color:#718096;font-size:13px}.fade-in{animation:fadeInUp .6s ease both}@keyframes fadeInUp{from{opacity:0;transform:translateY(16px)}to{opacity:1;transform:translateY(0)}}@keyframes ringDraw{from{stroke-dashoffset:420;opacity:.35}to{stroke-dashoffset:0;opacity:1}}@keyframes shine{0%,55%{transform:translateX(-110%)}100%{transform:translateX(110%)}}@keyframes pulseLine{0%,100%{box-shadow:0 0 0 0 rgba(37,99,235,.38)}50%{box-shadow:0 0 0 8px rgba(37,99,235,0)}}@keyframes riskPulse{0%,100%{box-shadow:0 12px 28px rgba(239,68,68,.12)}50%{box-shadow:0 12px 34px rgba(239,68,68,.28)}}.debate-hero{text-align:center;padding:20px;border-radius:22px;background:var(--card);border:1px solid rgba(223,232,245,.9);box-shadow:var(--shadow);margin-bottom:14px}.debate-hero.good{border-left:5px solid var(--green)}.debate-hero.bad{border-left:5px solid var(--red)}.debate-hero.neutral{border-left:5px solid var(--orange)}.dh-dir{font-size:38px;font-weight:1000;margin-bottom:6px}.debate-hero.good .dh-dir{color:var(--green)}.debate-hero.bad .dh-dir{color:var(--red)}.debate-hero.neutral .dh-dir{color:var(--orange)}.dh-conf{font-size:16px;color:var(--muted);margin-bottom:12px}.dh-conf b{font-size:28px;color:var(--ink)}.dh-stat{font-size:13px;color:var(--muted);margin-top:10px;font-weight:800}.debate-gauge{max-width:480px;margin:10px auto}.dg-bar{display:flex;height:18px;border-radius:99px;overflow:hidden;background:#e9eef7}.dg-bull{background:linear-gradient(90deg,#10b981,#6ee7b7);transition:width .6s}.dg-bear{background:linear-gradient(90deg,#f87171,#ef4444);transition:width .6s}.dg-labels{display:flex;justify-content:space-between;font-size:12px;font-weight:900;margin-top:5px}.dg-labels .good{color:var(--green)}.dg-labels .bad{color:var(--red)}.debate-grid{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:14px}.debate-vote{padding:14px;border-radius:18px;background:var(--card);border:1px solid rgba(223,232,245,.9);box-shadow:0 8px 20px rgba(30,56,96,.06);transition:.24s}.debate-vote:hover{transform:translateY(-2px);box-shadow:0 14px 32px rgba(30,56,96,.12)}.debate-vote.good{border-left:4px solid var(--green)}.debate-vote.bad{border-left:4px solid var(--red)}.debate-vote.neutral{border-left:4px solid var(--orange)}.dv-head{display:flex;align-items:center;gap:6px;margin-bottom:6px;font-size:13px}.dv-head b{flex:1}.dv-tag{padding:3px 8px;border-radius:99px;font-size:11px;font-weight:900}.dv-tag.good{background:#dcfce7;color:#166534}.dv-tag.bad{background:#fee2e2;color:#991b1b}.dv-tag.neutral{background:#fef3c7;color:#92400e}.dv-liner{font-size:12px;color:#526173;line-height:1.5}.debate-summary{margin-top:14px}.debate-summary h3{margin:0 0 8px;font-size:16px}.debate-summary p{font-size:13px;line-height:1.6;color:#334155;margin:0 0 10px}.debate-action,.debate-level{font-size:12px;color:#475569;margin:4px 0}.debate-action b,.debate-level b{color:var(--ink)}
@media print{body{background:#fff}.nav{position:relative;box-shadow:none}.card,.metric,.summary-tile,.source,.gloss{box-shadow:none;break-inside:avoid}.hero{box-shadow:none}.card:hover,.metric:hover,.summary-tile:hover{transform:none}.sig-band:after{display:none}}@media(max-width:900px){.g4{grid-template-columns:repeat(2,1fr)}.g3,.quick,.summary-grid{grid-template-columns:repeat(2,1fr)}.score-list{grid-template-columns:1fr}.risk-grid{grid-template-columns:1fr 1fr}.debate-grid{grid-template-columns:1fr 1fr}}@media(max-width:760px){.page{padding:10px}.nav{border-radius:0 0 18px 18px}.top{display:block}h1{font-size:34px}.hero{padding:23px;border-radius:25px}.verdict{font-size:18px}.hero-ring{width:116px;height:116px;margin-top:18px}.g4,.g3,.g2,.quick,.summary-grid,.risk-grid,.debate-grid{grid-template-columns:1fr}.card,.metric{padding:15px}.kline-svg{height:330px}.sig{height:176px}.score-item{grid-template-columns:1fr 66px}.metric strong{font-size:20px}body{font-size:16px}.quick .card span,.mini-line,.summary-tile b{font-size:14px}}
'''


def get_js():
    """Tiny progressive enhancement: scroll-spy and visible animation hook."""
    return r'''
(function(){
  var links=[].slice.call(document.querySelectorAll('.nav a'));
  var sections=links.map(function(a){return document.querySelector(a.getAttribute('href'));}).filter(Boolean);
  if(!('IntersectionObserver' in window) || !sections.length) return;
  var byId={}; links.forEach(function(a){byId[a.getAttribute('href').slice(1)]=a;});
  var io=new IntersectionObserver(function(entries){
    entries.forEach(function(en){
      if(en.isIntersecting){
        links.forEach(function(a){a.classList.remove('active');});
        var link=byId[en.target.id]; if(link){link.classList.add('active'); link.scrollIntoView({inline:'center',block:'nearest',behavior:'smooth'});}
      }
    });
  },{rootMargin:'-42% 0px -52% 0px',threshold:0});
  sections.forEach(function(s){io.observe(s);});
})();
'''


def debate_html(debate):
    """Render the multi-agent debate section if present."""
    if not debate:
        return ''
    votes = debate.get('votes') or []
    if not votes:
        return ''

    direction = debate.get('direction', '中性')
    confidence = debate.get('confidence', 50)
    bull_pct = debate.get('bull_pct', 50)
    bear_pct = debate.get('bear_pct', 50)
    bull_count = debate.get('bull_count', 0)
    bear_count = debate.get('bear_count', 0)
    neutral_count = debate.get('neutral_count', 0)
    summary_text = e(debate.get('summary', ''))
    action_text = e(debate.get('action', ''))
    key_level = e(debate.get('key_level', ''))

    dir_emoji = {'看涨': '📈', '看跌': '📉', '中性': '⚖️'}.get(direction, '⚖️')
    dir_cls = {'看涨': 'good', '看跌': 'bad', '中性': 'neutral'}.get(direction, 'neutral')

    # Vote cards
    vote_cards = ''
    for v in votes:
        vdir = v.get('direction', '中性')
        v_emoji = {'看涨': '🟢', '看跌': '🔴', '中性': '🟡'}.get(vdir, '⚪')
        v_cls = {'看涨': 'good', '看跌': 'bad', '中性': 'neutral'}.get(vdir, 'neutral')
        vote_cards += f'''<div class="debate-vote {v_cls}">
<div class="dv-head"><span>{e(v.get('emoji',''))}</span><b>{e(v.get('name',''))}</b><span class="dv-tag {v_cls}">{v_emoji}{e(vdir)}({v.get('confidence',50)})</span></div>
<div class="dv-liner">{e(v.get('one_liner',''))}</div>
</div>'''

    # Gauge bar
    gauge = f'''<div class="debate-gauge">
<div class="dg-bar"><div class="dg-bull" style="width:{bull_pct}%"></div><div class="dg-bear" style="width:{bear_pct}%"></div></div>
<div class="dg-labels"><span class="good">多方 {bull_pct}%</span><span class="bad">空方 {bear_pct}%</span></div>
</div>'''

    return f'''<section class="section" id="debate">
<div class="section-title"><h2>⚖️ 多智能体博弈裁定</h2><small>6位分析师独立投票 → 博弈汇总</small></div>
<div class="debate-hero {dir_cls}">
<div class="dh-dir">{dir_emoji} {e(direction)}</div>
<div class="dh-conf">信心度 <b>{confidence}</b>/100</div>
{gauge}
<div class="dh-stat">看涨×{bull_count} · 看跌×{bear_count} · 中性×{neutral_count}</div>
</div>
<div class="debate-grid">{vote_cards}</div>
<div class="debate-summary card">
<h3>🎯 裁定理由</h3>
<p>{summary_text}</p>
<div class="debate-action"><b>操作建议：</b>{action_text}</div>
<div class="debate-level"><b>关键位：</b>{key_level}</div>
</div>
</section>'''


def research_insight_html(d):
    block = d.get('research_insight') or {}
    industry = arr(block.get('industry_viewpoints'))
    company = arr(block.get('company_report_consensus'))
    falsify = arr(block.get('falsification_checklist'))
    sources = arr(block.get('source_index'))
    if not industry:
        industry = ["细分行业景气仍受供需与价格周期共同驱动，需跟踪核心原料与加工价差。", "新增产能释放与行业库存去化节奏，会直接影响盈利弹性。"]
    if not company:
        company = ["研报共识通常聚焦：单吨盈利、客户结构变化、海外出货增速。", "常见分歧在于：盈利高位持续性与新产能利用率爬坡速度。"]
    if not falsify:
        falsify = ["若连续两个季度利润增速明显低于行业，需下调景气判断。", "若经营现金流与利润长期背离，需降低业绩质量权重。", "若关键产品价格趋势反转且无成本对冲，需重估估值中枢。"]
    if not sources:
        sources = [{"title": "交易所公告/公司IR", "date": "持续跟踪", "url": ""}, {"title": "主流券商公开研报", "date": "近90天", "url": ""}]

    def lines(items):
        return ''.join(f'<div class="mini-line"><span></span><b>{e(x)}</b></div>' for x in items)

    src_html = ""
    for s in sources:
        if isinstance(s, dict):
            title = e(s.get('title', ''))
            date = e(s.get('date', ''))
            url = s.get('url') or ''
        else:
            title = e(s); date = ''; url = ''
        link = f' <a href="{e(url)}" target="_blank" rel="noreferrer">链接</a>' if url else ''
        src_html += f'<div class="mini-line"><span></span><b>{title}</b> <em>{date}</em>{link}</div>'

    return f'''<section class="section" id="insight">
<div class="section-title"><h2>行业/研报深度洞察</h2><small>细分行业 + 个股研报观点提炼</small></div>
<div class="grid g2"><div class="card"><h2>行业脉络</h2>{lines(industry)}</div><div class="card"><h2>个股研报共识</h2>{lines(company)}</div></div>
<div class="grid g2"><div class="card warn"><h2>分歧与证伪清单</h2>{lines(falsify)}</div><div class="card neutral"><h2>来源索引</h2>{src_html}</div></div>
</section>'''


def render(d):
    score = num(d.get('score'), 0)
    tp = d.get('trade_plan') or {}
    pv = d.get('position_view') or {}
    action = e(d.get('action') or '观察')
    stance = e(pv.get('stance') or d.get('action') or '观察')
    risk = e(d.get('risk_level') or '中')
    risks = arr(d.get('risks'))
    first_risk = '业绩或趋势证伪'
    if risks:
        first_risk = (risks[0].get('text') or risks[0].get('name') or '业绩或趋势证伪') if isinstance(risks[0], dict) else str(risks[0])
    first_summary = (arr(d.get('summary')) + [d.get('industry') or '业务与行业信息待补充'])[0]
    valuation_note = next((m.get('delta') for m in arr(d.get('metrics')) if 'PE' in str(m.get('label')) or 'PB' in str(m.get('label'))), '看估值卡')
    tracker = (arr(d.get('trackers')) or ['关键支撑和财报'])[0]
    css = get_css()
    js = get_js()

    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(d.get('title'))} 股票看板</title><style>{css}</style></head><body><div class="page">
<nav class="nav"><a href="#overview" class="active">总览</a><a href="#tearsheet">一页纸</a><a href="#thesis">Thesis</a><a href="#position">仓位</a><a href="#valuation">估值</a><a href="#finance">财务</a><a href="#peer">同行</a><a href="#risk">风险</a><a href="#kline">K线</a><a href="#trade">买卖点</a><a href="#debate">博弈</a><a href="#source">数据</a></nav>
<section class="hero" id="overview"><div class="top"><div><div class="eyebrow">China Stock Investment Sandbox · {e(d.get('date'))}</div><h1>{e(d.get('title'))} {e(d.get('code'))}</h1><div class="sub">{e(d.get('industry'))} · {e(d.get('market'))}</div><div class="verdict">{e(d.get('verdict'))}</div><div class="hero-badges"><span class="badge">仓位视图：{stance}</span><span class="badge">当前动作：{action}</span><span class="badge">风险等级：{risk}</span><span class="badge">评分：{score:.1f}/10</span></div></div>{ring_svg(score)}</div></section>
<section class="section grid g4">{metrics_html(d.get('metrics'))}</section>
{tearsheet_html(d.get('company_tearsheet'))}
{thesis_html(d.get('investment_thesis'))}
<section class="section" id="catalyst"><div class="section-title"><h2>催化剂时间轴</h2><small>30 / 60 / 90 天验证</small></div>{catalyst_timeline_html(d.get('catalyst_timeline'))}</section>
{position_view_html(d.get('position_view'), tp.get('position'))}
{valuation_html(d.get('valuation'))}
<section class="section grid g2" id="score"><div class="card"><h2>评分拆解</h2><div class="score-list">{scores_html(d.get('scores') or d.get('score_breakdown'))}</div></div><div class="card"><h2>业务结构</h2>{biz_html(d.get('business'))}</div></section>
<section class="section card" id="finance"><h2>📈 财务趋势</h2>{finance_trend_html(d.get('finance_trend') or d.get('financials') or d.get('financial_trend'))}</section>
<section class="section" id="peer"><h2>🔁 同行对比 / 更优选择</h2>{comps_html(d.get('comparables'), d.get('current_compare'))}</section>
<section class="section" id="risk"><div class="section-title"><h2>⚠️ 风险热力卡</h2><small>高风险优先看，低风险不等于没风险</small></div><div class="risk-grid">{risk_heatmap_html(d.get('risks'))}</div></section>
{thesis_tracker_html(d.get('thesis_tracker'))}
<section class="section grid g2"><div class="card good"><h2>短期催化</h2>{short_lines(d.get('catalysts'),5)}</div><div class="card neutral"><h2>跟踪指标</h2>{short_lines(d.get('trackers'),5)}</div></section>
<section class="section card" id="kline"><h2>📉 K线走势 + 信号位</h2>{kline_chart(d.get('kline'), d.get('signal_chart') or {})}</section>
<section class="section card"><h2>🧭 买卖信号轴</h2>{signal_axis(d.get('signal_chart') or {})}<span class="pill green">🟢 观察买入</span><span class="pill cyan">📈 突破确认</span><span class="pill orange">🟠 压力/减仓</span><span class="pill red">🔴 失效止损</span></section>
<section class="section grid g3" id="trade"><div class="card good"><h2>🟢 买入观察</h2>{short_lines(tp.get('buy_left'))}</div><div class="card good"><h2>📈 右侧确认</h2>{short_lines(tp.get('buy_right'))}</div><div class="card neutral"><h2>🔵 持有条件</h2>{short_lines(tp.get('hold'))}</div></section>
<section class="section grid g2"><div class="card warn"><h2>🟠 减仓警戒</h2>{short_lines(tp.get('sell'))}</div><div class="card bad"><h2>🔴 失效条件</h2>{short_lines(tp.get('stop'))}</div></section>
<section class="section grid g2"><div class="card neutral"><h2>仓位思路</h2>{short_lines(tp.get('position'),5)}</div><div class="card bad"><h2>重新评估</h2>{short_lines(d.get('reevaluate'),5)}</div></section>
{debate_html(d.get('debate'))}
{research_insight_html(d)}
<section class="section grid g2" id="source"><div><h2>🧾 数据可信度</h2><div class="grid g3">{data_sources_html(d.get('data_sources'))}</div></div><div><h2>📚 术语小抄</h2><div class="grid g2">{glossary_html(d.get('glossary'))}</div></div></section>
<div class="footer">免责声明：本看板基于公开信息与行情/财务聚合数据整理，仅作研究参考，不构成投资建议；买卖点均为条件化观察，不代表确定收益。关键决策请以交易所公告、公司披露和券商实时行情为准。</div>
</div><script>{js}</script></body></html>'''


def stable_output_path(data, requested):
    """Return a durable attachment path under the OpenClaw workspace.

    Telegram delivery may happen after the assistant turn is rendered, so files in
    /tmp or mktemp directories are fragile. Keep HTML artifacts in workspace/outputs
    unless the caller already supplied a durable non-/tmp path.
    """
    p = Path(requested).expanduser()
    raw = str(p)
    if p.is_absolute() and not raw.startswith('/tmp/') and '/tmp/' not in raw:
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    out_dir = Path(os.environ.get('OPENCLAW_WORKSPACE', '/root/.openclaw/workspace')) / 'outputs'
    out_dir.mkdir(parents=True, exist_ok=True)
    code = re.sub(r'[^0-9A-Za-z]+', '', str(data.get('code') or data.get('symbol') or data.get('title') or 'stock'))[:16] or 'stock'
    date = re.sub(r'[^0-9]', '', str(data.get('date') or ''))[:8] or datetime.now().strftime('%Y%m%d')
    return out_dir / f'stock_{code}_{date}.html'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--out-html', '--out', dest='out_html', required=True)
    ap.add_argument('--out-pdf')
    a = ap.parse_args()
    d = json.load(open(a.input, encoding='utf-8'))
    out_html = stable_output_path(d, a.out_html)
    out_html.write_text(render(d), encoding='utf-8')
    if not out_html.exists() or out_html.stat().st_size <= 0:
        raise RuntimeError(f'HTML output is empty or missing: {out_html}')
    out_pdf = a.out_pdf
    if out_pdf:
        out_pdf = str(Path(out_pdf).expanduser())
        browser = shutil.which('chromium') or shutil.which('google-chrome') or shutil.which('chrome')
        if browser:
            subprocess.check_call([browser, '--headless', '--disable-gpu', '--no-sandbox', '--print-to-pdf-no-header', f'--print-to-pdf={out_pdf}', out_html.absolute().as_uri()])
        else:
            from weasyprint import HTML
            HTML(str(out_html)).write_pdf(out_pdf)
    print(json.dumps({'html': str(out_html), 'pdf': out_pdf, 'media_line': f'MEDIA:{out_html}'}, ensure_ascii=False))


if __name__ == '__main__':
    main()
