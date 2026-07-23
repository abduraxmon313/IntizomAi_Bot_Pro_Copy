import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllChatAdministrators,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonCommands,
)

from bot.config import BOT_TOKEN
from bot.handlers import start, plan, callback, report, admin, status, subscribe, chat_events
from bot.services.scheduler import start_scheduler
from database.db import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def set_commands(bot: Bot):
    """
    Telegram "menu" tugmasi buyruqlarini per-scope ro'yxatga oladi.

    TELEGRAM SCOPE IERARXIYASI (eng aniqroqdan → eng umumiyroqqa):
      1. BotCommandScopeChat                    — bitta aniq chat
      2. BotCommandScopeChatAdministrators      — aniq chatning adminlari
      3. BotCommandScopeAllChatAdministrators   — istalgan guruh adminlari  ⚠️
      4. BotCommandScopeAllGroupChats           — istalgan guruh a'zolari
      5. BotCommandScopeAllPrivateChats         — istalgan DM
      6. BotCommandScopeDefault                 — fallback

    Guruhdagi ADMIN foydalanuvchilar #3 (AllChatAdministrators) scope'ni oladi
    (agar ular admin bo'lsa). Uni SET QILMASAK, admin foydalanuvchi eski
    (masalan `/start`, `/admin`) buyruqlarni ko'rishi mumkin va bu bir necha
    userlar aytgan "guruhda hali ham shaxsiy tugmalar chiqyapti" muammosi.

    Shu sabab hozir #3 scope'ni HAM aniq set qilamiz — u ham [hisobot, contact]
    dan iborat, ya'ni guruh admini ham a'zosi ham AYNAN bir xil menyu ko'radi.
    """
    # Har safar set qilishdan oldin BARCHA scope'lardan eski buyruqlarni
    # tozalaymiz. AllChatAdministrators — YANGI qo'shilgan (avval bo'lmagan).
    for scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
        BotCommandScopeAllChatAdministrators(),
    ):
        try:
            await bot.delete_my_commands(scope=scope)
        except Exception:
            # Delete ba'zan ishlamasa ham set_my_commands almashtiradi — jim o'tamiz.
            pass

    # ── Shaxsiy chat (DM) uchun buyruqlar ──────────────────────
    # `/admin` ATAYIN kiritilmagan — admin panelga oddiy foydalanuvchilar duch
    # kelmasin. Adminlar buyruqni qo'lda yozib chaqira oladi (handler mavjud).
    private_commands = [
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="premium", description="💎 Premium olish"),
        BotCommand(command="hisobot", description="📈 Bugungi hisobot"),
        BotCommand(command="contact", description="📞 Bog'lanish"),
    ]
    await bot.set_my_commands(
        private_commands, scope=BotCommandScopeAllPrivateChats(),
    )

    # ── Guruh chatlari uchun buyruqlar (faqat 2 ta) ────────────
    group_commands = [
        BotCommand(command="hisobot", description="📊 Umumiy hisobot"),
        BotCommand(command="contact", description="📞 Bog'lanish"),
    ]
    # Oddiy guruh a'zosi shu scope'ni ko'radi.
    await bot.set_my_commands(
        group_commands, scope=BotCommandScopeAllGroupChats(),
    )
    # Guruh ADMINI ham AYNAN shu 2 ta buyruqni ko'rishi kerak. Bu scope
    # aniq set qilinmasa Telegram AllGroupChats'ga tushib ketardi — lekin
    # eski deploylardan buzuq qiymatlar qolib qolishi mumkin edi.
    await bot.set_my_commands(
        group_commands, scope=BotCommandScopeAllChatAdministrators(),
    )

    # ── Default scope — minimal (fallback) ─────────────────────
    default_commands = [
        BotCommand(command="start", description="Botni boshlash"),
    ]
    await bot.set_my_commands(
        default_commands, scope=BotCommandScopeDefault(),
    )

    # ── Menu tugmasi rejimini AJRATIB set qilish ──────────────
    # Ba'zi deploylarda menu tugmasi `MenuButtonWebApp` yoki `MenuButtonDefault`
    # ga o'rnatilgan bo'lishi mumkin. Aniq `MenuButtonCommands` ga o'rnatib,
    # menu tugmasi TO'G'RIDAN-TO'G'RI buyruqlar ro'yxatini ko'rsatishini
    # kafolatlaymiz — foydalanuvchi guruhda menu tugmasini bosganda faqat
    # bizning group_commands ni ko'radi.
    try:
        await bot.set_chat_menu_button(menu_button=MenuButtonCommands())
    except Exception as e:
        logger.warning(f"set_chat_menu_button skip: {type(e).__name__}: {e}")

    logger.info(
        "📋 Bot commands o'rnatildi: private=%d, group=%d, admin(group)=%d",
        len(private_commands), len(group_commands), len(group_commands),
    )


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

    # Buyruqlarni sozlash
    await set_commands(bot)

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