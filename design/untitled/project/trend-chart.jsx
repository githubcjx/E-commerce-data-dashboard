/* global React, window */
// =========================================================================
// trend-chart.jsx — wraps TrendChart with metric chip selector
// =========================================================================

function TrendPanel({ daily, activeKey, setActiveKey, dragHandle }) {
  const def = window.METRIC_DEFS.find(d => d.key === activeKey) || window.METRIC_DEFS[0];

  return (
    <section className="panel" data-screen-label="趋势">
      <header className="panel-head">
        <span className="panel-title">{def.label}</span>
        <span className="panel-subtitle">趋势</span>
        <div className="panel-actions">
          <button className="btn ghost sm" title="导出 PNG">导出</button>
          {dragHandle}
        </div>
      </header>
      <div className="panel-body">
        <div className="chip-row">
          {window.METRIC_DEFS.map(m => (
            <button
              key={m.key}
              className={`chip ${m.key === activeKey ? "is-active" : ""}`}
              onClick={() => setActiveKey(m.key)}
            >
              {m.label}
            </button>
          ))}
        </div>
        <window.TrendChart
          data={daily}
          valueKey={activeKey}
          format={def.format}
          label={def.label}
        />
      </div>
    </section>
  );
}

Object.assign(window, { TrendPanel });
