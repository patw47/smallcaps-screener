"""
SEC EDGAR — achats nets d'insiders via les formulaires Form 4 (Sprint 5).

Remplace le « % de détention d'insiders » (statique, non daté, non backtestable) par les
« achats nets en marché ouvert sur les 3-6 derniers mois » (vrai signal « l'argent informé
accumule » — gratuit, DATÉ, donc backtestable point-in-time au Sprint 6).

Conformité SEC stricte :
  - User-Agent identifiant (email réel) via env EDGAR_USER_AGENT — SINON désactivé (pas de 403).
  - ≤ 10 requêtes/s (throttle global, verrou partagé entre threads de la Passe B).
  - Cache local (data/edgar_cache/) : une soumission a un TTL ; un FILING (immuable) n'est
    JAMAIS re-téléchargé.

EDGAR indisponible / ticker inconnu / User-Agent absent → retourne None (neutre, ne pénalise
pas) : le scan aboutit toujours (même pattern que les autres capteurs).
"""

import os
import json
import time
import threading
from datetime import datetime, timezone, timedelta
from pathlib import Path
import xml.etree.ElementTree as ET

import requests

from screener_backend import FILTERS, DATA_DIR

EDGAR_CACHE_DIR = Path(DATA_DIR) / "edgar_cache"

# User-Agent identifiant EXIGÉ par la SEC. Absent → EDGAR désactivé (signal neutre).
_USER_AGENT = os.environ.get("EDGAR_USER_AGENT", "").strip()

_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
_ARCHIVE_DOC = "https://www.sec.gov/Archives/edgar/data/{cik}/{acc_nodash}/{doc}"

# Throttle global (≤ 10 req/s) — la Passe B lance 2 threads, le verrou sérialise les requêtes.
_throttle_lock = threading.Lock()
_last_request_ts = 0.0

# Cache mémoire du mapping ticker→CIK (fichier volumineux, stable).
_cik_map = None
_cik_map_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Réseau (throttlé, User-Agent conforme) + cache disque
# ---------------------------------------------------------------------------

def _throttle() -> None:
    global _last_request_ts
    with _throttle_lock:
        wait = FILTERS["edgar_rate_limit_s"] - (time.monotonic() - _last_request_ts)
        if wait > 0:
            time.sleep(wait)
        _last_request_ts = time.monotonic()


def _get(url: str):
    """GET throttlé avec User-Agent SEC. Retourne la réponse (200) ou None. Jamais fatal."""
    if not _USER_AGENT:
        return None
    _throttle()
    try:
        resp = requests.get(
            url, headers={"User-Agent": _USER_AGENT, "Accept-Encoding": "gzip, deflate"},
            timeout=15,
        )
        return resp if resp.status_code == 200 else None
    except Exception:
        return None


def _cache_file(name: str) -> Path:
    return EDGAR_CACHE_DIR / name


def _read_cache(name: str, ttl_s: float | None) -> str | None:
    """Contenu du cache si présent et frais (ttl_s=None → jamais périmé, ex. filings immuables)."""
    p = _cache_file(name)
    try:
        if p.exists() and (ttl_s is None or (time.time() - p.stat().st_mtime) < ttl_s):
            return p.read_text()
    except Exception:
        pass
    return None


def _write_cache(name: str, text: str) -> None:
    try:
        EDGAR_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        _cache_file(name).write_text(text)
    except Exception:
        pass


def _cached_text(url: str, name: str, ttl_s: float | None) -> str | None:
    """Sert depuis le cache si frais, sinon télécharge (throttlé) et met en cache."""
    cached = _read_cache(name, ttl_s)
    if cached is not None:
        return cached
    resp = _get(url)
    if resp is None:
        return None
    _write_cache(name, resp.text)
    return resp.text


# ---------------------------------------------------------------------------
# Mapping ticker → CIK
# ---------------------------------------------------------------------------

def _load_cik_map() -> dict[str, int] | None:
    global _cik_map
    with _cik_map_lock:
        if _cik_map is not None:
            return _cik_map
        # company_tickers.json est stable → TTL long (7 × TTL des soumissions).
        text = _cached_text(_TICKERS_URL, "company_tickers.json",
                            FILTERS["edgar_cache_ttl_hours"] * 3600 * 7)
        if text is None:
            return None
        try:
            data = json.loads(text)
        except Exception:
            return None
        m = {}
        for row in data.values():
            tk = str(row.get("ticker", "")).upper().strip()
            cik = row.get("cik_str")
            if tk and cik is not None:
                m[tk] = int(cik)
        _cik_map = m
        return _cik_map


# ---------------------------------------------------------------------------
# Parsing Form 4
# ---------------------------------------------------------------------------

def _num(text: str | None) -> float | None:
    if text is None:
        return None
    try:
        return float(str(text).strip())
    except (TypeError, ValueError):
        return None


