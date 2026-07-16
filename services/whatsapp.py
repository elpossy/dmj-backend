"""
services/whatsapp.py
Intégration Meta Cloud API — WhatsApp Business

FLUX OTP (utilisateur-initié) :
  1. generate_otp()           → génère un code 6 chiffres
  2. L'app affiche l'instruction à l'utilisateur
  3. L'utilisateur envoie un message sur WhatsApp
  4. Le webhook (routes/whatsapp_webhook.py) reçoit le message
  5. send_otp_reply()         → envoie le code en réponse
  6. Si pas d'OTP en attente  → send_no_otp_menu()
"""

import requests
import random
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

# ── Clés Meta (à renseigner dans .env) ─────────────────
PHONE_NUMBER_ID   = (os.getenv("WHATSAPP_PHONE_NUMBER_ID")    or "").strip()
ACCESS_TOKEN      = (os.getenv("WHATSAPP_ACCESS_TOKEN")       or "").strip()
VERIFY_TOKEN      = (os.getenv("WHATSAPP_WEBHOOK_VERIFY_TOKEN") or "damundje_webhook_2025").strip()

API_URL = f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages"

HEADERS = {
    "Authorization": f"Bearer {ACCESS_TOKEN}",
    "Content-Type":  "application/json"
}

# ── Mode mock si clés absentes ──────────────────────────
OTP_MODE   = os.getenv("OTP_MODE", "mock").lower()
_MOCK_MODE = (OTP_MODE == "mock")

if _MOCK_MODE:
    logger.info("🧪 WhatsApp en mode MOCK (OTP_MODE=mock dans .env)")
elif not all([PHONE_NUMBER_ID, ACCESS_TOKEN]):
    logger.warning("⚠️  OTP_MODE=whatsapp mais clés Meta manquantes — les envois échoueront")

if _MOCK_MODE:
    logger.warning("⚠️  WhatsApp en mode MOCK (clés manquantes dans .env)")


def generate_otp() -> str:
    """Génère un code OTP à 6 chiffres."""
    return str(random.randint(100000, 999999))


def send_otp(phone: str, code: str) -> bool:
    """
    Appelé depuis /request-otp.
    Mock  → affiche le code dans la console + UI.
    Réel  → envoie DIRECTEMENT le code par WhatsApp (Business-Initiated).
    """
    if _MOCK_MODE:
        print(f"\n{'='*45}")
        print(f"  📱 [MOCK WhatsApp OTP]")
        print(f"  Téléphone : {phone}")
        print(f"  Code      : {code}")
        print(f"{'='*45}\n")
        return True

    # Mode réel — envoi direct sans attendre le webhook
    return _send_direct(phone, code)


