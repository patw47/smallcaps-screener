# Frontend

> **Epic 2 — the freeze is lifted.** `frontend/smallcap-screener.jsx` was frozen through
> Epic 1; since 2026-07-04 it is **editable**. It must display the **Fusée / Phénix profile
> badges prominently on every stock**, and the **Phénix badge must carry a visible "non
> validé" marker** (survivorship bias not yet corrected — protocol v2 §5). Keep edits focused
> (badges, filtering) — no redesign.
>
> **Epic 3 — survival-conditioned score.** Each card now leads with an **`ExplodeScore`**
> element: the model's **`P(+100 % / 63d)`** (`p_explode`) — the headline v3 signal — plus a
> red **survival-risk flag** (`survival_risk`) when a distress signal is raised. `p_explode` is
> `null` until the study (S5) trains and persists `model_v3.json` → shown honestly as "modèle
> non entraîné", no invented number. The score carries a **permanent "non validé" marker**:
> on free survivor-only data the backtest can only refute (protocol v3 §2); only the live
> tracker (Validation B) can validate it.

## Files

- `frontend/src/main.jsx`: React entry point.
- `frontend/smallcap-screener.jsx`: complete dashboard UI and browser-side data logic.
- `frontend/index.html`: Vite HTML entry.
- `frontend/package.json`: frontend scripts and dependencies.
- `frontend/vite.config.js`: Vite configuration.
- `frontend/Dockerfile`: frontend container definition.

## Application Entry

`frontend/src/main.jsx` mounts the React app:

```jsx
import { createRoot } from "react-dom/client";
import App from "../smallcap-screener.jsx";

createRoot(document.getElementById("root")).render(<App />);
```

## State Model

The main `App` component stores:

| State | Purpose |
| --- | --- |
| `stocks` | Normalized stock list from `/api/scan`. |
| `loading` | Initial scan loading state. |
| `scanning` | Force-scan button state. |
| `sector` | Selected sector filter. |
| `profile` | Selected profile filter (`All` / `Fusée` / `Phénix`, Epic 2). |
| `minScore` | Minimum local score filter. |
| `analyses` | Claude analysis text by ticker. |
| `loadingTickers` | Per-ticker analysis loading state. |
| `lastScan` | Localized display time for `scanned_at`. |

## Backend Data Normalization

Function: `normalizeStocks(raw)`

The backend returns snake_case fields. The frontend maps them into camelCase fields used by the UI:

| Backend | Frontend |
| --- | --- |
| `change_1d` | `change1d` percentage |
| `change_1m` | `change1m` percentage |
| `market_cap_m` | `marketCap` |
| `ipo_year` | `ipoYear` |
| `vol_ratio` | `volumeRatio` |
| `cash_positive` | `cashPositive` |
| `insider_buying` | `insiderBuying` |
| `catalyst_date` | `catalystDate` |
| `catalyst_type` | `catalystType` |
| `score` | `score` (backend score, 0–10) |
| `positives` | `positives` |
| `flags` | `flags` |
| `profile` / `is_fusee` / `is_phenix` | `profile` / `isFusee` / `isPhenix` (Epic 2) |
| `fusee_event` | `fuseeEvent` (Fusée member + same-day breakout) |
| `fusee_strength` / `phenix_strength` / `profile_strength` | `fuseeStrength` / `phenixStrength` / `profileStrength` |

`compressed` is converted into `volatility` (`true` → `"low"`, `false` → `"normal"`).

## Scoring

The frontend uses the **backend score directly** (`stock.score`, `stock.positives`,
`stock.flags`). The score bar, the "Score moyen" stat, the minimum-score filter, and
the sort all read `stock.score`. There is no browser-side scoring anymore — the old
`scoreStock` function was removed so the UI reflects the backend's assessment exactly.

See [backend.md](backend.md) for the scoring model. The score comes from the backend and
depends on `FILTERS["scoring_mode"]`: **binary** (default, ~0–8) or **continuous** (a decile
0–10 rank of a factor percentile composite). The UI renders whatever `stock.score` the
backend sends, so switching the mode changes the numbers with no frontend change.

