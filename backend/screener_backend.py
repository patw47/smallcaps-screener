"""
SmallCaps Screener — configuration partagée du backend.

Le scan (entonnoir deux passes, score, profils, cohortes) a été supprimé par la refonte
de l'Epic 15 (Sprint 2). Il reste ici ce que lisent les modules gardés (`edgar`,
`lifecycle`, `finviz`, `study`) : les seuils dans `FILTERS`, le répertoire de données et
l'overlay de config locale.
"""

import os
from pathlib import Path

import yaml

# ---------------------------------------------------------------------------
# FILTRES — tous les seuils configurables ici
# ---------------------------------------------------------------------------
FILTERS = {
    # --- EDGAR : dépôts officiels (dilution, retard, continuité, cash runway) ---
    "insider_window_days": 180,     # fenêtre d'agrégation des achats nets (Form 4)
    "survival_window_days": 180,    # fenêtre des signaux de survie EDGAR (dilution, NT)
    "edgar_cache_ttl_hours": 24,    # TTL cache des listes de filings (soumissions par CIK)
    "edgar_rate_limit_s": 0.12,     # ≥0.11 → ≤ ~9 req/s (SEC exige ≤ 10 req/s)
    "edgar_max_filings": 12,        # garde-fou : nb max de Form 4 parsés par ticker
    # --- Marqueur « cours sous le plancher de cotation » : la règle de la place de
    # cotation ne mord qu'après une SÉRIE CONSÉCUTIVE sous le plancher.
    "sub_dollar_price": 1.0,        # plancher de cotation (USD)
    "sub_dollar_min_days": 30,      # séances consécutives sous le plancher avant que la règle morde
    "sub_dollar_window": 63,        # fenêtre d'observation (~3 mois de séances)
    "reverse_split_window": 252,    # fenêtre (séances) du marqueur de regroupement d'actions
}

# ---------------------------------------------------------------------------
# Overlay de config locale (Epic 6 S1) — config/local.yml, gitignoré, YAML.
# Sans fichier : defaults inchangés. REQUIRE_LOCAL_CONFIG=1 : refus de démarrer
# sans fichier.
# ---------------------------------------------------------------------------
CONFIG_FILE = Path(os.environ.get("CONFIG_FILE", "/app/config/local.yml"))


class LocalConfigError(RuntimeError):
    """Config locale invalide, ou absente alors que REQUIRE_LOCAL_CONFIG=1."""


def _deep_merge(base: dict, overlay: dict, path: str) -> None:
    """Merge récursif overlay → base ; clé absente des defaults = erreur (anti-typo)."""
    for key, value in overlay.items():
        if key not in base:
            raise LocalConfigError(f"config locale : clé inconnue '{path}{key}'")
        if isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value, f"{path}{key}.")
        else:
            base[key] = value


def load_local_config(path: Path | None = None, filters: dict | None = None) -> None:
    """Surcharge `filters` (défaut : FILTERS) avec config/local.yml si présent."""
    path = CONFIG_FILE if path is None else path
    filters = FILTERS if filters is None else filters
    if not path.exists():
        if os.environ.get("REQUIRE_LOCAL_CONFIG") == "1":
            raise LocalConfigError(
                f"REQUIRE_LOCAL_CONFIG=1 mais {path} absent — refus de démarrer"
            )
        return
    raw = yaml.safe_load(path.read_text())
    if raw is None:
        return
    if not isinstance(raw, dict):
        raise LocalConfigError(f"config locale : la racine de {path} doit être un mapping YAML")
    for key, value in raw.items():
        value = value or {}
        if not isinstance(value, dict):
            raise LocalConfigError(f"config locale : la section '{key}' doit être un mapping")
        if key == "filters":
            _deep_merge(filters, value, "filters.")
        elif key == "finviz":
            # Source optionnelle (Epic 13) : le module lit lui-même sa section (une clé
            # inconnue y est IGNORÉE). Enregistrée ici, sinon refusée comme inconnue.
            import finviz
            finviz.load_config(path)
        elif key == "study":
            # Étude hors ligne (Epic 15 S1) : lue par backend/study/lake.py, rien ici.
            pass
        else:
            raise LocalConfigError(
                f"config locale : section inconnue '{key}' (attendu : filters, finviz, study)"
            )


load_local_config()

DATA_DIR = os.environ.get("DATA_DIR", "/app/data")
os.makedirs(DATA_DIR, exist_ok=True)
