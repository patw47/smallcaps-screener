import { useState, useEffect, useCallback } from "react";
import { t, fmt, lang as savedLang, setLang } from "./i18n/index.js";

const INSTRUMENTS = ["All", "Technology", "Healthcare", "Energy", "Industrials", "Consumer Cyclical"];

// ---------------------------------------------------------------------------
// Depuis l'Epic 6 S2, TOUT ce qui touche aux règles des deux familles (seuils,
// chiffres gelés des bandeaux, textes longs du glossaire UI) arrive de l'API via le
// bloc `display` du payload scan — plus aucune valeur en dur ici (gate : make
// check-edge). Depuis l'Epic 6 S3, toutes les chaînes UI vivent dans
// frontend/i18n/{fr,en}.json via t() (gate : make check-i18n).
// Epic 8 S3 : plus aucun numéro de version ni terme interne à l'écran (gate :
// make check-jargon). Les espaces de clés i18n suivent les noms publics —
// `market.*` = Purge de marché, `quiet.*` = Purge silencieuse ; les champs du
// payload (v4_cohort, v5.windows…) gardent leurs noms techniques.
// ---------------------------------------------------------------------------

// Nombre localisé (fr : virgule décimale + signe moins typographique).
const num = (x, d = 2) =>
  x == null ? "—" : t("locale") === "fr-FR"
    ? x.toFixed(d).replace(".", ",").replace("-", "−")
    : x.toFixed(d).replace("-", "−");

// ---------------------------------------------------------------------------
// Infobulle accessible (survol + focus clavier). Pointillé = explication dispo.
// Ne porte qu'UNE phrase de définition : le survol n'existe pas au tactile, les
// paragraphes vivent dans les blocs dépliables (Epic 8 S3).
// ---------------------------------------------------------------------------
function Tip({ tip, down, children, style }) {
  const [show, setShow] = useState(false);
  return (
    <span tabIndex={0}
      onMouseEnter={() => setShow(true)} onMouseLeave={() => setShow(false)}
      onFocus={() => setShow(true)} onBlur={() => setShow(false)}
      style={{ borderBottom: "1px dotted #5a6a79", cursor: "help", position: "relative", outline: "none", ...style }}>
      {children}
      {show && (
        <span style={{
          position: "absolute", left: "50%", transform: "translateX(-50%)",
          ...(down ? { top: "calc(100% + 8px)" } : { bottom: "calc(100% + 8px)" }),
          zIndex: 60, width: 300, maxWidth: "76vw",
          background: "#1c2836", color: "#d7e0e8", border: "1px solid #2b3b4c", borderRadius: 6,
          padding: "10px 13px", fontSize: 12.5, lineHeight: 1.55,
          fontFamily: "'Segoe UI', sans-serif", fontWeight: 400,
          textTransform: "none", letterSpacing: 0, whiteSpace: "normal", textAlign: "left",
          boxShadow: "0 10px 28px rgba(0,0,0,.55)",
        }}>{tip}</span>
      )}
    </span>
  );
}

const pctFmt = (x, digits = 1) => x == null ? "—" : `${x > 0 ? "+" : ""}${(x * 100).toFixed(digits)} %`;

// ---------------------------------------------------------------------------
// Mode présentation (Epic 8 S6) : l'API ne SERT PAS les seuils — la clé manque, elle
// n'arrive pas vide. L'écran se contente donc de constater l'absence : il dit que la
// règle a une valeur sans la montrer. Aucun drapeau à propager, et surtout aucun
// nombre qui n'a jamais atteint le navigateur ne peut s'afficher par accident.
// ---------------------------------------------------------------------------
const capped = (key, x, vars, hiddenKey = "chip.thrHidden") =>
  t(x == null ? hiddenKey : key, vars);

// Le mode présentation se demande dans l'URL de la page (…/?demo=1) et se décide côté
// service : l'instance peut l'imposer en permanence, une requête ne peut jamais le lever.
const DEMO_PARAM =
  typeof location !== "undefined" && new URLSearchParams(location.search).has("demo")
    ? "?demo=1" : "";

// ---------------------------------------------------------------------------
// Traduction des codes servis par l'API (Epic 8 S1). Le backend renvoie
// {code, variables} ; tout le texte affiché vient des dictionnaires i18n, dans
// la langue choisie par le client. `ns` = market ou quiet (mêmes codes, textes
// propres à chaque famille).
// ---------------------------------------------------------------------------
const noteText = (note, ns) => note?.code
  ? t(`${ns}.note.${note.code}`, { w: note.w, pct: pctFmt(note.mkt), n: note.n })
  : "";

const statusText = (s) => s?.code ? t(`status.${s.code}`, { d: s.d, cp: s.cp }) : "";

// Drapeau d'un titre. Deux formes coexistent : les drapeaux hérités sont des phrases
// fabriquées côté serveur, ceux de contexte (Epic 1 S7) sont des codes + variables
// traduits ici — comme les notes et statuts depuis l'Epic 8 S1.
const flagText = (f) => f?.code ? t(`flag.${f.code}`, { d: f.d }) : f;

const checkpointText = (c, thr) => c?.code
  ? t(`checkpoint.${c.code}${c.code === "week_one" && thr == null ? ".hidden" : ""}`,
    { h: c.h, thr: pctFmt(thr, 0) })
  : "—";

// ---------------------------------------------------------------------------
// Blocs pédagogiques communs aux deux familles (Epic 8 S3)
// ---------------------------------------------------------------------------
const RULE_STATE_COLOR = {
  ok: ["#00e096", "#1c4033"],
  blocked: ["#f0c040", "#4a3f1a"],
  pending: ["#8494a3", "#1e2a36"],
  unknown: ["#8494a3", "#1e2a36"],
};

const detailsStyle = {
  border: "1px solid #1e2a36", borderRadius: 8, background: "#0e141b",
  padding: "10px 14px", marginTop: 10,
};
const summaryStyle = {
  cursor: "pointer", color: "#d7e0e8", fontSize: 13, letterSpacing: 0.3,
};
const proseStyle = {
  color: "#8494a3", fontSize: 13, lineHeight: 1.6, margin: "8px 0 0",
};

// Règles d'entrée : toujours affichées, même sans liste — chaque règle porte son
// seuil, son état du jour et son explication (dépliable, clavier natif).
function RulesBlock({ items, blocking }) {
  return (
    <div style={{ border: "1px solid #1e2a36", borderRadius: 8, background: "#0e141b", padding: "12px 16px", margin: "12px 0" }}>
      <div style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: 0.8, color: "#5a6a79", marginBottom: 8 }}>
        {t("rules.title")}
      </div>
      {items.map(({ key, label, val, state, why }) => {
        const [color, borderColor] = RULE_STATE_COLOR[state];
        return (
          <details key={key} style={{ borderTop: "1px solid #16202b", padding: "7px 0" }}>
            <summary style={summaryStyle}>
              <span style={{ display: "inline-flex", flexWrap: "wrap", alignItems: "baseline", gap: 8 }}>
                <span>{label}</span>
                <span style={{ fontFamily: "monospace", fontSize: 12, color: "#8494a3" }}>{val}</span>
                <span style={{
                  fontSize: 10.5, textTransform: "uppercase", letterSpacing: 0.6, padding: "1px 7px",
                  borderRadius: 3, color, border: `1px solid ${borderColor}`, background: "#16202b",
                }}>{t(`rules.state.${state}`)}</span>
              </span>
            </summary>
            <p style={proseStyle}>{why}</p>
          </details>
        );
      })}
      {blocking && (
        <div style={{ fontSize: 12.5, color: "#8494a3", borderLeft: "2px solid #f0c040", padding: "4px 12px", marginTop: 10 }}>
          {blocking}
        </div>
      )}
    </div>
  );
}

