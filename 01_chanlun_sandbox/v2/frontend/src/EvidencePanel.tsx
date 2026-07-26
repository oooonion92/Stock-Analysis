import { useEffect, useMemo, useState } from "react";
import type { AnalysisResponse, ChanSignal, CrossLevelEvent, StructureComparison } from "./types";

type Tab = "structure" | "signal" | "crossLevel" | "comparison";

const stateLabels: Record<string, string> = {
  insufficient_structure: "结构不足",
  trend_up: "向上走势",
  trend_down: "向下走势",
  center_balance: "中枢震荡",
  balance: "平衡区内",
  up_leave: "向上离开中枢",
  down_leave: "向下离开中枢",
  up_leave_confirmed: "向上离开已确认",
  down_leave_confirmed: "向下离开已确认",
  active: "发展中",
  completed: "已完成",
  candidate: "候选",
  triggered: "已触发",
  confirmed: "已确认",
  invalidated: "已失效",
  expired: "已过期",
  risk_downgraded: "风险降级",
  pending: "等待关联一类点确认",
  missing: "缺少关联一类点",
  up: "向上",
  down: "向下",
  unknown: "未定",
  normal: "常规",
  reduced: "降低",
  research: "研究",
  none: "不参与",
};

const divergenceLabels: Record<string, string> = {
  trend_divergence: "趋势背驰",
  consolidation_divergence: "盘整背驰",
  structural_retest: "二类回撤",
  center_non_return: "三类不回中枢",
};

const auditLabels: Record<string, string> = {
  confirmed: "背驰确认",
  insufficient: "动力证据不足",
  unsupported: "不支持背驰",
  not_applicable: "非背驰型结构点",
};

function fmt(value: unknown, digits = 3): string {
  if (value === null || value === undefined || value === "") return "—";
  if (typeof value === "boolean") return value ? "是" : "否";
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(digits);
  const text = String(value);
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) return text.replace("T", " ").slice(0, 16);
  return stateLabels[text] || divergenceLabels[text] || auditLabels[text] || text;
}

function ratio(value: unknown): string {
  return typeof value === "number" ? `${value.toFixed(3)}×` : "—";
}

function structureDirection(state: unknown): string {
  const value = String(state || "");
  if (value.includes("up")) return "向上";
  if (value.includes("down")) return "向下";
  if (value.includes("balance") || value.includes("center")) return "震荡";
  return "未明确";
}

function levelRelation(activeState: unknown, contextState: unknown, conflicts: string[]): string {
  if (conflicts.length > 0) return "与上级别冲突";
  const activeDirection = structureDirection(activeState);
  const contextDirection = structureDirection(contextState);
  if (activeDirection === "未明确" || activeDirection === "震荡") return "当前方向未明确";
  if (contextDirection === "未明确" || contextDirection === "震荡") return "上级别方向未明确";
  return activeDirection === contextDirection ? "与上级别同向" : "与上级别冲突";
}

function EvidenceRows({ rows }: { rows: Array<[string, unknown]> }) {
  return (
    <dl className="evidence-list">
      {rows.map(([label, value]) => <div key={label}><dt>{label}</dt><dd>{fmt(value)}</dd></div>)}
    </dl>
  );
}

function compact(value: unknown): string {
  return typeof value === "number"
    ? new Intl.NumberFormat("zh-CN", { notation: "compact", maximumFractionDigits: 2 }).format(value)
    : "—";
}

