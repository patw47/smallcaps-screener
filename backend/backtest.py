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
import math
import random
import statistics
from collections import defaultdict

import numpy as np
import pandas as pd

from screener_backend import (
    FILTERS, discover_tickers, analyze_prices, _download_prices,
    _factor_composite, _binary_price_score, TECH_FACTORS,
)
from profiles import detect_profiles
from scoring import FEATURE_NAMES
from model import ScoreModel

# ===========================================================================
# Constantes PRÉ-ENREGISTRÉES du protocole v2 (docs/backtest_protocol_v2.md).
# FIGÉES : ce ne sont pas des seuils réglables (fenêtres et critères de succès
# gelés AVANT tout run) → hors FILTERS, exactement comme TAIL_THRESHOLDS de track.py.
# Toute modification = révision du protocole + décision d'epic (jamais un re-fit).
# ===========================================================================
# §4 — fenêtres (bornes de dates inclusives). Exploration = in-sample « dépensée ».
VALIDATION_A_WINDOW = ("2021-07-01", "2023-06-30")   # backward out-of-sample, jugée UNE fois
EXPLORATION_WINDOW = ("2023-07-01", "2026-06-30")    # in-sample, contexte seulement
# §1 — numérateurs forward : P(fwd ≥ +50 %) et P(fwd ≥ +100 %) ; garde P(fwd ≤ −50 %).
STUDY_TAIL_UP = (0.50, 1.00)
STUDY_TAIL_DOWN = -0.50
# §6 — critères de succès (fenêtres de validation) : lift primaire et plafond garde.
CRIT_LIFT_MIN = 1.4      # lift P(fwd63 ≥ +100 %) ≥ 1.4× avec IC95 bootstrap excluant 1.0×
CRIT_GUARD_MAX = 1.5     # P(fwd63 ≤ −50 %) ≤ 1.5× le taux de base tradable
STUDY_PRIMARY_HORIZON = 63   # §1 : horizon décisif ; 21 j reporté mais non décisif


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
                    forward_days: int, as_of_offset: int = 0) -> tuple[bool, float, dict | None] | None:
    """
    Évalue un ticker à as_of = dernier jour - forward_days - as_of_offset.
    `as_of_offset` permet de balayer PLUSIEURS fenêtres passées (backtest rolling → + de données).
    Retourne (survécu, rendement_forward, signals) ou None si données insuffisantes.
    """
    if df is None or "Close" not in df:
        return None
    close = df["Close"].dropna()
    as_of_idx = len(close) - 1 - forward_days - as_of_offset
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
    return survived, fwd, signals            # signals=None si rejeté


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
    surv_pairs: list[tuple[float, dict]] = []   # (fwd, signals)

    for tk, df in prices.items():
        res = evaluate_ticker(df, bench_close, forward_days)
        if res is None:
            continue
        survived, fwd, signals = res
        all_fwd.append(fwd)
        if survived:
            survivors_fwd.append(fwd)
            surv_pairs.append((fwd, signals))

    # Rendement forward du benchmark sur le même horizon
    bench_fwd = None
    if bench_close is not None:
        bench_fwd = _forward_return(bench_close, len(bench_close) - 1 - forward_days, forward_days)

    surv = _stats(survivors_fwd)
    univ = _stats(all_fwd)
    edge = (surv["mean"] - univ["mean"]) if (surv["mean"] is not None and univ["mean"] is not None) else None

    # Comparaison des DEUX scorings sur le MÊME vivier de survivants :
    #  - continu  : percentile de facteurs continus (recommandation quant)
    #  - binaire  : ancien score « cases à cocher »
    # On regarde lequel sépare le mieux le rendement forward (quartiles croissants ?).
    fwds = [f for f, _ in surv_pairs]
    sigs = [s for _, s in surv_pairs]
    cont_q = _quartile_returns(fwds, _factor_composite(sigs, TECH_FACTORS)) if len(sigs) >= 4 else []
    bin_q = _quartile_returns(fwds, [_binary_price_score(s) for s in sigs]) if len(sigs) >= 4 else []

    result = {
        "n_tested": univ["n"], "n_survivors": surv["n"],
        "survivor": surv, "universe": univ, "benchmark_fwd": bench_fwd,
        "edge_vs_universe": edge,
        "continuous_quartiles": cont_q, "binary_quartiles": bin_q,
        "forward_days": forward_days, "seed": seed,
    }
    _print_report(result)
    return result


def _quartile_returns(fwds: list[float], scores: list) -> list[tuple[str, float | None]]:
    """Trie par score, coupe en quartiles, renvoie le rendement forward moyen de chaque."""
    pairs = sorted(zip(scores, fwds), key=lambda x: x[0])
    q = len(pairs) // 4
    out = []
    for i, label in enumerate(["Q1 (bas)", "Q2", "Q3", "Q4 (haut)"]):
        chunk = pairs[i * q:(i + 1) * q] if i < 3 else pairs[i * q:]
        vals = [f for _, f in chunk]
        out.append((label, _stats(vals)["mean"]))
    return out


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
    if r["continuous_quartiles"]:
        print("\n  Rendement forward moyen par quartile — CONTINU (percentile) :")
        for label, mean in r["continuous_quartiles"]:
            print(f"    {label:<12} {_pct(mean)}")
    if r["binary_quartiles"]:
        print("\n  Rendement forward moyen par quartile — BINAIRE (ancien) :")
        for label, mean in r["binary_quartiles"]:
            print(f"    {label:<12} {_pct(mean)}")
    print("\n  ⚠️  Biais de survie + signaux prix/volume seuls (pas de fondamentaux point-in-time).")
    print(f"{'='*60}\n")


def run_weight_sweep(n_tickers: int = 250, forward_days: int = 63, seed: int = 42,
                     period: str = "2y", offsets=(0, 30, 60, 90, 120, 150),
                     comp_weights=(3, 2, 1)) -> dict:
    """
    Backtest ROLLING : pool les survivants sur PLUSIEURS fenêtres passées (offsets) pour
    sortir du bruit, puis teste plusieurs poids de compression sur le score BINAIRE.
    Montre si baisser le poids change le classement (quartiles) ou seulement l'échelle.
    """
    prev_seed = FILTERS["shuffle_seed"]
    FILTERS["shuffle_seed"] = seed
    try:
        universe = discover_tickers()[:n_tickers]
    finally:
        FILTERS["shuffle_seed"] = prev_seed

    print(f"\n{'='*60}\n  SWEEP POIDS COMPRESSION — {len(universe)} tickers × {len(offsets)} fenêtres\n{'='*60}")
    prices = _download_prices(universe, FILTERS["rs_benchmark"], period=period)
    bench_df = prices.pop(FILTERS["rs_benchmark"], None)
    bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None

    # Pool des survivants sur toutes les fenêtres
    pool: list[tuple[float, dict]] = []
    for tk, df in prices.items():
        for off in offsets:
            res = evaluate_ticker(df, bench_close, forward_days, off)
            if res is None:
                continue
            survived, fwd, signals = res
            if survived:
                pool.append((fwd, signals))

    fwds = [f for f, _ in pool]
    sigs = [s for _, s in pool]
    n_compressed = sum(1 for s in sigs if s.get("compressed"))
    print(f"  Survivants poolés : {len(pool)}   dont 'compressed' : {n_compressed} "
          f"({100*n_compressed/max(len(sigs),1):.1f}%)")
    print(f"  Rendement forward moyen (pool) : {_pct(_stats(fwds)['mean'])}")

    orig = FILTERS["score_weights"]["compression"]
    results = {}
    try:
        for w in comp_weights:
            FILTERS["score_weights"]["compression"] = w
            scores = [_binary_price_score(s) for s in sigs]
            q = _quartile_returns(fwds, scores) if len(sigs) >= 4 else []
            spread = (q[-1][1] - q[0][1]) if q and q[-1][1] is not None and q[0][1] is not None else None
            results[w] = {"quartiles": q, "spread_Q4_Q1": spread}
            print(f"\n  compression = {w}  (séparation Q4−Q1 = {_pct(spread)})")
            for label, mean in q:
                print(f"    {label:<12} {_pct(mean)}")
    finally:
        FILTERS["score_weights"]["compression"] = orig

    print("\n  Lecture : si les quartiles/séparation bougent peu entre poids → le changement")
    print("  est surtout COSMÉTIQUE (l'ordre ne change quasi pas, seule l'échelle change).")
    print(f"{'='*60}\n")
    return results