// Paragraphes longs servis par l'API (chiffres gelés) — hors infobulle.
function MoreBlock({ items }) {
  const rows = items.filter(i => i.text);
  if (rows.length === 0) return null;
  return (
    <details style={detailsStyle}>
      <summary style={summaryStyle}>{t("rules.more")}</summary>
      {rows.map(({ label, text }) => (
        <p key={label} style={proseStyle}>
          <b style={{ color: "#d7e0e8" }}>{label}</b> — {text}
        </p>
      ))}
    </details>
  );
}

// Panneau d'explication : ouvert à la première visite, replié ensuite.
const PANEL_SEEN = "howToReadSeen";
function HowToRead() {
  const [open] = useState(() => {
    try { return !localStorage.getItem(PANEL_SEEN); } catch { return true; }
  });
  useEffect(() => { try { localStorage.setItem(PANEL_SEEN, "1"); } catch { /* mode privé */ } }, []);
  return (
    <details open={open} style={{ ...detailsStyle, marginTop: 16 }}>
      <summary style={{ ...summaryStyle, fontSize: 14, fontWeight: 650, color: "#e8e8ff" }}>
        {t("panel.title")}
      </summary>
      {["role", "frozen", "families", "survivors", "forward", "checkpoint"].map(k => (
        <p key={k} style={proseStyle}>{t(`panel.p.${k}`)}</p>
      ))}
    </details>
  );
}

// État d'une famille : la règle marché est connue au niveau de la section, les
// règles propres au titre ne sont évaluées que les jours où le marché baisse.
function ruleStates(mkt, count) {
  const mktState = mkt == null ? "unknown" : mkt < 0 ? "ok" : "blocked";
  const stockState = mktState === "ok" ? (count > 0 ? "ok" : "blocked") : "pending";
  const blocking = mktState === "unknown" ? t("rules.blocking.unknown")
    : mktState === "blocked" ? t("rules.blocking.mkt")
      : count === 0 ? t("rules.blocking.stock") : null;
  return { mktState, stockState, blocking };
}

// ---------------------------------------------------------------------------
// Étage 1 — Purge de marché (la seule liste à gain moyen mesuré positif)
// ---------------------------------------------------------------------------
function MarketCard({ entry, rank, total, dp4 }) {
  const g = dp4.gloss ?? {}, rules = dp4.rules ?? {};
  const depth = entry.resid != null && dp4.depth_scale > 0
    ? Math.min(100, Math.abs(Math.min(entry.resid, 0)) / dp4.depth_scale * 100) : 0;
  const first = rank === 0;
  return (
    <div style={{
      background: "#111820", border: `1px solid ${first ? "#2a5c48" : "#1e2a36"}`,
      boxShadow: first ? "0 0 0 1px #1c4033 inset" : "none",
      borderRadius: 8, padding: 16,
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: 0.5, fontFamily: "monospace", color: "#e8e8ff" }}>{entry.ticker}</span>
        <span style={{ color: "#8494a3", fontFamily: "monospace" }}>{entry.price} $</span>
        {first ? (
          <span style={{
            marginLeft: "auto", background: "#0e2c22", color: "#00e096", border: "1px solid #1c4033",
            borderRadius: 3, fontSize: 10.5, letterSpacing: 1, textTransform: "uppercase", padding: "2px 7px",
          }}>{t("market.first")}</span>
        ) : (
          <span style={{ marginLeft: "auto", color: "#5a6a79", fontSize: 12 }}>#{rank + 1} / {total}</span>
        )}
      </div>

      {first && g.first_pick && (
        <div style={{ marginTop: 10, fontSize: 13, color: "#d7e0e8", borderLeft: "2px solid #00e096", paddingLeft: 10 }}>
          {fmt(g.first_pick, { total, resid: pctFmt(entry.resid) })}
        </div>
      )}

      <div style={{ margin: "12px 0 4px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#8494a3", marginBottom: 4 }}>
          <span>{t("market.depth")}</span>
          <span style={{ fontFamily: "monospace" }}>{t("market.own", { pct: pctFmt(entry.resid) })}</span>
        </div>
        <div style={{ height: 6, background: "#182230", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ width: `${depth}%`, height: "100%", background: "linear-gradient(90deg,#0e6e52,#00e096)", borderRadius: 3 }} />
        </div>
        <div style={{ fontSize: 11.5, color: "#5a6a79", marginTop: 3 }}>
          <Tip tip={t("gloss.beta")}>{t("market.beta")}</Tip> {entry.beta ?? "—"} · {t("market.corr")} {entry.corr ?? "—"}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
        {[
          <>{t("chip.price")} <b style={{ color: "#d7e0e8" }}>{entry.price} $</b> {capped("chip.priceMax", rules.price_max, { x: rules.price_max })}</>,
          <>{t("chip.1m")} <b style={{ color: "#d7e0e8" }}>{pctFmt(entry.change_1m)}</b> {capped("chip.chgMax", rules.chg1m_max, { x: pctFmt(rules.chg1m_max, 0) })}</>,
          <>{t("chip.dil.pre")} <b style={{ color: "#d7e0e8" }}>{t("chip.dil.none")}</b> {t("chip.dil.post")}</>,
          <>{t("chip.mkt", { w: rules.mkt_window ?? "—" })} <b style={{ color: "#d7e0e8" }}>({pctFmt(entry.mkt21)})</b></>,
        ].map((text, i) => (
          <span key={i} style={{
            background: "#16202b", border: "1px solid #1c4033", borderRadius: 4,
            padding: "3px 8px", fontSize: 12, color: "#8494a3",
          }}>{text}</span>
        ))}
      </div>

      {first && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px dashed #1e2a36", fontSize: 12, color: "#8494a3" }}>
          <b style={{ color: "#d7e0e8" }}>{t("market.buy.title")}</b>{t("market.buy.body")}
        </div>
      )}
    </div>
  );
}

