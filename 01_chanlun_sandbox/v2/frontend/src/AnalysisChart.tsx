import { useEffect, useRef } from "react";
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
  CrossLevelEvent,
  StructureComparison,
  StructureScope,
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
  rangeStart: string;
  rangeEnd: string;
  onRangeChange?: (start: string, end: string) => void;
  onSignalSelect?: (signal: ChanSignal) => void;
  onCrossLevelSelect?: (event: CrossLevelEvent) => void;
  onLineSelect?: (line: ChanLine, scope: StructureScope) => void;
  signalAuditMode?: "confirmed" | "all" | "questionable";
  includeInvalidated?: boolean;
  experimentalComparison?: boolean;
  selectedSignal?: ChanSignal | null;
  selectedCrossLevel?: CrossLevelEvent | null;
  selectedComparison?: StructureComparison | null;
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

function nextTradingDate(date: string): string {
  const next = new Date(`${date}T00:00:00Z`);
  do {
    next.setUTCDate(next.getUTCDate() + 1);
  } while (next.getUTCDay() === 0 || next.getUTCDay() === 6);
  return next.toISOString().slice(0, 10);
}

function futureSessionTimes(times: string[]): string[] {
  const last = times[times.length - 1];
  if (!last || last.slice(11, 16) < "15:00") return [];
  const lastDate = last.slice(0, 10);
  const nextDate = nextTradingDate(lastDate);
  return times
    .filter((time) => time.slice(0, 10) === lastDate)
    .map((time) => `${nextDate}T${time.slice(11)}`);
}

function rangeIndex(times: string[], date: string, edge: "start" | "end"): number {
  if (!date) return edge === "start" ? 0 : Math.max(0, times.length - 1);
  const target = `${date}T${edge === "start" ? "00:00:00" : "23:59:59"}`;
  if (edge === "start") {
    const found = times.findIndex((time) => time >= target);
    return found < 0 ? Math.max(0, times.length - 1) : found;
  }
  for (let index = times.length - 1; index >= 0; index -= 1) {
    if (times[index] <= target) return index;
  }
  return 0;
}

function alignStepSeries(
  targetTimes: string[],
  sourceTimes: string[],
  sourceValues: Array<number | null>,
): Array<number | null> {
  let sourceIndex = -1;
  return targetTimes.map((time) => {
    while (sourceIndex + 1 < sourceTimes.length && sourceTimes[sourceIndex + 1] <= time) {
      sourceIndex += 1;
    }
    return sourceIndex >= 0 ? sourceValues[sourceIndex] ?? null : null;
  });
}

