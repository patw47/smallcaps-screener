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

# ---------------------------------------------------------------------------
# Signaux de SURVIE (Epic 3 S2) — la queue gauche que le prix ne voit pas
# ---------------------------------------------------------------------------

# Émissions d'actions à venir (registrations / prospectus) → dilution.
_DILUTION_PREFIXES = ("S-1", "S-3", "F-1", "F-3", "424B")
# Rapports périodiques en retard → détresse de reporting.
_LATE_FORMS = ("NT 10-Q", "NT 10-K")
# Rapports périodiques de base (texte scanné pour le going-concern).
_PERIODIC_FORMS = ("10-Q", "10-K")


def _doc_text(cik: int, accession: str, doc: str) -> str | None:
    """Texte du document primaire d'un filing (IMMUABLE → cache permanent). Générique.

    Comme pour le Form 4, `primaryDocument` peut porter un préfixe de rendu XSL : on vise le
    nom nu (dernier segment). Jamais fatal ; None si indisponible.
    """
    raw = doc.split("/")[-1]
    name = f"doc_{accession.replace('-', '')}_{raw}"
    cached = _read_cache(name, None)  # filing immuable → jamais périmé
    if cached is not None:
        return cached
    url = _ARCHIVE_DOC.format(cik=cik, acc_nodash=accession.replace("-", ""), doc=raw)
    resp = _get(url)
    if resp is None:
        return None
    _write_cache(name, resp.text)
    return resp.text


def survival_signals(ticker: str, now: datetime | None = None,
                     window_days: int | None = None) -> dict | None:
    """
    Signaux de SURVIE datés depuis EDGAR (Epic 3 S2) — l'information de queue gauche que le
    prix ne contient pas. POINT-IN-TIME STRICT : seuls les filings dont `filingDate ≤ as_of`
    sont vus (aucun look-ahead), donc réutilisable tel quel par l'étude walk-forward.

    - `dilution_flag`      : registration / prospectus (S-1/S-3/F-1/F-3/424B) dans la fenêtre
                             → émission d'actions à venir.
    - `late_filing_flag`   : NT 10-Q / NT 10-K dans la fenêtre → rapport en retard (détresse).
    - `going_concern_flag` : « substantial doubt » (langage ASC 205-40) dans le dernier
                             10-Q/10-K ≤ as_of → le signal de faillite le plus direct.
    - `cash_runway`        : None pour l'instant (voir ponytail — piste XBRL companyfacts).

    Booléens : filing absent → False (pas de mauvaise nouvelle), jamais None pour « donnée
    manquante ». None UNIQUEMENT si EDGAR est indisponible / désactivé / ticker inconnu
    (neutre, ne pénalise pas — même contrat que `net_insider_buying`).
    """
    if not _USER_AGENT:
        return None
    window_days = window_days or FILTERS["survival_window_days"]
    now = now or datetime.now(tz=timezone.utc)
    as_of = now.date().isoformat()
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

    dilution = late = False
    gc = None  # (filingDate, cik, accession, doc) du dernier 10-Q/10-K ≤ as_of
    for form, acc, fdate, doc in zip(forms, accs, fdates, docs):
        if fdate > as_of:
            continue  # POINT-IN-TIME : filing postérieur à la date de scan → invisible
        f = form.strip()
        if cutoff <= fdate <= as_of:
            if f.startswith(_DILUTION_PREFIXES):
                dilution = True
            if f in _LATE_FORMS:
                late = True
        if f in _PERIODIC_FORMS and (gc is None or fdate > gc[0]):
            gc = (fdate, cik, acc, doc)

    going_concern = False
    if gc is not None:
        text = _doc_text(gc[1], gc[2], gc[3])
        if text is not None:
            going_concern = "substantial doubt" in text.lower()

    return {
        "ticker": ticker.upper(), "cik": cik,
        "dilution_flag": dilution,
        "late_filing_flag": late,
        "going_concern_flag": going_concern,
        # ponytail: cash_runway via XBRL companyfacts (data.sec.gov/api/xbrl/companyfacts) —
        # datable mais parsing fragile (annuel vs trimestriel, restatements). None = neutre
        # au protocole v3 §3. À câbler si le modèle S3 montre que le veto survie en a besoin.
        "cash_runway": None,
        "window_days": window_days, "cutoff": cutoff, "as_of": as_of,
    }


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