def _parse_form4(xml_text: str) -> list[dict]:
    """
    Extrait les transactions NON dérivées en marché ouvert d'un Form 4 :
      - code « P » = achat en marché ouvert, code « S » = vente en marché ouvert.
    Ignore explicitement A (grant/award), M (exercice d'option), F (retenue fiscale), G (don)…
    Retourne [{date, code, shares, price, value}].
    """
    out: list[dict] = []
    try:
        root = ET.fromstring(xml_text)
    except Exception:
        return out
    for tx in root.iterfind(".//nonDerivativeTransaction"):
        code = (tx.findtext("./transactionCoding/transactionCode") or "").strip()
        if code not in ("P", "S"):
            continue
        date = (tx.findtext("./transactionDate/value") or "").strip()
        shares = _num(tx.findtext("./transactionAmounts/transactionShares/value"))
        price = _num(tx.findtext("./transactionAmounts/transactionPricePerShare/value"))
        if shares is None or price is None:
            continue
        out.append({"date": date, "code": code, "shares": shares,
                    "price": price, "value": shares * price})
    return out


def _filing_xml(cik: int, accession: str, doc: str) -> str | None:
    """XML d'un Form 4. Un filing est IMMUABLE → cache permanent (jamais re-téléchargé)."""
    name = f"form4_{accession.replace('-', '')}.xml"
    cached = _read_cache(name, None)  # TTL None = jamais périmé
    if cached is not None:
        return cached
    # `primaryDocument` porte souvent le préfixe de RENDU XSL (ex. "xslF345X06/wk-form4_x.xml")
    # qui pointe vers la version HTML humaine ; le XML BRUT est au nom nu (dernier segment).
    raw_doc = doc.split("/")[-1]
    url = _ARCHIVE_DOC.format(cik=cik, acc_nodash=accession.replace("-", ""), doc=raw_doc)
    resp = _get(url)
    if resp is None:
        return None
    text = resp.text
    # Garde-fou : ne JAMAIS mettre en cache une page HTML rendue (empoisonnerait le cache
    # permanent). On n'accepte qu'un vrai document ownership XML.
    if "<ownershipDocument" not in text:
        return None
    _write_cache(name, text)
    return text


# ---------------------------------------------------------------------------
# Achats nets d'insiders
# ---------------------------------------------------------------------------

def net_insider_buying(ticker: str, window_days: int | None = None,
                       now: datetime | None = None) -> dict | None:
    """
    Somme nette des achats en marché ouvert (Σ P − Σ S, en $) sur `window_days`, filtrée par
    transactionDate (daté → réutilisable point-in-time au Sprint 6).

    Retourne un dict daté OU None si EDGAR est indisponible / désactivé / le ticker est inconnu
    (None = neutre, ne pénalise pas). Un ticker CONNU sans transaction dans la fenêtre renvoie
    net_buying=0.0 (signal réel « pas d'achat »), pas None.
    """
    if not _USER_AGENT:
        return None
    window_days = window_days or FILTERS["insider_window_days"]
    now = now or datetime.now(tz=timezone.utc)
    cutoff = (now - timedelta(days=window_days)).date().isoformat()

    cik_map = _load_cik_map()
    if not cik_map:
        return None
    cik = cik_map.get(ticker.upper())
    if cik is None:
        return None  # ticker absent d'EDGAR → neutre

    cik10 = f"{cik:010d}"
    subs_text = _cached_text(
        _SUBMISSIONS_URL.format(cik10=cik10), f"submissions_{cik10}.json",
        FILTERS["edgar_cache_ttl_hours"] * 3600)
    if subs_text is None:
        return None
    try:
        recent = json.loads(subs_text)["filings"]["recent"]
        forms, accs = recent["form"], recent["accessionNumber"]
        fdates, docs = recent["filingDate"], recent["primaryDocument"]
    except Exception:
        return None

    transactions: list[dict] = []
    parsed = 0
    # recent[] est trié du plus récent au plus ancien : on s'arrête dès qu'un filing est
    # déposé avant le cutoff (transactionDate ≤ filingDate → forcément hors fenêtre).
    for form, acc, fdate, doc in zip(forms, accs, fdates, docs):
        if form != "4":
            continue
        if fdate < cutoff:
            break
        if parsed >= FILTERS["edgar_max_filings"]:
            break
        xml = _filing_xml(cik, acc, doc)
        parsed += 1
        if xml is not None:
            transactions.extend(_parse_form4(xml))

    inwin = [t for t in transactions if t["date"] and t["date"] >= cutoff]
    buys = sum(t["value"] for t in inwin if t["code"] == "P")
    sells = sum(t["value"] for t in inwin if t["code"] == "S")
    return {
        "ticker": ticker.upper(), "cik": cik,
        "net_buying": buys - sells, "buy_dollars": buys, "sell_dollars": sells,
        "n_buys": sum(1 for t in inwin if t["code"] == "P"),
        "n_sells": sum(1 for t in inwin if t["code"] == "S"),
        "window_days": window_days, "cutoff": cutoff, "as_of": now.isoformat(),
        "transactions": inwin,  # datées → point-in-time (Sprint 6)
    }
