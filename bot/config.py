from dotenv import load_dotenv
import os
import pytz

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

DB_HOST = os.getenv("DB_HOST", "localhost")
DB_PORT = os.getenv("DB_PORT", "5432")
DB_NAME = os.getenv("DB_NAME", "productivity_bot")
DB_USER = os.getenv("DB_USER", "postgres")
DB_PASS = os.getenv("DB_PASS", "")

DATABASE_URL = f"postgresql+asyncpg://{DB_USER}:{DB_PASS}@{DB_HOST}:{DB_PORT}/{DB_NAME}"

ADMIN_ID = int(os.getenv("ADMIN_ID", 0))

# O'zbekiston vaqti
TIMEZONE = pytz.timezone("Asia/Tashkent")

# Ball tizimi
SCORE_DONE = 5
SCORE_FAILED = -3
STREAK_BONUS = 2

# Kunlik summary vaqti (Tashkent vaqti)
SUMMARY_HOUR = 23
SUMMARY_MINUTE = 59

# Pending check vaqti (Tashkent vaqti)
PENDING_CHECK_HOUR = 23
PENDING_CHECK_MINUTE = 0

# ─────────────────────────────────────────────────────────────
#  MONETIZATSIYA / OBUNA
# ─────────────────────────────────────────────────────────────
# Sinov bosqichidagi promokod — shu matn yuborilsa obuna faollashadi.
# Kelajakda karta to'lovi qo'shilganda shu joy o'zgartiriladi.
PROMO_CODE = os.getenv("PROMO_CODE", "intizom").strip()

# Mini App (WebApp) URL — bot/handlers/start.py va paywall uchun.
WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()

# Free (bepul) foydalanuvchi uchun kunlik reja limiti.
FREE_DAILY_PLAN_LIMIT = int(os.getenv("FREE_DAILY_PLAN_LIMIT", 5))

# Free foydalanuvchi uchun kunlik AI Coach suhbat limiti (taste → premiumga undash).
FREE_AI_DAILY_LIMIT = int(os.getenv("FREE_AI_DAILY_LIMIT", 3))

# Obuna planlari: kalit -> (nom, davomiylik kun, narx so'mda, emoji, teg).
SUBSCRIPTION_PLANS = {
    "7d":  {"title": "Sinov 7 kun", "days": 7,   "price": 9900,  "emoji": "🔥", "tag": ""},
    "1m":  {"title": "Oylik",       "days": 30,  "price": 19900, "emoji": "💎", "tag": ""},
    "3m":  {"title": "3 oy",        "days": 90,  "price": 39900, "emoji": "🌟", "tag": "TOP tanlov"},
    "6m":  {"title": "6 oy",        "days": 180, "price": 59900, "emoji": "🚀", "tag": ""},
    "12m": {"title": "Yillik",      "days": 365, "price": 99900, "emoji": "👑", "tag": ""},
}

# Obuna tugashidan necha kun oldin eslatma yuborilsin.
PREMIUM_EXPIRY_REMINDER_DAYS = [3, 1]



# ─────────────────────────────────────────────────────────────
#  PAYLOV / wlcm.uz TO'LOV TIZIMI
# ─────────────────────────────────────────────────────────────
# Railway env qiymatlari (.env kabi o'qiladi). Asosiy nomlar — foydalanuvchi
# Railway'ga qo'ygan nomlar; PAYLOV_ prefiksli muqobil nomlar ham qo'llab-quvvatlanadi.
def _normalize_api_base(url: str) -> str:
    """
    To'lov API bazaviy URL'ini normallashtiradi.

    Klient (bot/services/paylov.py) yo'lga doim '/api/v1' prefiksini qo'shadi,
    shuning uchun bazaviy URL faqat HOST bo'lishi kerak (masalan
    https://api.wlcm.uz). Agar Railway'da Base_URL ga '/api/v1' (yoki '/api')
    qo'shib qo'yilgan bo'lsa — uni olib tashlaymiz, aks holda yo'l
    '/api/v1/api/v1/...' bo'lib 404 (Not Found) qaytaradi.
    """
    url = (url or "").strip().rstrip("/")
    for suffix in ("/api/v1", "/api"):
        if url.lower().endswith(suffix):
            url = url[: -len(suffix)].rstrip("/")
            break
    return url


