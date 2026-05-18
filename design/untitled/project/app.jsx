/* global React, ReactDOM, window */
// =========================================================================
// app.jsx — top-level app, filter bar, view switching, drag-hint, toast
// =========================================================================
const { useState: useAppState, useEffect, useMemo: useAppMemo } = React;

const STORAGE_KEY   = "dashboard.panel.order.v1";
const ACTIVE_KEY    = "dashboard.active.metric.v1";
const SECTION_KEY   = "dashboard.section.order.v1";
const DEFAULT_SECTIONS = ["trend", "categoryTable"];

// ----- Draggable section wrapper (handle-initiated) ---------------------
function GripIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
      <circle cx="5" cy="3"  r="1" fill="currentColor"/>
      <circle cx="9" cy="3"  r="1" fill="currentColor"/>
      <circle cx="5" cy="7"  r="1" fill="currentColor"/>
      <circle cx="9" cy="7"  r="1" fill="currentColor"/>
      <circle cx="5" cy="11" r="1" fill="currentColor"/>
      <circle cx="9" cy="11" r="1" fill="currentColor"/>
    </svg>
  );
}

function DraggableSection({ index, dragIdx, overIdx, setDragIdx, setOverIdx, onReorder, onDragActive, children }) {
  const [armed, setArmed] = React.useState(false);
  const isDragging = dragIdx === index;
  const isOver     = overIdx === index && dragIdx !== null && dragIdx !== index;

  const handle = (
    <button
      className="drag-handle"
      title="拖动调整面板顺序"
      aria-label="拖动调整面板顺序"
      onMouseDown={() => setArmed(true)}
      onMouseUp={()   => setArmed(false)}
      onMouseLeave={() => setArmed(false)}
    >
      <GripIcon />
    </button>
  );

  return (
    <div
      className={`section-wrap ${isDragging ? "is-dragging" : ""} ${isOver ? "is-over" : ""}`}
      draggable={armed}
      onDragStart={(e) => {
        if (!armed) { e.preventDefault(); return; }
        setDragIdx(index);
        onDragActive && onDragActive(true);
        e.dataTransfer.effectAllowed = "move";
        try { e.dataTransfer.setData("text/plain", String(index)); } catch (_) {}
      }}
      onDragEnter={(e) => {
        e.preventDefault();
        if (dragIdx === null || dragIdx === index) return;
        setOverIdx(index);
      }}
      onDragOver={(e) => { if (dragIdx !== null) e.preventDefault(); }}
      onDrop={(e) => {
        e.preventDefault();
        if (dragIdx !== null && dragIdx !== index) onReorder(dragIdx, index);
        setArmed(false);
        setDragIdx(null);
        setOverIdx(null);
        onDragActive && onDragActive(false);
      }}
      onDragEnd={() => {
        setArmed(false);
        setDragIdx(null);
        setOverIdx(null);
        onDragActive && onDragActive(false);
      }}
    >
      {typeof children === "function" ? children(handle) : children}
    </div>
  );
}

const TWEAK_DEFAULTS = /*EDITMODE-BEGIN*/{
  "showHandles": true
}/*EDITMODE-END*/;

function loadOrder() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return window.DEFAULT_PANEL_ORDER.slice();
    const parsed = JSON.parse(raw);
    // sanity-check: must contain exactly the known keys
    const known = new Set(window.DEFAULT_PANEL_ORDER);
    if (!Array.isArray(parsed) || parsed.length !== known.size) return window.DEFAULT_PANEL_ORDER.slice();
    if (!parsed.every(k => known.has(k))) return window.DEFAULT_PANEL_ORDER.slice();
    return parsed;
  } catch (_) { return window.DEFAULT_PANEL_ORDER.slice(); }
}

function loadSectionOrder() {
  try {
    const raw = localStorage.getItem(SECTION_KEY);
    if (!raw) return DEFAULT_SECTIONS.slice();
    const parsed = JSON.parse(raw);
    const known = new Set(DEFAULT_SECTIONS);
    if (!Array.isArray(parsed) || parsed.length !== known.size) return DEFAULT_SECTIONS.slice();
    if (!parsed.every(k => known.has(k))) return DEFAULT_SECTIONS.slice();
    return parsed;
  } catch (_) { return DEFAULT_SECTIONS.slice(); }
}