function MarketSection({ cohort, note, mkt21, prelist, dp4 }) {
  const g = dp4.gloss ?? {}, stats = dp4.stats ?? {}, rules = dp4.rules ?? {};
  const noteLabel = noteText(note, "market");
  const { mktState, stockState, blocking } = ruleStates(mkt21, cohort.length);
  const ruleItems = [
    { key: "price", label: t("market.rule.price"), val: capped("chip.priceMax", rules.price_max, { x: rules.price_max }), state: stockState, why: g.rule_price },
    { key: "dil", label: t("market.rule.dil"), val: t("chip.dil.post"), state: stockState, why: t("gloss.ruleDil") },
    { key: "chg", label: t("market.rule.chg"), val: capped("chip.chgMax", rules.chg1m_max, { x: pctFmt(rules.chg1m_max, 0) }), state: stockState, why: g.rule_chg },
    { key: "mkt", label: t("market.rule.mkt"), val: `${t("chip.win", { w: rules.mkt_window ?? "—" })} ${pctFmt(mkt21)}`, state: mktState, why: g.rule_mkt },
  ];
  return (
    <section style={{ marginTop: 30 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 style={{
          fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase",
          letterSpacing: 1.2, color: "#e8e8ff",
        }}>
          {t("market.section.title")} {cohort.length > 0 && t("market.section.startHere")}
        </h2>
        <Tip tip={t("research.tip")} style={{
          fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px",
          borderRadius: 3, border: "1px solid #4a3f1a", color: "#f0c040",
        }}>{t("research.badge")}</Tip>
      </div>

      <p style={{ ...proseStyle, marginTop: 8 }}>{t("market.intro")}</p>

      <RulesBlock items={ruleItems} blocking={blocking} />

      <div style={{
        display: "flex", flexWrap: "wrap", border: "1px solid #1e2a36", borderRadius: 6,
        background: "#0e141b", margin: "12px 0 6px", fontFamily: "monospace",
      }}>
        {[
          { v: stats.esperance || "—", vc: "#00e096", l: t("stats.esperance") },
          { v: stats.p_explode || "—", vc: "#d7e0e8", l: t("stats.pExplode") },
          { v: stats.p_crash || "—", vc: "#d7e0e8", l: t("stats.pCrash") },
          { v: stats.t || "—", vc: "#f0c040", l: t("stats.t") },
          { v: "4 / 4", vc: "#d7e0e8", l: t("stats.rules") },
        ].map((c, i) => (
          <div key={i} style={{ flex: "1 1 130px", padding: "10px 14px", borderRight: i < 4 ? "1px solid #1e2a36" : "none" }}>
            <b style={{ display: "block", fontSize: 17, fontWeight: 640, color: c.vc }}>{c.v}</b>
            <span style={{ fontSize: 11.5, color: "#8494a3", textTransform: "uppercase", letterSpacing: 0.6 }}>{c.l}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", margin: "10px 0 16px" }}>
        {t("market.disclaimer")}
      </div>

      <MoreBlock items={[
        { label: t("market.more.research"), text: g.research },
        { label: t("stats.rules"), text: g.regles },
        { label: t("stats.esperance"), text: g.esperance },
        { label: t("stats.pExplode"), text: g.p_explode },
        { label: t("stats.pCrash"), text: g.p_crash },
        { label: t("stats.t"), text: g.tstat },
        { label: t("market.more.depth"), text: g.profondeur },
        { label: t("tracking.h.checkpoint"), text: g.checkpoint },
      ]} />

      {cohort.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14, marginTop: 14 }}>
          {cohort.map((e, i) => <MarketCard key={e.ticker} entry={e} rank={i} total={cohort.length} dp4={dp4} />)}
        </div>
      ) : (
        <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b", marginTop: 14 }}>
          <b style={{ color: "#d7e0e8" }}>{noteLabel || t("market.emptyNote")}</b>{" "}
          {t("market.emptyInfo")}
          {prelist.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Tip tip={t("gloss.prelist")} style={{ fontSize: 12, color: "#8494a3" }}>{t("market.prelist")}</Tip>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                {prelist.map(p => (
                  <span key={p.ticker} style={{
                    background: "#16202b", border: "1px solid #1e2a36", borderRadius: 4,
                    padding: "3px 8px", fontSize: 12, fontFamily: "monospace", color: "#8494a3",
                  }}>{p.ticker} · {p.price} $ · {pctFmt(p.change_1m)}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Étage 1 bis — Purge silencieuse (fenêtre pilotée par le sélecteur du header).
// Purement additive : la Purge de marché reste l'étage de référence.
// ---------------------------------------------------------------------------
function QuietCard({ entry, win, rank, total, dp5 }) {
  const rules = dp5.rules ?? {};
  const first = rank === 0;
  return (
    <div style={{
      background: "#111820", border: `1px solid ${first ? "#2a5c48" : "#1e2a36"}`,
      boxShadow: first ? "0 0 0 1px #1c4033 inset" : "none",
      borderRadius: 8, padding: 16,
    }}>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontSize: 18, fontWeight: 700, letterSpacing: 0.5, fontFamily: "monospace", color: "#e8e8ff" }}>{entry.ticker}</span>
        <span style={{ color: "#8494a3", fontFamily: "monospace" }}>{entry.price} $</span>
        {first ? (
          <span style={{
            marginLeft: "auto", background: "#0e2c22", color: "#00e096", border: "1px solid #1c4033",
            borderRadius: 3, fontSize: 10.5, letterSpacing: 1, textTransform: "uppercase", padding: "2px 7px",
          }}>{t("quiet.first")}</span>
        ) : (
          <span style={{ marginLeft: "auto", color: "#5a6a79", fontSize: 12 }}>#{rank + 1} / {total}</span>
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
        {[
          <>{t("chip.price")} <b style={{ color: "#d7e0e8" }}>{entry.price} $</b> {capped("chip.priceMax", rules.price_max, { x: rules.price_max })}</>,
          <>{t("chip.win", { w: win })} <b style={{ color: "#d7e0e8" }}>{pctFmt(entry.chg)}</b> {capped("chip.chgMax", rules.chg_max, { x: pctFmt(rules.chg_max, 0) })}</>,
          <>{t("chip.dil.pre")} <b style={{ color: "#d7e0e8" }}>{t("chip.dil.none")}</b> {t("chip.dil.post")}</>,
          <>{t("chip.mkt", { w: win })} <b style={{ color: "#d7e0e8" }}>({pctFmt(entry.mkt)})</b></>,
          <>{t("chip.flow")} <b style={{ color: "#d7e0e8" }}>{entry.cmf}</b> {capped("chip.flowMin", rules.cmf_min, { x: num(rules.cmf_min) })}</>,
          <>{t("chip.vol")} <b style={{ color: "#d7e0e8" }}>{entry.vol_calm}×</b> {capped("chip.volMax", rules.volcalm_max, { x: num(rules.volcalm_max) })}</>,
        ].map((text, i) => (
          <span key={i} style={{
            background: "#16202b", border: "1px solid #1c4033", borderRadius: 4,
            padding: "3px 8px", fontSize: 12, color: "#8494a3",
          }}>{text}</span>
        ))}
      </div>

      {first && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px dashed #1e2a36", fontSize: 12, color: "#8494a3" }}>
          <b style={{ color: "#d7e0e8" }}>{t("market.buy.title")}</b>{t("quiet.buy.body")}
        </div>
      )}
    </div>
  );
}

function QuietSection({ v5, win, dp4, dp5 }) {
  const g = dp5.gloss ?? {}, g4 = dp4.gloss ?? {}, rules = dp5.rules ?? {};
  const block = v5.windows?.[String(win)] ?? { mkt: null, cohort: [], prelist: [], note: null };
  const stats = dp5.stats?.[String(win)] ?? {};
  const cohort = block.cohort ?? [];
  const prelist = block.prelist ?? [];
  const { mktState, stockState, blocking } = ruleStates(block.mkt, cohort.length);
  const ruleItems = [
    { key: "price", label: t("quiet.rule.price"), val: capped("chip.priceMax", rules.price_max, { x: rules.price_max }), state: stockState, why: g4.rule_price },
    { key: "dil", label: t("quiet.rule.dil"), val: t("chip.dil.post"), state: stockState, why: t("gloss.ruleDil") },
    { key: "chg", label: t("quiet.rule.chg"), val: capped("chip.chgMax", rules.chg_max, { x: pctFmt(rules.chg_max, 0) }), state: stockState, why: g.chg },
    { key: "mkt", label: t("quiet.rule.mkt"), val: `${t("chip.win", { w: win })} ${pctFmt(block.mkt)}`, state: mktState, why: g4.rule_mkt },
    { key: "flow", label: t("quiet.rule.flow"), val: capped("chip.flowMin", rules.cmf_min, { x: num(rules.cmf_min) }), state: stockState, why: g.cmf },
    { key: "vol", label: t("quiet.rule.vol"), val: capped("chip.volMax", rules.volcalm_max, { x: num(rules.volcalm_max) }), state: stockState, why: g.vol_calme },
  ];
  return (
    <section style={{ marginTop: 30 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
          {t("quiet.section.title", { w: win })}
        </h2>
        <Tip tip={t("research.tip")} style={{
          fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px",
          borderRadius: 3, border: "1px solid #4a3f1a", color: "#f0c040",
        }}>{t("research.badge")}</Tip>
      </div>

      <p style={{ ...proseStyle, marginTop: 8 }}>{t("quiet.intro")}</p>

      <RulesBlock items={ruleItems} blocking={blocking} />

      <div style={{
        display: "flex", flexWrap: "wrap", border: "1px solid #1e2a36", borderRadius: 6,
        background: "#0e141b", margin: "12px 0 6px", fontFamily: "monospace",
      }}>
        {[
          { v: stats.esperance || "—", vc: "#00e096", l: t("stats.esperance") },
          { v: stats.mediane || "—", vc: "#d7e0e8", l: t("stats.mediane") },
          { v: stats.p_explode || "—", vc: "#d7e0e8", l: t("stats.pExplode") },
          { v: stats.p_crash || "—", vc: "#d7e0e8", l: t("stats.pCrash") },
          { v: stats.t || "—", vc: "#f0c040", l: t("stats.t") },
          { v: "6 / 6", vc: "#d7e0e8", l: t("stats.rules") },
        ].map((c, i) => (
          <div key={i} style={{ flex: "1 1 120px", padding: "10px 14px", borderRight: i < 5 ? "1px solid #1e2a36" : "none" }}>
            <b style={{ display: "block", fontSize: 17, fontWeight: 640, color: c.vc }}>{c.v}</b>
            <span style={{ fontSize: 11.5, color: "#8494a3", textTransform: "uppercase", letterSpacing: 0.6 }}>{c.l}</span>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", margin: "10px 0 16px" }}>
        {t("quiet.disclaimer", { n: stats.n ?? "—" })}
      </div>

      <MoreBlock items={[
        { label: t("quiet.more.research"), text: g.research },
        { label: t("stats.rules"), text: g.regles },
        { label: t("stats.mediane"), text: g.mediane },
        { label: t("stats.pCrash"), text: g.crash },
        { label: t("quiet.more.windows"), text: g.mkt_switch },
        { label: t("quiet.more.flash"), text: g.flash },
        { label: t("quiet.more.tracking"), text: g.tracking },
      ]} />

      {cohort.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14, marginTop: 14 }}>
          {cohort.map((e, i) => <QuietCard key={e.ticker} entry={e} win={win} rank={i} total={cohort.length} dp5={dp5} />)}
        </div>
      ) : (
        <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b", marginTop: 14 }}>
          <b style={{ color: "#d7e0e8" }}>{noteText(block.note, "quiet") || t("quiet.emptyNote")}</b>{" "}
          {t("quiet.emptyInfo")}
          {prelist.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Tip tip={t("gloss.prelist")} style={{ fontSize: 12, color: "#8494a3" }}>{t("quiet.prelist", { w: win })}</Tip>
              <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
                {prelist.map(p => (
                  <span key={p.ticker} style={{
                    background: "#16202b", border: "1px solid #1e2a36", borderRadius: 4,
                    padding: "3px 8px", fontSize: 12, fontFamily: "monospace", color: "#8494a3",
                  }}>{p.ticker} · {p.price} $ · {pctFmt(p.chg)}</span>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

    </section>
  );
}

// ---------------------------------------------------------------------------
// Étage 2 — cycle de vie des titres suivis (information, jamais un ordre de vente)
// L'API sert des CODES de statut/checkpoint (Epic 8 S1) et une PHASE de cycle de
// vie (Epic 8 S4) : les branches ci-dessous comparent des codes, jamais des
// chaînes traduites. Le classement en trois blocs vient de `phase`, calculée et
// testée côté backend — l'écran ne la redevine pas.
// ---------------------------------------------------------------------------
const STATUS_COLORS = {
  above: ["#00e096", "#1c4033"], explosion: ["#00e096", "#1c4033"],
  below: ["#f0c040", "#4a3f1a"],
  crash: ["#ff6b6b", "#4a2626"], no_data: ["#ff6b6b", "#4a2626"],
};
const STATUS_PREFIX = { explosion: "💥 ", no_data: "⚠ " };

function statusChip(row) {
  const base = { display: "inline-block", padding: "2px 8px", borderRadius: 3, fontSize: 11.5, border: "1px solid #1e2a36", background: "#16202b", whiteSpace: "nowrap" };
  const [color, borderColor] = STATUS_COLORS[row.status?.code] ?? ["#8494a3", "#1e2a36"];
  return <span style={{ ...base, color, borderColor }}>
    {STATUS_PREFIX[row.status?.code] ?? ""}{statusText(row.status)}
  </span>;
}

function probText(row, g) {
  if (row.status?.code === "above") return <span style={{ color: "#00e096" }}>{g.checkpoint_above || "—"}</span>;
  if (row.status?.code === "below") return <span style={{ color: "#ff6b6b" }}>{g.checkpoint_below || "—"}</span>;
  if (row.checkpoint?.code === "window_closed") return <>{t("tracking.endOfWindow")} <b>{pctFmt(row.ret_63)}</b></>;
  return "—";
}

// Phase d'une ligne. Servie par l'API ; le repli dérive des codes déjà présents,
// pour un résultat de scan mis en cache avant l'arrivée du champ.
const phaseOf = (r) => r.phase
  ?? (r.days_held == null ? "no_data"
    : r.checkpoint?.code === "window_closed" ? "closed" : "open");

// Frise : entrée → point de contrôle (trait jaune) → clôture ; le remplissage est
// la position courante, le texte dit ce qui reste à observer.
function Lifecycle({ row, cal }) {
  const h = cal.horizon ?? 0, cp = cal.day ?? 0;
  const done = phaseOf(row) === "closed";
  const pct = h > 0 && row.days_held != null ? Math.min(100, row.days_held / h * 100) : 0;
  const cpPct = h > 0 ? Math.min(100, cp / h * 100) : 0;
  const left = done ? t("tracking.done")
    : row.days_left == null ? "—"
      : t(`tracking.left.${row.days_left === 1 ? "one" : "many"}`, { n: row.days_left });
  return (
    <div style={{ minWidth: 150 }}>
      <div role="img" aria-label={t("tracking.calendar", { cp, h })}
        style={{ position: "relative", height: 6, background: "#182230", borderRadius: 3, margin: "2px 0 5px" }}>
        <div style={{
          width: `${pct}%`, height: "100%", borderRadius: 3,
          background: done ? "#3a4a5a" : "linear-gradient(90deg,#0e6e52,#00e096)",
        }} />
        <span style={{ position: "absolute", left: `${cpPct}%`, top: -2, width: 1, height: 10, background: "#f0c040" }} />
      </div>
      <span style={{ fontSize: 11.5, color: "#8494a3", fontFamily: "'Segoe UI', sans-serif" }}>
        {checkpointText(row.checkpoint, cal.thr)} · {left}
      </span>
    </div>
  );
}

const CELL = { padding: "10px 14px", borderBottom: "1px solid #1e2a36" };
const RIGHT = new Set(["entryPrice", "today"]);

function TrackingTable({ rows, dp, windowCol }) {
  const g = dp.gloss ?? {}, cal = dp.checkpoint ?? {};
  const headers = ["ticker", ...(windowCol ? ["window"] : []),
    "entryDate", "entryPrice", "today", "lifecycle", "position", "probs"];
  return (
    <div style={{ overflowX: "auto", border: "1px solid #1e2a36", borderRadius: 8, background: "#111820" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5, fontFamily: "monospace" }}>
        <thead>
          <tr>
            {headers.map(h => (
              <th key={h} style={{
                color: "#8494a3", fontWeight: 600, textTransform: "uppercase", fontSize: 11,
                letterSpacing: 0.7, textAlign: RIGHT.has(h) ? "right" : "left", ...CELL,
              }}>
                {h === "lifecycle" && g.tip_checkpoint
                  ? <Tip down tip={g.tip_checkpoint}>{t("tracking.h.lifecycle")}</Tip>
                  : t(`tracking.h.${h}`)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={`${r.ticker}-${r.window ?? ""}-${r.entry_date}`}>
              <td style={{ ...CELL, fontWeight: 700, color: "#e8e8ff" }}>{r.ticker}</td>
              {windowCol && <td style={{ ...CELL, color: "#8494a3" }}>{t("chip.win", { w: r.window })}</td>}
              <td style={{ ...CELL, color: "#8494a3" }}>{r.entry_date}</td>
              <td style={{ ...CELL, textAlign: "right", color: "#d7e0e8" }}>{r.entry_price} $</td>
              <td style={{ ...CELL, textAlign: "right", color: r.ret == null ? "#8494a3" : r.ret >= 0 ? "#00e096" : "#ff6b6b" }}>
                {r.ret == null ? "—" : `${pctFmt(r.ret)} · ${t("tracking.day", { d: r.days_held })}`}
              </td>
              <td style={CELL}><Lifecycle row={r} cal={cal} /></td>
              <td style={CELL}>{statusChip(r)}</td>
              <td style={{ ...CELL, color: "#d7e0e8", fontFamily: "'Segoe UI', sans-serif", fontSize: 12.5 }}>{probText(r, g)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// Un bloc par phase. « En observation » est toujours déployé — c'est le panier
// vivant ; les deux autres sont repliés (élément natif, aucun script).
function TrackingGroup({ phase, rows, dp, windowCol }) {
  if (rows.length === 0) return null;
  const head = t(`tracking.group.${phase}`, { n: rows.length });
  const table = <TrackingTable rows={rows} dp={dp} windowCol={windowCol} />;
  if (phase === "open") {
    return (
      <div style={{ marginTop: 14 }}>
        <div style={{ fontSize: 11.5, textTransform: "uppercase", letterSpacing: 0.8, color: "#5a6a79", marginBottom: 6 }}>
          {head}
        </div>
        {table}
      </div>
    );
  }
  return (
    <details style={detailsStyle}>
      <summary style={summaryStyle}>{head}</summary>
      <div style={{ marginTop: 10 }}>{table}</div>
    </details>
  );
}

const PHASES = ["open", "closed", "no_data"];

function TrackingSection({ tracking, dp, family, windowCol }) {
  const g = dp.gloss ?? {}, cal = dp.checkpoint ?? {};
  const groups = { open: [], closed: [], no_data: [] };
  // Phase inconnue (backend en avance sur l'écran) → rangée avec les lignes sans
  // données plutôt que de faire planter la section entière.
  tracking.forEach(r => (groups[phaseOf(r)] ?? groups.no_data).push(r));
  return (
    <section style={{ marginTop: 34 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
          {t("tracking.title")}
        </h2>
        <span style={{ color: "#d7e0e8", fontSize: 13 }}>{family}</span>
        <span style={{ color: "#8494a3", fontSize: 13 }}>{t("tracking.subtitle")}</span>
      </div>

      <p style={{ ...proseStyle, margin: 0 }}>{t("tracking.calendar", { cp: cal.day ?? "—", h: cal.horizon ?? "—" })}</p>
      <p style={proseStyle}>{t("tracking.notAnExit")}</p>

      {tracking.length === 0 ? (
        <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b", marginTop: 12 }}>
          {t("tracking.empty")}
        </div>
      ) : (
        <>
          {groups.open.length === 0 && (
            <div style={{ fontSize: 12.5, color: "#8494a3", borderLeft: "2px solid #1e2a36", padding: "4px 12px", marginTop: 12 }}>
              {t("tracking.noOpen")}
            </div>
          )}
          {PHASES.map(p => (
            <TrackingGroup key={p} phase={p} rows={groups[p]} dp={dp} windowCol={windowCol} />
          ))}
        </>
      )}

      {tracking.length > 0 && g.stops_footer && (
        <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", marginTop: 10 }}>
          {g.stops_footer}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Étage 2 bis — résultats RÉELS par profil (Epic 8 S5). Alimenté par
// /api/performance, calculé depuis l'origine et jamais affiché jusqu'ici : c'est
// la seule mesure non biaisée par la survie. Ni le calcul ni l'endpoint ne
// changent — on affiche ce qui existe déjà.
//
// L'appel vit ICI, pas dans App : une réponse vide, un historique absent ou une
// erreur réseau laissent tout le reste de la page intact (aucun état partagé,
// aucun throw qui remonte). Le cadre de lecture est rendu dans tous les cas —
// sans lui, un petit échantillon a l'air de trancher quelque chose.
// ---------------------------------------------------------------------------
const PERF_SLEEVES = ["overall", "fusee", "phenix", "unknown"];

function PerfSection() {
  const [perf, setPerf] = useState(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    fetch("/api/performance")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(setPerf)
      .catch(() => setFailed(true));
  }, []);

  const sleeves = perf?.sleeves ?? {};
  // Réponse vide, historique absent, bloc `sleeves` manquant : tous ces cas
  // arrivent ici avec 0 ligne suivie et sortent par le même message.
  const empty = !perf || (perf.n_tracked ?? 0) === 0;
  // "unknown" n'apparaît que s'il porte des lignes : sinon la colonne raconte une
  // catégorie vide au lieu d'un résultat.
  const rows = PERF_SLEEVES.filter(k => sleeves[k] && (k !== "unknown" || sleeves[k].n > 0));
  const asOf = perf?.as_of ? new Date(perf.as_of) : null;
  const note = (text) => (
    <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b", marginTop: 12 }}>
      {text}
    </div>
  );

  return (
    <section style={{ marginTop: 34 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
          {t("perf.title")}
        </h2>
        <span style={{ color: "#8494a3", fontSize: 13 }}>{t("perf.subtitle")}</span>
      </div>

      <p style={{ ...proseStyle, margin: 0 }}>{t("perf.intro")}</p>

      {failed ? note(t("perf.unavailable"))
        : empty || rows.length === 0 ? note(t("perf.empty"))
          : (
            <>
              <div style={{ overflowX: "auto", border: "1px solid #1e2a36", borderRadius: 8, background: "#111820", marginTop: 12 }}>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5, fontFamily: "monospace" }}>
                  <thead>
                    <tr>
                      {["sleeve", "n", "mean", "median", "excess", "up50", "up100"].map((h, i) => (
                        <th key={h} style={{
                          color: "#8494a3", fontWeight: 600, textTransform: "uppercase", fontSize: 11,
                          letterSpacing: 0.7, textAlign: i === 0 ? "left" : "right", ...CELL,
                        }}>{t(`perf.h.${h}`)}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {rows.map(k => {
                      const s = sleeves[k];
                      return (
                        <tr key={k}>
                          <td style={{ ...CELL, color: "#e8e8ff", fontFamily: "'Segoe UI', sans-serif" }}>{t(`perf.sleeve.${k}`)}</td>
                          <td style={{ ...CELL, textAlign: "right", color: "#d7e0e8" }}>{s.n}</td>
                          {[s.mean, s.median, s.excess_mean].map((v, i) => (
                            <td key={i} style={{ ...CELL, textAlign: "right", color: v == null ? "#8494a3" : v >= 0 ? "#00e096" : "#ff6b6b" }}>
                              {pctFmt(v)}
                            </td>
                          ))}
                          <td style={{ ...CELL, textAlign: "right", color: "#d7e0e8" }}>{s.n_up50 ?? "—"}</td>
                          <td style={{ ...CELL, textAlign: "right", color: "#d7e0e8" }}>{s.n_up100 ?? "—"}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              <p style={{ ...proseStyle, fontSize: 12.5 }}>
                {t("perf.counts", {
                  tracked: perf.n_tracked ?? "—", picks: perf.n_picks ?? "—",
                  when: asOf ? asOf.toLocaleDateString(t("locale")) : "—",
                })}
              </p>
              <p style={{ ...proseStyle, fontSize: 12.5, marginTop: 4 }}>{t("perf.note.overlap")}</p>
              {rows.includes("unknown") && (
                <p style={{ ...proseStyle, fontSize: 12.5, marginTop: 4 }}>{t("perf.note.unknown")}</p>
              )}
            </>
          )}

      {["fast", "slow", "verdict"].map(k => (
        <p key={k} style={{ ...proseStyle, borderLeft: "2px solid #1e2a36", paddingLeft: 12 }}>
          {t(`perf.frame.${k}`)}
        </p>
      ))}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Étage 3 — zones extrêmes (Fusée / Phénix : hypothèse réfutée, matière à
// recherche humaine — ni liste d'achat, ni signal d'exclusion)
// ---------------------------------------------------------------------------
const PROFILE_STYLE = {
  fusee: { emoji: "🚀", fg: "#00e69a", bg: "#00ff9d18", bd: "#00ff9d44" },
  phenix: { emoji: "🔥", fg: "#ff9966", bg: "#ff6b6b18", bd: "#ff6b6b44" },
};

function profileStats(kind) {
  return kind === "fusee" ? (
    <>{t("profile.double")} <b>{t("profile.fusee.doubleVal")}</b> · {t("profile.esperance")} <b style={{ color: "#ff6b6b" }}>{t("profile.fusee.espVal")}</b></>
  ) : (
    <>{t("profile.double")} <b style={{ color: "#00e096" }}>{t("profile.phenix.doubleVal")}</b> {t("profile.phenix.crashLabel")} <b style={{ color: "#ff6b6b" }}>{t("profile.phenix.crashVal")}</b> · {t("profile.esperance")} <b style={{ color: "#ff6b6b" }}>{t("profile.phenix.espVal")}</b></>
  );
}

function ProfileBadge({ kind, strength, event }) {
  const c = PROFILE_STYLE[kind];
  const pct = strength != null ? Math.round(strength * 100) : null;
  return (
    <Tip tip={t(`gloss.${kind}`)} style={{
      display: "inline-flex", alignItems: "center", gap: 5, flexWrap: "wrap",
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`, borderBottom: `1px solid ${c.bd}`,
      borderRadius: 20, padding: "4px 11px", fontSize: 12, fontWeight: 700,
      fontFamily: "monospace", letterSpacing: 0.3,
    }}>
      <span>{c.emoji} {t(`profile.${kind}.label`)}</span>
      {pct != null && <span style={{ opacity: 0.7, fontWeight: 600 }}>· {pct}</span>}
      {event && <span style={{ color: "#ffd24d" }}>⚡</span>}
      <span style={{
        background: "#ffcc6622", color: "#ffcc66", fontSize: 9, fontWeight: 700,
        padding: "1px 6px", borderRadius: 10, marginLeft: 3,
        textTransform: "uppercase", letterSpacing: 0.4,
      }}>{t("badge.refuted")}</span>
    </Tip>
  );
}

function StockCard({ stock, onAnalyze, analysis, isLoading }) {
  const changeColor = (v) => v >= 0 ? "#00e096" : "#ff6b6b";
  const profileKind = stock.isPhenix ? "phenix" : stock.isFusee ? "fusee" : null;

  return (
    <div style={{
      background: "linear-gradient(135deg, #0d0d1a 0%, #111128 100%)",
      border: "1px solid #ffffff11", borderRadius: 12, padding: "20px 22px", position: "relative",
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontFamily: "'Courier New', monospace", fontSize: 18, fontWeight: 700, color: "#e8e8ff", letterSpacing: 1 }}>{stock.ticker}</span>
            <span style={{ background: "#ffffff0d", color: "#8888aa", fontSize: 10, padding: "2px 8px", borderRadius: 20, fontFamily: "monospace" }}>{stock.sector}</span>
          </div>
          <div style={{ color: "#5555aa", fontSize: 12, marginTop: 3 }}>{stock.name}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#e8e8ff", fontFamily: "monospace" }}>${stock.price}</div>
          <div style={{ fontSize: 12, color: changeColor(stock.change1d), fontFamily: "monospace" }}>{stock.change1d > 0 ? "+" : ""}{stock.change1d}{t("card.today")}</div>
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {stock.isFusee && <ProfileBadge kind="fusee" strength={stock.fuseeStrength} event={stock.fuseeEvent} />}
        {stock.isPhenix && <ProfileBadge kind="phenix" strength={stock.phenixStrength} />}
      </div>

      {profileKind && (
        <div style={{ fontSize: 12.5, color: "#8494a3", marginBottom: 12 }}>
          {profileStats(profileKind)}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
        {[
          { label: t("card.mktCap"), value: `$${stock.marketCap}M` },
          { label: t("card.volRatio"), value: `${stock.volumeRatio}x` },
          { label: t("card.1m"), value: `${stock.change1m > 0 ? "+" : ""}${stock.change1m}%`, color: changeColor(stock.change1m) },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: "#ffffff05", borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ color: "#44446a", fontSize: 10, marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
            <div style={{ color: color || "#c0c0e0", fontSize: 13, fontWeight: 600, fontFamily: "monospace" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Dossier de risque : faits tirés des dépôts officiels, sémantique mesurée */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 14 }}>
        {stock.survivalRisk && (
          <Tip tip={t("gloss.goingConcern")} style={{
            background: "#f0c04012", color: "#f0c040", fontSize: 10, padding: "3px 8px",
            borderRadius: 20, border: "1px solid #f0c04033",
          }}>{t("card.distress")}</Tip>
        )}
        {stock.flags.map((f, i) => {
          const texte = flagText(f);
          return (
            <Tip key={f?.code ?? `${i}`} tip={/dilution/i.test(texte) ? t("gloss.dilution") : texte} style={{
              background: "#ff6b6b0d", color: "#ff6b6b", fontSize: 10, padding: "3px 8px",
              borderRadius: 20, border: "1px solid #ff6b6b22",
            }}>⚠ {texte}</Tip>
          );
        })}
        {stock.positives.map(p => (
          <span key={p} style={{ background: "#00ff9d0d", color: "#00cc7a", fontSize: 10, padding: "3px 8px", borderRadius: 20, border: "1px solid #00ff9d22" }}>✓ {p}</span>
        ))}
      </div>

      {analysis && (
        <div style={{ background: "#0a0a1f", border: "1px solid #2222aa44", borderRadius: 8, padding: "14px 16px", marginBottom: 14 }}>
          <div style={{ color: "#6666dd", fontSize: 10, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>{t("analyze.header")}</div>
          <div style={{ color: "#c0c0e0", fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{analysis}</div>
        </div>
      )}

      <button
        onClick={() => onAnalyze(stock)}
        disabled={isLoading}
        style={{
          width: "100%", padding: "10px",
          background: isLoading ? "#1a1a3a" : "linear-gradient(90deg, #1a1a4a, #2a2a6a)",
          border: "1px solid #3333aa", borderRadius: 8,
          color: isLoading ? "#4444aa" : "#8888ff",
          fontSize: 12, fontFamily: "monospace",
          cursor: isLoading ? "not-allowed" : "pointer", letterSpacing: 0.5,
        }}
      >
        {isLoading ? t("analyze.loading") : analysis ? t("analyze.again") : t("analyze.btn")}
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Application
// ---------------------------------------------------------------------------
function normalizeStocks(raw) {
  return raw.map(s => ({
    ticker: s.ticker, name: s.name, sector: s.sector, price: s.price,
    change1d: s.change_1d != null ? +(s.change_1d * 100).toFixed(2) : 0,
    change1m: s.change_1m != null ? +(s.change_1m * 100).toFixed(2) : 0,
    marketCap: s.market_cap_m, volumeRatio: s.vol_ratio,
    positives: s.positives ?? [], flags: s.flags ?? [],
    profile: s.profile ?? null,
    isFusee: !!s.is_fusee, isPhenix: !!s.is_phenix, fuseeEvent: !!s.fusee_event,
    fuseeStrength: s.fusee_strength ?? null, phenixStrength: s.phenix_strength ?? null,
    profileStrength: s.profile_strength ?? 0,
    survivalRisk: !!s.survival_risk,
  }));
}

export default function App() {
  const [stocks, setStocks] = useState([]);
  const [v4, setV4] = useState({ cohort: [], note: null, mkt21: null, prelist: [], tracking: [] });
  const [v5, setV5] = useState({ windows: {}, flash: false, flash_ret3: null, tracking: [] });
  const [display, setDisplay] = useState({});  // seuils/textes servis par l'API (Epic 6 S2)
  const [mktWin, setMktWin] = useState(21);   // 7/14/21
  // Bascule FR/EN : le setState force le re-render, t() lit la langue du module.
  const [uiLang, setUiLang] = useState(savedLang);
  const switchLang = (l) => { setLang(l); setUiLang(l); };
  useEffect(() => { document.documentElement.lang = uiLang; }, [uiLang]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [sector, setSector] = useState("All");
  const [profile, setProfile] = useState("all");
  const [analyses, setAnalyses] = useState({});
  const [loadingTickers, setLoadingTickers] = useState({});
  const [lastScan, setLastScan] = useState(null);

  const fetchData = useCallback(() => {
    return fetch(`/api/scan${DEMO_PARAM}`)
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(json => {
        setStocks(normalizeStocks(json.stocks ?? []));
        setV4({
          cohort: json.v4_cohort ?? [], note: json.v4_note ?? null,
          mkt21: json.v4_mkt21 ?? null, prelist: json.v4_prelist ?? [],
          tracking: json.v4_tracking ?? [],
        });
        setV5({
          windows: json.v5?.windows ?? {}, flash: !!json.v5?.flash,
          flash_ret3: json.v5?.flash_ret3 ?? null, tracking: json.v5?.tracking ?? [],
        });
        setDisplay(json.display ?? {});
        if (json.scanned_at) setLastScan(new Date(json.scanned_at));
      })
      .catch(console.error);
  }, []);

  useEffect(() => { fetchData().finally(() => setLoading(false)); }, [fetchData]);

  const runScan = () => {
    setScanning(true);
    fetch("/api/scan/force", { method: "POST" })
      .then(() => fetchData()).catch(console.error).finally(() => setScanning(false));
  };

  const analyzeStock = useCallback(async (stock) => {
    setLoadingTickers(prev => ({ ...prev, [stock.ticker]: true }));
    const prompt = t("analyze.prompt", {
      ticker: stock.ticker, name: stock.name, sector: stock.sector, price: stock.price,
      marketCap: stock.marketCap, volumeRatio: stock.volumeRatio, change1m: stock.change1m,
      profile: t(`analyze.profile.${stock.isPhenix ? "phenix" : stock.isFusee ? "fusee" : "none"}`),
      positives: stock.positives.join(", ") || "—",
      flags: stock.flags.length > 0 ? stock.flags.map(flagText).join(", ") : t("analyze.none"),
    });

    try {
      const response = await fetch("https://api.anthropic.com/v1/messages", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "x-api-key": import.meta.env.VITE_ANTHROPIC_API_KEY,
          "anthropic-version": "2023-06-01",
          "anthropic-dangerous-direct-browser-access": "true",
        },
        body: JSON.stringify({
          model: "claude-sonnet-4-6",
          max_tokens: 2000,
          tools: [{ type: "web_search_20260209", name: "web_search", max_uses: 3 }],
          messages: [{ role: "user", content: prompt }]
        })
      });
      const data = await response.json();
      // Avec web_search la réponse alterne blocs texte et blocs de recherche : concaténer tous les textes
      const text = data.content?.filter(b => b.type === "text").map(b => b.text).join("") || t("analyze.unavailable");
      setAnalyses(prev => ({ ...prev, [stock.ticker]: text }));
    } catch (e) {
      setAnalyses(prev => ({ ...prev, [stock.ticker]: t("analyze.error") }));
    }
    setLoadingTickers(prev => ({ ...prev, [stock.ticker]: false }));
  }, []);

  const dp4 = display.v4 ?? {};
  const dp5 = display.v5 ?? {};
  const winButtons = dp5.windows?.length ? dp5.windows : [7, 14, 21];

  const fuseeCount = stocks.filter(s => s.isFusee).length;
  const phenixCount = stocks.filter(s => s.isPhenix).length;

  const filtered = stocks
    .filter(s => {
      if (sector !== "All" && s.sector !== sector) return false;
      if (profile === "fusee" && !s.isFusee) return false;
      if (profile === "phenix" && !s.isPhenix) return false;
      return true;
    })
    .sort((a, b) => {
      if (profile === "fusee") return (b.fuseeStrength ?? 0) - (a.fuseeStrength ?? 0);
      if (profile === "phenix") return (b.phenixStrength ?? 0) - (a.phenixStrength ?? 0);
      return (b.profileStrength ?? 0) - (a.profileStrength ?? 0);
    });

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: "#070714", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <style>{`@keyframes spin { to{transform:rotate(360deg)} }`}</style>
        <div style={{ width: 32, height: 32, border: "2px solid #00ff9d22", borderTop: "2px solid #00ff9d", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        <div style={{ fontFamily: "monospace", color: "#00ff9d", fontSize: 13, letterSpacing: 3, textTransform: "uppercase" }}>{t("loading.scan")}</div>
      </div>
    );
  }

  const glanceLine = v4.cohort.length > 0
    ? <>{t("glance.today")} <b style={{ color: "#00e096" }}>{v4.cohort.length > 1 ? t("glance.qualified.many", { n: v4.cohort.length }) : t("glance.qualified.one")}</b> {t("glance.startWith")} <b style={{ color: "#00e096" }}>{v4.cohort[0].ticker}</b> {t("glance.mostOversold")}</>
    : <>{t("glance.today")} <b>{t("glance.noList")}</b> — {v4.mkt21 != null ? t("glance.bullish", { w: dp4.rules?.mkt_window ?? "—", pct: pctFmt(v4.mkt21) }) : t("glance.mktUnavailable")}{t("glance.paused")}</>;

  return (
    <div style={{ minHeight: "100vh", background: "#070714", fontFamily: "'Segoe UI', sans-serif", color: "#e8e8ff", padding: "0 0 60px" }}>
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0a0a1a; }
        ::-webkit-scrollbar-thumb { background: #2a2a6a; border-radius: 2px; }
        summary::marker { color: #5a6a79; }
      `}</style>

      {/* Header */}
      <div style={{
        background: "linear-gradient(180deg, #0a0a20 0%, #070714 100%)",
        borderBottom: "1px solid #ffffff0a", padding: "24px 32px 20px",
        position: "sticky", top: 0, zIndex: 100, backdropFilter: "blur(20px)",
      }}>
        <div style={{ maxWidth: 1100, margin: "0 auto", display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
              <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#00ff9d", animation: "pulse 2s infinite" }} />
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 11, color: "#00ff9d", letterSpacing: 3, textTransform: "uppercase" }}>{t("header.radar")}</span>
            </div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, letterSpacing: -0.5, color: "#e8e8ff" }}>
              {t("header.title.prefix")} <span style={{ color: "#4444cc" }}>{t("header.title.accent")}</span>
            </h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {/* Toggle FR/EN — choix persisté en localStorage, bascule sans reload */}
            <span style={{
              display: "flex", alignItems: "center", gap: 4, background: "#16202b",
              border: "1px solid #1e2a36", borderRadius: 4, padding: "6px 8px",
            }}>
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
            {(() => {
              const mkt = v5.windows?.[String(mktWin)]?.mkt ?? (mktWin === 21 ? v4.mkt21 : null);
              return (
                <span style={{
                  display: "flex", alignItems: "center", gap: 8, background: "#16202b",
                  border: "1px solid #1e2a36", borderRadius: 4, padding: "6px 8px 6px 12px",
                  fontSize: 13, fontFamily: "monospace",
                }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: mkt == null ? "#5a6a79" : mkt < 0 ? "#ff6b6b" : "#00e096" }} />
                  <Tip down tip={t("header.marketTip")}>{t("header.market")}</Tip>
                  {winButtons.map(w => (
                    <button key={w} onClick={() => setMktWin(w)} style={{
                      background: mktWin === w ? "#1c2f42" : "transparent",
                      border: `1px solid ${mktWin === w ? "#2b4b66" : "#1e2a36"}`,
                      borderRadius: 3, color: mktWin === w ? "#d7e0e8" : "#5a6a79",
                      fontSize: 12, fontFamily: "monospace", padding: "2px 7px", cursor: "pointer",
                    }}>{t("header.winBtn", { w })}</button>
                  ))}
                  <b style={{ color: mkt == null ? "#5a6a79" : mkt < 0 ? "#ff6b6b" : "#00e096" }}>{pctFmt(mkt)}</b>
                  {v5.flash && (
                    <Tip down tip={dp5.gloss?.tip_flash} style={{
                      border: "1px solid #6e2a1c", borderRadius: 3, color: "#ff9b6b",
                      padding: "2px 7px", fontSize: 12, background: "#2c1410",
                    }}>{t("header.flash", { pct: pctFmt(v5.flash_ret3) })}</Tip>
                  )}
                </span>
              );
            })()}
            {lastScan && <span style={{ color: "#33335a", fontSize: 11, fontFamily: "monospace" }}>{t("header.lastScan")} {lastScan.toLocaleTimeString(t("locale"))}</span>}
            <button onClick={runScan} disabled={scanning} style={{
              padding: "10px 20px",
              background: scanning ? "#1a1a3a" : "linear-gradient(90deg, #00cc7a, #0066ff)",
              border: "none", borderRadius: 8, color: scanning ? "#33335a" : "#fff",
              fontSize: 12, fontWeight: 700, fontFamily: "monospace",
              cursor: scanning ? "not-allowed" : "pointer", letterSpacing: 0.5,
            }}>
              {scanning ? t("header.scanning") : t("header.scanBtn")}
            </button>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px" }}>

        {/* En un coup d'œil */}
        <div style={{
          display: "flex", flexWrap: "wrap", gap: 10, alignItems: "center", marginTop: 18,
          background: "linear-gradient(180deg,#101a24,#0e151d)", border: "1px solid #1f3c31",
          borderRadius: 8, padding: "14px 18px",
        }}>
          <span style={{ fontSize: 15, fontWeight: 650 }}>{glanceLine}</span>
          <span style={{ color: "#8494a3", fontSize: 13, flexBasis: "100%" }}>
            {t("intro.p1")} <b style={{ color: "#00e096" }}>{t("intro.positive")}</b>{t("intro.p2")}
          </span>
        </div>

        <HowToRead />

        <MarketSection cohort={v4.cohort} note={v4.note} mkt21={v4.mkt21} prelist={v4.prelist} dp4={dp4} />
        <QuietSection v5={v5} win={mktWin} dp4={dp4} dp5={dp5} />
        <TrackingSection tracking={v4.tracking} dp={dp4} family={t("market.section.title")} />
        <TrackingSection tracking={v5.tracking} dp={dp5} family={t("quiet.name")} windowCol />
        <PerfSection />

        {/* Zones extrêmes */}
        <section style={{ marginTop: 34 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
            <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
              {t("zones.title")}
            </h2>
            <Tip tip={t("zones.tip")}
                 style={{ fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px", borderRadius: 3, border: "1px solid #1e2a36", color: "#8494a3" }}>
              {t("zones.badge")}
            </Tip>
          </div>

          <p style={{ ...proseStyle, margin: "0 0 14px" }}>{t("zones.intro")}</p>

          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
            {[
              { key: "all", label: t("filters.all", { n: stocks.length }) },
              { key: "fusee", label: t("filters.fusee", { n: fuseeCount }) },
              { key: "phenix", label: t("filters.phenix", { n: phenixCount }) },
            ].map(({ key, label }) => (
              <button key={key} onClick={() => setProfile(key)} style={{
                padding: "7px 16px",
                background: profile === key ? "#2a2a6a" : "#0d0d1a",
                border: `1px solid ${profile === key ? "#4444aa" : "#ffffff0a"}`,
                borderRadius: 20, color: profile === key ? "#aaaaff" : "#6666aa",
                fontSize: 12, fontWeight: 700, fontFamily: "monospace", cursor: "pointer",
              }}>{label}</button>
            ))}
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginLeft: "auto" }}>
              {INSTRUMENTS.map(s => (
                <button key={s} onClick={() => setSector(s)} style={{
                  padding: "6px 14px",
                  background: sector === s ? "#2a2a6a" : "#0d0d1a",
                  border: `1px solid ${sector === s ? "#4444aa" : "#ffffff0a"}`,
                  borderRadius: 20, color: sector === s ? "#aaaaff" : "#44446a",
                  fontSize: 12, fontFamily: "monospace", cursor: "pointer",
                }}>{s}</button>
              ))}
            </div>
          </div>

          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
            {filtered.map(stock => (
              <StockCard key={stock.ticker} stock={stock} onAnalyze={analyzeStock}
                         analysis={analyses[stock.ticker]} isLoading={loadingTickers[stock.ticker]} />
            ))}
          </div>

          {filtered.length === 0 && (
            <div style={{ textAlign: "center", padding: "60px 0", color: "#22224a" }}>
              <div style={{ fontSize: 40, marginBottom: 12 }}>◎</div>
              <div style={{ fontFamily: "monospace", fontSize: 14 }}>
                {stocks.length === 0 ? t("zones.empty.scanning") : t("zones.empty.noMatch")}
              </div>
            </div>
          )}
        </section>

        {/* Footer traçabilité */}
        <div style={{ marginTop: 40, borderTop: "1px solid #1e2a36", paddingTop: 16, fontSize: 12.5, color: "#5a6a79" }}>
          <p style={{ margin: "6px 0" }}>
            <b>{t("footer.removed.title")}</b>{t("footer.removed.body")}
          </p>
          <p style={{ margin: "6px 0" }}>
            <b>{t("footer.trace.title")}</b>{t("footer.trace.body")} <code>{t("footer.trace.gloss")}</code>.
          </p>
        </div>
      </div>
    </div>
  );
}
