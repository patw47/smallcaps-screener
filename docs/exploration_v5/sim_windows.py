"""Sensibilité EXPLORATOIRE de la condition marché v4 : IWM 7j / 14j / 21j.
Re-tranche les observations de l'exploration du 2026-07-06 (sim_filter.json).
Ne change AUCUNE règle — info de robustesse seulement."""
import json, math
import yfinance as yf

obs = json.load(open("/app/data/sim_filter.json"))
beta = json.load(open("/app/data/sim_beta.json"))
mkt21_ref = {}  # mkt21 exact utilisé par l'exploration, par date
for o in beta:
    mkt21_ref.setdefault(o["d"], o["mkt21"])

dates = sorted({o["d"] for o in obs})

iwm = yf.download("IWM", period="6y", interval="1d", auto_adjust=True, progress=False)
close = iwm["Close"]
if hasattr(close, "columns"):  # MultiIndex éventuel
    close = close.iloc[:, 0]
close = close.dropna()
idx_str = [str(x)[:10] for x in close.index]

def ret_at(d, w):
    """Rendement IWM sur w séances finissant à la dernière séance <= d."""
    import bisect
    i = bisect.bisect_right(idx_str, d) - 1
    if i < w:
        return None
    return float(close.iloc[i]) / float(close.iloc[i - w]) - 1.0

# calibration : mon ret21 vs mkt21 de l'exploration
print("Calibration ret21 vs exploration (doit coller à ~1e-3):")
for d in dates:
    r21 = ret_at(d, 21)
    ref = mkt21_ref.get(d)
    flag = "" if (ref is None or r21 is None or abs(r21 - ref) < 2e-3) else "  <<< ECART"
    print(f"  {d}  calc {r21:+.4f}  ref {('%+.4f' % ref) if ref is not None else '   n/a'}{flag}")

# identifier l'index fwd63 dans r[] : reproduire E net +5.9% / n=1193 / P 2.0/1.9
combo21 = [o for o in obs if o["price"] <= 8 and o["dil"] is False and o["chg1m"] <= -0.03
           and mkt21_ref.get(o["d"]) is not None and mkt21_ref[o["d"]] < 0]
print(f"\ncombo+mkt21<0 (ref exploration): n={len(combo21)} (protocole: 1193)")
HAIRCUT = 0.01
for i in range(7):
    rs = [o["r"][i] for o in combo21 if o["r"][i] is not None]
    if not rs: continue
    e = sum(rs)/len(rs) - HAIRCUT
    pex = sum(1 for r in rs if r >= 1.0)/len(rs)
    pcr = sum(1 for r in rs if r <= -0.5)/len(rs)
    print(f"  r[{i}] n={len(rs)}  E_net {e:+.3f}  P(x2) {pex:.3%}  P(-50%) {pcr:.3%}")