function ComparisonTable({ reference, test, ratios, audit }: {
  reference?: Record<string, any> | null;
  test?: Record<string, any> | null;
  ratios: Record<string, any>;
  audit: Record<string, any>;
}) {
  if (!reference || !test) return <p className="empty">当前点没有可还原的对照段，只展示结构条件。</p>;
  const verdict = (value: unknown) => {
    if (typeof value !== "boolean") return { label: "—", className: "neutral" };
    return value
      ? { label: "背驰", className: "pass" }
      : { label: "无背驰", className: "fail" };
  };
  const rows = [
    { label: "时间", reference: `${fmt(reference.startTime)} 至 ${fmt(reference.endTime)}`, test: `${fmt(test.startTime)} 至 ${fmt(test.endTime)}`, ratio: "", verdict: verdict(null) },
    { label: "价格幅度", reference: fmt(reference.priceMove), test: fmt(test.priceMove), ratio: ratio(ratios.price_move), verdict: verdict(audit.price_extension) },
    { label: "MACD面积", reference: fmt(reference.macdArea), test: fmt(test.macdArea), ratio: ratio(ratios.macd_area), verdict: verdict(audit.macd_area_weakening) },
    { label: "MACD峰值", reference: fmt(reference.macdPeak), test: fmt(test.macdPeak), ratio: ratio(ratios.macd_peak), verdict: verdict(audit.macd_peak_weakening) },
    { label: "DIF极值", reference: fmt(reference.difExtreme), test: fmt(test.difExtreme), ratio: ratio(ratios.dif_extreme), verdict: verdict(audit.dif_weakening) },
    { label: "平均成交量", reference: compact(reference.volumeAverage), test: compact(test.volumeAverage), ratio: ratio(ratios.volume_average), verdict: verdict(audit.volume_contracting) },
  ];
  return (
    <table className="metric-table">
      <thead><tr><th>指标</th><th>对照段</th><th>检验段</th><th>比值</th><th>备注</th></tr></thead>
      <tbody>{rows.map((row) => (
        <tr key={row.label}>
          <td>{row.label}</td>
          <td>{row.reference}</td>
          <td>{row.test}</td>
          <td>{row.ratio}</td>
          <td className={`metric-verdict ${row.verdict.className}`}>{row.verdict.label}</td>
        </tr>
      ))}</tbody>
    </table>
  );
}

function ThirdPointEvidence({ structure, center }: {
  structure?: Record<string, any> | null;
  center?: Record<string, any> | null;
}) {
  if (!structure || !center) return <p className="empty">当前三类点没有可追溯的所属中枢。</p>;
  const departure = structure.departure || {};
  const retrace = structure.retrace || {};
  return (
    <>
      <p className="evidence-basis">{structure.rule}</p>
      <EvidenceRows rows={[
        ["中枢区间", `${fmt(center.start_at)} 至 ${fmt(center.end_at)}`],
        ["中枢下沿 ZD", center.zd],
        ["中枢上沿 ZG", center.zg],
        ["离开笔", `${fmt(departure.startTime)} ${fmt(departure.startValue)} → ${fmt(departure.endTime)} ${fmt(departure.endValue)}`],
        ["回踩 / 反抽笔", `${fmt(retrace.startTime)} ${fmt(retrace.startValue)} → ${fmt(retrace.endTime)} ${fmt(retrace.endValue)}`],
        ["检查边界", `${structure.center_boundary_name} ${fmt(structure.center_boundary)}`],
        ["回踩低点 / 反抽高点", structure.retrace_extreme],
        ["边界余量", structure.clearance],
        ["是否守住中枢", structure.holds_center],
      ]} />
    </>
  );
}

