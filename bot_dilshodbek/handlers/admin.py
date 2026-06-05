"""
Dilshodbek bot — admin panel + userlarga xabar yuborish (broadcast).

/admin → "📢 Userlarga xabar yuborish" → matn → preview → tasdiqlash → yuborish.

MUHIM (umumiy baza):
  Userlar bazasi ikkala bot uchun YAGONA. Telegram qoidasiga ko'ra bot FAQAT
  o'ziga /start bosgan (chati ochiq) foydalanuvchilarga xabar yubora oladi.
  Shu sabab biz bazadagi BARCHA userlarga yuborishga harakat qilamiz, lekin
  amalda xabar faqat SHU (Dilshodbek) botga start bosganlarga yetib boradi.
  Boshqalar (faqat asosiy botga start bosganlar) "yetib bormadi" deb sanaladi.

  Diqqat: bu yerda foydalanuvchining `is_active` maydoni O'ZGARTIRILMAYDI —
  chunki u asosiy bot holati uchun ishlatiladi (Dilshodbek bot yetib
  bormagani — asosiy botda nofaol degani emas).
"""
import asyncio
import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.admin_service import get_users_count, is_admin
from bot_dilshodbek.keyboards import (
    admin_main_keyboard,
    back_to_admin_keyboard,
    broadcast_confirm_keyboard,
)

logger = logging.getLogger(__name__)
router = Router()


class DilshodBroadcast(StatesGroup):
    waiting_text = State()


PANEL_TEXT = (
    "🛡 <b>Admin Panel</b> (Dilshodbek bot)\n\n"
    "👥 Bazadagi userlar: <b>{count} ta</b>\n\n"
    "<i>Eslatma: xabar faqat shu botga /start bosgan foydalanuvchilarga "
    "yetib boradi.</i>\n\nKerakli amalni tanlang:"
)


@router.message(Command("admin"))
async def admin_panel(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        await message.answer("❌ Sizda admin huquqi yo'q.")
        return
    await state.clear()
    count = await get_users_count(session)
    await message.answer(
        PANEL_TEXT.format(count=count),
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )


@router.callback_query(F.data == "dilshod_admin_panel")
async def admin_panel_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await state.clear()
    count = await get_users_count(session)
    await callback.message.edit_text(
        PANEL_TEXT.format(count=count),
        parse_mode="HTML",
        reply_markup=admin_main_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "dilshod_admin_close")
async def admin_close_cb(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    try:
        await callback.message.edit_text("✅ Admin panel yopildi.")
    except Exception:
        pass
    await callback.answer()


# ───────────────────────── BROADCAST ─────────────────────────
@router.callback_query(F.data == "dilshod_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await state.set_state(DilshodBroadcast.waiting_text)
    await callback.message.edit_text(
        "📢 <b>Userlarga xabar yuborish</b>\n\n"
        "Yubormoqchi bo'lgan xabar matnini yuboring:\n\n"
        "<i>HTML format ishlaydi:\n"
        "&lt;b&gt;qalin&lt;/b&gt; → <b>qalin</b>\n"
        "&lt;i&gt;kursiv&lt;/i&gt; → <i>kursiv</i>\n"
        "&lt;code&gt;kod&lt;/code&gt; → <code>kod</code></i>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard(),
    )
    await callback.answer()


@router.message(DilshodBroadcast.waiting_text)
async def broadcast_text_received(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    text = message.text or message.caption or ""
    if not text.strip():
        await message.answer("❌ Bo'sh xabar. Matn yuboring:")
        return

    await state.update_data(broadcast_text=text)
    count = await get_users_count(session)

    await message.answer(
        "👁 <b>Preview:</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"{text}\n"
        "━━━━━━━━━━━━━━━\n\n"
        f"📢 Bazadagi <b>{count} ta</b> userga yuborishga harakat qilinadi "
        "(faqat shu botga start bosganlar oladi).\n\n"
        "Tasdiqlaysizmi?",
        parse_mode="HTML",
        reply_markup=broadcast_confirm_keyboard(),
    )


@router.callback_query(F.data == "dilshod_broadcast_send")
async def broadcast_send(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    data = await state.get_data()
    text = data.get("broadcast_text", "")
    await state.clear()

    if not text.strip():
        await callback.answer("❌ Xabar topilmadi.", show_alert=True)
        return

    progress_msg = await callback.message.edit_text(
        "⏳ Yuborish boshlandi... (orqa fonda davom etadi)"
    )
    asyncio.create_task(_run_broadcast(callback.bot, text, progress_msg))
    await callback.answer("📢 Yuborish boshlandi", show_alert=False)


async def _run_broadcast(bot, text: str, progress_msg) -> None:
    """
    Barcha userlarga (umumiy baza) xabar yuborish — FON vazifasi.

    `is_active` maydoni O'ZGARTIRILMAYDI (u asosiy botga tegishli). Yetib
    bormagan userlar shunchaki "yetib bormadi" deb sanaladi.
    """
    from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter
    from sqlalchemy import select

    from database.db import AsyncSessionLocal
    from bot.models.user import User

    sent = failed = unreachable = 0
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User))).scalars().all()
        total = len(users)

        for i, user in enumerate(users, 1):
            try:
                await bot.send_message(user.telegram_id, text, parse_mode="HTML")
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await bot.send_message(user.telegram_id, text, parse_mode="HTML")
                    sent += 1
                except TelegramForbiddenError:
                    unreachable += 1
                except Exception:
                    failed += 1
            except TelegramForbiddenError:
                # Shu botga start bosmagan yoki bloklagan — bu KUTILGAN holat.
                unreachable += 1
            except Exception:
                failed += 1

            if i % 25 == 0:
                try:
                    await progress_msg.edit_text(f"⏳ Yuborilmoqda... {i}/{total}")
                except Exception:
                    pass
            await asyncio.sleep(0.05)

    try:
        await progress_msg.edit_text(
            "✅ <b>Yuborish tugadi!</b>\n\n"
            f"👥 Bazada jami: <b>{total} ta</b>\n"
            f"✅ Yetkazildi: <b>{sent} ta</b>\n"
            f"🚫 Yetib bormadi (start bosmagan/bloklagan): <b>{unreachable} ta</b>\n"
            f"❌ Xatolik: <b>{failed} ta</b>",
            parse_mode="HTML",
            reply_markup=back_to_admin_keyboard(),
        )
    except Exception:
        pass
