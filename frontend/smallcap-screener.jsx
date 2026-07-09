import { useState, useEffect, useCallback } from "react";

const INSTRUMENTS = ["All", "Technology", "Healthcare", "Energy", "Industrials", "Consumer Cyclical"];

// ---------------------------------------------------------------------------
// Constantes GELÉES — source unique : docs/backtest_protocol_v4.md Annexe A (v4)
// et docs/backtest_protocol_v2.md §9 (profils). L'interface affiche CES chiffres
// verbatim (§3 du protocole) — rien n'est recalculé en direct. Tout terme affiché
// a son entrée dans docs/glossaire.md (règle S3).
// ---------------------------------------------------------------------------
const V4_STATS = {
  esperance: "+5,9 %", mediane: "+1,6 %", pExplode: "2,0 %", pCrash: "1,9 %",
  t: "t = 0,47",
};
const DEPTH_SCALE = 0.15;   // échelle de la jauge résidu (0 → −15 %)

// Chiffres gelés v5 (protocole v5 §6.2, SIGNÉ 2026-07-09) — fwd63 net, in-sample.
// P(−50 %) « 0 % » à 7/14 j = artefact d'échantillon (vrai taux ~2 %) — voir l'infobulle.
const V5_WINDOWS = [7, 14, 21];
const V5_STATS = {
  7:  { esperance: "+32,3 %", mediane: "+23,1 %", pExplode: "8,6 %", pCrash: "0 %*", t: "t = 0,34", n: 70 },
  14: { esperance: "+16,5 %", mediane: "+10,9 %", pExplode: "5,3 %", pCrash: "0 %*", t: "t = 0,42", n: 151 },
  21: { esperance: "+13,3 %", mediane: "+10,5 %", pExplode: "4,0 %", pCrash: "1,3 %", t: "t = 0,02", n: 150 },
};

