# SmallCaps Screener

Screener automatique de small caps US. Découverte dynamique des candidats via NASDAQ API + Finviz, scoring multi-critères, analyse IA par action via Claude.

## Stack

- **Backend** : Python 3.11, FastAPI, yfinance, BeautifulSoup
- **Frontend** : React + Vite
- **Orchestration** : Docker Compose

## Prérequis

Docker Desktop — c'est tout.

## Lancement

```bash
cp .env.example .env
# Éditer .env et renseigner ANTHROPIC_API_KEY
docker-compose up --build
```

- **Frontend** : http://localhost:5173
- **API** : http://localhost:8000/api/scan
- **Docs API** : http://localhost:8000/docs

Le premier lancement déclenche automatiquement un scan (~2–3 min pour 300 tickers). Les résultats sont mis en cache 30 minutes dans un volume Docker persistant.

## Filtres appliqués

**Filtres durs** (élimination immédiate) :

| Critère | Seuil |
|---------|-------|
| Bourse | NMS, NYQ, NGM, NCM |
| Prix | $2 – $50 |
| Market cap | $50M – $2 000M |
| Historique | ≥ 50 jours |
| Perf 1 mois | -35% à +25% |

**Scoring** (0–10, pas d'élimination) : ratio de volume, compression de range, consolidation 1 mois, insider buying, bilan cash, croissance revenus, IPO récente, short interest élevé.

## Analyse IA

Chaque fiche dispose d'un bouton "Analyser" qui interroge Claude (claude-sonnet-4-6) pour obtenir :
- Pourquoi c'est intéressant (ou pas)
- Niveau à surveiller
- Risque principal
- Verdict en une phrase

Nécessite `ANTHROPIC_API_KEY` dans `.env`.

## Commandes utiles

```bash
# Relancer un scan manuellement
docker-compose exec backend python screener_backend.py

# Forcer un nouveau scan via l'API
curl -X POST http://localhost:8000/api/scan/force

# Logs backend en temps réel
docker-compose logs -f backend

# Arrêt
docker-compose down

# Arrêt + suppression du cache
docker-compose down -v
```

## Variables d'environnement

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | Clé API Anthropic (requise pour l'analyse IA) |
