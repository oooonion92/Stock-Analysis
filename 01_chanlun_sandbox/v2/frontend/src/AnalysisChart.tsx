import { useEffect, useRef, useState } from "react";
import * as echarts from "echarts/core";
import { BarChart, CandlestickChart, LineChart, ScatterChart } from "echarts/charts";
import {
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
} from "echarts/components";
import { CanvasRenderer } from "echarts/renderers";
import type { EChartsType } from "echarts/core";
import type {
  AnalysisResponse,
  ChanCenter,
  ChanLine,
  ChanSignal,
} from "./types";

echarts.use([
  BarChart,
  CandlestickChart,
  LineChart,
  ScatterChart,
  AxisPointerComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  MarkLineComponent,
  TooltipComponent,
  CanvasRenderer,
]);

interface Props {
  data: AnalysisResponse;
  layers: Record<string, boolean>;
  levelVisibility: Record<string, boolean>;
  onSignalSelect?: (signal: ChanSignal) => void;
  signalAuditMode?: "confirmed" | "all" | "questionable";
  selectedSignal?: ChanSignal | null;
}

function buildNearestTime(times: string[]) {
  const exact = new Set(times);
  const millis = times.map((time) => new Date(time).getTime());
  return (time: string): string => {
    if (exact.has(time)) return time;
    const target = new Date(time).getTime();
    let low = 0;
    let high = millis.length - 1;
    while (low < high) {
      const middle = Math.floor((low + high) / 2);
      if (millis[middle] < target) low = middle + 1;
      else high = middle;
    }
    if (low === 0) return times[0];
    return target - millis[low - 1] <= millis[low] - target ? times[low - 1] : times[low];
  };
}

function linePath(lines: ChanLine[], nearest: (time: string) => string, sure: boolean) {
  const selected = lines.filter((line) => line.is_sure === sure);
  if (!selected.length) return [];
  const points: Array<[string, number] | null> = [];
  for (const line of selected) {
    points.push(
      [nearest(line.start_at), line.start_price],
      [nearest(line.end_at), line.end_price],
      null,
    );
  }
  return points;
}

function centerAreas(
  centers: ChanCenter[],
  nearest: (time: string) => string,
  history: boolean,
  limit: number,
  fill: string,
  border: string,
) {
  const selected = history ? centers : centers.slice(-limit);
  return selected.map((center) => [
    {
      xAxis: nearest(center.start_at),
      yAxis: center.zd,
      itemStyle: { color: fill, borderColor: border, borderWidth: 1 },
    },
    { xAxis: nearest(center.end_at), yAxis: center.zg },
  ]);
}

function signalAuditVisible(signal: ChanSignal, mode: "confirmed" | "all" | "questionable") {
  const evidence = signal.evidence as Record<string, any>;
  const divergenceConfirmed = evidence.comparison_kind !== "divergence"
    || evidence.divergence_audit?.status === "confirmed";
  const dependencyConfirmed = !evidence.dependency?.required
    || evidence.dependency?.status === "confirmed";
  const confirmed = divergenceConfirmed && dependencyConfirmed && signal.lifecycle.state === "confirmed";
  if (mode === "confirmed") return confirmed;
  if (mode === "questionable") return !confirmed;
  return true;
}

