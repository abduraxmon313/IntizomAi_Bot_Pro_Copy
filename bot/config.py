from dotenv import load_dotenv
import os
import pytz

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

# ─────────────────────────────────────────────────────────────
#  IKKINCHI BOT (Dilshodbek) — eski "IntizomAI_bot"
# ─────────────────────────────────────────────────────────────
# Bu tokenga tegishli bot loyihaga qo'shimcha ulanadi (bot_dilshodbek paketi).
# Token Railway env yoki .env da DILSHODBEK_BOT_TOKEN nomi bilan beriladi.
# Bo'sh bo'lsa — ikkinchi bot ishga tushmaydi (asosiy bot ishlashda davom etadi).
DILSHODBEK_BOT_TOKEN = os.getenv("DILSHODBEK_BOT_TOKEN", "").strip()

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

# Odat (habit) bajarilgani uchun beriladigan ball (reja/maqsad kabi).
HABIT_DONE_SCORE = int(os.getenv("HABIT_DONE_SCORE", 5))

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

# Free (bepul) foydalanuvchi uchun maqsad va odat limitlari (premiumga undash).
# Bepul user Mini App'ni to'liq KO'RA oladi, lekin shu limitdan oshsa — paywall.
FREE_GOAL_LIMIT = int(os.getenv("FREE_GOAL_LIMIT", 3))
FREE_HABIT_LIMIT = int(os.getenv("FREE_HABIT_LIMIT", 3))

# Odat (habit) eslatmasi yuboriladigan soat (Tashkent vaqti) — bugun belgilanmagan
# odatlar uchun bitta jamlangan eslatma.
HABIT_REMINDER_HOUR = int(os.getenv("HABIT_REMINDER_HOUR", 19))
HABIT_REMINDER_MINUTE = int(os.getenv("HABIT_REMINDER_MINUTE", 0))

# Yangi foydalanuvchiga avtomatik beriladigan Premium sinov (trial) kunlari.
# 0 bo'lsa — trial berilmaydi. Loss-aversion: 3 kun premiumdan keyin limitlar.
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", 3))

# Obuna planlari: kalit -> (nom, davomiylik kun, narx so'mda, emoji, teg).
# Faqat 3 ta tarif — 7 kunlik va 6 oylik olib tashlandi (paywall soddaligi uchun).
# Admin `/admin → 💎 Premium → 💰 Tariflar narxi` orqali NOMI VA NARXINI
# o'zgartira oladi (title/tag/emoji ham override qilinadi).
SUBSCRIPTION_PLANS = {
    "1m":  {"title": "1 oy",  "days": 30,  "price": 39900,  "emoji": "✅", "tag": ""},
    "3m":  {"title": "3 oy",  "days": 90,  "price": 79900,  "emoji": "⭐", "tag": "33% tejaysiz"},
    "12m": {"title": "12 oy", "days": 365, "price": 179900, "emoji": "💎", "tag": "≈ 14 990 so'm/oy"},
}

# Obuna tugashidan necha kun oldin eslatma yuborilsin.
PREMIUM_EXPIRY_REMINDER_DAYS = [3, 1]


# ─────────────────────────────────────────────────────────────
#  REFERRAL (TAKLIF) TIZIMI
# ─────────────────────────────────────────────────────────────
# Bot username (havola yasash uchun). Telegram'dan avtomatik olinadi, lekin
# olinmasa shu qiymat ishlatiladi. '@' belgisisiz yoziladi.
BOT_USERNAME = os.getenv("BOT_USERNAME", "intizomAi_bot").strip().lstrip("@")

# Necha do'st taklif qilinsa mukofot beriladi.
REFERRAL_THRESHOLD = int(os.getenv("REFERRAL_THRESHOLD", 5))

# Taklif qilingan (yangi) do'stning O'ZIGA beriladigan premium kunlari
# (ikki tomonlama mukofot — taklif qilingan ham yutadi). 0 = berilmaydi.
REFERRAL_INVITEE_REWARD_DAYS = int(os.getenv("REFERRAL_INVITEE_REWARD_DAYS", 3))

# Mukofot sifatida beriladigan premium kunlari (har bir to'plam uchun).
REFERRAL_REWARD_DAYS = int(os.getenv("REFERRAL_REWARD_DAYS", 7))

# Mukofot premiumi manba nomi (Subscription tarixi uchun) — plan_key emas, chunki
# referral mukofoti tarif katalogiga bog'liq bo'lmasligi kerak. Bu manba
# `grant_bonus_premium(..., source=<bu>)` ga uzatiladi.
REFERRAL_REWARD_SOURCE = os.getenv("REFERRAL_REWARD_SOURCE", "referral").strip()

# Deep-link payload prefiksi: https://t.me/<bot>?start=ref_<telegram_id>
REFERRAL_PAYLOAD_PREFIX = "ref_"



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

# Webhook imzo maxfiy kaliti (WLCM webhookni ulagandan keyin beradi).
# Webhook haqiqatan WLCM'dan kelganini HMAC-SHA256 orqali tasdiqlash uchun.
PAYLOV_WEBHOOK_SECRET = os.getenv("PAYLOV_WEBHOOK_SECRET", "") or ""

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
#  FISCALIZATION (soliq cheki / OFD)
# ─────────────────────────────────────────────────────────────
def _to_int(val, default: int = 0) -> int:
    try:
        return int(str(val).strip())
    except (TypeError, ValueError):
        return default


# Soliq cheki yoqilganmi. Kalitlar (MXIK/package_code) bo'lmasa ham xavfsiz —
# faqat to'lov uchun kerak emas, best-effort. Default: env'dagi qiymat.
PAYLOV_FISCAL_ENABLED = (
    os.getenv("PAYLOV_FISCAL_ENABLED", "false").strip().lower() in ("1", "true", "yes")
)
# IKPU/MXIK mahsulot kodi (hujjatda item.code "mxik sifatida saqlanadi").
PAYLOV_FISCAL_MXIK = (os.getenv("PAYLOV_FISCAL_MXIK", "") or "").strip()
# Qadoq (package) kodi.
PAYLOV_FISCAL_PACKAGE_CODE = (os.getenv("PAYLOV_FISCAL_PACKAGE_CODE", "") or "").strip()
# QQS foizi (masalan 0 yoki 12).
PAYLOV_FISCAL_VAT_PERCENT = _to_int(os.getenv("PAYLOV_FISCAL_VAT_PERCENT", "0"), 0)


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
