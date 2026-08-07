from sqlalchemy import (
    Column, BigInteger, Text, Boolean,
    Numeric, SmallInteger, Integer,
    TIMESTAMP, ForeignKey
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR
from sqlalchemy.sql import func
from database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    phone         = Column(Text, unique=True, nullable=False)
    name          = Column(Text, nullable=True)
    avatar_url    = Column(Text, nullable=True)
    bio           = Column(Text, nullable=True)
    city          = Column(Text, nullable=True)
    is_verified   = Column(Boolean, default=False)
    is_banned     = Column(Boolean, default=False)
    rating_avg    = Column(Numeric(3, 2), default=0.00)
    rating_count  = Column(Integer, default=0)
    created_at    = Column(TIMESTAMP(timezone=True), server_default=func.now())
    last_seen_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())
    dob_balance   = Column(Integer, default=14)


class OTPCode(Base):
    __tablename__ = "otp_codes"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    phone      = Column(Text, nullable=False)
    code       = Column(Text, nullable=False)        # stocké hashé (bcrypt)
    expires_at = Column(TIMESTAMP(timezone=True), nullable=False)
    used       = Column(Boolean, default=False)
    attempts   = Column(Integer, default=0)          # max 3 tentatives
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Session(Base):
    __tablename__ = "sessions"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id     = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    token       = Column(Text, unique=True, nullable=False)
    device_info = Column(Text, nullable=True)
    expires_at  = Column(TIMESTAMP(timezone=True), nullable=False)
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Category(Base):
    __tablename__ = "categories"

    id        = Column(BigInteger, primary_key=True, autoincrement=True)
    slug      = Column(Text, unique=True, nullable=False)
    label     = Column(Text, nullable=False)
    icon      = Column(Text, nullable=True)
    parent_id = Column(BigInteger, ForeignKey("categories.id"), nullable=True)


class Listing(Base):
    __tablename__ = "listings"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    seller_id       = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    category_id     = Column(BigInteger, ForeignKey("categories.id", ondelete="SET NULL"), nullable=True)
    title           = Column(Text, nullable=False)
    description     = Column(Text, nullable=True)
    price           = Column(Numeric(14, 2), nullable=False)
    currency        = Column(Text, default="XOF")
    is_negotiable   = Column(Boolean, default=False)
    condition       = Column(Text, default="used")
    photos          = Column(JSONB, default=list)     # liste d'URLs Cloudinary
    city            = Column(Text, nullable=True)
    status          = Column(Text, default="active")
    views           = Column(Integer, default=0)
    favorites_count = Column(Integer, default=0)
    created_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    updated_at      = Column(TIMESTAMP(timezone=True), server_default=func.now())
    search_vector   = Column(TSVECTOR, nullable=True)  # généré par trigger Supabase


class Favorite(Base):
    __tablename__ = "favorites"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id    = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id = Column(BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Review(Base):
    __tablename__ = "reviews"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    reviewer_id = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    seller_id   = Column(BigInteger, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    listing_id  = Column(BigInteger, ForeignKey("listings.id", ondelete="SET NULL"), nullable=True)
    rating      = Column(SmallInteger, nullable=False)
    comment     = Column(Text, nullable=True)
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())


class Report(Base):
    __tablename__ = "reports"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    reporter_id = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    listing_id  = Column(BigInteger, ForeignKey("listings.id", ondelete="CASCADE"), nullable=False)
    reason      = Column(Text, nullable=False)
    details     = Column(Text, nullable=True)
    resolved    = Column(Boolean, default=False)
    created_at  = Column(TIMESTAMP(timezone=True), server_default=func.now())


class UserEvent(Base):
    __tablename__ = "user_events"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    user_id    = Column(BigInteger, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    listing_id = Column(BigInteger, ForeignKey("listings.id", ondelete="SET NULL"), nullable=True)
    event_type = Column(Text, nullable=False)
    query      = Column(Text, nullable=True)
    duration_s = Column(Integer, nullable=True)
    created_at = Column(TIMESTAMP(timezone=True), server_default=func.now())