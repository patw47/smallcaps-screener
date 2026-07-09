"""EXPLORATION : profil 'explosée type' en règles d'entrée, fenêtres 7/14/21j.
Filtres fixés a priori : prix<=8, sans dilution, chute_w <= -15%, IWM_w < 0,
puis couches : CMF > -0.10 ; volume calme (vol_w <= 1.25x base 60j) ; les deux."""
import json, math, bisect, os, pickle
import yfinance as yf

obs = json.load(open("/app/data/sim_filter.json"))
dates = sorted({o["d"] for o in obs})
tickers = sorted({o["t"] for o in obs})

closes = pickle.load(open("/app/data/closes_1870.pkl", "rb"))

VCACHE = "/app/data/volumes_1870.pkl"
if os.path.exists(VCACHE):
    vols = pickle.load(open(VCACHE, "rb"))
else:
    vols = {}
    for j in range(0, len(tickers), 100):
        lot = tickers[j:j+100]
        df = yf.download(lot, start="2021-01-01", end="2026-02-01", interval="1d",
                         auto_adjust=True, progress=False, threads=True)
        v = df["Volume"]
        if not hasattr(v, "columns"): v = v.to_frame(name=lot[0])
        for t in v.columns:
            s = v[t].dropna()
            if len(s) > 30: vols[t] = ([str(x)[:10] for x in s.index], s.to_list())
        print(f"[lot {j//100+1}/19] cumul {len(vols)}", flush=True)
    pickle.dump(vols, open(VCACHE, "wb"))

iwm = yf.download("IWM", period="6y", interval="1d", auto_adjust=True, progress=False)
bc = iwm["Close"]; bc = bc.iloc[:, 0] if hasattr(bc, "columns") else bc
bc = bc.dropna(); bidx = [str(x)[:10] for x in bc.index]
def mkt_ret(d, w):
    i = bisect.bisect_right(bidx, d) - 1
    return None if i < w else float(bc.iloc[i])/float(bc.iloc[i-w]) - 1.0
def chg(t, d, w):
    if t not in closes: return None
    idx, vals = closes[t]
    i = bisect.bisect_right(idx, d) - 1
    return None if i < w else vals[i]/vals[i-w] - 1.0
def vol_calm(t, d, w):
    """moyenne volume fenêtre w / moyenne volume 60j précédents (None si base insuffisante)."""
    if t not in vols: return None
    idx, vals = vols[t]
    i = bisect.bisect_right(idx, d) - 1
    if i < w + 30: return None
    recent = vals[i-w+1:i+1]
    base = vals[max(0, i-w-60+1):i-w+1]
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

for w in (7, 14, 21):
    active = {d for d in dates if (m := mkt_ret(d, w)) is not None and m < 0}
    enr = []
    for o in pool:
        if o["d"] not in active: continue
        c = chg(o["t"], o["d"], w)
        if c is None or c > -0.15: continue
        enr.append((o, vol_calm(o["t"], o["d"], w)))
    layers = [
        ("base (chute<=-15%, sans dil.)", [o for o, _ in enr]),
        ("+ CMF > -0.10",                 [o for o, _ in enr if o["cmf"] is not None and o["cmf"] > -0.10]),
        ("+ volume calme (<=1.25x)",      [o for o, v in enr if v is not None and v <= 1.25]),
        ("+ les deux",                    [o for o, v in enr if o["cmf"] is not None and o["cmf"] > -0.10
                                                             and v is not None and v <= 1.25]),
    ]
    print(f"\n=== FENÊTRE {w}j — {len(active)}/18 dates actives ===")
    print(f" {'filtre':<32} {'n':>5} {'E_net':>7} {'méd':>7} {'P(x2)':>6} {'P(-50)':>7} {'t':>6} {'k':>3}")
    for name, sel in layers:
        s = stats(sel)
        if s["n"] < 15:
            print(f" {name:<32} {s['n']:>5}   (n trop faible)"); continue
        print(f" {name:<32} {s['n']:>5} {s['e']:>+7.1%} {s['med']:>+7.1%} {s['pex']:>6.1%} "
              f"{s['pcr']:>7.1%} {round(s['t'],2) if s['t'] is not None else 'n/a':>6} {s['k']:>3}")
    s = stats(layers[3][1])
    if s.get("bydate"):
        print("  par date (profil complet):", "  ".join(f"{d[2:]}: n={n} {e:+.0%}" for d, (n, e) in s["bydate"].items()))