const GLOSS = {
  iwm: "IWM = l'indice des petites capitalisations US (Russell 2000). On mesure sa variation sur les 21 dernières séances (~1 mois de bourse). Négatif = marché en baisse = la méthode v4 s'applique ; positif = elle se met en pause.",
  esperance: "Gain ou perte MOYEN par titre, 3 mois après l'entrée, frais de 1 % déduits — mesuré sur 2021-2026 (1 193 cas historiques). Moyenne tirée par quelques gros gagnants : le titre médian ne fait que +1,6 %.",
  pExplode: "Fréquence historique des +100 % en 3 mois parmi les titres de ce filtre. Référence : 0,8 % pour une petite action prise au hasard — le filtre multiplie par ~2,5.",
  pCrash: "Fréquence historique des chutes de moitié en 3 mois dans ce filtre. Référence : 3,8 % au hasard — le filtre divise par 2. Rare cas où doubler est devenu AUSSI probable que crasher.",
  tstat: "Test statistique sur les 18 trimestres indépendants de l'historique. Il faut t ≥ 2 pour exclure le hasard ; à 0,47, le +5,9 % peut parfaitement être de la chance. C'est pour ça que la méthode est en VALIDATION : seules les données réelles à venir trancheront (été 2027).",
  regles: "Les 4 conditions du protocole signé : prix ≤ 8 $ · aucune dilution en attente · chute ≥ 3 % sur 1 mois · marché lui-même en baisse. « Gelées » = aucun réglage possible sans nouvelle version du protocole, qui remettrait le chronomètre du test à zéro.",
  research: "Cette liste applique une hypothèse issue de l'analyse du passé, dont la promesse n'est PAS démontrée (t = 0,47). Elle est en cours de test grandeur nature : chaque jour, les titres qualifiés sont enregistrés, et leurs résultats réels seront jugés à partir de l'été 2027 selon des critères écrits à l'avance.",
  profondeur: "De combien le titre a chuté EN PLUS de ce que la baisse du marché explique (via son bêta). Historiquement, plus cette part propre est profonde, meilleur a été le rebond (+11,2 % contre +2,9 %) — c'est l'ordre d'affichage, et il reste à confirmer en réel. (Terme technique : le « résidu bêta ».)",
  beta: "Sensibilité du titre au marché, mesurée sur ses 6 derniers mois : bêta 1,6 = quand l'indice small caps fait −1 %, ce titre fait −1,6 % en moyenne.",
  rulePrice: "Règle 1 du protocole : prix ≤ 8 $. Les explosions historiques cotaient 6,5 $ en médiane, contre 13 $ pour les autres — la zone des gros mouvements est bon marché.",
  ruleChg: "Règle 3 : le titre doit avoir perdu au moins 3 % sur le dernier mois — on achète des soldes, pas des sommets.",
  ruleDil: "Règle 2 : aucun dépôt de préparation d'émission d'actions (S-1/S-3/424B) à la SEC dans les 180 derniers jours. Une émission en attente écrase les cours à son arrivée — seul signal officiel qui penche clairement vers le crash (2,1×).",
  ruleMkt: "Règle 4 : l'indice small caps doit lui-même baisser sur 1 mois. Un marché en purge brade des titres sans raison propre (récupérables) ; un titre qui s'effondre seul dans un marché haussier a de vraies casseroles (pire cas mesuré : −7,3 %).",
  checkpoint: "Point de contrôle mesuré une semaine (5 séances) après l'entrée : au-dessus de +3 %, les titres ont historiquement 4× plus doublé et 2× moins crashé. Information — jamais un ordre de vente : 31 % des explosions étaient encore négatives ici, et vendre automatiquement détruit le rendement mesuré du panier (+1,4 % → −0,4 %).",
  phenix: "Profil « Phénix » : action massacrée (loin de son plus-haut annuel), volatilité comprimée, premiers signes de stabilisation. C'est la zone où vivent les explosions (jusqu'à 4,6× la moyenne)… et encore plus les crashs (2,3×) : espérance −11 %, réservé à la recherche humaine. Validation A (protocole v2 §6) : ÉCHEC.",
  fusee: "Profil « Fusée » : momentum extrême + explosion de volume — l'action déjà brûlante. Verdict mesuré : aucun avantage (elle double aussi souvent qu'un titre au hasard, 1,03×) et espérance −9,6 %. Affiché pour information, sans aucune prétention.",
  goingConcern: "« Going-concern » : dans son rapport officiel, les commissaires aux comptes écrivent douter que l'entreprise survive 12 mois. Contre-intuitif mais mesuré : multiplie par 4-5 les chances de doubler ET de s'effondrer — signal de « gros mouvement imminent », sans direction.",
  dilution: "L'entreprise a déposé à la SEC un document préparant une émission de nouvelles actions : ta part sera mécaniquement réduite et l'arrivée des titres écrase le cours. Seul drapeau clairement défavorable : 2,1× plus fréquent avant un crash.",
  prelist: "Titres qui passent les règles-titre (prix, chute) mais attendent la condition marché. La dilution n'est PAS encore vérifiée (elle le sera le jour où ils qualifient).",
  mktSwitch: "Le même thermomètre (IWM, indice small caps) mesuré sur trois rétroviseurs : 7, 14 ou 21 séances de bourse. Aucun n'est « le bon » : les fenêtres courtes voient les purges éclair (celle de juillet 2024, −10 % en 16 séances, n'a jamais allumé le 21 j), les longues voient les glissades de plusieurs mois. Le choix change la liste v5 affichée en dessous — la cohorte v4, elle, reste jugée sur 21 j (protocole distinct).",
  v5Regles: "Les 6 conditions du protocole v5 signé (2026-07-09) : prix ≤ 8 $ · aucune dilution en attente · chute ≥ 15 % sur la fenêtre · marché lui-même en baisse sur la MÊME fenêtre · flux CMF > −0,10 · volume calme (≤ 1,25× la normale). Gelées : tout réglage = nouvelle version du protocole + chrono remis à zéro.",
  v5Research: "Profil « explosée type » issu de l'autopsie des doubleurs historiques : écrasé fort, mais SANS volume ni fuite d'argent — la signature de la survente mécanique, pas du naufrage mérité. Chiffres 2021-2026, survivants seuls, seuils choisis après coup, t < 0,5 partout : peut-être du bruit. Jugement par données réelles uniquement (variante primaire : 14 j).",
  v5Chg: "Règle 3 v5 : le titre doit avoir perdu au moins 15 % sur la fenêtre choisie. Mesuré : plus la chute est profonde (jusqu'à −20 %), plus le rebond moyen historique est fort — au-delà, les crashs doublent.",
  volCalme: "Volume moyen pendant la chute rapporté au volume habituel (60 séances précédentes). ≤ 1,25× = le titre baisse « dans l'indifférence », personne ne se précipite pour vendre — c'était la signature des futurs doubleurs. Les futurs morts, eux, chutaient SUR volume (1,4-1,6×).",
  cmfRule: "Chaikin Money Flow sur 20 séances : où se font les clôtures dans le range du jour, pondéré par le volume. Proche de −1 = l'argent fuit. Règle v5 : CMF > −0,10 — les futurs morts avaient un CMF deux fois plus négatif (−0,15) que les futurs doubleurs (−0,07).",
  flash: "⚡ Krach éclair : IWM a perdu ≥ 8 % en 3 séances — le pire demi-percentile de 26 ans d'historique (~1 fois tous les 2 ans : COVID 2020, purges 2022, yen-carry août 2024, tarifs avril 2025). Signale un épisode de purge violente en cours. Information de contexte — pas une règle d'entrée, et son rendement n'est mesuré que sur UN épisode.",
  v5Crash: "Fréquence mesurée des chutes de moitié dans le profil. Le « 0 % » des fenêtres 7 et 14 j est un artefact : sur 70-151 cas avec un vrai taux ~2 %, observer zéro crash est du bruit d'échantillon. Dimensionner comme si c'était ~2 %.",
  v5Tracking: "Journal de la Validation D : chaque titre qualifié v5 est enregistré (fenêtre, date, prix) et suivi. Première lecture ≥ 4 cohortes non chevauchantes ; jugement final ≥ 8 (~24 mois). Information, jamais un ordre de vente.",
};

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
function V4Card({ entry, rank, total }) {
  const depth = entry.resid != null ? Math.min(100, Math.abs(Math.min(entry.resid, 0)) / DEPTH_SCALE * 100) : 0;
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

      {first && (
        <div style={{ marginTop: 10, fontSize: 13, color: "#d7e0e8", borderLeft: "2px solid #00e096", paddingLeft: 10 }}>
          Pourquoi lui : le plus survendu des {total} qualifiés (résidu {pctFmt(entry.resid)}),
          toutes les marges larges — le sous-groupe historiquement le plus payant (+11,2 %).
        </div>
      )}

      <div style={{ margin: "12px 0 4px" }}>
        <div style={{ display: "flex", justifyContent: "space-between", fontSize: 12, color: "#8494a3", marginBottom: 4 }}>
          <Tip tip={GLOSS.profondeur}>Profondeur de survente</Tip>
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
          { tip: GLOSS.rulePrice, text: <>prix <b style={{ color: "#d7e0e8" }}>{entry.price} $</b> / seuil 8 $</> },
          { tip: GLOSS.ruleChg, text: <>1 mois <b style={{ color: "#d7e0e8" }}>{pctFmt(entry.change_1m)}</b> / seuil −3 %</> },
          { tip: GLOSS.ruleDil, text: <>dilution : <b style={{ color: "#d7e0e8" }}>aucune</b> (EDGAR 180 j)</> },
          { tip: GLOSS.ruleMkt, text: <>marché IWM 21 j &lt; 0 ✓ <b style={{ color: "#d7e0e8" }}>({pctFmt(entry.mkt21)})</b></> },
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

function V4Section({ cohort, note, mkt21, prelist }) {
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
        <Tip tip={GLOSS.research} style={{
          fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px",
          borderRadius: 3, border: "1px solid #4a3f1a", color: "#f0c040",
        }}>Recherche statistique — validation forward en cours</Tip>
        <span style={{ color: "#8494a3", fontSize: 13 }}>protocole signé · docs/backtest_protocol_v4.md</span>
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
          { v: V4_STATS.esperance, vc: "#00e096", l: "espérance hist. 3 mois", tip: GLOSS.esperance },
          { v: V4_STATS.pExplode, vc: "#d7e0e8", l: "P(doubler en 3 mois)", tip: GLOSS.pExplode },
          { v: V4_STATS.pCrash, vc: "#d7e0e8", l: "P(perdre −50 %)", tip: GLOSS.pCrash },
          { v: V4_STATS.t, vc: "#f0c040", l: "non significatif", tip: GLOSS.tstat },
          { v: "4 / 4", vc: "#d7e0e8", l: "règles gelées actives", tip: GLOSS.regles },
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
          {cohort.map((e, i) => <V4Card key={e.ticker} entry={e} rank={i} total={cohort.length} />)}
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
function V5Card({ entry, win, rank, total }) {
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
          { tip: GLOSS.rulePrice, text: <>prix <b style={{ color: "#d7e0e8" }}>{entry.price} $</b> / seuil 8 $</> },
          { tip: GLOSS.v5Chg, text: <>{win} j <b style={{ color: "#d7e0e8" }}>{pctFmt(entry.chg)}</b> / seuil −15 %</> },
          { tip: GLOSS.ruleDil, text: <>dilution : <b style={{ color: "#d7e0e8" }}>aucune</b> (EDGAR 180 j)</> },
          { tip: GLOSS.ruleMkt, text: <>marché IWM {win} j &lt; 0 ✓ <b style={{ color: "#d7e0e8" }}>({pctFmt(entry.mkt)})</b></> },
          { tip: GLOSS.cmfRule, text: <>CMF <b style={{ color: "#d7e0e8" }}>{entry.cmf}</b> / seuil −0,10</> },
          { tip: GLOSS.volCalme, text: <>volume <b style={{ color: "#d7e0e8" }}>{entry.vol_calm}×</b> / max 1,25×</> },
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

function V5Section({ v5, win }) {
  const block = v5.windows?.[String(win)] ?? { mkt: null, cohort: [], prelist: [], note: "" };
  const stats = V5_STATS[win];
  const cohort = block.cohort ?? [];
  const prelist = block.prelist ?? [];
  const tracking = v5.tracking ?? [];
  return (
    <section style={{ marginTop: 30 }}>
      <div style={{ display: "flex", flexWrap: "wrap", alignItems: "baseline", gap: 10, marginBottom: 4 }}>
        <h2 style={{ fontSize: 15, margin: 0, fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2, color: "#e8e8ff" }}>
          Cohorte v5 — fenêtre {win} j
        </h2>
        <Tip tip={GLOSS.v5Research} style={{
          fontSize: 11, letterSpacing: 0.8, textTransform: "uppercase", padding: "2px 8px",
          borderRadius: 3, border: "1px solid #4a3f1a", color: "#f0c040",
        }}>Recherche statistique — validation forward en cours</Tip>
        <span style={{ color: "#8494a3", fontSize: 13 }}>protocole signé · docs/backtest_protocol_v5.md{win === 14 ? " · variante primaire" : ""}</span>
      </div>

      <div style={{
        display: "flex", flexWrap: "wrap", border: "1px solid #1e2a36", borderRadius: 6,
        background: "#0e141b", margin: "12px 0 6px", fontFamily: "monospace",
      }}>
        {[
          { v: stats.esperance, vc: "#00e096", l: "espérance hist. 3 mois", tip: GLOSS.esperance },
          { v: stats.mediane, vc: "#d7e0e8", l: "titre médian", tip: "La moitié des titres du profil ont fait mieux, la moitié moins bien. Contrairement à la v4 (médiane +1,6 %), le titre typique du profil v5 gagnait — sur l'historique, survivants seuls." },
          { v: stats.pExplode, vc: "#d7e0e8", l: "P(doubler en 3 mois)", tip: GLOSS.pExplode },
          { v: stats.pCrash, vc: "#d7e0e8", l: "P(perdre −50 %)", tip: GLOSS.v5Crash },
          { v: stats.t, vc: "#f0c040", l: "non significatif", tip: GLOSS.tstat },
          { v: "6 / 6", vc: "#d7e0e8", l: "règles gelées actives", tip: GLOSS.v5Regles },
        ].map((c, i) => (
          <div key={i} style={{ flex: "1 1 120px", padding: "10px 14px", borderRight: i < 5 ? "1px solid #1e2a36" : "none" }}>
            <b style={{ display: "block", fontSize: 17, fontWeight: 640, color: c.vc }}>{c.v}</b>
            <Tip down tip={c.tip} style={{ fontSize: 11.5, color: "#8494a3", textTransform: "uppercase", letterSpacing: 0.6 }}>{c.l}</Tip>
          </div>
        ))}
      </div>
      <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", margin: "10px 0 16px" }}>
        Chiffres 2021-2026 ({stats.n} cas), survivants seuls, seuils choisis a posteriori, et
        l'essentiel du signal vient de 2-3 purges — encore moins solide que la v4 (t &lt; 0,5).
        Jugement : données réelles uniquement. Pas un conseil d'investissement.
      </div>

      {cohort.length > 0 ? (
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(320px, 1fr))", gap: 14 }}>
          {cohort.map((e, i) => <V5Card key={e.ticker} entry={e} win={win} rank={i} total={cohort.length} />)}
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
          <Tip tip={GLOSS.v5Tracking} style={{ textTransform: "uppercase", letterSpacing: 0.6, fontSize: 11.5 }}>
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

function probText(row) {
  if (row.status === "au-dessus") return <>P(doubler) <b style={{ color: "#00e096" }}>×4</b> · P(−50 %) <b style={{ color: "#00e096" }}>÷2</b></>;
  if (row.status === "sous le seuil") return <>P(doubler) <b style={{ color: "#ff6b6b" }}>÷4</b> · P(−50 %) <b style={{ color: "#ff6b6b" }}>×2</b> — 31 % des explosions étaient encore négatives ici</>;
  if (row.checkpoint === "fenêtre 63j close") return <>résultat à 63 j : <b>{pctFmt(row.ret_63)}</b></>;
  return "—";
}

function TrackingSection({ tracking }) {
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
                  }} title={h === "Checkpoint" ? GLOSS.checkpoint : undefined}>{h}{h === "Checkpoint" ? " ⓘ" : ""}</th>
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
                  <td style={{ padding: "10px 14px", borderBottom: "1px solid #1e2a36", color: "#d7e0e8", fontFamily: "'Segoe UI', sans-serif", fontSize: 12.5 }}>{probText(r)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {tracking.length > 0 && (
        <div style={{ fontSize: 12.5, color: "#5a6a79", borderLeft: "2px solid #f0c040", padding: "4px 12px", marginTop: 10 }}>
          Vendre automatiquement sous le seuil détruit le rendement mesuré du panier (+1,4 % → −0,4 %) :
          les stops coupent la réversion. Ces lignes informent la décision humaine, rien d'autre.
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
    : <>Aujourd'hui : <b>pas de cohorte v4</b> — {v4.mkt21 != null ? `marché haussier (IWM 21 j ${pctFmt(v4.mkt21)})` : "état du marché indisponible"}, la méthode est en pause</>;

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
                  <Tip down tip={GLOSS.mktSwitch}>Marché : IWM</Tip>
                  {V5_WINDOWS.map(w => (
                    <button key={w} onClick={() => setMktWin(w)} style={{
                      background: mktWin === w ? "#1c2f42" : "transparent",
                      border: `1px solid ${mktWin === w ? "#2b4b66" : "#1e2a36"}`,
                      borderRadius: 3, color: mktWin === w ? "#d7e0e8" : "#5a6a79",
                      fontSize: 12, fontFamily: "monospace", padding: "2px 7px", cursor: "pointer",
                    }}>{w} j</button>
                  ))}
                  <b style={{ color: mkt == null ? "#5a6a79" : mkt < 0 ? "#ff6b6b" : "#00e096" }}>{pctFmt(mkt)}</b>
                  {v5.flash && (
                    <Tip down tip={GLOSS.flash} style={{
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

        <V4Section cohort={v4.cohort} note={v4.note} mkt21={v4.mkt21} prelist={v4.prelist} />
        <V5Section v5={v5} win={mktWin} />
        <TrackingSection tracking={v4.tracking} />

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
            <b>Traçabilité</b> : chaque chiffre affiché provient d'une table gelée de l'Annexe A du
            protocole v4 (ou du protocole v2 §9 pour les profils) — rien d'inventé, rien de recalculé
            en direct. Tous les termes : <code>docs/glossaire.md</code>.
          </p>
        </div>
      </div>
    </div>
  );
}
