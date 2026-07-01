import { useState, useEffect, useCallback } from "react";

const INSTRUMENTS = ["All", "Technology", "Healthcare", "Energy", "Industrials", "Consumer Cyclical"];

function normalizeStocks(raw) {
  return raw.map(s => ({
    ticker: s.ticker,
    name: s.name,
    sector: s.sector,
    price: s.price,
    change1d: s.change_1d != null ? +(s.change_1d * 100).toFixed(2) : 0,
    change1m: s.change_1m != null ? +(s.change_1m * 100).toFixed(2) : 0,
    marketCap: s.market_cap_m,
    ipoYear: s.ipo_year,
    volumeRatio: s.vol_ratio,
    volatility: s.compressed ? "low" : "normal",
    cashPositive: s.cash_positive,
    insiderBuying: s.insider_buying,
    catalystDate: s.catalyst_date,
    catalystType: s.catalyst_type,
    // Score, points positifs et flags viennent DIRECTEMENT du backend (source de vérité).
    score: s.score ?? 0,
    positives: s.positives ?? [],
    flags: s.flags ?? [],
  }));
}

function ScoreBar({ score }) {
  const color = score >= 8 ? "#00ff9d" : score >= 6 ? "#f0c040" : "#ff6b6b";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
      <div style={{ flex: 1, height: 4, background: "#1a1a2e", borderRadius: 2, overflow: "hidden" }}>
        <div style={{ width: `${score * 10}%`, height: "100%", background: color, borderRadius: 2, transition: "width 1s ease" }} />
      </div>
      <span style={{ color, fontFamily: "monospace", fontSize: 13, fontWeight: 700, minWidth: 32 }}>{score}/10</span>
    </div>
  );
}

