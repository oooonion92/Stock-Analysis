from __future__ import annotations

import json
import mimetypes
import os
import re
import sys
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path

import pandas as pd

from chanlun_v10_20_core import analyze_frame_original, dif_peak, macd_momentum


ROOT = Path(__file__).resolve().parent
LEGACY_DATA_DIR = Path(r"D:\OneDrive\Stock\details")
DATA_DIR = Path(os.environ.get("CHANLUN_DATA_DIR", str(LEGACY_DATA_DIR)))
HOST = "127.0.0.1"
PORT = 8765
APP_VERSION = "V10.20-0603-1715"
DEFAULT_TRADING_DAYS = 30
WATCH_KEEP_BARS_5M = 48
SM_EXTREME_BUFFER = 0.0005
INDEX_NAMES = {
    "sh000001": "上证指数",
    "sh000300": "沪深300",
    "sh000852": "中证1000",
    "sh000905": "中证500",
    "sz399001": "深证成指",
    "sz399006": "创业板指",
}
STOCK_NAME_CACHE: dict[str, str] = {}

SENSITIVITY_PROFILE = {
    "aggressive": {"hold_ratio": 0.998, "break_ratio": 1.0},
    "balanced": {"hold_ratio": 1.0, "break_ratio": 1.001},
    "conservative": {"hold_ratio": 1.002, "break_ratio": 1.003},
}


