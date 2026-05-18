/* global React, window */
// =========================================================================
// charts.jsx — hand-drawn SVG charts (sparkline + main trend)
// Smoothed cubic-bezier paths for the rounded, premium look in the prototype
// =========================================================================
const { useMemo } = React;

// ---------- smooth path builder (Catmull-Rom → bezier) ----------
function smoothPath(points, tension = 0.35) {
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

function Sparkline({ values, trend /* "up" | "down" | "flat" */, width = 220, height = 44 }) {
  const path = useMemo(() => {
    if (!values || values.length === 0) return { line: "", area: "" };
    const min = Math.min(...values);
    const max = Math.max(...values);
    const span = max - min || 1;
    const px = (i) => (i / (values.length - 1 || 1)) * (width - 4) + 2;
    const py = (v) => height - 4 - ((v - min) / span) * (height - 8);
    const pts = values.map((v, i) => ({ x: px(i), y: py(v) }));
    if (Math.abs(span) < 1e-9) {
      // Render as flat line
      const y = height / 2;
      return {
        line: `M 2 ${y} L ${width - 2} ${y}`,
        area: `M 2 ${y} L ${width - 2} ${y} L ${width - 2} ${height} L 2 ${height} Z`,
      };
    }
    const line = smoothPath(pts);
    const area = `${line} L ${pts[pts.length - 1].x} ${height} L ${pts[0].x} ${height} Z`;
    return { line, area };
  }, [values, width, height]);

  const color =
    trend === "up"   ? "var(--pos)" :
    trend === "down" ? "var(--neg)" :
                       "var(--ink-4)";
  const fill =
    trend === "up"   ? "var(--pos-soft)" :
    trend === "down" ? "var(--neg-soft)" :
                       "transparent";
  const gid = `sg-${trend}-${Math.random().toString(36).slice(2, 8)}`;

  return (
    <svg viewBox={`0 0 ${width} ${height}`} width="100%" height={height} preserveAspectRatio="none" className="metric-spark">
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"  stopColor={color} stopOpacity="0.18" />
          <stop offset="100%" stopColor={color} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={path.area} fill={`url(#${gid})`} />
      <path d={path.line} fill="none" stroke={color} strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" />
    </svg>
  );
}

// =========================================================================
// Main trend chart — interactive with hover tooltip
// =========================================================================
function TrendChart({ data, valueKey, format, label }) {
  const [hover, setHover] = React.useState(null);
  const wrapRef = React.useRef(null);

  // Layout
  const padL = 56, padR = 24, padT = 16, padB = 36;
  const W = 1100, H = 320;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;

  const values = data.map(d => d[valueKey]);
  const minV = Math.min(...values, 0);
  const maxV = Math.max(...values, 0);
  // Pretty-axis: add 10% headroom
  const range = (maxV - minV) || 1;
  const yMin = minV - range * 0.08;
  const yMax = maxV + range * 0.12;

  // Round to nicer ticks
  function niceTicks(min, max, count = 6) {
    const span = max - min;
    const rawStep = span / (count - 1);
    const magnitude = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const norm = rawStep / magnitude;
    let step;
    if      (norm < 1.5) step = 1 * magnitude;
    else if (norm < 3)   step = 2 * magnitude;
    else if (norm < 7)   step = 5 * magnitude;
    else                 step = 10 * magnitude;
    const niceMin = Math.floor(min / step) * step;
    const niceMax = Math.ceil(max / step) * step;
    const ticks = [];
    for (let v = niceMin; v <= niceMax + 1e-9; v += step) ticks.push(v);
    return { ticks, niceMin, niceMax };
  }
  const { ticks, niceMin, niceMax } = niceTicks(yMin, yMax, 6);
  const yScale = (v) => padT + innerH - ((v - niceMin) / (niceMax - niceMin || 1)) * innerH;
  const xScale = (i) => padL + (i / (data.length - 1 || 1)) * innerW;

  const pts = data.map((d, i) => ({ x: xScale(i), y: yScale(d[valueKey]) }));
  const linePath = smoothPath(pts, 0.4);
  const areaPath = `${linePath} L ${pts[pts.length - 1].x} ${padT + innerH} L ${pts[0].x} ${padT + innerH} Z`;

  // Color follows whether the latest value is favorable. We just use accent.
  const accent = "var(--accent)";

  const handleMove = (e) => {
    if (!wrapRef.current) return;
    const rect = wrapRef.current.getBoundingClientRect();
    const xRel = ((e.clientX - rect.left) / rect.width) * W;
    if (xRel < padL || xRel > W - padR) { setHover(null); return; }
    // Nearest point
    let best = 0, bestDist = Infinity;
    pts.forEach((p, i) => {
      const d = Math.abs(p.x - xRel);
      if (d < bestDist) { bestDist = d; best = i; }
    });
    setHover(best);
  };
  const handleLeave = () => setHover(null);

  // tooltip pixel position (relative to wrapper)
  let tipLeft = 0, tipTop = 0;
  if (hover !== null) {
    const p = pts[hover];
    tipLeft = (p.x / W) * 100;
    tipTop  = (p.y / H) * 100;
  }

  // Format y-axis label
  const yfmt = (v) => {
    if (format === "percent") return v.toFixed(0) + "%";
    if (format === "int")     return Math.round(v).toLocaleString("en-US");
    if (Math.abs(v) >= 1000)  return (v / 1000).toFixed(v % 1000 === 0 ? 0 : 1) + "k";
    return v.toFixed(0);
  };

  return (
    <div className="trend-wrap" ref={wrapRef} onMouseMove={handleMove} onMouseLeave={handleLeave}>
      <svg className="trend-svg" viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none">
        <defs>
          <linearGradient id="trend-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%"  stopColor={accent} stopOpacity="0.18" />
            <stop offset="100%" stopColor={accent} stopOpacity="0" />
          </linearGradient>
        </defs>

        {/* Y-axis grid + labels */}
        {ticks.map((t, i) => {
          const y = yScale(t);
          return (
            <g key={i}>
              <line x1={padL} x2={W - padR} y1={y} y2={y}
                    stroke="var(--divider)" strokeWidth="1"
                    strokeDasharray={t === 0 ? "0" : "3 4"} />
              <text x={padL - 10} y={y + 4}
                    fontSize="11" textAnchor="end" fill="var(--ink-4)"
                    fontFamily="var(--font-mono)">{yfmt(t)}</text>
            </g>
          );
        })}

        {/* zero baseline emphasized */}
        {niceMin < 0 && niceMax > 0 && (
          <line x1={padL} x2={W - padR} y1={yScale(0)} y2={yScale(0)}
                stroke="var(--border-strong)" strokeWidth="1" />
        )}

        {/* X labels */}
        {data.map((d, i) => {
          // Show only every other to avoid overlap on small widths
          const show = data.length <= 10 || i % 2 === 0;
          if (!show) return null;
          return (
            <text key={i} x={xScale(i)} y={H - 12}
                  fontSize="11" textAnchor="middle" fill="var(--ink-4)"
                  fontFamily="var(--font-mono)">{d.date}</text>
          );
        })}

        {/* Area + line */}
        <path d={areaPath} fill="url(#trend-fill)" />
        <path d={linePath} fill="none" stroke={accent} strokeWidth="2"
              strokeLinejoin="round" strokeLinecap="round" />

        {/* Points */}
        {pts.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={hover === i ? 5 : 3.5}
                  fill="#fff" stroke={accent} strokeWidth="2" />
        ))}

        {/* hover vertical guide */}
        {hover !== null && (
          <line x1={pts[hover].x} x2={pts[hover].x}
                y1={padT} y2={padT + innerH}
                stroke="var(--ink)" strokeOpacity="0.18" strokeWidth="1" strokeDasharray="3 4" />
        )}
      </svg>

      {hover !== null && (
        <div
          className="trend-tooltip is-visible"
          style={{ left: `${tipLeft}%`, top: `${tipTop}%` }}
        >
          <span className="t-label">{label} · {data[hover].date}</span>
          <strong>{window.formatValue(data[hover][valueKey], format)}</strong>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { Sparkline, TrendChart, smoothPath });
