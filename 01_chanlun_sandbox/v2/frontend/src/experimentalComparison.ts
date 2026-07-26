import type {
  ChanLine,
  StructureComparison,
  StructureLineMetrics,
  StructureScope,
} from "./types";

const WEAKENING_RATIO = 0.85;
const REQUIRED_MOMENTUM_VOTES = 2;

function safeRatio(value: number, reference: number): number | null {
  return Math.abs(reference) > 1e-12 ? value / reference : null;
}

function metrics(line: ChanLine, name: string): StructureLineMetrics {
  return {
    name,
    startTime: line.start_at,
    endTime: line.end_at,
    startValue: line.start_price,
    endValue: line.end_price,
    direction: line.direction,
    bars: line.bars,
    priceMove: line.price_move,
    macdArea: line.macd_area,
    macdPeak: line.macd_peak,
    difExtreme: line.dif_extreme,
    volumeTotal: line.volume,
    volumeAverage: line.volume_average,
    amountAverage: line.amount_average,
  };
}

export function buildStructureComparison(
  selected: ChanLine,
  lines: ChanLine[],
  scope: StructureScope,
): StructureComparison {
  const selectedIndex = lines.findIndex((line) => line.id === selected.id);
  const referenceLine = selectedIndex > 0
    ? lines.slice(0, selectedIndex).reverse().find((line) => line.direction === selected.direction) || null
    : null;
  const test = metrics(selected, "检验段");

  if (!referenceLine) {
    return {
      id: `${scope}:${selected.id}`,
      level: selected.level,
      scope,
      direction: selected.direction,
      reference: null,
      test,
      ratios: {},
      audit: {
        status: "insufficient",
        status_label: "缺少同向对照段",
        conclusion: "当前结构之前没有可用于比较的同级别、同类型、同方向结构。",
      },
    };
  }

  const reference = metrics(referenceLine, "对照段");
  const ratios = {
    price_move: safeRatio(test.priceMove, reference.priceMove),
    macd_area: safeRatio(test.macdArea, reference.macdArea),
    macd_peak: safeRatio(test.macdPeak, reference.macdPeak),
    dif_extreme: safeRatio(test.difExtreme, reference.difExtreme),
    volume_average: safeRatio(test.volumeAverage, reference.volumeAverage),
  };
  const priceExtension = selected.direction === "down"
    ? test.endValue < reference.endValue
    : test.endValue > reference.endValue;
  const checks = {
    macd_area_weakening: ratios.macd_area !== null && ratios.macd_area <= WEAKENING_RATIO,
    macd_peak_weakening: ratios.macd_peak !== null && ratios.macd_peak <= WEAKENING_RATIO,
    dif_weakening: ratios.dif_extreme !== null && ratios.dif_extreme <= WEAKENING_RATIO,
  };
  const votes = Object.values(checks).filter(Boolean).length;
  const status = priceExtension && votes >= REQUIRED_MOMENTUM_VOTES
    ? "confirmed"
    : priceExtension && votes === 1
      ? "insufficient"
      : "unsupported";
  const conclusion = !priceExtension
    ? "价格没有形成同向新极值，不符合背驰比较的价格前提。"
    : votes >= REQUIRED_MOMENTUM_VOTES
      ? `价格创新值，三项动能证据中有 ${votes} 项减弱，符合实验性背驰特征。`
      : votes === 1
        ? "价格创新值，但只有一项动能证据减弱，证据不足。"
        : "价格创新值，但动能没有出现明确减弱。";

  return {
    id: `${scope}:${referenceLine.id}:${selected.id}`,
    level: selected.level,
    scope,
    direction: selected.direction,
    reference,
    test,
    ratios,
    audit: {
      status,
      status_label: status === "confirmed" ? "符合实验性背驰特征" : status === "insufficient" ? "证据不足" : "不符合",
      price_extension: priceExtension,
      momentum_votes: votes,
      required_votes: REQUIRED_MOMENTUM_VOTES,
      weakening_ratio: WEAKENING_RATIO,
      ...checks,
      volume_contracting: ratios.volume_average !== null && ratios.volume_average < 1,
      conclusion,
    },
  };
}
