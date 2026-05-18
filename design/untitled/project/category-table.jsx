/* global React, window */
// =========================================================================
// category-table.jsx — category breakdown with sortable columns + share bar
// =========================================================================
const { useState: useTblState, useMemo: useTblMemo } = React;

function CategoryTable({ rows, dragHandle }) {
  const [sortKey, setSortKey] = useTblState("sales");
  const [sortDir, setSortDir] = useTblState("desc");

  const sorted = useTblMemo(() => {
    const r = rows.slice();
    r.sort((a, b) => {
      const va = a[sortKey];
      const vb = b[sortKey];
      if (typeof va === "string") {
        return sortDir === "asc" ? va.localeCompare(vb) : vb.localeCompare(va);
      }
      return sortDir === "asc" ? va - vb : vb - va;
    });
    return r;
  }, [rows, sortKey, sortDir]);

  const maxSales = Math.max(...rows.map(r => r.sales));

  const head = (key, label, align = "right") => (
    <th
      style={{ cursor: "pointer", textAlign: align }}
      onClick={() => {
        if (sortKey === key) setSortDir(sortDir === "asc" ? "desc" : "asc");
        else { setSortKey(key); setSortDir("desc"); }
      }}
    >
      {label}
      <span style={{ marginLeft: 6, color: "var(--ink-5)", fontFamily: "var(--font-mono)" }}>
        {sortKey === key ? (sortDir === "asc" ? "↑" : "↓") : ""}
      </span>
    </th>
  );

  return (
    <section className="panel" data-screen-label="类目汇总">
      <header className="panel-head">
        <span className="panel-title">类目分类汇总</span>
        <span className="panel-subtitle">按销售额排序 · 共 {rows.length} 项</span>
        <div className="panel-actions">
          <button className="btn ghost sm">导出 CSV</button>
          {dragHandle}
        </div>
      </header>
      <table className="tbl">
        <thead>
          <tr>
            {head("name", "类目", "left")}
            {head("sales", "销售额")}
            {head("profit", "利润额")}
            {head("orders", "订单量")}
            {head("grossMargin", "毛利率")}
            {head("refundRate", "退款率")}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={i}>
              <td>{r.name}</td>
              <td>
                {window.formatValue(r.sales, "currency")}
                <span className="t-bar"><i style={{ width: `${(r.sales / maxSales) * 100}%` }} /></span>
              </td>
              <td className={r.profit >= 0 ? "t-pos" : "t-neg"}>
                {window.formatValue(r.profit, "currency")}
              </td>
              <td className="t-muted">{window.formatValue(r.orders, "int")}</td>
              <td>{window.formatValue(r.grossMargin, "percent")}</td>
              <td className={r.refundRate >= 40 ? "t-neg" : ""}>
                {window.formatValue(r.refundRate, "percent")}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

Object.assign(window, { CategoryTable });