def _send_direct(phone: str, code: str) -> bool:
    """
    Envoie le code OTP directement à l'utilisateur
    sans attendre qu'il envoie un message en premier.
    Business-Initiated Message — Meta autorise ça pour l'auth.
    """
    phone_clean = phone.replace("+", "").replace(" ", "")

    body = (
        f"Voici ton code de vérification Damundjé 🔐\n\n"
        f"*{code}*\n\n"
        f"⏳ Valide pendant *15 minutes*.\n"
        f"🔒 Ne le partage avec personne.\n\n"
        f"Si tu n'as pas demandé ce code, ignore ce message."
    )

    payload = {
        "messaging_product": "whatsapp",
        "to":   phone_clean,
        "type": "text",
        "text": {"body": body}
    }

    try:
        res = requests.post(API_URL, headers=HEADERS, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info(f"✅ OTP envoyé directement à {phone}")
            return True
        else:
            logger.error(f"WhatsApp API {res.status_code}: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Erreur réseau WhatsApp: {e}")
        return False


def send_otp_reply(phone: str, code: str, user_name: str = None) -> bool:
    """
    Envoie le code OTP EN RÉPONSE au message de l'utilisateur.
    C'est une conversation initiée par l'utilisateur → 24h gratuites.

    phone : format E.164 sans + (ex: 22796000000)
    """
    if _MOCK_MODE:
        print(f"\n🔐 [MOCK] OTP reply → {phone} : {code}\n")
        return True

    name = user_name or "toi"
    body = (
        f"Bonjour{' ' + name if user_name else ''} 👋\n\n"
        f"Voici ton code de vérification Damundjé :\n\n"
        f"*{code}*\n\n"
        f"⏳ Ce code expire dans *10 minutes*.\n"
        f"🔒 Ne le partage avec personne.\n\n"
        f"Si tu n'as pas demandé ce code, ignore ce message."
    )

    phone_clean = phone.replace("+", "").replace(" ", "")

    payload = {
        "messaging_product": "whatsapp",
        "to":                phone_clean,
        "type":              "text",
        "text":              {"body": body}
    }

    try:
        res = requests.post(API_URL, headers=HEADERS, json=payload, timeout=10)
        if res.status_code == 200:
            logger.info(f"OTP envoyé à {phone}")
            return True
        else:
            logger.error(f"WhatsApp API error {res.status_code}: {res.text}")
            return False
    except Exception as e:
        logger.error(f"Erreur réseau WhatsApp: {e}")
        return False


def send_no_otp_menu(phone: str) -> bool:
    """
    Envoyé quand quelqu'un écrit sur WhatsApp
    mais qu'il n'y a pas d'OTP en attente pour ce numéro.
    Message interactif avec 3 boutons.
    """
    if _MOCK_MODE:
        print(f"\n🤖 [MOCK] Menu interactif → {phone}\n")
        return True

    phone_clean = phone.replace("+", "").replace(" ", "")

    payload = {
        "messaging_product": "whatsapp",
        "to":                phone_clean,
        "type":              "interactive",
        "interactive": {
            "type": "button",
            "body": {
                "text": (
                    "Bonjour 👋 Je ne trouve pas de demande de code "
                    "pour ce numéro.\n\n"
                    "Que souhaites-tu faire ?"
                )
            },
            "action": {
                "buttons": [
                    {
                        "type":  "reply",
                        "reply": {
                            "id":    "RETRY_OTP",
                            "title": "🔄 Réessayer"
                        }
                    },
                    {
                        "type":  "reply",
                        "reply": {
                            "id":    "WRONG_NUMBER",
                            "title": "❓ Mauvais numéro ?"
                        }
                    },
                    {
                        "type":  "reply",
                        "reply": {
                            "id":    "CONTACT_SUPPORT",
                            "title": "💬 Support"
                        }
                    }
                ]
            }
        }
    }

    try:
        res = requests.post(API_URL, headers=HEADERS, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"Erreur envoi menu: {e}")
        return False


def handle_button_reply(phone: str, button_id: str) -> bool:
    """
    Gère les réponses aux boutons du menu interactif.
    """
    phone_clean = phone.replace("+", "").replace(" ", "")

    messages = {
        "RETRY_OTP": (
            "Pour recevoir ton code :\n\n"
            "1️⃣ Ouvre l'app Damundjé\n"
            "2️⃣ Entre ton numéro\n"
            "3️⃣ Clique sur *Recevoir le code*\n"
            "4️⃣ Reviens ici — ton code arrivera automatiquement ✅"
        ),
        "WRONG_NUMBER": (
            "Si tu penses t'être trompé de numéro :\n\n"
            "▪ Vérifie que le numéro entré dans l'app "
            "correspond bien à ce numéro WhatsApp\n"
            "▪ Assure-toi d'utiliser l'indicatif +227 pour le Niger\n\n"
            "Besoin d'aide ? Réponds *support* 🙏"
        ),
        "CONTACT_SUPPORT": (
            "Notre équipe te répond dans les plus brefs délais 🛠️\n\n"
            "📧 support@damundje.ne\n"
            "🌍 Made in Niger avec ❤️"
        )
    }

    text = messages.get(button_id, "Merci de nous avoir contacté 🙏")

    if _MOCK_MODE:
        print(f"\n🤖 [MOCK] Réponse bouton {button_id} → {phone}\n")
        return True

    payload = {
        "messaging_product": "whatsapp",
        "to":   phone_clean,
        "type": "text",
        "text": {"body": text}
    }

    try:
        res = requests.post(API_URL, headers=HEADERS, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        logger.error(f"Erreur réponse bouton: {e}")
        return False
