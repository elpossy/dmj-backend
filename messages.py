from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_
from datetime import datetime, timezone
from typing import List, Optional
from pydantic import BaseModel

from database import get_db
from models import User, Listing
from dependencies import get_current_user

# ── Import des modèles de chat ──────────────────────────
from sqlalchemy import Column, BigInteger, Text, Boolean, Integer, ForeignKey, TIMESTAMP
from sqlalchemy.sql import func
from database import Base

# ── Modèles SQLAlchemy inline ───────────────────────────
class Conversation(Base):
    __tablename__ = "conversations"
    id           = Column(BigInteger, primary_key=True, autoincrement=True)
    listing_id   = Column(BigInteger, ForeignKey("listings.id", ondelete="CASCADE"))
    buyer_id     = Column(BigInteger, ForeignKey("users.id",    ondelete="CASCADE"))
    seller_id    = Column(BigInteger, ForeignKey("users.id",    ondelete="CASCADE"))
    last_message = Column(Text,    nullable=True)
    last_msg_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())
    ttl_days     = Column(Integer, default=3)
    created_at   = Column(TIMESTAMP(timezone=True), server_default=func.now())

class Message(Base):
    __tablename__ = "messages"
    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    conversation_id = Column(BigInteger, ForeignKey("conversations.id", ondelete="CASCADE"))
    sender_id       = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    content         = Column(Text, nullable=False)
    is_read         = Column(Boolean, default=False)
    read_at         = Column(TIMESTAMP(timezone=True), nullable=True)
    ttl_days        = Column(Integer, default=3)
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())


router = APIRouter()

# ── Schemas ─────────────────────────────────────────────
class ConversationOut(BaseModel):
    id:           int
    listing_id:   Optional[int]
    buyer_id:     int
    seller_id:    int
    last_message: Optional[str]
    last_msg_at:  Optional[datetime]
    ttl_days:     int
    created_at:   datetime
    # Champs enrichis (remplis manuellement)
    other_user_name:   Optional[str] = None
    other_user_phone:  Optional[str] = None
    listing_title:     Optional[str] = None
    listing_photo:     Optional[str] = None
    unread_count:      int           = 0

    class Config:
        from_attributes = True

class MessageOut(BaseModel):
    id:              int
    conversation_id: int
    sender_id:       Optional[int]
    content:         str
    is_read:         bool
    read_at:         Optional[datetime]
    ttl_days:        int
    created_at:      datetime
    expires_at:      Optional[datetime] = None   # calculé à la volée

    class Config:
        from_attributes = True

class SendMessageIn(BaseModel):
    content: str
    ttl_days: int = 3   # 1 à 7 jours

class UpdateTTLIn(BaseModel):
    ttl_days: int   # 1 à 7


