"""
Obuna (premium) oqimi.

Foydalanuvchi yo'li:
  1. "💎 Obuna" tugmasi yoki paywall'dagi tugma → obuna sahifasi
  2. Plan tanlaydi (1/3/6/12 oy)
  3. Promokod so'raladi
  4. To'g'ri promokod ("intizom") yuborsa — obuna faollashadi
  5. Faol obunasi bo'lsa — sotib olish tugmalari ko'rsatilmaydi (faqat holat)

Kelajakda karta to'lovi qo'shilsa — faqat 3→4 bosqich o'zgaradi.
"""
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import PROMO_CODE, SUBSCRIPTION_PLANS, FREE_DAILY_PLAN_LIMIT
from bot.services.user_service import get_or_create_user, get_user_by_telegram_id
from bot.services.premium_service import (
    get_status,
    get_plan,
    format_price,
    redeem_with_promocode,
)
from bot.keyboards.subscribe_keys import (
    plans_keyboard,
    promocode_keyboard,
    premium_active_keyboard,
)

router = Router()
logger = logging.getLogger(__name__)


class SubscribeState(StatesGroup):
    choosing_plan = State()
    waiting_promocode = State()


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y")


async def render_subscription(message: Message, session: AsyncSession, telegram_id: int):
    """Obuna sahifasini ko'rsatadi (holatga qarab)."""
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        user = await get_or_create_user(
            session, telegram_id, message.chat.full_name or "", ""
        )

    status = await get_status(session, user)

    if status.is_premium:
        # Faol obuna — sotib olish tugmalari YO'Q
        text = (
            "💎 <b>Premium faol!</b>\n\n"
            f"📦 Tarif: <b>{status.plan_title or 'Premium'}</b>\n"
            f"📅 Tugaydi: <b>{_fmt_date(status.premium_until)}</b>\n"
            f"⏳ Qolgan kun: <b>{status.days_left} kun</b>\n\n"
            "✨ Sizda barcha imkoniyatlar ochiq:\n"
            "• Cheksiz reja va maqsadlar\n"
            "• Mini App (kalendar, statistika, AI Coach)\n"
            "• Streak Freeze va chuqur tahlil\n\n"
            "Rahmat! Intizomingiz davom etsin 🔥"
        )
        await message.answer(
            text, parse_mode="HTML", reply_markup=premium_active_keyboard()
        )
        return

    # Bepul foydalanuvchi — planlarni taklif qilamiz
    text = (
        "💎 <b>Intizom AI Premium</b>\n\n"
        "Premium bilan to'liq imkoniyatlar ochiladi:\n"
        "• <b>Mini App</b> — kalendar, statistika, AI Coach\n"
        "• Cheksiz reja va maqsadlar\n"
        "• Streak Freeze (streakni himoya qilish)\n"
        "• Chuqur tahlil va elite belgilar\n"
        "• Premium temalar\n\n"
        f"🆓 <b>Bepul rejim:</b> Mini App'siz, kuniga {FREE_DAILY_PLAN_LIMIT} tagacha reja.\n\n"
        "👇 Tarifni tanlang:"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=plans_keyboard())


# ─────────────────────────────────────────────────────────────
#  KIRISH NUQTALARI
# ─────────────────────────────────────────────────────────────
@router.message(F.text == "💎 Obuna")
async def subscription_button(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    await render_subscription(message, session, message.from_user.id)


@router.callback_query(F.data == "open_subscription")
async def open_subscription_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    await state.clear()
    await render_subscription(callback.message, session, callback.from_user.id)
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  PLAN TANLASH
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("sub_plan_"))
async def choose_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    plan_key = callback.data.replace("sub_plan_", "")
    plan = get_plan(plan_key)
    if not plan:
        await callback.answer("Tarif topilmadi!", show_alert=True)
        return

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user.premium_until and user.premium_until > datetime.utcnow():
        # Allaqachon premium — qayta sotib olishga yo'l qo'ymaymiz
        await callback.answer("Sizda allaqachon faol obuna bor ✅", show_alert=True)
        return

    await state.update_data(plan_key=plan_key)
    await state.set_state(SubscribeState.waiting_promocode)

    await callback.message.edit_text(
        f"💎 <b>{plan['title']}</b> tanlandi\n"
        f"💰 Narx: <b>{format_price(plan['price'])} so'm</b>\n"
        f"📅 Davomiyligi: <b>{plan['days']} kun</b>\n\n"
        "🎟 <b>Promokodni kiriting:</b>\n"
        f"<i>(sinov bosqichi uchun: <code>{PROMO_CODE}</code>)</i>\n\n"
        "Promokodni shu yerga matn ko'rinishida yuboring.",
        parse_mode="HTML",
        reply_markup=promocode_keyboard(),
    )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  PROMOKOD QABUL QILISH
# ─────────────────────────────────────────────────────────────
@router.message(SubscribeState.waiting_promocode, F.text)
async def receive_promocode(message: Message, state: FSMContext, session: AsyncSession):
    data = await state.get_data()
    plan_key = data.get("plan_key")
    if not plan_key:
        await state.clear()
        await render_subscription(message, session, message.from_user.id)
        return

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        user = await get_or_create_user(
            session, message.from_user.id, message.from_user.full_name, message.from_user.username or ""
        )

    code = (message.text or "").strip()
    success, reason, sub = await redeem_with_promocode(session, user, plan_key, code)

    if not success:
        await message.answer(
            f"❌ <b>Promokod qabul qilinmadi.</b>\n\n"
            f"Sabab: <i>{reason}</i>\n\n"
            "Qaytadan urinib ko'ring yoki bekor qiling.",
            parse_mode="HTML",
            reply_markup=promocode_keyboard(),
        )
        return

    await state.clear()
    plan = SUBSCRIPTION_PLANS.get(sub.plan, {})
    await message.answer(
        "🎉 <b>Tabriklaymiz — Premium faollashdi!</b>\n\n"
        f"📦 Tarif: <b>{plan.get('title', sub.plan)}</b>\n"
        f"📅 Amal qiladi: <b>{_fmt_date(sub.expires_at)} gacha</b>\n"
        f"⏳ Davomiylik: <b>{sub.days} kun</b>\n\n"
        "✨ Endi Mini App va barcha premium imkoniyatlar ochiq!\n"
        "Pastdagi tugma orqali Mini App'ni oching 👇",
        parse_mode="HTML",
        reply_markup=premium_active_keyboard(),
    )
    logger.info(f"🎟 Promokod ishlatildi: user={user.telegram_id} code={code} plan={sub.plan}")


# ─────────────────────────────────────────────────────────────
#  BEKOR QILISH
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sub_cancel")
async def cancel_subscription(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.edit_text(
        "❌ Obuna jarayoni bekor qilindi.\n\n"
        "Istalgan vaqtda «💎 Obuna» tugmasi orqali qaytishingiz mumkin.",
        parse_mode="HTML",
    )
    await callback.answer()
