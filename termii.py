"""
services/termii.py
Intégration Termii — Envoi OTP par SMS
"""

import requests
import random
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

TERMII_API_KEY   = (os.getenv("TERMII_API_KEY") or "").strip()
TERMII_SENDER_ID = (os.getenv("TERMII_SENDER_ID") or "Damundje").strip()
TERMII_API_URL   = "https://api.ng.termii.com/api/sms/send"

# ── OTP_MODE = "debug" (mock) ou "production" (envoi réel) ──
OTP_MODE   = os.getenv("OTP_MODE", "debug").lower()
_MOCK_MODE = (OTP_MODE == "debug")

if _MOCK_MODE:
    logger.info("🧪 Termii en mode DEBUG (OTP_MODE=debug dans .env)")
elif not TERMII_API_KEY:
    logger.warning("⚠️  OTP_MODE=production mais TERMII_API_KEY manquante")


def generate_otp() -> str:
    return str(random.randint(100000, 999999))


def send_otp(phone: str, code: str) -> bool:
    if _MOCK_MODE:
        print(f"\n{'='*45}")
        print(f"  📱 [DEBUG Termii OTP]")
        print(f"  Téléphone : {phone}")
        print(f"  Code      : {code}")
        print(f"{'='*45}\n")
        return True

    payload = {
        "to": phone,
        "from": TERMII_SENDER_ID,
        "sms": f"Ton code de vérification Damundjé est : {code}. Valide 15 minutes. Ne le partage avec personne.",
        "type": "plain",
        "channel": "generic",
        "api_key": TERMII_API_KEY,
    }

    try:
        res = requests.post(TERMII_API_URL, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info(f"✅ OTP envoyé via Termii à {phone}")
            return True
        logger.error(f"Termii API {res.status_code}: {res.text}")
        return False
    except Exception as e:
        logger.error(f"Erreur réseau Termii: {e}")
        return False