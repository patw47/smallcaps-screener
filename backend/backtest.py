"""
Harnais de validation (backtest forward) — #1 des recommandations.

Objectif : mesurer si les titres retenus par la Passe A (filtres prix/volume :
liquidité, tendance, RS, compression, accumulation) **surperforment l'univers**
sur les N jours suivants. C'est le seul moyen de calibrer les seuils sur des
faits plutôt que sur l'intuition.

Méthode :
1. Télécharger ~2 ans d'historique pour un échantillon reproductible de tickers.
2. Se placer à une date « as-of » = dernier jour - `forward_days` (il reste donc
   `forward_days` de données APRÈS pour mesurer le rendement forward).
3. Rejouer `analyze_prices` sur l'historique TRONQUÉ à la date as-of.
4. Comparer le rendement forward des survivants vs tout l'univers testé vs IWM.
5. Ventiler les survivants par quartile de force relative (RS continue) pour voir
   si une RS plus forte prédit un meilleur rendement.

LIMITES HONNÊTES (à garder en tête en lisant les chiffres) :
- **Biais de survie** : les tickers délistés ne sont plus dans l'univers courant.
- **Pas de fondamentaux point-in-time** : yfinance ne donne pas le `.info` passé.
  → le backtest valide UNIQUEMENT les signaux prix/volume (ceux qui pilotent la
  sélection dure), pas le scoring fondamental.
- **Un seul instantané as-of** : ce n'est pas un backtest roulant multi-période.

Usage : DATA_DIR=/tmp/bt PYTHONPATH=backend python backtest.py --n 200 --forward 63
"""

import argparse
import statistics

import pandas as pd

from screener_backend import (
    FILTERS, discover_tickers, analyze_prices, _download_prices, _price_score,
)


def _forward_return(close: pd.Series, as_of_idx: int, forward_days: int) -> float | None:
    """Rendement de as_of_idx à as_of_idx + forward_days (pur, testable hors ligne)."""
    if close is None or as_of_idx < 0 or as_of_idx + forward_days >= len(close):
        return None
    base = close.iloc[as_of_idx]
    fwd = close.iloc[as_of_idx + forward_days]
    if base == 0:
        return None
    return float(fwd / base - 1)


def evaluate_ticker(df: pd.DataFrame, bench_close: pd.Series | None,
                    forward_days: int) -> tuple[bool, float, int | None] | None:
    """
    Évalue un ticker à as_of = dernier jour - forward_days.
    Retourne (survécu, rendement_forward, score_technique) ou None si données insuffisantes.
    Le score technique est celui utilisé pour classer (accumulation en tête).
    """
    if df is None or "Close" not in df:
        return None
    close = df["Close"].dropna()
    as_of_idx = len(close) - 1 - forward_days
    if as_of_idx < FILTERS["vol_window_long"] + FILTERS["ma_slope_lookback"]:
        return None
    fwd = _forward_return(close, as_of_idx, forward_days)
    if fwd is None:
        return None

    as_of_date = close.index[as_of_idx]
    df_trunc = df.loc[df.index <= as_of_date]                      # historique connu à as_of
    bench_trunc = (bench_close[bench_close.index <= as_of_date]
                   if bench_close is not None else None)
    signals, _ = analyze_prices("BT", df_trunc, bench_trunc)
    survived = signals is not None
    score = _price_score(signals) if signals else None
    return survived, fwd, score


def _stats(xs: list[float]) -> dict:
    if not xs:
        return {"n": 0, "mean": None, "median": None, "hit": None}
    return {
        "n": len(xs),
        "mean": statistics.mean(xs),
        "median": statistics.median(xs),
        "hit": sum(1 for x in xs if x > 0) / len(xs),
    }


