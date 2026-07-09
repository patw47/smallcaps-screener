"""Comparaison EXPLORATOIRE fenêtres marché 7/14/21 séances — règles titre inchangées."""
import json, math, bisect
import yfinance as yf

obs = json.load(open("/app/data/sim_filter.json"))
dates = sorted({o["d"] for o in obs})

iwm = yf.download("IWM", period="6y", interval="1d", auto_adjust=True, progress=False)
close = iwm["Close"]
if hasattr(close, "columns"):
    close = close.iloc[:, 0]
close = close.dropna()
idx_str = [str(x)[:10] for x in close.index]

def ret_at(d, w):
    i = bisect.bisect_right(idx_str, d) - 1
    return None if i < w else float(close.iloc[i]) / float(close.iloc[i - w]) - 1.0

FWD, HAIRCUT = 5, 0.01   # r[5] = fwd63
combo = [o for o in obs if o["price"] <= 8 and o["dil"] is False and o["chg1m"] <= -0.03
         and o["r"][FWD] is not None]

def stats(window):
    mkt = {d: ret_at(d, window) for d in dates}
    active = [d for d in dates if mkt[d] is not None and mkt[d] < 0]
    sel = [o for o in combo if o["d"] in active]
    rs = sorted(o["r"][FWD] for o in sel)
    n = len(rs)
    if n == 0:
        return dict(window=window, active=len(active), n=0)
    e = sum(rs)/n - HAIRCUT
    med = rs[n//2] if n % 2 else (rs[n//2-1]+rs[n//2])/2
    pex = sum(1 for r in rs if r >= 1.0)/n
    pcr = sum(1 for r in rs if r <= -0.5)/n
    # t date-level : moyenne des moyennes par date
    dm = []
    for d in active:
        drs = [o["r"][FWD] for o in combo if o["d"] == d]
        if drs:
            dm.append(sum(drs)/len(drs) - HAIRCUT)
    k = len(dm)
    t = None
    if k >= 2:
        m = sum(dm)/k
        sd = math.sqrt(sum((x-m)**2 for x in dm)/(k-1))
        t = m / (sd/math.sqrt(k)) if sd > 0 else None
    return dict(window=window, active=len(active), dates_with_obs=k, n=n,
                e_net=e, med=med-HAIRCUT, pex=pex, pcr=pcr, t=t,
                active_dates=[f"{d} ({mkt[d]:+.1%})" for d in active])

print(f"combo (prix<=8, sans dilution, chute>=3%): {len(combo)} obs, fwd63 net (coûts -1%)\n")
for w in (7, 14, 21):
    s = stats(w)
    print(f"— Fenêtre {w} séances : {s['active']}/18 dates actives, n={s['n']}")
    if s['n']:
        print(f"   E_net {s['e_net']:+.1%}  médiane {s['med']:+.1%}  P(x2) {s['pex']:.1%}  "
              f"P(-50%) {s['pcr']:.1%}  t(date, k={s['dates_with_obs']}) = "
              f"{s['t']:.2f}" if s['t'] is not None else "   t: n/a")
        print(f"   dates: {', '.join(s['active_dates'])}")
    print()

print("Base aléatoire (toutes obs, tous marchés):")
rs = [o["r"][FWD] for o in obs if o["r"][FWD] is not None]
print(f"   n={len(rs)}  E_net {sum(rs)/len(rs)-HAIRCUT:+.1%}  "
      f"P(x2) {sum(1 for r in rs if r>=1.0)/len(rs):.1%}  P(-50%) {sum(1 for r in rs if r<=-0.5)/len(rs):.1%}")

print("\nAujourd'hui (dernière clôture IWM):")
last = idx_str[-1]
for w in (7, 14, 21):
    r = ret_at(last, w)
    print(f"   IWM {w}j = {r:+.1%}  → méthode {'ACTIVE' if r < 0 else 'en pause'}")
