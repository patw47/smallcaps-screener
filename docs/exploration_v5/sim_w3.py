"""EXPLORATION : fenêtre 3 séances — grille de profondeur + profil 'explosée type'."""
import json, math, bisect, pickle
import yfinance as yf

obs = json.load(open("/app/data/sim_filter.json"))
dates = sorted({o["d"] for o in obs})
closes = pickle.load(open("/app/data/closes_1870.pkl", "rb"))
vols = pickle.load(open("/app/data/volumes_1870.pkl", "rb"))

iwm = yf.download("IWM", period="6y", interval="1d", auto_adjust=True, progress=False)
bc = iwm["Close"]; bc = bc.iloc[:, 0] if hasattr(bc, "columns") else bc
bc = bc.dropna(); bidx = [str(x)[:10] for x in bc.index]
W = 3
def mkt_ret(d):
    i = bisect.bisect_right(bidx, d) - 1
    return None if i < W else float(bc.iloc[i])/float(bc.iloc[i-W]) - 1.0
def chg(t, d):
    if t not in closes: return None
    idx, vals = closes[t]
    i = bisect.bisect_right(idx, d) - 1
    return None if i < W else vals[i]/vals[i-W] - 1.0
def vol_calm(t, d):
    if t not in vols: return None
    idx, vals = vols[t]
    i = bisect.bisect_right(idx, d) - 1
    if i < W + 30: return None
    recent = vals[i-W+1:i+1]; base = vals[max(0, i-W-60+1):i-W+1]
    if not base or not recent: return None
    b = sum(base)/len(base)
    return None if b == 0 else (sum(recent)/len(recent)) / b

FWD, HAIRCUT = 5, 0.01
pool = [o for o in obs if o["price"] <= 8 and o["dil"] is False and o["r"][FWD] is not None]

def stats(sel):
    rs = sorted(o["r"][FWD] for o in sel)
    n = len(rs)
    if n < 15: return dict(n=n)
    e = sum(rs)/n - HAIRCUT
    m = (rs[n//2] if n % 2 else (rs[n//2-1]+rs[n//2])/2) - HAIRCUT
    pex = sum(1 for r in rs if r >= 1.0)/n
    pcr = sum(1 for r in rs if r <= -0.5)/n
    bydate = {}
    for o in sel: bydate.setdefault(o["d"], []).append(o["r"][FWD])
    dm = [sum(v)/len(v) - HAIRCUT for v in bydate.values()]
    k = len(dm); t = None
    if k >= 2:
        mu = sum(dm)/k
        sd = math.sqrt(sum((x-mu)**2 for x in dm)/(k-1))
        if sd > 0: t = mu/(sd/math.sqrt(k))
    return dict(n=n, e=e, med=m, pex=pex, pcr=pcr, t=t, k=k,
                bydate={d: (len(v), round(sum(v)/len(v)-HAIRCUT, 3)) for d, v in sorted(bydate.items())})

active = {d for d in dates if (m := mkt_ret(d)) is not None and m < 0}
print(f"IWM 3j < 0 : {len(active)}/18 dates actives — {sorted(f'{d} ({mkt_ret(d):+.1%})' for d in active)}")

enr = []
for o in pool:
    if o["d"] not in active: continue
    c = chg(o["t"], o["d"])
    if c is None: continue
    enr.append((o, c, vol_calm(o["t"], o["d"])))

def row(name, sel):
    s = stats(sel)
    if s["n"] < 15:
        print(f" {name:<34} {s['n']:>5}   (n trop faible)"); return
    print(f" {name:<34} {s['n']:>5} {s['e']:>+7.1%} {s['med']:>+7.1%} {s['pex']:>6.1%} "
          f"{s['pcr']:>7.1%} {round(s['t'],2) if s['t'] is not None else 'n/a':>6} {s['k']:>3}")
    return s

print(f"\n— grille de profondeur (chute 3j, sans dilution) —")
print(f" {'chute <=':<34} {'n':>5} {'E_net':>7} {'méd':>7} {'P(x2)':>6} {'P(-50)':>7} {'t':>6} {'k':>3}")
for thr in (0.0, -0.03, -0.05, -0.10, -0.15, -0.20):
    row(f"{thr:.0%}", [o for o, c, _ in enr if c <= thr])

print(f"\n— profil 'explosée type' (chute<=-15%) —")
sel15 = [(o, c, v) for o, c, v in enr if c <= -0.15]
row("base", [o for o, _, _ in sel15])
row("+ CMF > -0.10", [o for o, _, _ in sel15 if o["cmf"] is not None and o["cmf"] > -0.10])
row("+ volume calme (<=1.25x)", [o for o, _, v in sel15 if v is not None and v <= 1.25])
s = row("+ les deux", [o for o, _, v in sel15 if o["cmf"] is not None and o["cmf"] > -0.10 and v is not None and v <= 1.25])
if s and s.get("bydate"):
    print("  par date:", "  ".join(f"{d[2:]}: n={n} {e:+.0%}" for d, (n, e) in s["bydate"].items()))
