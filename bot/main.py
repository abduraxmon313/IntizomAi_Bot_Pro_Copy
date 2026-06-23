import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from bot.config import BOT_TOKEN
from bot.handlers import start, plan, callback, report, admin, status, subscribe
from bot.services.scheduler import start_scheduler
from database.db import create_tables

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


async def set_commands(bot: Bot):
    commands = [
        BotCommand(command="start", description="Botni boshlash"),
        BotCommand(command="admin", description="Admin panel"),
    ]
    await bot.set_my_commands(commands)


async def main():
    # DB jadvallarini yaratish
    await create_tables()
    logger.info("✅ Database tayyor")

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
    
    dp.include_router(start.router)
    dp.include_router(status.router)
    dp.include_router(admin.router)
    dp.include_router(subscribe.router)
    dp.include_router(plan.router)
    dp.include_router(callback.router)
    dp.include_router(report.router)

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