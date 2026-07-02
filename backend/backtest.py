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

import pandas as pd

from screener_backend import (
    FILTERS, discover_tickers, analyze_prices, _download_prices,
    _factor_composite, _binary_price_score, TECH_FACTORS,
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


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Backtest forward du screener (signaux prix/volume)")
    ap.add_argument("--n", type=int, default=200, help="nombre de tickers échantillonnés")
    ap.add_argument("--forward", type=int, default=63, help="horizon forward en jours de bourse")
    ap.add_argument("--seed", type=int, default=42, help="seed de reproductibilité")
    ap.add_argument("--period", type=str, default="2y", help="profondeur d'historique (yfinance)")
    ap.add_argument("--sweep", action="store_true", help="balayer le poids de compression (rolling)")
    ap.add_argument("--study", action="store_true", help="STUDY roulante multi-date (Sprint 6)")
    args = ap.parse_args()
    if args.study:
        run_study(n_tickers=(args.n if args.n else None), period=args.period, seed=args.seed)
    elif args.sweep:
        run_weight_sweep(n_tickers=args.n, forward_days=args.forward, seed=args.seed, period=args.period)
    else:
        run_backtest(n_tickers=args.n, forward_days=args.forward, seed=args.seed, period=args.period)