# ===========================================================================
# STUDY (Sprint 6) — instrument de mesure : cross-section roulante + stats
# Voir docs/backtest_protocol.md (protocole pré-enregistré AVANT tout run).
# ===========================================================================

# --- Fonctions statistiques PURES (testables hors ligne) ---

def _rank_avg(xs: list[float]) -> list[float]:
    """Rangs moyens 1-based (gère les ex-æquo) — base de Spearman."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    ranks = [0.0] * len(xs)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x: list[float], y: list[float]) -> float | None:
    n = len(x)
    if n < 3:
        return None
    mx, my = sum(x) / n, sum(y) / n
    sxx = sum((a - mx) ** 2 for a in x)
    syy = sum((b - my) ** 2 for b in y)
    if sxx == 0 or syy == 0:
        return None
    sxy = sum((a - mx) * (b - my) for a, b in zip(x, y))
    return sxy / math.sqrt(sxx * syy)


def spearman_ic(scores: list[float], returns: list[float]) -> float | None:
    """IC = corrélation de rang Spearman score→rendement. None si <3 obs ou variance nulle."""
    if scores is None or returns is None or len(scores) != len(returns) or len(scores) < 3:
        return None
    return _pearson(_rank_avg(scores), _rank_avg(returns))


def mean_tstat(xs: list[float]) -> tuple[float | None, float | None, int]:
    """(moyenne, t-stat, n). t = mean / (sd/√n). t=None si n<2 ou sd=0."""
    xs = [x for x in xs if x is not None]
    n = len(xs)
    if n == 0:
        return (None, None, 0)
    m = statistics.mean(xs)
    if n < 2:
        return (m, None, n)
    sd = statistics.stdev(xs)
    if sd == 0:
        return (m, None, n)
    return (m, m / (sd / math.sqrt(n)), n)


def nonoverlapping_indices(n_dates: int, step_days: int, horizon_days: int) -> list[int]:
    """Indices d'une sous-série NON chevauchante : 1 date sur ⌈horizon/step⌉ (no offset < horizon)."""
    if step_days <= 0:
        return list(range(n_dates))
    stride = max(1, math.ceil(horizon_days / step_days))
    return list(range(0, n_dates, stride))


def decile_spread(scores: list[float], returns: list[float], k: int = 10):
    """(D1_mean, Dk_mean, Dk−D1) par rang en k paquets. (None,None,None) si < k obs."""
    if len(scores) < k or len(scores) != len(returns):
        return (None, None, None)
    pairs = sorted(zip(scores, returns), key=lambda p: p[0])
    q = len(pairs) // k
    d1 = [r for _, r in pairs[:q]]
    dk = [r for _, r in pairs[-q:]]
    m1, mk = statistics.mean(d1), statistics.mean(dk)
    return (m1, mk, mk - m1)


