import { useCallback, useEffect, useMemo, useState } from "react";
import { ArrowUpDown, CalendarDays, Download, Layers3, RefreshCw, Save } from "lucide-react";
import AnalysisChart from "./AnalysisChart";
import EvidencePanel from "./EvidencePanel";
import { api } from "./api";
import type { AnalysisResponse, AnalyzePayload, ChanSignal, StockInfo } from "./types";

function defaultLayers(level: "5m" | "30m") {
  const fiveMinute = level === "5m";
  return {
    executionStrokes: fiveMinute,
    executionSegments: fiveMinute,
    executionCenters: fiveMinute,
    executionSegmentCenters: fiveMinute,
    decisionStrokes: !fiveMinute,
    decisionSegments: !fiveMinute,
    decisionCenters: !fiveMinute,
    decisionSegmentCenters: !fiveMinute,
    higherStrokes: false,
    higherSegments: false,
    higherCenters: !fiveMinute,
    signals: true,
    segmentSignals: false,
    macd: true,
    centerHistory: false,
  };
}

function inputDate(value: string): string {
  return value ? value.slice(0, 10) : "";
}

export default function App() {
  const [stocks, setStocks] = useState<StockInfo[]>([]);
  const [symbol, setSymbol] = useState("sh000001");
  const [fetchSymbol, setFetchSymbol] = useState("");
  const [viewLevel, setViewLevel] = useState<"5m" | "30m">("30m");
  const [levelVisibility, setLevelVisibility] = useState<Record<"5m" | "30m" | "1d", boolean>>({ "5m": false, "30m": true, "1d": false });
  const [startDate, setStartDate] = useState("");
  const [endDate, setEndDate] = useState("");
  const [includeInvalidated, setIncludeInvalidated] = useState(false);
  const [layers, setLayers] = useState(() => defaultLayers("30m"));
  const [layersOpen, setLayersOpen] = useState(true);
  const [analysis, setAnalysis] = useState<AnalysisResponse | null>(null);
  const [selectedSignal, setSelectedSignal] = useState<ChanSignal | null>(null);
  const [signalAuditMode, setSignalAuditMode] = useState<"confirmed" | "all" | "questionable">("confirmed");
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState("正在连接沙盘");
  const [error, setError] = useState("");

  const payload = useMemo<AnalyzePayload>(() => ({
    symbol,
    decision_level: "30m",
    execution_level: "5m",
    display_level: viewLevel,
    start: startDate ? `${startDate}T00:00:00` : undefined,
    end: endDate ? `${endDate}T23:59:59` : undefined,
    profile: "balanced",
    benchmark: "sh000001",
    include_invalidated: includeInvalidated,
  }), [symbol, viewLevel, startDate, endDate, includeInvalidated]);

  const loadStocks = useCallback(async () => {
    const items = await api.stocks();
    setStocks(items);
    if (!items.some((item) => item.symbol === symbol) && items.length) setSymbol(items[0].symbol);
  }, [symbol]);

  const loadAnalysis = useCallback(async (request = payload) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.analyze(request);
      setAnalysis(result);
      setSelectedSignal(null);
      if (!endDate) setEndDate(inputDate(result.visible_bar_end));
      setMessage(`更新至 ${result.visible_bar_end.replace("T", " ").slice(0, 16)}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  }, [payload, startDate, endDate]);

  useEffect(() => {
    void (async () => {
      try {
        await loadStocks();
        await loadAnalysis();
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : String(reason));
      }
    })();
    // Initial boot deliberately runs once; subsequent changes use explicit controls.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const sync = async (requestedSymbol = symbol) => {
    setLoading(true);
    setError("");
    try {
      const result = await api.sync(requestedSymbol) as { symbol?: string };
      const syncedSymbol = result.symbol || requestedSymbol.trim().toLowerCase();
      await loadStocks();
      setSymbol(syncedSymbol);
      setFetchSymbol("");
      await loadAnalysis({ ...payload, symbol: syncedSymbol });
      setMessage("行情同步完成");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setLoading(false);
    }
  };

  const changeViewLevel = async (level: "5m" | "30m") => {
    setViewLevel(level);
    setLevelVisibility(level === "5m"
      ? { "5m": true, "30m": false, "1d": false }
      : { "5m": false, "30m": true, "1d": false });
    setLayers(defaultLayers(level));
    await loadAnalysis({ ...payload, display_level: level });
  };

  const toggleLayer = (key: keyof typeof layers, checked: boolean) => {
    setLayers((current) => ({ ...current, [key]: checked }));
  };

  const toggleLevel = (level: "5m" | "30m" | "1d") => {
    setLevelVisibility((current) => {
      if (current[level] && Object.values(current).filter(Boolean).length === 1) return current;
      return { ...current, [level]: !current[level] };
    });
  };

  const changeSymbol = async (nextSymbol: string) => {
    setSymbol(nextSymbol);
    await loadAnalysis({ ...payload, symbol: nextSymbol });
  };

  const freeze = async () => {
    if (!analysis) return;
    try {
      await api.snapshot({ ...payload, as_of: analysis.as_of, end: undefined });
      setMessage("当前证据已冻结");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const exportAnalysis = async () => {
    if (!analysis) return;
    try {
      const result = await api.export({ ...payload, as_of: analysis.as_of, end: undefined });
      setMessage(`已导出 ${result.path}`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    }
  };

  const stock = stocks.find((item) => item.symbol === symbol);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand-block"><b>缠论互动沙盘</b><span>逻辑 V1</span></div>
        <div className="instrument-title"><strong>{stock?.name || analysis?.stock_name || symbol}</strong><span>{symbol} · {viewLevel === "5m" ? "5m 结构" : "30m 结构"} · 可叠加上级别</span></div>
        <div className="topbar-state">
          <span className="live-pill">实时</span>
          <span>{message}</span>
        </div>
      </header>

      <div className="workspace">
        <aside className="control-rail">
          <section className="control-section">
            <label htmlFor="symbol">标的</label>
            <div className="inline-control">
              <select id="symbol" value={symbol} onChange={(event) => void changeSymbol(event.target.value)} disabled={loading}>
                {stocks.map((item) => <option value={item.symbol} key={item.symbol}>{item.name ? `${item.name} ${item.symbol}` : item.symbol}</option>)}
              </select>
              <button className="icon-button primary" onClick={() => sync(symbol)} title="刷新当前标的" aria-label="刷新当前标的" disabled={loading}><RefreshCw size={16} /></button>
            </div>
          </section>

          <section className="control-section">
            <label htmlFor="fetch-symbol">在线同步 / 新增标的</label>
            <div className="inline-control">
              <input id="fetch-symbol" type="text" value={fetchSymbol} onChange={(event) => setFetchSymbol(event.target.value)} placeholder="如 sh000001 / 000001" />
              <button className="icon-button primary" onClick={() => sync(fetchSymbol || symbol)} title="同步或新增标的" aria-label="同步或新增标的" disabled={loading}><ArrowUpDown size={16} /></button>
            </div>
          </section>

          <section className="control-section">
            <label><CalendarDays size={14} /> 周期与范围</label>
            <div className="period-segmented" role="group" aria-label="观察周期">
              <button className={viewLevel === "5m" ? "active" : ""} aria-pressed={viewLevel === "5m"} disabled={loading} onClick={() => viewLevel !== "5m" && void changeViewLevel("5m")}>5m 观察</button>
              <button className={viewLevel === "30m" ? "active" : ""} aria-pressed={viewLevel === "30m"} disabled={loading} onClick={() => viewLevel !== "30m" && void changeViewLevel("30m")}>30m 决策</button>
            </div>
            <div className="date-range-controls">
              <label className="date-field-row"><span>开始</span><input aria-label="起点日期" type="date" value={startDate} onChange={(event) => setStartDate(event.target.value)} /></label>
              <label className="date-field-row"><span>结束</span><input aria-label="结束日期" type="date" value={endDate} onChange={(event) => setEndDate(event.target.value)} /></label>
            </div>
          </section>

          <section className="control-section level-filter-section">
            <label>级别过滤</label>
            <div className="level-filter-actions">
              {(["5m", "30m", "1d"] as const).map((level) => <button key={level} className={levelVisibility[level] ? "active" : ""} onClick={() => toggleLevel(level)}>{level}</button>)}
            </div>
            <p>当前显示：{(["5m", "30m", "1d"] as const).filter((level) => levelVisibility[level]).join(" + ")}</p>
          </section>

          <details className="control-section layer-details" open={layersOpen} onToggle={(event) => setLayersOpen(event.currentTarget.open)}>
            <summary><Layers3 size={14} />图层细调</summary>
            <div className="layers-section">
              <section className="layer-module structure-module">
                <h4>结构层级</h4>
                <div className="layer-level-list">
                  {[
                    { level: "5m", items: [["executionStrokes", "笔"], ["executionSegments", "线段"], ["executionCenters", "笔中枢"], ["executionSegmentCenters", "段中枢"]] },
                    { level: "30m", items: [["decisionStrokes", "笔"], ["decisionSegments", "线段"], ["decisionCenters", "笔中枢"], ["decisionSegmentCenters", "段中枢"]] },
                    { level: "日线", items: [["higherStrokes", "笔"], ["higherSegments", "线段"], ["higherCenters", "中枢"]] },
                  ].map((group) => (
                    <div className="layer-level-row" key={group.level}>
                      <span className="layer-level-name">{group.level}</span>
                      <div className="layer-level-options">
                        {group.items.map(([key, label]) => (
                          <label className="check-row" key={key}><input type="checkbox" checked={layers[key as keyof typeof layers]} onChange={(event) => toggleLayer(key as keyof typeof layers, event.target.checked)} /><span>{label}</span></label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
                <label className="check-row layer-wide-option"><input type="checkbox" checked={layers.centerHistory} onChange={(event) => toggleLayer("centerHistory", event.target.checked)} /><span>显示完整中枢历史</span></label>
              </section>

              <section className="layer-module">
                <h4>信号显示</h4>
                <div className="layer-option-grid">
                  <label className="check-row"><input type="checkbox" checked={layers.signals} onChange={(event) => toggleLayer("signals", event.target.checked)} /><span>笔买卖点</span></label>
                  <label className="check-row"><input type="checkbox" checked={layers.segmentSignals} onChange={(event) => toggleLayer("segmentSignals", event.target.checked)} /><span>段买卖点</span></label>
                  <label className="check-row"><input type="checkbox" checked={includeInvalidated} onChange={(event) => setIncludeInvalidated(event.target.checked)} /><span>失效历史</span></label>
                </div>
                <label className="signal-audit-control">
                  <span>一类点筛选</span>
                  <select value={signalAuditMode} onChange={(event) => setSignalAuditMode(event.target.value as typeof signalAuditMode)}>
                    <option value="confirmed">严格确认</option>
                    <option value="all">全部候选</option>
                    <option value="questionable">仅看争议</option>
                  </select>
                </label>
              </section>

              <section className="layer-module">
                <h4>技术指标</h4>
                <div className="layer-option-grid">
                  <label className="check-row"><input type="checkbox" checked={layers.macd} onChange={(event) => toggleLayer("macd", event.target.checked)} /><span>MACD</span></label>
                </div>
              </section>
            </div>
          </details>

          <div className="rail-actions">
            <button className="command-button primary" onClick={() => loadAnalysis()} disabled={loading}><RefreshCw size={15} />分析</button>
            <button className="icon-button" onClick={freeze} title="冻结快照" disabled={!analysis}><Save size={16} /></button>
            <button className="icon-button" onClick={exportAnalysis} title="导出" disabled={!analysis}><Download size={16} /></button>
          </div>
        </aside>

        <main className="chart-stage">
          {error && <div className="error-banner">{error}<button onClick={() => setError("")}>×</button></div>}
          {analysis ? <AnalysisChart data={analysis} layers={layers} levelVisibility={levelVisibility} signalAuditMode={signalAuditMode} selectedSignal={selectedSignal} onSignalSelect={setSelectedSignal} /> : <div className="loading-state">加载行情…</div>}
          {loading && <div className="busy-line" />}
        </main>

        {analysis && <EvidencePanel data={analysis} activeLevel={viewLevel} selectedSignal={selectedSignal} />}
      </div>
    </div>
  );
}