function linePath(
  lines: ChanLine[],
  nearest: (time: string) => string,
  sure: boolean,
  scope: StructureScope,
) {
  const selected = lines.filter((line) => line.is_sure === sure);
  if (!selected.length) return [];
  const points: Array<{ value: [string, number]; structureLine: { line: ChanLine; scope: StructureScope } } | null> = [];
  for (const line of selected) {
    const structureLine = { line, scope };
    points.push(
      { value: [nearest(line.start_at), line.start_price], structureLine },
      { value: [nearest(line.end_at), line.end_price], structureLine },
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
  rangeStart,
  rangeEnd,
  onRangeChange,
  onSignalSelect,
  onCrossLevelSelect,
  onLineSelect,
  signalAuditMode = "confirmed",
  includeInvalidated = false,
  experimentalComparison = false,
  selectedSignal = null,
  selectedCrossLevel = null,
  selectedComparison = null,
}: Props) {
  const elementRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<EChartsType | null>(null);
  const signalSelectRef = useRef(onSignalSelect);
  const crossLevelSelectRef = useRef(onCrossLevelSelect);
  const lineSelectRef = useRef(onLineSelect);
  const structureSelectionRef = useRef<Array<{ line: ChanLine; scope: StructureScope }>>([]);
  const rangeChangeRef = useRef(onRangeChange);
  const zoomAxisRef = useRef<{ times: string[]; lastActualIndex: number }>({ times: [], lastActualIndex: 0 });
  const emittedRangeRef = useRef("");

  useEffect(() => { signalSelectRef.current = onSignalSelect; }, [onSignalSelect]);
  useEffect(() => { crossLevelSelectRef.current = onCrossLevelSelect; }, [onCrossLevelSelect]);
  useEffect(() => { lineSelectRef.current = onLineSelect; }, [onLineSelect]);
  useEffect(() => { rangeChangeRef.current = onRangeChange; }, [onRangeChange]);

  useEffect(() => {
    if (!elementRef.current) return;
    const chart = echarts.init(elementRef.current, undefined, { renderer: "canvas" });
    chartRef.current = chart;
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(elementRef.current);
    const click = (params: any) => {
      if (params?.data?.chanSignal) signalSelectRef.current?.(params.data.chanSignal as ChanSignal);
      if (params?.data?.crossLevelEvent) crossLevelSelectRef.current?.(params.data.crossLevelEvent as CrossLevelEvent);
      if (params?.data?.structureLine) {
        const selection = params.data.structureLine as { line: ChanLine; scope: StructureScope };
        lineSelectRef.current?.(selection.line, selection.scope);
        return;
      }
      if (params?.seriesId === "structure-selection" && typeof params?.dataIndex === "number") {
        const selection = structureSelectionRef.current[params.dataIndex];
        if (selection) lineSelectRef.current?.(selection.line, selection.scope);
      }
    };
    const dataZoom = () => {
      const current = (chart.getOption() as any)?.dataZoom?.[0];
      if (typeof current?.start !== "number" || typeof current?.end !== "number") return;
      const { times, lastActualIndex } = zoomAxisRef.current;
      if (!times.length) return;
      const lastAxisIndex = Math.max(1, times.length - 1);
      const startIndex = Math.min(lastActualIndex, Math.max(0, Math.round(lastAxisIndex * current.start / 100)));
      const endIndex = Math.min(lastActualIndex, Math.max(startIndex, Math.round(lastAxisIndex * current.end / 100)));
      const nextRange = `${times[startIndex].slice(0, 10)}|${times[endIndex].slice(0, 10)}`;
      if (emittedRangeRef.current === nextRange) return;
      emittedRangeRef.current = nextRange;
      rangeChangeRef.current?.(times[startIndex].slice(0, 10), times[endIndex].slice(0, 10));
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
    const barTimes = data.bars.map((bar) => bar.time);
    const times = [...barTimes, ...futureSessionTimes(barTimes)];
    const nearest = buildNearestTime(barTimes);
    const timeIndex = new Map(barTimes.map((time, index) => [time, index]));
    const execution = data.chan.execution;
    const decision = data.chan.decision;
    const higher = data.chan.higher;
    const selectedEvidence = (selectedSignal?.evidence || {}) as Record<string, any>;
    const selectedReference = selectedEvidence.reference as Record<string, any> | undefined;
    const selectedTest = selectedEvidence.test as Record<string, any> | undefined;
    const comparisonReference = selectedComparison?.reference || selectedReference;
    const comparisonTest = selectedComparison?.test || selectedTest;
    const selectedCenter = selectedEvidence.center as ChanCenter | undefined;
    const selectedCenterArea = selectedSignal && selectedCenter ? [[
      {
        name: "所属中枢",
        xAxis: nearest(selectedCenter.start_at),
        yAxis: selectedCenter.zd,
        itemStyle: { color: "rgba(31,157,114,.12)", borderColor: "#1f9d72", borderWidth: 2 },
        label: { show: true, color: "#177759", fontSize: 10, formatter: "所属中枢" },
      },
      { xAxis: nearest(selectedCenter.end_at), yAxis: selectedCenter.zg },
    ]] : [];
    const comparisonAreas = selectedSignal || selectedComparison ? [
      ...(comparisonReference ? [[
        { xAxis: nearest(comparisonReference.startTime), itemStyle: { color: "rgba(47,127,193,.10)" } },
        { xAxis: nearest(comparisonReference.endTime) },
      ]] : []),
      ...(comparisonTest ? [[
        { xAxis: nearest(comparisonTest.startTime), itemStyle: { color: "rgba(229,138,43,.11)" } },
        { xAxis: nearest(comparisonTest.endTime) },
      ]] : []),
    ] : [];

    const areas = [
      ...(layers.executionCenters && levelVisibility["5m"]
        ? centerAreas(execution.centers, nearest, layers.centerHistory, 4, "rgba(245,158,11,.09)", "rgba(245,158,11,.68)")
        : []),
      ...(layers.executionSegmentCenters && levelVisibility["5m"]
        ? centerAreas(execution.segment_centers, nearest, layers.centerHistory, 3, "rgba(194,65,12,.09)", "rgba(194,65,12,.76)")
        : []),
      ...(layers.decisionCenters && levelVisibility["30m"]
        ? centerAreas(decision.centers, nearest, layers.centerHistory, 4, "rgba(14,165,233,.09)", "rgba(14,165,233,.68)")
        : []),
      ...(layers.decisionSegmentCenters && levelVisibility["30m"]
        ? centerAreas(decision.segment_centers, nearest, layers.centerHistory, 3, "rgba(29,78,216,.09)", "rgba(29,78,216,.78)")
        : []),
      ...(layers.higherCenters && levelVisibility["1d"]
        ? centerAreas(higher.centers, nearest, layers.centerHistory, 2, "rgba(126,82,153,.08)", "rgba(126,82,153,.62)")
        : []),
      ...selectedCenterArea,
      ...comparisonAreas,
    ];

    const lastIndex = Math.max(0, barTimes.length - 1);
    const lastAxisIndex = Math.max(1, times.length - 1);
    const rangeStartIndex = rangeIndex(barTimes, rangeStart, "start");
    const rangeEndIndex = Math.max(rangeStartIndex, rangeIndex(barTimes, rangeEnd, "end"));
    const zoomStart = rangeStartIndex / lastAxisIndex * 100;
    const zoomEnd = rangeEndIndex / lastAxisIndex * 100;
    zoomAxisRef.current = { times, lastActualIndex: lastIndex };
    emittedRangeRef.current = `${barTimes[rangeStartIndex].slice(0, 10)}|${barTimes[rangeEndIndex].slice(0, 10)}`;
    const visibleStartIndex = Math.min(lastIndex, rangeStartIndex);
    const visibleEndIndex = Math.min(lastIndex, rangeEndIndex);
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
      if (signal.lifecycle.state === "invalidated") return includeInvalidated;
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
    const crossLevelData = data.cross_level.events
      .filter((event) => event.lifecycle.state !== "invalidated" || includeInvalidated)
      .map((event) => {
        const plotAt = event.lifecycle.confirmed_at || event.lifecycle.triggered_at || event.lifecycle.detected_at;
        const mappedTime = nearest(plotAt);
        const index = timeIndex.get(mappedTime);
        if (index === undefined || index <= firstSignalIndex || index > visibleEndIndex) return null;
        const up = event.direction === "up";
        const state = event.lifecycle.state;
        const stateText = state === "confirmed" ? "确认" : state === "triggered" ? "触发" : state === "invalidated" ? "失效" : "候选";
        const color = state === "invalidated" ? "#8a96a3" : state === "triggered" ? "#d08723" : up ? "#177759" : "#af3745";
        return {
          value: [mappedTime, data.bars[index].close],
          crossLevelEvent: event,
          symbol: state === "confirmed" ? "diamond" : "circle",
          symbolSize: state === "confirmed" ? 20 : 15,
          itemStyle: { color, borderColor: "#ffffff", borderWidth: 1.5 },
          label: {
            show: showLabels,
            formatter: `5→30${up ? "B" : "S"}·${stateText}`,
            position: up ? "bottom" : "top",
            distance: 5,
            color,
            backgroundColor: "rgba(255,255,255,.96)",
            borderColor: color,
            borderWidth: 1,
            borderRadius: 3,
            padding: [2, 4],
            fontSize: 10,
          },
        };
      })
      .filter(Boolean);

    const dayStarts = barTimes.filter((time, index) => index > 0 && time.slice(0, 10) !== barTimes[index - 1].slice(0, 10));
    const allDays = [barTimes[0], ...dayStarts];
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
    const higherMacd = data.indicators.higher_macd;
    const higherHistogram = alignStepSeries(barTimes, higherMacd.times, higherMacd.histogram);
    const currentMacdScale = Math.max(
      1,
      ...macd.histogram.slice(visibleStartIndex, visibleEndIndex + 1).map((value) => Math.abs(value || 0)),
      ...macd.dif.slice(visibleStartIndex, visibleEndIndex + 1).map((value) => Math.abs(value || 0)),
      ...macd.dea.slice(visibleStartIndex, visibleEndIndex + 1).map((value) => Math.abs(value || 0)),
    );
    const higherMacdScale = Math.max(
      1,
      ...higherHistogram.slice(visibleStartIndex, visibleEndIndex + 1).map((value) => Math.abs(value || 0)),
    );
    const higherBackgroundScale = currentMacdScale * .72 / higherMacdScale;
    const higherBackground = higherHistogram.map((value) => value === null ? null : value * higherBackgroundScale);

    const lineSeries = (
      name: string,
      lines: ChanLine[],
      visible: boolean,
      color: string,
      width: number,
      scope: StructureScope,
      type: "solid" | "dashed" | "dotted" = "solid",
      z = 4,
    ) => visible ? [
      {
        name,
        type: "line",
        data: linePath(lines, nearest, true, scope),
        showSymbol: false,
        connectNulls: false,
        triggerLineEvent: experimentalComparison,
        cursor: experimentalComparison ? "pointer" : "default",
        lineStyle: { color, width, type },
        itemStyle: { color: "#ffffff", borderColor: color, borderWidth: 2 },
        emphasis: experimentalComparison ? { lineStyle: { width: width + 1.4 } } : { disabled: true },
        z,
      },
      {
        name: `${name}（未确认）`,
        type: "line",
        data: linePath(lines, nearest, false, scope),
        showSymbol: true,
        symbolSize: 4,
        triggerLineEvent: experimentalComparison,
        cursor: experimentalComparison ? "pointer" : "default",
        lineStyle: { color, width, type: "dotted", opacity: .7 },
        itemStyle: { color },
        emphasis: experimentalComparison ? { lineStyle: { width: width + 1.4 } } : { disabled: true },
        z,
      },
    ] : [];

    const lineSelectionData = (
      lines: ChanLine[],
      scope: StructureScope,
      color: string,
    ) => lines.map((line) => {
      const startIndex = timeIndex.get(nearest(line.start_at)) ?? 0;
      const endIndex = timeIndex.get(nearest(line.end_at)) ?? startIndex;
      const middleIndex = Math.max(0, Math.min(lastIndex, Math.round((startIndex + endIndex) / 2)));
      const progress = endIndex === startIndex ? .5 : (middleIndex - startIndex) / (endIndex - startIndex);
      return {
        value: [barTimes[middleIndex], line.start_price + (line.end_price - line.start_price) * progress],
        structureLine: { line, scope },
        symbol: scope === "segment" ? "diamond" : "circle",
        symbolSize: scope === "segment" ? 11 : 8,
        itemStyle: { color: "#ffffff", borderColor: color, borderWidth: 2 },
      };
    });

    const structureSelectionData = experimentalComparison ? [
      ...(layers.executionStrokes && levelVisibility["5m"] ? lineSelectionData(execution.strokes, "stroke", "#f59e0b") : []),
      ...(layers.executionSegments && levelVisibility["5m"] ? lineSelectionData(execution.segments, "segment", "#c2410c") : []),
      ...(layers.decisionStrokes && levelVisibility["30m"] ? lineSelectionData(decision.strokes, "stroke", "#0ea5e9") : []),
      ...(layers.decisionSegments && levelVisibility["30m"] ? lineSelectionData(decision.segments, "segment", "#1d4ed8") : []),
      ...(layers.higherStrokes && levelVisibility["1d"] ? lineSelectionData(higher.strokes, "stroke", "#84548f") : []),
      ...(layers.higherSegments && levelVisibility["1d"] ? lineSelectionData(higher.segments, "segment", "#63366e") : []),
    ] : [];
    structureSelectionRef.current = structureSelectionData.map(({ structureLine }) => structureLine);

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
        { type: "inside", xAxisIndex: [0, 1, 2], start: zoomStart, end: zoomEnd, minValueSpan: 20, filterMode: "none" },
        { type: "slider", xAxisIndex: [0, 1, 2], bottom: 5, height: 18, start: zoomStart, end: zoomEnd, filterMode: "none", borderColor: "#d6dde5", fillerColor: "rgba(42,99,139,.12)", showDetail: false },
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
        ...lineSeries("5m笔", execution.strokes, layers.executionStrokes && levelVisibility["5m"], "#f59e0b", 1.5, "stroke"),
        ...lineSeries("5m线段", execution.segments, layers.executionSegments && levelVisibility["5m"], "#c2410c", 2.8, "segment", "dashed", 5),
        ...lineSeries("30m笔", decision.strokes, layers.decisionStrokes && levelVisibility["30m"], "#0ea5e9", 1.6, "stroke"),
        ...lineSeries("30m线段", decision.segments, layers.decisionSegments && levelVisibility["30m"], "#1d4ed8", 3, "segment", "dashed", 5),
        ...lineSeries("日线笔", higher.strokes, layers.higherStrokes && levelVisibility["1d"], "#84548f", 1.65, "stroke", "dotted"),
        ...lineSeries("日线线段", higher.segments, layers.higherSegments && levelVisibility["1d"], "#63366e", 2.5, "segment"),
        experimentalComparison && {
          id: "structure-selection",
          name: "",
          type: "scatter",
          data: structureSelectionData,
          cursor: "pointer",
          tooltip: { show: false },
          emphasis: { scale: 1.35 },
          z: 18,
        },
        layers.signals && { name: "笔买卖点", type: "scatter", data: penSignalData, labelLayout: { hideOverlap: true }, cursor: "pointer", z: 9 },
        layers.segmentSignals && { name: "段买卖点", type: "scatter", data: segmentSignalData, labelLayout: { hideOverlap: true }, cursor: "pointer", z: 10 },
        layers.crossLevel && { name: "5m→30m转折", type: "scatter", data: crossLevelData, labelLayout: { hideOverlap: true }, cursor: "pointer", z: 12 },
        comparisonReference && {
          name: "对照段高亮", type: "line", data: [
            [nearest(comparisonReference.startTime), comparisonReference.startValue],
            [nearest(comparisonReference.endTime), comparisonReference.endValue],
          ], showSymbol: false, silent: true, lineStyle: { color: "#2f7fc1", width: 4 }, z: 20,
        },
        comparisonTest && {
          name: "检验段高亮", type: "line", data: [
            [nearest(comparisonTest.startTime), comparisonTest.startValue],
            [nearest(comparisonTest.endTime), comparisonTest.endValue],
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
        layers.macd && {
          name: `${higherMacd.level} MACD面积`,
          type: "bar",
          xAxisIndex: 2,
          yAxisIndex: 2,
          data: higherBackground.map((value) => ({ value, itemStyle: { color: (value || 0) >= 0 ? "rgba(217,71,79,.075)" : "rgba(30,154,112,.075)" } })),
          barWidth: "92%",
          silent: true,
          z: 0,
        },
        layers.macd && { name: "MACD", type: "bar", xAxisIndex: 2, yAxisIndex: 2, data: macd.histogram.map((value) => ({ value, itemStyle: { color: (value || 0) >= 0 ? "rgba(217,71,79,.58)" : "rgba(30,154,112,.58)" } })), barWidth: "42%", barGap: "-100%", markLine: dateMarkLine, z: 2 },
        layers.macd && { name: "DIF", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: macd.dif, showSymbol: false, lineStyle: { width: 1, color: "#2a7fb8" } },
        layers.macd && { name: "DEA", type: "line", xAxisIndex: 2, yAxisIndex: 2, data: macd.dea, showSymbol: false, lineStyle: { width: 1, color: "#e08b35" } },
      ].filter(Boolean),
    }, true);
  }, [data, layers, levelVisibility, rangeStart, rangeEnd, signalAuditMode, includeInvalidated, experimentalComparison, selectedSignal, selectedCrossLevel, selectedComparison]);

  return <div ref={elementRef} className="analysis-chart" aria-label="缠论多层级行情图" />;
}
