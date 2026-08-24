"""
WebApp xavfsizlik qatlami.

Asosiy himoyalar:
  1. Telegram WebApp `initData` HMAC tekshiruvi — foydalanuvchi haqiqatan
     o'sha telegram_id egasimi yoki yo'qligini bot token bilan tasdiqlaydi.
     (Buzg'unchi boshqa odamning telegram_id sini qo'lda yuborib, uning
      ma'lumotini o'qiy/o'zgartira olmaydi.)
  2. Soddalashtirilgan in-memory rate limiting (DoS / brute-force'ga qarshi).
  3. Xavfsizlik header'lari (XSS, clickjacking, MIME-sniffing).
  4. So'rov hajmi cheklovi (katta payload bilan hujumdan saqlanish).

Eslatma: initData tekshiruvi STRICT_AUTH=true (default) bo'lganda majburiy.
Bu rejimda faqat Telegram ichidan ochilgan Mini App ishlaydi (u har doim
initData yuboradi). Brauzerda to'g'ridan-to'g'ri ochish (demo) rad etiladi.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl

from fastapi import HTTPException, Request

from bot.config import BOT_TOKEN

logger = logging.getLogger(__name__)

# Tekshiruv qat'iyligini muhit (env) orqali boshqarish.
# Default = true: faqat Telegram WebApp `initData` (HMAC bilan tasdiqlangan)
# orqali kelgan so'rovlarga ruxsat beriladi. Bu boshqa odamning telegram_id
# sini qo'lda yuborib ma'lumotini o'qish/o'zgartirishni (IDOR) to'sadi.
# Agar zarur bo'lsa Railway'da STRICT_AUTH=false qilib vaqtincha yumshatish mumkin.
STRICT_AUTH = os.getenv("STRICT_AUTH", "true").strip().lower() in ("1", "true", "yes")

# XAVFSIZLIK: Production muhitda STRICT_AUTH=false bo'lsa — IDOR zaifligini
# qaytaradi. Shu sababli production'da (RAILWAY_ENVIRONMENT yoki NODE_ENV=production)
# STRICT_AUTH=false bo'lsa OGOHLANTIRISH beramiz va majburan true qilamiz.
_IS_PRODUCTION = os.getenv("RAILWAY_ENVIRONMENT", "").lower() in ("production", "prod") or \
    os.getenv("NODE_ENV", "").lower() == "production" or \
    bool(os.getenv("RAILWAY_PUBLIC_DOMAIN"))  # Railway'da deploy bo'lganda domain beriladi

if not STRICT_AUTH and _IS_PRODUCTION:
    logger.critical(
        "🚨 XAVFSIZLIK OGOHLANTIRILISHI: STRICT_AUTH=false production muhitda! "
        "Bu IDOR zaifligini ochadi. STRICT_AUTH majburan TRUE qilinmoqda. "
        "Debug uchun faqat lokal muhitda STRICT_AUTH=false ishlating."
    )
    STRICT_AUTH = True
elif not STRICT_AUTH:
    logger.warning(
        "⚠️ STRICT_AUTH=false — faqat lokal debug uchun. Production'da "
        "bu IDOR xavfini qaytaradi. Deploy qilishdan oldin STRICT_AUTH=true qiling."
    )

# initData maksimal "yoshi" (sekund) — eski/qayta yuborilgan ma'lumotni rad etish
INITDATA_MAX_AGE = int(os.getenv("INITDATA_MAX_AGE", 86400))  # 24 soat

# So'rov tanasi maksimal hajmi (bayt)
MAX_BODY_BYTES = int(os.getenv("MAX_BODY_BYTES", 1_500_000))  # 1.5 MB (avatar upload uchun)

# Rate limit: bir IP uchun oynada ruxsat etilgan so'rovlar
RATE_LIMIT_MAX = int(os.getenv("RATE_LIMIT_MAX", 120))     # so'rov
RATE_LIMIT_WINDOW = int(os.getenv("RATE_LIMIT_WINDOW", 60))  # sekund


def _secret_key() -> bytes:
    """Telegram WebApp uchun maxfiy kalit: HMAC_SHA256("WebAppData", bot_token)."""
    return hmac.new(b"WebAppData", (BOT_TOKEN or "").encode(), hashlib.sha256).digest()


def verify_init_data(init_data: str) -> dict | None:
    """
    Telegram WebApp initData ni tekshiradi.
    Muvaffaqiyatda parse qilingan `user` dict qaytaradi (id, first_name, ...),
    aks holda None.
    """
    if not init_data or not BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            return None

        # auth_date — replay/eskirgan tekshiruvi
        auth_date = int(pairs.get("auth_date", "0") or "0")
        if auth_date and INITDATA_MAX_AGE > 0:
            if time.time() - auth_date > INITDATA_MAX_AGE:
                return None

        # data_check_string — alifbo tartibida kalit=qiymat\n
        data_check_string = "\n".join(
            f"{k}={pairs[k]}" for k in sorted(pairs.keys())
        )
        computed = hmac.new(
            _secret_key(), data_check_string.encode(), hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(computed, received_hash):
            return None

        user_raw = pairs.get("user")
        if not user_raw:
            return None
        return json.loads(user_raw)
    except Exception:
        return None


def extract_verified_telegram_id(init_data: str | None) -> int | None:
    """initData dan tasdiqlangan telegram_id ni qaytaradi (yoki None)."""
    user = verify_init_data(init_data or "")
    if user and isinstance(user, dict) and user.get("id"):
        try:
            return int(user["id"])
        except (ValueError, TypeError):
            return None
    return None


# ─────────────────────────────────────────────────────────────
#  In-memory rate limiter (oddiy, bitta instans uchun yetarli)
# ─────────────────────────────────────────────────────────────
_hits: dict[str, list[float]] = {}


def rate_limited(client_key: str) -> bool:
    """True qaytarsa — limit oshib ketgan (so'rovni rad etish kerak)."""
    now = time.time()
    window_start = now - RATE_LIMIT_WINDOW
    bucket = _hits.get(client_key)
    if bucket is None:
        bucket = []
        _hits[client_key] = bucket
    # eski yozuvlarni tozalaymiz
    while bucket and bucket[0] < window_start:
        bucket.pop(0)
    if len(bucket) >= RATE_LIMIT_MAX:
        return True
    bucket.append(now)
    # xotira o'smasligi uchun vaqti-vaqti bilan tozalash
    if len(_hits) > 5000:
        for k in list(_hits.keys()):
            if not _hits[k] or _hits[k][-1] < window_start:
                _hits.pop(k, None)
    return False



# ─────────────────────────────────────────────────────────────
#  FastAPI dependency: tasdiqlangan telegram_id ni aniqlash
# ─────────────────────────────────────────────────────────────
def resolve_telegram_id(request: Request, telegram_id: int | None = None) -> int:
    """
    So'rovdan ishonchli telegram_id ni aniqlaydi (FastAPI dependency).

    Tartib:
      1. `X-Telegram-Init-Data` header bo'lsa — uni HMAC bilan tekshirib,
         undagi user.id ni ishlatadi (eng ishonchli). Bu holda query'dagi
         telegram_id E'TIBORGA OLINMAYDI — shuning uchun haqiqiy foydalanuvchini
         boshqa id yuborib aldab bo'lmaydi.
      2. STRICT_AUTH=false bo'lsa — query'dagi telegram_id ga ruxsat beradi
         (eski mijozlar / debug uchun).
      3. STRICT_AUTH=true (default) bo'lsa va initData yo'q/yaroqsiz bo'lsa — rad etadi.

    HTTPException ko'taradi (401/400) agar aniqlab bo'lmasa.
    """
    init_data = None
    try:
        init_data = request.headers.get("x-telegram-init-data")
    except Exception:
        init_data = None

    verified_id = extract_verified_telegram_id(init_data) if init_data else None
    if verified_id is not None:
        return verified_id

    if STRICT_AUTH:
        if init_data:
            logger.warning("initData tekshiruvi muvaffaqiyatsiz (HMAC mos kelmadi).")
        raise HTTPException(
            status_code=401,
            detail="Tasdiqlanmagan so'rov. Mini App'ni Telegram orqali oching.",
        )

    # Moslik rejimi (STRICT_AUTH=false): query telegram_id
    if telegram_id is None or telegram_id <= 0:
        raise HTTPException(status_code=400, detail="telegram_id noto'g'ri.")
    return int(telegram_id)