PAYLOV_BASE_URL = _normalize_api_base(
    os.getenv("Base_URL")
    or os.getenv("PAYLOV_BASE_URL")
    or "https://api.wlcm.uz"
)
PAYLOV_API_KEY = os.getenv("API_KEY") or os.getenv("PAYLOV_API_KEY", "") or ""
PAYLOV_API_SECRET = os.getenv("API_SECRET") or os.getenv("PAYLOV_API_SECRET", "") or ""
PAYLOV_PARTNER_ID = os.getenv("PARTNER_ID") or os.getenv("PAYLOV_PARTNER_ID", "") or ""
PAYLOV_PROD_TOKEN = os.getenv("PROD_TOKEN") or os.getenv("PAYLOV_PROD_TOKEN", "") or ""

# To'lov provayderi (paylov/payme/click/uzum/card) va to'lovdan keyin qaytish URL.
# PAYLOV_PROVIDER — foydalanuvchi tanlamasa ishlatiladigan default provayder.
PAYLOV_PROVIDER = os.getenv("PAYLOV_PROVIDER", "paylov").strip()
PAYLOV_RETURN_URL = os.getenv("PAYLOV_RETURN_URL", "https://t.me/intizomAi_bot").strip()

# To'lov oynasida foydalanuvchiga ko'rsatiladigan provayderlar (tugma sifatida).
# Vergul bilan ajratilgan. Hujjatdagi qiymatlar: payme, click, uzum, paylov, card.
# Eslatma: 'card' bu yerga KIRITILMAYDI — u alohida OTP oqimini talab qiladi
# (checkout_url emas, balki transaction_id + OTP). Faqat redirect-checkout
# provayderlari ko'rsatiladi.
_VALID_PROVIDERS = {"payme", "click", "uzum", "paylov"}
PAYLOV_PROVIDERS = [
    p.strip().lower()
    for p in os.getenv("PAYLOV_PROVIDERS", "payme,click,uzum,paylov").split(",")
    if p.strip().lower() in _VALID_PROVIDERS
] or ["paylov"]

# Onboarding endpoint path (PROD_TOKEN → api_key + api_secret olish uchun).
# Hujjatda `partners/onboarding/` deyilgan; boshqa endpointlar /api/v1 ostida.
# Agar server boshqa path ishlatsa — WLCM_ONBOARDING_PATH bilan o'zgartiring.
PAYLOV_ONBOARDING_PATH = (
    os.getenv("WLCM_ONBOARDING_PATH")
    or os.getenv("PAYLOV_ONBOARDING_PATH")
    or "/api/v1/partners/onboarding/"
).strip()

# To'lov tizimi sozlanganmi (kalitlar bormi). Bo'lmasa — sinov (simulyatsiya) rejimi.
PAYLOV_ENABLED = bool(PAYLOV_API_KEY and PAYLOV_API_SECRET)


# ─────────────────────────────────────────────────────────────
#  WEBHOOK URL (WLCM shu manzilga to'lov natijasini yuboradi)
# ─────────────────────────────────────────────────────────────
def _origin(url: str) -> str:
    """URL dan faqat scheme://host qismini ajratadi (path/queryни tashlaydi)."""
    if not url:
        return ""
    from urllib.parse import urlsplit
    parts = urlsplit(url if "://" in url else f"https://{url}")
    if parts.scheme and parts.netloc:
        return f"{parts.scheme}://{parts.netloc}"
    return ""


# Ommaviy domen: aniq PUBLIC_BASE_URL > Railway domeni > WEBAPP_URL origin'i.
PUBLIC_BASE_URL = (
    _origin(os.getenv("PUBLIC_BASE_URL", ""))
    or (f"https://{os.getenv('RAILWAY_PUBLIC_DOMAIN')}" if os.getenv("RAILWAY_PUBLIC_DOMAIN") else "")
    or _origin(WEBAPP_URL)
).rstrip("/")

PAYLOV_WEBHOOK_PATH = "/webhook/paylov"
# To'liq webhook URL (domen aniqlansa). Aniqlanmasa — faqat path.
PAYLOV_WEBHOOK_URL = (
    f"{PUBLIC_BASE_URL}{PAYLOV_WEBHOOK_PATH}" if PUBLIC_BASE_URL else PAYLOV_WEBHOOK_PATH
)
