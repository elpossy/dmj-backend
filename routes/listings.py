from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified   # ← FIX principal
from typing import Optional, List
from datetime import datetime, timezone
import logging

from database import get_db
from models import Listing, Favorite, User
from schemas import ListingPublic
from dependencies import get_current_user
from services.cloudinary_service import upload_listing_photo, delete_photo
from routes.dob import calculate_dob_cost, _debit_dob, _credit_dob

router = APIRouter()
logger = logging.getLogger(__name__)

ALLOWED_TYPES  = {"image/jpeg", "image/png", "image/webp"}
ALLOWED_VIDEO_TYPES = {"video/mp4", "video/quicktime", "video/webm"}
MAX_PHOTO_SIZE = 10 * 1024 * 1024
MAX_VIDEO_SIZE = 50 * 1024 * 1024
MAX_FILES      = 20   # garde-fou technique, pas une limite commerciale


@router.post("/", response_model=ListingPublic, summary="Publier une annonce")
async def create_listing(
    title:         str   = Form(...),
    price:         float = Form(...),
    description:   str   = Form(None),
    currency:      str   = Form("XOF"),
    is_negotiable: bool  = Form(False),
    condition:     str   = Form("new"),
    category_id:   int   = Form(None),
    city:          str   = Form(None),
    photos: List[UploadFile] = File(default=[]),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    if len(photos) > MAX_FILES:
        raise HTTPException(400, f"Maximum {MAX_FILES} photos par annonce")

    # ① Valider TOUS les fichiers AVANT de créer l'annonce ou de toucher aux DOB
    validated_files = []   # [(bytes, is_video, index)]
    for index, photo in enumerate(photos):
        if not photo.filename:
            continue

        is_video = photo.content_type in ALLOWED_VIDEO_TYPES
        is_photo = photo.content_type in ALLOWED_TYPES

        if not is_photo and not is_video:
            raise HTTPException(400, f"Format non supporté : {photo.content_type}")

        size_limit = MAX_VIDEO_SIZE if is_video else MAX_PHOTO_SIZE
        file_bytes = await photo.read()

        if len(file_bytes) == 0:
            continue

        if len(file_bytes) > size_limit:
            raise HTTPException(400, f"Photo {index+1} trop lourde (max 10 Mo)")

        validated_files.append((file_bytes, is_video, index))

    # ② Coût réel calculé sur les fichiers validés
    vid_count = sum(1 for _, is_video, _ in validated_files if is_video)
    pic_count = len(validated_files) - vid_count
    cost = calculate_dob_cost(pic_count, vid_count)

    # ③ Crée l'annonce en BROUILLON d'abord — aucun DOB engagé à ce stade
    listing = Listing(
        seller_id     = current_user.id,
        category_id   = category_id,
        title         = title,
        description   = description,
        price         = price,
        currency      = currency,
        is_negotiable = is_negotiable,
        condition     = condition,
        city          = city,
        photos        = [],
        status        = "draft"
    )
    db.add(listing)
    db.commit()
    db.refresh(listing)

    # ④ Débite les DOB — si solde insuffisant, exception levée AVANT tout débit,
    #    l'annonce reste en brouillon, 0 DOB perdu.
    _debit_dob(
        db, current_user, cost["total"],
        reason=f"listing_publish:base{cost['base']}+photo{cost['photo_extra']}+video{cost['video_cost']}",
        listing_id=listing.id
    )

    # ⑤ Upload des photos — si ça échoue, on REMBOURSE et on garde le brouillon
    uploaded_urls = []
    try:
        for file_bytes, is_video, index in validated_files:
            url = upload_listing_photo(file_bytes, listing.id, index)
            uploaded_urls.append(url)
            logger.info(f"Photo {index} uploadée : {url}")

        listing.photos = uploaded_urls
        listing.status = "active"
        flag_modified(listing, "photos")
        db.commit()
        db.refresh(listing)
        logger.info(f"Annonce {listing.id} publiée avec {len(uploaded_urls)} photo(s)")

    except Exception as e:
        logger.error(f"Échec upload photos annonce {listing.id} : {e}")
        _credit_dob(
            db, current_user, cost["total"],
            reason=f"refund_upload_failed:listing_{listing.id}",
            listing_id=listing.id
        )
        listing.photos = uploaded_urls   # garde celles déjà uploadées avant l'échec
        flag_modified(listing, "photos")
        db.commit()
        db.refresh(listing)
        # L'annonce reste "draft" — rien à recommencer, aucun DOB perdu

    return listing


@router.get("/", response_model=List[ListingPublic], summary="Annonces actives")
def get_listings(
    skip:        int           = Query(0, ge=0),
    limit:       int           = Query(20, ge=1, le=100),
    category_id: Optional[int] = Query(None),
    city:        Optional[str] = Query(None),
    db:          Session       = Depends(get_db)
):
    query = db.query(Listing).filter(Listing.status == "active")
    if category_id:
        query = query.filter(Listing.category_id == category_id)
    if city:
        query = query.filter(Listing.city.ilike(f"%{city}%"))
    return query.order_by(Listing.created_at.desc()).offset(skip).limit(limit).all()


@router.get("/me/favorites", response_model=List[ListingPublic], summary="Mes favoris")
def get_my_favorites(
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    favorites   = db.query(Favorite).filter(Favorite.user_id == current_user.id).all()
    listing_ids = [f.listing_id for f in favorites]
    return db.query(Listing).filter(
        Listing.id.in_(listing_ids),
        Listing.status == "active"
    ).all()


@router.get("/{listing_id}", response_model=ListingPublic, summary="Détail annonce")
def get_listing(listing_id: int, db: Session = Depends(get_db)):
    listing = db.query(Listing).filter(
        Listing.id == listing_id,
        Listing.status == "active"
    ).first()
    if not listing:
        raise HTTPException(404, "Annonce introuvable")
    listing.views += 1
    db.commit()
    return listing


@router.patch("/{listing_id}", response_model=ListingPublic, summary="Modifier annonce")
async def update_listing(
    listing_id:    int,
    title:         Optional[str]   = Form(None),
    price:         Optional[float] = Form(None),
    description:   Optional[str]   = Form(None),
    is_negotiable: Optional[bool]  = Form(None),
    condition:     Optional[str]   = Form(None),
    category_id:   Optional[int]   = Form(None),
    city:          Optional[str]   = Form(None),
    status:        Optional[str]   = Form(None),
    new_photos: List[UploadFile] = File(default=[]),
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(404, "Annonce introuvable")
    if listing.seller_id != current_user.id:
        raise HTTPException(403, "Action non autorisée")

    for field, value in {
        "title": title, "price": price, "description": description,
        "is_negotiable": is_negotiable, "condition": condition,
        "category_id": category_id, "city": city, "status": status
    }.items():
        if value is not None:
            setattr(listing, field, value)

    valid_new = [p for p in new_photos if p.filename]
    if valid_new:
        current_photos = list(listing.photos or [])
        for index, photo in enumerate(valid_new):
            if photo.content_type not in ALLOWED_TYPES | ALLOWED_VIDEO_TYPES:
                raise HTTPException(400, "Format non supporté")
            file_bytes = await photo.read()
            url = upload_listing_photo(file_bytes, listing.id, len(current_photos) + index)
            current_photos.append(url)
        listing.photos = current_photos
        flag_modified(listing, "photos")

    listing.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(listing)
    return listing


@router.delete("/{listing_id}", summary="Supprimer annonce")
def delete_listing(
    listing_id: int,
    db:         Session = Depends(get_db),
    current_user: User  = Depends(get_current_user)
):
    listing = db.query(Listing).filter(Listing.id == listing_id).first()
    if not listing:
        raise HTTPException(404, "Annonce introuvable")
    if listing.seller_id != current_user.id:
        raise HTTPException(403, "Action non autorisée")

    for url in (listing.photos or []):
        try:
            parts = url.split("/upload/")
            if len(parts) == 2:
                public_id = parts[1].rsplit(".", 1)[0]
                delete_photo(public_id)
        except Exception as e:
            logger.warning(f"Impossible de supprimer la photo Cloudinary : {e}")

    db.delete(listing)
    db.commit()
    return {"message": "Annonce supprimée"}


@router.post("/{listing_id}/favorite", summary="Ajouter/retirer favori")
def toggle_favorite(
    listing_id:   int,
    db:           Session = Depends(get_db),
    current_user: User    = Depends(get_current_user)
):
    existing = db.query(Favorite).filter(
        Favorite.user_id    == current_user.id,
        Favorite.listing_id == listing_id
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
        return {"favorited": False, "message": "Retiré des favoris"}
    db.add(Favorite(user_id=current_user.id, listing_id=listing_id))
    db.commit()
    return {"favorited": True, "message": "Ajouté aux favoris"}
