import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage

from bot.config import BOT_TOKEN
from bot.handlers import start, plan, callback, report, admin, status, subscribe, chat_events
from bot.middleware.group_keyboard import GroupKeyboardRemoveMiddleware
from bot.services.scheduler import start_scheduler
from database.db import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────
#  DIQQAT: Bot buyruqlari (commands) va Menu Button sozlamalari
#  MANUAL, ya'ni BotFather orqali boshqariladi.
#
#  Ilgari bu yerda `set_commands(bot)` funksiyasi bor edi — u har safar bot
#  ishga tushganda `bot.set_my_commands(...)` va `bot.set_chat_menu_button(...)`
#  chaqirib, BotFather'da qo'lda sozlangan sozlamalarni O'ZI USTIDAN YOZIB
#  QO'YARDI (natijada foydalanuvchining Telegram klaviaturasi yonidagi Menu
#  tugmasi har server restart'da qayta paydo bo'lardi va /start /premium
#  /hisobot /contact buyruqlarini ko'rsatardi).
#
#  Endi bot Telegram API orqali commands/menu button'ga TEGMAYDI. Buni
#  sozlash butunlay BotFather orqali (yoki qo'lda API chaqiruvi bilan) amalga
#  oshiriladi. Bot ichidagi 6 talik reply klaviatura (main_reply_keyboard)
#  asosiy interfeys sifatida ishlatiladi.
# ─────────────────────────────────────────────────────────────


async def main():
    # DB jadvallarini yaratish
    await create_tables()
    logger.info("✅ Database tayyor")

    # ── ONE-TIME CLEANUP: eski trial obunalarni bekor qilish ────────────
    # Trial funksiyasi loyihadan olib tashlangan. Bu chaqiruv idempotent —
    # birinchi startup'da mavjud trial obunalarni bekor qiladi, keyingi
    # startup'larda topilmaganini ko'rib 0 qaytaradi. (Xuddi shu cleanup
    # `webapp/app.py` lifespan'ida ham chaqiriladi — bot alohida jarayonda
    # ishlasa yoki webapp bilan bir jarayonda — barchasida ishlaydi.)
    try:
        from bot.services.premium_service import revoke_all_trial_subscriptions
        revoked = await revoke_all_trial_subscriptions()
        if revoked > 0:
            logger.info(
                f"🧹 Trial cleanup: {revoked} ta eski trial obuna bekor qilindi."
            )
    except Exception as e:
        logger.warning(f"trial cleanup skip: {type(e).__name__}: {e}")

    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    # Middleware — session
    from database.db import AsyncSessionLocal
    from aiogram import BaseMiddleware
    from typing import Callable, Dict, Any, Awaitable
    from aiogram.types import TelegramObject

    class DbSessionMiddleware(BaseMiddleware):
        async def __call__(
            self,
            handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
            event: TelegramObject,
            data: Dict[str, Any],
        ) -> Any:
            async with AsyncSessionLocal() as session:
                data["session"] = session
                return await handler(event, data)

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())
    # my_chat_member — bot Telegram guruhlariga qo'shilgan/chiqarilganida
    # `bot_chats` jadvaliga yozish uchun sessiya kerak (chat_events handler).
    dp.my_chat_member.middleware(DbSessionMiddleware())

    # Guruh chatlarda Reply Keyboard va Menu Button ko'rsatilmasligini
    # ta'minlovchi middleware.
    dp.message.middleware(GroupKeyboardRemoveMiddleware())
    
    dp.include_router(start.router)
    dp.include_router(status.router)
    dp.include_router(admin.router)
    dp.include_router(subscribe.router)
    dp.include_router(plan.router)
    dp.include_router(callback.router)
    dp.include_router(report.router)
    # chat_events — bot Telegram guruhlariga qo'shildi/chiqarildi kuzatuvi.
    # WebApp digest funksiyasi bu jadval ustida ishlaydi.
    dp.include_router(chat_events.router)

    # Buyruqlar va Menu Button sozlamalari BOTGA TEGMAYMIZ —
    # ular BotFather orqali qo'lda sozlanadi (foydalanuvchi qo'yiladigan
    # sozlamalar ustidan yozib qo'yilmaydi).

    # Schedulerni ishga tushirish
    start_scheduler(bot)
    logger.info("✅ Scheduler ishga tushdi")

    logger.info("🚀 Intizom AI bot ishga tushdi!")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())