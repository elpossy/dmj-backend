from fastapi import Depends, HTTPException, Header
from sqlalchemy.orm import Session
from datetime import datetime, timezone
from database import get_db
from models import Session as DBSession, User


def get_current_user(
    authorization: str = Header(..., description="Bearer TON_TOKEN"),
    db: Session = Depends(get_db)
) -> User:
    """
    Dépendance injectée dans toutes les routes protégées.

    Le frontend envoie : Authorization: Bearer <token>
    On vérifie : le token existe, n'est pas expiré,
                 et l'utilisateur n'est pas banni.
    """

    # ① Extraire le token du header "Bearer <token>"
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Format du token invalide")

    token = authorization.split(" ", 1)[1]

    # ② Chercher la session en DB
    session = db.query(DBSession).filter(DBSession.token == token).first()

    if not session:
        raise HTTPException(status_code=401, detail="Token invalide")

    # ③ Vérifier l'expiration
    if session.expires_at < datetime.now(timezone.utc):
        raise HTTPException(status_code=401, detail="Session expirée, reconnecte-toi")

    # ④ Charger l'utilisateur
    user = db.query(User).filter(User.id == session.user_id).first()

    if not user:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")

    if user.is_banned:
        raise HTTPException(status_code=403, detail="Compte suspendu")

    return user