export default function AnalysisChart({
  data,
  layers,
  levelVisibility,
  onSignalSelect,
  signalAuditMode = "confirmed",
  selectedSignal = null,
}: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const signalSelectRef = useRef(onSignalSelect);
  const [zoomWindow, setZoomWindow] = useState<{ start: number; end: number } | null>(null);

  useEffect(() => { signalSelectRef.current = onSignalSelect; }, [onSignalSelect]);

  useEffect(() => {
    if (!elementRef.current) return;
    const chart = echarts.init(elementRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(elementRef.current);
    const click = (params: any) => {
      if (params?.data?.chanSignal) signalSelectRef.current?.(params.data.chanSignal as ChanSignal);
    };
    const dataZoom = () => {
      const current = (chart.getOption() as any)?.dataZoom?.[0];
      if (typeof current?.start !== "number" || typeof current?.end !== "number") return;
      setZoomWindow((previous) => {
        if (previous && Math.abs(previous.start - current.start) < .05 && Math.abs(previous.end - current.end) < .05) return previous;
        return { start: current.start, end: current.end };
      });
    };
    chart.on("click", click);
    chart.on("datazoom", dataZoom);
    return () => {
      observer.disconnect();
      chart.off("click", click);
      chart.off("datazoom", dataZoom);
      chart.dispose();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart || !data.bars.length) return;

    const showLabels = chart.getWidth() >= 720;
    const times = data.bars.map((bar) => bar.time);
    const nearest = buildNearestTime(times);
    const timeIndex = new Map(times.map((time, index) => [time, index]));
    const execution = data.chan.execution;
    const decision = data.chan.decision;
    const higher = data.chan.higher;
    const selectedEvidence = (selectedSignal?.evidence || {}) as Record<string, any>;
    const selectedReference = selectedEvidence.reference as Record<string, any> | undefined;
    const selectedTest = selectedEvidence.test as Record<string, any> | undefined;
    const comparisonAreas = selectedSignal ? [
      ...(selectedReference ? [[
        { xAxis: nearest(selectedReference.startTime), itemStyle: { color: "rgba(47,127,193,.10)" } },
        { xAxis: nearest(selectedReference.endTime) },
      ]] : []),
      ...(selectedTest ? [[
        { xAxis: nearest(selectedTest.startTime), itemStyle: { color: "rgba(229,138,43,.11)" } },
        { xAxis: nearest(selectedTest.endTime) },
      ]] : []),
    ] : [];

    const areas = [
      ...(layers.executionCenters && levelVisibility["5m"]
        ? centerAreas(execution.centers, nearest, layers.centerHistory, 4, "rgba(64,136,205,.09)", "rgba(64,136,205,.58)")
        : []),
      ...(layers.executionSegmentCenters && levelVisibility["5m"]
        ? centerAreas(execution.segment_centers, nearest, layers.centerHistory, 3, "rgba(229,138,43,.09)", "rgba(224,160,94,.68)")
        : []),
      ...(layers.decisionCenters && levelVisibility["30m"]
        ? centerAreas(decision.centers, nearest, layers.centerHistory, 4, "rgba(64,136,205,.09)", "rgba(64,136,205,.58)")
        : []),
      ...(layers.decisionSegmentCenters && levelVisibility["30m"]
        ? centerAreas(decision.segment_centers, nearest, layers.centerHistory, 3, "rgba(229,138,43,.09)", "rgba(224,160,94,.68)")
        : []),
      ...(layers.higherCenters && levelVisibility["1d"]
        ? centerAreas(higher.centers, nearest, layers.centerHistory, 2, "rgba(126,82,153,.08)", "rgba(126,82,153,.62)")
        : []),
      ...comparisonAreas,
    ];

    const startPercent = data.bars.length > 480 ? Math.max(0, 100 - (480 / data.bars.length) * 100) : 0;
    const existingZoom = (chart.getOption() as any)?.dataZoom?.[0];
    const zoomStart = zoomWindow?.start ?? (typeof existingZoom?.start === "number" ? existingZoom.start : startPercent);
    const zoomEnd = zoomWindow?.end ?? (typeof existingZoom?.end === "number" ? existingZoom.end : 100);
    const lastIndex = Math.max(0, times.length - 1);
    const visibleStartIndex = Math.max(0, Math.floor(lastIndex * zoomStart / 100));
    const visibleEndIndex = Math.min(lastIndex, Math.ceil(lastIndex * zoomEnd / 100));
    const visibleSpan = Math.max(1, visibleEndIndex - visibleStartIndex + 1);
    const visibleBars = data.bars.slice(visibleStartIndex, visibleEndIndex + 1);
    const visibleLow = Math.min(...visibleBars.map((bar) => bar.low));
    const visibleHigh = Math.max(...visibleBars.map((bar) => bar.high));
    const rawPriceSpan = visibleHigh - visibleLow;
    const priceSpan = rawPriceSpan > 0 ? rawPriceSpan : Math.max(Math.abs(visibleHigh) * .01, 1);
    const pricePadding = priceSpan * .045;
    const priceAxisMin = visibleLow - pricePadding;
    const priceAxisMax = visibleHigh + pricePadding;
    const priceAxisDecimals = visibleHigh >= 1000 ? 0 : visibleHigh >= 100 ? 1 : visibleHigh >= 10 ? 2 : 3;
    const formatPriceAxis = (value: number) => value.toLocaleString("zh-CN", {
      minimumFractionDigits: priceAxisDecimals,
      maximumFractionDigits: priceAxisDecimals,
    });
    const leftSignalGuard = visibleSpan >= 120 ? Math.max(3, Math.ceil(visibleSpan * .02)) : 0;
    const firstSignalIndex = visibleStartIndex + leftSignalGuard;

    const signalPool = [
      ...(levelVisibility["5m"] ? execution.signal_history : []),
      ...(levelVisibility["30m"] ? decision.signal_history : []),
      ...(levelVisibility["1d"] ? higher.signal_history : []),
    ].filter((signal) => {
      if (!signalAuditVisible(signal, signalAuditMode)) return false;
      const eventAt = signal.lifecycle.event_at;
      if (eventAt < times[0] || eventAt > times[lastIndex]) return false;
      const index = timeIndex.get(nearest(eventAt));
      return index !== undefined && index > firstSignalIndex && index <= visibleEndIndex;
    });
    const visibleLevelCount = Object.values(levelVisibility).filter(Boolean).length;
    const buildSignalData = (scope: "stroke" | "segment") => signalPool
      .filter((signal) => signal.evidence.scope === scope)
      .map((signal) => {
      const buy = signal.side ? signal.side === "buy" : signal.label.endsWith("B");
      const display = signal.display_label || `${scope === "segment" ? "段" : "笔"}${signal.label}`;
      const baseLevel = signal.level.replace("段", "");
      return {
        value: [nearest(signal.lifecycle.event_at), signal.price],
        chanSignal: signal,
        symbol: buy ? "triangle" : "pin",
        symbolSize: scope === "segment" ? 22 : 18,
        itemStyle: {
          color: buy ? "#1f9d72" : "#d95262",
          borderColor: "#ffffff",
          borderWidth: 1,
        },
        label: {
          show: showLabels,
          formatter: visibleLevelCount > 1 ? `${baseLevel}·${display}` : display,
          position: buy ? "bottom" : "top",
          distance: 5,
          color: buy ? "#177759" : "#af3745",
          backgroundColor: "rgba(255,255,255,.95)",
          borderColor: buy ? "#83cbb4" : "#e7a4ad",
          borderWidth: 1,
          borderRadius: 3,
          padding: [2, 4],
          fontSize: 10,
        },
      };
    });
    const penSignalData = buildSignalData("stroke");
    const segmentSignalData = buildSignalData("segment");

    const dayStarts = times.filter((time, index) => index > 0 && time.slice(0, 10) !== times[index - 1].slice(0, 10));
    const allDays = [times[0], ...dayStarts];
    const maxLabels = Math.max(3, Math.floor(chart.getWidth() / 76));
    const labelStride = Math.max(1, Math.ceil(allDays.length / maxLabels));
    const dayLabels = new Set(allDays.filter((_time, index) => index % labelStride === 0 || index === allDays.length - 1));
    const dateMarkLine = {
      silent: true,
      symbol: ["none", "none"],
      label: { show: false },
      lineStyle: { color: "#cbd5df", type: "dashed", width: 1 },
      data: dayStarts.map((time) => ({ xAxis: time })),
    };
    const macd = data.indicators.macd;

    const lineSeries = (
      name: string,
      lines: ChanLine[],
      visible: boolean,
      color: string,
      width: number,
      type: "solid" | "dashed" | "dotted" = "solid",
      z = 4,
    ) => visible ? [
      {
        name,
        type: "line",
        data: linePath(lines, nearest, true),
        showSymbol: false,
        connectNulls: false,
        lineStyle: { color, width, type },
        z,
      },
      {
        name: `${name}（未确认）`,
        type: "line",
        data: linePath(lines, nearest, false),
        showSymbol: true,
        symbolSize: 4,
        lineStyle: { color, width, type: "dotted", opacity: .7 },
        itemStyle: { color },
        z,
      },
    ] : [];

    chart.setOption({
      animation: false,
      backgroundColor: "#ffffff",
      legend: {
        top: 3,
        right: 16,
        itemWidth: 14,
        itemHeight: 6,
        textStyle: { color: "#5c6978", fontSize: 9 },
      },
      axisPointer: { link: [{ xAxisIndex: [0, 1, 2] }], label: { backgroundColor: "#344254" } },
      tooltip: {
        trigger: "axis",
        axisPointer: { type: "cross" },
        borderColor: "#cbd3dc",
        textStyle: { color: "#17202b", fontSize: 11 },
        backgroundColor: "rgba(255,255,255,.97)",
      },
      grid: [
        { left: 58, right: 18, top: 30, height: "59%" },
        { left: 58, right: 18, top: "65%", height: "11%" },
        { left: 58, right: 18, top: "79%", height: "13%" },
      ],
      xAxis: [0, 1, 2].map((index) => ({
        type: "category",
        data: times,
        gridIndex: index,
        boundaryGap: true,
        axisLine: { lineStyle: { color: "#b9c3cf" } },
        axisTick: { show: false },
        axisLabel: {
          show: index === 2,
          interval: (_axisIndex: number, value: string) => dayLabels.has(value),
          color: "#647286",
          fontSize: 10,
          formatter: (value: string) => value.slice(5, 10),
        },
        splitLine: { show: false },
      })),
      yAxis: [
        {
          scale: true,
          min: priceAxisMin,
          max: priceAxisMax,
          gridIndex: 0,
          splitLine: { lineStyle: { color: "#e7ebef" } },
          axisLabel: { color: "#647286", fontSize: 10, formatter: formatPriceAxis },
        },
        { scale: true, gridIndex: 1, splitNumber: 2, axisLabel: { show: false }, splitLine: { show: false } },
        { scale: true, gridIndex: 2, splitNumber: 3, axisLabel: { color: "#647286", fontSize: 9 }, splitLine: { lineStyle: { color: "#edf1f5" } } },
      ],
      dataZoom: [
        { type: "inside", xAxisIndex: [0, 1, 2], start: zoomStart, end: zoomEnd, minValueSpan: 20 },
        { type: "slider", xAxisIndex: [0, 1, 2], bottom: 5, height: 18, start: zoomStart, end: zoomEnd, borderColor: "#d6dde5", fillerColor: "rgba(42,99,139,.12)", showDetail: false },
      ],
      series: [
        {
          name: "K线",
          type: "candlestick",
          xAxisIndex: 0,
          yAxisIndex: 0,
          data: data.bars.map((bar) => [bar.open, bar.close, bar.low, bar.high]),
          itemStyle: { color: "#d9474f", color0: "#1e9a70", borderColor: "#d9474f", borderColor0: "#1e9a70" },
          markArea: areas.length ? { silent: true, data: areas } : undefined,
          markLine: dateMarkLine,
          z: 2,
        },
        ...lineSeries("5m笔", execution.strokes, layers.executionStrokes && levelVisibility["5m"], "#2f7fc1", 1.6),
        ...lineSeries("5m线段", execution.segments, layers.executionSegments && levelVisibility["5m"], "#e58a2b", 2.2),
        ...lineSeries("30m笔", decision.strokes, layers.decisionStrokes && levelVisibility["30m"], "#2f7fc1", 1.6),
        ...lineSeries("30m线段", decision.segments, layers.decisionSegments && levelVisibility["30m"], "#e58a2b", 2.2),
        ...lineSeries("日线笔", higher.strokes, layers.higherStrokes && levelVisibility["1d"], "#84548f", 1.65, "dotted"),
        ...lineSeries("日线线段", higher.segments, layers.higherSegments && levelVisibility["1d"], "#63366e", 2.5),
        layers.signals && { name: "笔买卖点", type: "scatter", data: penSignalData, labelLayout: { hideOverlap: true }, cursor: "pointer", z: 9 },
        layers.segmentSignals && { name: "段买卖点", type: "scatter", data: segmentSignalData, labelLayout: { hideOverlap: true }, cursor: "pointer", z: 10 },
        selectedReference && {
          name: "对照段高亮", type: "line", data: [
            [nearest(selectedReference.startTime), selectedReference.startValue],
            [nearest(selectedReference.endTime), selectedReference.endValue],
          ], showSymbol: false, silent: true, lineStyle: { color: "#2f7fc1", width: 4 }, z: 20,
        },
        selectedTest && {
          name: "检验段高亮", type: "line", data: [
            [nearest(selectedTest.startTime), selectedTest.startValue],
            [nearest(selectedTest.endTime), selectedTest.endValue],
          ], showSymbol: false, silent: true, lineStyle: { color: "#e58a2b", width: 4 }, z: 21,
        },
        {
          name: "成交量",
          type: "bar",
          xAxisIndex: 1,
          yAxisIndex: 1,
          data: data.bars.map((bar) => ({ value: bar.volume, itemStyle: { color: bar.close >= bar.open ? "rgba(217,71,79,.52)" : "rgba(30,154,112,.52)" } })),
          markLine: dateMarkLine,
        },
        layers.macd && { name: "MACD", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: macd.histogram.map((value) => ({ value, itemStyle: { color: (value || 0) >= 0 ? "rgba(217,71,79,.55)" : "rgba(30,154,112,.55)" } })), markLine: dateMarkLine },
        layers.macd && { name: "DIF", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: macd.dif, showSymbol: false, lineStyle: { width: 1, color: "#2a7fb8" } },
        layers.macd && { name: "DEA", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: macd.dea, showSymbol: false, lineStyle: { width: 1, color: "#e08b35" } },
      ].filter(Boolean),
    }, true);
  }, [data, layers, levelVisibility, signalAuditMode, selectedSignal, zoomWindow]);

  return <div ref={elementRef} className="analysis-chart" aria-label="缠论多层级行情图" />;
}
