from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from bot.services.user_service import get_user_by_telegram_id
from bot.services.ai_service import transcribe_voice, extract_plans_from_text
from bot.services.plan_service import create_plans, get_today_plans, get_plan_by_id, delete_plan, plan_block_reason
from bot.services.premium_service import user_is_premium
from bot.utils.ratelimit import allow_ai_analysis, seconds_until_reset
from bot.keyboards.plan_keys import (
    confirm_plans_keyboard, plans_list_keyboard,
    plan_actions_keyboard, plan_list_actions_keyboard
)
from bot.utils.formatters import format_plan_confirm, format_plan_list

router = Router()
logger = logging.getLogger(__name__)


async def _ai_rate_ok(message: Message, session: AsyncSession) -> bool:
    """
    AI tahliliga (Whisper/GPT) ruxsat bormi? Suiiste'mol (cost abuse) himoyasi.
    Limit oshsa — foydalanuvchiga xabar berib False qaytaradi.
    """
    is_premium = False
    try:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        is_premium = user_is_premium(user) if user else False
    except Exception:
        is_premium = False

    if allow_ai_analysis(message.from_user.id, is_premium):
        return True

    wait_min = max(1, seconds_until_reset(message.from_user.id) // 60)
    await message.answer(
        "⏳ <b>Biroz sekinlashtiramiz.</b>\n\n"
        "Juda ko'p ketma-ket so'rov yubordingiz. "
        f"Iltimos, ~{wait_min} daqiqadan so'ng qayta urinib ko'ring.\n\n"
        "💎 Premium foydalanuvchilar uchun cheklov ancha yuqori.",
        parse_mode="HTML",
    )
    return False


class PlanState(StatesGroup):
    waiting_for_plan = State()
    asking_time = State()        # Vaqt so'rash
    confirming_plans = State()
    editing_plan = State()


def no_time_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🕐 Vaqtsiz saqlash", callback_data="save_without_time")]
    ])


async def ask_time_for_plan(message: Message, state: FSMContext, plans: list):
    """Vaqtsiz rejalar uchun vaqt so'raydi"""
    # Vaqtsiz rejalarni topish
    no_time_plans = [p for p in plans if not p.get("scheduled_time")]
    has_time_plans = [p for p in plans if p.get("scheduled_time")]

    if not no_time_plans:
        # Hammada vaqt bor — tasdiqlashga o'tish
        await state.update_data(plans=plans)
        await state.set_state(PlanState.confirming_plans)
        await message.answer(
            format_plan_confirm(plans),
            parse_mode="HTML",
            reply_markup=confirm_plans_keyboard()
        )
        return

    # Vaqtsiz rejalar bor — birinchisini so'raymiz
    first_no_time = no_time_plans[0]
    await state.update_data(
        plans=plans,
        no_time_plans=no_time_plans,
        has_time_plans=has_time_plans,
        current_asking_index=0
    )
    await state.set_state(PlanState.asking_time)

    await message.answer(
        f"⏰ <b>Vaqtni belgilang</b>\n\n"
        f"📌 <b>{first_no_time['title']}</b> — qachon?\n\n"
        f"Ovozli yoki matn orqali ayting:\n"
        f"<i>Masalan: 'Soat 15 da', '30 minutdan keyin', 'Kechqurun 19:00'</i>",
        parse_mode="HTML",
        reply_markup=no_time_keyboard()
    )


async def process_next_no_time_plan(message_or_callback, state: FSMContext, current_index: int, plans: list):
    """Keyingi vaqtsiz rejani so'raydi yoki tasdiqlashga o'tadi"""
    data = await state.get_data()
    no_time_plans = data.get("no_time_plans", [])

    next_index = current_index + 1

    if next_index >= len(no_time_plans):
        # Hammasi tayyor — tasdiqlashga o'tish
        await state.update_data(plans=plans)
        await state.set_state(PlanState.confirming_plans)

        if hasattr(message_or_callback, 'message'):
            msg = message_or_callback.message
            await msg.edit_text(
                format_plan_confirm(plans),
                parse_mode="HTML",
                reply_markup=confirm_plans_keyboard()
            )
        else:
            await message_or_callback.answer(
                format_plan_confirm(plans),
                parse_mode="HTML",
                reply_markup=confirm_plans_keyboard()
            )
    else:
        # Keyingi vaqtsiz rejani so'rash
        next_plan = no_time_plans[next_index]
        await state.update_data(current_asking_index=next_index, plans=plans)

        text = (
            f"⏰ <b>Vaqtni belgilang</b>\n\n"
            f"📌 <b>{next_plan['title']}</b> — qachon?\n\n"
            f"<i>Masalan: 'Soat 15 da', '30 minutdan keyin'</i>"
        )

        if hasattr(message_or_callback, 'message'):
            await message_or_callback.message.edit_text(
                text, parse_mode="HTML", reply_markup=no_time_keyboard()
            )
        else:
            await message_or_callback.answer(
                text, parse_mode="HTML", reply_markup=no_time_keyboard()
            )


