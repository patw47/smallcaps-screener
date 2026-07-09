"""EXPLORATION (pas un protocole) : profondeur de chute titre requise, par fenêtre 7/14/21 j,
marché en baisse sur la même fenêtre. Règles constantes : prix <= 8, sans dilution.
fwd63 net (coûts -1%) repris de sim_filter.json (r[5])."""
import json, math, bisect
import yfinance as yf

obs = json.load(open("/app/data/sim_filter.json"))
dates = sorted({o["d"] for o in obs})
tickers = sorted({o["t"] for o in obs})

iwm = yf.download("IWM", period="6y", interval="1d", auto_adjust=True, progress=False)
bc = iwm["Close"];  bc = bc.iloc[:, 0] if hasattr(bc, "columns") else bc
bc = bc.dropna();  bidx = [str(x)[:10] for x in bc.index]
def mkt_ret(d, w):
    i = bisect.bisect_right(bidx, d) - 1
    return None if i < w else float(bc.iloc[i]) / float(bc.iloc[i - w]) - 1.0

# clôtures 2021->2026 par lots de 100
closes = {}
LOT = 100
for j in range(0, len(tickers), LOT):
    lot = tickers[j:j+LOT]
    df = yf.download(lot, start="2021-01-01", end="2026-02-01", interval="1d",
                     auto_adjust=True, progress=False, threads=True)
    c = df["Close"]
    if not hasattr(c, "columns"):
        c = c.to_frame(name=lot[0])
    for t in c.columns:
        s = c[t].dropna()
        if len(s) > 30:
            closes[t] = ([str(x)[:10] for x in s.index], s.to_list())
    print(f"[lot {j//LOT+1}/{(len(tickers)+LOT-1)//LOT}] cumul {len(closes)} séries", flush=True)

def chg(t, d, w):
    if t not in closes: return None
    idx, vals = closes[t]
    i = bisect.bisect_right(idx, d) - 1
    if i < w or idx[i] != d and idx[i] < d[:8] + "01": pass
    if i < w: return None
    return vals[i] / vals[i - w] - 1.0

FWD, HAIRCUT = 5, 0.01
base = [o for o in obs if o["price"] <= 8 and o["dil"] is False and o["r"][FWD] is not None]
print(f"\nbase (prix<=8, sans dilution, fwd63 connu): {len(base)} obs")
print(f"couverture prix: {sum(1 for o in base if o['t'] in closes)}/{len(base)}")

THRESHOLDS = [0.0, -0.03, -0.05, -0.10, -0.15, -0.20, -0.30]
out = {}
for w in (7, 14, 21):
    mkt = {d: mkt_ret(d, w) for d in dates}
    active = {d for d in dates if mkt[d] is not None and mkt[d] < 0}
    rows = []
    enriched = [(o, chg(o["t"], o["d"], w)) for o in base if o["d"] in active]
    enriched = [(o, c) for o, c in enriched if c is not None]
    for thr in THRESHOLDS:
        sel = [o for o, c in enriched if c <= thr]
        rs = sorted(o["r"][FWD] for o in sel)
        n = len(rs)
        if n < 20:
            rows.append(dict(thr=thr, n=n)); continue
        e = sum(rs)/n - HAIRCUT
        med = (rs[n//2] if n % 2 else (rs[n//2-1]+rs[n//2])/2) - HAIRCUT
        pex = sum(1 for r in rs if r >= 1.0)/n
        pcr = sum(1 for r in rs if r <= -0.5)/n
        bydate = {}
        for o, c in enriched:
            if c <= thr: bydate.setdefault(o["d"], []).append(o["r"][FWD])
        dm = [sum(v)/len(v) - HAIRCUT for v in bydate.values()]
        k = len(dm); t = None
        if k >= 2:
            m = sum(dm)/k
            sd = math.sqrt(sum((x-m)**2 for x in dm)/(k-1))
            if sd > 0: t = m/(sd/math.sqrt(k))
        rows.append(dict(thr=thr, n=n, e=e, med=med, pex=pex, pcr=pcr, t=t, k=k))
    out[w] = dict(active=len(active), rows=rows)

json.dump(out, open("/app/data/sim_grid_windows.json", "w"))
for w, r in out.items():
    print(f"\n=== Fenêtre {w} séances — marché <0 sur {w}j : {r['active']}/18 dates ===")
    print(f"{'chute <=':>9} {'n':>6} {'E_net':>7} {'méd':>7} {'P(x2)':>6} {'P(-50)':>7} {'t':>6} {'k':>3}")
    for row in r["rows"]:
        if "e" not in row:
            print(f"{row['thr']:>8.0%} {row['n']:>6}   (n trop faible)"); continue
        print(f"{row['thr']:>8.0%} {row['n']:>6} {row['e']:>+7.1%} {row['med']:>+7.1%} "
              f"{row['pex']:>6.1%} {row['pcr']:>7.1%} {row['t'] if row['t'] is None else round(row['t'],2)!s:>6} {row['k']:>3}")