## Main User Flows

### Initial Load

1. `useEffect()` calls `fetchData()`.
2. `fetchData()` calls `GET /api/scan`.
3. The response is normalized and stored in `stocks`.
4. `lastScan` is derived from `scanned_at`.
5. The loading screen is replaced with the dashboard.

### Force Scan

The "Scanner le marché" button calls:

```text
POST /api/scan/force
```

After the request resolves, the frontend immediately calls `fetchData()` again. Because force scan runs in the backend background, this follow-up request can still return existing data or wait depending on cache and scan timing.

### Filtering

Filtering happens entirely in the browser:

- **Profile filter (Epic 2)**: `All` / `🚀 Fusée` / `🔥 Phénix`, each button showing its
  live count. A `Fusée` / `Phénix` view keeps only members of that profile.
- Sector filter from `INSTRUMENTS`.
- Minimum score filter with preset values `0`, `5`, `7`, and `9`.
- **Sort by profile strength**: in a profile view results are ordered by that profile's
  strength (`fuseeStrength` / `phenixStrength`); in `All` view by `profileStrength` (the max).
  The score column and score filter still work; the score no longer drives the ordering.

### Claude Analysis

Each stock card has an "Analyser avec Claude" button. Clicking it:

1. Builds a French prompt from stock metrics, positives, and flags.
2. Calls `https://api.anthropic.com/v1/messages` directly from the browser.
3. Uses `import.meta.env.VITE_ANTHROPIC_API_KEY`.
4. Stores the returned text in `analyses[ticker]`.

The Docker Compose file maps:

```yaml
VITE_ANTHROPIC_API_KEY: ${ANTHROPIC_API_KEY}
```

Security note: this exposes the key to browser code. Use a backend proxy before production deployment.

## UI Components

### `ProfileBadge` / `ProfileBadges` (Epic 2)

`ProfileBadge` renders one coloured chip per profile: **🚀 Fusée** (green) and **🔥 Phénix**
(orange), each with the member's strength (0–100). A Fusée chip shows a **⚡** when
`fuseeEvent` is set (breakout that day). **Both chips carry a "non validé" tag** (driven by a
per-profile `caveat` tooltip in `PROFILE_STYLE`) since **Validation A failed for each**
(Epic 2 Sprint 6, protocol v2 §6/§9): the tooltip carries that profile's Sprint 5 numbers —
Fusée's dropped-momentum verdict, Phénix's barbell + money-gate. The profile-filter footnote
mirrors it for whichever profile is selected. `ProfileBadges` renders every profile a stock
belongs to (both chips for dual-profile stocks); it returns nothing for a non-member. The
badges sit prominently at the top of each `StockCard`. The stats header shows the
**per-profile candidate counts**.

Rendered UI (Epic 2 Sprint 3, mock data): [`docs/screenshots/epic2-profile-badges-all.png`](screenshots/epic2-profile-badges-all.png)
(All view — dual-profile VXRT shows both chips, FCEL carries the ⚡ event marker) and
[`docs/screenshots/epic2-profile-badges-phenix.png`](screenshots/epic2-profile-badges-phenix.png)
(Phénix filter — only Phénix members, "non validé" markers, sorted by Phénix strength).

### `ScoreBar`

Displays the current score as a horizontal bar:

- Green for scores >= 8.
- Yellow for scores >= 6.
- Red for lower scores.

### `StockCard`

Displays:

- Ticker, name, sector, IPO year.
- **Profile badges** (Fusée / Phénix, Epic 2) — prominent, at the top.
- Price and one-day change.
- Market cap, volume ratio, one-month change.
- Score bar.
- Positive labels and warning flags.
- Optional catalyst block.
- Optional Claude analysis block.
- Analysis action button.

## Development Commands

From `frontend/`:

```bash
npm install
npm run dev
npm run build
npm run preview
```

In Docker Compose, the frontend is served on:

```text
http://localhost:5173
```