# ─────────────────────────────────────────
#  REJA QO'SHISH
# ─────────────────────────────────────────

@router.message(F.text == "➕ Reja qo'shish")
async def add_plan_btn(message: Message, state: FSMContext):
    await message.answer(
        "➕ <b>Yangi reja</b>\n\n"
        "Bugun nima qilmoqchi ekanligingizni yozing yoki "
        "🎤 ovozli xabar yuboring.\n\n"
        "<i>Masalan: 'Soat 7 da turaman, 10 da sport qilaman'</i>",
        parse_mode="HTML"
    )
    await state.set_state(PlanState.waiting_for_plan)


@router.callback_query(F.data == "add_plan")
async def add_plan_callback(callback: CallbackQuery, state: FSMContext):
    await callback.message.answer(
        "➕ <b>Yangi reja</b>\n\n"
        "Bugun nima qilmoqchi ekanligingizni yozing yoki "
        "🎤 ovozli xabar yuboring.",
        parse_mode="HTML"
    )
    await state.set_state(PlanState.waiting_for_plan)
    await callback.answer()


# ─────────────────────────────────────────
#  OVOZ — istalgan vaqt
# ─────────────────────────────────────────

@router.message(F.voice)
async def handle_voice_any(message: Message, state: FSMContext, session: AsyncSession):
    current_state = await state.get_state()

    # Agar vaqt so'rayotgan bo'lsak — vaqt uchun ovoz
    if current_state == PlanState.asking_time.state:
        await handle_voice_for_time(message, state)
        return

    # AI xarajat himoyasi — Whisper/GPT chaqiruvidan OLDIN
    if not await _ai_rate_ok(message, session):
        return

    processing_msg = await message.answer("⏳ Tahlil qilinmoqda...")

    try:
        file = await message.bot.get_file(message.voice.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        audio_data = file_bytes.read()

        text = await transcribe_voice(audio_data)
        logger.info(f"🎤 Transcribed: '{text}'")

        if not text:
            await processing_msg.delete()
            await message.answer("😕 Ovozni anglay olmadim. Qayta yuboring.")
            return

        plans = await extract_plans_from_text(text)
        logger.info(f"📋 Plans: {plans}")

        await processing_msg.delete()

        if not plans:
            await message.answer(
                f"😕 Rejani aniqlay olmadim.\n\n"
                f"<i>Men eshitdim: \"{text}\"</i>\n\n"
                f"Aniqroq ayting, masalan: 'Soat 6 da turaman'",
                parse_mode="HTML"
            )
            return

        await ask_time_for_plan(message, state, plans)

    except Exception as e:
        logger.error(f"❌ Voice handler xato: {e}")
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")


async def handle_voice_for_time(message: Message, state: FSMContext):
    """Vaqt so'raganda ovoz kelsa"""
    processing_msg = await message.answer("⏳ Vaqt aniqlanmoqda...")
    try:
        file = await message.bot.get_file(message.voice.file_id)
        file_bytes = await message.bot.download_file(file.file_path)
        audio_data = file_bytes.read()

        text = await transcribe_voice(audio_data)
        await processing_msg.delete()
        await process_time_input(message, state, text)
    except Exception:
        await processing_msg.delete()
        await message.answer("❌ Xatolik. Qayta urinib ko'ring.")


# ─────────────────────────────────────────
#  MATN — istalgan vaqt
# ─────────────────────────────────────────

@router.message(F.text & ~F.text.startswith("/") & ~F.text.in_({
    "📊 Mening statusim", "📋 Rejalarim", "📈 Hisobot", "➕ Reja qo'shish", "💎 Obuna"
}))
async def handle_text_any(message: Message, state: FSMContext, session: AsyncSession):
    current_state = await state.get_state()

    if current_state == PlanState.editing_plan.state:
        return

    # Vaqt so'rash holatida
    if current_state == PlanState.asking_time.state:
        await process_time_input(message, state, message.text)
        return

    # AI xarajat himoyasi — GPT chaqiruvidan OLDIN
    if not await _ai_rate_ok(message, session):
        return

    processing_msg = await message.answer("⏳ Tahlil qilinmoqda...")

    try:
        plans = await extract_plans_from_text(message.text)
        await processing_msg.delete()

        if not plans:
            await message.answer(
                "😕 Rejalarni aniqlay olmadim.\n"
                "<i>Masalan: 'Soat 6 da turaman, 9 da kitob o'qiyman'</i>",
                parse_mode="HTML"
            )
            return

        await ask_time_for_plan(message, state, plans)

    except Exception:
        try:
            await processing_msg.delete()
        except Exception:
            pass
        await message.answer("❌ Xatolik yuz berdi. Qayta urinib ko'ring.")


async def process_time_input(message: Message, state: FSMContext, text: str):
    """User vaqt aytganda — GPT dan faqat vaqtni chiqaradi"""
    data = await state.get_data()
    plans = data.get("plans", [])
    no_time_plans = data.get("no_time_plans", [])
    current_index = data.get("current_asking_index", 0)

    # Faqat vaqtni chiqarish
    from bot.services.ai_service import extract_time_only
    scheduled_time = await extract_time_only(text)

    if not scheduled_time:
        await message.answer(
            "😕 Vaqtni aniqlay olmadim.\n"
            "<i>Masalan: 'Soat 15:00', '30 minutdan keyin'</i>",
            parse_mode="HTML",
            reply_markup=no_time_keyboard()
        )
        return

    # Vaqtni tegishli rejaga qo'shish
    current_plan_title = no_time_plans[current_index]["title"]
    for plan in plans:
        if plan["title"] == current_plan_title and not plan.get("scheduled_time"):
            plan["scheduled_time"] = scheduled_time
            break

    await message.answer(
        f"✅ <b>{current_plan_title}</b> — 🕐 {scheduled_time} ga belgilandi!",
        parse_mode="HTML"
    )

    await process_next_no_time_plan(message, state, current_index, plans)


# ─────────────────────────────────────────
#  VAQTSIZ SAQLASH TUGMASI
# ─────────────────────────────────────────

@router.callback_query(F.data == "save_without_time")
async def save_without_time(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    plans = data.get("plans", [])
    no_time_plans = data.get("no_time_plans", [])
    current_index = data.get("current_asking_index", 0)

    await callback.answer("🕐 Vaqtsiz saqlandi")
    await process_next_no_time_plan(callback, state, current_index, plans)


# ─────────────────────────────────────────
#  TASDIQLASH / BEKOR QILISH
# ─────────────────────────────────────────

@router.callback_query(F.data == "confirm_plans")
async def confirm_plans_handler(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    plans_data = data.get("plans", [])

    user = await get_user_by_telegram_id(session, callback.from_user.id)

    # ── Free-tier kunlik limit tekshiruvi ───────────────────────────
    from bot.services.premium_service import check_plan_limit
    from bot.keyboards.subscribe_keys import buy_subscription_keyboard

    limit = await check_plan_limit(session, user, adding=len(plans_data))
    if not limit.allowed:
        await state.clear()
        await callback.message.edit_text(
            "🔒 <b>Bugungi bepul limit tugadi</b>\n\n"
            f"Bepul rejimda kuniga <b>{limit.limit} tagacha</b> reja qo'shasiz.\n"
            f"Bugun ishlatildi: <b>{limit.used}/{limit.limit}</b>\n\n"
            "💎 <b>Premium</b> bilan ochiladi:\n"
            "• Cheksiz reja va maqsadlar\n"
            "• Mini App — kalendar, statistika, AI Coach\n"
            "• Streak Freeze va chuqur tahlil",
            parse_mode="HTML",
            reply_markup=buy_subscription_keyboard(),
        )
        await callback.answer("Bepul limit tugadi", show_alert=True)
        return

    # Bot orqali qo'shilgan rejalar HAR DOIM bugun uchun saqlanadi.
    # (Ertaga/boshqa kun uchun reja faqat WebApp orqali sana tanlab qo'shiladi.)
    for p in plans_data:
        p["for_tomorrow"] = False

    await create_plans(session, user, plans_data)
    await state.clear()

    all_plans = await get_today_plans(session, user)

    await callback.message.edit_text(
        f"✅ <b>Rejalar saqlandi!</b>\n\n{format_plan_list(all_plans)}",
        parse_mode="HTML",
        reply_markup=plan_list_actions_keyboard()
    )
    await callback.answer("Saqlandi! ✅")


@router.callback_query(F.data == "retry_plans")
async def retry_plans_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("🔄 Qaytadan yozing yoki ovozli xabar yuboring:")
    await callback.answer()


@router.callback_query(F.data == "cancel_plans")
async def cancel_plans_handler(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text("❌ Bekor qilindi.")
    await callback.answer()


# ─────────────────────────────────────────
#  REJALARIM
# ─────────────────────────────────────────

@router.message(F.text == "📋 Rejalarim")
async def my_plans_message(message: Message, session: AsyncSession):
    user = await get_user_by_telegram_id(session, message.from_user.id)
    plans = await get_today_plans(session, user)

    if not plans:
        await message.answer(
            "📭 <b>Bugun hech qanday reja yo'q.</b>\n\nYangi reja qo'shing!",
            parse_mode="HTML"
        )
        return

    await message.answer(
        format_plan_list(plans),
        parse_mode="HTML",
        reply_markup=plans_list_keyboard(plans)
    )


@router.callback_query(F.data == "my_plans")
async def my_plans_callback(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    plans = await get_today_plans(session, user)

    if not plans:
        await callback.message.edit_text(
            "📭 <b>Bugun hech qanday reja yo'q.</b>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="➕ Reja qo'sh", callback_data="add_plan")]
            ])
        )
    else:
        await callback.message.edit_text(
            format_plan_list(plans),
            parse_mode="HTML",
            reply_markup=plans_list_keyboard(plans)
        )
    await callback.answer()


# ─────────────────────────────────────────
#  REJA DETAIL + O'CHIRISH
# ─────────────────────────────────────────

@router.callback_query(F.data.startswith("plan_"))
async def plan_detail_handler(callback: CallbackQuery, session: AsyncSession):
    plan_id = int(callback.data.split("_")[1])
    plan = await get_plan_by_id(session, plan_id)

    if not plan:
        await callback.answer("Reja topilmadi!", show_alert=True)
        return

    status_text = {
        "pending": "⏳ Kutilmoqda",
        "done": "✅ Bajarildi",
        "failed": "❌ Bajarilmadi"
    }
    time_str = f"🕐 {plan.scheduled_time}" if plan.scheduled_time else "🕐 Eslatmasiz"

    text = (
        f"📌 <b>{plan.title}</b>\n\n"
        f"{time_str}\n"
        f"⭐️ Ball: <b>{plan.score_value}</b>\n"
        f"📊 Holat: <b>{status_text.get(plan.status.value, '⏳')}</b>"
    )
    if plan.description:
        text += f"\n📝 {plan.description}"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=plan_actions_keyboard(plan_id)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("delete_"))
async def delete_plan_handler(callback: CallbackQuery, session: AsyncSession):
    plan_id = int(callback.data.split("_")[1])
    plan = await get_plan_by_id(session, plan_id)

    if plan:
        if plan_block_reason(plan.plan_date, plan.scheduled_time) == "past":
            await callback.answer(
                "⏰ O'tib ketgan kundagi rejani o'chirib bo'lmaydi.", show_alert=True
            )
            return
        await delete_plan(session, plan)
        await callback.answer("🗑 O'chirildi!", show_alert=True)

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    plans = await get_today_plans(session, user)

    if plans:
        await callback.message.edit_text(
            format_plan_list(plans),
            parse_mode="HTML",
            reply_markup=plans_list_keyboard(plans)
        )
    else:
        await callback.message.edit_text("📭 Bugun hech qanday reja yo'q.", reply_markup=None)