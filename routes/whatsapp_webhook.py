"""
routes/whatsapp_webhook.py

Deux routes :
  GET  /api/whatsapp/webhook  → vérification par Meta (une seule fois)
  POST /api/whatsapp/webhook  → réception des messages entrants
"""

from fastapi import APIRouter, Request, HTTPException, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, timezone
import logging
import hmac
import hashlib
import os

from database import get_db
from models import OTPCode, User
from services.whatsapp import (
    send_otp_reply,
    send_no_otp_menu,
    handle_button_reply,
    VERIFY_TOKEN,
    _MOCK_MODE
)

router  = APIRouter()
logger  = logging.getLogger(__name__)

APP_SECRET = (os.getenv("WHATSAPP_APP_SECRET") or "").strip()


# ════════════════════════════════════════════════════════
#  GET — Vérification du webhook par Meta
#  Meta appelle cette URL une seule fois pour confirmer
#  que le serveur est bien le nôtre
# ════════════════════════════════════════════════════════
@router.get("/webhook", summary="Vérification webhook Meta")
def verify_webhook(
    hub_mode:         str = Query(None, alias="hub.mode"),
    hub_challenge:    str = Query(None, alias="hub.challenge"),
    hub_verify_token: str = Query(None, alias="hub.verify_token"),
):
    """
    Meta envoie :
      ?hub.mode=subscribe
      &hub.challenge=XXXXX   ← nombre aléatoire à renvoyer tel quel
      &hub.verify_token=TON_TOKEN

    Si hub.verify_token correspond au nôtre → on renvoie hub.challenge
    Sinon → 403
    """
    if hub_mode == "subscribe" and hub_verify_token == VERIFY_TOKEN:
        logger.info("✅ Webhook WhatsApp vérifié par Meta")
        return int(hub_challenge)

    logger.warning(f"❌ Tentative de vérification échouée : token={hub_verify_token}")
    raise HTTPException(403, "Token de vérification invalide")


# ════════════════════════════════════════════════════════
#  POST — Réception des messages entrants
# ════════════════════════════════════════════════════════
@router.post("/webhook", summary="Webhook messages entrants WhatsApp")
async def receive_webhook(
    request: Request,
    db:      Session = Depends(get_db)
):
    """
    Meta envoie ici chaque message reçu sur notre numéro WhatsApp.

    Structure du payload Meta :
    {
      "object": "whatsapp_business_account",
      "entry": [{
        "changes": [{
          "value": {
            "messages": [{
              "from": "22796000000",
              "type": "text",
              "text": {"body": "Damundjé"}
            }]
          }
        }]
      }]
    }
    """

    body = await request.json()

    # ── Vérification signature (sécurité) ───────────────
    if APP_SECRET and not _MOCK_MODE:
        signature = request.headers.get("x-hub-signature-256", "")
        raw_body  = await request.body()
        expected  = "sha256=" + hmac.new(
            APP_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            logger.warning("❌ Signature webhook invalide")
            raise HTTPException(403, "Signature invalide")

    # ── Extraction du message ────────────────────────────
    try:
        entry   = body["entry"][0]
        change  = entry["changes"][0]["value"]
        messages = change.get("messages", [])

        if not messages:
            # Peut être un statut de livraison ou de lecture
            return {"status": "ok"}

        msg        = messages[0]
        from_phone = "+" + msg["from"]   # ex: +22796000000
        msg_type   = msg.get("type", "")

        logger.info(f"Message reçu de {from_phone} — type: {msg_type}")

        # ── Réponse à un bouton interactif ───────────────
        if msg_type == "interactive":
            button_id = (
                msg.get("interactive", {})
                   .get("button_reply", {})
                   .get("id", "")
            )
            if button_id:
                handle_button_reply(from_phone, button_id)
            return {"status": "ok"}

        # ── Message texte ────────────────────────────────
        if msg_type != "text":
            return {"status": "ok"}

        text_body = msg.get("text", {}).get("body", "").strip()

        # ── Cherche un OTP en attente pour ce numéro ─────
        otp = db.query(OTPCode).filter(
            OTPCode.phone == from_phone,
            OTPCode.used  == False
        ).order_by(OTPCode.created_at.desc()).first()

        if not otp:
            # Aucun OTP en attente → menu explicatif
            logger.info(f"Aucun OTP en attente pour {from_phone}")
            send_no_otp_menu(from_phone)
            return {"status": "ok"}

        # ── OTP expiré ────────────────────────────────────
        if otp.expires_at < datetime.now(timezone.utc):
            otp.used = True
            db.commit()

            # Récupère le vrai code depuis la DB n'est pas possible
            # (stocké hashé) → on envoie un message d'expiration
            _send_expired_message(from_phone)
            return {"status": "ok"}

        # ── OTP valide — récupère le code en clair ────────
        # Le code en clair n'est pas stocké (hashé en DB)
        # On doit le régénérer ET mettre à jour le hash
        from routes.auth import _hash_code
        from services.whatsapp import generate_otp

        new_code        = generate_otp()
        otp.code        = _hash_code(new_code)
        otp.expires_at  = datetime.now(timezone.utc) + __import__('datetime').timedelta(minutes=10)
        db.commit()

        # Récupère le prénom de l'utilisateur si inscrit
        user = db.query(User).filter(User.phone == from_phone).first()
        name = user.name if user else None

        # Envoie le code en réponse
        sent = send_otp_reply(from_phone, new_code, name)

        if sent:
            logger.info(f"✅ OTP envoyé à {from_phone}")
        else:
            logger.error(f"❌ Échec envoi OTP à {from_phone}")

    except (KeyError, IndexError) as e:
        # Meta envoie parfois des payloads vides (notifications de statut)
        logger.debug(f"Payload webhook ignoré : {e}")

    return {"status": "ok"}


# ════════════════════════════════════════════════════════
#  HELPER — message d'expiration
# ════════════════════════════════════════════════════════
def _send_expired_message(phone: str):
    """Informe l'utilisateur que son code a expiré."""
    from services.whatsapp import PHONE_NUMBER_ID, ACCESS_TOKEN, _MOCK_MODE
    import requests

    if _MOCK_MODE:
        print(f"[MOCK] Code expiré → {phone}")
        return

    phone_clean = phone.replace("+", "")
    payload = {
        "messaging_product": "whatsapp",
        "to":   phone_clean,
        "type": "text",
        "text": {
            "body": (
                "⏰ Ton code de vérification a expiré.\n\n"
                "Retourne sur l'app Damundjé et clique sur "
                "*Renvoyer le code* pour en recevoir un nouveau. 🔄"
            )
        }
    }

    try:
        requests.post(
            f"https://graph.facebook.com/v19.0/{PHONE_NUMBER_ID}/messages",
            headers={"Authorization": f"Bearer {ACCESS_TOKEN}", "Content-Type": "application/json"},
            json=payload,
            timeout=10
        )
    except Exception as e:
        logger.error(f"Erreur message expiration: {e}")