# ════════════════════════════════════════════════════════
#  DÉMARRER OU RÉCUPÉRER UNE CONVERSATION
# ════════════════════════════════════════════════════════
@router.post("/start", summary="Démarrer une conversation sur une annonce")
def start_conversation(
    listing_id: int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    """
    L'acheteur clique "Contacter" → on crée la conversation
    ou on retourne celle qui existe déjà.
    UNIQUE(listing_id, buyer_id) garantit l'unicité.
    """
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(404, "Annonce introuvable")

    # Empêche le vendeur de se contacter lui-même
    if listing.seller_id == current_user.id:
        raise HTTPException(400, "Tu ne peux pas te contacter toi-même")

    # Cherche si la conversation existe déjà
    conv = db.query(Conversation).filter(
        Conversation.listing_id == listing_id,
        Conversation.buyer_id   == current_user.id
    ).first()

    if not conv:
        conv = Conversation(
            listing_id = listing_id,
            buyer_id   = current_user.id,
            seller_id  = listing.seller_id,
            ttl_days   = 3
        )
        db.add(conv)
        db.commit()
        db.refresh(conv)

    return {"conversation_id": conv.id, "is_new": conv.last_message is None}


# ════════════════════════════════════════════════════════
#  MES CONVERSATIONS
# ════════════════════════════════════════════════════════
@router.get("/", summary="Toutes mes conversations")
def get_conversations(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    convs = db.query(Conversation).filter(
        or_(
            Conversation.buyer_id  == current_user.id,
            Conversation.seller_id == current_user.id
        )
    ).order_by(Conversation.last_msg_at.desc()).all()

    result = []
    for conv in convs:
        # Identifie l'autre utilisateur
        other_id = conv.seller_id if conv.buyer_id == current_user.id else conv.buyer_id
        other    = db.query(User).filter(User.id == other_id).first()

        # Infos de l'annonce
        listing = db.query(Listing).filter(Listing.id == conv.listing_id).first()

        # Compte les messages non lus
        unread = db.query(Message).filter(
            Message.conversation_id == conv.id,
            Message.sender_id       != current_user.id,
            Message.is_read         == False
        ).count()

        result.append({
            "id":               conv.id,
            "listing_id":       conv.listing_id,
            "buyer_id":         conv.buyer_id,
            "seller_id":        conv.seller_id,
            "last_message":     conv.last_message,
            "last_msg_at":      conv.last_msg_at,
            "ttl_days":         conv.ttl_days,
            "created_at":       conv.created_at,
            "other_user_name":  other.name  if other  else "Utilisateur",
            "other_user_phone": other.phone if other  else None,
            "listing_title":    listing.title              if listing else None,
            "listing_photo":    (listing.photos or [None])[0] if listing else None,
            "unread_count":     unread,
        })

    return result


# ════════════════════════════════════════════════════════
#  MESSAGES D'UNE CONVERSATION
# ════════════════════════════════════════════════════════
@router.get("/{conv_id}/messages", summary="Messages d'une conversation")
def get_messages(
    conv_id:      int,
    skip:         int     = Query(0, ge=0),
    limit:        int     = Query(50, ge=1, le=100),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    conv = _get_conv_or_403(conv_id, current_user.id, db)

    messages = db.query(Message).filter(
        Message.conversation_id == conv_id
    ).order_by(Message.created_at.asc()).offset(skip).limit(limit).all()

    # Marque comme lus les messages reçus
    for msg in messages:
        if msg.sender_id != current_user.id and not msg.is_read:
            msg.is_read = True
            msg.read_at = datetime.now(timezone.utc)
    db.commit()

    result = []
    for msg in messages:
        expires_at = None
        if msg.is_read and msg.read_at:
            from datetime import timedelta
            expires_at = msg.read_at + timedelta(days=msg.ttl_days)

        result.append({
            "id":              msg.id,
            "conversation_id": msg.conversation_id,
            "sender_id":       msg.sender_id,
            "content":         msg.content,
            "is_read":         msg.is_read,
            "read_at":         msg.read_at,
            "ttl_days":        msg.ttl_days,
            "created_at":      msg.created_at,
            "expires_at":      expires_at,
            "is_mine":         msg.sender_id == current_user.id,
        })

    return result


# ════════════════════════════════════════════════════════
#  ENVOYER UN MESSAGE
# ════════════════════════════════════════════════════════
@router.post("/{conv_id}/messages", summary="Envoyer un message")
def send_message(
    conv_id:      int,
    payload:      SendMessageIn,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    conv = _get_conv_or_403(conv_id, current_user.id, db)

    # Validation TTL
    ttl = max(1, min(7, payload.ttl_days))

    if not payload.content.strip():
        raise HTTPException(400, "Le message ne peut pas être vide")

    msg = Message(
        conversation_id = conv_id,
        sender_id       = current_user.id,
        content         = payload.content.strip(),
        ttl_days        = ttl,
        is_read         = False
    )
    db.add(msg)

    # Met à jour le dernier message de la conversation
    preview = payload.content[:60] + ("..." if len(payload.content) > 60 else "")
    conv.last_message = preview
    conv.last_msg_at  = datetime.now(timezone.utc)

    db.commit()
    db.refresh(msg)

    return {
        "id":         msg.id,
        "content":    msg.content,
        "sender_id":  msg.sender_id,
        "is_read":    msg.is_read,
        "ttl_days":   msg.ttl_days,
        "created_at": msg.created_at,
        "is_mine":    True,
    }


# ════════════════════════════════════════════════════════
#  MARQUER UN MESSAGE COMME LU
# ════════════════════════════════════════════════════════
@router.patch("/{conv_id}/messages/{msg_id}/read", summary="Marquer comme lu")
def mark_as_read(
    conv_id:      int,
    msg_id:       int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    _get_conv_or_403(conv_id, current_user.id, db)

    msg = db.query(Message).filter(
        Message.id              == msg_id,
        Message.conversation_id == conv_id
    ).first()

    if not msg:
        raise HTTPException(404, "Message introuvable")

    if msg.sender_id == current_user.id:
        raise HTTPException(400, "Tu ne peux pas marquer ton propre message comme lu")

    if not msg.is_read:
        msg.is_read = True
        msg.read_at = datetime.now(timezone.utc)
        db.commit()

    from datetime import timedelta
    return {
        "message_id": msg.id,
        "read_at":    msg.read_at,
        "expires_at": msg.read_at + timedelta(days=msg.ttl_days)
    }


# ════════════════════════════════════════════════════════
#  MODIFIER LE TTL D'UNE CONVERSATION
# ════════════════════════════════════════════════════════
@router.patch("/{conv_id}/ttl", summary="Modifier la durée de conservation")
def update_ttl(
    conv_id:      int,
    payload:      UpdateTTLIn,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    """
    L'utilisateur choisit entre 1 et 7 jours.
    Par défaut : 3 jours après lecture.
    Si non lu : message conservé indéfiniment.
    """
    conv = _get_conv_or_403(conv_id, current_user.id, db)

    ttl = max(1, min(7, payload.ttl_days))
    conv.ttl_days = ttl
    db.commit()

    return {"conversation_id": conv_id, "ttl_days": ttl,
            "message": f"Messages supprimés {ttl} jour(s) après lecture"}


# ════════════════════════════════════════════════════════
#  SUPPRIMER UNE CONVERSATION
# ════════════════════════════════════════════════════════
@router.delete("/{conv_id}", summary="Supprimer une conversation")
def delete_conversation(
    conv_id:      int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    conv = _get_conv_or_403(conv_id, current_user.id, db)
    db.delete(conv)
    db.commit()
    return {"message": "Conversation supprimée"}


# ════════════════════════════════════════════════════════
#  NETTOYAGE MANUEL DES MESSAGES EXPIRÉS
# ════════════════════════════════════════════════════════
@router.post("/cleanup", summary="Nettoyer les messages expirés")
def cleanup_expired(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    """
    Supprime les messages lus depuis plus de ttl_days jours.
    Les messages non lus ne sont jamais supprimés.
    """
    from datetime import timedelta
    from sqlalchemy import text

    deleted = db.execute(text("""
        DELETE FROM messages
        WHERE is_read = TRUE
          AND read_at IS NOT NULL
          AND read_at + (ttl_days || ' days')::INTERVAL < NOW()
        RETURNING id
    """)).rowcount
    db.commit()

    return {"deleted_count": deleted, "message": f"{deleted} message(s) supprimé(s)"}


# ════════════════════════════════════════════════════════
#  HELPER — vérifie l'accès à la conversation
# ════════════════════════════════════════════════════════
def _get_conv_or_403(conv_id: int, user_id: int, db: Session) -> Conversation:
    conv = db.query(Conversation).filter(Conversation.id == conv_id).first()
    if not conv:
        raise HTTPException(404, "Conversation introuvable")
    if conv.buyer_id != user_id and conv.seller_id != user_id:
        raise HTTPException(403, "Accès non autorisé à cette conversation")
    return conv
