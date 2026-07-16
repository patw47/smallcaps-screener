import { useState, useEffect, useCallback } from "react";

const INSTRUMENTS = ["All", "Technology", "Healthcare", "Energy", "Industrials", "Consumer Cyclical"];

// ---------------------------------------------------------------------------
// Depuis l'Epic 6 S2, TOUT ce qui touche aux protocoles v4/v5 (seuils des règles,
// chiffres gelés des bandeaux, textes du glossaire UI) arrive de l'API via le bloc
// `display` du payload scan — plus aucune valeur en dur ici (gate : make check-edge).
// Ne restent ci-dessous que les textes des thèses PUBLIQUES (v1-v3, post-mortems
// versionnés dans docs/). Tout terme affiché a son entrée dans docs/glossaire.md.
// ---------------------------------------------------------------------------
const GLOSS = {
  beta: "Sensibilité du titre au marché, mesurée sur ses 6 derniers mois : bêta 1,6 = quand l'indice small caps fait −1 %, ce titre fait −1,6 % en moyenne.",
  ruleDil: "Règle « dilution » : aucun dépôt de préparation d'émission d'actions (S-1/S-3/424B) à la SEC dans les 180 derniers jours. Une émission en attente écrase les cours à son arrivée — seul signal officiel qui penche clairement vers le crash (2,1×).",
  phenix: "Profil « Phénix » : action massacrée (loin de son plus-haut annuel), volatilité comprimée, premiers signes de stabilisation. C'est la zone où vivent les explosions (jusqu'à 4,6× la moyenne)… et encore plus les crashs (2,3×) : espérance −11 %, réservé à la recherche humaine. Validation A (protocole v2 §6) : ÉCHEC.",
  fusee: "Profil « Fusée » : momentum extrême + explosion de volume — l'action déjà brûlante. Verdict mesuré : aucun avantage (elle double aussi souvent qu'un titre au hasard, 1,03×) et espérance −9,6 %. Affiché pour information, sans aucune prétention.",
  goingConcern: "« Going-concern » : dans son rapport officiel, les commissaires aux comptes écrivent douter que l'entreprise survive 12 mois. Contre-intuitif mais mesuré : multiplie par 4-5 les chances de doubler ET de s'effondrer — signal de « gros mouvement imminent », sans direction.",
  dilution: "L'entreprise a déposé à la SEC un document préparant une émission de nouvelles actions : ta part sera mécaniquement réduite et l'arrivée des titres écrase le cours. Seul drapeau clairement défavorable : 2,1× plus fréquent avant un crash.",
  prelist: "Titres qui passent les règles-titre (prix, chute) mais attendent la condition marché. La dilution n'est PAS encore vérifiée (elle le sera le jour où ils qualifient).",
};

// Interpolation {clé} dans les templates servis par l'API (remplacée par t() au S3 i18n).
const fmt = (tpl, vars = {}) =>
  tpl ? Object.entries(vars).reduce((s, [k, v]) => s.replaceAll(`{${k}}`, v ?? "—"), tpl) : "";
// Nombre au format français (ex. −0,42 · 2,5) — les valeurs arrivent numériques de l'API.
const numFr = (x, d = 2) => x == null ? "—" : x.toFixed(d).replace(".", ",").replace("-", "−");

// ---------------------------------------------------------------------------
// Infobulle accessible (survol + focus clavier). Pointillé = explication dispo.
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
// Étage 1 — cohorte v4 (la seule liste à espérance historique positive)
// ---------------------------------------------------------------------------
function V4Card({ entry, rank, total, dp4 }) {
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
          }}>à étudier en premier</span>
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
          <Tip tip={g.profondeur}>Profondeur de survente</Tip>
          <span style={{ fontFamily: "monospace" }}>résidu {pctFmt(entry.resid)}</span>
        </div>
        <div style={{ height: 6, background: "#182230", borderRadius: 3, overflow: "hidden" }}>
          <div style={{ width: `${depth}%`, height: "100%", background: "linear-gradient(90deg,#0e6e52,#00e096)", borderRadius: 3 }} />
        </div>
        <div style={{ fontSize: 11.5, color: "#5a6a79", marginTop: 3 }}>
          <Tip tip={GLOSS.beta}>bêta</Tip> {entry.beta ?? "—"} · corrélation {entry.corr ?? "—"}
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
        {[
          { tip: g.rule_price, text: <>prix <b style={{ color: "#d7e0e8" }}>{entry.price} $</b> / seuil {rules.price_max ?? "—"} $</> },
          { tip: g.rule_chg, text: <>1 mois <b style={{ color: "#d7e0e8" }}>{pctFmt(entry.change_1m)}</b> / seuil {pctFmt(rules.chg1m_max, 0)}</> },
          { tip: GLOSS.ruleDil, text: <>dilution : <b style={{ color: "#d7e0e8" }}>aucune</b> (EDGAR 180 j)</> },
          { tip: g.rule_mkt, text: <>marché IWM {rules.mkt_window ?? "—"} j &lt; 0 ✓ <b style={{ color: "#d7e0e8" }}>({pctFmt(entry.mkt21)})</b></> },
        ].map((m, i) => (
          <Tip key={i} tip={m.tip} style={{
            background: "#16202b", border: "1px solid #1c4033", borderRadius: 4,
            padding: "3px 8px", fontSize: 12, color: "#8494a3",
          }}>{m.text}</Tip>
        ))}
      </div>

      {first && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px dashed #1e2a36", fontSize: 12, color: "#8494a3" }}>
          <b style={{ color: "#d7e0e8" }}>Avant tout achat</b> : lire les 8-K récents (le catalyseur est
          dans les news, pas dans nos chiffres) · vérifier l'écart achat/vente (s'il fait 3 %, il faut
          +3 % pour revenir à zéro) · dimensionner pour survivre à −50 %.
        </div>
      )}
    </div>
  );
}

