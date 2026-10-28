import { useState, useEffect } from "react";
import { t, lang as savedLang, setLang } from "./i18n/index.js";

// Page réduite par la refonte de l'Epic 15 (Sprint 2) : listes, badges, suivi et
// résultats supprimés avec le scan qui les produisait. Les alertes après publication
// de résultats arrivent au Sprint 5 ; d'ici là, la page affiche son état vide.
export default function App() {
  // Bascule FR/EN : le setState force le re-render, t() lit la langue du module.
  const [uiLang, setUiLang] = useState(savedLang);
  const switchLang = (l) => { setLang(l); setUiLang(l); };
  useEffect(() => { document.documentElement.lang = uiLang; }, [uiLang]);

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
        <h2 style={{ fontSize: 15, margin: "0 0 10px", fontWeight: 650, textTransform: "uppercase", letterSpacing: 1.2 }}>
          {t("alerts.title")}
        </h2>
        <p style={{ color: "#8494a3", fontSize: 14, lineHeight: 1.6, margin: 0 }}>{t("alerts.empty")}</p>
      </section>
    </div>
  );
}
