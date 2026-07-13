"""
Foydalanuvchi Telegram profil rasmi proksisi (reyting/leaderboard uchun).

Nima uchun kerak:
  Ilgari faqat Mini App'ni OCHGAN foydalanuvchining rasmi (Telegram `initData`
  bergan `photo_url`) bazaga saqlanardi. Shu sababli reytingda faqat o'zining
  rasmi ko'rinardi — boshqalarniki (ayniqsa Mini App'ni ochmaganlar) yo'q edi.

  Bu endpoint BOT orqali istalgan foydalanuvchining profil rasmini yuklaydi
  (foydalanuvchi faqat botni ishga tushirgan bo'lsa kifoya — Mini App shart emas)
  va uni rasm sifatida qaytaradi. Reytingdagi barcha rasmlar shu proksidan
  o'tadi, natijada 20 talik ro'yxatdagi hamma (va o'zi) rasmi bilan ko'rinadi.

Xavfsizlik:
  <img src> maxsus header (X-Telegram-Init-Data) yubora olmagani uchun bu
  endpoint autentifikatsiyasiz ishlaydi (profil rasmlari ochiq ma'lumot).
  Ochiq proksi bo'lib qolmasligi uchun FAQAT bazada mavjud foydalanuvchilar
  uchun rasm qaytaradi. Natijalar (rasm bor/yo'q) xotirada keshlanadi —
  Telegram API ga ortiqcha so'rov yubormaslik uchun.
"""
import asyncio
import logging
import time
from typing import Optional

import httpx
from fastapi import APIRouter, Depends, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import BOT_TOKEN
from bot.models.user import User
from database.db import AsyncSessionLocal

router = APIRouter()
logger = logging.getLogger(__name__)

_TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
_TG_FILE = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Xotira keshi: telegram_id -> (bytes|None, content_type, expires_at)
#   bytes=None  → rasm yo'q (privacy yoki topilmadi) — qayta urinishdan oldin kutamiz.
_CACHE: dict[int, tuple[Optional[bytes], str, float]] = {}
_CACHE_TTL = 12 * 3600      # muvaffaqiyatli rasm — 12 soat
_NEG_TTL = 3 * 3600         # rasm yo'q — 3 soatdan keyin qayta urinamiz
_MAX_CACHE = 3000

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()


async def get_session():
    async with AsyncSessionLocal() as session:
        yield session


async def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                _client = httpx.AsyncClient(timeout=10.0)
    return _client


async def _fetch_photo_bytes(telegram_id: int) -> tuple[Optional[bytes], str]:
    """
    Telegram Bot API orqali foydalanuvchi profil rasmini yuklaydi.
    Qaytaradi: (rasm_baytlari|None, content_type).
    """
    if not BOT_TOKEN:
        return None, "image/jpeg"
    try:
        client = await _get_client()
        # 1) Profil rasmlari ro'yxati
        r = await client.get(
            f"{_TG_API}/getUserProfilePhotos",
            params={"user_id": telegram_id, "limit": 1},
        )
        data = r.json()
        if not data.get("ok"):
            return None, "image/jpeg"
        photos = (data.get("result") or {}).get("photos") or []
        if not photos:
            return None, "image/jpeg"

        # Har bir rasm bir nechta o'lchamda keladi (kichikdan kattaga).
        # Reyting uchun o'rtacha o'lcham yetarli — 2-o'lchamni (yoki mavjudini) olamiz.
        sizes = photos[0]
        if not sizes:
            return None, "image/jpeg"
        chosen = sizes[min(1, len(sizes) - 1)]
        file_id = chosen.get("file_id")
        if not file_id:
            return None, "image/jpeg"

        # 2) file_id → file_path
        rf = await client.get(f"{_TG_API}/getFile", params={"file_id": file_id})
        fdata = rf.json()
        if not fdata.get("ok"):
            return None, "image/jpeg"
        file_path = (fdata.get("result") or {}).get("file_path")
        if not file_path:
            return None, "image/jpeg"

        # 3) Rasmni yuklab olamiz
        img = await client.get(f"{_TG_FILE}/{file_path}")
        if img.status_code != 200 or not img.content:
            return None, "image/jpeg"
        ct = img.headers.get("content-type", "image/jpeg")
        return img.content, ct
    except Exception as e:
        logger.warning(f"avatar fetch fail user={telegram_id}: {type(e).__name__}: {e}")
        return None, "image/jpeg"


@router.get("/avatar/{telegram_id}")
async def avatar(telegram_id: int, session: AsyncSession = Depends(get_session)):
    """Foydalanuvchi profil rasmini qaytaradi (yo'q bo'lsa 404 — frontend emojiga tushadi)."""
    now = time.time()

    cached = _CACHE.get(telegram_id)
    if cached and cached[2] > now:
        content, ct, _ = cached
        if content:
            return Response(
                content=content, media_type=ct,
                headers={"Cache-Control": "public, max-age=43200"},
            )
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})

    # Ochiq proksi bo'lmasligi uchun — faqat bazadagi foydalanuvchilar.
    exists = await session.scalar(select(User.id).where(User.telegram_id == telegram_id))
    if not exists:
        return Response(status_code=404)

    content, ct = await _fetch_photo_bytes(telegram_id)
    ttl = _CACHE_TTL if content else _NEG_TTL
    if len(_CACHE) > _MAX_CACHE:
        _CACHE.clear()
    _CACHE[telegram_id] = (content, ct, now + ttl)

    if not content:
        return Response(status_code=404, headers={"Cache-Control": "public, max-age=3600"})
    return Response(
        content=content, media_type=ct,
        headers={"Cache-Control": "public, max-age=43200"},
    )
