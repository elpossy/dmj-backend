from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from typing import List

from database import get_db
from models import Listing, UserEvent, User
from schemas import ListingPublic
from dependencies import get_current_user

router = APIRouter()


@router.get("/", response_model=List[ListingPublic], summary="Annonces recommandées")
def get_recommendations(
    limit:        int     = Query(10, ge=1, le=50),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    """
    ML Niveau 1 — Scoring basé sur l'historique de l'utilisateur.

    Logique :
    1. Récupère les catégories que l'utilisateur consulte le plus
    2. Retourne les annonces actives de ces catégories
       triées par popularité (vues + favoris)
    3. Exclut les annonces déjà vues par l'utilisateur
    """

    # Annonces déjà vues par cet utilisateur
    seen_ids = db.query(UserEvent.listing_id).filter(
        UserEvent.user_id    == current_user.id,
        UserEvent.event_type == "view",
        UserEvent.listing_id != None
    ).subquery()

    # Catégories préférées (les plus consultées)
    top_categories = db.query(
        Listing.category_id,
        func.count(UserEvent.id).label("event_count")
    ).join(
        UserEvent, UserEvent.listing_id == Listing.id
    ).filter(
        UserEvent.user_id == current_user.id
    ).group_by(
        Listing.category_id
    ).order_by(
        func.count(UserEvent.id).desc()
    ).limit(3).all()

    category_ids = [row.category_id for row in top_categories if row.category_id]

    # Si l'utilisateur n'a pas d'historique → annonces populaires générales
    if not category_ids:
        return db.query(Listing).filter(
            Listing.status == "active"
        ).order_by(
            (Listing.views + Listing.favorites_count * 3).desc()
        ).limit(limit).all()

    # Annonces recommandées dans les catégories préférées
    recommendations = db.query(Listing).filter(
        Listing.status      == "active",
        Listing.category_id.in_(category_ids),
        Listing.id.not_in(seen_ids)
    ).order_by(
        # Score = vues + favoris pondérés (un favori vaut 3x une vue)
        (Listing.views + Listing.favorites_count * 3).desc()
    ).limit(limit).all()

    return recommendations


@router.post("/event", summary="Enregistrer une interaction utilisateur")
def record_event(
    listing_id:  int,
    event_type:  str,
    query:       str    = None,
    duration_s:  int    = None,
    db:          Session = Depends(get_db),
    current_user: User  = Depends(get_current_user)
):
    """
    Enregistre une interaction (vue, contact, favori, recherche).
    Appelé automatiquement par le frontend à chaque action.
    C'est ce qui alimente le moteur ML.
    """
    allowed = {"view", "contact", "favorite", "search", "purchase"}
    if event_type not in allowed:
        return {"message": "Type d'événement ignoré"}

    event = UserEvent(
        user_id    = current_user.id,
        listing_id = listing_id,
        event_type = event_type,
        query      = query,
        duration_s = duration_s
    )
    db.add(event)
    db.commit()
    return {"message": "Événement enregistré"}