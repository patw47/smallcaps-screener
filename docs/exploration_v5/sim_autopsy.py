"""EXPLORATION : mortes (fwd63<=-50%) vs explosées (fwd63>=+100%) dans les cases washout 7/14j.
Cellule : prix<=8, chute_w <= -3%, IWM_w < 0 (dilution NON filtrée — on la mesure)."""
import json, math, bisect, os, pickle
import yfinance as yf

obs = json.load(open("/app/data/sim_filter.json"))
dates = sorted({o["d"] for o in obs})
tickers = sorted({o["t"] for o in obs})

aut = {}
for f in ("autopsy.json", "autopsy_crash.json"):
    for a in json.load(open("/app/data/" + f)):
        aut.setdefault((a["t"], a["d"]), a)

CACHE = "/app/data/closes_1870.pkl"
if os.path.exists(CACHE):
    closes = pickle.load(open(CACHE, "rb"))
else:
    closes = {}
    for j in range(0, len(tickers), 100):
        lot = tickers[j:j+100]
        df = yf.download(lot, start="2021-01-01", end="2026-02-01", interval="1d",
                         auto_adjust=True, progress=False, threads=True)
        c = df["Close"]
        if not hasattr(c, "columns"): c = c.to_frame(name=lot[0])
        for t in c.columns:
            s = c[t].dropna()
            if len(s) > 30: closes[t] = ([str(x)[:10] for x in s.index], s.to_list())
        print(f"[lot {j//100+1}/19] cumul {len(closes)}", flush=True)
    pickle.dump(closes, open(CACHE, "wb"))

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

FWD = 5
base = [o for o in obs if o["price"] <= 8 and o["r"][FWD] is not None]

def med(xs):
    xs = sorted(x for x in xs if x is not None)
    n = len(xs)
    return None if n == 0 else (xs[n//2] if n % 2 else (xs[n//2-1]+xs[n//2])/2)
def pct(xs):
    xs = [x for x in xs if x is not None]
    return None if not xs else sum(1 for x in xs if x)/len(xs)

FEATURES = [
    ("dilution",        "flag", "dilution en attente"),
    ("going_concern",   "flag", "going-concern"),
    ("late_filing",     "flag", "retard de dépôt"),
    ("cash_runway",     "med",  "cash runway (trim.)"),
    ("pct_52w_high",    "med",  "prix / plus-haut 52s"),
    ("cmf",             "med",  "CMF (flux)"),
    ("vol_ratio",       "med",  "ratio volume"),
    ("updown_vol_ratio","med",  "vol. hausse/baisse"),
    ("pre_8k",          "med",  "8-K 90j avant"),
    ("price",           "med",  "prix ($)"),
]

result = {}
for w in (7, 14):
    active = {d for d in dates if (m := mkt_ret(d, w)) is not None and m < 0}
    cell = []
    for o in base:
        if o["d"] not in active: continue
        c = chg(o["t"], o["d"], w)
        if c is not None and c <= -0.03:
            cell.append((o, c))
    dead = [(o, c) for o, c in cell if o["r"][FWD] <= -0.5]
    expl = [(o, c) for o, c in cell if o["r"][FWD] >= 1.0]
    print(f"\n{'='*70}\n FENÊTRE {w}j — cellule n={len(cell)} · mortes {len(dead)} · explosées {len(expl)}\n{'='*70}")
    cov_d = sum(1 for o, _ in dead if (o['t'], o['d']) in aut)
    cov_e = sum(1 for o, _ in expl if (o['t'], o['d']) in aut)
    print(f" couverture dossier EDGAR: mortes {cov_d}/{len(dead)} · explosées {cov_e}/{len(expl)}")
    rows = []
    for key, kind, label in FEATURES:
        vd = [aut[(o['t'],o['d'])].get(key) for o, _ in dead if (o['t'],o['d']) in aut]
        ve = [aut[(o['t'],o['d'])].get(key) for o, _ in expl if (o['t'],o['d']) in aut]
        if kind == "flag":
            a, b = pct(vd), pct(ve)
            rows.append((label, f"{a:.0%}" if a is not None else "n/a",
                                f"{b:.0%}" if b is not None else "n/a"))
        else:
            a, b = med(vd), med(ve)
            fmt = lambda x: "n/a" if x is None else (f"{x:.2f}" if abs(x) < 10 else f"{x:.0f}")
            rows.append((label, fmt(a), fmt(b)))
    # profondeur de chute + checkpoint J+5 (r[0]) + drawdown 52w depuis sim/closes
    rows.append((f"chute {w}j (méd.)", f"{med([c for _,c in dead]):+.1%}", f"{med([c for _,c in expl]):+.1%}"))
    cp_d = [o["r"][0] for o,_ in dead]; cp_e = [o["r"][0] for o,_ in expl]
    rows.append(("checkpoint J+5 (méd.)", f"{med(cp_d):+.1%}", f"{med(cp_e):+.1%}"))
    rows.append(("checkpoint > +3 %", f"{pct([x>0.03 for x in cp_d]):.0%}", f"{pct([x>0.03 for x in cp_e]):.0%}"))
    print(f"\n {'caractéristique':<24} {'MORTES':>10} {'EXPLOSÉES':>10}")
    for label, a, b in rows:
        print(f" {label:<24} {a:>10} {b:>10}")
    def listing(group):
        out = []
        for o, c in sorted(group, key=lambda x: x[0]["r"][FWD]):
            a = aut.get((o['t'], o['d']), {})
            flags = "".join(["D" if a.get("dilution") else "-",
                             "G" if a.get("going_concern") else "-",
                             "L" if a.get("late_filing") else "-"])
            out.append(f"   {o['d']}  {o['t']:<6} {o['price']:>6.2f}$  chute{w}j {c:+.0%}  fwd63 {o['r'][FWD]:+.0%}  [{flags}]")
        return out
    print(f"\n MORTES (fwd63 <= -50%) — flags D=dilution G=going-concern L=late-filing:")
    print("\n".join(listing(dead)))
    print(f"\n EXPLOSÉES (fwd63 >= +100%):")
    print("\n".join(reversed(listing(expl))))
    result[w] = dict(cell=len(cell), dead=len(dead), expl=len(expl))
json.dump(result, open("/app/data/sim_autopsy_windows.json", "w"))
