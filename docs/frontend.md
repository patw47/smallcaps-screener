# Frontend

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

`compressed` is converted into `volatility` (`true` → `"low"`, `false` → `"normal"`).

## Scoring

The frontend uses the **backend score directly** (`stock.score`, `stock.positives`,
`stock.flags`). The score bar, the "Score moyen" stat, the minimum-score filter, and
the sort all read `stock.score`. There is no browser-side scoring anymore — the old
`scoreStock` function was removed so the UI reflects the backend's assessment exactly.

See [backend.md](backend.md) for the scoring model and weights. The score is a
**decile rank of a continuous-factor percentile composite** (0–10), so it spreads the
full range and the best candidate of the current scan shows 10. It is a *relative*
score ("how good among today's candidates"), not an absolute rating.

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

- Sector filter from `INSTRUMENTS`.
- Minimum score filter with preset values `0`, `5`, `7`, and `9`.
- Final results are sorted by local frontend score descending.

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

### `ScoreBar`

Displays the current score as a horizontal bar:

- Green for scores >= 8.
- Yellow for scores >= 6.
- Red for lower scores.

### `StockCard`

Displays:

- Ticker, name, sector, IPO year.
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
