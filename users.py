from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from typing import List

from database import get_db
from models import User, Listing, Review
from schemas import UserPublic, UserUpdate, ReviewCreate, ListingPublic
from dependencies import get_current_user
from services.cloudinary_service import upload_avatar

router = APIRouter()

ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp"}
MAX_AVATAR_SIZE      = 5 * 1024 * 1024  # 5 Mo

@router.post("/me/avatar", response_model=UserPublic, summary="Changer ma photo de profil")
async def update_avatar(
    file:         UploadFile = File(...),
    db:           Session    = Depends(get_db),
    current_user: User       = Depends(get_current_user)
):
    if file.content_type not in ALLOWED_AVATAR_TYPES:
        raise HTTPException(400, f"Format non supporté : {file.content_type}")

    file_bytes = await file.read()
    if len(file_bytes) > MAX_AVATAR_SIZE:
        raise HTTPException(400, "L'avatar ne doit pas dépasser 5 Mo")

    try:
        url = upload_avatar(file_bytes, current_user.id)
    except Exception as e:
        raise HTTPException(500, f"Échec de l'upload : {str(e)}")

    current_user.avatar_url = url
    db.commit()
    db.refresh(current_user)
    return current_user

@router.get("/me", response_model=UserPublic, summary="Mon profil")
def get_my_profile(current_user: User = Depends(get_current_user)):
    return current_user


@router.patch("/me", response_model=UserPublic, summary="Modifier mon profil")
def update_my_profile(
    payload:      UserUpdate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(current_user, field, value)
    db.commit()
    db.refresh(current_user)
    return current_user


@router.get("/{user_id}", response_model=UserPublic, summary="Profil public d'un vendeur")
def get_user_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")
    return user


@router.get("/{user_id}/listings", response_model=List[ListingPublic], summary="Annonces d'un vendeur")
def get_user_listings(user_id: int, db: Session = Depends(get_db)):
    return db.query(Listing).filter(
        Listing.seller_id == user_id,
        Listing.status    == "active"
    ).order_by(Listing.created_at.desc()).all()


@router.post("/reviews", summary="Laisser un avis sur un vendeur")
def create_review(
    payload:      ReviewCreate,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    # Empêcher de se noter soi-même
    if payload.seller_id == current_user.id:
        raise HTTPException(status_code=400, detail="Tu ne peux pas te noter toi-même")

    # Vérifier si un avis existe déjà pour cette transaction
    existing = db.query(Review).filter(
        Review.reviewer_id == current_user.id,
        Review.listing_id  == payload.listing_id
    ).first()

    if existing:
        raise HTTPException(status_code=400, detail="Tu as déjà laissé un avis pour cette annonce")

    review = Review(
        reviewer_id = current_user.id,
        seller_id   = payload.seller_id,
        listing_id  = payload.listing_id,
        rating      = payload.rating,
        comment     = payload.comment
    )
    db.add(review)
    db.commit()

    # La moyenne est recalculée automatiquement par le trigger Supabase ✅
    return {"message": "Avis enregistré"}


@router.get("/{user_id}/reviews", summary="Avis reçus par un vendeur")
def get_user_reviews(user_id: int, db: Session = Depends(get_db)):
    reviews = db.query(Review).filter(Review.seller_id == user_id).all()
    return reviews