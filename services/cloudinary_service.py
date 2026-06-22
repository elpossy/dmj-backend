import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
import os
import logging

load_dotenv()
logger = logging.getLogger(__name__)

# .strip() retire les caractères invisibles Windows \r\n
# qui corrompent la signature Cloudinary
_cloud_name = (os.getenv("CLOUDINARY_CLOUD_NAME") or "").strip()
_api_key    = (os.getenv("CLOUDINARY_API_KEY")    or "").strip()
_api_secret = (os.getenv("CLOUDINARY_API_SECRET") or "").strip()

if not all([_cloud_name, _api_key, _api_secret]):
    raise RuntimeError("❌ Clés Cloudinary manquantes dans .env")

cloudinary.config(
    cloud_name = _cloud_name,
    api_key    = _api_key,
    api_secret = _api_secret,
    secure     = True
)

logger.info(f"✅ Cloudinary configuré : cloud={_cloud_name}")


def upload_listing_photo(file_bytes: bytes, listing_id: int, index: int) -> str:
    result = cloudinary.uploader.upload(
        file_bytes,
        folder    = f"damundje/listings/{listing_id}",
        public_id = f"photo_{index}",
        overwrite = True
    )
    url = result["secure_url"]
    logger.info(f"Photo {index} uploadée → {url}")
    return url


def upload_avatar(file_bytes: bytes, user_id: int) -> str:
    result = cloudinary.uploader.upload(
        file_bytes,
        folder    = "damundje/avatars",
        public_id = f"user_{user_id}",
        overwrite = True
    )
    return result["secure_url"]


def delete_photo(public_id: str) -> None:
    try:
        cloudinary.uploader.destroy(public_id)
        logger.info(f"Photo supprimée : {public_id}")
    except Exception as e:
        logger.warning(f"Impossible de supprimer {public_id} : {e}")
