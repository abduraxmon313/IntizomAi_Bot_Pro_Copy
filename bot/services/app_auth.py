"""
Mobil ilova (Flutter) autentifikatsiyasi.

  • JWT token: ilova barcha `/api/webapp/*` so'rovlarida
    `Authorization: Bearer <token>` yuboradi. Token ichida `telegram_id` bor.
  • Kirish so'rovi (AppLoginRequest): ilova yaratgan bir martalik `nonce`
    bot ichida foydalanuvchi tomonidan tasdiqlanadi.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta
from typing import Optional

from jose import JWTError, jwt
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import JWT_ALGORITHM, JWT_EXPIRY_DAYS, JWT_SECRET
from bot.models.app_login import AppLoginRequest

# /start payload: applogin_<nonce>. Telegram payload limiti 64 belgi,
# ruxsat etilgan belgilar A-Z a-z 0-9 _ -.
APP_LOGIN_PREFIX = "applogin_"
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{32,54}$")

# Kirish so'rovi necha daqiqa amal qiladi.
LOGIN_REQUEST_TTL = timedelta(minutes=10)


# ─────────────────────────────────────────────────────────────
#  JWT
# ─────────────────────────────────────────────────────────────
def create_app_token(telegram_id: int) -> str:
    now = datetime.utcnow()
    payload = {
        "sub": str(telegram_id),
        "telegram_id": int(telegram_id),
        "type": "app",
        "iat": now,
        "exp": now + timedelta(days=JWT_EXPIRY_DAYS),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_app_token(token: str) -> Optional[int]:
    """Token to'g'ri bo'lsa telegram_id qaytaradi, aks holda None."""
    if not token or not JWT_SECRET:
        return None
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None
    if payload.get("type") != "app":
        return None
    try:
        return int(payload["telegram_id"])
    except (KeyError, TypeError, ValueError):
        return None


# ─────────────────────────────────────────────────────────────
#  Kirish so'rovi (nonce)
# ─────────────────────────────────────────────────────────────
def parse_app_login_nonce(args: Optional[str]) -> Optional[str]:
    if not args:
        return None
    s = args.strip()
    if not s.startswith(APP_LOGIN_PREFIX):
        return None
    nonce = s[len(APP_LOGIN_PREFIX):]
    return nonce if _NONCE_RE.match(nonce) else None


def is_valid_nonce(nonce: Optional[str]) -> bool:
    return bool(nonce and _NONCE_RE.match(nonce))


def hash_nonce(nonce: str) -> str:
    # 48 hex (192 bit) — Telegram callback_data 64 bayt limitiga sig'ishi uchun.
    return hashlib.sha256(nonce.encode()).hexdigest()[:48]


async def _purge_expired(session: AsyncSession) -> None:
    cutoff = datetime.utcnow() - LOGIN_REQUEST_TTL
    await session.execute(
        delete(AppLoginRequest).where(AppLoginRequest.created_at < cutoff)
    )


async def register_login_request(session: AsyncSession, nonce: str) -> str:
    """Bot /start applogin_<nonce> ni qabul qilganda chaqiriladi. Xeshni qaytaradi."""
    h = hash_nonce(nonce)
    await _purge_expired(session)
    row = await session.get(AppLoginRequest, h)
    if row is None:
        session.add(AppLoginRequest(nonce_hash=h, created_at=datetime.utcnow()))
    await session.commit()
    return h


async def approve_login_request(
    session: AsyncSession, nonce_hash: str, telegram_id: int,
) -> bool:
    """Foydalanuvchi botda "Tasdiqlash"ni bosganda. Muddati o'tgan bo'lsa False."""
    row = await session.get(AppLoginRequest, nonce_hash)
    if row is None or row.created_at < datetime.utcnow() - LOGIN_REQUEST_TTL:
        return False
    if row.approved_at is not None:
        # Bir so'rovni faqat bitta foydalanuvchi tasdiqlaydi.
        return row.telegram_id == telegram_id
    row.telegram_id = telegram_id
    row.approved_at = datetime.utcnow()
    await session.commit()
    return True


async def consume_login_request(session: AsyncSession, nonce: str) -> tuple[str, Optional[int]]:
    """
    Ilova so'rovi. Qaytaradi:
      ("approved", telegram_id) — tasdiqlangan, yozuv o'chirildi
      ("pending", None)         — hali tasdiqlanmagan
      ("expired", None)         — topilmadi yoki muddati o'tgan
    """
    h = hash_nonce(nonce)
    row = await session.get(AppLoginRequest, h)
    if row is None:
        return "expired", None
    if row.created_at < datetime.utcnow() - LOGIN_REQUEST_TTL:
        await session.delete(row)
        await session.commit()
        return "expired", None
    if row.approved_at is None or row.telegram_id is None:
        return "pending", None
    telegram_id = int(row.telegram_id)
    await session.delete(row)
    await session.commit()
    return "approved", telegram_id