function StockCard({ stock, onAnalyze, analysis, isLoading }) {
  const { score = 0, positives = [], flags = [] } = stock;   // score backend
  const changeColor = (v) => v >= 0 ? "#00ff9d" : "#ff6b6b";

  return (
    <div style={{
      background: "linear-gradient(135deg, #0d0d1a 0%, #111128 100%)",
      border: `1px solid ${score >= 8 ? "#00ff9d33" : score >= 6 ? "#f0c04033" : "#ffffff11"}`,
      borderRadius: 12,
      padding: "20px 22px",
      position: "relative",
      overflow: "hidden",
      transition: "transform 0.2s ease, box-shadow 0.2s ease",
    }}
      onMouseEnter={e => { e.currentTarget.style.transform = "translateY(-2px)"; e.currentTarget.style.boxShadow = "0 8px 32px #00ff9d18"; }}
      onMouseLeave={e => { e.currentTarget.style.transform = "translateY(0)"; e.currentTarget.style.boxShadow = "none"; }}
    >
      <div style={{ position: "absolute", top: 0, right: 0, width: 80, height: 80, background: score >= 8 ? "radial-gradient(circle, #00ff9d08 0%, transparent 70%)" : "transparent", borderRadius: "0 12px 0 80px" }} />

      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", marginBottom: 12 }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
            <span style={{ fontFamily: "'Courier New', monospace", fontSize: 18, fontWeight: 700, color: "#e8e8ff", letterSpacing: 1 }}>{stock.ticker}</span>
            <span style={{ background: "#ffffff0d", color: "#8888aa", fontSize: 10, padding: "2px 8px", borderRadius: 20, fontFamily: "monospace" }}>{stock.sector}</span>
            <span style={{ background: "#00ff9d0d", color: "#00cc7a", fontSize: 10, padding: "2px 8px", borderRadius: 20, fontFamily: "monospace" }}>IPO {stock.ipoYear}</span>
          </div>
          <div style={{ color: "#5555aa", fontSize: 12, marginTop: 3 }}>{stock.name}</div>
        </div>
        <div style={{ textAlign: "right" }}>
          <div style={{ fontSize: 20, fontWeight: 700, color: "#e8e8ff", fontFamily: "monospace" }}>${stock.price}</div>
          <div style={{ fontSize: 12, color: changeColor(stock.change1d), fontFamily: "monospace" }}>{stock.change1d > 0 ? "+" : ""}{stock.change1d}% today</div>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr 1fr", gap: 8, marginBottom: 14 }}>
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

      <div style={{ marginBottom: 14 }}>
        <ScoreBar score={score} />
      </div>

      <div style={{ display: "flex", flexWrap: "wrap", gap: 5, marginBottom: 14 }}>
        {positives.map(p => (
          <span key={p} style={{ background: "#00ff9d0d", color: "#00cc7a", fontSize: 10, padding: "3px 8px", borderRadius: 20, border: "1px solid #00ff9d22" }}>✓ {p}</span>
        ))}
        {flags.map(f => (
          <span key={f} style={{ background: "#ff6b6b0d", color: "#ff6b6b", fontSize: 10, padding: "3px 8px", borderRadius: 20, border: "1px solid #ff6b6b22" }}>⚠ {f}</span>
        ))}
      </div>

      {stock.catalystDate && (
        <div style={{ background: "#f0c04008", border: "1px solid #f0c04022", borderRadius: 8, padding: "8px 12px", marginBottom: 14, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <span style={{ color: "#f0c040", fontSize: 11 }}>📅 {stock.catalystType}</span>
          <span style={{ color: "#888899", fontSize: 11, fontFamily: "monospace" }}>{stock.catalystDate}</span>
        </div>
      )}

      {analysis && (
        <div style={{ background: "#0a0a1f", border: "1px solid #2222aa44", borderRadius: 8, padding: "14px 16px", marginBottom: 14, animation: "fadeIn 0.4s ease" }}>
          <div style={{ color: "#6666dd", fontSize: 10, textTransform: "uppercase", letterSpacing: 1, marginBottom: 8 }}>⚡ Analyse Claude</div>
          <div style={{ color: "#c0c0e0", fontSize: 13, lineHeight: 1.7, whiteSpace: "pre-wrap" }}>{analysis}</div>
        </div>
      )}

      <button
        onClick={() => onAnalyze(stock)}
        disabled={isLoading}
        style={{
          width: "100%",
          padding: "10px",
          background: isLoading ? "#1a1a3a" : "linear-gradient(90deg, #1a1a4a, #2a2a6a)",
          border: "1px solid #3333aa",
          borderRadius: 8,
          color: isLoading ? "#4444aa" : "#8888ff",
          fontSize: 12,
          fontFamily: "monospace",
          cursor: isLoading ? "not-allowed" : "pointer",
          letterSpacing: 0.5,
          transition: "all 0.2s ease",
        }}
        onMouseEnter={e => { if (!isLoading) { e.target.style.background = "linear-gradient(90deg, #2a2a6a, #3a3a9a)"; e.target.style.color = "#aaaaff"; } }}
        onMouseLeave={e => { if (!isLoading) { e.target.style.background = "linear-gradient(90deg, #1a1a4a, #2a2a6a)"; e.target.style.color = "#8888ff"; } }}
      >
        {isLoading ? "⟳ Analyse en cours..." : analysis ? "↻ Ré-analyser" : "⚡ Analyser avec Claude"}
      </button>
    </div>
  );
}

export default function App() {
  const [stocks, setStocks] = useState([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [sector, setSector] = useState("All");
  const [minScore, setMinScore] = useState(0);
  const [analyses, setAnalyses] = useState({});
  const [loadingTickers, setLoadingTickers] = useState({});
  const [lastScan, setLastScan] = useState(null);

  const fetchData = useCallback(() => {
    return fetch("/api/scan")
      .then(r => {
        if (!r.ok) throw new Error(`HTTP ${r.status}`);
        return r.json();
      })
      .then(json => {
        setStocks(normalizeStocks(json.stocks ?? []));
        if (json.scanned_at) setLastScan(new Date(json.scanned_at).toLocaleTimeString("fr-FR"));
      })
      .catch(console.error);
  }, []);

  useEffect(() => {
    fetchData().finally(() => setLoading(false));
  }, [fetchData]);

  const runScan = () => {
    setScanning(true);
    fetch("/api/scan/force", { method: "POST" })
      .then(() => fetchData())
      .catch(console.error)
      .finally(() => setScanning(false));
  };

  const analyzeStock = useCallback(async (stock) => {
    setLoadingTickers(prev => ({ ...prev, [stock.ticker]: true }));
    const { score = 0, positives = [], flags = [] } = stock;   // score backend

    const prompt = `Tu es un analyste spécialisé small caps US. Analyse ce profil d'action et donne un brief concis en 4-5 lignes.

Action: ${stock.ticker} — ${stock.name}
Secteur: ${stock.sector} | IPO: ${stock.ipoYear} | Prix: $${stock.price}
Market Cap: $${stock.marketCap}M | Volume ratio 10j/50j: ${stock.volumeRatio}x
Performance 1 mois: ${stock.change1m}% | Volatilité récente: ${stock.volatility}
Cash positif: ${stock.cashPositive ? "Oui" : "Non"} | Insider buying: ${stock.insiderBuying ? "Oui" : "Non"}
Catalyseur attendu: ${stock.catalystType} le ${stock.catalystDate}
Score setup: ${score}/10
Points positifs: ${positives.join(", ")}
Red flags: ${flags.length > 0 ? flags.join(", ") : "Aucun"}

Réponds en français. Structure:
1. Pourquoi c'est intéressant (ou pas)
2. Niveau à surveiller
3. Risque principal
4. Verdict en une phrase`;

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
          max_tokens: 1000,
          messages: [{ role: "user", content: prompt }]
        })
      });
      const data = await response.json();
      const text = data.content?.find(b => b.type === "text")?.text || "Analyse indisponible";
      setAnalyses(prev => ({ ...prev, [stock.ticker]: text }));
    } catch (e) {
      setAnalyses(prev => ({ ...prev, [stock.ticker]: "Erreur lors de l'analyse. Vérifie ta connexion." }));
    }
    setLoadingTickers(prev => ({ ...prev, [stock.ticker]: false }));
  }, []);

  const filtered = stocks
    .filter(s => {
      if (sector !== "All" && s.sector !== sector) return false;
      if ((s.score ?? 0) < minScore) return false;
      return true;
    })
    .sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

  if (loading) {
    return (
      <div style={{ minHeight: "100vh", background: "#070714", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", gap: 20 }}>
        <style>{`@keyframes pulse { 0%,100%{opacity:1} 50%{opacity:0.3} } @keyframes spin { to{transform:rotate(360deg)} }`}</style>
        <div style={{ width: 32, height: 32, border: "2px solid #00ff9d22", borderTop: "2px solid #00ff9d", borderRadius: "50%", animation: "spin 1s linear infinite" }} />
        <div style={{ fontFamily: "monospace", color: "#00ff9d", fontSize: 13, letterSpacing: 3, textTransform: "uppercase" }}>Scan en cours...</div>
        <div style={{ fontFamily: "monospace", color: "#33335a", fontSize: 11 }}>Analyse du marché (~2–3 min)</div>
      </div>
    );
  }

  return (
    <div style={{
      minHeight: "100vh",
      background: "#070714",
      fontFamily: "'Segoe UI', sans-serif",
      color: "#e8e8ff",
      padding: "0 0 60px",
    }}>
      <style>{`
        @keyframes fadeIn { from { opacity: 0; transform: translateY(6px); } to { opacity: 1; transform: translateY(0); } }
        @keyframes pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.4; } }
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 4px; }
        ::-webkit-scrollbar-track { background: #0a0a1a; }
        ::-webkit-scrollbar-thumb { background: #2a2a6a; border-radius: 2px; }
      `}</style>

      {/* Header */}
      <div style={{
        background: "linear-gradient(180deg, #0a0a20 0%, #070714 100%)",
        borderBottom: "1px solid #ffffff0a",
        padding: "28px 32px 24px",
        position: "sticky", top: 0, zIndex: 100,
        backdropFilter: "blur(20px)",
      }}>
        <div style={{ maxWidth: 1100, margin: "0 auto" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 16 }}>
            <div>
              <div style={{ display: "flex", alignItems: "center", gap: 12, marginBottom: 4 }}>
                <div style={{ width: 8, height: 8, borderRadius: "50%", background: "#00ff9d", animation: "pulse 2s infinite" }} />
                <span style={{ fontFamily: "'Courier New', monospace", fontSize: 11, color: "#00ff9d", letterSpacing: 3, textTransform: "uppercase" }}>Small Cap Radar</span>
              </div>
              <h1 style={{ margin: 0, fontSize: 26, fontWeight: 800, letterSpacing: -0.5, color: "#e8e8ff" }}>
                Pépites <span style={{ color: "#4444cc" }}>avant</span> le rallye
              </h1>
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
              {lastScan && <span style={{ color: "#33335a", fontSize: 11, fontFamily: "monospace" }}>Dernier scan: {lastScan}</span>}
              <button onClick={runScan} disabled={scanning} style={{
                padding: "10px 20px",
                background: scanning ? "#1a1a3a" : "linear-gradient(90deg, #00cc7a, #0066ff)",
                border: "none", borderRadius: 8,
                color: scanning ? "#33335a" : "#fff",
                fontSize: 12, fontWeight: 700, fontFamily: "monospace",
                cursor: scanning ? "not-allowed" : "pointer",
                letterSpacing: 0.5,
              }}>
                {scanning ? "⟳ Scan..." : "▶ Scanner le marché"}
              </button>
            </div>
          </div>
        </div>
      </div>

      <div style={{ maxWidth: 1100, margin: "0 auto", padding: "0 24px" }}>

        {/* Stats bar */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12, margin: "24px 0" }}>
          {[
            { label: "Candidates", value: filtered.length, color: "#8888ff" },
            { label: "Score moyen", value: (filtered.reduce((a, s) => a + (s.score ?? 0), 0) / (filtered.length || 1)).toFixed(1) + "/10", color: "#f0c040" },
            { label: "Avec catalyseur", value: filtered.filter(s => s.catalystDate).length, color: "#00cc7a" },
            { label: "Insider buying", value: filtered.filter(s => s.insiderBuying).length, color: "#ff9966" },
          ].map(({ label, value, color }) => (
            <div key={label} style={{ background: "#0d0d1a", border: "1px solid #ffffff08", borderRadius: 10, padding: "14px 18px" }}>
              <div style={{ color: "#33335a", fontSize: 10, textTransform: "uppercase", letterSpacing: 0.5, marginBottom: 4 }}>{label}</div>
              <div style={{ color, fontSize: 22, fontWeight: 700, fontFamily: "monospace" }}>{value}</div>
            </div>
          ))}
        </div>

        {/* Filters */}
        <div style={{ display: "flex", gap: 12, marginBottom: 24, flexWrap: "wrap", alignItems: "center" }}>
          <div style={{ display: "flex", gap: 6, flexWrap: "wrap" }}>
            {INSTRUMENTS.map(s => (
              <button key={s} onClick={() => setSector(s)} style={{
                padding: "6px 14px",
                background: sector === s ? "#2a2a6a" : "#0d0d1a",
                border: `1px solid ${sector === s ? "#4444aa" : "#ffffff0a"}`,
                borderRadius: 20, color: sector === s ? "#aaaaff" : "#44446a",
                fontSize: 12, fontFamily: "monospace", cursor: "pointer", transition: "all 0.15s ease",
              }}>{s}</button>
            ))}
          </div>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginLeft: "auto" }}>
            <span style={{ color: "#33335a", fontSize: 11, fontFamily: "monospace" }}>Score min:</span>
            {[0, 5, 7, 9].map(v => (
              <button key={v} onClick={() => setMinScore(v)} style={{
                padding: "5px 12px",
                background: minScore === v ? "#1a1a4a" : "transparent",
                border: `1px solid ${minScore === v ? "#3333aa" : "#ffffff0a"}`,
                borderRadius: 6, color: minScore === v ? "#8888ff" : "#33335a",
                fontSize: 11, fontFamily: "monospace", cursor: "pointer",
              }}>{v === 0 ? "Tous" : `${v}+`}</button>
            ))}
          </div>
        </div>

        {/* Cards grid */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 16 }}>
          {filtered.map(stock => (
            <StockCard
              key={stock.ticker}
              stock={stock}
              onAnalyze={analyzeStock}
              analysis={analyses[stock.ticker]}
              isLoading={loadingTickers[stock.ticker]}
            />
          ))}
        </div>

        {filtered.length === 0 && (
          <div style={{ textAlign: "center", padding: "80px 0", color: "#22224a" }}>
            <div style={{ fontSize: 40, marginBottom: 12 }}>◎</div>
            <div style={{ fontFamily: "monospace", fontSize: 14 }}>
              {stocks.length === 0 ? "Scan en cours... relancez dans quelques instants" : "Aucune candidate avec ces filtres"}
            </div>
          </div>
        )}

        {/* Legend */}
        <div style={{ marginTop: 40, padding: "20px 24px", background: "#0a0a18", border: "1px solid #ffffff06", borderRadius: 12 }}>
          <div style={{ color: "#22224a", fontSize: 10, textTransform: "uppercase", letterSpacing: 1, marginBottom: 12, fontFamily: "monospace" }}>Logique de scoring</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(220px, 1fr))", gap: 8 }}>
            {[
              "Volume ratio 1.3–2.5x → accumulation discrète",
              "Volatilité faible → prix compressé",
              "Perf 1 mois < 15% → pas encore rallié",
              "Insider buying → signal interne fort",
              "Cash positif → pas de risque dilution",
              "Catalyseur identifiable → timing clair",
              "IPO récente → pas une zombie",
            ].map(item => (
              <div key={item} style={{ color: "#33335a", fontSize: 11, fontFamily: "monospace", display: "flex", gap: 6 }}>
                <span style={{ color: "#2a2a6a" }}>▸</span> {item}
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