function App() {
  const [view, setView]         = useAppState("dashboard");   // "dashboard" | "import"
  const [order, setOrder]       = useAppState(loadOrder);
  const [sectionOrder, setSectionOrder] = useAppState(loadSectionOrder);
  const [secDragIdx, setSecDragIdx] = useAppState(null);
  const [secOverIdx, setSecOverIdx] = useAppState(null);
  const [activeKey, setActiveKey] = useAppState(() => localStorage.getItem(ACTIVE_KEY) || "sales");
  const [granularity, setGranularity] = useAppState("day");
  const [date, setDate]         = useAppState("2026-05-10");
  const [shop, setShop]         = useAppState("全部");
  const [owner, setOwner]       = useAppState("全部");
  const [cat, setCat]           = useAppState("全部");
  const [isDragging, setIsDragging] = useAppState(false);

  const [toast, setToast]       = useAppState(null);
  const showToast = (msg, kind = "success") => {
    setToast({ msg, kind, id: Date.now() });
  };
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 2400);
    return () => clearTimeout(t);
  }, [toast]);

  // Persist
  useEffect(() => { localStorage.setItem(STORAGE_KEY, JSON.stringify(order)); }, [order]);
  useEffect(() => { localStorage.setItem(SECTION_KEY, JSON.stringify(sectionOrder)); }, [sectionOrder]);
  useEffect(() => { localStorage.setItem(ACTIVE_KEY, activeKey); }, [activeKey]);

  const reorderSections = (from, to) => {
    const next = sectionOrder.slice();
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setSectionOrder(next);
  };

  const renderSection = (key, idx) => {
    const common = {
      index: idx,
      dragIdx: secDragIdx,
      overIdx: secOverIdx,
      setDragIdx: setSecDragIdx,
      setOverIdx: setSecOverIdx,
      onReorder: reorderSections,
      onDragActive: setIsDragging,
    };
    if (key === "trend") {
      return (
        <DraggableSection key="trend" {...common}>
          {(handle) => (
            <window.TrendPanel
              daily={daily}
              activeKey={activeKey}
              setActiveKey={setActiveKey}
              dragHandle={handle}
            />
          )}
        </DraggableSection>
      );
    }
    if (key === "categoryTable") {
      return (
        <DraggableSection key="categoryTable" {...common}>
          {(handle) => (
            <window.CategoryTable rows={window.CATEGORIES} dragHandle={handle} />
          )}
        </DraggableSection>
      );
    }
    return null;
  };

  const daily = window.DAILY;
  const prev  = window.PREV_PERIOD;

  return (
    <>
      <header className="topbar">
        <div className="topbar-inner">
          <div className="brand">
            <span className="brand-mark">EC</span>
            <span className="brand-name">电商经营看板</span>
            <span className="brand-tag">· v1.0</span>
          </div>
          <div className="tabs" role="tablist">
            <button className={`tab ${view === "dashboard" ? "is-active" : ""}`}
                    onClick={() => setView("dashboard")} role="tab">看板</button>
            <button className={`tab ${view === "import" ? "is-active" : ""}`}
                    onClick={() => setView("import")} role="tab">导入</button>
          </div>
          <div className="topbar-right">
            <span className="status-dot" />
            <span>数据更新于 09:42</span>
            <span className="topbar-divider" />
            <span className="mono">陈雨晴</span>
          </div>
        </div>
      </header>

      <main className="shell">
        {view === "dashboard" ? (
          <>
            <div className="filter-row">
              <div className="seg" role="tablist">
                {[["day", "日"], ["week", "周"], ["month", "月"]].map(([k, l]) => (
                  <button key={k}
                          className={`seg-btn ${granularity === k ? "is-active" : ""}`}
                          onClick={() => setGranularity(k)}>{l}</button>
                ))}
              </div>

              <div className="filter-group">
                <span className="filter-label">店铺</span>
                <select className="select" value={shop} onChange={e => setShop(e.target.value)}>
                  {window.SHOPS.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
              <div className="filter-group">
                <span className="filter-label">负责人</span>
                <select className="select" value={owner} onChange={e => setOwner(e.target.value)}>
                  {window.OWNERS.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>
              <div className="filter-group">
                <span className="filter-label">类目</span>
                <select className="select" value={cat} onChange={e => setCat(e.target.value)}>
                  {window.CATS.map(s => <option key={s}>{s}</option>)}
                </select>
              </div>

              <div className="spacer-x" />

              <input
                type="date"
                className="date-input"
                value={date}
                onChange={e => setDate(e.target.value)}
                min="2024-01-01"
                max="2027-12-31"
              />
              <button className="btn" onClick={() => {
                setOrder(window.DEFAULT_PANEL_ORDER.slice());
                setSectionOrder(DEFAULT_SECTIONS.slice());
                showToast("已重置面板顺序");
              }}>重置布局</button>
            </div>

            <window.MetricGrid
              order={order}
              setOrder={setOrder}
              activeKey={activeKey}
              setActiveKey={setActiveKey}
              daily={daily}
              prev={prev}
              onDragActive={setIsDragging}
            />

            <div className="stack">
              {sectionOrder.map((key, idx) => renderSection(key, idx))}
            </div>
          </>
        ) : (
          <window.ImportView toast={showToast} />
        )}
      </main>

      <div className={`drag-hint ${isDragging ? "is-visible" : ""}`}>
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
          <circle cx="5" cy="3" r="1" fill="currentColor"/>
          <circle cx="9" cy="3" r="1" fill="currentColor"/>
          <circle cx="5" cy="7" r="1" fill="currentColor"/>
          <circle cx="9" cy="7" r="1" fill="currentColor"/>
          <circle cx="5" cy="11" r="1" fill="currentColor"/>
          <circle cx="9" cy="11" r="1" fill="currentColor"/>
        </svg>
        松开以放置在此处
      </div>

      <div className={`toast ${toast ? "is-visible" : ""} ${toast?.kind || ""}`}>
        <span className="toast-dot" />
        <span>{toast?.msg}</span>
      </div>
    </>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
