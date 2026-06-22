from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime
import re


# ─── AUTH ──────────────────────────────────────────

class PhoneRequest(BaseModel):
    """Demande d'envoi d'un code OTP"""
    phone: str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v):
        # Format E.164 obligatoire : +22796000000
        if not re.match(r"^\+\d{8,15}$", v):
            raise ValueError("Format invalide. Utilise le format international : +22796000000")
        return v


class OTPVerifyRequest(BaseModel):
    """Vérification du code OTP reçu sur WhatsApp"""
    phone: str
    code: str


class TokenResponse(BaseModel):
    """Réponse après connexion réussie"""
    token: str
    user_id: int
    name: Optional[str]
    is_new_user: bool   # True si c'est la première connexion


# ─── USERS ─────────────────────────────────────────

class UserPublic(BaseModel):
    """Profil public visible par tous"""
    id: int
    name: Optional[str]
    avatar_url: Optional[str]
    city: Optional[str]
    is_verified: bool
    rating_avg: float
    rating_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    """Mise à jour du profil (champs optionnels)"""
    name: Optional[str] = None
    avatar_url: Optional[str] = None
    bio: Optional[str] = None
    city: Optional[str] = None


# ─── LISTINGS ──────────────────────────────────────

class ListingCreate(BaseModel):
    title: str
    description: Optional[str] = None
    price: float
    currency: str = "XOF"
    is_negotiable: bool = False
    condition: str = "used"
    category_id: Optional[int] = None
    city: Optional[str] = None
    photos: List[str] = []       # URLs envoyées après upload Cloudinary

    @field_validator("price")
    @classmethod
    def price_positive(cls, v):
        if v <= 0:
            raise ValueError("Le prix doit être supérieur à 0")
        return v

    @field_validator("condition")
    @classmethod
    def valid_condition(cls, v):
        allowed = {"new", "like_new", "good", "used", "damaged"}
        if v not in allowed:
            raise ValueError(f"Condition invalide. Valeurs acceptées : {allowed}")
        return v


class ListingUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = None
    is_negotiable: Optional[bool] = None
    condition: Optional[str] = None
    category_id: Optional[int] = None
    city: Optional[str] = None
    photos: Optional[List[str]] = None
    status: Optional[str] = None


class ListingPublic(BaseModel):
    id: int
    seller_id: int
    title: str
    description: Optional[str]
    price: float
    currency: str
    is_negotiable: bool
    condition: str
    photos: List[str]
    city: Optional[str]
    status: str
    views: int
    favorites_count: int
    created_at: datetime

    class Config:
        from_attributes = True


# ─── REVIEWS ───────────────────────────────────────

class ReviewCreate(BaseModel):
    seller_id: int
    listing_id: Optional[int] = None
    rating: int
    comment: Optional[str] = None

    @field_validator("rating")
    @classmethod
    def valid_rating(cls, v):
        if not 1 <= v <= 5:
            raise ValueError("La note doit être entre 1 et 5")
        return v


# ─── REPORTS ───────────────────────────────────────

class ReportCreate(BaseModel):
    listing_id: int
    reason: str
    details: Optional[str] = None

    @field_validator("reason")
    @classmethod
    def valid_reason(cls, v):
        allowed = {"spam", "fake", "inappropriate", "scam", "other"}
        if v not in allowed:
            raise ValueError(f"Raison invalide. Valeurs acceptées : {allowed}")
        return v