HTML = r"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>缠论互动沙盘 V10.21</title>
  <style>
    :root {
      --bg: #f3f6fa;
      --panel: #ffffff;
      --line: #d9dee7;
      --text: #20242a;
      --muted: #677282;
      --red: #d94b45;
      --green: #23956b;
      --blue: #245985;
      --orange: #ff7f0e;
      --buy-soft: #fff1ef;
      --sell-soft: #eef8f3;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Microsoft YaHei", "Segoe UI", Arial, sans-serif;
      background: var(--bg);
      color: var(--text);
      overflow: hidden;
    }
    .app {
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
      height: 100vh;
      min-width: 980px;
    }
    aside {
      background: var(--panel);
      border-right: 1px solid var(--line);
      padding: 18px 16px;
      overflow: auto;
      box-shadow: 8px 0 24px rgba(27, 39, 53, 0.04);
    }
    main {
      display: grid;
      grid-template-rows: auto minmax(620px, calc(100vh - 96px)) auto;
      min-width: 0;
      overflow: auto;
    }
    h1 {
      font-size: 21px;
      margin: 0 0 4px;
      letter-spacing: 0;
    }
    .sub {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.45;
      margin-bottom: 18px;
    }
    label {
      display: block;
      font-size: 13px;
      font-weight: 700;
      color: #3d4652;
      margin: 14px 0 6px;
    }
    input, select, button {
      width: 100%;
      height: 38px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: white;
      color: var(--text);
      padding: 0 10px;
      font: inherit;
    }
    button {
      cursor: pointer;
      background: linear-gradient(180deg, #2e6696, #1f4e79);
      border-color: #1f4e79;
      color: white;
      font-weight: 700;
    }
    button.secondary {
      background: #eef3f8;
      color: #1f4e79;
      border-color: #c8d7e7;
    }
    button:disabled {
      opacity: 0.55;
      cursor: wait;
    }
    .select-action {
      display: grid;
      grid-template-columns: 1fr 38px;
      gap: 8px;
      align-items: center;
    }
    .row {
      display: grid;
      grid-template-columns: 1fr 46px;
      gap: 8px;
    }
    .period-row {
      display: grid;
      grid-template-columns: 1fr 38px;
      gap: 8px;
      align-items: center;
    }
    .date-picker {
      position: relative;
      width: 38px;
      height: 38px;
    }
    .icon-btn {
      min-width: 38px;
      padding: 0;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 17px;
      line-height: 1;
    }
    .date-btn {
      width: 38px;
      height: 38px;
    }
    .date-picker input[type="date"] {
      position: absolute;
      inset: 0;
      width: 38px;
      height: 38px;
      opacity: 0;
      padding: 0;
      cursor: pointer;
    }
    .date-picker.has-date .date-btn {
      background: #e9f2ff;
      color: #1f4e79;
      border-color: #93b8e6;
    }
    .chip {
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 7px 8px;
      font-size: 13px;
      text-align: center;
      cursor: pointer;
      user-select: none;
      background: #f8fafc;
    }
    .chip.active {
      background: #e9f2ff;
      color: #1f4e79;
      border-color: #93b8e6;
      font-weight: 700;
    }
    .legend {
      margin-top: 6px;
      border: 1px solid var(--line);
      border-radius: 6px;
      padding: 8px;
      background: #fbfdff;
      font-size: 12px;
      color: #3d4652;
      line-height: 1.45;
    }
    .legend-row {
      display: none;
      grid-template-columns: 54px 1fr;
      gap: 8px;
      align-items: center;
      margin: 4px 0;
    }
    .legend-tag {
      border-radius: 4px;
      padding: 2px 6px;
      text-align: center;
      font-weight: 700;
      border: 1px solid transparent;
    }
    .legend-30m {
      color: #a65308;
      background: rgba(248, 173, 91, 0.18);
      border-color: rgba(240, 140, 42, 0.52);
    }
    .legend-5m {
      color: #3b82c6;
      background: rgba(191, 219, 254, 0.30);
      border-color: rgba(147, 197, 253, 0.64);
    }
    .legend-1d {
      color: #855514;
      background: rgba(187, 130, 43, 0.13);
      border-color: rgba(187, 130, 43, 0.48);
    }
    .legend-actions {
      display: flex;
      gap: 6px;
      margin: 8px 0 2px;
      flex-wrap: wrap;
    }
    .legend-chip {
      min-width: 56px;
      border-radius: 6px;
      border: 1px solid #cbd8ea;
      background: #eef3ff;
      color: #2a4a75;
      font-weight: 700;
      font-size: 12px;
      padding: 5px 8px;
      text-align: center;
      cursor: pointer;
      user-select: none;
    }
    .legend-chip.off {
      opacity: 0.45;
      background: #f5f7fb;
      color: #5d6b7e;
      border-color: #d8dee8;
    }
    .detail {
      margin-top: 16px;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: linear-gradient(180deg, #ffffff, #f8fafc);
      padding: 10px;
      font-size: 13px;
      line-height: 1.45;
    }
    .detail h2 {
      font-size: 13px;
      margin: 0 0 8px;
    }
    .kv {
      display: grid;
      grid-template-columns: 76px 1fr;
      gap: 5px 8px;
      margin-top: 6px;
    }
    .kv span:nth-child(odd) {
      color: var(--muted);
    }
    .note {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--line);
      color: #3d4652;
    }
    .evidence-list {
      margin-top: 8px;
      padding-top: 8px;
      border-top: 1px solid var(--line);
      display: grid;
      gap: 6px;
      color: #3d4652;
    }
    .evidence-row {
      display: grid;
      grid-template-columns: 58px 1fr;
      gap: 8px;
      align-items: baseline;
    }
    .evidence-row span {
      color: var(--muted);
    }
    .evidence-row b {
      color: #18212d;
    }
    .topbar {
      display: flex;
      align-items: center;
      gap: 12px;
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      padding: 12px 18px;
      min-width: 0;
      box-shadow: 0 8px 20px rgba(27, 39, 53, 0.035);
    }
    .title {
      font-weight: 800;
      white-space: nowrap;
      min-width: 0;
    }
    .status {
      color: var(--muted);
      font-size: 12px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .version-tag {
      margin-left: auto;
      color: #8a97a8;
      font-size: 12px;
      opacity: 0.58;
      white-space: nowrap;
    }
    .canvas-wrap {
      position: relative;
      overflow: hidden;
      background: #ffffff;
      padding: 10px 14px 8px;
      min-height: 620px;
      max-height: calc(100vh - 96px);
    }
    canvas {
      width: 100%;
      height: 100%;
      display: block;
      cursor: crosshair;
      border-radius: 6px;
    }
    .hint {
      border-top: 1px solid var(--line);
      padding: 8px 16px;
      background: var(--panel);
      color: var(--muted);
      font-size: 12px;
    }
    .error {
      margin-top: 10px;
      color: #a73535;
      font-size: 12px;
      line-height: 1.4;
      min-height: 18px;
    }
    @media (max-width: 980px) {
      body { overflow: auto; }
      .app { grid-template-columns: 1fr; height: auto; min-width: 0; }
      aside { border-right: 0; border-bottom: 1px solid var(--line); }
      main { height: 78vh; }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <h1>缠论互动沙盘</h1>
      <div class="sub">本地 CSV 优先，可在线同步新浪分钟线。默认采用 30m 决策级别，更适合 A 股 T+1；5m 后续作为区间套细化观察。</div>

      <label>标的</label>
      <div class="select-action">
        <select id="symbol"></select>
        <button id="refreshBtn" class="icon-btn" title="刷新当前标的" aria-label="刷新当前标的">↻</button>
      </div>

      <label>在线同步 / 新增标的</label>
      <div class="row">
        <input id="fetchSymbol" placeholder="如 sh000001 / 000001" />
        <button id="fetchBtn" class="icon-btn" title="同步或新增标的" aria-label="同步或新增标的">⇅</button>
      </div>

      <label>周期与起点</label>
      <div class="period-row">
        <select id="period">
          <option value="30m">30m 决策</option>
          <option value="5m" selected>5m 观察</option>
        </select>
        <div class="date-picker" id="startDatePicker">
          <button id="startDateBtn" class="icon-btn secondary date-btn" title="选择起点日期" aria-label="选择起点日期">▣</button>
          <input id="startDate" type="date" aria-label="起点日期" />
        </div>
      </div>

      <label>信号过滤</label>
      <div class="legend-actions" id="levelLegendActions"></div>
      <div class="legend">
        <div id="levelLegendDesc" style="margin-top:4px;color:#607086;"></div>
        <div><b>图例（当前仅显示：本级别 + 上一级别）</b></div>
        <div class="legend-row">
          <span class="legend-tag legend-5m">5m</span>
          <span>5m 决策时显示：5m + 30m</span>
        </div>
        <div class="legend-row">
          <span class="legend-tag legend-30m">30m</span>
          <span>30m 决策时显示：30m + 日线</span>
        </div>
        <div class="legend-row">
          <span class="legend-tag legend-1d">1d</span>
          <span>日线为 30m 聚合得到的上一级结构</span>
        </div>
      </div>

      <div class="detail" id="currentBox">
        <h2>当前结构</h2>
        <div class="kv">
          <span>状态</span><b id="curState">-</b>
          <span>价格</span><b id="curPrice">-</b>
          <span>中枢</span><b id="curZs">-</b>
        </div>
      </div>
      <div class="detail" id="signalBox">
        <h2>信号证据</h2>
        <div id="signalDetail">点击图上的买卖点查看结构证据链。</div>
      </div>
      <div id="err" class="error"></div>
    </aside>

    <main>
      <div class="topbar">
        <div class="title" id="chartTitle">等待数据</div>
        <div class="status" id="status">加载中...</div>
        <div class="version-tag" id="versionTag"></div>
      </div>
      <div class="canvas-wrap">
        <canvas id="chart"></canvas>
      </div>
      <div class="hint">滚轮缩放，拖动平移，双击图表恢复全量；鼠标悬停查看时间与价格。红色为买点，绿色为卖点。</div>
    </main>
  </div>

  <script>
    const state = {
      data: null,
      viewStart: 0,
      viewEnd: 1,
      dragging: false,
      dragX: 0,
      dragMoved: false,
      hover: null,
      selectedSignalId: null,
      signalHitboxes: [],
      activeLevels: new Set(),
      autoStartDate: true,
      theme5m: "soft"
    };

    const $ = id => document.getElementById(id);
    const canvas = $("chart");
    const ctx = canvas.getContext("2d");

    function setStatus(text) { $("status").textContent = text; }
    function setError(text) { $("err").textContent = text || ""; }
    function paletteFor5m() {
      if (state.theme5m === "clear") {
        return {
          line: "#4b98e6",
          zsFill: "rgba(147, 197, 253, 0.24)",
          zsStroke: "rgba(96, 165, 250, 0.70)",
          buyMain: [66, 141, 220],
          buySoft: [238, 248, 255],
          sellMain: [49, 118, 198],
          sellSoft: [231, 244, 255],
        };
      }
      return {
        line: "#9cc9ff",
        zsFill: "rgba(219, 234, 254, 0.24)",
        zsStroke: "rgba(147, 197, 253, 0.62)",
        buyMain: [101, 163, 234],
        buySoft: [247, 251, 255],
        sellMain: [77, 140, 215],
        sellSoft: [241, 248, 255],
      };
    }

    async function api(path) {
      const res = await fetch(path);
      const json = await res.json();
      if (!res.ok || json.error) throw new Error(json.error || res.statusText);
      return json;
    }

    function renderLevelLegend() {
      const actions = $("levelLegendActions");
      const desc = $("levelLegendDesc");
      if (!actions || !desc) return;
      const layers = state.data?.layers || [];
      actions.innerHTML = "";
      if (!layers.length) {
        desc.textContent = "暂无级别数据";
        return;
      }
      for (const layer of layers) {
        const lv = String(layer.level || "").toLowerCase();
        const chip = document.createElement("div");
        chip.className = "legend-chip" + (state.activeLevels.has(lv) ? "" : " off");
        chip.textContent = lv;
        chip.onclick = () => {
          if (state.activeLevels.has(lv)) {
            if (state.activeLevels.size <= 1) return;
            state.activeLevels.delete(lv);
          } else {
            state.activeLevels.add(lv);
          }
          renderLevelLegend();
          draw();
        };
        actions.appendChild(chip);
      }
      desc.textContent = `当前显示：${[...state.activeLevels].join(" + ")}`;
    }

    function updateStartDateControl() {
      const picker = $("startDatePicker");
      const btn = $("startDateBtn");
      const input = $("startDate");
      if (!picker || !btn || !input) return;
      const isManual = Boolean(input.value) && !state.autoStartDate;
      picker.classList.toggle("has-date", isManual);
      btn.title = isManual ? `起点日期：${input.value}` : "选择起点日期";
      btn.setAttribute("aria-label", btn.title);
    }

    async function loadStocks(selectPreferred) {
      const data = await api("/api/stocks");
      const sel = $("symbol");
      sel.innerHTML = "";
      for (const item of data.stocks) {
        const opt = document.createElement("option");
        opt.value = item.symbol;
        opt.textContent = item.symbol;
        opt.title = item.name ? `${item.name} ${item.symbol}` : item.symbol;
        opt.dataset.name = item.name || "";
        sel.appendChild(opt);
      }
      if (selectPreferred && data.stocks.some(s => s.symbol === selectPreferred)) sel.value = selectPreferred;
      if (!sel.value && data.stocks[0]) sel.value = data.stocks[0].symbol;
      return sel.value;
    }

    async function loadAnalysis() {
      const symbol = $("symbol").value;
      const period = $("period").value;
      const sensitivity = ($("sensitivity")?.value || "balanced");
      const start = state.autoStartDate ? "" : ($("startDate").value || "");
      if (!symbol) return;
      setError("");
      setStatus("分析中...");
      const data = await api(`/api/analyze?symbol=${encodeURIComponent(symbol)}&period=${period}&start=${start}&sensitivity=${sensitivity}`);
      state.data = data;
      state.activeLevels = new Set((data.layers || []).map(l => String(l.level || "").toLowerCase()));
      renderLevelLegend();
      state.viewStart = 0;
      state.viewEnd = data.bars.length;
      const periodName = period === "30m" ? "30m 决策级别" : "5m 观察级别";
      const displayName = data.stock_name && data.stock_name !== data.symbol
        ? `${data.stock_name} ${data.symbol}`
        : data.symbol || symbol;
      $("chartTitle").textContent = `${displayName} · ${periodName}`;
      $("versionTag").textContent = data.version || data.summary.app_version || "V10.20";
      if (state.autoStartDate && data.summary.default_start_date) {
        $("startDate").value = data.summary.default_start_date;
      }
      updateStartDateControl();
      updateCurrentBox(data.current);
      state.selectedSignalId = null;
      renderSignalDetail(null);
      setStatus(`数据范围 ${data.summary.first_time} 至 ${data.summary.last_time}`);
      resizeAndDraw();
    }

    function stateText(code) {
      return {
        above_active_bi_zs: "中枢上方离开",
        below_active_bi_zs: "中枢下方离开",
        inside_active_bi_zs: "中枢震荡区",
        no_center: "暂无中枢"
      }[code] || code || "-";
    }

    function updateCurrentBox(cur) {
      if (!cur) return;
      $("curState").textContent = stateText(cur.state);
      $("curPrice").textContent = Number(cur.price || 0).toFixed(2);
      if (cur.active_zs) {
        $("curZs").textContent = `ZD ${cur.active_zs.ZD.toFixed(2)} / ZG ${cur.active_zs.ZG.toFixed(2)}`;
      } else {
        $("curZs").textContent = "-";
      }
    }

    function fmtPct(v) {
      if (v == null || Number.isNaN(v)) return "-";
      return `${v > 0 ? "+" : ""}${Number(v).toFixed(2)}%`;
    }

    function signalTimeMs(sig) {
      return new Date(String(sig?.time || "").replace(" ", "T")).getTime();
    }

    function lowerLevelSignalsFor(sig) {
      if (!sig || !state.data?.layers?.length) return [];
      const sigLevel = String(sig.level || state.data.period || "").toLowerCase();
      const lowerLevel = sigLevel === "30m" ? "5m" : sigLevel === "1d" ? "30m" : "";
      if (!lowerLevel) return [];
      const lowerLayer = state.data.layers.find(layer => String(layer.level || "").toLowerCase() === lowerLevel);
      if (!lowerLayer) return [];
      const selfSegments = sig.evidence?.evidence_layers?.self_level?.segments || [];
      const focusSeg = selfSegments[selfSegments.length - 1];
      if (!focusSeg?.start || !focusSeg?.end) return [];
      const startMs = new Date(focusSeg.start.replace(" ", "T")).getTime();
      const endMs = new Date(focusSeg.end.replace(" ", "T")).getTime();
      if (!Number.isFinite(startMs) || !Number.isFinite(endMs)) return [];
      const lo = Math.min(startMs, endMs);
      const hi = Math.max(startMs, endMs);
      return [...(lowerLayer.signals || []), ...(lowerLayer.candidates || [])]
        .filter(item => {
          const t = signalTimeMs(item);
          return Number.isFinite(t) && t >= lo && t <= hi;
        })
        .sort((a, b) => signalTimeMs(a) - signalTimeMs(b))
        .slice(-8);
    }

    function renderSignalDetail(sig) {
      const box = $("signalDetail");
      if (!sig) {
        box.textContent = "点击图上的买卖点查看结构证据链。";
        return;
      }
      const ev = sig.evidence || {};
      const evZs = ev.zs || ev;
      const f10 = sig.forward?.n10 || {};
      const zsLine = evZs.ZD != null ? `ZD ${Number(evZs.ZD).toFixed(2)} / ZG ${Number(evZs.ZG).toFixed(2)}` : "-";
      const boundary = ev.boundary_name ? `${ev.boundary_name} ${Number(ev.boundary).toFixed(2)}` : "-";
      const macdLine = ev.macd_test_area != null
        ? `${Number(ev.macd_test_area).toFixed(3)} / ${Number(ev.macd_base_area).toFixed(3)}`
        : ev.macd_current_area != null
          ? `${Number(ev.macd_current_area).toFixed(3)} / ${Number(ev.macd_previous_area).toFixed(3)}`
          : "-";
      const difLine = ev.dif_current_peak != null
        ? `${Number(ev.dif_current_peak).toFixed(3)} / ${Number(ev.dif_previous_peak).toFixed(3)}`
        : "-";
      const smTrace = ev.source === "state_machine_5m_to_30m"
        ? `状态机: 5m候选 ${ev.candidate_5m_time || "-"} → 30m B0 ${ev.b0_time || "-"} → T1 ${ev.t1_time || "-"} → B1 ${ev.b1_time || "-"} → T2 ${ev.t2_time || "-"}`
        : "";
      const levelLabel = (sig.level || state.data?.period || "").toLowerCase();
      const selfEv = ev.evidence_layers?.self_level || null;
      const segmentNameZh = {
        entry: "入中枢前段",
        leave: "离开段",
        build: "一买后上冲段",
        pullback: "回调段",
        crash: "一卖后下跌段",
        rebound: "反抽段",
      };
      const guardNameZh = {
        "1B low": "1买低点",
        "1S high": "1卖高点",
        ZG: "中枢上沿 ZG",
        ZD: "中枢下沿 ZD",
      };
      const trendBasisZh = {
        "single related center; classify as consolidation divergence / exhaustion": "只关联到一个中枢，按盘整背驰/震荡衰竭处理，不强行判定趋势背驰。",
        "two descending centers support downtrend divergence": "前后两个中枢下移，支持下跌趋势背驰。",
        "prior center exists but centers are not clearly descending": "存在前序中枢，但中枢没有明确下移，按盘整背驰/震荡衰竭处理。",
        "two ascending centers support uptrend divergence": "前后两个中枢上移，支持上涨趋势背驰。",
        "prior center exists but centers are not clearly ascending": "存在前序中枢，但中枢没有明确上移，按盘整背驰/震荡衰竭处理。",
        "second buy checks the first pullback after 1B; focus is not breaking the 1B low and weaker pullback momentum": "二买看一买后的第一次回调，重点是回调不破一买低点，且回调动能弱于前段上冲。",
        "second sell checks the first rebound after 1S; focus is not breaking the 1S high and weaker rebound momentum": "二卖看一卖后的第一次反抽，重点是反抽不破一卖高点，且反抽动能弱于前段下跌。",
        "third buy checks pullback after leaving the center; focus is staying above ZG": "三买看离开中枢后的回调，重点是回调不跌回中枢上沿 ZG。",
        "third sell checks rebound after leaving the center; focus is staying below ZD": "三卖看离开中枢后的反抽，重点是反抽不突破中枢下沿 ZD。",
      };
      const basisZh = {
        "classic V10.20 signal": "V10.20 经典结构信号",
        "local down-up-down divergence watch; needs higher-level non-break and breakout to confirm": "本级别下-上-下背驰观察，需要更高一级别不破并重新突破后确认。",
        "local up-down-up divergence watch; needs higher-level non-break and breakdown to confirm": "本级别上-下-上背驰观察，需要更高一级别不破并重新跌破后确认。",
        "5m local divergence after 30m center breakout; pullback stayed above the center, so classify as 30m third buy": "30分钟中枢向上离开后，5分钟局部背驰且回调守在中枢上方，归类为30分钟三买。",
        "5m local divergence after 30m center breakdown; rebound stayed below the center, so classify as 30m third sell": "30分钟中枢向下离开后，5分钟局部背驰且反抽压在中枢下方，归类为30分钟三卖。",
        "Daily center breakout, pullback stayed above daily ZG, then price broke the prior daily high; promoted as 1d third buy.": "日线中枢向上离开，回调守住日线 ZG，随后突破前高，提升为日线三买。",
      };
      const ruleZh = {
        "5m watch + 30m center breakout pullback above ZG -> 30m 3B": "5分钟候选 + 30分钟中枢上破，回调守住 ZG，确认30分钟三买。",
        "5m watch + 30m center breakdown rebound below ZD -> 30m 3S": "5分钟候选 + 30分钟中枢下破，反抽压在 ZD 下方，确认30分钟三卖。",
        "1d center formed -> upward leave -> pullback low stayed above daily ZG -> next daily break above leave top -> 1d-3B": "日线中枢形成 → 向上离开 → 回调低点守住日线 ZG → 次日突破离开段高点 → 日线三买。",
      };
      const lifeStateZh = {
        confirmed: "已确认",
        watch: "观察候选",
        risk: "高级别风险降级",
        invalidated: "已失效",
        expired: "观察期结束",
      };
      const segBrief = (seg) => `${segmentNameZh[seg.name] || seg.name} ${seg.macd_area ?? "-"} / DIF ${seg.dif_extreme ?? "-"}`;
      const classText = selfEv?.divergence_class === "trend_divergence"
        ? "趋势背驰"
        : selfEv?.divergence_class === "consolidation_divergence"
          ? "盘整背驰 / 震荡衰竭"
          : selfEv?.divergence_class === "pullback_confirmation"
            ? "二买回调确认"
            : selfEv?.divergence_class === "rebound_confirmation"
              ? "二卖反抽确认"
              : selfEv?.divergence_class === "center_non_return"
                ? "三类买卖点不回中枢"
                : "暂未归类";
      const guardText = selfEv?.guard_name && selfEv.guard_value != null
        ? `${guardNameZh[selfEv.guard_name] || selfEv.guard_name} ${Number(selfEv.guard_value).toFixed(2)}`
        : "无";
      const trendText = trendBasisZh[selfEv?.trend_basis] || selfEv?.trend_basis || "";
      const segmentLine = selfEv?.segments?.length
        ? selfEv.segments.map(segBrief).join(" ｜ ")
        : "暂无本级别对比段";
      const macdBrief = selfEv?.segments?.length
        ? `${selfEv.macd_ratio ?? "-"}（${segmentLine}）`
        : macdLine;
      const lowerSignals = lowerLevelSignalsFor(sig);
      const lowerBrief = lowerSignals.length
        ? lowerSignals.map(item => `${item.level}-${item.label}${item.status === "watch" ? "*" : ""} ${item.time}`).join("；")
        : "无";
      const promotionBrief = ev.source === "state_machine_5m_to_30m"
        ? (smTrace || "由次级别状态机确认")
        : "无";
      const life = sig.lifecycle || ev.lifecycle || {};
      const lifecycleBrief = life.state
        ? `${lifeStateZh[life.state] || life.state}${life.confirmed_at ? `，确认 ${life.confirmed_at}` : ""}${life.watch_until ? `，观察到 ${life.watch_until}` : ""}${life.invalidated_at ? `，失效 ${life.invalidated_at}` : ""}${life.expired_at ? `，过期 ${life.expired_at}` : ""}`
        : "无";
      const basisLine = basisZh[sig.basis] || sig.basis || "";
      const ruleLine = ruleZh[ev.rule] || ev.rule || "";
      box.innerHTML = `
        <div class="kv">
          <span>类型</span><b>${levelLabel}-${sig.label} / ${Math.round(sig.confidence * 100)}%</b>
          <span>时间</span><b>${sig.time}</b>
          <span>价格</span><b>${Number(sig.price).toFixed(2)}</b>
          <span>中枢</span><b>${zsLine}</b>
          <span>边界</span><b>${boundary}</b>
          <span>MACD</span><b>${macdLine}</b>
          <span>DIF峰值</span><b>${difLine}</b>
          <span>后10根</span><b>有利 ${fmtPct(f10.favorable_pct)} / 不利 ${fmtPct(f10.adverse_pct)}</b>
        </div>
        <div class="evidence-list">
          <div class="evidence-row"><span>结论</span><b>${classText}</b></div>
          <div class="evidence-row"><span>防守</span><b>${guardText}</b></div>
          <div class="evidence-row"><span>MACD</span><b>${macdBrief}</b></div>
          <div class="evidence-row"><span>区间套</span><b>${lowerBrief}</b></div>
          <div class="evidence-row"><span>状态</span><b>${lifecycleBrief}</b></div>
        </div>
        <div class="note"><b>说明</b><br>${trendText || basisLine || "按信号当时及以前的完整历史生成。"}${promotionBrief !== "无" ? `<br>${promotionBrief}` : ""}${ruleLine ? `<br>${ruleLine}` : ""}${ev.logic_text ? `<br>${ev.logic_text}` : ""}</div>
      `;
    }

    function filteredSignals() {
      if (!state.data) return [];
      const src = (state.data.layers || []).flatMap(layer => [...(layer.signals || []), ...(layer.candidates || [])]);
      return src.filter(s => state.activeLevels.has(String(s.level || state.data.period || "").toLowerCase()));
    }

    function visibleRange() {
      const n = state.data?.bars.length || 0;
      let s = Math.max(0, Math.floor(state.viewStart));
      let e = Math.min(n, Math.ceil(state.viewEnd));
      if (e - s < 20) e = Math.min(n, s + 20);
      return [s, e];
    }

    function rightFutureBars(data) {
      const bars = data?.bars || [];
      if (!bars.length) return 0;
      const counts = new Map();
      for (const b of bars) {
        const day = String(b.time || "").slice(0, 10);
        if (!day) continue;
        counts.set(day, (counts.get(day) || 0) + 1);
      }
      const last = bars[bars.length - 1];
      const lastDay = String(last.time || "").slice(0, 10);
      const lastHm = String(last.time || "").slice(11, 16);
      const expected = Math.max(1, ...counts.values());
      const currentDayBars = counts.get(lastDay) || expected;
      if (lastHm >= "15:00") return expected;
      return Math.max(0, expected - currentDayBars);
    }

    function resetView() {
      if (!state.data) return;
      state.viewStart = 0;
      state.viewEnd = state.data.bars.length;
      draw();
    }

    function clampView() {
      if (!state.data) return;
      const n = state.data.bars.length;
      let span = state.viewEnd - state.viewStart;
      if (!Number.isFinite(span) || span <= 0) {
        state.viewStart = 0;
        state.viewEnd = n;
        return;
      }
      span = Math.max(20, Math.min(n, span));
      if (span >= n - 0.001) {
        state.viewStart = 0;
        state.viewEnd = n;
        return;
      }
      state.viewStart = Math.max(0, Math.min(n - span, state.viewStart));
      state.viewEnd = state.viewStart + span;
    }

    function resizeAndDraw() {
      const rect = canvas.parentElement.getBoundingClientRect();
      const dpr = window.devicePixelRatio || 1;
      const cssW = Math.max(900, Math.floor(rect.width));
      const cssH = Math.max(620, Math.min(860, Math.floor(rect.height)));
      canvas.width = Math.floor(cssW * dpr);
      canvas.height = Math.floor(cssH * dpr);
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      canvas.style.width = `${cssW}px`;
      canvas.style.height = `${cssH}px`;
      draw();
    }

    function draw() {
      const data = state.data;
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      ctx.clearRect(0, 0, w, h);
      ctx.fillStyle = "#fff";
      ctx.fillRect(0, 0, w, h);
      if (!data || !data.bars.length) return;

      const [s, e] = visibleRange();
      const bars = data.bars.slice(s, e);
      const left = 78, right = 26, top = 24, priceH = Math.floor(h * 0.70), gap = 24;
      const macdTop = top + priceH + gap, macdH = h - macdTop - 42;
      const plotW = w - left - right;
      const lows = bars.map(b => b.low), highs = bars.map(b => b.high);
      let minP = Math.min(...lows), maxP = Math.max(...highs);
      const pad = Math.max((maxP - minP) * 0.04, 1e-6);
      minP -= pad; maxP += pad;
      const atLatestEdge = state.viewEnd >= data.bars.length - 0.001;
      const futureBars = atLatestEdge ? rightFutureBars(data) : 0;
      const xEnd = e + futureBars;
      const x = i => left + ((i - s) / Math.max(xEnd - s - 1, 1)) * plotW;
      const y = p => top + (maxP - p) / (maxP - minP) * priceH;
      const idxFromTime = new Map(data.bars.map((b, i) => [b.time, i]));
      const barTs = data.bars.map(b => new Date(b.time.replace(" ", "T")).getTime());
      const xByTime = (timeStr) => {
        const i = idxFromTime.get(timeStr);
        if (i != null) return x(i);
        const t = new Date(timeStr.replace(" ", "T")).getTime();
        if (!Number.isFinite(t) || !barTs.length) return null;
        if (t <= barTs[0]) return x(0);
        if (t >= barTs[barTs.length - 1]) return x(barTs.length - 1);
        let lo = 0, hi = barTs.length - 1;
        while (lo <= hi) {
          const mid = (lo + hi) >> 1;
          if (barTs[mid] < t) lo = mid + 1;
          else hi = mid - 1;
        }
        const r = Math.max(1, lo);
        const l = r - 1;
        const span = Math.max(1, barTs[r] - barTs[l]);
        const ratio = (t - barTs[l]) / span;
        return x(l + ratio);
      };
      const layersRaw = (data.layers && data.layers.length) ? data.layers : [{ level: data.period, bi_points: data.bi_points, zs: data.zs, signals: data.signals, candidates: data.candidates || [], macd: data.bars }];
      const layers = layersRaw.filter(layer => state.activeLevels.has(String(layer.level || data.period).toLowerCase()));
      const viewStartTs = barTs[s] || barTs[0] || 0;
      const viewEndTs = barTs[Math.min(e - 1, barTs.length - 1)] || viewStartTs;
      const overlayMacdBars = [];
      for (const layer of layers) {
        if (String(layer.level || data.period).toLowerCase() === String(data.period || "").toLowerCase()) continue;
        for (const m of (layer.macd || [])) {
          const t = new Date(String(m.time || "").replace(" ", "T")).getTime();
          if (Number.isFinite(t) && t >= viewStartTs && t <= viewEndTs) overlayMacdBars.push(m);
        }
      }
      const macdAbs = Math.max(
        1e-6,
        ...bars.map(b => Math.abs(b.macd || 0)),
        ...bars.map(b => Math.abs(b.dif || 0)),
        ...bars.map(b => Math.abs(b.dea || 0)),
        ...overlayMacdBars.map(b => Math.abs(b.macd || 0)),
        ...overlayMacdBars.map(b => Math.abs(b.dif || 0)),
        ...overlayMacdBars.map(b => Math.abs(b.dea || 0)),
      );
      const ym = v => macdTop + (macdAbs - v) / (macdAbs * 2) * macdH;
      const levelPalette = {
        "30m": {
          line: "#f08c2a",
          zsFill: "rgba(248, 173, 91, 0.18)",
          zsStroke: "rgba(240, 140, 42, 0.68)",
          buyMain: [217, 75, 69],
          buySoft: [255, 241, 239],
          sellMain: [35, 149, 107],
          sellSoft: [238, 248, 243],
        },
        "5m": paletteFor5m(),
        "1d": {
          line: "#bb822b",
          zsFill: "rgba(187, 130, 43, 0.10)",
          zsStroke: "rgba(187, 130, 43, 0.52)",
          buyMain: [182, 118, 31],
          buySoft: [255, 247, 233],
          sellMain: [133, 85, 20],
          sellSoft: [252, 242, 226],
        },
      };
      state.signalHitboxes = [];
      const visibleSignals = filteredSignals()
        .filter(sig => {
          const i = idxFromTime.get(sig.time);
          if (i != null) return i >= s && i < e;
          const xx = xByTime(sig.time);
          return xx != null && xx >= left && xx <= w - right;
        });
      const recentSignalIds = new Set(visibleSignals.slice(-10).map(sig => sig.id));
      const selectedSignal = visibleSignals.find(sig => sig.id === state.selectedSignalId)
        || (data.layers || []).flatMap(layer => [...(layer.signals || []), ...(layer.candidates || [])]).find(sig => sig.id === state.selectedSignalId)
        || null;
      const auxiliarySignalIds = new Set(lowerLevelSignalsFor(selectedSignal).map(sig => sig.id));
      const selectedZs = selectedSignal?.evidence?.zs || null;
      const sameTime = (a, b) => String(a || "").slice(0, 16) === String(b || "").slice(0, 16);
      const samePrice = (a, b) => Math.abs(Number(a) - Number(b)) < 1e-4;
      const isFocusedZs = (z) => selectedZs
        && sameTime(z.start, selectedZs.start)
        && sameTime(z.end, selectedZs.end)
        && samePrice(z.ZD, selectedZs.ZD)
        && samePrice(z.ZG, selectedZs.ZG);
      const macdCompareWindows = (sig) => {
        if (!sig) return [];
        const ev = sig.evidence || {};
        const selfSegments = ev.evidence_layers?.self_level?.segments || [];
        if (selfSegments.length) {
          const divClass = ev.evidence_layers?.self_level?.divergence_class;
          const isRange = divClass === "consolidation_divergence";
          return selfSegments.map((seg, idx) => ({
            start: seg.start,
            end: seg.end,
            label: isRange ? `range-${seg.name || (idx === 0 ? "entry" : "leave")}` : (seg.name || (idx === 0 ? "entry" : "leave")),
            color: idx === 0 ? "rgba(245, 158, 11, 0.20)" : "rgba(59, 130, 246, 0.18)",
            stroke: idx === 0 ? "rgba(245, 158, 11, 0.70)" : "rgba(59, 130, 246, 0.72)",
          }));
        }
        if (ev.prev_leg_start && ev.prev_same_time && ev.middle_time && ev.current_time) {
          return [
            { start: ev.prev_leg_start, end: ev.prev_same_time, label: "prev", color: "rgba(245, 158, 11, 0.20)", stroke: "rgba(245, 158, 11, 0.70)" },
            { start: ev.middle_time, end: ev.current_time, label: "current", color: "rgba(59, 130, 246, 0.18)", stroke: "rgba(59, 130, 246, 0.72)" },
          ];
        }
        if (ev.zs?.start && ev.zs?.end && sig.time) {
          return [
            { start: ev.zs.start, end: ev.zs.end, label: "center", color: "rgba(245, 158, 11, 0.16)", stroke: "rgba(245, 158, 11, 0.60)" },
            { start: ev.zs.end, end: sig.time, label: "leave", color: "rgba(59, 130, 246, 0.15)", stroke: "rgba(59, 130, 246, 0.66)" },
          ];
        }
        if (ev.first_signal_time && sig.time) {
          return [
            { start: ev.first_signal_time, end: sig.time, label: "compare", color: "rgba(59, 130, 246, 0.16)", stroke: "rgba(59, 130, 246, 0.68)" },
          ];
        }
        return [];
      };

      ctx.strokeStyle = "#d9dee7";
      ctx.lineWidth = 1;
      ctx.font = "13px Microsoft YaHei, Arial";
      ctx.fillStyle = "#677282";
      for (let k = 0; k <= 5; k++) {
        const p = minP + (maxP - minP) * k / 5;
        const yy = y(p);
        ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(w - right, yy); ctx.stroke();
        ctx.fillText(p.toFixed(1), 12, yy + 4);
      }
      ctx.strokeRect(left, top, plotW, priceH);
      ctx.strokeRect(left, macdTop, plotW, macdH);

      ctx.save();
      ctx.strokeStyle = "rgba(36, 89, 133, 0.16)";
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 7]);
      for (let i = s + 1; i < e; i++) {
        const prevDay = String(data.bars[i - 1].time).slice(0, 10);
        const curDay = String(data.bars[i].time).slice(0, 10);
        if (curDay === prevDay) continue;
        const xx = x(i);
        ctx.beginPath();
        ctx.moveTo(xx, top);
        ctx.lineTo(xx, macdTop + macdH);
        ctx.stroke();
      }
      ctx.restore();

      for (const layer of [...layers].reverse()) {
        const pal = levelPalette[layer.level] || levelPalette["30m"];
        const lastZs = layer.zs.length ? layer.zs[layer.zs.length - 1] : null;
        for (const z of layer.zs) {
          const x1raw = xByTime(z.start), x2raw = xByTime(z.end);
          if (x1raw == null || x2raw == null) continue;
          const x1 = Math.max(left, Math.min(x1raw, x2raw));
          const x2 = Math.min(w - right, Math.max(x1raw, x2raw));
          if (x2 < left || x1 > w - right) continue;
          const active = lastZs && z.start === lastZs.start && z.end === lastZs.end;
          const focused = isFocusedZs(z);
          ctx.save();
          if (selectedSignal) ctx.globalAlpha = focused ? 1 : 0.16;
          ctx.fillStyle = pal.zsFill;
          ctx.strokeStyle = pal.zsStroke;
          ctx.lineWidth = focused ? 2.4 : active ? 1.8 : 1.1;
          ctx.fillRect(x1, y(z.ZG), Math.max(1, x2 - x1), Math.max(1, y(z.ZD) - y(z.ZG)));
          ctx.strokeRect(x1, y(z.ZG), Math.max(1, x2 - x1), Math.max(1, y(z.ZD) - y(z.ZG)));
          ctx.restore();
        }
      }
      ctx.lineWidth = 1;

      const candleW = Math.max(1, Math.min(8, plotW / Math.max(e - s, 1) * 0.62));
      for (let i = s; i < e; i++) {
        const b = data.bars[i];
        const xx = x(i);
        const up = b.close >= b.open;
        ctx.strokeStyle = up ? "#d62728" : "#2ca02c";
        ctx.fillStyle = ctx.strokeStyle;
        ctx.beginPath(); ctx.moveTo(xx, y(b.low)); ctx.lineTo(xx, y(b.high)); ctx.stroke();
        const y1 = y(Math.max(b.open, b.close));
        const y2 = y(Math.min(b.open, b.close));
        ctx.fillRect(xx - candleW / 2, y1, candleW, Math.max(1, y2 - y1));
      }

      for (const layer of layers) {
        const pal = levelPalette[layer.level] || levelPalette["30m"];
        ctx.strokeStyle = pal.line;
        ctx.lineWidth = layer.level === data.period ? 1.6 : 1.15;
        ctx.beginPath();
        let moved = false;
        for (const p of layer.bi_points) {
          const xx = xByTime(p.time);
          if (xx == null || xx < left || xx > w - right) continue;
          if (!moved) { ctx.moveTo(xx, y(p.value)); moved = true; }
          else ctx.lineTo(xx, y(p.value));
        }
        if (moved) ctx.stroke();
      }

      const selectedSelfEv = selectedSignal?.evidence?.evidence_layers?.self_level || null;
      const guardValue = Number(selectedSelfEv?.guard_value);
      if (selectedSignal && Number.isFinite(guardValue) && guardValue >= minP && guardValue <= maxP) {
        const guardLabels = {
          "1B low": "1买低点",
          "1S high": "1卖高点",
          ZG: "中枢上沿 ZG",
          ZD: "中枢下沿 ZD",
        };
        const gy = y(guardValue);
        const text = `失效线 ${guardLabels[selectedSelfEv.guard_name] || selectedSelfEv.guard_name || ""} ${guardValue.toFixed(2)}`;
        ctx.save();
        ctx.strokeStyle = "rgba(220, 38, 38, 0.72)";
        ctx.fillStyle = "rgba(220, 38, 38, 0.92)";
        ctx.lineWidth = 1.4;
        ctx.setLineDash([6, 5]);
        ctx.beginPath();
        ctx.moveTo(left, gy);
        ctx.lineTo(w - right, gy);
        ctx.stroke();
        ctx.setLineDash([]);
        ctx.font = "bold 11px Microsoft YaHei, Arial";
        const tw = ctx.measureText(text).width + 12;
        const tx = Math.max(left + 4, w - right - tw - 6);
        const ty = Math.max(top + 4, Math.min(top + priceH - 19, gy - 18));
        ctx.fillStyle = "rgba(255, 255, 255, 0.88)";
        ctx.fillRect(tx, ty, tw, 18);
        ctx.strokeStyle = "rgba(220, 38, 38, 0.40)";
        ctx.strokeRect(tx, ty, tw, 18);
        ctx.fillStyle = "rgba(185, 28, 28, 0.95)";
        ctx.fillText(text, tx + 6, ty + 13);
        ctx.restore();
      }

      ctx.lineWidth = 1;
      const zero = ym(0);
      ctx.strokeStyle = "#888"; ctx.beginPath(); ctx.moveTo(left, zero); ctx.lineTo(w - right, zero); ctx.stroke();
      let prevD = null, prevE = null;
      for (let i = s; i < e; i++) {
        const b = data.bars[i];
        const xx = x(i), by = ym(b.macd || 0);
        ctx.fillStyle = b.macd >= 0 ? "rgba(214,39,40,.48)" : "rgba(44,160,44,.48)";
        ctx.fillRect(xx - candleW / 2, Math.min(zero, by), candleW, Math.max(1, Math.abs(zero - by)));
        const d = [xx, ym(b.dif || 0)], de = [xx, ym(b.dea || 0)];
        if (prevD) {
          ctx.strokeStyle = "#1f77b4"; ctx.beginPath(); ctx.moveTo(...prevD); ctx.lineTo(...d); ctx.stroke();
          ctx.strokeStyle = "#ff7f0e"; ctx.beginPath(); ctx.moveTo(...prevE); ctx.lineTo(...de); ctx.stroke();
        }
        prevD = d; prevE = de;
      }

      function drawMacdLine(points, key, style, dash = []) {
        ctx.save();
        ctx.strokeStyle = style;
        ctx.lineWidth = 1.35;
        ctx.setLineDash(dash);
        ctx.beginPath();
        let moved = false;
        for (const m of points) {
          const xx = xByTime(m.time);
          if (xx == null || xx < left || xx > w - right) continue;
          const yy = ym(m[key] || 0);
          if (!moved) { ctx.moveTo(xx, yy); moved = true; }
          else ctx.lineTo(xx, yy);
        }
        if (moved) ctx.stroke();
        ctx.restore();
      }

      function drawMacdValueLine(points, valueFn, style, dash = []) {
        ctx.save();
        ctx.strokeStyle = style;
        ctx.lineWidth = 1.35;
        ctx.setLineDash(dash);
        ctx.beginPath();
        let moved = false;
        for (const m of points) {
          const xx = xByTime(m.time);
          if (xx == null || xx < left || xx > w - right) continue;
          const yy = ym(valueFn(m));
          if (!moved) { ctx.moveTo(xx, yy); moved = true; }
          else ctx.lineTo(xx, yy);
        }
        if (moved) ctx.stroke();
        ctx.restore();
      }

      function higherMacdAtTime(timeStr) {
        const t = new Date(String(timeStr || "").replace(" ", "T")).getTime();
        if (!Number.isFinite(t)) return null;
        const baseLevel = String(data.period || "").toLowerCase();
        let best = null;
        for (const layer of layers) {
          const lv = String(layer.level || data.period).toLowerCase();
          if (lv === baseLevel) continue;
          for (const m of (layer.macd || [])) {
            const mt = new Date(String(m.time || "").replace(" ", "T")).getTime();
            if (!Number.isFinite(mt)) continue;
            const dist = Math.abs(mt - t);
            if (!best || dist < best.dist) best = { level: lv, macd: m.macd || 0, dif: m.dif || 0, dea: m.dea || 0, dist };
          }
        }
        return best;
      }

      for (const layer of layers) {
        if (String(layer.level || data.period).toLowerCase() === String(data.period || "").toLowerCase()) continue;
        const points = (layer.macd || [])
          .map(m => ({ ...m, xx: xByTime(m.time) }))
          .filter(m => m.xx != null && m.xx >= left && m.xx <= w - right)
          .sort((a, b) => a.xx - b.xx);
        if (!points.length) continue;
        const stripH = 18;
        const stripY = macdTop + macdH - stripH;
        ctx.save();
        for (let j = 0; j < points.length; j++) {
          const m = points[j];
          const prevX = j > 0 ? points[j - 1].xx : left;
          const nextX = j < points.length - 1 ? points[j + 1].xx : w - right;
          const x1 = j > 0 ? (prevX + m.xx) / 2 : left;
          const x2 = j < points.length - 1 ? (m.xx + nextX) / 2 : w - right;
          const v = Number(m.macd || 0);
          const nearZero = Math.abs(v) < macdAbs * 0.018;
          ctx.fillStyle = nearZero
            ? "rgba(120, 132, 150, 0.10)"
            : v > 0
              ? "rgba(240, 140, 42, 0.13)"
              : "rgba(35, 149, 107, 0.11)";
          ctx.fillRect(x1, stripY, Math.max(1, x2 - x1), stripH);
        }
        ctx.strokeStyle = "rgba(120, 132, 150, 0.18)";
        ctx.strokeRect(left, stripY, plotW, stripH);
        ctx.fillStyle = "rgba(124, 84, 32, 0.58)";
        ctx.font = "11px Microsoft YaHei, Arial";
        ctx.fillText(`${String(layer.level || "").toLowerCase()} MACD`, left + 6, stripY + 13);
        ctx.restore();
        drawMacdValueLine(points, m => ((Number(m.dif || 0) + Number(m.dea || 0)) / 2), "rgba(217, 119, 6, 0.44)", [7, 5]);
      }

      for (const win of macdCompareWindows(selectedSignal)) {
        const x1raw = xByTime(win.start), x2raw = xByTime(win.end);
        if (x1raw == null || x2raw == null) continue;
        const x1 = Math.max(left, Math.min(x1raw, x2raw));
        const x2 = Math.min(w - right, Math.max(x1raw, x2raw));
        if (x2 < left || x1 > w - right) continue;
        ctx.save();
        ctx.fillStyle = win.color;
        ctx.strokeStyle = win.stroke;
        ctx.lineWidth = 1.4;
        ctx.fillRect(x1, macdTop, Math.max(1, x2 - x1), macdH);
        ctx.strokeRect(x1, macdTop, Math.max(1, x2 - x1), macdH);
        ctx.fillStyle = win.stroke;
        ctx.font = "11px Microsoft YaHei, Arial";
        ctx.fillText(win.label, x1 + 5, macdTop + 14);
        ctx.restore();
      }

      function roundRect(x, y, width, height, radius) {
        const r = Math.min(radius, width / 2, height / 2);
        ctx.beginPath();
        ctx.moveTo(x + r, y);
        ctx.lineTo(x + width - r, y);
        ctx.quadraticCurveTo(x + width, y, x + width, y + r);
        ctx.lineTo(x + width, y + height - r);
        ctx.quadraticCurveTo(x + width, y + height, x + width - r, y + height);
        ctx.lineTo(x + r, y + height);
        ctx.quadraticCurveTo(x, y + height, x, y + height - r);
        ctx.lineTo(x, y + r);
        ctx.quadraticCurveTo(x, y, x + r, y);
        ctx.closePath();
      }

      function drawSignalBadge(sig, xx, yy) {
        const buy = sig.label.includes("B");
        const selected = state.selectedSignalId === sig.id;
        const recent = recentSignalIds.has(sig.id);
        const watch = sig.status === "watch";
        const risk = sig.status === "risk";
        let alpha = selected ? 1 : watch ? 0.34 : risk ? 0.30 : recent ? 0.92 : 0.45;
        if (selectedSignal && !selected) alpha = auxiliarySignalIds.has(sig.id) ? 0.62 : 0.12;
        const pal = levelPalette[sig.level || data.period] || levelPalette["30m"];
        const main = buy ? pal.buyMain : pal.sellMain;
        const soft = buy ? pal.buySoft : pal.sellSoft;
        const levelText = (sig.level || data.period || "").toLowerCase();
        const badgeText = `${levelText}-${sig.label}${watch ? "*" : ""}`;
        const bw = Math.max(44, Math.min(94, 12 + badgeText.length * 7));
        const bh = 20;
        const gap = selected ? 12 : 9;
        const bx = xx - bw / 2;
        const by = buy ? yy + gap : yy - gap - bh;
        const badgeCenterX = bx + bw / 2;
        const badgeAnchorY = buy ? by : by + bh;

        ctx.save();
        ctx.globalAlpha = alpha;
        ctx.strokeStyle = `rgba(${main[0]},${main[1]},${main[2]},.92)`;
        ctx.fillStyle = `rgba(${soft[0]},${soft[1]},${soft[2]},.96)`;
        ctx.lineWidth = selected ? 2.2 : (watch || risk) ? 1 : 1.2;
        if (watch || risk) ctx.setLineDash([4, 3]);
        ctx.beginPath();
        ctx.moveTo(xx, yy);
        ctx.lineTo(badgeCenterX, badgeAnchorY);
        ctx.stroke();
        if (watch || risk) ctx.setLineDash([]);
        ctx.fillStyle = `rgba(${main[0]},${main[1]},${main[2]},.95)`;
        ctx.beginPath();
        ctx.arc(xx, yy, selected ? 5 : 3.8, 0, Math.PI * 2);
        ctx.fill();
        roundRect(bx, by, bw, bh, 5);
        ctx.fillStyle = `rgba(${soft[0]},${soft[1]},${soft[2]},.98)`;
        ctx.fill();
        ctx.strokeStyle = `rgba(${main[0]},${main[1]},${main[2]},${(watch || risk) ? .7 : .95})`;
        if (watch || risk) ctx.setLineDash([4, 3]);
        ctx.stroke();
        if (watch || risk) ctx.setLineDash([]);
        ctx.fillStyle = `rgba(${main[0]},${main[1]},${main[2]},1)`;
        ctx.font = selected ? "bold 12px Microsoft YaHei, Arial" : "bold 11px Microsoft YaHei, Arial";
        ctx.fillText(badgeText, bx + 6, by + 14);
        if (risk) {
          const textW = ctx.measureText(badgeText).width;
          const sy = by + 10;
          ctx.strokeStyle = `rgba(${main[0]},${main[1]},${main[2]},.95)`;
          ctx.lineWidth = selected ? 2 : 1.4;
          ctx.beginPath();
          ctx.moveTo(bx + 5, sy);
          ctx.lineTo(bx + 7 + textW, sy);
          ctx.stroke();
        }
        ctx.restore();
        state.signalHitboxes.push({ id: sig.id, x: bx + bw / 2, y: by + bh / 2, r: Math.max(16, bw / 2) });
      }

      for (const sig of visibleSignals) {
        const i = idxFromTime.get(sig.time);
        const xx = x(i), yy = y(sig.price);
        drawSignalBadge(sig, xx, yy);
      }
      ctx.lineWidth = 1;

      ctx.fillStyle = "#677282";
      const ticks = Math.min(8, e - s);
      for (let k = 0; k < ticks; k++) {
        const i = Math.floor(s + (e - s - 1) * k / Math.max(ticks - 1, 1));
        ctx.font = "13px Microsoft YaHei, Arial";
        ctx.fillText(data.bars[i].time.slice(5, 16), x(i) - 34, h - 14);
      }

      if (state.hover) {
        const inPlot = (
          state.hover.x >= left &&
          state.hover.x <= (w - right) &&
          state.hover.y >= top &&
          state.hover.y <= (macdTop + macdH)
        );
        if (!inPlot) return;
        const hoverX = state.hover.x;
        const hoverY = state.hover.y;
        const i = Math.max(s, Math.min(e - 1, Math.round(s + (hoverX - left) / plotW * (xEnd - s - 1))));
        const b = data.bars[i];
        const xx = hoverX;
        const yy = hoverY;
        ctx.strokeStyle = "rgba(32,36,42,.35)";
        ctx.beginPath(); ctx.moveTo(xx, top); ctx.lineTo(xx, macdTop + macdH); ctx.stroke();
        ctx.beginPath(); ctx.moveTo(left, yy); ctx.lineTo(w - right, yy); ctx.stroke();
        const higherMacd = higherMacdAtTime(b.time);
        const higherMacdText = higherMacd
          ? `  ${higherMacd.level} MACD:${Number(higherMacd.macd).toFixed(3)} DIF:${Number(higherMacd.dif).toFixed(3)}`
          : "";
        const box = `${b.time}  O:${b.open.toFixed(2)} H:${b.high.toFixed(2)} L:${b.low.toFixed(2)} C:${b.close.toFixed(2)}${higherMacdText}`;
        ctx.fillStyle = "rgba(255,255,255,.92)";
        ctx.font = "13px Microsoft YaHei, Arial";
        const hoverBoxW = Math.min(plotW - 16, Math.max(410, Math.ceil(ctx.measureText(box).width) + 18));
        ctx.fillRect(left + 8, top + 8, hoverBoxW, 24);
        ctx.strokeStyle = "#d9dee7"; ctx.strokeRect(left + 8, top + 8, hoverBoxW, 24);
        ctx.fillStyle = "#20242a"; ctx.fillText(box, left + 16, top + 25);

        // x-axis precise time tag under crosshair
        const timeText = b.time;
        ctx.font = "12px Microsoft YaHei, Arial";
        const tw = Math.ceil(ctx.measureText(timeText).width) + 14;
        const th = 20;
        let tx = xx - tw / 2;
        tx = Math.max(left, Math.min(w - right - tw, tx));
        const ty = h - th - 4;
        ctx.fillStyle = "rgba(255,255,255,.96)";
        ctx.fillRect(tx, ty, tw, th);
        ctx.strokeStyle = "#cfd6e2";
        ctx.strokeRect(tx, ty, tw, th);
        ctx.fillStyle = "#2e3a49";
        ctx.fillText(timeText, tx + 7, ty + 14);

        const clampedY = Math.max(top, Math.min(top + priceH, yy));
        const hoverPrice = maxP - ((clampedY - top) / priceH) * (maxP - minP);
        const priceText = Number(hoverPrice).toFixed(2);
        const pw = Math.ceil(ctx.measureText(priceText).width) + 14;
        const ph = 20;
        const px = Math.max(2, left - pw - 6);
        let py = yy - ph / 2;
        py = Math.max(top + 2, Math.min(macdTop - ph - 2, py));
        ctx.fillStyle = "rgba(255,255,255,.96)";
        ctx.fillRect(px, py, pw, ph);
        ctx.strokeStyle = "#cfd6e2";
        ctx.strokeRect(px, py, pw, ph);
        ctx.fillStyle = "#2e3a49";
        ctx.fillText(priceText, px + 7, py + 14);
      }
    }

    canvas.addEventListener("wheel", ev => {
      if (!state.data) return;
      ev.preventDefault();
      const n = state.data.bars.length;
      const rect = canvas.getBoundingClientRect();
      const mouse = (ev.clientX - rect.left) / rect.width;
      const span = state.viewEnd - state.viewStart;
      const nextSpan = Math.max(40, Math.min(n, span * (ev.deltaY > 0 ? 1.16 : 0.86)));
      const center = state.viewStart + span * mouse;
      state.viewStart = center - nextSpan * mouse;
      state.viewEnd = state.viewStart + nextSpan;
      clampView();
      draw();
    }, { passive: false });

    canvas.addEventListener("mousedown", ev => {
      state.dragging = true;
      state.dragX = ev.clientX;
      state.dragMoved = false;
    });
    canvas.addEventListener("dblclick", ev => {
      ev.preventDefault();
      resetView();
    });
    canvas.addEventListener("click", ev => {
      if (!state.data) return;
      const rect = canvas.getBoundingClientRect();
      const px = ev.clientX - rect.left;
      const py = ev.clientY - rect.top;
      if (state.dragMoved) {
        state.dragMoved = false;
        return;
      }
      const hit = state.signalHitboxes.find(h => Math.hypot(h.x - px, h.y - py) <= h.r);
      if (!hit) {
        state.selectedSignalId = null;
        renderSignalDetail(null);
        draw();
        return;
      }
      if (state.selectedSignalId === hit.id) {
        state.selectedSignalId = null;
        renderSignalDetail(null);
        draw();
        return;
      }
      state.selectedSignalId = hit.id;
      const sig = ((state.data.layers || []).flatMap(layer => [...(layer.signals || []), ...(layer.candidates || [])])).find(s => s.id === hit.id);
      renderSignalDetail(sig);
      draw();
    });
    window.addEventListener("mouseup", () => { state.dragging = false; });
    window.addEventListener("mousemove", ev => {
      const rect = canvas.getBoundingClientRect();
      if (state.dragging && state.data) {
        const span = state.viewEnd - state.viewStart;
        if (span >= state.data.bars.length - 0.001) {
          state.viewStart = 0;
          state.viewEnd = state.data.bars.length;
          state.dragX = ev.clientX;
          draw();
          return;
        }
        const dx = ev.clientX - state.dragX;
        if (Math.abs(dx) > 2) state.dragMoved = true;
        const shift = -dx / rect.width * span;
        state.viewStart = state.viewStart + shift;
        state.viewEnd = state.viewStart + span;
        clampView();
        state.dragX = ev.clientX;
        draw();
        return;
      }
      if (ev.clientX >= rect.left && ev.clientX <= rect.right && ev.clientY >= rect.top && ev.clientY <= rect.bottom) {
        state.hover = { x: ev.clientX - rect.left, y: ev.clientY - rect.top };
        draw();
      }
    });
    canvas.addEventListener("mouseleave", () => { state.hover = null; draw(); });

    if ($("fitBtn")) $("fitBtn").onclick = () => {
      if (!state.data) return;
      state.viewStart = 0;
      state.viewEnd = state.data.bars.length;
      draw();
    };
    if ($("lastBtn")) $("lastBtn").onclick = () => {
      if (!state.data) return;
      state.viewEnd = state.data.bars.length;
      state.viewStart = Math.max(0, state.viewEnd - 520);
      draw();
    };
    $("symbol").onchange = loadAnalysis;
    $("period").onchange = loadAnalysis;
    if ($("sensitivity")) $("sensitivity").onchange = loadAnalysis;
    if ($("theme5m")) {
      $("theme5m").onchange = () => {
        state.theme5m = $("theme5m").value || "soft";
        draw();
      };
    }
    $("startDate").onchange = () => {
      state.autoStartDate = !$("startDate").value;
      updateStartDateControl();
      loadAnalysis();
    };
    async function syncSymbol(code, buttonEl) {
      const target = (code || $("symbol").value || "").trim();
      if (!target) return;
      if (buttonEl) buttonEl.disabled = true;
      setError("");
      setStatus("在线同步中...");
      try {
        const ret = await api(`/api/fetch?symbol=${encodeURIComponent(target)}`);
        await loadStocks(ret.symbol);
        await loadAnalysis();
        $("fetchSymbol").value = "";
        setStatus(`同步完成：${ret.name && ret.name !== ret.symbol ? `${ret.name} ${ret.symbol}` : ret.symbol}`);
      } catch (err) {
        setError(err.message);
        setStatus("同步失败，仍可使用本地缓存");
      } finally {
        if (buttonEl) buttonEl.disabled = false;
      }
    }
    $("refreshBtn").onclick = () => syncSymbol($("symbol").value, $("refreshBtn"));
    $("fetchBtn").onclick = async () => {
      await syncSymbol($("fetchSymbol").value.trim() || $("symbol").value, $("fetchBtn"));
    };

    window.addEventListener("resize", resizeAndDraw);

    async function boot() {
      const sSel = $("sensitivity");
      if (sSel) {
        if (sSel.previousElementSibling) sSel.previousElementSibling.textContent = "底部灵敏度";
        sSel.innerHTML = `
          <option value="balanced" selected>平衡</option>
          <option value="aggressive">激进</option>
          <option value="conservative">保守</option>
        `;
      }
      const lvActions = $("levelLegendActions");
      if (lvActions && lvActions.previousElementSibling) lvActions.previousElementSibling.textContent = "级别过滤";
      try {
        await loadStocks();
        await loadAnalysis();
      } catch (err) {
        setError(err.message);
        setStatus("未能加载数据");
      }
    }
    boot();
  </script>
</body>
</html>
"""


def normalize_symbol(symbol_input: str) -> str:
    text = str(symbol_input).strip().lower()
    match = re.match(r"([a-z]{0,2})\s*(\d{6})$", text)
    if not match:
        raise ValueError("请输入 6 位代码，可带 sh/sz 前缀")
    prefix, code = match.groups()
    if not prefix:
        prefix = "sh" if code.startswith("6") or code in {"000001", "000016", "000300", "000905", "000852"} else "sz"
    if prefix not in {"sh", "sz"}:
        raise ValueError("前缀只能是 sh 或 sz")
    return f"{prefix}{code}"


def period_file(symbol: str, period: str) -> Path:
    name = "5Min" if period == "5m" else "30Min"
    return DATA_DIR / f"{symbol}_{name}_MaxAvailable.csv"


def stock_display_name(symbol: str, online: bool = True) -> str:
    symbol = normalize_symbol(symbol)
    if symbol in STOCK_NAME_CACHE:
        return STOCK_NAME_CACHE[symbol]
    if symbol in INDEX_NAMES:
        STOCK_NAME_CACHE[symbol] = INDEX_NAMES[symbol]
        return STOCK_NAME_CACHE[symbol]
    if not online:
        return ""
    try:
        url = f"https://hq.sinajs.cn/list={symbol}"
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn/",
            },
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            raw = resp.read().decode("gb18030", errors="replace")
        match = re.search(r'="([^,"]+)', raw)
        if match and match.group(1).strip():
            STOCK_NAME_CACHE[symbol] = match.group(1).strip()
            return STOCK_NAME_CACHE[symbol]
    except Exception:
        pass
    STOCK_NAME_CACHE[symbol] = symbol
    return symbol


def list_stocks() -> list[dict]:
    stocks: dict[str, set[str]] = {}
    if not DATA_DIR.exists():
        return []
    for path in DATA_DIR.glob("*_MaxAvailable.csv"):
        m = re.match(r"(.+?)_(5Min|30Min)_MaxAvailable\.csv$", path.name)
        if not m:
            continue
        symbol, period_name = m.groups()
        stocks.setdefault(symbol, set()).add("5m" if period_name == "5Min" else "30m")
    return [{"symbol": k, "name": stock_display_name(k, online=False), "periods": sorted(v)} for k, v in sorted(stocks.items())]


def sina_fetch(symbol: str, scale: int) -> pd.DataFrame:
    url = (
        "https://quotes.sina.cn/cn/api/json_v2.php/"
        f"CN_MarketDataService.getKLineData?symbol={symbol}&scale={scale}&ma=no&datalen=1970"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=18) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
    data = json.loads(raw)
    if not isinstance(data, list):
        raise ValueError("在线接口返回格式异常")
    df = pd.DataFrame(data)
    if df.empty:
        raise ValueError("在线接口没有返回分钟线")
    rename = {"day": "time"}
    df = df.rename(columns=rename)
    keep = ["time", "open", "high", "low", "close", "volume"]
    for col in keep:
        if col not in df.columns:
            df[col] = 0
    df = df[keep]
    df["amount"] = 0.0
    df["time"] = pd.to_datetime(df["time"])
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["time", "open", "high", "low", "close"]).sort_values("time")


def merge_cache(path: Path, new_df: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        old = pd.read_csv(path)
        if "day" in old.columns and "time" not in old.columns:
            old = old.rename(columns={"day": "time"})
        combined = pd.concat([old, new_df], ignore_index=True)
    else:
        combined = new_df
    combined["time"] = pd.to_datetime(combined["time"])
    combined = combined.sort_values("time").drop_duplicates("time", keep="last")
    combined.to_csv(path, index=False, encoding="utf-8-sig")


def fetch_and_cache(symbol_input: str) -> str:
    symbol = normalize_symbol(symbol_input)
    errors: list[str] = []
    for period, scale in [("5m", 5), ("30m", 30)]:
        try:
            df = sina_fetch(symbol, scale)
            merge_cache(period_file(symbol, period), df)
        except Exception as exc:
            errors.append(f"{period}: {exc}")
    if errors and not any(period_file(symbol, p).exists() for p in ["5m", "30m"]):
        raise RuntimeError("; ".join(errors))
    return symbol


def analyze_payload(symbol: str, period: str, start: str, sensitivity: str = "balanced") -> dict:
    symbol = normalize_symbol(symbol)
    sensitivity = (sensitivity or "balanced").strip().lower()
    if sensitivity not in SENSITIVITY_PROFILE:
        sensitivity = "balanced"
    if period not in {"5m", "30m"}:
        raise ValueError("period 只能是 5m 或 30m")
    path = period_file(symbol, period)
    if not path.exists():
        raise FileNotFoundError(f"未找到缓存数据：{path}")
    df = pd.read_csv(path)
    engine = "classic"
    def run_analysis(input_df: pd.DataFrame, level: str) -> dict:
        return analyze_frame_original(input_df, level)

    def to_daily_ohlc(input_df: pd.DataFrame) -> pd.DataFrame:
        dfx = input_df.copy()
        dfx["time"] = pd.to_datetime(dfx["time"])
        dfx = dfx.sort_values("time")
        dfx["trade_day"] = dfx["time"].dt.floor("D")
        return (
            dfx.groupby("trade_day", as_index=False)
            .agg(open=("open", "first"), high=("high", "max"), low=("low", "min"), close=("close", "last"))
            .rename(columns={"trade_day": "time"})
        )

    result = run_analysis(df, period)
    analysis_start = result["df"]["time"].iloc[0]
    analysis_end = result["df"]["time"].iloc[-1]
    bars = result["df"].copy()
    default_start_date = None
    if not start:
        trade_days = bars["time"].dt.floor("D").drop_duplicates().reset_index(drop=True)
        if not trade_days.empty:
            cutoff_day = trade_days.iloc[max(0, len(trade_days) - DEFAULT_TRADING_DAYS)]
            default_start_date = pd.Timestamp(cutoff_day).strftime("%Y-%m-%d")
            start = default_start_date
    bars["time"] = bars["time"].dt.strftime("%Y-%m-%d %H:%M")
    if start:
        cutoff = pd.Timestamp(start)
        mask = pd.to_datetime(bars["time"]) >= cutoff
        bars = bars.loc[mask].reset_index(drop=True)
    if bars.empty:
        raise ValueError("该起点之后没有可用数据")
    visible_times = set(bars["time"])
    source_index = {t: i for i, t in enumerate(result["df"]["time"].dt.strftime("%Y-%m-%d %H:%M"))}

    def fmt_time(ts: pd.Timestamp) -> str:
        return pd.Timestamp(ts).strftime("%Y-%m-%d %H:%M")

    def json_safe(value):
        if isinstance(value, pd.Timestamp):
            return fmt_time(value)
        if hasattr(value, "item"):
            return value.item()
        if isinstance(value, dict):
            return {k: json_safe(v) for k, v in value.items()}
        if isinstance(value, (list, tuple)):
            return [json_safe(v) for v in value]
        return value

    def sig_date(sig):
        return sig["date"] if isinstance(sig, dict) else sig.date

    def sig_value(sig):
        return sig["val"] if isinstance(sig, dict) else sig.value

    def sig_label(sig):
        return sig["label"] if isinstance(sig, dict) else sig.label

    def sig_basis(sig):
        if isinstance(sig, dict):
            basis_map = {
                "1B": "classic V10.20 first buy",
                "2B": "classic V10.20 second buy",
                "3B": "classic V10.20 third buy",
                "1S": "classic V10.20 first sell",
                "2S": "classic V10.20 second sell",
                "3S": "classic V10.20 third sell",
            }
            return basis_map.get(sig["label"], "classic V10.20 signal")
        return sig.basis

    def sig_confidence(sig):
        if not isinstance(sig, dict):
            return round(sig.confidence, 3)
        if sig["label"].startswith("3"):
            return 0.72
        if sig["label"].startswith("2"):
            return 0.62
        return 0.58

    def sig_related_zs(sig):
        if not isinstance(sig, dict):
            return sig.related_zs
        ev = sig.get("evidence", {})
        zs_ev = ev.get("zs")
        if zs_ev in result["zs"]:
            return result["zs"].index(zs_ev)
        return None

    def sig_evidence(sig):
        if not isinstance(sig, dict):
            return sig.evidence
        ev = dict(sig.get("evidence", {}))
        label = sig["label"]
        ev["signal_family"] = {
            "1B": "classic_first_buy",
            "2B": "classic_second_buy",
            "3B": "classic_third_buy",
            "1S": "classic_first_sell",
            "2S": "classic_second_sell",
            "3S": "classic_third_sell",
        }.get(label, "classic_signal")
        ev["rule"] = {
            "1B": "Original V10.20: new low after recent center with weaker downside MACD momentum.",
            "2B": "Original V10.20: pullback after 1B holds above the 1B low with weaker pullback momentum.",
            "3B": "Original V10.20: latest center upward break and pullback stays above ZG, with momentum check.",
            "1S": "Original V10.20: new high after recent center with weaker upside MACD momentum.",
            "2S": "Original V10.20: rebound after 1S stays below the 1S high with weaker rebound momentum.",
            "3S": "Original V10.20: latest center downward break and rebound stays below ZD, with momentum check.",
        }.get(label, "Original V10.20 signal.")
        try:
            if ev.get("macd_current_area") is not None and ev.get("macd_previous_area") is not None:
                cur = float(ev.get("macd_current_area"))
                prev = max(1e-6, float(ev.get("macd_previous_area")))
                macd_ratio = cur / prev
                ev["macd_ratio"] = round(macd_ratio, 4)
                dif_line = ""
                if ev.get("dif_current_peak") is not None and ev.get("dif_previous_peak") is not None:
                    dcur = float(ev.get("dif_current_peak"))
                    dprev = max(1e-6, float(ev.get("dif_previous_peak")))
                    ev["dif_ratio"] = round(dcur / dprev, 4)
                    dif_line = f"，DIF峰值比={ev['dif_ratio']:.3f}"
                if label == "1S":
                    dif_comment = ""
                    if ev.get("dif_ratio") is not None and ev["dif_ratio"] >= 1:
                        dif_comment = "（DIF未同步背驰，当前由MACD强背驰主导）"
                    ev["logic_text"] = (
                        f"同级上冲后再创新高，MACD上行动能比={ev['macd_ratio']:.3f}{dif_line}，"
                        f"动能弱于前一段，判定为1S候选。{dif_comment}"
                    )
                elif label == "1B":
                    dif_comment = ""
                    if ev.get("dif_ratio") is not None and ev["dif_ratio"] >= 1:
                        dif_comment = "（DIF未同步背驰，当前由MACD强背驰主导）"
                    ev["logic_text"] = (
                        f"同级下探后再创新低，MACD下行动能比={ev['macd_ratio']:.3f}{dif_line}，"
                        f"动能弱于前一段，判定为1B候选。{dif_comment}"
                    )
        except Exception:
            pass
        return ev

    def forward_stats(sig) -> dict:
        signal_time = fmt_time(sig_date(sig))
        idx = source_index.get(signal_time)
        if idx is None:
            return {}
        out = {}
        full = result["df"]
        is_buy = "B" in sig_label(sig)
        value = sig_value(sig)
        for n in [5, 10, 20]:
            future = full.iloc[idx + 1 : idx + 1 + n]
            if future.empty:
                out[f"n{n}"] = None
                continue
            if is_buy:
                favorable = (float(future["high"].max()) - value) / value * 100
                adverse = (float(future["low"].min()) - value) / value * 100
            else:
                favorable = (value - float(future["low"].min())) / value * 100
                adverse = (value - float(future["high"].max())) / value * 100
            out[f"n{n}"] = {
                "favorable_pct": round(favorable, 3),
                "adverse_pct": round(adverse, 3),
                "end_time": fmt_time(full.iloc[min(idx + n, len(full) - 1)]["time"]),
            }
        return out

    full_df = result["df"].copy()
    full_df["time_str"] = full_df["time"].dt.strftime("%Y-%m-%d %H:%M")

    def zs_start(z):
        return z.start if hasattr(z, "start") else z["start"]

    def zs_end(z):
        return z.end if hasattr(z, "end") else z["end"]

    def zs_zd(z):
        return z.zd if hasattr(z, "zd") else z["ZD"]

    def zs_zg(z):
        return z.zg if hasattr(z, "zg") else z["ZG"]

    def zs_count(z):
        return z.bi_count if hasattr(z, "bi_count") else None

    def prune_invalid_signals(signals_raw: list[dict], layer_full_df: pd.DataFrame) -> list[dict]:
        sigs = sorted(signals_raw, key=lambda x: x["time"])
        keep = [True] * len(sigs)
        idx_by_time = {
            row.time_str: i
            for i, row in enumerate(
                layer_full_df.assign(time_str=layer_full_df["time"].dt.strftime("%Y-%m-%d %H:%M")).itertuples(index=False)
            )
        }
        first_buy_valid_time = set()
        first_sell_valid_time = set()
        for i, s in enumerate(sigs):
            label = s["label"]
            s_idx = idx_by_time.get(s["time"])
            if s_idx is None:
                continue
            if label == "1B":
                next_1s_idx = None
                for j in range(i + 1, len(sigs)):
                    if sigs[j]["label"] == "1S":
                        next_1s_idx = idx_by_time.get(sigs[j]["time"])
                        break
                own_2b_idx = None
                for j in range(i + 1, len(sigs)):
                    if sigs[j]["label"] == "2B" and sigs[j].get("evidence", {}).get("first_signal_time") == s["time"]:
                        own_2b_idx = idx_by_time.get(sigs[j]["time"])
                        break
                candidates = [x for x in [next_1s_idx, own_2b_idx] if x is not None]
                end_idx = (min(candidates) if candidates else len(layer_full_df) - 1)
                if end_idx > s_idx:
                    if float(layer_full_df.iloc[s_idx + 1 : end_idx + 1]["low"].min()) < float(s["price"]):
                        keep[i] = False
                    else:
                        first_buy_valid_time.add(s["time"])
            elif label == "1S":
                next_1b_idx = None
                for j in range(i + 1, len(sigs)):
                    if sigs[j]["label"] == "1B":
                        next_1b_idx = idx_by_time.get(sigs[j]["time"])
                        break
                own_2s_idx = None
                for j in range(i + 1, len(sigs)):
                    if sigs[j]["label"] == "2S" and sigs[j].get("evidence", {}).get("first_signal_time") == s["time"]:
                        own_2s_idx = idx_by_time.get(sigs[j]["time"])
                        break
                candidates = [x for x in [next_1b_idx, own_2s_idx] if x is not None]
                end_idx = (min(candidates) if candidates else len(layer_full_df) - 1)
                if end_idx > s_idx:
                    if float(layer_full_df.iloc[s_idx + 1 : end_idx + 1]["high"].max()) > float(s["price"]):
                        keep[i] = False
                    else:
                        first_sell_valid_time.add(s["time"])
            elif label == "2B":
                ref = s.get("evidence", {}).get("first_signal_time")
                if ref and ref not in first_buy_valid_time:
                    keep[i] = False
            elif label == "2S":
                ref = s.get("evidence", {}).get("first_signal_time")
                if ref and ref not in first_sell_valid_time:
                    keep[i] = False

        # Pass-2: sequence governance
        # 1) Same-level first signals should alternate (no repeated 1B before a valid 1S, and vice versa)
        # 2) Once 1B->2B chain is formed, suppress extra 1B until an opposite 1S appears (small-to-big confirmation priority)
        # 3) Symmetric rule for 1S->2S chain.
        accepted: list[dict] = []
        first_state: str | None = None
        seen_2b_for_first: set[str] = set()
        seen_2s_for_first: set[str] = set()
        last_buy_cycle_zs_end: pd.Timestamp | None = None
        last_sell_cycle_zs_end: pd.Timestamp | None = None

        def sig_zs_start(sigx: dict) -> pd.Timestamp | None:
            try:
                zs = sigx.get("evidence", {}).get("zs")
                if isinstance(zs, dict) and zs.get("start"):
                    return pd.Timestamp(zs.get("start"))
            except Exception:
                return None
            return None

        def sig_zs_end(sigx: dict) -> pd.Timestamp | None:
            try:
                zs = sigx.get("evidence", {}).get("zs")
                if isinstance(zs, dict) and zs.get("end"):
                    return pd.Timestamp(zs.get("end"))
            except Exception:
                return None
            return None

        for i, s in enumerate(sigs):
            if not keep[i]:
                continue
            label = s["label"]
            t = s["time"]
            ref = s.get("evidence", {}).get("first_signal_time")

            if label == "1B":
                if first_state == "1S_DONE":
                    # after a completed sell cycle, require a fresh structural switch
                    cur_zs_start = sig_zs_start(s)
                    if last_sell_cycle_zs_end is not None and cur_zs_start is not None and cur_zs_start <= last_sell_cycle_zs_end:
                        continue
                    accepted.append(s)
                    first_state = "1B"
                    continue
                if first_state == "1B":
                    continue
                accepted.append(s)
                first_state = "1B"
                continue

            if label == "1S":
                if first_state == "1B_DONE":
                    # after a completed buy cycle, require a fresh structural switch
                    cur_zs_start = sig_zs_start(s)
                    if last_buy_cycle_zs_end is not None and cur_zs_start is not None and cur_zs_start <= last_buy_cycle_zs_end:
                        continue
                    accepted.append(s)
                    first_state = "1S"
                    continue
                if first_state == "1S":
                    continue
                accepted.append(s)
                first_state = "1S"
                continue

            if label == "2B":
                if not ref:
                    continue
                # only after its 1B and before opposite 1S appears
                ref_exists = any(x["label"] == "1B" and x["time"] == ref for x in accepted)
                if not ref_exists:
                    continue
                if ref in seen_2b_for_first:
                    continue
                opposite_after_ref = any(x["label"] == "1S" and x["time"] > ref for x in accepted)
                if opposite_after_ref:
                    continue
                accepted.append(s)
                seen_2b_for_first.add(ref)
                ref_sig = next((x for x in accepted if x["label"] == "1B" and x["time"] == ref), None)
                last_buy_cycle_zs_end = sig_zs_end(ref_sig) if ref_sig else last_buy_cycle_zs_end
                # buy cycle completed; require opposite first signal to unlock next buy cycle
                first_state = "1B_DONE"
                continue

            if label == "2S":
                if not ref:
                    continue
                ref_exists = any(x["label"] == "1S" and x["time"] == ref for x in accepted)
                if not ref_exists:
                    continue
                if ref in seen_2s_for_first:
                    continue
                opposite_after_ref = any(x["label"] == "1B" and x["time"] > ref for x in accepted)
                if opposite_after_ref:
                    continue
                accepted.append(s)
                seen_2s_for_first.add(ref)
                ref_sig = next((x for x in accepted if x["label"] == "1S" and x["time"] == ref), None)
                last_sell_cycle_zs_end = sig_zs_end(ref_sig) if ref_sig else last_sell_cycle_zs_end
                # sell cycle completed; require opposite first signal to unlock next sell cycle
                first_state = "1S_DONE"
                continue

            accepted.append(s)

        return accepted

    def local_divergence_candidates(layer_result: dict, layer_period: str, signal_prefix: str, visible_times: set[str]) -> list[dict]:
        """Local 1B/1S watches from adjacent same-direction legs.

        These are not classic confirmed BS points. They mark a lower-level
        down-up-down / up-down-up divergence that can seed a small-to-big
        confirmation on the decision level.
        """
        fr = sorted(layer_result.get("fractals", []), key=lambda x: x["date"])
        df_full = layer_result["df"]
        out: list[dict] = []
        for i in range(3, len(fr)):
            curr = fr[i]
            mid = fr[i - 1]
            prev_same = fr[i - 2]
            leg_a_start = fr[i - 3]
            if curr["type"] == "Bottom" and prev_same["type"] == "Bottom" and mid["type"] == "Top" and leg_a_start["type"] == "Top":
                if float(curr["val"]) >= float(prev_same["val"]):
                    continue
                mom_a = macd_momentum(df_full, pd.Timestamp(leg_a_start["date"]), pd.Timestamp(prev_same["date"]), -1)
                mom_b = macd_momentum(df_full, pd.Timestamp(mid["date"]), pd.Timestamp(curr["date"]), -1)
                dif_a = dif_peak(df_full, pd.Timestamp(leg_a_start["date"]), pd.Timestamp(prev_same["date"]), -1)
                dif_b = dif_peak(df_full, pd.Timestamp(mid["date"]), pd.Timestamp(curr["date"]), -1)
                area_ok = mom_b < mom_a * 0.82
                dif_ok = dif_b < dif_a * 0.98
                if not (area_ok or dif_ok):
                    continue
                t = fmt_time(curr["date"])
                if t not in visible_times:
                    continue
                out.append(
                    {
                        "id": f"{signal_prefix}-watch-1b-{len(out)}",
                        "time": t,
                        "price": float(curr["val"]),
                        "label": "1B",
                        "confidence": 0.50 if (area_ok and dif_ok) else 0.44,
                        "basis": "local down-up-down divergence watch; needs higher-level non-break and breakout to confirm",
                        "related_zs": None,
                        "evidence": {
                            "source": "local_divergence_watch",
                            "watch_state": "watch",
                            "logic_text": "Local lower-level divergence only: price made a lower low while MACD area or DIF peak weakened. It is not a confirmed first buy until the decision level confirms a small-to-big turn.",
                            "prev_leg_start": fmt_time(leg_a_start["date"]),
                            "prev_same_time": fmt_time(prev_same["date"]),
                            "middle_time": fmt_time(mid["date"]),
                            "current_time": t,
                            "macd_previous_area": mom_a,
                            "macd_current_area": mom_b,
                            "dif_previous_peak": dif_a,
                            "dif_current_peak": dif_b,
                            "area_ok": area_ok,
                            "dif_ok": dif_ok,
                        },
                        "forward": {},
                        "level": layer_period,
                        "status": "watch",
                    }
                )
            elif curr["type"] == "Top" and prev_same["type"] == "Top" and mid["type"] == "Bottom" and leg_a_start["type"] == "Bottom":
                if float(curr["val"]) <= float(prev_same["val"]):
                    continue
                mom_a = macd_momentum(df_full, pd.Timestamp(leg_a_start["date"]), pd.Timestamp(prev_same["date"]), 1)
                mom_b = macd_momentum(df_full, pd.Timestamp(mid["date"]), pd.Timestamp(curr["date"]), 1)
                dif_a = dif_peak(df_full, pd.Timestamp(leg_a_start["date"]), pd.Timestamp(prev_same["date"]), 1)
                dif_b = dif_peak(df_full, pd.Timestamp(mid["date"]), pd.Timestamp(curr["date"]), 1)
                area_ok = mom_b < mom_a * 0.82
                dif_ok = dif_b < dif_a * 0.98
                if not (area_ok or dif_ok):
                    continue
                t = fmt_time(curr["date"])
                if t not in visible_times:
                    continue
                out.append(
                    {
                        "id": f"{signal_prefix}-watch-1s-{len(out)}",
                        "time": t,
                        "price": float(curr["val"]),
                        "label": "1S",
                        "confidence": 0.50 if (area_ok and dif_ok) else 0.44,
                        "basis": "local up-down-up divergence watch; needs higher-level non-break and breakdown to confirm",
                        "related_zs": None,
                        "evidence": {
                            "source": "local_divergence_watch",
                            "watch_state": "watch",
                            "logic_text": "Local lower-level divergence only: price made a higher high while MACD area or DIF peak weakened. It is not a confirmed first sell until the decision level confirms a small-to-big turn.",
                            "prev_leg_start": fmt_time(leg_a_start["date"]),
                            "prev_same_time": fmt_time(prev_same["date"]),
                            "middle_time": fmt_time(mid["date"]),
                            "current_time": t,
                            "macd_previous_area": mom_a,
                            "macd_current_area": mom_b,
                            "dif_previous_peak": dif_a,
                            "dif_current_peak": dif_b,
                            "area_ok": area_ok,
                            "dif_ok": dif_ok,
                        },
                        "forward": {},
                        "level": layer_period,
                        "status": "watch",
                    }
                )
        return out

    def build_layer(layer_result: dict, layer_period: str, signal_prefix: str, with_forward: bool) -> dict:
        layer_full_df = layer_result["df"].copy()
        layer_full_df["time"] = pd.to_datetime(layer_full_df["time"])
        layer_df = layer_full_df.copy()
        if start:
            cutoff = pd.Timestamp(start)
            layer_df = layer_df.loc[layer_df["time"] >= cutoff].reset_index(drop=True)
        if layer_df.empty:
            return {"level": layer_period, "bi_points": [], "zs": [], "signals": [], "candidates": [], "macd": []}
        layer_start = layer_df["time"].min()
        layer_end = layer_df["time"].max()
        layer_visible_times = set(layer_df["time"].dt.strftime("%Y-%m-%d %H:%M"))
        layer_full_times = layer_full_df["time"].dt.strftime("%Y-%m-%d %H:%M").tolist()
        layer_full_idx_by_time = {t: i for i, t in enumerate(layer_full_times)}
        invalidation_df = result["df"]
        invalidation_times = invalidation_df["time"].dt.strftime("%Y-%m-%d %H:%M").tolist()
        invalidation_idx_by_time = {t: i for i, t in enumerate(invalidation_times)}

        def confirmed_invalidated_at(sig: dict) -> str | None:
            label = str(sig.get("label", ""))
            if label not in {"1B", "1S", "2B", "2S", "3B", "3S"}:
                return None
            ev = sig.get("evidence", {}) or {}
            self_ev = (ev.get("evidence_layers") or {}).get("self_level") or {}
            guard_value = self_ev.get("guard_value")
            if guard_value is None and label in {"1B", "1S"}:
                guard_value = sig.get("price")
            if guard_value is None and label in {"2B", "2S"}:
                guard_value = ev.get("first_signal_value")
            if guard_value is None and label in {"3B", "3S"}:
                guard_value = ev.get("boundary")
            if guard_value is None:
                return None
            idx = invalidation_idx_by_time.get(sig.get("time"))
            check_df = invalidation_df
            if idx is None:
                idx = layer_full_idx_by_time.get(sig.get("time"))
                check_df = layer_full_df
            if idx is None or idx + 1 >= len(check_df):
                return None
            future = check_df.iloc[idx + 1 :]
            if "B" in label:
                broken = future.loc[future["low"].astype(float) < float(guard_value)]
            else:
                broken = future.loc[future["high"].astype(float) > float(guard_value)]
            if broken.empty:
                return None
            return fmt_time(broken.iloc[0]["time"])

        def lifecycle_for_confirmed(sig: dict) -> dict:
            ev = sig.get("evidence", {}) or {}
            invalidated_at = confirmed_invalidated_at(sig)
            state = "invalidated" if invalidated_at else ("risk" if sig.get("status") == "risk" else "confirmed")
            candidate_at = ev.get("candidate_5m_time") or ev.get("first_signal_time")
            return {
                "state": state,
                "candidate_at": candidate_at,
                "confirmed_at": sig.get("time"),
                "invalidated_at": invalidated_at,
                "expired_at": None,
                "note": "已确认信号跌破/突破保护线后隐藏。" if invalidated_at else "已确认信号保留当时证据；后续K线不会重写原信号。",
            }

        def lifecycle_for_candidate(sig: dict) -> dict:
            idx = layer_full_idx_by_time.get(sig.get("time"))
            expires_at = None
            invalidated_at = None
            if idx is not None:
                exp_idx = min(len(layer_full_df) - 1, idx + WATCH_KEEP_BARS_5M - 1)
                expires_at = fmt_time(layer_full_df.iloc[exp_idx]["time"])
                future = layer_full_df.iloc[idx + 1 : exp_idx + 1]
                if "B" in sig.get("label", ""):
                    broken = future.loc[future["low"].astype(float) < float(sig["price"])]
                else:
                    broken = future.loc[future["high"].astype(float) > float(sig["price"])]
                if not broken.empty:
                    invalidated_at = fmt_time(broken.iloc[0]["time"])
            now_time = layer_full_times[-1] if layer_full_times else None
            if invalidated_at:
                state = "invalidated"
            elif expires_at and now_time and now_time > expires_at:
                state = "expired"
            else:
                state = "watch"
            return {
                "state": state,
                "candidate_at": sig.get("time"),
                "confirmed_at": None,
                "invalidated_at": invalidated_at,
                "expired_at": expires_at if state == "expired" else None,
                "watch_until": expires_at,
                "note": "候选信号按时间向前演化：观察、确认、失效或过期。",
            }

        def layer_sig_related_zs(sig):
            if not isinstance(sig, dict):
                return sig.related_zs
            ev = sig.get("evidence", {})
            zs_ev = ev.get("zs")
            if zs_ev in layer_result["zs"]:
                return layer_result["zs"].index(zs_ev)
            return None

        signals_local = []
        for sig_idx, sig in enumerate(layer_result["signals"]):
            if "?" in sig_label(sig):
                continue
            sig_time = fmt_time(sig_date(sig))
            if sig_time not in layer_visible_times:
                continue
            signals_local.append(
                {
                    "id": f"{signal_prefix}-{sig_idx}",
                    "time": sig_time,
                    "price": sig_value(sig),
                    "label": sig_label(sig),
                    "confidence": sig_confidence(sig),
                    "basis": sig_basis(sig),
                    "related_zs": layer_sig_related_zs(sig),
                    "evidence": json_safe(sig_evidence(sig)),
                    "forward": forward_stats(sig) if with_forward else {},
                    "level": layer_period,
                }
            )

        def structural_third_signals() -> list[dict]:
            out: list[dict] = []
            fractals = sorted(layer_result.get("fractals", []), key=lambda f: pd.Timestamp(f["date"]))
            centers = sorted(layer_result.get("zs", []), key=lambda z: pd.Timestamp(zs_end(z)))
            if not fractals or not centers:
                return out
            hold_ratio = SENSITIVITY_PROFILE[sensitivity]["hold_ratio"]
            break_ratio = SENSITIVITY_PROFILE[sensitivity]["break_ratio"]
            existing = {(s["time"], s["label"]) for s in signals_local}

            for z in centers:
                z_end = pd.Timestamp(zs_end(z))
                zg = float(zs_zg(z))
                zd = float(zs_zd(z))
                post = [f for f in fractals if pd.Timestamp(f["date"]) > z_end]
                if len(post) < 3:
                    continue

                leave_top = next((f for f in post if f["type"] == "Top" and float(f["val"]) > zg * break_ratio), None)
                if leave_top:
                    after_leave = [f for f in post if pd.Timestamp(f["date"]) > pd.Timestamp(leave_top["date"])]
                    pullback = None
                    confirm = None
                    for f in after_leave:
                        if f["type"] == "Bottom":
                            if float(f["val"]) <= zg * hold_ratio:
                                break
                            if pullback is None or float(f["val"]) < float(pullback["val"]):
                                pullback = f
                        elif f["type"] == "Top" and pullback is not None and float(f["val"]) > float(leave_top["val"]) * break_ratio:
                            confirm = f
                            break
                    if pullback and confirm:
                        t = fmt_time(pd.Timestamp(pullback["date"]))
                        if t in layer_visible_times and (t, "3B") not in existing:
                            mom_pullback = macd_momentum(layer_full_df, pd.Timestamp(leave_top["date"]), pd.Timestamp(pullback["date"]), -1)
                            mom_base_down = macd_momentum(layer_full_df, pd.Timestamp(zs_start(z)), pd.Timestamp(zs_end(z)), -1)
                            out.append({
                                "id": f"{signal_prefix}-struct-3b-{t}",
                                "time": t,
                                "price": float(pullback["val"]),
                                "label": "3B",
                                "confidence": 0.68,
                                "basis": "本级别中枢上破后回踩不回中枢，并再次上破确认的3B",
                                "related_zs": None,
                                "evidence": {
                                    "source": "structural_center_non_return",
                                    "zs": json_safe(z),
                                    "boundary_name": "ZG",
                                    "boundary": zg,
                                    "leave_time": fmt_time(pd.Timestamp(leave_top["date"])),
                                    "confirm_time": fmt_time(pd.Timestamp(confirm["date"])),
                                    "macd_test_area": mom_pullback,
                                    "macd_base_area": mom_base_down,
                                    "rule": "中枢上破 -> 回踩低点仍高于ZG -> 后续再上破离开高点，确认本级别3B",
                                },
                                "forward": forward_stats({"date": pd.Timestamp(pullback["date"]), "val": float(pullback["val"]), "label": "3B"}) if with_forward else {},
                                "level": layer_period,
                            })
                            existing.add((t, "3B"))

                leave_bottom = next((f for f in post if f["type"] == "Bottom" and float(f["val"]) < zd / break_ratio), None)
                if leave_bottom:
                    after_leave = [f for f in post if pd.Timestamp(f["date"]) > pd.Timestamp(leave_bottom["date"])]
                    rebound = None
                    confirm = None
                    for f in after_leave:
                        if f["type"] == "Top":
                            if float(f["val"]) >= zd / hold_ratio:
                                break
                            if rebound is None or float(f["val"]) > float(rebound["val"]):
                                rebound = f
                        elif f["type"] == "Bottom" and rebound is not None and float(f["val"]) < float(leave_bottom["val"]) / break_ratio:
                            confirm = f
                            break
                    if rebound and confirm:
                        t = fmt_time(pd.Timestamp(rebound["date"]))
                        if t in layer_visible_times and (t, "3S") not in existing:
                            mom_rebound = macd_momentum(layer_full_df, pd.Timestamp(leave_bottom["date"]), pd.Timestamp(rebound["date"]), 1)
                            mom_base_up = macd_momentum(layer_full_df, pd.Timestamp(zs_start(z)), pd.Timestamp(zs_end(z)), 1)
                            out.append({
                                "id": f"{signal_prefix}-struct-3s-{t}",
                                "time": t,
                                "price": float(rebound["val"]),
                                "label": "3S",
                                "confidence": 0.68,
                                "basis": "本级别中枢下破后反抽不回中枢，并再次下破确认的3S",
                                "related_zs": None,
                                "evidence": {
                                    "source": "structural_center_non_return",
                                    "zs": json_safe(z),
                                    "boundary_name": "ZD",
                                    "boundary": zd,
                                    "leave_time": fmt_time(pd.Timestamp(leave_bottom["date"])),
                                    "confirm_time": fmt_time(pd.Timestamp(confirm["date"])),
                                    "macd_test_area": mom_rebound,
                                    "macd_base_area": mom_base_up,
                                    "rule": "中枢下破 -> 反抽高点仍低于ZD -> 后续再下破离开低点，确认本级别3S",
                                },
                                "forward": forward_stats({"date": pd.Timestamp(rebound["date"]), "val": float(rebound["val"]), "label": "3S"}) if with_forward else {},
                                "level": layer_period,
                            })
                            existing.add((t, "3S"))
            return out

        signals_local.extend(structural_third_signals())
        signals_local = prune_invalid_signals(signals_local, layer_result["df"])
        active_signals = []
        for s in signals_local:
            s["lifecycle"] = lifecycle_for_confirmed(s)
            ev = s.setdefault("evidence", {})
            ev["lifecycle"] = s["lifecycle"]
            if s["lifecycle"].get("state") != "invalidated":
                active_signals.append(s)
        signals_local = active_signals
        candidates_local = (
            local_divergence_candidates(layer_result, layer_period, signal_prefix, layer_visible_times)
            if layer_period == "5m"
            else []
        )
        confirmed_keys = {(s["time"], s["label"]) for s in signals_local}
        candidates_local = [c for c in candidates_local if (c["time"], c["label"]) not in confirmed_keys]
        for c in candidates_local:
            c["lifecycle"] = lifecycle_for_candidate(c)
            ev = c.setdefault("evidence", {})
            ev["lifecycle"] = c["lifecycle"]
            ev["watch_state"] = c["lifecycle"]["state"]
            c["status"] = c["lifecycle"]["state"]
        candidates_local = [c for c in candidates_local if c.get("lifecycle", {}).get("state") == "watch"]
        if layer_period == "5m" and candidates_local:
            idx_by_time = {fmt_time(ts): i for i, ts in enumerate(layer_df["time"])}
            last_idx = len(layer_df) - 1
            keep_from = max(0, last_idx - WATCH_KEEP_BARS_5M + 1)
            candidates_local = [
                c for c in candidates_local
                if idx_by_time.get(c["time"], -1) >= keep_from
            ]

        layer_all_zs = [
            {
                "start": fmt_time(zs_start(z)),
                "end": fmt_time(zs_end(z)),
                "ZD": zs_zd(z),
                "ZG": zs_zg(z),
                "bi_count": zs_count(z),
            }
            for z in layer_result["zs"]
        ]
        layer_zs = [
            z
            for z in layer_all_zs
            if pd.Timestamp(zs_end(z)) >= layer_start and pd.Timestamp(zs_start(z)) <= layer_end
        ]

        layer_bi_points = []
        layer_all_bi_points = []
        if "bis" in layer_result:
            for bi in layer_result["bis"]:
                for frac in [bi.start, bi.end]:
                    t = fmt_time(frac.date)
                    layer_all_bi_points.append({"time": t, "value": frac.value})
                    if t in layer_visible_times:
                        layer_bi_points.append({"time": t, "value": frac.value})
        else:
            for point in layer_result.get("bi_points", []):
                t = fmt_time(point["time"])
                layer_all_bi_points.append({"time": t, "value": point["value"]})
                if t in layer_visible_times:
                    layer_bi_points.append({"time": t, "value": point["value"]})
        layer_macd = []
        for row in layer_df.itertuples(index=False):
            layer_macd.append({
                "time": fmt_time(getattr(row, "time")),
                "macd": float(getattr(row, "macd", 0) or 0),
                "dif": float(getattr(row, "dif", 0) or 0),
                "dea": float(getattr(row, "dea", 0) or 0),
            })

        def segment_metrics(start_time: str, end_time: str, direction: str) -> dict:
            st = pd.Timestamp(start_time)
            et = pd.Timestamp(end_time)
            if et < st:
                st, et = et, st
            seg = layer_full_df.loc[(layer_full_df["time"] >= st) & (layer_full_df["time"] <= et)]
            if seg.empty:
                return {"macd_area": None, "dif_extreme": None, "bar_count": 0}
            macd = seg["macd"].astype(float)
            dif = seg["dif"].astype(float)
            if direction == "up":
                area = float(macd[macd > 0].sum())
                dif_extreme = float(dif.max())
            else:
                area = float(abs(macd[macd < 0].sum()))
                dif_extreme = float(dif.min())
            return {
                "macd_area": round(area, 4),
                "dif_extreme": round(dif_extreme, 4),
                "bar_count": int(len(seg)),
            }

        def build_self_level_evidence(sig: dict) -> dict:
            label = sig.get("label")
            if label not in {"1B", "1S", "2B", "2S", "3B", "3S"}:
                return {}
            ev = sig.get("evidence", {}) or {}
            pts_by_key = {}
            for p in layer_all_bi_points:
                pts_by_key[(p["time"], round(float(p["value"]), 6))] = {
                    "time": p["time"],
                    "value": float(p["value"]),
                    "ts": pd.Timestamp(p["time"]),
                }
            pts = sorted(pts_by_key.values(), key=lambda p: p["ts"])
            if len(pts) < 3:
                return {}
            pts_by_time = {p["time"]: p for p in pts}

            def point_for(time_str: str, fallback_value=None) -> dict | None:
                if not time_str:
                    return None
                if time_str in pts_by_time:
                    return pts_by_time[time_str]
                try:
                    ts = pd.Timestamp(time_str)
                except Exception:
                    return None
                value = float(fallback_value) if fallback_value is not None else None
                if value is None:
                    row = layer_full_df.loc[layer_full_df["time"] == ts]
                    if not row.empty:
                        value = float(row.iloc[0]["close"])
                if value is None:
                    return None
                return {"time": fmt_time(ts), "value": value, "ts": ts}

            def extreme_point(start_time: str, end_time: str, direction: str) -> dict | None:
                try:
                    st = pd.Timestamp(start_time)
                    et = pd.Timestamp(end_time)
                except Exception:
                    return None
                if et < st:
                    st, et = et, st
                candidates = [p for p in pts if st <= p["ts"] <= et]
                if not candidates:
                    return None
                return max(candidates, key=lambda p: p["value"]) if direction == "up" else min(candidates, key=lambda p: p["value"])

            def make_segment(name: str, start: dict, end: dict, direction: str) -> dict:
                metrics = segment_metrics(start["time"], end["time"], direction)
                return {
                    "name": name,
                    "start": start["time"],
                    "end": end["time"],
                    "direction": direction,
                    "start_value": round(float(start["value"]), 4),
                    "end_value": round(float(end["value"]), 4),
                    **metrics,
                }

            def ratio_of(current, base):
                if current in (None, 0) or base in (None, 0):
                    return None
                return round(float(current) / max(1e-6, float(base)), 4)

            if label in {"2B", "2S"}:
                first = point_for(ev.get("first_signal_time"), ev.get("first_signal_value"))
                current = point_for(sig["time"], sig.get("price"))
                if not first or not current:
                    return {}
                if label == "2B":
                    pivot = extreme_point(first["time"], current["time"], "up")
                    if not pivot:
                        return {}
                    build = make_segment("build", first, pivot, "up")
                    pullback = make_segment("pullback", pivot, current, "down")
                    macd_ratio = ratio_of(pullback.get("macd_area"), build.get("macd_area"))
                    return {
                        "level": layer_period,
                        "signal_type": label,
                        "compare_type": "second_buy_pullback",
                        "divergence_class": "pullback_confirmation",
                        "trend_ok": None,
                        "trend_basis": "second buy checks the first pullback after 1B; focus is not breaking the 1B low and weaker pullback momentum",
                        "guard_name": "1B low",
                        "guard_value": round(float(ev.get("first_signal_value", first["value"])), 4),
                        "segments": [build, pullback],
                        "macd_ratio": macd_ratio,
                    }
                pivot = extreme_point(first["time"], current["time"], "down")
                if not pivot:
                    return {}
                crash = make_segment("crash", first, pivot, "down")
                rebound = make_segment("rebound", pivot, current, "up")
                macd_ratio = ratio_of(rebound.get("macd_area"), crash.get("macd_area"))
                return {
                    "level": layer_period,
                    "signal_type": label,
                    "compare_type": "second_sell_rebound",
                    "divergence_class": "rebound_confirmation",
                    "trend_ok": None,
                    "trend_basis": "second sell checks the first rebound after 1S; focus is not breaking the 1S high and weaker rebound momentum",
                    "guard_name": "1S high",
                    "guard_value": round(float(ev.get("first_signal_value", first["value"])), 4),
                    "segments": [crash, rebound],
                    "macd_ratio": macd_ratio,
                }

            if label in {"3B", "3S"}:
                zs = ev.get("zs")
                if not isinstance(zs, dict) or not zs.get("end") or not ev.get("leave_time"):
                    return {}
                current = point_for(sig["time"], sig.get("price"))
                leave = point_for(ev.get("leave_time"))
                if not current or not leave:
                    return {}
                if label == "3B":
                    center_end = point_for(zs["end"], zs.get("ZG"))
                    leave_seg = make_segment("leave", center_end, leave, "up") if center_end else None
                    pullback = make_segment("pullback", leave, current, "down")
                    segments = [seg for seg in [leave_seg, pullback] if seg]
                    macd_ratio = ratio_of(pullback.get("macd_area"), leave_seg.get("macd_area") if leave_seg else ev.get("macd_base_area"))
                    return {
                        "level": layer_period,
                        "signal_type": label,
                        "compare_type": "third_buy_pullback",
                        "divergence_class": "center_non_return",
                        "trend_ok": None,
                        "trend_basis": "third buy checks pullback after leaving the center; focus is staying above ZG",
                        "guard_name": "ZG",
                        "guard_value": round(float(ev.get("boundary", zs.get("ZG"))), 4),
                        "zs": zs,
                        "segments": segments,
                        "macd_ratio": macd_ratio,
                    }
                center_end = point_for(zs["end"], zs.get("ZD"))
                leave_seg = make_segment("leave", center_end, leave, "down") if center_end else None
                rebound = make_segment("rebound", leave, current, "up")
                segments = [seg for seg in [leave_seg, rebound] if seg]
                macd_ratio = ratio_of(rebound.get("macd_area"), leave_seg.get("macd_area") if leave_seg else ev.get("macd_base_area"))
                return {
                    "level": layer_period,
                    "signal_type": label,
                    "compare_type": "third_sell_rebound",
                    "divergence_class": "center_non_return",
                    "trend_ok": None,
                    "trend_basis": "third sell checks rebound after leaving the center; focus is staying below ZD",
                    "guard_name": "ZD",
                    "guard_value": round(float(ev.get("boundary", zs.get("ZD"))), 4),
                    "zs": zs,
                    "segments": segments,
                    "macd_ratio": macd_ratio,
                }

            zs = ev.get("zs")
            if not isinstance(zs, dict) or not zs.get("start"):
                return {}
            direction = "down" if "B" in label else "up"
            sig_ts = pd.Timestamp(sig["time"])
            zs_start_ts = pd.Timestamp(zs["start"])
            valid_fractals = sorted(layer_result.get("fractals", []), key=lambda f: pd.Timestamp(f["date"]))
            touch_fractals = [
                f
                for f in valid_fractals
                if zs_start_ts <= pd.Timestamp(f["date"]) < sig_ts
                and float(zs["ZD"]) <= float(f["val"]) <= float(zs["ZG"])
            ]
            hub_exit_time = fmt_time(touch_fractals[-1]["date"]) if touch_fractals else fmt_time(zs_start_ts)
            entry_fracs = [f for f in valid_fractals if pd.Timestamp(f["date"]) < zs_start_ts]
            if not entry_fracs:
                return {}
            if label == "1B":
                prev_extremes = [f for f in entry_fracs if f["type"] == "Top"]
            else:
                prev_extremes = [f for f in entry_fracs if f["type"] == "Bottom"]
            start_a_time = fmt_time(prev_extremes[-1]["date"] if prev_extremes else entry_fracs[-1]["date"])
            entry_start = point_for(start_a_time)
            entry_end = point_for(fmt_time(zs_start_ts))
            leave_start = point_for(hub_exit_time)
            leave_end = point_for(sig["time"], sig.get("price"))
            if not all([entry_start, entry_end, leave_start, leave_end]):
                return {}
            segments = [
                make_segment("entry", entry_start, entry_end, direction),
                make_segment("leave", leave_start, leave_end, direction),
            ]
            entry_area = segments[0].get("macd_area")
            leave_area = segments[1].get("macd_area")
            macd_ratio = None
            if entry_area not in (None, 0) and leave_area is not None:
                macd_ratio = round(float(leave_area) / max(1e-6, float(entry_area)), 4)
            zs_idx = next(
                (
                    i for i, item in enumerate(layer_all_zs)
                    if item.get("start") == zs.get("start") and item.get("end") == zs.get("end")
                ),
                None,
            )
            prior_zs = layer_all_zs[zs_idx - 1] if isinstance(zs_idx, int) and zs_idx > 0 else None
            trend_ok = False
            trend_basis = "single related center; classify as consolidation divergence / exhaustion"
            if prior_zs:
                if direction == "down":
                    trend_ok = float(zs["ZG"]) < float(prior_zs["ZG"]) and float(zs["ZD"]) < float(prior_zs["ZD"])
                    trend_basis = (
                        "two descending centers support downtrend divergence"
                        if trend_ok
                        else "prior center exists but centers are not clearly descending"
                    )
                else:
                    trend_ok = float(zs["ZG"]) > float(prior_zs["ZG"]) and float(zs["ZD"]) > float(prior_zs["ZD"])
                    trend_basis = (
                        "two ascending centers support uptrend divergence"
                        if trend_ok
                        else "prior center exists but centers are not clearly ascending"
                    )
            divergence_class = "trend_divergence" if trend_ok else "consolidation_divergence"
            return {
                "level": layer_period,
                "signal_type": label,
                "compare_type": divergence_class,
                "divergence_class": divergence_class,
                "trend_ok": trend_ok,
                "trend_basis": trend_basis,
                "guard_name": "1B low" if label == "1B" else "1S high",
                "guard_value": round(float(sig.get("price", leave_end["value"])), 4),
                "prior_zs": prior_zs,
                "zs": zs,
                "segments": segments,
                "macd_ratio": macd_ratio,
                "note": "1B/1S 对比关联中枢前后的同向推动段。",
            }

        for sig in signals_local:
            ev = sig.setdefault("evidence", {})
            layers_ev = ev.setdefault("evidence_layers", {})
            self_ev = build_self_level_evidence(sig)
            if self_ev:
                layers_ev["self_level"] = self_ev
                ev["divergence_class"] = self_ev["divergence_class"]
                ev["trend_ok"] = self_ev["trend_ok"]
                ev["trend_basis"] = self_ev["trend_basis"]

        return {
            "level": layer_period,
            "bi_points": layer_bi_points,
            "zs": layer_zs,
            "signals": signals_local,
            "candidates": candidates_local,
            "macd": layer_macd,
        }

    base_layer = build_layer(result, period, "base", with_forward=True)
    def promote_5m_to_30m_small_to_big() -> list[dict]:
        if period != "30m":
            return []
        p5 = period_file(symbol, "5m")
        if not p5.exists():
            return []
        try:
            r5 = run_analysis(pd.read_csv(p5), "5m")
            l5 = build_layer(r5, "5m", "aux5", with_forward=False)
        except Exception:
            return []
        seed_signals = list(l5.get("signals", [])) + list(l5.get("candidates", []))
        cand_1b = [s for s in seed_signals if s["label"] == "1B"]
        cand_1s = [s for s in seed_signals if s["label"] == "1S"]
        fr = sorted(result.get("fractals", []), key=lambda x: x["date"])
        if (not cand_1b and not cand_1s) or not fr:
            return []

        promoted: list[dict] = []
        taken_b0: set[str] = set()
        taken_buy_zs: set[str] = set()
        taken_sell_zs: set[str] = set()

        def recent_zs_before(ts: pd.Timestamp):
            zs_items = [
                z for z in result.get("zs", [])
                if pd.Timestamp(zs_end(z)) < ts
            ]
            return zs_items[-1] if zs_items else None

        def zs_key(z) -> str:
            return f"{fmt_time(zs_start(z))}|{fmt_time(zs_end(z))}"

        for c in cand_1b:
            tc = pd.Timestamp(c["time"])
            nearby = [
                f for f in fr
                if f["type"] == "Bottom" and abs((pd.Timestamp(f["date"]) - tc).total_seconds()) <= 24 * 3600
            ]
            if not nearby:
                continue
            b0 = min(nearby, key=lambda f: abs((pd.Timestamp(f["date"]) - tc).total_seconds()))
            b0_time = fmt_time(pd.Timestamp(b0["date"]))
            if b0_time in taken_b0:
                continue
            i0 = fr.index(b0)
            prev_bottoms = [f for f in fr[:i0] if f["type"] == "Bottom"]
            prev_bottom = prev_bottoms[-1] if prev_bottoms else None
            makes_new_low = prev_bottom is None or float(b0["val"]) < float(prev_bottom["val"]) * (1 - SM_EXTREME_BUFFER)
            recent_z = recent_zs_before(pd.Timestamp(b0["date"]))
            third_buy_context = False
            third_buy_zs_key = None
            if recent_z is not None:
                third_buy_zs_key = zs_key(recent_z)
                third_buy_context = (
                    float(b0["val"]) > float(zs_zg(recent_z)) * (1 + SM_EXTREME_BUFFER)
                    and third_buy_zs_key not in taken_buy_zs
                )
            if not makes_new_low and not third_buy_context:
                continue

            t1 = next((f for f in fr[i0 + 1 :] if f["type"] == "Top"), None)
            if t1 is None:
                continue
            i1 = fr.index(t1)
            b1 = next((f for f in fr[i1 + 1 :] if f["type"] == "Bottom"), None)
            if b1 is None:
                continue
            i2 = fr.index(b1)
            t2 = next((f for f in fr[i2 + 1 :] if f["type"] == "Top"), None)
            if t2 is None:
                continue

            # state-machine confirmation:
            # 5m candidate -> 30m回踩不破(b1>b0) -> 再上破(t2>t1)
            hold_ratio = SENSITIVITY_PROFILE[sensitivity]["hold_ratio"]
            break_ratio = SENSITIVITY_PROFILE[sensitivity]["break_ratio"]
            if float(b1["val"]) >= float(b0["val"]) * hold_ratio and float(t2["val"]) >= float(t1["val"]) * break_ratio:
                taken_b0.add(b0_time)
                if third_buy_context and third_buy_zs_key:
                    taken_buy_zs.add(third_buy_zs_key)
                    promoted.append(
                        {
                            "id": f"sm30-3b-{b0_time}",
                            "time": b0_time,
                            "price": float(b0["val"]),
                            "label": "3B",
                            "confidence": 0.70,
                            "basis": "5m local divergence after 30m center breakout; pullback stayed above the center, so classify as 30m third buy",
                            "related_zs": None,
                            "evidence": {
                                "source": "state_machine_5m_to_30m",
                                "candidate_5m_time": c["time"],
                                "b0_time": b0_time,
                                "t1_time": fmt_time(pd.Timestamp(t1["date"])),
                                "b1_time": fmt_time(pd.Timestamp(b1["date"])),
                                "t2_time": fmt_time(pd.Timestamp(t2["date"])),
                                "zs": json_safe(recent_z),
                                "rule": "5m watch + 30m center breakout pullback above ZG -> 30m 3B",
                            },
                            "forward": {},
                            "level": "30m",
                        }
                    )
                    continue
                promoted.append(
                    {
                        "id": f"sm30-1b-{b0_time}",
                        "time": b0_time,
                        "price": float(b0["val"]),
                        "label": "1B",
                        "confidence": 0.74,
                        "basis": "5m候选经30m回踩不破并上破确认的小转大1B",
                        "related_zs": None,
                        "evidence": {
                            "source": "state_machine_5m_to_30m",
                            "candidate_5m_time": c["time"],
                            "b0_time": b0_time,
                            "t1_time": fmt_time(pd.Timestamp(t1["date"])),
                            "b1_time": fmt_time(pd.Timestamp(b1["date"])),
                            "t2_time": fmt_time(pd.Timestamp(t2["date"])),
                            "rule": "5m候选 -> 30m回踩不破 -> 再上破，固化为小转大",
                        },
                        "forward": {},
                        "level": "30m",
                    }
                )
                promoted.append(
                    {
                        "id": f"sm30-2b-{fmt_time(pd.Timestamp(b1['date']))}",
                        "time": fmt_time(pd.Timestamp(b1["date"])),
                        "price": float(b1["val"]),
                        "label": "2B",
                        "confidence": 0.72,
                        "basis": "小转大确认后的30m回踩不破2B",
                        "related_zs": None,
                        "evidence": {
                            "source": "state_machine_5m_to_30m",
                            "first_signal_time": b0_time,
                            "first_signal_value": float(b0["val"]),
                            "rule": "确认后回踩不破",
                        },
                        "forward": {},
                        "level": "30m",
                    }
                )
        taken_t0: set[str] = set()
        for c in cand_1s:
            tc = pd.Timestamp(c["time"])
            nearby = [
                f for f in fr
                if f["type"] == "Top" and abs((pd.Timestamp(f["date"]) - tc).total_seconds()) <= 24 * 3600
            ]
            if not nearby:
                continue
            t0 = min(nearby, key=lambda f: abs((pd.Timestamp(f["date"]) - tc).total_seconds()))
            t0_time = fmt_time(pd.Timestamp(t0["date"]))
            if t0_time in taken_t0:
                continue
            i0 = fr.index(t0)
            prev_tops = [f for f in fr[:i0] if f["type"] == "Top"]
            prev_top = prev_tops[-1] if prev_tops else None
            makes_new_high = prev_top is None or float(t0["val"]) > float(prev_top["val"]) * (1 + SM_EXTREME_BUFFER)
            recent_z = recent_zs_before(pd.Timestamp(t0["date"]))
            third_sell_context = False
            third_sell_zs_key = None
            if recent_z is not None:
                third_sell_zs_key = zs_key(recent_z)
                third_sell_context = (
                    float(t0["val"]) < float(zs_zd(recent_z)) * (1 - SM_EXTREME_BUFFER)
                    and third_sell_zs_key not in taken_sell_zs
                )
            if not makes_new_high and not third_sell_context:
                continue

            b1 = next((f for f in fr[i0 + 1 :] if f["type"] == "Bottom"), None)
            if b1 is None:
                continue
            i1 = fr.index(b1)
            t1 = next((f for f in fr[i1 + 1 :] if f["type"] == "Top"), None)
            if t1 is None:
                continue
            i2 = fr.index(t1)
            b2 = next((f for f in fr[i2 + 1 :] if f["type"] == "Bottom"), None)
            if b2 is None:
                continue

            hold_ratio = SENSITIVITY_PROFILE[sensitivity]["hold_ratio"]
            break_ratio = SENSITIVITY_PROFILE[sensitivity]["break_ratio"]
            # sell-side: rebound not break previous top, then downside breaks again
            if float(t1["val"]) <= float(t0["val"]) / hold_ratio and float(b2["val"]) <= float(b1["val"]) / break_ratio:
                taken_t0.add(t0_time)
                if third_sell_context and third_sell_zs_key:
                    taken_sell_zs.add(third_sell_zs_key)
                    promoted.append(
                        {
                            "id": f"sm30-3s-{t0_time}",
                            "time": t0_time,
                            "price": float(t0["val"]),
                            "label": "3S",
                            "confidence": 0.70,
                            "basis": "5m local divergence after 30m center breakdown; rebound stayed below the center, so classify as 30m third sell",
                            "related_zs": None,
                            "evidence": {
                                "source": "state_machine_5m_to_30m",
                                "candidate_5m_time": c["time"],
                                "t0_time": t0_time,
                                "b1_time": fmt_time(pd.Timestamp(b1["date"])),
                                "t1_time": fmt_time(pd.Timestamp(t1["date"])),
                                "b2_time": fmt_time(pd.Timestamp(b2["date"])),
                                "zs": json_safe(recent_z),
                                "rule": "5m watch + 30m center breakdown rebound below ZD -> 30m 3S",
                            },
                            "forward": {},
                            "level": "30m",
                        }
                    )
                    continue
                promoted.append(
                    {
                        "id": f"sm30-1s-{t0_time}",
                        "time": t0_time,
                        "price": float(t0["val"]),
                        "label": "1S",
                        "confidence": 0.74,
                        "basis": "5m候选经30m反抽不破并再下破确认的小转大1S",
                        "related_zs": None,
                        "evidence": {
                            "source": "state_machine_5m_to_30m",
                            "candidate_5m_time": c["time"],
                            "t0_time": t0_time,
                            "b1_time": fmt_time(pd.Timestamp(b1["date"])),
                            "t1_time": fmt_time(pd.Timestamp(t1["date"])),
                            "b2_time": fmt_time(pd.Timestamp(b2["date"])),
                            "rule": "5m候选 -> 30m反抽不破 -> 再下破，固化为小转大",
                        },
                        "forward": {},
                        "level": "30m",
                    }
                )
                promoted.append(
                    {
                        "id": f"sm30-2s-{fmt_time(pd.Timestamp(t1['date']))}",
                        "time": fmt_time(pd.Timestamp(t1["date"])),
                        "price": float(t1["val"]),
                        "label": "2S",
                        "confidence": 0.72,
                        "basis": "小转大确认后的30m反抽不破2S",
                        "related_zs": None,
                        "evidence": {
                            "source": "state_machine_5m_to_30m",
                            "first_signal_time": t0_time,
                            "first_signal_value": float(t0["val"]),
                            "rule": "确认后反抽不破",
                        },
                        "forward": {},
                        "level": "30m",
                    }
                )
        return promoted

    promoted_sm = promote_5m_to_30m_small_to_big()
    promoted_sm_count = len(promoted_sm)
    if promoted_sm:
        merged = list(base_layer["signals"]) + promoted_sm
        # dedup by (time,label), prefer state-machine signals
        merged_sorted = sorted(merged, key=lambda x: (x["time"], x["label"], 0 if str(x.get("id", "")).startswith("sm30-") else 1))
        dedup = {}
        for s in merged_sorted:
            dedup[(s["time"], s["label"])] = s
        side_rank = {"1B": 1, "2B": 2, "3B": 3, "1S": 1, "2S": 2, "3S": 3}
        side_dedup = {}
        for s in dedup.values():
            side = "B" if "B" in s["label"] else "S"
            key = (s["time"], side)
            old = side_dedup.get(key)
            if old is None or side_rank.get(s["label"], 0) > side_rank.get(old["label"], 0):
                side_dedup[key] = s
        base_layer["signals"] = prune_invalid_signals(list(side_dedup.values()), result["df"])

    def promote_30m_to_daily_third_buy() -> list[dict]:
        if period != "30m":
            return []
        daily_df = to_daily_ohlc(result["df"][["time", "open", "high", "low", "close"]])
        if len(daily_df) < 20:
            return []
        daily_result = run_analysis(daily_df, "1d")
        daily_fr = sorted(daily_result.get("fractals", []), key=lambda x: x["date"])
        daily_zs = sorted(daily_result.get("zs", []), key=lambda z: zs_end(z))
        intraday = result["df"].copy()
        intraday["time"] = pd.to_datetime(intraday["time"])
        promoted: list[dict] = []
        for z in daily_zs:
            zg = float(zs_zg(z))
            z_end = pd.Timestamp(zs_end(z)).floor("D")
            top_candidates = [
                f for f in daily_fr
                if f["type"] == "Top"
                and pd.Timestamp(f["date"]).floor("D") >= z_end
                and float(f["val"]) > zg * (1 + SM_EXTREME_BUFFER)
            ]
            if not top_candidates:
                continue
            top = top_candidates[0]
            top_day = pd.Timestamp(top["date"]).floor("D")
            daily_after_top = daily_df.loc[daily_df["time"] > top_day].copy()
            if daily_after_top.empty:
                continue
            pullback_rows = []
            confirm_day = None
            for row in daily_after_top.itertuples(index=False):
                pullback_rows.append(row)
                if float(row.high) > float(top["val"]) * (1 + SM_EXTREME_BUFFER):
                    confirm_day = pd.Timestamp(row.time).floor("D")
                    break
            if confirm_day is None or not pullback_rows:
                continue
            pullback_df = pd.DataFrame(pullback_rows)
            pullback_low = float(pullback_df["low"].min())
            if pullback_low <= zg * (1 + SM_EXTREME_BUFFER):
                continue
            low_day = pd.Timestamp(pullback_df.loc[pullback_df["low"].idxmin(), "time"]).floor("D")
            low_window = intraday.loc[
                (intraday["time"] >= low_day)
                & (intraday["time"] < low_day + pd.Timedelta(days=1))
            ]
            if low_window.empty:
                low_time = low_day + pd.Timedelta(hours=15)
                low_price = pullback_low
            else:
                low_row = low_window.loc[low_window["low"].idxmin()]
                low_time = pd.Timestamp(low_row["time"])
                low_price = float(low_row["low"])
            sig_time = fmt_time(low_time)
            if sig_time not in visible_times:
                continue
            promoted.append(
                {
                    "id": f"d1-3b-{sig_time}",
                    "time": sig_time,
                    "price": low_price,
                    "label": "3B",
                    "confidence": 0.78,
                    "basis": "Daily center breakout, pullback stayed above daily ZG, then price broke the prior daily high; promoted as 1d third buy.",
                    "related_zs": None,
                    "evidence": {
                        "source": "state_machine_30m_to_1d",
                        "higher_level": "1d",
                        "context_state": "daily_3b_confirmed",
                        "zs": json_safe(z),
                        "daily_zg": zg,
                        "daily_zd": float(zs_zd(z)),
                        "leave_top_time": fmt_time(top["date"]),
                        "leave_top_value": float(top["val"]),
                        "pullback_low_time": sig_time,
                        "pullback_low_value": low_price,
                        "confirm_day": fmt_time(confirm_day),
                        "rule": "1d center formed -> upward leave -> pullback low stayed above daily ZG -> next daily break above leave top -> 1d-3B",
                        "logic_text": "This is a higher-level third-buy context. Lower-level 30m sell points inside the pullback are treated as pullback risk, not dominant sell signals.",
                    },
                    "forward": {},
                    "level": "1d",
                }
            )
        return promoted[-2:]

    daily_context_signals = promote_30m_to_daily_third_buy()
    if daily_context_signals:
        protected_windows = []
        for sig in daily_context_signals:
            ev = sig.get("evidence", {})
            start_ts = pd.Timestamp(ev.get("leave_top_time"))
            end_ts = pd.Timestamp(ev.get("confirm_day"))
            protected_windows.append((start_ts, end_ts))
        base_layer["signals"] = [
            s for s in base_layer["signals"]
            if not (
                s["label"] == "3B"
                and s.get("level") == "30m"
                and any(a <= pd.Timestamp(s["time"]) <= b for a, b in protected_windows)
            )
        ]
        for s in base_layer["signals"]:
            if (
                "S" in s["label"]
                and s.get("level") == "30m"
                and any(a <= pd.Timestamp(s["time"]) <= b for a, b in protected_windows)
            ):
                s["status"] = "risk"
                s["confidence"] = min(float(s.get("confidence", 0.5)), 0.38)
                ev = dict(s.get("evidence", {}))
                ev["context_conflict"] = "inside_daily_3b_pullback"
                ev["logic_text"] = (
                    "This 30m sell signal is inside a higher-level daily third-buy pullback. "
                    "Treat it as pullback risk rather than a dominant sell point."
                )
                s["evidence"] = ev

    signals = base_layer["signals"]
    candidates = base_layer.get("candidates", [])
    zs = base_layer["zs"]
    bi_points = base_layer["bi_points"]
    layers = [base_layer]
    higher_period = "30m" if period == "5m" else "1d"
    if higher_period == "30m":
        higher_path = period_file(symbol, "30m")
        if higher_path.exists():
            higher_df = pd.read_csv(higher_path)
            higher_result = run_analysis(higher_df, "30m")
            hl = build_layer(higher_result, "30m", "higher", with_forward=False)
            # keep only active/recent upper-level centers to avoid long stale overlays
            if hl["zs"]:
                view_end_ts = pd.to_datetime(bars["time"]).max()
                recent_cut = view_end_ts - pd.Timedelta(days=50)
                hl["zs"] = [
                    z for z in hl["zs"]
                    if pd.Timestamp(z["end"]) >= recent_cut
                ]
            layers.append(hl)
    else:
        daily_df = to_daily_ohlc(result["df"][["time", "open", "high", "low", "close"]])
        if len(daily_df) >= 20:
            higher_result = run_analysis(daily_df, "1d")
            hl = build_layer(higher_result, "1d", "higher", with_forward=False)
            if daily_context_signals:
                existing = {(s["time"], s["label"]) for s in hl.get("signals", [])}
                hl["signals"] = list(hl.get("signals", [])) + [
                    s for s in daily_context_signals
                    if (s["time"], s["label"]) not in existing
                ]
            if hl["zs"]:
                view_end_ts = pd.to_datetime(bars["time"]).max()
                recent_cut = view_end_ts - pd.Timedelta(days=45)
                hl["zs"] = [
                    z for z in hl["zs"]
                    if pd.Timestamp(z["end"]) >= recent_cut
                ]
            layers.append(hl)

    def sync_signal_lifecycle(sig: dict) -> None:
        ev = sig.setdefault("evidence", {})
        life = dict(sig.get("lifecycle") or ev.get("lifecycle") or {})
        if not life:
            life = {
                "state": "risk" if sig.get("status") == "risk" else "confirmed",
                "candidate_at": ev.get("candidate_5m_time") or ev.get("first_signal_time"),
                "confirmed_at": sig.get("time"),
                "invalidated_at": None,
                "expired_at": None,
                "note": "已确认信号保留当时证据；后续K线不会重写原信号。",
            }
        elif sig.get("status") == "risk":
            life["state"] = "risk"
            life["note"] = "信号已确认，但被高级别环境风险降级；原始证据不重写。"
        sig["lifecycle"] = life
        ev["lifecycle"] = life

    for layer in layers:
        for sig in layer.get("signals", []):
            sync_signal_lifecycle(sig)
        for sig in layer.get("candidates", []):
            ev = sig.setdefault("evidence", {})
            if sig.get("lifecycle"):
                ev["lifecycle"] = sig["lifecycle"]

    payload_bars = [
        {
            "time": row.time,
            "open": float(row.open),
            "high": float(row.high),
            "low": float(row.low),
            "close": float(row.close),
            "macd": float(row.macd),
            "dif": float(row.dif),
            "dea": float(row.dea),
        }
        for row in bars.itertuples(index=False)
    ]
    current_price = payload_bars[-1]["close"]
    active_zs = result["zs"][-1] if result["zs"] else None
    current_state = "no_center"
    if active_zs is not None:
        active_zg = active_zs.zg if hasattr(active_zs, "zg") else active_zs["ZG"]
        active_zd = active_zs.zd if hasattr(active_zs, "zd") else active_zs["ZD"]
        if current_price > active_zg:
            current_state = "above_active_bi_zs"
        elif current_price < active_zd:
            current_state = "below_active_bi_zs"
        else:
            current_state = "inside_active_bi_zs"
    return {
        "symbol": symbol,
        "stock_name": stock_display_name(symbol, online=False),
        "period": period,
        "version": APP_VERSION,
        "bars": payload_bars,
        "zs": zs,
        "signals": signals,
        "candidates": candidates,
        "bi_points": bi_points,
        "layers": layers,
        "current": {
            "price": current_price,
            "state": current_state,
            "active_zs": None
            if active_zs is None
            else {
                "start": fmt_time(active_zs.start if hasattr(active_zs, "start") else active_zs["start"]),
                "end": fmt_time(active_zs.end if hasattr(active_zs, "end") else active_zs["end"]),
                "ZD": active_zs.zd if hasattr(active_zs, "zd") else active_zs["ZD"],
                "ZG": active_zs.zg if hasattr(active_zs, "zg") else active_zs["ZG"],
                "bi_count": active_zs.bi_count if hasattr(active_zs, "bi_count") else None,
            },
        },
        "summary": {
            "bars": len(payload_bars),
            "analysis_bars": len(result["df"]),
            "bis": len(result["bis"]) if "bis" in result else max(0, len(result.get("fractals", [])) - 1),
            "zs": len(result["zs"]),
            "signals": len(signals),
            "candidates": len(candidates),
            "total_signals": len(result["signals"]),
            "engine": engine,
            "app_version": APP_VERSION,
            "sensitivity": sensitivity,
            "promoted_sm_count": promoted_sm_count,
            "default_start_date": default_start_date,
            "default_trading_days": DEFAULT_TRADING_DAYS,
            "analysis_start": fmt_time(analysis_start),
            "analysis_end": fmt_time(analysis_end),
            "view_start": payload_bars[0]["time"],
            "view_end": payload_bars[-1]["time"],
            "first_time": payload_bars[0]["time"],
            "last_time": payload_bars[-1]["time"],
        },
    }


class SandboxHandler(BaseHTTPRequestHandler):
    server_version = "ChanlunSandbox/10.21"

    def log_message(self, fmt: str, *args) -> None:
        message = "%s - %s" % (self.address_string(), fmt % args)
        print(message.encode("ascii", errors="ignore").decode("ascii"))

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        qs = urllib.parse.parse_qs(parsed.query)
        try:
            if parsed.path == "/":
                body = HTML.encode("utf-8")
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
                return
            if parsed.path == "/api/stocks":
                self.send_json({"stocks": list_stocks()})
                return
            if parsed.path == "/api/fetch":
                symbol = qs.get("symbol", [""])[0]
                synced_symbol = fetch_and_cache(symbol)
                self.send_json({"symbol": synced_symbol, "name": stock_display_name(synced_symbol)})
                return
            if parsed.path == "/api/analyze":
                symbol = qs.get("symbol", [""])[0]
                period = qs.get("period", ["5m"])[0]
                start = qs.get("start", [""])[0]
                sensitivity = qs.get("sensitivity", ["balanced"])[0]
                self.send_json(analyze_payload(symbol, period, start, sensitivity))
                return
            self.send_json({"error": "not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else PORT
    if "--no-log-redirect" not in sys.argv:
        log_path = ROOT / "sandbox_runtime.log"
        log_file = open(log_path, "a", encoding="utf-8", buffering=1)
        sys.stdout = log_file
        sys.stderr = log_file
    httpd = ThreadingHTTPServer((HOST, port), SandboxHandler)
    print(f"Chanlun sandbox running at http://{HOST}:{port}")
    print(f"Data directory: {str(DATA_DIR).encode('ascii', errors='ignore').decode('ascii')}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()
