"""
Envoi Telegram — seul reste des alertes du screener après la refonte de l'Epic 15
(Sprint 2) ; l'alerte post-résultats (Sprint 4) l'appellera.

Secrets via variables d'environnement UNIQUEMENT (jamais en dur) :
  - TELEGRAM_BOT_TOKEN
  - TELEGRAM_CHAT_ID
Sans token/chat_id configurés, l'envoi est silencieusement désactivé.
"""

import os

import requests


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
