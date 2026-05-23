// Always show the full precise number with thousands separators and two
// decimal places. (We previously collapsed large amounts to "X.XX万" but
// the precision loss made it hard to verify totals against the source
// Excel — switched back to full numbers per user request.)
export function formatCurrency(v) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  return Number(v).toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

export function formatValue(v, fmt) {
  if (v === null || v === undefined || Number.isNaN(v)) return "—";
  if (fmt === "currency") return formatCurrency(v);
  if (fmt === "percent") {
    return Number(v).toFixed(2) + "%";
  }
  if (fmt === "int") {
    return Math.round(Number(v)).toLocaleString("en-US");
  }
  return String(v);
}

export function formatDelta(curr, prev, _higherIsBetter) {
  // Color follows raw direction (涨 = up = red, 跌 = down = green) regardless
  // of whether "up" is semantically good for this metric — this matches the
  // Chinese stock-chart convention the user requested.
  if (prev === 0 && curr === 0) return { sign: "flat", text: "0.00%", arrow: "→" };
  if (prev === 0 || prev === null || prev === undefined) return { sign: "flat", text: "—", arrow: "→" };
  const pct = ((curr - prev) / Math.abs(prev)) * 100;
  if (Math.abs(pct) < 0.005) return { sign: "flat", text: "0.00%", arrow: "→" };
  const isUp = pct > 0;
  return {
    sign: isUp ? "up" : "down",
    text: (pct > 0 ? "+" : "") + pct.toFixed(2) + "%",
    arrow: isUp ? "↑" : "↓",
  };
}

export function smoothPath(points, tension = 0.35) {
  if (points.length < 2) return "";
  let d = `M ${points[0].x} ${points[0].y}`;
  for (let i = 0; i < points.length - 1; i++) {
    const p0 = points[i - 1] || points[i];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[i + 2] || p2;
    const cp1x = p1.x + (p2.x - p0.x) * tension / 3;
    const cp1y = p1.y + (p2.y - p0.y) * tension / 3;
    const cp2x = p2.x - (p3.x - p1.x) * tension / 3;
    const cp2y = p2.y - (p3.y - p1.y) * tension / 3;
    d += ` C ${cp1x} ${cp1y}, ${cp2x} ${cp2y}, ${p2.x} ${p2.y}`;
  }
  return d;
}