def bootstrap_mean_ci(xs: list[float], n_boot: int = 1000, seed: int = 0, alpha: float = 0.05):
    """IC bootstrap (percentile) de la moyenne. (None,None) si vide."""
    xs = [x for x in xs if x is not None]
    if not xs:
        return (None, None)
    rng = random.Random(seed)
    n = len(xs)
    means = sorted(sum(xs[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return (means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1])


# --- Orchestration de la study ---

def _bench_fwd_map(bench_close, dates, horizons) -> dict:
    """date → {h: rendement forward IWM} aligné sur la dernière barre ≤ date."""
    out = {}
    if bench_close is None:
        return out
    pos = {ts: i for i, ts in enumerate(bench_close.index)}
    for d in dates:
        sub = bench_close.index[bench_close.index <= d]
        if len(sub) == 0:
            continue
        i = pos[sub[-1]]
        out[d] = {h: _forward_return(bench_close, i, h) for h in horizons}
    return out


def _pool_deciles(rows: list[dict], ret_key: str) -> list[list[float]]:
    """Déciles assignés PAR DATE (par percentile du score continu), rendements poolés par décile."""
    by_date = defaultdict(list)
    for r in rows:
        by_date[r["date"]].append(r)
    buckets = [[] for _ in range(10)]
    for rs in by_date.values():
        rs2 = sorted(rs, key=lambda r: r["cont"])
        n = len(rs2)
        for i, r in enumerate(rs2):
            if r[ret_key] is not None:
                buckets[min(9, i * 10 // n)].append(r[ret_key])
    return buckets


def _study_horizon(obs: list[dict], h: int, bench_map: dict, split, step: int) -> dict:
    """Toutes les métriques pour un horizon `h` : IC (t-stat non chevauchant), déciles, coûts…"""
    cost = FILTERS["study_cost_roundtrip"]
    cap_min_dv = FILTERS["study_position_usd"] / FILTERS["study_adv_max_frac"]

    per_date = defaultdict(list)
    for o in obs:
        f = o["fwd"].get(h)
        if f is None or o["dv"] is None or o["dv"] < cap_min_dv:   # filtre capacité
            continue
        per_date[o["date"]].append(o)

    dates = sorted(per_date)
    ic_cont, ic_bin = [], []            # [(date, ic)]
    ic_factor = {name: [] for _, name, _ in TECH_FACTORS}
    d10_gt_d1 = {"calib": [0, 0], "valid": [0, 0]}   # [succès, total]
    rows = []

    for d in dates:
        group = per_date[d]
        sigs = [o["signals"] for o in group]
        rets = [o["fwd"][h] for o in group]
        bench_h = bench_map.get(d, {}).get(h)
        cont = _factor_composite(sigs, TECH_FACTORS)
        bins = [float(_binary_price_score(s)) for s in sigs]

        if len(group) >= FILTERS["study_ic_min_names"]:
            ic = spearman_ic(cont, rets)
            if ic is not None:
                ic_cont.append((d, ic))
            icb = spearman_ic(bins, rets)
            if icb is not None:
                ic_bin.append((d, icb))
            for key, name, higher in TECH_FACTORS:
                xs, ys = [], []
                for s, r in zip(sigs, rets):
                    v = s.get(key)
                    if v is not None:
                        xs.append(v if higher else -v)
                        ys.append(r)
                icf = spearman_ic(xs, ys)
                if icf is not None:
                    ic_factor[name].append(icf)

        _, _, spread = decile_spread(cont, rets, 10)
        if spread is not None:
            half = "calib" if (split is None or d <= split) else "valid"
            d10_gt_d1[half][1] += 1
            if spread > 0:
                d10_gt_d1[half][0] += 1

        for o, c, b, r in zip(group, cont, bins, rets):
            ok = r is not None and bench_h is not None
            rows.append({"date": d, "cont": c, "bin": b, "fwd": r,
                         "excess": (r - bench_h) if ok else None,
                         "net": (r - cost) if r is not None else None,
                         "net_excess": (r - cost - bench_h) if ok else None, "year": d.year,
                         "half": "calib" if (split is None or d <= split) else "valid"})

    def _ic_summary(ic_pairs, grid):
        # Mapper les IC sur la GRILLE COMPLÈTE des dates puis sélectionner des POSITIONS DE
        # GRILLE espacées de ⌈horizon/step⌉ : garantit des fenêtres NON chevauchantes même si
        # certaines dates sont absentes d'ic_pairs (dates à < study_ic_min_names survivants).
        pos = {dd: i for i, dd in enumerate(grid)}
        by_grid = [None] * len(grid)
        for dd, v in ic_pairs:
            by_grid[pos[dd]] = v
        keep = nonoverlapping_indices(len(grid), step, h)
        series = [by_grid[i] for i in keep if by_grid[i] is not None]
        m, t, n = mean_tstat(series)
        return {"mean": m, "t": t, "n": n, "ci95": bootstrap_mean_ci(series)}

    def _ic_summary_half(ic_pairs, want_calib):
        grid = [dd for dd in dates if (split is None or dd <= split) == want_calib]
        sub = [(dd, v) for dd, v in ic_pairs if (split is None or dd <= split) == want_calib]
        return _ic_summary(sub, grid)

    # Déciles poolés (net d'IWM et de coûts) + version brute
    dec_excess = [_stats(b)["mean"] for b in _pool_deciles(rows, "excess")]
    dec_net = [_stats(b)["mean"] for b in _pool_deciles(rows, "net_excess")]
    dec_net_med = [_stats(b)["median"] for b in _pool_deciles(rows, "net_excess")]

    # Meilleur facteur unique (|IC moyen|)
    factor_ic = {name: (statistics.mean(v) if v else None) for name, v in ic_factor.items()}
    best = max(((n, m) for n, m in factor_ic.items() if m is not None),
               key=lambda x: abs(x[1]), default=(None, None))

    # Baseline random : rendement net-excès moyen d'un survivant tiré au hasard vs top-décile
    net_all = [r["net_excess"] for r in rows if r["net_excess"] is not None]
    top_dec = _pool_deciles(rows, "net_excess")[9]

    # Par année (net-excès)
    by_year = defaultdict(list)
    for r in rows:
        if r["net_excess"] is not None:
            by_year[r["year"]].append(r["net_excess"])

    def _half_topdec(half):
        rr = [r for r in rows if r["half"] == half]
        return _pool_deciles(rr, "net_excess")[9] if rr else []

    return {
        "horizon": h, "n_obs": len(rows), "n_dates": len(dates),
        "ic_continuous": _ic_summary(ic_cont, dates),
        "ic_binary": _ic_summary(ic_bin, dates),
        "ic_cont_calib": _ic_summary_half(ic_cont, True),
        "ic_cont_valid": _ic_summary_half(ic_cont, False),
        "best_single_factor": {"name": best[0], "mean_ic": best[1]},
        "factor_ic": factor_ic,
        "decile_excess": dec_excess, "decile_net_excess": dec_net, "decile_net_median": dec_net_med,
        "decile_spread_net": (dec_net[9] - dec_net[0]) if dec_net[0] is not None and dec_net[9] is not None else None,
        "d10_gt_d1_calib": d10_gt_d1["calib"], "d10_gt_d1_valid": d10_gt_d1["valid"],
        "random_net_excess_mean": _stats(net_all)["mean"],
        "topdecile_net_excess_mean": _stats(top_dec)["mean"],
        "topdecile_net_excess_valid": _stats(_half_topdec("valid"))["mean"],
        "by_year": {y: _stats(v) for y, v in sorted(by_year.items())},
    }


def run_study(n_tickers: int | None = None, period: str = "3y", seed: int = 42) -> dict:
    """
    Cross-section ROULANTE sur tout l'univers : à chaque date as-of mensuelle, rejoue
    analyze_prices, mesure IC score→rendement + déciles excès-IWM, coûts, split calib/valid.
    Voir docs/backtest_protocol.md. La study MESURE — elle n'ajuste aucun poids (Sprint 8).
    """
    step = FILTERS["study_step_days"]
    horizons = list(FILTERS["study_horizons"])
    hmax = max(horizons)
    min_hist = FILTERS["vol_window_long"] + FILTERS["ma_slope_lookback"]

    prev = FILTERS["shuffle_seed"]
    FILTERS["shuffle_seed"] = seed
    try:
        universe = discover_tickers()
    finally:
        FILTERS["shuffle_seed"] = prev
    if n_tickers:
        universe = universe[:n_tickers]

    print(f"\n{'='*64}\n  STUDY — {len(universe)} tickers · {period} · pas {step}j · horizons {horizons}"
          f"\n  sensors_version={FILTERS['sensors_version']}  (voir docs/backtest_protocol.md)\n{'='*64}")
    prices = _download_prices(universe, FILTERS["rs_benchmark"], period=period)
    bench_df = prices.pop(FILTERS["rs_benchmark"], None)
    bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None

    maxlen = max((len(df["Close"].dropna()) for df in prices.values() if "Close" in df), default=0)
    offsets = list(range(0, max(maxlen - 1 - hmax - min_hist, 0) + 1, step))

    obs = []
    for tk, df in prices.items():
        if "Close" not in df:
            continue
        close = df["Close"].dropna()
        for off in offsets:
            as_of_idx = len(close) - 1 - hmax - off
            if as_of_idx < min_hist:
                continue
            as_of_date = close.index[as_of_idx]
            df_tr = df.loc[df.index <= as_of_date]
            bench_tr = bench_close[bench_close.index <= as_of_date] if bench_close is not None else None
            signals, _ = analyze_prices(tk, df_tr, bench_tr)
            if signals is None:
                continue
            obs.append({"date": as_of_date, "ticker": tk, "signals": signals,
                        "fwd": {h: _forward_return(close, as_of_idx, h) for h in horizons},
                        "dv": signals.get("dollar_volume")})

    result = {"n_obs": len(obs), "n_tickers": len(prices), "period": period, "seed": seed,
              "horizons": horizons, "sensors_version": FILTERS["sensors_version"], "by_horizon": {}}
    if not obs:
        print("  Aucune observation (univers/horizon trop courts).")
        return result

    all_dates = sorted({o["date"] for o in obs})
    split = all_dates[len(all_dates) // 2] if all_dates else None
    result["split_date"] = str(split.date()) if split is not None else None
    bench_map = _bench_fwd_map(bench_close, all_dates, horizons)
    for h in horizons:
        result["by_horizon"][h] = _study_horizon(obs, h, bench_map, split, step)

    _print_study(result)
    return result


def _print_study(r: dict) -> None:
    print(f"\n{'='*64}\n  STUDY — RÉSULTATS ({r['n_obs']} observations, {r['n_tickers']} tickers,"
          f" capteurs {r['sensors_version']})")
    print(f"  Split calibration/validation à : {r.get('split_date')}\n{'='*64}")
    for h in r["horizons"]:
        s = r["by_horizon"][h]
        ic, icb = s["ic_continuous"], s["ic_binary"]
        icv = s["ic_cont_valid"]
        print(f"\n  ─── Horizon {h}j  ({s['n_obs']} obs, {s['n_dates']} dates) ───")
        print(f"    IC continu   : moyenne {_pct(ic['mean'])}  t={_fmt(ic['t'])}  n={ic['n']}  "
              f"IC95 [{_pct(ic['ci95'][0])},{_pct(ic['ci95'][1])}]  (non chevauchant)")
        print(f"    IC binaire   : moyenne {_pct(icb['mean'])}  t={_fmt(icb['t'])}  n={icb['n']}")
        bf = s["best_single_factor"]
        print(f"    Meilleur facteur unique : {bf['name']}  IC {_pct(bf['mean_ic'])}   "
              f"(composite {'>' if (ic['mean'] or 0) > (bf['mean_ic'] or 0) else '≤'} meilleur facteur)")
        print(f"    Random (survivant moyen) net-excès {_pct(s['random_net_excess_mean'])}  "
              f"vs top-décile {_pct(s['topdecile_net_excess_mean'])}")
        print(f"\n    Déciles (rendement moyen, net de coûts, EXCÈS d'IWM) :")
        for i, (e, ne, nm) in enumerate(zip(s["decile_excess"], s["decile_net_excess"], s["decile_net_median"]), 1):
            print(f"      D{i:<2} excès {_pct(e)}   net-excès moy {_pct(ne)}  méd {_pct(nm)}")
        print(f"    Spread D10−D1 (net-excès) : {_pct(s['decile_spread_net'])}")
        cc, cv = s["d10_gt_d1_calib"], s["d10_gt_d1_valid"]
        print(f"    D10>D1 — calib {cc[0]}/{cc[1]} ({_frac(cc)})   valid {cv[0]}/{cv[1]} ({_frac(cv)})")
        print(f"    Validation (2e moitié) : IC {_pct(icv['mean'])} t={_fmt(icv['t'])}  "
              f"top-décile net-excès {_pct(s['topdecile_net_excess_valid'])}")
        print(f"    Par année (net-excès moyen) :")
        for y, st in s["by_year"].items():
            print(f"      {y} : moy {_pct(st['mean'])}  méd {_pct(st['median'])}  n={st['n']}")
    print(f"\n  ⚠️  BIAIS DE SURVIE : univers = titres cotés AUJOURD'HUI (délistés absents) →")
    print(f"      les edges affichés sont une BORNE SUPÉRIEURE. Signaux PRIX/VOLUME uniquement ;")
    print(f"      l'insider EDGAR daté n'est PAS inclus dans cette study (extension future).")
    print(f"      Voir docs/backtest_protocol.md.")
    print(f"{'='*64}\n")


def _fmt(x):
    return " n/a" if x is None else f"{x:+.2f}"


def _frac(pair):
    return "n/a" if pair[1] == 0 else f"{100*pair[0]/pair[1]:.0f}%"


# ===========================================================================
# STUDY v2 (Sprint 5) — chasse à la queue : lift des profils Fusée/Phénix vs base
# tradable, garde de queue gauche, espérance nette, taux de délisting break-even,
# verdict PASS/FAIL/CONDITIONAL contre le protocole v2 §6. Voir backtest_protocol_v2.md.
#
# Réutilise SANS duplication les détecteurs de production (profiles.detect_profiles)
# et le pool tradable (screener_backend.analyze_prices en mode "tradability"). Aucune
# définition d'appartenance n'est réécrite ici — c'est un bloqueur de revue (§3).
# ===========================================================================

# --- Fonctions statistiques PURES (testables hors ligne, valeurs à la main) ---

def tail_frac(returns: list[float], threshold: float, upper: bool = True) -> float | None:
    """
    Fraction des rendements (None ignorés) franchissant `threshold` : queue DROITE
    `r ≥ threshold` si upper, queue GAUCHE `r ≤ threshold` sinon. None si population vide.
    """
    xs = [r for r in returns if r is not None]
    if not xs:
        return None
    hits = sum(1 for r in xs if (r >= threshold if upper else r <= threshold))
    return hits / len(xs)


def lift(p_member: float | None, p_base: float | None) -> float | None:
    """Lift = P(membre) / P(base). None si l'un est None ou si la base est nulle."""
    if p_member is None or p_base is None or p_base == 0:
        return None
    return p_member / p_base


def bootstrap_lift_ci(member_returns: list[float], p_base: float | None, threshold: float,
                      n_boot: int = 1000, seed: int = 0, alpha: float = 0.05,
                      upper: bool = True) -> tuple[float | None, float | None]:
    """
    IC bootstrap (percentile) du LIFT de queue vs une base de taux FIXE `p_base` : à chaque
    tirage on rééchantillonne les rendements membres (n avec remise), on recalcule la
    fréquence de queue, divisée par `p_base`. La base = tout l'univers tradable (n immense,
    variance négligeable) → l'incertitude dominante est celle du petit échantillon membre.
    (None, None) si base nulle/None ou aucun membre.
    """
    xs = [r for r in member_returns if r is not None]
    if not xs or p_base is None or p_base == 0:
        return (None, None)
    rng = random.Random(seed)
    n = len(xs)
    ratios = []
    for _ in range(n_boot):
        hits = 0
        for _ in range(n):
            r = xs[rng.randrange(n)]
            if (r >= threshold if upper else r <= threshold):
                hits += 1
        ratios.append((hits / n) / p_base)
    ratios.sort()
    return (ratios[int(alpha / 2 * n_boot)], ratios[int((1 - alpha / 2) * n_boot) - 1])


def break_even_delisting_rate(lift_value: float | None) -> float | None:
    """
    Protocole §5 : fraction des membres (population VRAIE, délisting inclus) qui devraient
    être des −100 % cachés pour EFFACER le lift mesuré. Démonstration : membres observés n,
    k succès de queue (p̂ = k/n) ; d membres cachés tout-perdants portent p à k/(n+d).
    Lift effacé quand k/(n+d) = base ⇒ fraction cachée d/(n+d) = 1 − base/p̂ = 1 − 1/lift.
    Ne dépend que du lift. None si lift ≤ 1 (aucun lift à effacer).
    """
    if lift_value is None or lift_value <= 1.0:
        return None
    return 1.0 - 1.0 / lift_value


def net_expectancy(returns: list[float], cost: float) -> float | None:
    """Espérance nette moyenne par ticket = moyenne(rendement − coût). None si vide."""
    xs = [r for r in returns if r is not None]
    if not xs:
        return None
    return statistics.mean(xs) - cost


def study_verdict(profile: str, lift100: float | None, ci_low100: float | None,
                  net_exp: float | None, guard_ok: bool) -> str:
    """
    Verdict §6 (fenêtre de validation) à partir des trois critères pré-enregistrés :
    (1) lift P(fwd63≥+100%) ≥ 1.4× ET IC95 bas > 1.0× ; (2) espérance nette > 0 ;
    (3) garde de queue gauche ≤ 1.5× base. Phénix qui passe → CONDITIONAL (money-gated,
    délisting à confirmer) ; Fusée qui passe → PASS (provisoire tant que Validation B manque).
    """
    crit1 = (lift100 is not None and lift100 >= CRIT_LIFT_MIN
             and ci_low100 is not None and ci_low100 > 1.0)
    crit2 = net_exp is not None and net_exp > 0
    if not (crit1 and crit2 and guard_ok):
        return "FAIL"
    return "CONDITIONAL" if profile == "phenix" else "PASS"


# --- Orchestration de la study v2 ---

def _window_of(date) -> str | None:
    """Range une date as-of dans sa fenêtre de protocole (validation_a / exploration / None)."""
    ds = str(date.date())
    if VALIDATION_A_WINDOW[0] <= ds <= VALIDATION_A_WINDOW[1]:
        return "validation_a"
    if EXPLORATION_WINDOW[0] <= ds <= EXPLORATION_WINDOW[1]:
        return "exploration"
    return None


def _profile_metrics(profile: str, member_rows: list[dict], base_rows: list[dict],
                     h: int, seed: int) -> dict:
    """
    Toutes les métriques §1/§5/§6 d'un profil sur une fenêtre, horizon `h` : lifts de queue
    +50%/+100% (IC95 bootstrap), garde queue gauche, espérance nette, break-even délisting,
    et verdict. Base et membres déjà filtrés capacité en amont. `member_rows ⊆ base_rows`.
    """
    m_ret = [r["fwd"].get(h) for r in member_rows]
    b_ret = [r["fwd"].get(h) for r in base_rows]
    cost = FILTERS["study_cost_roundtrip"]
    up1, up2 = STUDY_TAIL_UP

    p_b_up1, p_b_up2 = tail_frac(b_ret, up1), tail_frac(b_ret, up2)
    lift1 = lift(tail_frac(m_ret, up1), p_b_up1)
    lift2 = lift(tail_frac(m_ret, up2), p_b_up2)
    ci1 = bootstrap_lift_ci(m_ret, p_b_up1, up1, seed=seed)
    ci2 = bootstrap_lift_ci(m_ret, p_b_up2, up2, seed=seed + 1)

    # Garde de queue gauche : base nulle → garde OK ssi les membres n'ont aucun −50 %.
    p_m_dn = tail_frac(m_ret, STUDY_TAIL_DOWN, upper=False)
    p_b_dn = tail_frac(b_ret, STUDY_TAIL_DOWN, upper=False)
    if p_b_dn in (None, 0):
        guard_lift, guard_ok = None, (not p_m_dn)
    else:
        guard_lift = (p_m_dn or 0.0) / p_b_dn
        guard_ok = guard_lift <= CRIT_GUARD_MAX

    net_exp = net_expectancy(m_ret, cost)      # §1 espérance nette (horizon décisif = 63)
    verdict = (study_verdict(profile, lift2, ci2[0], net_exp, guard_ok)
               if h == STUDY_PRIMARY_HORIZON else None)
    return {
        "profile": profile, "horizon": h,
        "n_member": sum(1 for r in m_ret if r is not None),
        "n_base": sum(1 for r in b_ret if r is not None),
        "lift_up50": lift1, "lift_up50_ci": ci1,
        "lift_up100": lift2, "lift_up100_ci": ci2,
        "guard_left_lift": guard_lift, "guard_ok": guard_ok,
        "net_expectancy": net_exp,
        "break_even_delisting": break_even_delisting_rate(lift2),
        "verdict": verdict,
    }


def _study_v2_window(name: str, rows: list[dict], horizons: list[int], seed: int) -> dict:
    """Métriques par profil (fusee / fusee_event / phenix) pour une fenêtre, tous horizons."""
    cap_min_dv = FILTERS["study_position_usd"] / FILTERS["study_adv_max_frac"]   # filtre capacité §7
    base = [r for r in rows if r["dv"] is not None and r["dv"] >= cap_min_dv]
    profiles_out = {}
    for prof, key in (("fusee", "is_fusee"), ("fusee_event", "fusee_event"), ("phenix", "is_phenix")):
        members = [r for r in base if r.get(key)]
        profiles_out[prof] = {h: _profile_metrics(prof, members, base, h, seed) for h in horizons}
    return {"window": name, "n_base": len(base), "profiles": profiles_out}


def run_study_v2(n_tickers: int | None = None, period: str = "5y", seed: int = 42) -> dict:
    """
    Study v2 (chasse à la queue) : cross-section roulante mensuelle sur l'univers TRADABLE.
    À chaque date as-of on rejoue analyze_prices (pool tradability), on étiquette les profils
    via detect_profiles (percentiles cross-sectionnels de la date), puis on mesure les queues
    forward par profil × fenêtre. Validation A jugée UNE fois contre §6. Voir §1-§8.
    """
    step = FILTERS["study_step_days"]
    horizons = list(FILTERS["study_horizons"])
    hmax = max(horizons)
    min_hist = FILTERS["vol_window_long"] + FILTERS["ma_slope_lookback"]

    # pool_mode doit rester "tradability" pendant TOUT le run (discover + download + analyze) ;
    # try/finally EXTERNE → restauré sur tous les chemins, y compris si discover_tickers lève.
    prev_pool, prev_seed = FILTERS["pool_mode"], FILTERS["shuffle_seed"]
    FILTERS["pool_mode"] = "tradability"        # la study v2 vit sur le pool tradable (§2)
    try:
        FILTERS["shuffle_seed"] = seed
        try:
            universe = discover_tickers()
        finally:
            FILTERS["shuffle_seed"] = prev_seed
        if n_tickers:
            universe = universe[:n_tickers]

        print(f"\n{'='*64}\n  STUDY v2 (tail hunting) — {len(universe)} tickers · {period} · pas {step}j"
              f" · horizons {horizons}\n  profils via profiles.detect_profiles (§3)"
              f"  ·  voir docs/backtest_protocol_v2.md\n{'='*64}")
        prices = _download_prices(universe, FILTERS["rs_benchmark"], period=period)
        bench_df = prices.pop(FILTERS["rs_benchmark"], None)
        bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None

        # Calendrier maître = index du benchmark (le plus complet des séries liquides).
        cal = bench_close.index if bench_close is not None else _union_calendar(prices)
        grid = [cal[i] for i in range(min_hist, max(len(cal) - hmax, min_hist), step)]

        rows: list[dict] = []
        for d in grid:
            win = _window_of(d)
            if win is None:
                continue
            bench_tr = bench_close[bench_close.index <= d] if bench_close is not None else None
            at_date: list[dict] = []                      # signaux tradables de la cross-section à d
            for tk, df in prices.items():
                if "Close" not in df:
                    continue
                close = df["Close"].dropna()
                sub = close.index[close.index <= d]
                if len(sub) < min_hist:
                    continue
                as_of_idx = len(sub) - 1
                fwd = {h: _forward_return(close, as_of_idx, h) for h in horizons}
                if all(v is None for v in fwd.values()):
                    continue                              # aucune donnée forward → inutile
                signals, _ = analyze_prices(tk, df.loc[df.index <= d], bench_tr)
                if signals is None:                       # non tradable (prix/liquidité/histo)
                    continue
                at_date.append({"signals": signals, "fwd": fwd,
                                "dv": signals.get("dollar_volume")})
            if not at_date:
                continue
            detect_profiles([o["signals"] for o in at_date])   # percentiles de LA date (§3)
            for o in at_date:
                s = o["signals"]
                rows.append({"date": d, "window": win, "fwd": o["fwd"], "dv": o["dv"],
                             "is_fusee": s.get("is_fusee"), "fusee_event": s.get("fusee_event"),
                             "is_phenix": s.get("is_phenix")})
    finally:
        FILTERS["pool_mode"] = prev_pool

    by_window = {}
    for name in ("validation_a", "exploration"):
        wr = [r for r in rows if r["window"] == name]
        by_window[name] = _study_v2_window(name, wr, horizons, seed)

    result = {"n_obs": len(rows), "n_tickers": len(universe), "period": period, "seed": seed,
              "horizons": horizons, "primary_horizon": STUDY_PRIMARY_HORIZON,
              "windows": {"validation_a": VALIDATION_A_WINDOW, "exploration": EXPLORATION_WINDOW},
              "by_window": by_window}
    _print_study_v2(result)
    return result


def _union_calendar(prices: dict) -> pd.DatetimeIndex:
    """Calendrier de repli (union triée des dates) si le benchmark manque."""
    idx = pd.DatetimeIndex([])
    for df in prices.values():
        if "Close" in df:
            idx = idx.union(df["Close"].dropna().index)
    return idx


def _lift(x):
    return "  n/a" if x is None else f"{x:4.2f}×"


def _print_study_v2(r: dict) -> None:
    print(f"\n{'='*64}\n  STUDY v2 — RÉSULTATS ({r['n_obs']} obs profil×date, {r['n_tickers']} tickers,"
          f" {r['period']})\n  horizon décisif = {r['primary_horizon']}j  ·  seuils +50%/+100% (§1)"
          f"\n{'='*64}")
    for name in ("validation_a", "exploration"):
        w = r["by_window"][name]
        lo, hi = r["windows"][name]
        tag = "JUGÉE UNE FOIS (out-of-sample)" if name == "validation_a" else "IN-SAMPLE, DÉPENSÉE — contexte seulement"
        print(f"\n  ═══ Fenêtre {name}  [{lo} → {hi}]  ({w['n_base']} obs base) — {tag} ═══")
        if w["n_base"] == 0:
            print("    (aucune observation dans cette fenêtre — période téléchargée trop courte)")
            continue
        for prof in ("fusee", "fusee_event", "phenix"):
            print(f"\n    ── {prof} ──")
            for h in r["horizons"]:
                m = w["profiles"][prof][h]
                primary = " ◀ décisif" if h == r["primary_horizon"] else ""
                c1lo, c1hi = m["lift_up50_ci"]
                c2lo, c2hi = m["lift_up100_ci"]
                print(f"      h={h:<2}  n_membre={m['n_member']:<4} / base {m['n_base']}{primary}")
                print(f"         lift +50%  {_lift(m['lift_up50'])}  IC95[{_lift(c1lo)},{_lift(c1hi)}]"
                      f"   lift +100% {_lift(m['lift_up100'])}  IC95[{_lift(c2lo)},{_lift(c2hi)}]")
                print(f"         garde ≤−50% {_lift(m['guard_left_lift'])} ({'OK' if m['guard_ok'] else 'DÉPASSE'})"
                      f"   espérance nette {_pct(m['net_expectancy'])}"
                      f"   break-even délisting {_hit(m['break_even_delisting'])}")
                if m["verdict"] is not None:
                    fragile = (m["break_even_delisting"] is not None and m["break_even_delisting"] < 0.05)
                    frag = "  ⚠️ FRAGILE (break-even <5%)" if fragile else ""
                    print(f"         VERDICT §6 : {m['verdict']}{frag}")
    print(f"\n  Règle §6 : Fusée PASS(A) = provisoire tant que Validation B (tracker) n'a pas confirmé ;")
    print(f"  Phénix ne peut être que CONDITIONAL (money-gated, données délisting à acheter — §5).")
    print(f"  ⚠️  BIAIS DE SURVIE : univers = titres cotés AUJOURD'HUI ; le break-even délisting")
    print(f"      chiffre la fragilité de chaque lift. Validation A jugée UNE fois — aucun re-fit.")
    print(f"{'='*64}\n")


# ===========================================================================
# STUDY v3 (Epic 3 S5) — score conditionné à la survie : purged walk-forward,
# lift du décile haut de P(+100 %), VALUE-OF-SURVIVAL (le veto améliore-t-il ?),
# garde queue gauche, par régime. Réutilise scoring.assemble_matrix (features
# gelées §3) + model.ScoreModel — zéro définition dupliquée.
#
# Constantes FIGÉES au protocole v3 §4/§7 (hors FILTERS). JAMAIS jugé avant le
# sign-off du protocole (§0) : --study-v3 imprime NON-BINDING tant qu'il n'est pas signé.
# ===========================================================================
STUDY_V3_K = 5                             # purged k-fold
STUDY_V3_EMBARGO = 73                       # jours de bourse (horizon 63 + buffer 10) — purge la fuite
STUDY_V3_LAM_GRID = (0.03, 0.1, 0.3, 1.0)   # grille §4 (choix par CV interne)
STUDY_V3_DECILE = 0.90                       # top décile de p_hat jugé
CRIT_V3_LIFT_MIN = 1.4                       # §7 (1)
CRIT_V3_GUARD_MAX = 1.5                      # §7 (3)
N_TECH_FEATURES = 6                          # 6 premières features = techniques ; le reste = survie


def purged_fold_masks(pos, k: int, embargo: int) -> list[tuple[np.ndarray, np.ndarray]]:
    """
    CV purgée temporelle (López de Prado). `pos` = position de chaque obs dans le calendrier
    maître (jours de bourse). Découpe les DATES uniques en `k` blocs contigus ; pour chaque bloc
    = test, l'entraînement exclut toute obs à moins de `embargo` positions du bloc (purge la
    fuite de label des DEUX côtés). Retourne [(train_idx, test_idx)].
    """
    pos = np.asarray(pos)
    uniq = np.unique(pos)
    k = max(1, min(k, len(uniq)))
    out = []
    for blk in np.array_split(uniq, k):
        lo, hi = int(blk.min()), int(blk.max())
        test = np.where((pos >= lo) & (pos <= hi))[0]
        train = np.where((pos < lo - embargo) | (pos > hi + embargo))[0]
        out.append((train, test))
    return out


def _select_lam(X, y, pos, grid) -> float:
    """Choix de lambda par UN split temporel interne (derniers ~20 % des dates = validation)."""
    uniq = np.unique(pos)
    if len(uniq) < 3:
        return grid[-1]
    cut = uniq[int(len(uniq) * 0.8)]
    tr, va = pos < cut, pos >= cut
    if tr.sum() == 0 or va.sum() == 0 or len(np.unique(y[tr])) < 2:
        return grid[-1]
    best, best_ll = grid[-1], float("inf")
    for lam in grid:
        m = ScoreModel([f"f{i}" for i in range(X.shape[1])], lam=lam).fit(X[tr], y[tr])
        p = np.clip(m.predict_proba(X[va]), 1e-6, 1 - 1e-6)
        ll = -np.mean(y[va] * np.log(p) + (1 - y[va]) * np.log(1 - p))
        if ll < best_ll:
            best_ll, best = ll, lam
    return best


def oof_predictions(X, y, pos, folds, grid=STUDY_V3_LAM_GRID) -> np.ndarray:
    """Prédictions OUT-OF-FOLD : chaque bloc test prédit par un modèle entraîné hors de lui
    (lambda choisi en CV interne). NaN si un fold n'a pas de quoi entraîner (une seule classe)."""
    X = np.asarray(X, float); y = np.asarray(y, float); pos = np.asarray(pos)
    names = [f"f{i}" for i in range(X.shape[1])]
    oof = np.full(len(y), np.nan)
    for tr, te in folds:
        if len(tr) < 20 or len(np.unique(y[tr])) < 2:
            continue
        lam = _select_lam(X[tr], y[tr], pos[tr], grid)
        m = ScoreModel(names, lam=lam).fit(X[tr], y[tr])
        oof[te] = m.predict_proba(X[te])
    return oof


def _ne_top(p, fwd, cost: float, q: float = STUDY_V3_DECILE) -> float | None:
    """Espérance nette du top décile de `p` (obs valides seulement)."""
    p = np.asarray(p, float); fwd = np.asarray(fwd, float)
    ok = ~np.isnan(p) & ~np.isnan(fwd)
    if ok.sum() < 20:
        return None
    p, fwd = p[ok], fwd[ok]
    thr = np.quantile(p, q)
    top = fwd[p >= thr]
    return float(top.mean() - cost) if len(top) else None


def decile_metrics(oof, fwd, cost: float, seed: int = 0) -> dict | None:
    """Métriques §7 du décile haut de `oof` : lift +100 %, IC, garde queue gauche, espérance, break-even."""
    oof = np.asarray(oof, float); fwd = np.asarray(fwd, float)
    ok = ~np.isnan(oof) & ~np.isnan(fwd)
    if ok.sum() < 20:
        return None
    p, f = oof[ok], fwd[ok]
    thr = np.quantile(p, STUDY_V3_DECILE)
    top = f[p >= thr].tolist()
    base = f.tolist()
    up = STUDY_TAIL_UP[1]
    p_base_up = tail_frac(base, up)
    lift100 = lift(tail_frac(top, up), p_base_up)
    ci = bootstrap_lift_ci(top, p_base_up, up, seed=seed)
    p_base_dn = tail_frac(base, STUDY_TAIL_DOWN, upper=False)
    p_top_dn = tail_frac(top, STUDY_TAIL_DOWN, upper=False)
    guard = None if p_base_dn in (None, 0) else (p_top_dn or 0.0) / p_base_dn
    return {
        "n_top": len(top), "n_base": len(base),
        "lift100": lift100, "lift100_ci": ci,
        "net_expectancy": net_expectancy(top, cost),
        "guard_left": guard, "guard_ok": (guard is not None and guard <= CRIT_V3_GUARD_MAX),
        "break_even_delisting": break_even_delisting_rate(lift100),
    }


def value_of_survival(X, y, pos, fwd, folds, cost: float) -> dict:
    """
    Critère §7 (2) — le veto survie AJOUTE-t-il de la valeur ? Compare l'espérance nette du top
    décile du modèle COMPLET vs le modèle SANS features de survie (les 6 techniques seules), sur
    les prédictions out-of-fold, globalement ET par fold (≥ 4/5 folds meilleurs requis).
    """
    X = np.asarray(X, float)
    oof_full = oof_predictions(X, y, pos, folds)
    oof_tech = oof_predictions(X[:, :N_TECH_FEATURES], y, pos, folds)
    fwd = np.asarray(fwd, float)
    ne_full = _ne_top(oof_full, fwd, cost)
    ne_tech = _ne_top(oof_tech, fwd, cost)
    better = 0
    n_folds = 0
    for _, te in folds:
        ff = _ne_top(oof_full[te], fwd[te], cost)
        ft = _ne_top(oof_tech[te], fwd[te], cost)
        if ff is None or ft is None:
            continue
        n_folds += 1
        if ff > ft:
            better += 1
    return {
        "ne_full": ne_full, "ne_tech": ne_tech,
        "delta": (None if ne_full is None or ne_tech is None else ne_full - ne_tech),
        "folds_better": better, "n_folds": n_folds,
        "adds_value": (ne_full is not None and ne_tech is not None
                       and ne_full > ne_tech and n_folds > 0 and better >= n_folds - 1),
        "oof_full": oof_full,
    }


def _regime_label(bench_close, date) -> str:
    """Régime de marché à `date` = signe du rendement IWM sur ~63 j de bourse glissants."""
    if bench_close is None:
        return "all"
    sub = bench_close[bench_close.index <= date]
    if len(sub) < STUDY_PRIMARY_HORIZON + 1:
        return "all"
    r = float(sub.iloc[-1] / sub.iloc[-(STUDY_PRIMARY_HORIZON + 1)] - 1)
    return "bull" if r >= 0 else "bear"


def run_study_v3(n_tickers: int | None = None, period: str = "5y", seed: int = 42,
                 signed_off: bool = False) -> dict:
    """
    Study v3 (protocole v3) : cross-section roulante sur l'univers tradable ; à chaque date on
    rejoue analyze_prices + fusionne les signaux de survie EDGAR point-in-time, on assemble les
    features gelées (scoring §3), on labellise y = 1 si fwd63 ≥ +100 %, puis PURGED WALK-FORWARD
    (k-fold + embargo) → prédictions out-of-fold → métriques §7 + value-of-survival + par régime.

    `signed_off=False` → run NON-BINDING (plomberie / dry-run) : le protocole §0 interdit tout
    jugement avant sign-off humain. Le verdict n'est écrit au run-log que sur un run signé.
    """
    from scoring import assemble_matrix
    import edgar

    step = FILTERS["study_step_days"]
    hmax = STUDY_PRIMARY_HORIZON
    min_hist = FILTERS["vol_window_long"] + FILTERS["ma_slope_lookback"]
    cost = FILTERS["study_cost_roundtrip"]

    prev_pool, prev_seed = FILTERS["pool_mode"], FILTERS["shuffle_seed"]
    FILTERS["pool_mode"] = "tradability"
    try:
        FILTERS["shuffle_seed"] = seed
        try:
            universe = discover_tickers()
        finally:
            FILTERS["shuffle_seed"] = prev_seed
        if n_tickers:
            universe = universe[:n_tickers]

        tag = "SIGNÉ (jugé)" if signed_off else "DRY-RUN / NON-BINDING (protocole non signé §0)"
        print(f"\n{'='*66}\n  STUDY v3 (survival-conditioned) — {len(universe)} tickers · {period}"
              f" · pas {step}j\n  purged {STUDY_V3_K}-fold, embargo {STUDY_V3_EMBARGO}j · "
              f"features scoring.§3\n  {tag}  ·  docs/backtest_protocol_v3.md\n{'='*66}")

        prices = _download_prices(universe, FILTERS["rs_benchmark"], period=period)
        bench_df = prices.pop(FILTERS["rs_benchmark"], None)
        bench_close = bench_df["Close"].dropna() if bench_df is not None and "Close" in bench_df else None
        cal = bench_close.index if bench_close is not None else _union_calendar(prices)
        grid = [cal[i] for i in range(min_hist, max(len(cal) - hmax, min_hist), step)]

        Xrows, ys, poss, fwds, dvs, regimes, phenix = [], [], [], [], [], [], []
        for d in grid:
            bench_tr = bench_close[bench_close.index <= d] if bench_close is not None else None
            reg = _regime_label(bench_close, d)
            at_date = []
            for tk, df in prices.items():
                if "Close" not in df:
                    continue
                close = df["Close"].dropna()
                sub = close.index[close.index <= d]
                if len(sub) < min_hist:
                    continue
                fwd63 = _forward_return(close, len(sub) - 1, hmax)
                if fwd63 is None:
                    continue                       # pas de forward → inutilisable (labellisation)
                signals, _ = analyze_prices(tk, df.loc[df.index <= d], bench_tr)
                if signals is None:
                    continue
                surv = edgar.survival_signals(tk, now=d.to_pydatetime())  # point-in-time
                if surv:
                    signals.update(surv)
                at_date.append({"sig": signals, "fwd63": fwd63, "dv": signals.get("dollar_volume")})
            if not at_date:
                continue
            detect_profiles([o["sig"] for o in at_date])          # baseline v2 (Phénix)
            Xd = assemble_matrix([o["sig"] for o in at_date])      # features gelées §3
            pos = int(cal.get_loc(d))
            for o, xr in zip(at_date, Xd):
                Xrows.append(xr)
                ys.append(1.0 if o["fwd63"] >= STUDY_TAIL_UP[1] else 0.0)
                poss.append(pos)
                fwds.append(o["fwd63"])
                dvs.append(o["dv"])
                regimes.append(reg)
                phenix.append(bool(o["sig"].get("is_phenix")))
    finally:
        FILTERS["pool_mode"] = prev_pool

    X = np.array(Xrows, float) if Xrows else np.zeros((0, len(FEATURE_NAMES)))
    y = np.array(ys, float)
    pos = np.array(poss)
    fwd = np.array(fwds, float)
    dv = np.array(dvs, float)

    # Filtre capacité §7 (position ≤ 1 % du dollar-volume) appliqué avant jugement.
    cap_min_dv = FILTERS["study_position_usd"] / FILTERS["study_adv_max_frac"]
    keep = dv >= cap_min_dv
    X, y, pos, fwd = X[keep], y[keep], pos[keep], fwd[keep]
    regimes = [r for r, k in zip(regimes, keep) if k]
    phenix = [p for p, k in zip(phenix, keep) if k]

    result = {"n_obs": int(len(y)), "n_tickers": len(universe), "period": period,
              "signed_off": signed_off, "base_rate_up100": tail_frac(fwd.tolist(), STUDY_TAIL_UP[1])}
    if len(y) >= STUDY_V3_K * 20 and len(np.unique(y)) == 2:
        folds = purged_fold_masks(pos, STUDY_V3_K, STUDY_V3_EMBARGO)
        vos = value_of_survival(X, y, pos, fwd, folds, cost)
        overall = decile_metrics(vos["oof_full"], fwd, cost, seed=seed)
        by_regime = {}
        for rg in ("bull", "bear"):
            idx = np.array([i for i, r in enumerate(regimes) if r == rg])
            if len(idx):
                by_regime[rg] = decile_metrics(vos["oof_full"][idx], fwd[idx], cost, seed=seed)
        # baseline : meilleure feature seule (espérance nette top décile) + Phénix v2 brut
        best_feat = None
        for j in range(X.shape[1]):
            ne = _ne_top(X[:, j], fwd, cost)
            if ne is not None and (best_feat is None or ne > best_feat[1]):
                best_feat = (j, ne)
        ph_idx = np.array([i for i, p in enumerate(phenix) if p])
        ne_phenix = net_expectancy(fwd[ph_idx].tolist(), cost) if len(ph_idx) else None
        vos.pop("oof_full", None)
        result.update({
            "overall": overall, "by_regime": by_regime, "value_of_survival": vos,
            "baseline_best_feature": (None if best_feat is None else
                                      {"feature": FEATURE_NAMES[best_feat[0]], "net_expectancy": best_feat[1]}),
            "baseline_phenix_ne": ne_phenix,
        })
    else:
        result["note"] = "trop peu d'observations ou une seule classe — plomberie seulement"
    _print_study_v3(result)
    return result


def _print_study_v3(r: dict) -> None:
    print(f"\n{'='*66}\n  STUDY v3 — {r['n_obs']} obs · base P(+100%)={_fmt(r.get('base_rate_up100'))}"
          f"\n{'='*66}")
    if "overall" not in r:
        print(f"  {r.get('note', 'aucune métrique')}")
        print(f"{'='*66}\n")
        return
    o = r["overall"] or {}
    v = r["value_of_survival"]
    print(f"  DÉCILE HAUT p_hat (fwd63) : lift +100% = {_fmt(o.get('lift100'))}× "
          f"(IC95 {_fmt((o.get('lift100_ci') or [None])[0])}–{_fmt((o.get('lift100_ci') or [None,None])[1])})"
          f" · espérance nette {_fmt(o.get('net_expectancy'), pct=True)}"
          f" · garde ≤−50% {_fmt(o.get('guard_left'))}× ({'OK' if o.get('guard_ok') else 'DÉPASSE'})")
    print(f"  VALUE-OF-SURVIVAL : ne(complet)={_fmt(v['ne_full'], pct=True)} vs "
          f"ne(technique-seul)={_fmt(v['ne_tech'], pct=True)} · Δ={_fmt(v['delta'], pct=True)}"
          f" · folds meilleurs {v['folds_better']}/{v['n_folds']} → "
          f"{'AJOUTE de la valeur' if v['adds_value'] else 'N’AJOUTE PAS'}")
    for rg, m in (r.get("by_regime") or {}).items():
        if m:
            print(f"    [{rg}] lift +100% {_fmt(m.get('lift100'))}× · ne {_fmt(m.get('net_expectancy'), pct=True)}")
    bf = r.get("baseline_best_feature")
    print(f"  BASELINES : meilleure feature seule = {bf['feature'] if bf else '—'} "
          f"(ne {_fmt(bf['net_expectancy'] if bf else None, pct=True)}) · "
          f"Phénix v2 ne {_fmt(r.get('baseline_phenix_ne'), pct=True)}")
    if not r["signed_off"]:
        print(f"\n  ⚠️  NON-BINDING — protocole v3 non signé (§0). Verdict NON écrit au run-log.")
        print(f"      Rappel §2 : données gratuites = plafond optimiste ; le backtest ne peut que RÉFUTER.")
    print(f"{'='*66}\n")


def _fmt(x, pct: bool = False) -> str:
    if x is None:
        return "—"
    return f"{x*100:.1f}%" if pct else f"{x:.2f}"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest forward du screener (signaux prix/volume)")
    ap.add_argument("--n", type=int, default=200, help="nombre de tickers échantillonnés")
    ap.add_argument("--forward", type=int, default=63, help="horizon forward en jours de bourse")
    ap.add_argument("--seed", type=int, default=42, help="seed de reproductibilité")
    ap.add_argument("--period", type=str, default=None, help="profondeur d'historique (yfinance)")
    ap.add_argument("--sweep", action="store_true", help="balayer le poids de compression (rolling)")
    ap.add_argument("--study", action="store_true", help="STUDY roulante v1 multi-date (Sprint 6)")
    ap.add_argument("--study-v2", dest="study_v2", action="store_true",
                    help="STUDY v2 tail-hunting : profils Fusée/Phénix vs base (protocole v2)")
    ap.add_argument("--study-v3", dest="study_v3", action="store_true",
                    help="STUDY v3 survival-conditioned : purged walk-forward (protocole v3)")
    ap.add_argument("--signed-off", dest="signed_off", action="store_true",
                    help="autorise le JUGEMENT v3 (protocole v3 signé §0) ; sinon dry-run NON-BINDING")
    args = ap.parse_args()
    if args.study_v3:
        run_study_v3(n_tickers=(args.n if args.n else None), period=(args.period or "5y"),
                     seed=args.seed, signed_off=args.signed_off)
    elif args.study_v2:
        run_study_v2(n_tickers=(args.n if args.n else None), period=(args.period or "5y"), seed=args.seed)
    elif args.study:
        run_study(n_tickers=(args.n if args.n else None), period=(args.period or "3y"), seed=args.seed)
    elif args.sweep:
        run_weight_sweep(n_tickers=args.n, forward_days=args.forward, seed=args.seed, period=(args.period or "2y"))
    else:
        run_backtest(n_tickers=args.n, forward_days=args.forward, seed=args.seed, period=(args.period or "2y"))