function V4Section({ cohort, note, mkt21, prelist, dp4 }) {
  const g = dp4.gloss ?? {}, stats = dp4.stats ?? {};
  // Repliée par défaut (protocole distinct, jugé sur 21 j) — s'ouvre seule quand une
  // cohorte existe (marché baissier 21 j), le seul cas actionnable.
  const [open, setOpen] = useState(cohort.length > 0);
  useEffect(() => { if (cohort.length > 0) setOpen(true); }, [cohort.length]);
  return (
    <section style={{ marginTop: 30 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 onClick={() => setOpen(o => !o)} style={{
          fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase",
          letterSpacing: 1.2, color: "#e8e8ff", cursor: "pointer", userSelect: "none",
        }}>
          <span style={{ color: "#5a6a79", marginRight: 6 }}>{open ? "▾" : "▸"}</span>
          Cohorte v4 du jour {cohort.length > 0 && "— commencer ici"}
        </h2>
        <Tip tip={g.research} style={{
          fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px",
          borderRadius: 3, border: "1px solid #4a3f1a", color: "#f0c040",
        }}>Recherche statistique — validation forward en cours</Tip>
        <span style={{ color: "#8494a3", fontSize: 13 }}>protocole v4 signé — archivé hors repo</span>
      </div>

      {!open && (
        <div onClick={() => setOpen(true)} style={{
          border: "1px dashed #1e2a36", borderRadius: 8, padding: "10px 16px", cursor: "pointer",
          color: "#8494a3", fontSize: 13, background: "#0e141b",
        }}>
          {cohort.length > 0
            ? <>{cohort.length} titre(s) qualifié(s) — cliquer pour déplier</>
            : <>{note || "Pas de cohorte aujourd'hui."} — cliquer pour déplier (pré-liste, chiffres gelés)</>}
        </div>
      )}

      {open && <><div style={{
        display: "flex", flexWrap: "wrap", border: "1px solid #1e2a36", borderRadius: 6,
        background: "#0e141b", margin: "12px 0 6px", fontFamily: "monospace",
      }}>
        {[
          { v: stats.esperance || "—", vc: "#00e096", l: "espérance hist. 3 mois", tip: g.esperance },
          { v: stats.p_explode || "—", vc: "#d7e0e8", l: "P(doubler en 3 mois)", tip: g.p_explode },
          { v: stats.p_crash || "—", vc: "#d7e0e8", l: "P(perdre −50 %)", tip: g.p_crash },
          { v: stats.t || "—", vc: "#f0c040", l: "non significatif", tip: g.tstat },
          { v: "4 / 4", vc: "#d7e0e8", l: "règles gelées actives", tip: g.regles },
        ].map((c, i) => (
          <div key={i} style={{ flex: "1 1 130px", padding: "10px 14px", borderRight: i < 4 ? "1px solid #1e2a36" : "none" }}>
            <b style={{ display: "block", fontSize: 17, fontWeight: 640, color: c.vc }}>{c.v}</b>
            <Tip down tip={c.tip} style={{ fontSize: 11.5, color: "#8494a3", textTransform: "uppercase", letterSpacing: 0.6 }}>{c.l}</Tip>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", margin: "10px 0 16px" }}>
        Chiffres historiques 2021-2026, survivants seuls, seuils choisis a posteriori — un plafond
        d'espoir, pas une promesse. Jugement par données réelles : été 2027. Pas un conseil d'investissement.
      </div>

      {cohort.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {cohort.map((e, i) => <V4Card key={e.ticker} entry={e} rank={i} total={cohort.length} dp4={dp4} />)}
        </div>
      ) : (
        <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b" }}>
          <b style={{ color: "#d7e0e8" }}>{note || "Pas de cohorte aujourd'hui."}</b>{" "}
          L'absence de cohorte est une information, pas une panne : la méthode n'achète que pendant
          les soldes générales.
          {prelist.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Tip tip={GLOSS.prelist} style={{ fontSize: 12, color: "#8494a3" }}>Pré-liste (en attente d'un marché baissier)</Tip>
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
      )}</>}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Étage 1 bis — cohorte v5 multi-fenêtres (protocole v5, fenêtre pilotée par le
// sélecteur du header). Purement additive : la v4 reste l'étage de référence.
// ---------------------------------------------------------------------------
function V5Card({ entry, win, rank, total, dp4, dp5 }) {
  const g = dp5.gloss ?? {}, g4 = dp4.gloss ?? {}, rules = dp5.rules ?? {};
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
          }}>le plus écrasé du jour</span>
        ) : (
          <span style={{ marginLeft: "auto", color: "#5a6a79", fontSize: 12 }}>#{rank + 1} / {total}</span>
        )}
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
        {[
          { tip: g4.rule_price, text: <>prix <b style={{ color: "#d7e0e8" }}>{entry.price} $</b> / seuil {rules.price_max ?? "—"} $</> },
          { tip: g.chg, text: <>{win} j <b style={{ color: "#d7e0e8" }}>{pctFmt(entry.chg)}</b> / seuil {pctFmt(rules.chg_max, 0)}</> },
          { tip: GLOSS.ruleDil, text: <>dilution : <b style={{ color: "#d7e0e8" }}>aucune</b> (EDGAR 180 j)</> },
          { tip: g4.rule_mkt, text: <>marché IWM {win} j &lt; 0 ✓ <b style={{ color: "#d7e0e8" }}>({pctFmt(entry.mkt)})</b></> },
          { tip: g.cmf, text: <>CMF <b style={{ color: "#d7e0e8" }}>{entry.cmf}</b> / seuil {numFr(rules.cmf_min)}</> },
          { tip: g.vol_calme, text: <>volume <b style={{ color: "#d7e0e8" }}>{entry.vol_calm}×</b> / max {numFr(rules.volcalm_max)}×</> },
        ].map((m, i) => (
          <Tip key={i} tip={m.tip} style={{
            background: "#16202b", border: "1px solid #1c4033", borderRadius: 4,
            padding: "3px 8px", fontSize: 12, color: "#8494a3",
          }}>{m.text}</Tip>
        ))}
      </div>

      {first && (
        <div style={{ marginTop: 12, paddingTop: 10, borderTop: "1px dashed #1e2a36", fontSize: 12, color: "#8494a3" }}>
          <b style={{ color: "#d7e0e8" }}>Avant tout achat</b> : lire les 8-K récents · vérifier
          l'écart achat/vente · dimensionner pour survivre à −50 % (le « 0 % » de crash mesuré
          est un artefact d'échantillon).
        </div>
      )}
    </div>
  );
}

function V5Section({ v5, win, dp4, dp5 }) {
  const g = dp5.gloss ?? {};
  const block = v5.windows?.[String(win)] ?? { mkt: null, cohort: [], prelist: [], note: "" };
  const stats = dp5.stats?.[String(win)] ?? {};
  const cohort = block.cohort ?? [];
  const prelist = block.prelist ?? [];
  const tracking = v5.tracking ?? [];
  return (
    <section style={{ marginTop: 30 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
          Cohorte v5 — fenêtre {win} j
        </h2>
        <Tip tip={g.research} style={{
          fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px",
          borderRadius: 3, border: "1px solid #4a3f1a", color: "#f0c040",
        }}>Recherche statistique — validation forward en cours</Tip>
        <span style={{ color: "#8494a3", fontSize: 13 }}>protocole v5 signé — archivé hors repo{win === dp5.primary_window ? " · variante primaire" : ""}</span>
      </div>

      <div style={{
        display: "flex", flexWrap: "wrap", border: "1px solid #1e2a36", borderRadius: 6,
        background: "#0e141b", margin: "12px 0 6px", fontFamily: "monospace",
      }}>
        {[
          { v: stats.esperance || "—", vc: "#00e096", l: "espérance hist. 3 mois", tip: (dp4.gloss ?? {}).esperance },
          { v: stats.mediane || "—", vc: "#d7e0e8", l: "titre médian", tip: g.mediane },
          { v: stats.p_explode || "—", vc: "#d7e0e8", l: "P(doubler en 3 mois)", tip: (dp4.gloss ?? {}).p_explode },
          { v: stats.p_crash || "—", vc: "#d7e0e8", l: "P(perdre −50 %)", tip: g.crash },
          { v: stats.t || "—", vc: "#f0c040", l: "non significatif", tip: (dp4.gloss ?? {}).tstat },
          { v: "6 / 6", vc: "#d7e0e8", l: "règles gelées actives", tip: g.regles },
        ].map((c, i) => (
          <div key={i} style={{ flex: "1 1 120px", padding: "10px 14px", borderRight: i < 5 ? "1px solid #1e2a36" : "none" }}>
            <b style={{ display: "block", fontSize: 17, fontWeight: 640, color: c.vc }}>{c.v}</b>
            <Tip down tip={c.tip} style={{ fontSize: 11.5, color: "#8494a3", textTransform: "uppercase", letterSpacing: 0.6 }}>{c.l}</Tip>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", margin: "10px 0 16px" }}>
        Chiffres 2021-2026 ({stats.n ?? "—"} cas), survivants seuls, seuils choisis a posteriori, et
        l'essentiel du signal vient de 2-3 purges — encore moins solide que la v4.
        Jugement : données réelles uniquement. Pas un conseil d'investissement.
      </div>

      {cohort.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {cohort.map((e, i) => <V5Card key={e.ticker} entry={e} win={win} rank={i} total={cohort.length} dp4={dp4} dp5={dp5} />)}
        </div>
      ) : (
        <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b" }}>
          <b style={{ color: "#d7e0e8" }}>{block.note || "Pas de cohorte v5 aujourd'hui."}</b>{" "}
          Essaie une autre fenêtre avec le sélecteur en haut — les fenêtres courtes voient les
          purges éclair que la longue ne voit pas (et inversement).
          {prelist.length > 0 && (
            <div style={{ marginTop: 10 }}>
              <Tip tip={GLOSS.prelist} style={{ fontSize: 12, color: "#8494a3" }}>Pré-liste (en attente d'un marché baissier sur {win} j)</Tip>
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

      {tracking.length > 0 && (
        <div style={{ marginTop: 14, fontSize: 12.5, color: "#8494a3" }}>
          <Tip tip={g.tracking} style={{ textTransform: "uppercase", letterSpacing: 0.6, fontSize: 11.5 }}>
            Suivi Validation D ({tracking.length} lignes, toutes fenêtres)
          </Tip>
          <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 6 }}>
            {tracking.slice(0, 24).map((r, i) => (
              <span key={i} style={{
                background: "#16202b", border: "1px solid #1e2a36", borderRadius: 4,
                padding: "3px 8px", fontFamily: "monospace",
              }}>{r.ticker} · {r.window} j · {r.entry_date} · {pctFmt(r.ret)} · {r.status}</span>
            ))}
          </div>
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------------------
// Étage 2 — suivi des cohortes passées (information, jamais un ordre de vente)
// ---------------------------------------------------------------------------
function statusChip(row) {
  const base = { display: "inline-block", padding: "2px 8px", borderRadius: 3, fontSize: 11.5, border: "1px solid #1e2a36", background: "#16202b", whiteSpace: "nowrap" };
  if (row.status === "au-dessus")
    return <span style={{ ...base, color: "#00e096", borderColor: "#1c4033" }}>au-dessus — suit la trajectoire</span>;
  if (row.status === "sous le seuil")
    return <span style={{ ...base, color: "#f0c040", borderColor: "#4a3f1a" }}>sous le seuil</span>;
  if (row.status?.startsWith("explosion"))
    return <span style={{ ...base, color: "#00e096", borderColor: "#1c4033" }}>💥 {row.status}</span>;
  if (row.status?.startsWith("crash"))
    return <span style={{ ...base, color: "#ff6b6b", borderColor: "#4a2626" }}>{row.status}</span>;
  if (row.status?.includes("délisting"))
    return <span style={{ ...base, color: "#ff6b6b", borderColor: "#4a2626" }}>⚠ {row.status}</span>;
  return <span style={{ ...base, color: "#8494a3" }}>{row.status}</span>;
}

function probText(row, g) {
  if (row.status === "au-dessus") return <span style={{ color: "#00e096" }}>{g.checkpoint_above || "—"}</span>;
  if (row.status === "sous le seuil") return <span style={{ color: "#ff6b6b" }}>{g.checkpoint_below || "—"}</span>;
  if (row.checkpoint?.startsWith("fenêtre")) return <>résultat en fin de fenêtre : <b>{pctFmt(row.ret_63)}</b></>;
  return "—";
}

function TrackingSection({ tracking, dp4 }) {
  const g = dp4.gloss ?? {};
  return (
    <section style={{ marginTop: 34 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 8 }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
          Suivi des cohortes passées
        </h2>
        <span style={{ color: "#8494a3", fontSize: 13 }}>position vs trajectoires historiques — information, jamais un ordre de vente</span>
      </div>
      {tracking.length === 0 ? (
        <div style={{ border: "1px dashed #1e2a36", borderRadius: 8, padding: "14px 18px", color: "#8494a3", fontSize: 13.5, background: "#0e141b" }}>
          Aucune cohorte enregistrée pour l'instant — en attente du premier marché baissier.
          Le journal a démarré le 6 juillet 2026 ; chaque scan quotidien enregistre sa cohorte (vide ou pas).
        </div>
      ) : (
        <div style={{ overflowX: "auto", border: "1px solid #1e2a36", borderRadius: 8, background: "#111820" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13.5, fontFamily: "monospace" }}>
            <thead>
              <tr>
                {["Titre", "Entré le", "Prix entrée", "Aujourd'hui", "Checkpoint", "Position", "Probabilités conditionnelles"].map((h, i) => (
                  <th key={h} style={{
                    color: "#8494a3", fontWeight: 600, textTransform: "uppercase", fontSize: 11,
                    letterSpacing: 0.7, textAlign: i === 2 || i === 3 ? "right" : "left",
                    padding: "10px 14px", borderBottom: "1px solid #1e2a36",
                  }} title={h === "Checkpoint" ? g.checkpoint : undefined}>{h}{h === "Checkpoint" ? " ⓘ" : ""}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {tracking.map(r => (
                <tr key={r.ticker + r.entry_date}>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", fontWeight: 700, color: "#e8e8ff" }}>{r.ticker}</td>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", color: "#8494a3" }}>{r.entry_date}</td>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", textAlign: "right", color: "#d7e0e8" }}>{r.entry_price} $</td>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", textAlign: "right", color: r.ret == null ? "#8494a3" : r.ret >= 0 ? "#00e096" : "#ff6b6b" }}>
                    {r.ret != null ? `${pctFmt(r.ret)} · J+${r.days_held}` : "—"}
                  </td>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", color: "#8494a3" }}>{r.checkpoint ?? "—"}</td>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36" }}>{statusChip(r)}</td>
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", color: "#d7e0e8", fontFamily: "'Segoe UI', sans-serif", fontSize: 12.5 }}>{probText(r, g)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
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
// Étage 3 — zones extrêmes (profils v2, à étudier — pas à acheter)
// ---------------------------------------------------------------------------
const PROFILE_STYLE = {
  fusee: {
    emoji: "🚀", label: "Fusée", fg: "#00e69a", bg: "#00ff9d18", bd: "#00ff9d44",
    tip: GLOSS.fusee,
    stats: <>doubler : <b>1,03× — pas d'avantage mesuré</b> · espérance : <b style={{ color: "#ff6b6b" }}>−9,6 %</b></>,
  },
  phenix: {
    emoji: "🔥", label: "Phénix", fg: "#ff9966", bg: "#ff6b6b18", bd: "#ff6b6b44",
    tip: GLOSS.phenix,
    stats: <>doubler : <b style={{ color: "#00e096" }}>4-5 % (4,6×)</b> · −50 % : <b style={{ color: "#ff6b6b" }}>2,3× la base</b> · espérance : <b style={{ color: "#ff6b6b" }}>−11 %</b></>,
  },
};

function ProfileBadge({ kind, strength, event }) {
  const c = PROFILE_STYLE[kind];
  const pct = strength != null ? Math.round(strength * 100) : null;
  return (
    <Tip tip={c.tip} style={{
      display: "inline-flex", alignItems: "center", gap: 5,
      background: c.bg, color: c.fg, border: `1px solid ${c.bd}`, borderBottom: `1px solid ${c.bd}`,
      borderRadius: 20, padding: "4px 11px", fontSize: 12, fontWeight: 700,
      fontFamily: "monospace", letterSpacing: 0.3,
    }}>
      <span>{c.emoji} {c.label}</span>
      {pct != null && <span style={{ opacity: 0.7, fontWeight: 600 }}>· {pct}</span>}
      {event && <span style={{ color: "#ffd24d" }}>⚡</span>}
      <span style={{
        background: "#ffcc6622", color: "#ffcc66", fontSize: 9, fontWeight: 700,
        padding: "1px 6px", borderRadius: 10, marginLeft: 3,
        textTransform: "uppercase", letterSpacing: 0.4,
      }}>non validé</span>
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
          <div style={{ fontSize: 12, color: changeColor(stock.change1d), fontFamily: "monospace" }}>{stock.change1d > 0 ? "+" : ""}{stock.change1d}% today</div>
        </div>
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: 10 }}>
        {stock.isFusee && <ProfileBadge kind="fusee" strength={stock.fuseeStrength} event={stock.fuseeEvent} />}
        {stock.isPhenix && <ProfileBadge kind="phenix" strength={stock.phenixStrength} />}
      </div>

      {profileKind && (
        <div style={{ fontSize: 12.5, color: "#8494a3", marginBottom: 12 }}>
          {PROFILE_STYLE[profileKind].stats}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 12 }}>
        {[
          { label: "Mkt Cap", value: `$${stock.marketCap}M` },
          { label: "Vol Ratio", value: `${stock.volumeRatio}x` },
          { label: "1 mois", value: `${stock.change1m > 0 ? "+" : ""}${stock.change1m}%`, color: changeColor(stock.change1m) },
        ].map(({ label, value, color }) => (
          <div key={label} style={{ background: "#ffffff05", borderRadius: 8, padding: "8px 10px" }}>
            <div style={{ color: "#44446a", fontSize: 10, marginBottom: 2, textTransform: "uppercase", letterSpacing: 0.5 }}>{label}</div>
            <div style={{ color: color || "#c0c0e0", fontSize: 13, fontWeight: 600, fontFamily: "monospace" }}>{value}</div>
          </div>
        ))}
      </div>

      {/* Dossier de risque : faits EDGAR + drapeaux, sémantique mesurée (glossaire) */}
      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 14 }}>
        {stock.survivalRisk && (
          <Tip tip={GLOSS.goingConcern} style={{
            background: "#f0c04012", color: "#f0c040", fontSize: 10, padding: "3px 8px",
            borderRadius: 20, border: "1px solid #f0c04033",
          }}>⚠ détresse EDGAR — volatilité extrême (les 2 queues)</Tip>
        )}
        {stock.flags.map(f => (
          <Tip key={f} tip={/dilution/i.test(f) ? GLOSS.dilution : f} style={{
            background: "#ff6b6b0d", color: "#ff6b6b", fontSize: 10, padding: "3px 8px",
            borderRadius: 20, border: "1px solid #ff6b6b22",
          }}>⚠ {f}</Tip>
        ))}
        {stock.positives.map(p => (
          <span key={p} style={{ background: "#00ff9d0d", color: "#00cc7a", fontSize: 10, padding: "3px 8px", borderRadius: 20, border: "1px solid #00ff9d22" }}>✓ {p}</span>
        ))}
      </div>

      {analysis && (
        <div style={{ background: "#0a0a1f", border: "1px solid #2222aa44", borderRadius: 8, padding: "14px 16px", marginBottom: 14 }}>
          <div style={{ color: "#6666dd", fontSize: 10, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>⚡ Analyse Claude</div>
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
        {isLoading ? "⟳ Analyse en cours..." : analysis ? "↻ Ré-analyser" : "⚡ Analyser avec Claude (lire le dossier)"}
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
  const [v4, setV4] = useState({ cohort: [], note: "", mkt21: null, prelist: [], tracking: [] });
  const [v5, setV5] = useState({ windows: {}, flash: false, flash_ret3: null, tracking: [] });
  const [display, setDisplay] = useState({});  // seuils/textes v4-v5 servis par l'API (Epic 6 S2)
  const [mktWin, setMktWin] = useState(21);   // fenêtre du sélecteur marché (7/14/21)
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [sector, setSector] = useState("All");
  const [profile, setProfile] = useState("All");
  const [analyses, setAnalyses] = useState({});
  const [loadingTickers, setLoadingTickers] = useState({});
  const [lastScan, setLastScan] = useState(null);

  const fetchData = useCallback(() => {
    return fetch("/api/scan")
      .then(r => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
      .then(json => {
        setStocks(normalizeStocks(json.stocks ?? []));
        setV4({
          cohort: json.v4_cohort ?? [], note: json.v4_note ?? "",
          mkt21: json.v4_mkt21 ?? null, prelist: json.v4_prelist ?? [],
          tracking: json.v4_tracking ?? [],
        });
        setV5({
          windows: json.v5?.windows ?? {}, flash: !!json.v5?.flash,
          flash_ret3: json.v5?.flash_ret3 ?? null, tracking: json.v5?.tracking ?? [],
        });
        setDisplay(json.display ?? {});
        if (json.scanned_at) setLastScan(new Date(json.scanned_at).toLocaleTimeString("fr-FR"));
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
    const prompt = `Tu es un analyste spécialisé small caps US. Cherche les news récentes sur cette action (90 derniers jours : 8-K, communiqués, refinancement, essais cliniques, contrats, menace de délisting), puis donne un brief concis.

Action: ${stock.ticker} — ${stock.name}
Secteur: ${stock.sector} | Prix: $${stock.price}
Market Cap: $${stock.marketCap}M | Volume ratio 10j/50j: ${stock.volumeRatio}x
Performance 1 mois: ${stock.change1m}%
Profil détecté: ${stock.isPhenix ? "Phénix (massacrée qui se stabilise — zone à explosions ET à crashs)" : stock.isFusee ? "Fusée (momentum extrême — aucun avantage mesuré)" : "aucun"}
Points positifs: ${stock.positives.join(", ") || "—"}
Red flags: ${stock.flags.length > 0 ? stock.flags.join(", ") : "Aucun"}

Contexte : notre étude a montré que l'issue dépend du CONTENU des news à venir — pas des chiffres ci-dessus. Les chiffres disent où regarder ; les news disent quoi penser.
Réponds en français. Structure:
1. News récentes trouvées (datées, sourcées — ou "rien trouvé", c'est une info aussi)
2. Catalyseurs possibles et risque principal au vu de ces news
3. Verdict en une phrase (recherche, pas conseil)`;

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
      const text = data.content?.filter(b => b.type === "text").map(b => b.text).join("") || "Analyse indisponible";
      setAnalyses(prev => ({ ...prev, [stock.ticker]: text }));
    } catch (e) {
      setAnalyses(prev => ({ ...prev, [stock.ticker]: "Erreur lors de l'analyse. Vérifie ta connexion." }));
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
      if (profile === "Fusée" && !s.isFusee) return false;
      if (profile === "Phénix" && !s.isPhenix) return false;
      return true;
    })
    .sort((a, b) => {
      if (profile === "Fusée") return (b.fuseeStrength ?? 0) - (a.fuseeStrength ?? 0);
      if (profile === "Phénix") return (b.phenixStrength ?? 0) - (a.phenixStrength ?? 0);
      return (b.profileStrength ?? 0) - (a.profileStrength ?? 0);
    });

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: "#070714", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <style>{`@keyframes spin { to{transform:rotate(360deg)} }`}</style>
        <div style={{ width: 32, height: 32, border: "2px solid #00ff9d22", borderTop: "2px solid #00ff9d", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        <div style={{ fontFamily: "monospace", color: "#00ff9d", fontSize: 13, letterSpacing: 3, textTransform: "uppercase" }}>Scan en cours...</div>
      </div>
    );
  }

  const glanceLine = v4.cohort.length > 0
    ? <>Aujourd'hui : <b style={{ color: "#00e096" }}>{v4.cohort.length} titre{v4.cohort.length > 1 ? "s" : ""} qualifié{v4.cohort.length > 1 ? "s" : ""} v4</b> — commencer par <b style={{ color: "#00e096" }}>{v4.cohort[0].ticker}</b> (le plus survendu du jour)</>
    : <>Aujourd'hui : <b>pas de cohorte v4</b> — {v4.mkt21 != null ? `marché haussier (IWM ${dp4.rules?.mkt_window ?? "—"} j ${pctFmt(v4.mkt21)})` : "état du marché indisponible"}, la méthode est en pause</>;

  return (
    <div style={{ minHeight: "100vh", background: "#070714", fontFamily: "'Segoe UI', sans-serif", color: "#e8e8ff", padding: "0 0 60px" }}>
      <style>{`
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0a0a1a; }
        ::-webkit-scrollbar-thumb { background: #2a2a6a; border-radius: 2px; }
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
              <span style={{ fontFamily: "'Courier New', monospace", fontSize: 11, color: "#00ff9d", letterSpacing: 3, textTransform: "uppercase" }}>Small Cap Radar</span>
            </div>
            <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, letterSpacing: -0.5, color: "#e8e8ff" }}>
              Assistant de recherche <span style={{ color: "#4444cc" }}>small caps</span>
            </h1>
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
            {(() => {
              const mkt = v5.windows?.[String(mktWin)]?.mkt ?? (mktWin === 21 ? v4.mkt21 : null);
              return (
                <span style={{
                  display: "flex", alignItems: "center", gap: 8, background: "#16202b",
                  border: "1px solid #1e2a36", borderRadius: 4, padding: "6px 8px 6px 12px",
                  fontSize: 13, fontFamily: "monospace",
                }}>
                  <span style={{ width: 8, height: 8, borderRadius: "50%", background: mkt == null ? "#5a6a79" : mkt < 0 ? "#ff6b6b" : "#00e096" }} />
                  <Tip down tip={dp5.gloss?.mkt_switch}>Marché : IWM</Tip>
                  {winButtons.map(w => (
                    <button key={w} onClick={() => setMktWin(w)} style={{
                      background: mktWin === w ? "#1c2f42" : "transparent",
                      border: `1px solid ${mktWin === w ? "#2b4b66" : "#1e2a36"}`,
                      borderRadius: 3, color: mktWin === w ? "#d7e0e8" : "#5a6a79",
                      fontSize: 12, fontFamily: "monospace", padding: "2px 7px", cursor: "pointer",
                    }}>{w} j</button>
                  ))}
                  <b style={{ color: mkt == null ? "#5a6a79" : mkt < 0 ? "#ff6b6b" : "#00e096" }}>{pctFmt(mkt)}</b>
                  {v5.flash && (
                    <Tip down tip={dp5.gloss?.flash} style={{
                      border: "1px solid #6e2a1c", borderRadius: 3, color: "#ff9b6b",
                      padding: "2px 7px", fontSize: 12, background: "#2c1410",
                    }}>⚡ krach éclair ({pctFmt(v5.flash_ret3)} / 3 j)</Tip>
                  )}
                </span>
              );
            })()}
            {lastScan && <span style={{ color: "#33335a", fontSize: 11, fontFamily: "monospace" }}>Dernier scan: {lastScan}</span>}
            <button onClick={runScan} disabled={scanning} style={{
              padding: "10px 20px",
              background: scanning ? "#1a1a3a" : "linear-gradient(90deg, #00cc7a, #0066ff)",
              border: "none", borderRadius: 8, color: scanning ? "#33335a" : "#fff",
              fontSize: 12, fontWeight: 700, fontFamily: "monospace",
              cursor: scanning ? "not-allowed" : "pointer", letterSpacing: 0.5,
            }}>
              {scanning ? "⟳ Scan..." : "▶ Scanner le marché"}
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
            La cohorte v4 est le seul groupe dont le profil a une espérance historique{" "}
            <b style={{ color: "#00e096" }}>positive</b>. Les zones extrêmes plus bas sont de la
            matière à recherche (espérance négative) — pas des candidats à l'achat. Le screener ne
            dit jamais « achète » : il dit où regarder en premier, et pourquoi.
          </span>
        </div>

        <V4Section cohort={v4.cohort} note={v4.note} mkt21={v4.mkt21} prelist={v4.prelist} dp4={dp4} />
        <V5Section v5={v5} win={mktWin} dp4={dp4} dp5={dp5} />
        <TrackingSection tracking={v4.tracking} dp4={dp4} />

        {/* Zones extrêmes */}
        <section style={{ marginTop: 34 }}>
          <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 10 }}>
            <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
              🔥🚀 Zones extrêmes — à étudier, pas à acheter
            </h2>
            <Tip tip="Ces profils concentrent les explosions (jusqu'à 4,6× la moyenne) mais AUSSI les crashs, et leur espérance mesurée est négative (−9 à −11 %). Ce n'est pas une liste d'achat : c'est la liste des dossiers où une recherche humaine (news, refinancement, essais cliniques) peut faire la différence que nos chiffres ne font pas."
                 style={{ fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px", borderRadius: 3, border: "1px solid #1e2a36", color: "#8494a3" }}>
              espérance négative mesurée — lecture de dossier requise
            </Tip>
          </div>

          <div style={{ display: "flex", gap: 8, marginBottom: 16, flexWrap: "wrap", alignItems: "center" }}>
            {[
              { key: "All", label: `Tous (${stocks.length})` },
              { key: "Fusée", label: `🚀 Fusée (${fuseeCount})` },
              { key: "Phénix", label: `🔥 Phénix (${phenixCount})` },
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
                {stocks.length === 0 ? "Scan en cours... relancez dans quelques instants" : "Aucune candidate avec ces filtres"}
              </div>
            </div>
          )}
        </section>

        {/* Footer traçabilité */}
        <div style={{ marginTop: 40, borderTop: "1px solid #1e2a36", paddingTop: 16, fontSize: 12.5, color: "#5a6a79" }}>
          <p style={{ margin: "6px 0" }}>
            <b>Retiré de l'interface</b> : la note 0-10 (score v1 — réfuté par son étude : dix déciles
            négatifs) · P(+100 %) par modèle (v3 — verdict terminal, jamais déployé) · les alertes de
            cassure (déclencheur mesuré non-prédictif, 1,0×) — remplacées par l'alerte « nouvelle
            entrée en cohorte v4 ».
          </p>
          <p style={{ margin: "6px 0" }}>
            <b>Traçabilité</b> : chaque chiffre affiché est servi par l'API depuis les tables gelées
            des protocoles signés (v4/v5, archivés hors repo ; v2 pour les profils) — rien d'inventé,
            rien de recalculé en direct. Tous les termes : <code>docs/glossaire.md</code>.
          </p>
        </div>
      </div>
    </div>
  );
}
