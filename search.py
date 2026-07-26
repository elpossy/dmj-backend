from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, or_, cast
from sqlalchemy.dialects.postgresql import TSVECTOR
from typing import Optional, List

from database import get_db
from models import Listing, UserEvent
from schemas import ListingPublic
from dependencies import get_current_user
from models import User

router = APIRouter()


@router.get("/", response_model=List[ListingPublic], summary="Recherche d'annonces")
def search_listings(
    q:           Optional[str]   = Query(None, description="Texte libre : titre ou description"),
    min_price:   Optional[float] = Query(None, ge=0),
    max_price:   Optional[float] = Query(None, ge=0),
    category_id: Optional[int]   = Query(None),
    city:        Optional[str]   = Query(None),
    condition:   Optional[str]   = Query(None),
    sort_by:     str             = Query("recent", enum=["recent", "price_asc", "price_desc", "popular"]),
    skip:        int             = Query(0, ge=0),
    limit:       int             = Query(20, ge=1, le=100),
    db:          Session         = Depends(get_db)
):
    """
    Recherche full-text + filtres combinables.

    - q          : recherche dans titre ET description (full-text PostgreSQL)
    - min_price  : prix minimum
    - max_price  : prix maximum
    - category_id: filtrer par catégorie
    - city       : filtrer par ville (recherche partielle)
    - condition  : new / like_new / good / used / damaged
    - sort_by    : recent | price_asc | price_desc | popular
    """

    query = db.query(Listing).filter(Listing.status == "active")

    # ── Recherche textuelle full-text (pg_trgm + tsvector) ──
    if q:
        # On utilise le vecteur pré-calculé par le trigger Supabase
        ts_query = func.plainto_tsquery("french", q)
        query = query.filter(
            or_(
                Listing.search_vector.op("@@")(ts_query),
                # Fallback : similarité floue sur le titre (pg_trgm)
                func.similarity(Listing.title, q) > 0.15
            )
        )

    # ── Filtres de prix ──
    if min_price is not None:
        query = query.filter(Listing.price >= min_price)
    if max_price is not None:
        query = query.filter(Listing.price <= max_price)

    # ── Autres filtres ──
    if category_id:
        query = query.filter(Listing.category_id == category_id)
    if city:
        query = query.filter(Listing.city.ilike(f"%{city}%"))
    if condition:
        query = query.filter(Listing.condition == condition)

    # ── Tri ──
    if sort_by == "recent":
        query = query.order_by(Listing.created_at.desc())
    elif sort_by == "price_asc":
        query = query.order_by(Listing.price.asc())
    elif sort_by == "price_desc":
        query = query.order_by(Listing.price.desc())
    elif sort_by == "popular":
        query = query.order_by(Listing.views.desc())

    results = query.offset(skip).limit(limit).all()
    return results
