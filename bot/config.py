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
    "7d":  {"title": "Sinov 7 kun", "days": 7,   "price": 9900,  "emoji": "🔥", "tag": "Challenge"},
    "1m":  {"title": "Oylik",       "days": 30,  "price": 19900, "emoji": "💎", "tag": ""},
    "3m":  {"title": "3 oy",        "days": 90,  "price": 39900, "emoji": "⭐", "tag": "TOP tanlov"},
    "6m":  {"title": "6 oy",        "days": 180, "price": 59900, "emoji": "🚀", "tag": "Ko'proq tejash"},
    "12m": {"title": "Yillik",      "days": 365, "price": 99900, "emoji": "👑", "tag": "Eng yaxshi qiymat"},
}

# Obuna tugashidan necha kun oldin eslatma yuborilsin.
PREMIUM_EXPIRY_REMINDER_DAYS = [3, 1]