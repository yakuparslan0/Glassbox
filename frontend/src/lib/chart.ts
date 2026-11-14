// Pure geometry for the Big-O chart (inline SVG): measured points + the fitted curve, linear axes.
export interface ChartPoint {
  n: number;
  steps: number;
}

export interface Plot {
  points: { x: number; y: number }[];
  curve: string; // SVG path of the fitted model
  xTicks: { x: number; label: string }[];
  yTicks: { y: number; label: string }[];
}

export function plot(points: ChartPoint[], predicted: number[], width: number, height: number, pad = 36): Plot {
  const maxN = Math.max(...points.map((p) => p.n), 1);
  const maxY = Math.max(...points.map((p) => p.steps), ...predicted.filter(Number.isFinite), 1);
  const sx = (n: number): number => pad + (n / maxN) * (width - 2 * pad);
  const sy = (v: number): number => height - pad - (Math.max(0, v) / maxY) * (height - 2 * pad);
  const curve = points
    .map((p, i) => `${i === 0 ? "M" : "L"}${sx(p.n).toFixed(1)},${sy(predicted[i] ?? 0).toFixed(1)}`)
    .join(" ");
  const fmt = (v: number): string => (v >= 1000 ? `${Math.round(v / 100) / 10}k` : String(Math.round(v)));
  return {
    points: points.map((p) => ({ x: sx(p.n), y: sy(p.steps) })),
    curve,
    xTicks: [0, 0.5, 1].map((f) => ({ x: sx(f * maxN), label: fmt(f * maxN) })),
    yTicks: [0, 0.5, 1].map((f) => ({ y: sy(f * maxY), label: fmt(f * maxY) })),
  };
}
