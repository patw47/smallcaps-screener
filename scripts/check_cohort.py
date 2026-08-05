"""
Étanchéité de la cohorte de suivi (Epic 9 S1).

Rejoue le suivi des deux familles sur l'historique COURANT en partant d'un
dictionnaire de prix VIDE, donc sans l'univers découvert aujourd'hui. Toute ligne
encore lue « données absentes » est ensuite confrontée à un appel isolé : si le
titre cote, la cohorte fuit et la cible rougit en nommant les fautifs.

Partir du vide n'est pas un artifice de test : c'est précisément ce qui vérifie
que le suivi ne dépend plus de l'univers du jour. Sur du code qui ne complète pas
le dictionnaire, TOUTES les lignes tombent en « données absentes » et la cible
rougit — c'est la rougeur attendue avant correction.

Réseau requis (c'est une vérification de données, pas un gate de dépôt). Tourne
dans le conteneur, seul porteur de l'historique vivant : `make check-cohort`.
"""
import sys

import yfinance as yf

import lifecycle
import v4
import v5
from screener_backend import HISTORY_DIR, _extract_symbol


def _quotes_after(ticker: str, entry_date: str) -> int:
    """Nombre de séances postérieures à l'entrée, en appel ISOLÉ. 0 si muet."""
    try:
        data = yf.download(ticker, start=entry_date, interval="1d", auto_adjust=True,
                           group_by="ticker", threads=False, progress=False)
        df = _extract_symbol(data, ticker) if data is not None and len(data) else None
        if df is None or "Close" not in df:
            return 0
        return len(lifecycle._after_entry(df["Close"].dropna(), entry_date))
    except Exception as e:
        print(f"  [{ticker}] appel isolé indisponible : {e}")
        return 0


def main() -> int:
    prices: dict = {}          # partagé : le complément d'une famille sert à l'autre
    rows = v4.build_tracking(prices, HISTORY_DIR) + v5.build_tracking(prices, HISTORY_DIR)
    if not rows:
        print("check-cohort : aucun titre suivi dans l'historique — rien à vérifier")
        return 0

    absent = {(r["ticker"], r["entry_date"]) for r in rows if r["phase"] == "no_data"}
    faulty = []
    for tk, day in sorted(absent):
        n = _quotes_after(tk, day)
        if n:
            faulty.append(f"{tk} (entré le {day}, {n} séances cotées depuis)")

    print(f"[check-cohort] {len(rows)} lignes suivies · {len(absent)} en données absentes")
    if faulty:
        print("check-cohort ÉCHEC — titres cotés marqués « données absentes » :")
        for f in faulty:
            print(f"  - {f}")
        return 1
    print("check-cohort OK (toute donnée absente confirmée sans cotation en appel isolé)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
