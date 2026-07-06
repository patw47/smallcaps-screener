"""
Alertes Telegram sur les cassures Fusée (Sprint 3 ; sémantique révisée Epic 2 Sprint 2).

Le score dit « le ressort est armé » (watchlist) ; le variant ÉVÉNEMENT de Fusée dit
« un extrême de momentum casse MAINTENANT ». Ce module notifie, à chaque scan, les tickers
NOUVELLEMENT en `fusee_event` (membre Fusée + cassure le jour même) dont le `setup_score`
dépasse `FILTERS["alert_min_score"]`. Un simple `triggered` non-Fusée n'alerte plus.

Anti-doublon : un même ticker n'est pas re-notifié avant `FILTERS["alert_dedup_days"]`
jours (état persistant dans `data/alerts_state.json`).

Secrets via variables d'environnement UNIQUEMENT (jamais en dur) :
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
Sans token/chat_id configurés, l'alerting est silencieusement désactivé : le scan
fonctionne normalement.
"""

import os
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

from screener_backend import FILTERS, DATA_DIR

ALERT_STATE_FILE = Path(DATA_DIR) / "alerts_state.json"


# ---------------------------------------------------------------------------
# État anti-doublon (persistant, tolérant aux corruptions)
# ---------------------------------------------------------------------------

def _load_state(path: Path) -> dict[str, str]:
    """{ticker: ISO date de dernière alerte}. Fichier absent/corrompu → {} (jamais fatal)."""
    try:
        return json.loads(Path(path).read_text())
    except Exception:
        return {}


def _save_state(path: Path, state: dict[str, str]) -> None:
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_text(json.dumps(state, indent=2, ensure_ascii=False))
    except Exception as e:
        print(f"[alert] écriture d'état impossible (ignorée) : {e}")


# ---------------------------------------------------------------------------
# Envoi Telegram
# ---------------------------------------------------------------------------

def send_telegram(text: str) -> bool:
    """
    Envoie un message. Retourne True si envoyé, False si désactivé (pas de secrets)
    ou en cas d'échec réseau. N'élève jamais d'exception.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False  # alerting silencieusement désactivé
    try:
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                  "disable_web_page_preview": True},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception as e:
        # Ne JAMAIS logger `e` : les exceptions requests contiennent l'URL avec le bot token.
        print(f"[alert] envoi Telegram échoué (ignoré) : {type(e).__name__}")
        return False


def _format_line(s: dict) -> str:
    price = s.get("price")
    score = s.get("setup_score", s.get("score"))
    pivot = s.get("pivot_level")
    piv = f" · pivot {pivot}$" if pivot is not None else ""
    return f"• <b>{s.get('ticker')}</b> — score {score}/10 · {price}${piv}"


# ---------------------------------------------------------------------------
# Notification des nouveaux déclenchés
# ---------------------------------------------------------------------------

def notify_new_triggers(candidates: list[dict], *, state_path: Path = ALERT_STATE_FILE,
                        min_score: int | None = None, dedup_days: int | None = None,
                        now: datetime | None = None, send_fn=send_telegram) -> list[str]:
    """
    Notifie les tickers `triggered` avec `setup_score >= min_score` non déjà alertés
    depuis moins de `dedup_days` jours. Retourne la liste des tickers réellement notifiés
    (vide si rien à envoyer OU si l'envoi a échoué / est désactivé).

    L'état anti-doublon n'est mis à jour QUE si l'envoi réussit → un échec réseau (ou
    l'absence de token) laisse le ticker éligible au prochain scan.
    """
    min_score = FILTERS["alert_min_score"] if min_score is None else min_score
    dedup_days = FILTERS["alert_dedup_days"] if dedup_days is None else dedup_days
    now = now or datetime.now(tz=timezone.utc)

    state = _load_state(state_path)
    fresh: list[dict] = []
    for s in candidates:
        if not s.get("fusee_event"):   # Epic 2 : alerte sur le variant ÉVÉNEMENT de Fusée
            continue                    # (membre Fusée + cassure du jour), plus le simple trigger
        if (s.get("setup_score", s.get("score")) or 0) < min_score:
            continue
        tk = s.get("ticker")
        if not tk:
            continue
        last = state.get(tk)
        if last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(days=dedup_days):
                    continue  # déjà notifié récemment
            except (TypeError, ValueError):
                pass  # date d'état corrompue → on ré-alerte
        fresh.append(s)

    if not fresh:
        return []

    text = ("🚀 <b>Fusée — cassure déclenchée</b> ({} nouveau(x))\n".format(len(fresh))
            + "\n".join(_format_line(s) for s in fresh))
    if not send_fn(text):
        return []  # désactivé ou échec → on n'enregistre rien (retry au prochain scan)

    for s in fresh:
        state[s["ticker"]] = now.isoformat()
    _save_state(state_path, state)
    return [s["ticker"] for s in fresh]


# ---------------------------------------------------------------------------
# Notification des nouvelles entrées en cohorte v4 (Epic 4 S3)
# ---------------------------------------------------------------------------

def notify_new_v4_entries(cohort: list[dict], *, state_path: Path = ALERT_STATE_FILE,
                          dedup_days: int | None = None, now: datetime | None = None,
                          send_fn=send_telegram) -> list[str]:
    """
    Notifie les tickers NOUVELLEMENT en cohorte v4 (protocole v4 §2 — la seule liste à
    espérance historique positive). Même anti-doublon persistant que l'alerte cassure
    (préfixe d'état « v4: » pour éviter toute collision avec elle). Le message rappelle
    le statut : recherche statistique en validation forward, pas un conseil.
    """
    dedup_days = FILTERS["alert_dedup_days"] if dedup_days is None else dedup_days
    now = now or datetime.now(tz=timezone.utc)

    state = _load_state(state_path)
    fresh: list[dict] = []
    for e in cohort:
        tk = e.get("ticker")
        if not tk:
            continue
        last = state.get(f"v4:{tk}")
        if last:
            try:
                if now - datetime.fromisoformat(last) < timedelta(days=dedup_days):
                    continue
            except (TypeError, ValueError):
                pass
        fresh.append(e)

    if not fresh:
        return []

    def _line(e: dict) -> str:
        resid = e.get("resid")
        r = f" · résidu {resid:+.1%}" if resid is not None else ""
        return f"• <b>{e.get('ticker')}</b> — {e.get('price')}$ · 1m {e.get('change_1m'):+.1%}{r}"

    text = ("🧪 <b>Cohorte v4 — {} nouvelle(s) entrée(s)</b>\n".format(len(fresh))
            + "\n".join(_line(e) for e in fresh)
            + "\n<i>Recherche statistique en validation forward (t=0,47) — pas un conseil.</i>")
    if not send_fn(text):
        return []

    for e in fresh:
        state[f"v4:{e['ticker']}"] = now.isoformat()
    _save_state(state_path, state)
    return [e["ticker"] for e in fresh]
