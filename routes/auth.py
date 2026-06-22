from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from datetime import datetime, timedelta, timezone
import secrets
import hashlib
import hmac
import os

from database import get_db
from models import User, OTPCode, Session as DBSession
from schemas import PhoneRequest, OTPVerifyRequest, TokenResponse
from services.whatsapp import send_otp, generate_otp

router = APIRouter()

OTP_EXPIRE_MINUTES = 15
SESSION_EXPIRE_DAYS = 60
MAX_OTP_ATTEMPTS    = 3

_SECRET = os.getenv("SECRET_KEY", "changeme").encode()

def _hash_code(code: str) -> str:
    return hmac.new(_SECRET, code.encode(), hashlib.sha256).hexdigest()

def _check_code(plain: str, hashed: str) -> bool:
    return hmac.compare_digest(_hash_code(plain), hashed)


@router.post("/request-otp", summary="Envoyer un code OTP sur WhatsApp")
def request_otp(payload: PhoneRequest, db: Session = Depends(get_db)):
    db.query(OTPCode).filter(
        OTPCode.phone == payload.phone,
        OTPCode.used  == False
    ).update({"used": True})
    db.commit()

    code        = generate_otp()
    hashed_code = _hash_code(code)

    otp = OTPCode(
        phone      = payload.phone,
        code       = hashed_code,
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=OTP_EXPIRE_MINUTES),
        used       = False,
        attempts   = 0
    )
    db.add(otp)
    db.commit()

    sent = send_otp(payload.phone, code)
    if not sent:
        raise HTTPException(503, "Échec d'envoi WhatsApp")

    from services.whatsapp import OTP_MODE as otp_mode

    result = {
        "message": f"Code envoyé ({OTP_EXPIRE_MINUTES} min)",
    }

    # Mode mock : retourne le code pour l'afficher dans l'UI
    if otp_mode == "mock":
        result["dev_code"] = code  # ← visible dans l'UI pour développement

    # Mode WhatsApp : le code ne sera envoyé que via webhook
    # (l'utilisateur doit d'abord envoyer un message)

    result["otp_mode"] = otp_mode
    return result


@router.post("/verify-otp", response_model=TokenResponse)
def verify_otp_route(payload: OTPVerifyRequest, db: Session = Depends(get_db)):
    otp = db.query(OTPCode).filter(
        OTPCode.phone == payload.phone,
        OTPCode.used  == False
    ).order_by(OTPCode.created_at.desc()).first()

    if not otp:
        raise HTTPException(400, "Aucun code en attente pour ce numéro")

    if otp.attempts >= MAX_OTP_ATTEMPTS:
        otp.used = True
        db.commit()
        raise HTTPException(429, "Trop de tentatives. Demande un nouveau code")

    if otp.expires_at < datetime.now(timezone.utc):
        otp.used = True
        db.commit()
        raise HTTPException(400, "Code expiré. Demande un nouveau code")

    if not _check_code(payload.code, otp.code):
        otp.attempts += 1
        db.commit()
        remaining = MAX_OTP_ATTEMPTS - otp.attempts
        raise HTTPException(400, f"Code incorrect. {remaining} tentative(s) restante(s)")

    otp.used = True
    db.commit()

    is_new_user = False
    user = db.query(User).filter(User.phone == payload.phone).first()

    if not user:
        # 14 DOB offerts à l'inscription
        user = User(phone=payload.phone, dob_balance=14)
        db.add(user)
        db.commit()
        db.refresh(user)
        is_new_user = True

        # Enregistre la transaction bonus signup
        from routes.dob import DOBTransaction
        tx = DOBTransaction(user_id=user.id, amount=14, reason="signup_bonus")
        db.add(tx)
        db.commit()

    user.last_seen_at = datetime.now(timezone.utc)
    db.commit()

    token   = secrets.token_urlsafe(32)
    session = DBSession(
        user_id    = user.id,
        token      = token,
        expires_at = datetime.now(timezone.utc) + timedelta(days=SESSION_EXPIRE_DAYS)
    )
    db.add(session)
    db.commit()

    return TokenResponse(token=token, user_id=user.id, name=user.name, is_new_user=is_new_user)
