import asyncio
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from webapp.routes import goals, plans, stats, subscription, ai
from webapp.security import (
    MAX_BODY_BYTES,
    RATE_LIMIT_MAX,
    RATE_LIMIT_WINDOW,
    rate_limited,
)

logger = logging.getLogger(__name__)
STATIC_DIR = Path(__file__).parent / "static"

# Bot'ni shu server jarayonida ishga tushirishni boshqarish.
# Default = true. Agar bot alohida jarayonda ishga tushsa yoki uvicorn bir
# nechta worker bilan ishlasa — bu yerda false qilib qo'yib, 409 Conflict
# (bir token bilan ko'p polling) muammosini oldini olish mumkin.
RUN_BOT = os.getenv("RUN_BOT", "true").strip().lower() in ("1", "true", "yes")


async def run_bot():
    try:
        from bot.main import main
        logger.info("🤖 Bot ishga tushmoqda...")
        await main()
    except asyncio.CancelledError:
        logger.info("🛑 Bot to'xtatildi")
    except Exception as e:
        logger.error(f"❌ Bot xatosi: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    bot_task = None
    if RUN_BOT:
        bot_task = asyncio.create_task(run_bot())
    else:
        logger.info("ℹ️ RUN_BOT=false — bot bu jarayonda ishga tushirilmadi")
    logger.info("🌐 FastAPI server tayyor")
    yield
    if bot_task is not None:
        bot_task.cancel()
        try:
            await bot_task
        except asyncio.CancelledError:
            pass


app = FastAPI(
    title="Intizom AI Web App API",
    docs_url=None,
    redoc_url=None,
    lifespan=lifespan,
)

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


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/")
async def root():
    return FileResponse(STATIC_DIR / "index.html")