export default function EvidencePanel({
  data,
  activeLevel,
  selectedSignal,
  selectedCrossLevel,
  selectedComparison,
  experimentalComparison = false,
  onClearSelection,
}: {
  data: AnalysisResponse;
  activeLevel: "5m" | "30m";
  selectedSignal?: ChanSignal | null;
  selectedCrossLevel?: CrossLevelEvent | null;
  selectedComparison?: StructureComparison | null;
  experimentalComparison?: boolean;
  onClearSelection?: () => void;
}) {
  const [tab, setTab] = useState<Tab>("structure");
  const active = activeLevel === "5m" ? data.chan.execution : data.chan.decision;
  const context = activeLevel === "5m" ? data.chan.decision : data.chan.higher;
  const latestCenter = active.centers[active.centers.length - 1] || null;
  const signal = selectedSignal || active.signals[active.signals.length - 1] || null;
  const evidence = (signal?.evidence || {}) as Record<string, any>;
  const audit = (evidence.divergence_audit || {}) as Record<string, any>;
  const ratios = (evidence.ratios || {}) as Record<string, any>;
  const isThirdPoint = evidence.comparison_kind === "center_non_return";
  const crossLevel = selectedCrossLevel || data.cross_level.active[data.cross_level.active.length - 1] || data.cross_level.events[data.cross_level.events.length - 1] || null;
  const crossEvidence = (crossLevel?.evidence || {}) as Record<string, any>;
  const comparisonAudit = (selectedComparison?.audit || {}) as Record<string, any>;

  useEffect(() => {
    setTab(selectedSignal ? "signal" : "structure");
  }, [selectedSignal?.id]);

  useEffect(() => {
    if (selectedCrossLevel) setTab("crossLevel");
  }, [selectedCrossLevel?.id]);

  useEffect(() => {
    if (selectedComparison) setTab("comparison");
    else if (!experimentalComparison) setTab((current) => current === "comparison" ? "structure" : current);
  }, [selectedComparison?.id, experimentalComparison]);

  const recentSignals = useMemo(
    () => active.signals.slice(-8).reverse(),
    [active.signals],
  );
  return (
    <aside className="evidence-panel">
      <div className={`evidence-tabs ${experimentalComparison ? "four-tabs" : ""}`} role="tablist">
        <button className={tab === "structure" ? "active" : ""} onClick={() => setTab("structure")}>结构</button>
        <button className={tab === "signal" ? "active" : ""} onClick={() => {
          if (tab === "signal") {
            setTab("structure");
            onClearSelection?.();
          } else {
            setTab("signal");
          }
        }}>BS点</button>
        <button className={tab === "crossLevel" ? "active" : ""} onClick={() => setTab("crossLevel")}>小转大</button>
        {experimentalComparison && <button className={tab === "comparison" ? "active" : ""} onClick={() => {
          if (tab === "comparison") {
            setTab("structure");
            onClearSelection?.();
          } else {
            setTab("comparison");
          }
        }}>对比</button>}
      </div>

      <div className="evidence-content">
        {tab === "structure" && (
          <>
            <section>
              <div className="section-title-line">
                <h3>{active.level} 当前判断</h3>
                <span className="radar-version">chan.py {active.engine_commit.slice(0, 10)}</span>
              </div>
              <EvidenceRows rows={[
                ["结构状态", active.current.state],
                ["结构方向", structureDirection(active.current.state)],
                ["信号状态", signal?.lifecycle.state || "无活动信号"],
                ["级别关系", levelRelation(active.current.state, context.current.state, data.fusion.conflicts)],
                ["现价", active.current.price],
              ]} />
            </section>

            <section>
              <h3>关键边界</h3>
              <EvidenceRows rows={[
                ["中枢下沿 ZD", latestCenter?.zd],
                ["中枢上沿 ZG", latestCenter?.zg],
                ["确认端点", signal?.price],
                ["结构保护线", signal?.structure_guard ?? active.current.risk_line],
                ["信号风险线", signal?.risk_guard],
              ]} />
            </section>

            <section>
              <h3>条件式应对</h3>
              <div className="plan-block"><span>当前应对</span><p>{data.plan.action}</p></div>
              <div className="plan-block"><span>延续条件</span><p>{data.plan.trigger}</p></div>
              <div className="plan-block danger"><span>转折 / 失效</span><p>{data.plan.invalidation}</p></div>
              <div className="plan-block caution"><span>禁止</span><p>{data.plan.forbidden}</p></div>
              <div className="plan-block"><span>下一观察</span><p>{data.plan.next_observation}</p></div>
            </section>

            <section>
              <h3>{active.level} 最近中枢</h3>
              <EvidenceRows rows={[
                ["状态", latestCenter?.state],
                ["下沿 ZD", latestCenter?.zd],
                ["上沿 ZG", latestCenter?.zg],
                ["最低 DD", latestCenter?.dd],
                ["最高 GG", latestCenter?.gg],
                ["起点", latestCenter?.start_at],
                ["终点", latestCenter?.end_at],
                ["构成笔", latestCenter?.component_count],
                ["延伸笔", latestCenter?.extension_count],
              ]} />
            </section>

            <section>
              <h3>结构规模</h3>
              <EvidenceRows rows={[
                ["笔", active.summary.strokes],
                ["确认笔", active.summary.confirmed_strokes],
                ["线段", active.summary.segments],
                ["确认线段", active.summary.confirmed_segments],
                ["笔中枢", active.summary.centers],
                ["线段中枢", active.summary.segment_centers],
                ["当前有效 BS", active.summary.signals],
              ]} />
            </section>

            <section>
              <h3>{context.level} 上级背景</h3>
              <EvidenceRows rows={[
                ["状态", context.current.state],
                ["风险线", context.current.risk_line],
                ["笔", context.summary.strokes],
                ["线段", context.summary.segments],
                ["中枢", context.summary.centers],
              ]} />
            </section>
          </>
        )}

        {tab === "signal" && (
          <>
            {!signal && <p className="empty">当前可见区间没有已确认 BS 点。</p>}
            {signal && (
              <>
                <section>
                  <div className="section-title-line">
                    <h3>{signal.level.replace("段", "")} · {signal.display_label || signal.label}</h3>
                    <span className={`state-tag ${signal.lifecycle.state}`}>{fmt(signal.lifecycle.state)}</span>
                  </div>
                  <EvidenceRows rows={[
                    ["结构类型", signal.divergence_class],
                    ["事件位置", signal.lifecycle.event_at],
                    ["最早可见", signal.lifecycle.detected_at],
                    ["确认时间", signal.lifecycle.confirmed_at],
                    ["价格", signal.price],
                    ["结构失效线", signal.structure_guard],
                    ["风险线", signal.risk_guard],
                    ["原生类型", (evidence.native_types || []).join(" + ")],
                    ["判定层", evidence.scope === "segment" ? "线段" : "笔"],
                  ]} />
                </section>

                <section>
                  <h3>判定依据</h3>
                  <p className="evidence-basis">{evidence.basis || "由 chan.py 原生结构生成。"}</p>
                  {isThirdPoint
                    ? <EvidenceRows rows={[
                        ["判定方式", "离开中枢后的首次回踩 / 反抽"],
                        ["结构结论", evidence.third_structure?.holds_center ? "未返回中枢" : "已返回中枢"],
                        ["动力复核", "三类点不以背驰作为直接成立条件"],
                      ]} />
                    : <EvidenceRows rows={[
                        ["复核结论", audit.status],
                        ["价格创新值", audit.price_extension],
                        ["动力减弱票数", audit.momentum_votes],
                        ["所需票数", audit.required_votes],
                        ["减弱阈值", audit.weakening_ratio],
                        ["结论", audit.conclusion],
                      ]} />}
                </section>

                {evidence.dependency?.required && (
                  <section>
                    <h3>前序依赖</h3>
                    <EvidenceRows rows={[
                      ["关联一类点", evidence.dependency.parent_display_label],
                      ["一类点位置", evidence.dependency.parent_event_at],
                      ["一类点状态", evidence.dependency.parent_state],
                      ["依赖结论", evidence.dependency.status_label],
                    ]} />
                    <p className="evidence-basis">{evidence.dependency.conclusion}</p>
                  </section>
                )}

                <section>
                  <h3>{isThirdPoint ? "三类点结构验证" : "背驰区间对比"}</h3>
                  {isThirdPoint
                    ? <ThirdPointEvidence structure={evidence.third_structure} center={evidence.center} />
                    : <ComparisonTable reference={evidence.reference} test={evidence.test} ratios={ratios} audit={audit} />}
                </section>

                <section>
                  <h3>最近有效 BS 点</h3>
                  <div className="signal-list">
                    {recentSignals.map((item) => (
                      <div key={item.id} className={item.id === signal.id ? "active" : ""}>
                        <b>{item.level.replace("段", "")} · {item.display_label || item.label}</b>
                        <small>{fmt(item.lifecycle.event_at)} · {fmt(item.divergence_class)}</small>
                      </div>
                    ))}
                  </div>
                </section>
              </>
            )}
          </>
        )}

        {tab === "crossLevel" && (
          <>
            {!crossLevel && <p className="empty">当前历史中没有满足来源条件的5m→30m转折事件。</p>}
            {crossLevel && (
              <>
                <section>
                  <div className="section-title-line">
                    <h3>{crossLevel.label}</h3>
                    <span className={`state-tag ${crossLevel.lifecycle.state}`}>{fmt(crossLevel.lifecycle.state)}</span>
                  </div>
                  <EvidenceRows rows={[
                    ["来源信号", crossLevel.source_signal_label],
                    ["结构发生", crossLevel.lifecycle.event_at],
                    ["来源确认", crossLevel.lifecycle.detected_at],
                    ["5m突破触发", crossLevel.lifecycle.triggered_at],
                    ["30m收盘确认", crossLevel.lifecycle.confirmed_at],
                    ["失效时间", crossLevel.lifecycle.invalidated_at],
                    ["来源价格", crossLevel.source_price],
                    ["突破边界", crossLevel.break_boundary],
                    ["风险线", crossLevel.risk_guard],
                  ]} />
                </section>

                <section>
                  <h3>确认链</h3>
                  <p className="evidence-basis">{crossEvidence.rule}</p>
                  <EvidenceRows rows={[
                    ["边界类型", "已确认5m线段端点"],
                    ["边界形成", crossEvidence.break_boundary_pivot?.event_at],
                    ["边界确认", crossEvidence.break_boundary_pivot?.confirmed_at],
                    ["30m背景方向", crossEvidence.decision_context?.direction],
                    ["30m背景起点", crossEvidence.decision_context?.start_at],
                    ["30m背景终点", crossEvidence.decision_context?.end_at],
                    ["30m背景确认", crossEvidence.decision_context_confirmed_at],
                  ]} />
                </section>

                <section>
                  <h3>触发证据</h3>
                  <EvidenceRows rows={[
                    ["触发收盘价", crossEvidence.trigger?.close],
                    ["20周期量比", crossEvidence.trigger?.volume_ratio_20],
                    ["DIF", crossEvidence.trigger?.dif],
                    ["DEA", crossEvidence.trigger?.dea],
                    ["MACD柱", crossEvidence.trigger?.macd],
                  ]} />
                </section>
              </>
            )}
          </>
        )}

        {tab === "comparison" && experimentalComparison && (
          <>
            {!selectedComparison && <p className="empty">选择图中的一笔或一条线段后，这里会显示它与最近同向结构的实验性比较。</p>}
            {selectedComparison && (
              <>
                <section>
                  <div className="section-title-line">
                    <h3>{selectedComparison.level} · {selectedComparison.scope === "stroke" ? "笔" : "线段"} · {selectedComparison.direction === "up" ? "向上" : "向下"}</h3>
                    <span className={`state-tag ${comparisonAudit.status}`}>{fmt(comparisonAudit.status_label)}</span>
                  </div>
                  <EvidenceRows rows={[
                    ["比较方式", "最近同级别、同类型、同方向结构"],
                    ["检验区间", `${fmt(selectedComparison.test.startTime)} 至 ${fmt(selectedComparison.test.endTime)}`],
                    ["对照区间", selectedComparison.reference ? `${fmt(selectedComparison.reference.startTime)} 至 ${fmt(selectedComparison.reference.endTime)}` : null],
                    ["价格创新值", comparisonAudit.price_extension],
                    ["动能减弱票数", comparisonAudit.momentum_votes],
                    ["所需票数", comparisonAudit.required_votes],
                  ]} />
                </section>

                <section>
                  <h3>实验判定</h3>
                  <p className="experimental-basis">该结果仅用于人工复核，不会生成、修改或替代正式 BS 点。</p>
                  <p className="evidence-basis">{comparisonAudit.conclusion}</p>
                </section>

                <section>
                  <h3>背驰区间对比</h3>
                  <ComparisonTable reference={selectedComparison.reference} test={selectedComparison.test} ratios={selectedComparison.ratios} audit={comparisonAudit} />
                </section>
              </>
            )}
          </>
        )}

      </div>
    </aside>
  );
}
