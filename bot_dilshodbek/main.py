"""
Dilshodbek bot kirish nuqtasi.

Asosiy bot bilan BIR jarayonda (webapp lifespan ichida) alohida task sifatida
ishga tushadi. O'ziga xos Bot + Dispatcher ishlatadi, lekin ma'lumotlar bazasi
(AsyncSessionLocal) va admin ro'yxati asosiy loyiha bilan UMUMIY.
"""
import logging
from typing import Any, Awaitable, Callable, Dict

from aiogram import BaseMiddleware, Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, TelegramObject

from bot.config import DILSHODBEK_BOT_TOKEN
from database.db import AsyncSessionLocal, create_tables
from bot_dilshodbek.handlers import admin as d_admin
from bot_dilshodbek.handlers import start as d_start

logger = logging.getLogger(__name__)


class DbSessionMiddleware(BaseMiddleware):
    """Har bir update uchun DB sessiyasi (asosiy bot bilan bir xil pattern)."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any],
    ) -> Any:
        async with AsyncSessionLocal() as session:
            data["session"] = session
            return await handler(event, data)


async def set_commands(bot: Bot):
    await bot.set_my_commands([
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="admin", description="Admin panel"),
    ])


async def main():
    if not DILSHODBEK_BOT_TOKEN:
        logger.warning("ℹ️ DILSHODBEK_BOT_TOKEN yo'q — Dilshodbek bot ishga tushirilmadi.")
        return

    # Jadvallar tayyorligiga ishonch hosil qilamiz (lock bilan, bir martalik).
    await create_tables()

    bot = Bot(token=DILSHODBEK_BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())

    dp.message.middleware(DbSessionMiddleware())
    dp.callback_query.middleware(DbSessionMiddleware())

    # Admin router BIRINCHI — broadcast FSM holati boshqa handlerlardan ustun bo'lsin.
    dp.include_router(d_admin.router)
    dp.include_router(d_start.router)

    await set_commands(bot)
    logger.info("🚀 Dilshodbek bot ishga tushdi!")

    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()
