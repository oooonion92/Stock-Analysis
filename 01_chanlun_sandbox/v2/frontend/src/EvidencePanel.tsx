import { useEffect, useMemo, useState } from "react";
import type { AnalysisResponse, ChanSignal } from "./types";

type Tab = "structure" | "signal";

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

function ComparisonTable({ reference, test, ratios }: {
  reference?: Record<string, any> | null;
  test?: Record<string, any> | null;
  ratios: Record<string, any>;
}) {
  if (!reference || !test) return <p className="empty">当前点没有可还原的对照段，只展示结构条件。</p>;
  const rows = [
    ["时间", `${fmt(reference.startTime)} 至 ${fmt(reference.endTime)}`, `${fmt(test.startTime)} 至 ${fmt(test.endTime)}`, ""],
    ["价格幅度", fmt(reference.priceMove), fmt(test.priceMove), ratio(ratios.price_move)],
    ["MACD面积", fmt(reference.macdArea), fmt(test.macdArea), ratio(ratios.macd_area)],
    ["MACD峰值", fmt(reference.macdPeak), fmt(test.macdPeak), ratio(ratios.macd_peak)],
    ["DIF极值", fmt(reference.difExtreme), fmt(test.difExtreme), ratio(ratios.dif_extreme)],
    ["平均成交量", compact(reference.volumeAverage), compact(test.volumeAverage), ratio(ratios.volume_average)],
  ];
  return (
    <table className="metric-table">
      <thead><tr><th>指标</th><th>对照段</th><th>检验段</th><th>比值</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row[0]}>{row.map((cell, index) => <td key={index}>{cell}</td>)}</tr>)}</tbody>
    </table>
  );
}

export default function EvidencePanel({
  data,
  activeLevel,
  selectedSignal,
}: {
  data: AnalysisResponse;
  activeLevel: "5m" | "30m";
  selectedSignal?: ChanSignal | null;
}) {
  const [tab, setTab] = useState<Tab>("structure");
  const active = activeLevel === "5m" ? data.chan.execution : data.chan.decision;
  const context = activeLevel === "5m" ? data.chan.decision : data.chan.higher;
  const latestCenter = active.centers[active.centers.length - 1] || null;
  const signal = selectedSignal || active.signals[active.signals.length - 1] || null;
  const evidence = (signal?.evidence || {}) as Record<string, any>;
  const audit = (evidence.divergence_audit || {}) as Record<string, any>;
  const ratios = (evidence.ratios || {}) as Record<string, any>;

  useEffect(() => {
    if (selectedSignal) setTab("signal");
  }, [selectedSignal?.id]);

  const recentSignals = useMemo(
    () => active.signals.slice(-8).reverse(),
    [active.signals],
  );
  return (
    <aside className="evidence-panel">
      <div className="evidence-tabs" role="tablist">
        <button className={tab === "structure" ? "active" : ""} onClick={() => setTab("structure")}>结构</button>
        <button className={tab === "signal" ? "active" : ""} onClick={() => setTab("signal")}>BS点</button>
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
                  <EvidenceRows rows={[
                    ["复核结论", audit.status],
                    ["价格创新值", audit.price_extension],
                    ["动力减弱票数", audit.momentum_votes],
                    ["所需票数", audit.required_votes],
                    ["减弱阈值", audit.weakening_ratio],
                    ["结论", audit.conclusion],
                  ]} />
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
                  <h3>背驰区间对比</h3>
                  <ComparisonTable reference={evidence.reference} test={evidence.test} ratios={ratios} />
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

      </div>
    </aside>
  );
}