def run_backtest(n_tickers: int = 200, forward_days: int = 63,
                 seed: int = 42, period: str = "2y",
                 tickers: list[str] | None = None) -> dict:
    # Reproductibilité : fixer le seed de découverte le temps du backtest
    prev_seed = FILTERS["shuffle_seed"]
    FILTERS["shuffle_seed"] = seed
    try:
        universe = tickers if tickers is not None else discover_tickers()
    finally:
        FILTERS["shuffle_seed"] = prev_seed
    universe = universe[:n_tickers]

    print(f"\n{'='*60}\n  BACKTEST — {len(universe)} tickers, forward {forward_days}j, seed {seed}\n{'='*60}")
    prices = _download_prices(universe, FILTERS["rs_benchmark"], period=period)
    bench_df = prices.pop(FILTERS["rs_benchmark"], None)
    bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None

    survivors_fwd: list[float] = []
    all_fwd: list[float] = []
    survivor_score: list[tuple[int, float]] = []   # (score_technique, fwd)

    for tk, df in prices.items():
        res = evaluate_ticker(df, bench_close, forward_days)
        if res is None:
            continue
        survived, fwd, score = res
        all_fwd.append(fwd)
        if survived:
            survivors_fwd.append(fwd)
            if score is not None:
                survivor_score.append((score, fwd))

    # Rendement forward du benchmark sur le même horizon
    bench_fwd = None
    if bench_close is not None:
        bench_fwd = _forward_return(bench_close, len(bench_close) - 1 - forward_days, forward_days)

    surv = _stats(survivors_fwd)
    univ = _stats(all_fwd)
    edge = (surv["mean"] - univ["mean"]) if (surv["mean"] is not None and univ["mean"] is not None) else None

    # Ventilation par quartile de SCORE technique : plus le score est haut,
    # meilleur le rendement forward ? (le vrai test du scoring accumulation-en-tête)
    score_buckets = []
    if len(survivor_score) >= 4:
        survivor_score.sort(key=lambda x: x[0])
        q = len(survivor_score) // 4
        for i, label in enumerate(["Q1 (score bas)", "Q2", "Q3", "Q4 (score haut)"]):
            chunk = survivor_score[i * q:(i + 1) * q] if i < 3 else survivor_score[i * q:]
            fwds = [f for _, f in chunk]
            score_buckets.append((label, _stats(fwds)["mean"]))

    result = {
        "n_tested": univ["n"], "n_survivors": surv["n"],
        "survivor": surv, "universe": univ, "benchmark_fwd": bench_fwd,
        "edge_vs_universe": edge, "score_quartiles": score_buckets,
        "forward_days": forward_days, "seed": seed,
    }
    _print_report(result)
    return result


def _pct(x):
    return "   n/a" if x is None else f"{x*100:+6.2f}%"


def _hit(x):
    return "   n/a" if x is None else f"{x*100:5.1f}%"


def _print_report(r: dict) -> None:
    s, u = r["survivor"], r["universe"]
    print(f"\n{'='*60}\n  RÉSULTAT (forward {r['forward_days']}j)\n{'='*60}")
    print(f"  Testés (données OK) : {r['n_tested']}")
    print(f"  Survivants Passe A  : {r['n_survivors']}")
    print(f"\n  {'':<20}{'moyenne':>9}{'médiane':>9}{'hit-rate':>10}")
    print(f"  {'Survivants':<20}{_pct(s['mean']):>9}{_pct(s['median']):>9}{_hit(s['hit']):>10}")
    print(f"  {'Univers testé':<20}{_pct(u['mean']):>9}{_pct(u['median']):>9}{_hit(u['hit']):>10}")
    print(f"  {'Benchmark (IWM)':<20}{_pct(r['benchmark_fwd']):>9}")
    print(f"\n  EDGE survivants − univers : {_pct(r['edge_vs_universe'])}")
    if r["score_quartiles"]:
        print("\n  Rendement forward moyen par quartile de score technique :")
        for label, mean in r["score_quartiles"]:
            print(f"    {label:<18} {_pct(mean)}")
    print("\n  ⚠️  Biais de survie + signaux prix/volume seuls (pas de fondamentaux point-in-time).")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest forward du screener (signaux prix/volume)")
    ap.add_argument("--n", type=int, default=200, help="nombre de tickers échantillonnés")
    ap.add_argument("--forward", type=int, default=63, help="horizon forward en jours de bourse")
    ap.add_argument("--seed", type=int, default=42, help="seed de reproductibilité")
    ap.add_argument("--period", type=str, default="2y", help="profondeur d'historique (yfinance)")
    args = ap.parse_args()
    run_backtest(n_tickers=args.n, forward_days=args.forward, seed=args.seed, period=args.period)
