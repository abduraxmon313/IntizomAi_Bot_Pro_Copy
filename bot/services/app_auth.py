"""
Mobil ilova uchun JWT autentifikatsiya xizmati.

Bot foydalanuvchiga JWT token beradi → foydalanuvchi ilovaga kiritadi →
ilova token bilan /api/app/* endpointlariga so'rov yuboradi.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from jose import JWTError, jwt

from bot.config import JWT_SECRET, JWT_ALGORITHM, JWT_EXPIRY_DAYS


def create_app_token(user_id: int, telegram_id: int) -> str:
    """Mobil ilova uchun JWT token yaratadi.

    Token tarkibi:
      - user_id: DB'dagi users.id
      - telegram_id: Telegram foydalanuvchi ID'si
      - exp: muddati (default 365 kun)
    """
    payload = {
        "user_id": user_id,
        "telegram_id": telegram_id,
        "exp": datetime.utcnow() + timedelta(days=JWT_EXPIRY_DAYS),
        "iat": datetime.utcnow(),
        "type": "app",
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_app_token(token: str) -> dict | None:
    """JWT tokenni tekshiradi va payload qaytaradi.

    Xato bo'lsa None qaytaradi.
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "app":
            return None
        return payload
    except JWTError:
        return None
