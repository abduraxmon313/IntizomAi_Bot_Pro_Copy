import asyncio
import hashlib
import logging
import os
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from webapp.routes import goals, plans, stats, subscription, ai, payments, habits, profile, avatar, friends, config
from webapp.security import (
    MAX_BODY_BYTES,
    RATE_LIMIT_MAX,
    RATE_LIMIT_WINDOW,
    rate_limited,
)

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"


# ─────────────────────────────────────────────────────────────
# Statik aktivlar avtomatik cache-busting versiyasi.
# ─────────────────────────────────────────────────────────────
# app.js va app.css `Cache-Control: immutable` bilan uzoq muddat keshlanadi
# (foydalanuvchi qurilmasida va Telegram Mini App'da). Yangi deployda kesh
# yangilanishi uchun ular URL'da `?v=<hash>` versiyaga bog'lanadi. Bu hash
# fayl mazmunidan hisoblanadi — mazmun o'zgarsa hash ham o'zgaradi va client
# yangi versiyani yuklab oladi. Qattiq kodlangan versiya YO'Q.
def _compute_asset_version() -> str:
    """app.js + app.css tarkibi asosidagi qisqa SHA256 hash (12 ta belgi)."""
    try:
        h = hashlib.sha256()
        for name in ("app.js", "app.css"):
            p = STATIC_DIR / name
            if p.exists():
                h.update(p.read_bytes())
                h.update(b"|")
        return h.hexdigest()[:12]
    except Exception as e:  # pragma: no cover
        logger.warning(f"asset version compute failed: {e}")
        # Fallback — bo'sh bo'lsa ham o'ziga xos deployga bog'liq qiymat.
        return "dev"


ASSET_VERSION = _compute_asset_version()
_VERSION_QS_RE = re.compile(r"\?v=[A-Za-z0-9]+")


def _render_index_html() -> str:
    """
    index.html ichidagi `?v=<hardcoded>` qatorlarini joriy `ASSET_VERSION`
    bilan almashtiradi. Shu bilan yangi deployda barcha clientlar avtomatik
    yangi CSS/JS oladi (kesh baribir server tomondagi `immutable` qoladi).
    """
    raw = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
    return _VERSION_QS_RE.sub(f"?v={ASSET_VERSION}", raw)

# Bot'ni shu server jarayonida ishga tushirishni boshqarish.
# Default = true. Agar bot alohida jarayonda ishga tushsa yoki uvicorn bir
# nechta worker bilan ishlasa — bu yerda false qilib qo'yib, 409 Conflict
# (bir token bilan ko'p polling) muammosini oldini olish mumkin.
RUN_BOT = os.getenv("RUN_BOT", "true").strip().lower() in ("1", "true", "yes")

# Ikkinchi (Dilshodbek) botni shu jarayonda ishga tushirish. Default = true,
# lekin token bo'lmasa baribir ishga tushmaydi (bot_dilshodbek.main o'zi tekshiradi).
RUN_DILSHODBEK_BOT = os.getenv("RUN_DILSHODBEK_BOT", "true").strip().lower() in ("1", "true", "yes")


async def run_bot():
    try:
        from bot.main import main
        logger.info("🤖 Bot ishga tushmoqda...")
        await main()
    except asyncio.CancelledError:
        logger.info("🛑 Bot to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Bot xatosi: {e}")


