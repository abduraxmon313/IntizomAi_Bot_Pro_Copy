import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    BotCommand,
    BotCommandScopeAllGroupChats,
    BotCommandScopeAllPrivateChats,
    BotCommandScopeDefault,
    MenuButtonDefault,
    MenuButtonCommands,
)

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


async def set_commands(bot: Bot):
    """
    Telegram "menu" tugmasi buyruqlarini ro'yxatga oladi.

    Alohida SCOPE'lar:
      • PRIVATE chats — shaxsiy ishlash tugmalari (obuna, hisobot, bog'lanish).
        Foydalanuvchi bot bilan shaxsiy chatda menu tugmasini bosganda shu
        buyruqlar chiqadi.
      • GROUP/SUPERGROUP chats — FAQAT 2 ta amal (Umumiy hisobot, Bog'lanish).
        Guruh a'zolari menu tugmasini bosganda "mening statusim/rejalarim/reja
        qo'shish/premium" kabi shaxsiy tugmalarni KO'RMAYDI. Bu Telegram
        darajasidagi cheklov — reply keyboard va shaxsiy handlerlar allaqachon
        ChatType.PRIVATE bilan filtrlangan.
      • DEFAULT scope — minimal fallback (asosan hech qachon ishlatilmaydi,
        chunki har ikki asosiy scope aniq ko'rsatilgan).
    """
    # Har safar set qilishdan oldin BARCHA scope'lardan eski buyruqlarni
    # tozalaymiz — aks holda avvalgi deploy'larda ro'yxatga olingan (masalan
    # /admin) buyruqlar qolib ketishi mumkin.
    for scope in (
        BotCommandScopeDefault(),
        BotCommandScopeAllPrivateChats(),
        BotCommandScopeAllGroupChats(),
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
    await bot.set_my_commands(
        group_commands, scope=BotCommandScopeAllGroupChats(),
    )

    # ── Default scope — minimal (fallback) ─────────────────────
    default_commands = [
        BotCommand(command="start", description="Botni boshlash"),
    ]
    await bot.set_my_commands(
        default_commands, scope=BotCommandScopeDefault(),
    )

    # ── Menu Button sozlamalari ─────────────────────────────────
    # Private chatlar uchun — Menu tugmasini ko'rsatamiz (commands menyusi).
    try:
        await bot.set_chat_menu_button(
            menu_button=MenuButtonCommands(),
        )
    except Exception:
        pass

    # Guruh chatlarida Menu Button ko'rsatilmasin — MenuButtonDefault (bo'sh)
    # Telegram API scope bo'yicha chat_menu_button o'rnatishga ruxsat bermaydi,
    # lekin buyruqlar ro'yxati guruh uchun alohida o'rnatilgan (yuqorida).
    # Bu yetarli — guruh foydalanuvchilari faqat guruh buyruqlarini ko'radi.


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