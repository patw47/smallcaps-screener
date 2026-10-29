import { useState, useEffect } from "react";
import { t, lang as savedLang, setLang } from "./i18n/index.js";
import { summarize } from "./journal.js";

// Page des alertes après publication de résultats (Epic 15 S5). Données : /api/alerts
// (journal du job du VPS) ; la logique (moyennes, états des cases) vit dans journal.js.
const C = { dim: "#8494a3", line: "#ffffff12", up: "#00ff9d", down: "#ff6b6b", warn: "#ffb84d" };
const th = { textAlign: "left", padding: "6px 10px", color: C.dim, fontWeight: 600, fontSize: 12, borderBottom: `1px solid ${C.line}`, whiteSpace: "nowrap" };
const td = { padding: "7px 10px", borderBottom: `1px solid ${C.line}`, fontSize: 13, verticalAlign: "top" };
const h2 = { fontSize: 15, margin: "0 0 10px", fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2 };
const note = { color: C.dim, fontSize: 12, lineHeight: 1.6, margin: "8px 0 0" };

const pct = (lang, v) => v == null ? "—"
  : new Intl.NumberFormat(lang, { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: "exceptZero" }).format(v) + " %";
const tone = (v) => (v == null ? undefined : v > 0 ? C.up : v < 0 ? C.down : undefined);

function Risk({ risk }) {
  if (!risk?.length) return <span style={{ color: C.dim }}>{t("risk.none")}</span>;
  return risk.map((m) => (
    <div key={m.code} title={t(`risk.tip.${m.code}`)} style={{ color: m.level === "high" ? C.down : C.warn, fontSize: 12 }}>
      {t(`risk.${m.code}`, { n: m.days })}{m.date ? ` · ${t("risk.since", { d: m.date })}` : ""}
    </div>
  ));
}

function Cell({ row, h, lang }) {
  const s = row.cells[h];
  if (s === "pending") return <span style={{ color: C.dim }}>{t("cell.pending")}</span>;
  if (s === "missing") return <span style={{ color: C.warn }} title={t("stats.missing.def")}>{t("cell.missing")}</span>;
  return (
    <span>
      <span style={{ color: tone(row[`ret_${h}`]) }}>{pct(lang, row[`ret_${h}`])}</span>
      <div style={{ color: C.dim, fontSize: 11 }}>{t("cell.iwm", { v: pct(lang, row[`iwm_${h}`]) })}</div>
    </span>
  );
}

function AlertTable({ rows, horizons, lang }) {
  return (
    <div style={{ overflowX: "auto" }}>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead><tr>
          <th style={th}>{t("col.ticker")}</th><th style={th}>{t("col.session")}</th>
          <th style={th}>{t("col.entry")}</th><th style={th}>{t("col.sue")}</th>
          {horizons.map((h) => <th key={h} style={th}>{t("col.h", { h })}</th>)}
          <th style={th}>{t("col.risk")}</th>
        </tr></thead>
        <tbody>{rows.map((r) => (
          <tr key={`${r.cik}-${r.period_end}`}>
            <td style={td}><a href={`https://finviz.com/quote.ashx?t=${encodeURIComponent(r.ticker)}`} target="_blank" rel="noreferrer" style={{ color: "#8fa8ff", fontWeight: 700 }}>{r.ticker}</a></td>
            <td style={td}>{r.session}</td><td style={td}>{r.entry}</td>
            <td style={td}>{r.sue?.toFixed(2)}</td>
            {horizons.map((h) => <td key={h} style={td}><Cell row={r} h={h} lang={lang} /></td>)}
            <td style={td}><Risk risk={r.risk} /></td>
          </tr>
        ))}</tbody>
      </table>
    </div>
  );
}