async def run_dilshodbek_bot():
    try:
        from bot_dilshodbek.main import main as dilshodbek_main
        logger.info("🤖 Dilshodbek bot ishga tushmoqda...")
        await dilshodbek_main()
    except asyncio.CancelledError:
        logger.info("🛑 Dilshodbek bot to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Dilshodbek bot xatosi: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    # DB jadvallari tayyorligini KAFOLATLAYMIZ.
    # Bot alohida jarayonda ishlasa (RUN_BOT=false), jadvallarni bot yaratmaydi —
    # shuning uchun web jarayoni ham o'zi create_tables() chaqiradi. Funksiya
    # idempotent (_tables_ready flag + IF NOT EXISTS), shuning uchun bot bilan
    # bir jarayonda ishlaganda ham xavfsiz (ikki marta yaratmaydi).
    try:
        from database.db import create_tables
        await create_tables()
        logger.info("✅ Database tayyor (web lifespan)")
    except Exception as e:
        logger.warning(f"create_tables (web) skip/xato: {type(e).__name__}: {e}")

    bot_task = None
    dilshodbek_task = None
    if RUN_BOT:
        bot_task = asyncio.create_task(run_bot())
    else:
        logger.info("ℹ️ RUN_BOT=false — bot bu jarayonda ishga tushirilmadi")

    from bot.config import DILSHODBEK_BOT_TOKEN
    if RUN_DILSHODBEK_BOT and DILSHODBEK_BOT_TOKEN:
        dilshodbek_task = asyncio.create_task(run_dilshodbek_bot())
    elif RUN_DILSHODBEK_BOT and not DILSHODBEK_BOT_TOKEN:
        logger.info("ℹ️ DILSHODBEK_BOT_TOKEN yo'q — Dilshodbek bot ishga tushirilmadi")

    # Effective tarif narxlari keshini preload qilamiz (admin override'lar bo'lsa).
    # create_tables() yuqorida tugagani uchun endi kechikish (sleep) shart emas.
    try:
        from database.db import AsyncSessionLocal
        from bot.services.plan_pricing import refresh_plans_cache
        async with AsyncSessionLocal() as s:
            await refresh_plans_cache(s)
    except Exception as e:
        logger.warning(f"plan_pricing preload skip: {type(e).__name__}: {e}")

    # ── ONE-TIME CLEANUP: eski trial obunalarni bekor qilish ────────────
    # Trial funksiyasi loyihadan olib tashlangan (bot/services/activation.py'da
    # endi trial berilmaydi). Baza'da hali ham `source="trial"` bilan faol
    # (is_active=True) obunalar bo'lishi mumkin — ularni bekor qilamiz va
    # user'lardan Premium'ni olib tashlaymiz. IDEMPOTENT: birinchi run'dan keyin
    # keyingi startup'larda hech qanday trial qolmagan bo'ladi va 0 qaytariladi.
    try:
        from bot.services.premium_service import revoke_all_trial_subscriptions
        revoked = await revoke_all_trial_subscriptions()
        if revoked > 0:
            logger.info(
                f"🧹 Trial cleanup: {revoked} ta eski trial obuna bekor qilindi "
                "(trial funksiyasi olib tashlangan)."
            )
    except Exception as e:
        logger.warning(f"trial cleanup skip: {type(e).__name__}: {e}")

    logger.info("🌐 FastAPI server tayyor")
    yield

    for task in (bot_task, dilshodbek_task):
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


app = FastAPI(
    title="Intizom AI Web App API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

# GZip — HTML/JS/CSS/JSON javoblarni siqadi (~70% kichrayadi). 500 baytdan
# katta javoblar siqiladi; rasm (avatar) allaqachon siqilgan bo'lgani uchun
# GZip ularga deyarli ta'sir qilmaydi (zararsiz).
app.add_middleware(GZipMiddleware, minimum_size=500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    # Autentifikatsiya cookie orqali emas, `X-Telegram-Init-Data` header orqali
    # bo'lgani uchun credentials kerak emas. allow_credentials=True + "*" — bu
    # brauzer spetsifikatsiyasiga zid (noto'g'ri konfiguratsiya), shuning uchun False.
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
#  Xavfsizlik middleware: rate limit + payload hajmi + header'lar
# ─────────────────────────────────────────────────────────────
@app.middleware("http")
async def security_middleware(request: Request, call_next):
    path = request.url.path

    # Faqat API yo'llari uchun rate limit va payload tekshiruvi
    if path.startswith("/api/"):
        # Klient IP (proxy orqali bo'lsa X-Forwarded-For)
        fwd = request.headers.get("x-forwarded-for", "")
        client_ip = fwd.split(",")[0].strip() if fwd else (
            request.client.host if request.client else "unknown"
        )

        # 1) Rate limiting
        if rate_limited(client_ip):
            return JSONResponse(
                status_code=429,
                content={"detail": "Juda ko'p so'rov. Biroz kuting."},
            )

        # 2) Payload hajmi cheklovi (Content-Length orqali)
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > MAX_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "So'rov hajmi juda katta."},
                    )
            except ValueError:
                pass

    response = await call_next(request)

    # 3) Xavfsizlik header'lari (barcha javoblarga)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    # Faqat Telegram (va o'zimiz) sahifani <iframe> ga joylashi mumkin —
    # boshqa saytlar embed qilolmaydi (clickjacking himoyasi). Bu X-Frame-Options:
    # SAMEORIGIN o'rniga ishlatiladi, chunki u Telegram Web'dagi Mini App'ni
    # (boshqa origin'dagi iframe) bloklab qo'yardi.
    response.headers["Content-Security-Policy"] = (
        "frame-ancestors 'self' https://telegram.org https://*.telegram.org "
        "https://web.telegram.org tg://"
    )
    return response

app.include_router(plans.router, prefix="/api/webapp")
app.include_router(goals.router, prefix="/api/webapp")
app.include_router(stats.router, prefix="/api/webapp")
app.include_router(subscription.router, prefix="/api/webapp")
app.include_router(ai.router, prefix="/api/webapp")
app.include_router(habits.router, prefix="/api/webapp")
app.include_router(profile.router, prefix="/api/webapp")
app.include_router(avatar.router, prefix="/api/webapp")
app.include_router(friends.router, prefix="/api/webapp")
app.include_router(config.router, prefix="/api/webapp")
# Paylov webhook — /webhook/paylov (prefiksiz, /api/ ostida emas)
app.include_router(payments.router)


@app.get("/health")
async def health():
    return {"status": "ok", "asset_version": ASSET_VERSION}


@app.get("/")
async def root():
    # index.html — har doim revalidatsiya (yangi deploy darhol ko'rinsin).
    # Og'ir CSS/JS alohida versiyalangan fayllarda (uzoq muddat keshlanadi).
    # `?v=<hash>` avtomatik yangilanadi — CSS/JS o'zgarsa clientlar avtomatik
    # yangi versiyani yuklab oladi.
    html = _render_index_html()
    return HTMLResponse(
        html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# Versiyalangan statik aktivlar (app.css / app.js) — uzoq muddat keshlanadi.
# URL'da ?v=<versiya> bo'lgani uchun yangi deployda avtomatik yangilanadi
# (cache-busting), shuning uchun "immutable" xavfsiz.
_STATIC_MAX_AGE = "public, max-age=31536000, immutable"


@app.get("/static/app.css")
async def static_css():
    return FileResponse(
        STATIC_DIR / "app.css",
        media_type="text/css",
        headers={"Cache-Control": _STATIC_MAX_AGE},
    )


@app.get("/static/app.js")
async def static_js():
    return FileResponse(
        STATIC_DIR / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": _STATIC_MAX_AGE},
    )
