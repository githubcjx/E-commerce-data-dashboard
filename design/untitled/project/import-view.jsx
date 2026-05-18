/* global React, window, XLSX */
// =========================================================================
// import-view.jsx — Excel upload + preview + history
// =========================================================================
const { useState: useImpState, useRef: useImpRef, useCallback } = React;

function UploadIcon() {
  return (
    <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
      <path d="M12 16V4M12 4L7 9M12 4L17 9" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M4 16V19C4 19.5523 4.44772 20 5 20H19C19.5523 20 20 19.5523 20 19V16" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}
function FileIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 14 14" fill="none">
      <path d="M3 1.5H8L11 4.5V12.5C11 12.7761 10.7761 13 10.5 13H3C2.72386 13 2.5 12.7761 2.5 12.5V2C2.5 1.72386 2.72386 1.5 3 1.5Z"
            stroke="currentColor" strokeWidth="1.2"/>
      <path d="M8 1.5V4.5H11" stroke="currentColor" strokeWidth="1.2"/>
    </svg>
  );
}

function ImportView({ onImported, toast }) {
  const [isOver, setIsOver]   = useImpState(false);
  const [parsed, setParsed]   = useImpState(null);  // { name, size, rows, columns, data, sheetNames, activeSheet }
  const [workbook, setWorkbook] = useImpState(null);
  const inputRef = useImpRef(null);
  const [busy, setBusy] = useImpState(false);

  const handleFile = useCallback(async (file) => {
    if (!file) return;
    setBusy(true);
    try {
      const buf = await file.arrayBuffer();
      const wb  = XLSX.read(buf, { type: "array", cellDates: true });
      setWorkbook(wb);
      const firstSheet = wb.SheetNames[0];
      const ws = wb.Sheets[firstSheet];
      const json = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
      const [header = [], ...rows] = json;
      setParsed({
        name: file.name,
        size: (file.size / 1024).toFixed(0) + " KB",
        rows: rows.length,
        columns: header,
        data: rows,
        sheetNames: wb.SheetNames,
        activeSheet: firstSheet,
        when: new Date().toLocaleString("zh-CN", { hour12: false }),
      });
      toast(`已解析 ${file.name} · ${rows.length} 行`);
    } catch (err) {
      console.error(err);
      toast("文件解析失败：" + err.message, "error");
    } finally {
      setBusy(false);
    }
  }, [toast]);

  const switchSheet = (name) => {
    if (!workbook) return;
    const ws = workbook.Sheets[name];
    const json = XLSX.utils.sheet_to_json(ws, { header: 1, defval: "" });
    const [header = [], ...rows] = json;
    setParsed(p => ({ ...p, activeSheet: name, columns: header, data: rows, rows: rows.length }));
  };

  const onDrop = (e) => {
    e.preventDefault();
    setIsOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  };

  return (
    <div className="stack">
      <div className="import-wrap">
        <div
          className={`dropzone ${isOver ? "is-over" : ""}`}
          onDragOver={(e) => { e.preventDefault(); setIsOver(true); }}
          onDragLeave={() => setIsOver(false)}
          onDrop={onDrop}
          onClick={() => inputRef.current?.click()}
        >
          <div className="dropzone-icon"><UploadIcon /></div>
          <h3>{busy ? "正在解析…" : "拖拽 Excel 至此处或点击选择"}</h3>
          <p>支持 .xlsx / .xls / .csv · 单次最大 20MB · 首行作为表头</p>
          <input
            ref={inputRef}
            type="file"
            accept=".xlsx,.xls,.csv"
            style={{ display: "none" }}
            onChange={(e) => handleFile(e.target.files?.[0])}
          />
        </div>

        <aside className="import-meta">
          <h4>导入要求</h4>
          <dl className="kv">
            <dt>必含字段</dt>
            <dd>日期 / 店铺 / 类目 / 销售额 / 订单量</dd>
            <dt>可选字段</dt>
            <dd>退款额 / 成本 / 快递费 / 营销费</dd>
            <dt>日期格式</dt>
            <dd>YYYY-MM-DD</dd>
            <dt>编码</dt>
            <dd>UTF-8 / GBK 自动识别</dd>
            <dt>解析方式</dt>
            <dd>客户端 SheetJS</dd>
          </dl>
          <div style={{ marginTop: 14, paddingTop: 14, borderTop: "1px solid var(--divider)" }}>
            <button className="btn sm" onClick={() => {
              // Download a template
              const ws = XLSX.utils.aoa_to_sheet([
                ["日期", "店铺", "类目", "销售额", "订单量", "退款额", "成本", "快递费", "营销费"],
                ["2026-05-10", "旗舰店 · 天猫", "家居家纺", 1280.50, 24, 80, 420, 38, 280],
              ]);
              const wb = XLSX.utils.book_new();
              XLSX.utils.book_append_sheet(wb, ws, "示例");
              XLSX.writeFile(wb, "导入模板.xlsx");
            }}>下载模板</button>
          </div>
        </aside>
      </div>

      {parsed && (
        <div className="preview-table-wrap">
          <header className="panel-head">
            <span className="panel-title">{parsed.name}</span>
            <span className="panel-subtitle">{parsed.rows.toLocaleString()} 行 · {parsed.columns.length} 列 · {parsed.size}</span>
            {parsed.sheetNames.length > 1 && (
              <div className="panel-actions" style={{ marginLeft: 16 }}>
                {parsed.sheetNames.map(n => (
                  <button key={n}
                          className={`chip ${parsed.activeSheet === n ? "is-active" : ""}`}
                          onClick={() => switchSheet(n)}>{n}</button>
                ))}
              </div>
            )}
            <div className="panel-actions">
              <button className="btn sm" onClick={() => { setParsed(null); setWorkbook(null); }}>移除</button>
              <button className="btn primary sm" onClick={() => {
                toast(`已应用 ${parsed.rows} 行至看板`, "success");
                onImported && onImported(parsed);
              }}>应用到看板</button>
            </div>
          </header>
          <div className="preview-scroll">
            <table className="preview-tbl">
              <thead>
                <tr>
                  <th className="row-num">#</th>
                  {parsed.columns.map((c, i) => <th key={i}>{c || `列 ${i + 1}`}</th>)}
                </tr>
              </thead>
              <tbody>
                {parsed.data.slice(0, 200).map((row, ri) => (
                  <tr key={ri}>
                    <td className="row-num">{ri + 1}</td>
                    {parsed.columns.map((_, ci) => {
                      const v = row[ci];
                      const display = v instanceof Date ? v.toISOString().slice(0, 10) : String(v ?? "");
                      return <td key={ci}>{display}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {parsed.data.length > 200 && (
            <div style={{ padding: "10px 22px", color: "var(--ink-4)", fontSize: 12, borderTop: "1px solid var(--divider)" }}>
              仅预览前 200 行，应用后将解析全部 {parsed.rows.toLocaleString()} 行。
            </div>
          )}
        </div>
      )}

      <div className="upload-history">
        <header className="panel-head">
          <span className="panel-title">导入记录</span>
          <span className="panel-subtitle">最近 30 天</span>
        </header>
        <ul className="upload-history-list">
          {window.UPLOAD_HISTORY.map((h, i) => (
            <li key={i}>
              <span className="file-icon"><FileIcon /></span>
              <span className="file-name">{h.name}</span>
              <span className="spacer" />
              <span className="file-meta">{h.rows.toLocaleString()} 行 · {h.size}</span>
              <span className="file-meta" style={{ width: 140, textAlign: "right" }}>{h.when}</span>
              <button className="btn ghost sm">查看</button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

Object.assign(window, { ImportView });
