/* global React, window */
// =========================================================================
// metric-cards.jsx — 8 KPI cards with sparklines + HTML5 drag-and-drop
// =========================================================================
const { useState, useRef } = React;

function HandleIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <circle cx="5" cy="3" r="1" fill="currentColor"/>
      <circle cx="9" cy="3" r="1" fill="currentColor"/>
      <circle cx="5" cy="7" r="1" fill="currentColor"/>
      <circle cx="9" cy="7" r="1" fill="currentColor"/>
      <circle cx="5" cy="11" r="1" fill="currentColor"/>
      <circle cx="9" cy="11" r="1" fill="currentColor"/>
    </svg>
  );
}

function MetricCard({ def, value, prev, series, isActive, onClick, dragHandlers, dragState }) {
  const delta = window.formatDelta(value, prev, def.higherIsBetter);
  const trend = delta.sign;
  const cls = [
    "metric-card",
    isActive ? "is-active" : "",
    dragState === "dragging" ? "is-dragging" : "",
    dragState === "over" ? "is-drop-target" : "",
  ].filter(Boolean).join(" ");

  return (
    <div
      className={cls}
      draggable
      onClick={onClick}
      onDragStart={dragHandlers.onDragStart}
      onDragEnter={dragHandlers.onDragEnter}
      onDragOver={dragHandlers.onDragOver}
      onDragLeave={dragHandlers.onDragLeave}
      onDrop={dragHandlers.onDrop}
      onDragEnd={dragHandlers.onDragEnd}
      role="button"
      tabIndex={0}
    >
      <div>
        <div className="metric-head">
          <span className="metric-label">{def.label}</span>
          <span className="metric-handle" title="拖动调整位置"><HandleIcon /></span>
        </div>
        <div className="metric-value-row">
          <span className="metric-value">{window.formatValue(value, def.format)}</span>
          <span className={`metric-delta ${trend}`}>
            {delta.arrow}{delta.text === "—" ? "" : delta.text}
          </span>
        </div>
        <div className="metric-prev">上期 {window.formatValue(prev, def.format)}</div>
      </div>
      <Sparkline values={series} trend={trend} />
    </div>
  );
}

function MetricGrid({ order, setOrder, activeKey, setActiveKey, daily, prev, onDragActive }) {
  const dragIndex = useRef(null);
  const [overIndex, setOverIndex] = useState(null);

  const handleDragStart = (i) => (e) => {
    dragIndex.current = i;
    e.dataTransfer.effectAllowed = "move";
    // Required for Firefox
    try { e.dataTransfer.setData("text/plain", String(i)); } catch (_) {}
    onDragActive && onDragActive(true);
  };
  const handleDragEnter = (i) => (e) => {
    e.preventDefault();
    if (dragIndex.current === null || dragIndex.current === i) return;
    setOverIndex(i);
  };
  const handleDragOver = (_i) => (e) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
  };
  const handleDragLeave = (_i) => (_e) => {
    // no-op; overIndex updates via dragEnter on the next card
  };
  const handleDrop = (i) => (e) => {
    e.preventDefault();
    const from = dragIndex.current;
    if (from === null || from === i) { reset(); return; }
    const next = order.slice();
    const [moved] = next.splice(from, 1);
    next.splice(i, 0, moved);
    setOrder(next);
    reset();
  };
  const handleDragEnd = (_i) => (_e) => { reset(); };
  const reset = () => {
    dragIndex.current = null;
    setOverIndex(null);
    onDragActive && onDragActive(false);
  };

  return (
    <div className="metrics-grid">
      {order.map((key, i) => {
        const def = window.METRIC_DEFS.find(d => d.key === key);
        if (!def) return null;
        const value = daily[daily.length - 1][key];
        const prevVal = prev[key];
        const series = daily.map(d => d[key]);
        const isDragging = dragIndex.current === i;
        const isOver = overIndex === i && !isDragging;
        return (
          <MetricCard
            key={key}
            def={def}
            value={value}
            prev={prevVal}
            series={series}
            isActive={activeKey === key}
            onClick={() => setActiveKey(key)}
            dragState={isDragging ? "dragging" : isOver ? "over" : null}
            dragHandlers={{
              onDragStart: handleDragStart(i),
              onDragEnter: handleDragEnter(i),
              onDragOver:  handleDragOver(i),
              onDragLeave: handleDragLeave(i),
              onDrop:      handleDrop(i),
              onDragEnd:   handleDragEnd(i),
            }}
          />
        );
      })}
    </div>
  );
}

Object.assign(window, { MetricGrid });