export default function App() {
  // Bascule FR/EN : le setState force le re-render, t() lit la langue du module.
  const [uiLang, setUiLang] = useState(savedLang);
  const switchLang = (l) => { setLang(l); setUiLang(l); };
  useEffect(() => { document.documentElement.lang = uiLang; }, [uiLang]);

  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    fetch("/api/alerts")
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then((p) => setData(summarize(p)))
      .catch((e) => setError(e.message));
  }, []);
  const horizons = data?.stats.map((s) => s.h) ?? [];
  const net = data?.stats.filter((s) => s.net != null) ?? [];

  return (
    <div style={{ minHeight: "100vh", background: "#070714", fontFamily: "'Segoe UI', sans-serif", color: "#e8e8ff", padding: "0 0 60px" }}>
      <div style={{ background: "linear-gradient(180deg, #0a0a20 0%, #070714 100%)", borderBottom: "1px solid #ffffff0a", padding: "24px 32px 20px" }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
          <div>
            <span style={{ fontFamily: "'Courier New', monospace", fontSize: 11, color: "#00ff9d", letterSpacing: 3, textTransform: "uppercase" }}>{t("header.radar")}</span>
            <h1 style={{ margin: "4px 0 0", fontSize: 24, fontWeight: 800, letterSpacing: -0.5 }}>
              {t("header.title.prefix")} <span style={{ color: "#4444cc" }}>{t("header.title.accent")}</span>
            </h1>
          </div>
          {/* Toggle FR/EN — choix persisté en localStorage, bascule sans reload */}
          <span style={{ display: "flex", gap: 4, background: "#16202b", border: "1px solid #1e2a36", borderRadius: 4, padding: "6px 8px" }}>
            {["fr", "en"].map(l => (
              <button key={l} onClick={() => switchLang(l)} aria-pressed={uiLang === l} style={{
                background: uiLang === l ? "#1c2f42" : "transparent",
                border: `1px solid ${uiLang === l ? "#2b4b66" : "#1e2a36"}`,
                borderRadius: 3, color: uiLang === l ? "#d7e0e8" : "#5a6a79",
                fontSize: 12, fontFamily: "monospace", padding: "2px 7px", cursor: "pointer",
                textTransform: "uppercase",
              }}>{l}</button>
            ))}
          </span>
        </div>
      </div>

      <section style={{ maxWidth: 1100, margin: "34px auto 0", padding: "0 24px" }}>
        <h2 style={h2}>{t("alerts.title")}</h2>
        <p style={{ color: C.dim, fontSize: 14, lineHeight: 1.6, margin: 0 }}>{t("alerts.intro")}</p>
        {error && <p style={{ color: C.down, fontSize: 14 }}>{t("alerts.error", { e: error })}</p>}
        {!data && !error && <p style={note}>{t("alerts.loading")}</p>}
      </section>

      {data && (
        <section style={{ maxWidth: 1100, margin: "30px auto 0", padding: "0 24px" }}>
          <h2 style={h2}>{t("alerts.today.title")}</h2>
          <p style={{ ...note, margin: "0 0 8px" }}>{t("alerts.today.session", { d: data.lastSession })}</p>
          {data.today.length
            ? <AlertTable rows={data.today} horizons={horizons} lang={uiLang} />
            : <p style={{ color: C.dim, fontSize: 14, margin: 0 }}>{t("alerts.today.empty", { d: data.lastSession })}</p>}
        </section>
      )}

      {data && (
        <section style={{ maxWidth: 1100, margin: "30px auto 0", padding: "0 24px" }}>
          <h2 style={h2}>{t("alerts.journal.title")}</h2>
          {data.empty ? <p style={{ color: C.dim, fontSize: 14, margin: 0 }}>{t("alerts.empty")}</p> : (
            <>
              <h3 style={{ fontSize: 13, margin: "0 0 6px", color: "#c8d0ff" }}>{t("stats.title")}</h3>
              <div style={{ overflowX: "auto" }}>
                <table style={{ borderCollapse: "collapse" }}>
                  <thead><tr>
                    {["stats.h", "stats.n", "stats.ret", "stats.iwm", "stats.excess", "stats.missing", "stats.pending"].map((k) => <th key={k} style={th}>{t(k)}</th>)}
                  </tr></thead>
                  <tbody>{data.stats.map((s) => (
                    <tr key={s.h}>
                      <td style={td}>{t("col.h", { h: s.h })}</td>
                      <td style={td}>{s.n}</td>
                      <td style={{ ...td, color: tone(s.ret) }}>{pct(uiLang, s.ret)}</td>
                      <td style={td}>{pct(uiLang, s.iwm)}</td>
                      <td style={{ ...td, color: tone(s.excess) }}>{pct(uiLang, s.excess)}</td>
                      <td style={{ ...td, color: s.missing ? C.warn : undefined }}>{s.missing}</td>
                      <td style={td}>{s.pending}</td>
                    </tr>
                  ))}</tbody>
                </table>
              </div>
              <p style={note}>{t("stats.realized.def")}</p>
              <p style={note}>{t("stats.missing.def")}</p>
              {net.length > 0 && (
                <div style={{ margin: "14px 0 0", padding: "10px 14px", border: `1px dashed ${C.line}`, borderRadius: 4 }}>
                  <div style={{ fontSize: 13, color: "#c8d0ff" }}>
                    {t("net.line", { list: net.map((s) => t("net.value", { v: pct(uiLang, s.net), h: s.h })).join(" · ") })}
                  </div>
                  <p style={note}>{t("net.def")}</p>
                </div>
              )}
              <div style={{ marginTop: 18 }}><AlertTable rows={data.rows} horizons={horizons} lang={uiLang} /></div>
            </>
          )}
        </section>
      )}
    </div>
  );
}
