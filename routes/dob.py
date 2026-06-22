from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import Column, BigInteger, Integer, Boolean, Text, ForeignKey, TIMESTAMP
from sqlalchemy.sql import func
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
import math

from database import Base, get_db
from models import User
from dependencies import get_current_user

router = APIRouter()


# ── Modèles SQLAlchemy ──────────────────────────────────
class DOBTransaction(Base):
    __tablename__ = "dob_transactions"
    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id    = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"))
    amount     = Column(Integer, nullable=False)
    reason     = Column(Text,    nullable=False)
    listing_id = Column(BigInteger, ForeignKey("listings.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())

class DOBPackage(Base):
    __tablename__ = "dob_packages"
    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    dob_amount   = Column(Integer, nullable=False)
    price_fcfa   = Column(Integer, nullable=False)
    is_available = Column(Boolean, default=False)
    is_free_now  = Column(Boolean, default=False)
    created_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())


# ── Formule de calcul ───────────────────────────────────
def calculate_dob_cost(photo_count: int = 0, video_count: int = 0) -> dict:
    """
    Base : 3 DOB par annonce
    Photos > 5 : 1 DOB par tranche de 5 franchie
      - 1-5  photos → 0 DOB extra
      - 6-10 photos → 1 DOB extra  (frontière de 5 franchie)
      - 11-15→ 2 DOB extra          (frontière de 10 franchie)
    Vidéos : 1 DOB chacune
    """
    base        = 3
    photo_extra = max(0, math.ceil(photo_count / 5) - 1) if photo_count > 0 else 0
    video_cost  = video_count
    total       = base + photo_extra + video_cost

    return {
        "base":        base,
        "photo_extra": photo_extra,
        "video_cost":  video_cost,
        "total":       total,
    }


# ════════════════════════════════════════════════════════
#  SOLDE & HISTORIQUE
# ════════════════════════════════════════════════════════
@router.get("/balance", summary="Mon solde DOB")
def get_balance(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    # Dernier historique
    history = db.query(DOBTransaction).filter(
        DOBTransaction.user_id == current_user.id
    ).order_by(DOBTransaction.created_at.desc()).limit(20).all()

    return {
        "balance": current_user.dob_balance or 0,
        "history": [
            {
                "id":         t.id,
                "amount":     t.amount,
                "reason":     t.reason,
                "created_at": t.created_at,
            }
            for t in history
        ]
    }


# ════════════════════════════════════════════════════════
#  CALCULER LE COÛT AVANT PUBLICATION
# ════════════════════════════════════════════════════════
@router.get("/calculate", summary="Calculer le coût DOB d'une annonce")
def calculate_cost(
    photo_count: int = 0,
    video_count: int = 0,
    db:          Session = Depends(get_db),
    current_user: User   = Depends(get_current_user)
):
    cost = calculate_dob_cost(photo_count, video_count)
    cost["can_afford"]  = (current_user.dob_balance or 0) >= cost["total"]
    cost["balance"]     = current_user.dob_balance or 0
    cost["missing"]     = max(0, cost["total"] - (current_user.dob_balance or 0))
    return cost


# ════════════════════════════════════════════════════════
#  PACKS DISPONIBLES
# ════════════════════════════════════════════════════════
@router.get("/packages", summary="Packs DOB disponibles")
def get_packages(db: Session = Depends(get_db)):
    packages = db.query(DOBPackage).order_by(DOBPackage.dob_amount).all()
    return [
        {
            "id":           p.id,
            "dob_amount":   p.dob_amount,
            "price_fcfa":   p.price_fcfa,
            "is_available": p.is_available,
            "is_free_now":  p.is_free_now,
        }
        for p in packages
    ]


# ════════════════════════════════════════════════════════
#  ACHETER UN PACK (gratuit pendant maintenance)
# ════════════════════════════════════════════════════════
@router.post("/purchase/{package_id}", summary="Acheter un pack DOB")
def purchase_package(
    package_id:   int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    pkg = db.query(DOBPackage).filter(DOBPackage.id == package_id).first()

    if not pkg:
        raise HTTPException(404, "Pack introuvable")

    # Pack pas encore disponible
    if not pkg.is_available:
        raise HTTPException(400,
            f"Ce pack n'est pas encore disponible. "
            f"Essaie avec 7 DOB ou 20 DOB pour l'instant 🎁"
        )

    # Crédit gratuit pendant maintenance
    if pkg.is_free_now:
        _credit_dob(
            db          = db,
            user        = current_user,
            amount      = pkg.dob_amount,
            reason      = f"purchase_free:{pkg.dob_amount}dob"
        )

        return {
            "success":   True,
            "dob_added": pkg.dob_amount,
            "balance":   current_user.dob_balance,
            "message":   (
                f"🎁 +{pkg.dob_amount} DOB ajoutés ! "
                f"Le paiement est en maintenance, c'est notre cadeau. "
                f"Ton solde : {current_user.dob_balance} DOB"
            )
        }

    # Paiement réel (à implémenter avec CinetPay)
    raise HTTPException(503,
        "Le paiement en ligne arrive bientôt. "
        "Choisis un pack gratuit pour l'instant 🎁"
    )


# ════════════════════════════════════════════════════════
#  BONUS ACTIONS
# ════════════════════════════════════════════════════════
@router.post("/bonus/profile-complete", summary="Bonus profil complet")
def bonus_profile(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    """
    +5 DOB quand l'utilisateur complète son profil (nom + ville + avatar).
    Une seule fois.
    """
    already = db.query(DOBTransaction).filter(
        DOBTransaction.user_id == current_user.id,
        DOBTransaction.reason  == "bonus_profile_complete"
    ).first()

    if already:
        raise HTTPException(400, "Bonus déjà reçu")

    if not (current_user.name and current_user.city):
        raise HTTPException(400, "Complete ton profil d'abord (nom + ville)")

    _credit_dob(db, current_user, 5, "bonus_profile_complete")
    return {"dob_added": 5, "balance": current_user.dob_balance,
            "message": "🎉 +5 DOB pour profil complet !"}


# ════════════════════════════════════════════════════════
#  HELPER INTERNE — crédite / débite des DOB
# ════════════════════════════════════════════════════════
def _credit_dob(db: Session, user: User, amount: int, reason: str, listing_id: int = None):
    """Ajoute des DOB au solde et enregistre la transaction."""
    user.dob_balance = (user.dob_balance or 0) + amount
    tx = DOBTransaction(
        user_id    = user.id,
        amount     = amount,
        reason     = reason,
        listing_id = listing_id
    )
    db.add(tx)
    db.commit()


def _debit_dob(db: Session, user: User, amount: int, reason: str, listing_id: int = None):
    """Retire des DOB. Lève une exception si solde insuffisant."""
    if (user.dob_balance or 0) < amount:
        raise HTTPException(
            402,
            f"Solde insuffisant. Tu as {user.dob_balance} DOB, "
            f"il en faut {amount}. Achète des DOB pour continuer."
        )
    user.dob_balance = (user.dob_balance or 0) - amount
    tx = DOBTransaction(
        user_id    = user.id,
        amount     = -amount,
        reason     = reason,
        listing_id = listing_id
    )
    db.add(tx)
    db.commit()
