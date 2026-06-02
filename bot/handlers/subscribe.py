"""
Obuna (premium) oqimi — to'lov tizimiga tayyorlangan.

Foydalanuvchi yo'li:
  1. "💎 Obuna" → tariflar ro'yxati + "🎟 Promokod kiritish" tugmasi
  2. (ixtiyoriy) Promokod kiritadi → agar admin yaratgan amaldagi kod bo'lsa,
     har bir tarifga promokoddagi bonus kunlar qo'shiladi ("1 oylik +15 kun")
  3. Tarifni tanlaydi → to'lov oynasi ochiladi
  4. "💳 To'lovni amalga oshirish" → (hozircha to'lov SIMULYATSIYA qilinadi)
     premium = tarif kunlari + promokod bonus kunlari muddatga ochiladi va DB ga
     shu muddat bilan saqlanadi.

Kelajakda to'lov kompaniyasi API qo'shilsa — faqat 4-bosqich (sub_pay_*) ichida
haqiqiy to'lov tasdiqlanishi tekshiriladi, qolgan oqim o'zgarmaydi.
"""
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
)
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession

from bot.config import SUBSCRIPTION_PLANS, FREE_DAILY_PLAN_LIMIT, PAYLOV_ENABLED
from bot.services.user_service import get_or_create_user, get_user_by_telegram_id
from bot.services.premium_service import (
    get_status,
    get_plan,
    format_price,
    validate_promocode,
    activate_subscription,
    increment_promocode_use,
    user_is_premium,
)
from bot.keyboards.subscribe_keys import (
    plans_keyboard,
    payment_keyboard,
    promocode_keyboard,
    premium_active_keyboard,
    PROVIDER_LABELS,
)

router = Router()
logger = logging.getLogger(__name__)


class SubscribeState(StatesGroup):
    waiting_promocode = State()


def _fmt_date(dt: datetime | None) -> str:
    if not dt:
        return "—"
    return dt.strftime("%d.%m.%Y")


async def render_subscription(
    message: Message,
    session: AsyncSession,
    telegram_id: int,
    bonus_days: int = 0,
    promo_code: str | None = None,
):
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
    free = bool(promo_code) and bonus_days == 0

    text = (
        "💎 <b>Intizom AI Premium</b>\n\n"
        "Premium bilan to'liq imkoniyatlar ochiladi:\n"
        "• <b>Mini App</b> — kalendar, statistika, AI Coach\n"
        "• Cheksiz reja va maqsadlar\n"
        "• Streak Freeze (streakni himoya qilish)\n"
        "• Chuqur tahlil va elite belgilar\n"
        "• Premium temalar\n\n"
        f"🆓 <b>Bepul rejim:</b> Mini App'siz, kuniga {FREE_DAILY_PLAN_LIMIT} tagacha reja.\n\n"
    )
    if free:
        text += (
            f"🎁 <b>Bepul promokod qabul qilindi:</b> <code>{promo_code}</code>\n"
            "Tarifni tanlang — <b>to'lovsiz</b> ochiladi! 🎉\n\n"
            "👇 Tarifni tanlang:"
        )
    elif bonus_days > 0 and promo_code:
        text += (
            f"🎟 <b>Promokod qabul qilindi:</b> <code>{promo_code}</code>\n"
            f"Har bir tarifga <b>+{bonus_days} kun</b> qo'shildi! 🎁\n\n"
            "👇 Tarifni tanlang:"
        )
    else:
        text += "👇 Tarifni tanlang:"

    await message.answer(
        text,
        parse_mode="HTML",
        reply_markup=plans_keyboard(
            bonus_days=bonus_days, promo_applied=bool(promo_code), free=free,
        ),
    )


async def _state_promo(state: FSMContext) -> tuple[int, str | None]:
    """FSM holatidan qo'llangan promokod bonusini o'qiydi."""
    data = await state.get_data()
    return int(data.get("promo_bonus_days") or 0), data.get("promo_code")


# ─────────────────────────────────────────────────────────────
#  KIRISH NUQTALARI
# ─────────────────────────────────────────────────────────────
@router.message(F.text == "💎 Obuna")
async def subscription_button(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()
    await render_subscription(message, session, message.from_user.id)


@router.callback_query(F.data == "open_subscription")
async def open_subscription_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    # State TOZALANMAYDI — qo'llangan promokod tariflarga qaytganda saqlanadi.
    bonus_days, promo_code = await _state_promo(state)
    await render_subscription(
        callback.message, session, callback.from_user.id,
        bonus_days=bonus_days, promo_code=promo_code,
    )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  PROMOKOD KIRITISH
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "sub_promo_enter")
async def promo_enter_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user_is_premium(user):
        await callback.answer("Sizda allaqachon faol obuna bor ✅", show_alert=True)
        return

    await state.set_state(SubscribeState.waiting_promocode)
    await callback.message.edit_text(
        "🎟 <b>Promokod kiriting</b>\n\n"
        "Sizda promokod bo'lsa — uni shu yerga matn ko'rinishida yuboring.\n"
        "Promokod tariflaringizga qo'shimcha kunlar qo'shadi 🎁",
        parse_mode="HTML",
        reply_markup=promocode_keyboard(),
    )
    await callback.answer()


@router.message(SubscribeState.waiting_promocode, F.text)
async def receive_promocode(message: Message, state: FSMContext, session: AsyncSession):
    code = (message.text or "").strip()
    result = await validate_promocode(session, code)

    if not result.valid:
        await message.answer(
            f"❌ <b>Promokod qabul qilinmadi.</b>\n\n"
            f"Sabab: <i>{result.reason}</i>\n\n"
            "Boshqa promokod kiriting yoki tariflarga qayting.",
            parse_mode="HTML",
            reply_markup=promocode_keyboard(),
        )
        return

    # Promokod qabul qilindi — bonusni holatga saqlaymiz (hali ishlatilmaydi)
    await state.update_data(promo_code=code, promo_bonus_days=int(result.bonus_days or 0))
    await state.set_state(None)  # tariflar bosqichiga qaytamiz (data saqlanadi)

    await render_subscription(
        message, session, message.from_user.id,
        bonus_days=int(result.bonus_days or 0), promo_code=code,
    )
    logger.info(f"🎟 Promokod qo'llandi: user={message.from_user.id} code={code} bonus={result.bonus_days}")


# ─────────────────────────────────────────────────────────────
#  TARIF TANLASH → TO'LOV OYNASI
# ─────────────────────────────────────────────────────────────
async def _finalize_subscription(callback, state, session, user, plan, plan_key, bonus_days, promo_code, free):
    """Obunani faollashtiradi, promokod hisobini oshiradi va xabar beradi."""
    source = "promo_free" if free else "card"
    sub = await activate_subscription(
        session, user,
        plan_key=plan_key,
        source=source,
        promocode=promo_code,
        bonus_days=bonus_days,
    )
    if promo_code:
        await increment_promocode_use(session, promo_code)

    await state.clear()

    if free:
        head = "🎁 <b>Bepul obuna faollashdi!</b>"
        extra = f" (promokod: <code>{promo_code}</code>)"
    else:
        head = "🎉 <b>Tabriklaymiz — Premium faollashdi!</b>"
        extra = f" (+{bonus_days} kun promokod)" if bonus_days > 0 else ""

    await callback.message.edit_text(
        f"{head}\n\n"
        f"📦 Tarif: <b>{plan['title']}</b>{extra}\n"
        f"📅 Amal qiladi: <b>{_fmt_date(sub.expires_at)} gacha</b>\n"
        f"⏳ Davomiylik: <b>{sub.days} kun</b>\n\n"
        "✨ Endi Mini App va barcha premium imkoniyatlar ochiq!\n"
        "Pastdagi tugma orqali Mini App'ni oching 👇",
        parse_mode="HTML",
        reply_markup=premium_active_keyboard(),
    )
    logger.info(
        f"💳 Obuna: user={user.telegram_id} plan={plan_key} bonus={bonus_days} "
        f"promo={promo_code} free={free}"
    )


@router.callback_query(F.data.startswith("sub_plan_"))
async def choose_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    plan_key = callback.data.replace("sub_plan_", "")
    plan = get_plan(plan_key)
    if not plan:
        await callback.answer("Tarif topilmadi!", show_alert=True)
        return

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.full_name, callback.from_user.username or "",
        )
    if user_is_premium(user):
        await callback.answer("Sizda allaqachon faol obuna bor ✅", show_alert=True)
        return

    bonus_days, promo_code = await _state_promo(state)

    # Promokod hali ham amaldami — qayta tekshiramiz
    if promo_code:
        recheck = await validate_promocode(session, promo_code)
        if recheck.valid:
            bonus_days = int(recheck.bonus_days or 0)
        else:
            bonus_days, promo_code = 0, None
            await state.update_data(promo_code=None, promo_bonus_days=0)

    free = bool(promo_code) and bonus_days == 0

    # BEPUL promokod (bonus_days=0) → to'lovsiz darhol ochamiz
    if free:
        await _finalize_subscription(
            callback, state, session, user, plan, plan_key, 0, promo_code, free=True
        )
        await callback.answer("Bepul obuna ochildi 🎁")
        return

    # Aks holda — to'lov oynasi
    total_days = plan["days"] + bonus_days
    bonus_line = f" <b>+{bonus_days} kun</b> (promokod)" if bonus_days > 0 else ""
    if PAYLOV_ENABLED:
        note = (
            "💳 <b>To'lov usulini tanlang</b> 👇\n"
            "To'lov muvaffaqiyatli bo'lgach, premium <b>avtomatik</b> ochiladi 🔔"
        )
    else:
        note = (
            "<i>💳 To'lov tizimi tez orada ulanadi. Hozircha obunani admin yoki "
            "promokod orqali ochishingiz mumkin.</i>"
        )
    text = (
        "💳 <b>To'lov</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📦 Tarif: <b>{plan['title']}</b>{bonus_line}\n"
        f"📅 Muddat: <b>{total_days} kun</b>\n"
        f"💰 Narx: <b>{format_price(plan['price'])} so'm</b>\n\n"
        f"{note}"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=payment_keyboard(plan_key),
    )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  TO'LOV — Paylov checkout (sozlanmagan bo'lsa simulyatsiya)
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data.startswith("sub_pay_"))
async def pay_plan(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    # callback format: sub_pay_<plan_key>_<provider>  (provider ixtiyoriy).
    # Tarif kalitlari (7d/1m/3m/6m/12m) va provayder nomlari '_' tutmaydi,
    # shuning uchun oxirgi '_' bo'yicha ajratamiz.
    from bot.config import PAYLOV_PROVIDERS
    raw = callback.data.replace("sub_pay_", "")
    provider = None
    if "_" in raw:
        plan_key, maybe_provider = raw.rsplit("_", 1)
        if maybe_provider in PAYLOV_PROVIDERS:
            provider = maybe_provider
        else:
            plan_key = raw  # provayder noma'lum — butun qism tarif kaliti
    else:
        plan_key = raw

    plan = get_plan(plan_key)
    if not plan:
        await callback.answer("Tarif topilmadi!", show_alert=True)
        return

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.full_name, callback.from_user.username or "",
        )
    if user_is_premium(user):
        await callback.answer("Sizda allaqachon faol obuna bor ✅", show_alert=True)
        return

    bonus_days, promo_code = await _state_promo(state)

    # Promokod hali ham amaldami — qayta tekshiramiz (xavfsizlik uchun)
    if promo_code:
        recheck = await validate_promocode(session, promo_code)
        bonus_days = int(recheck.bonus_days or 0) if recheck.valid else 0
        if not recheck.valid:
            promo_code = None

    # ── To'lov tizimi hali sozlanmagan (kalitlar yo'q) — Phase 1 ──
    # Tugma bosilsa hech narsa faollashtirilmaydi (bepul premium berilmaydi).
    if not PAYLOV_ENABLED:
        await callback.answer(
            "💳 To'lov tizimi tez orada ulanadi. Obuna admin yoki promokod orqali ochiladi.",
            show_alert=True,
        )
        return

    # ── Haqiqiy Paylov checkout ──────────────────────────────
    from bot.services.payment_service import create_checkout_order
    from bot.services.paylov import PaylovError
    try:
        order, checkout_url = await create_checkout_order(
            session, user, plan_key, bonus_days=bonus_days, promo_code=promo_code,
            provider=provider,
        )
    except (PaylovError, Exception) as e:
        logger.error(f"❌ Checkout yaratishda xato: {type(e).__name__}: {e}")
        await callback.answer("To'lov sahifasini ochib bo'lmadi. Birozdan so'ng urinib ko'ring.", show_alert=True)
        return

    if not checkout_url:
        await callback.answer("To'lov sahifasi olinmadi. Birozdan so'ng urinib ko'ring.", show_alert=True)
        return

    total_days = plan["days"] + bonus_days
    bonus_line = f" <b>+{bonus_days} kun</b> (promokod)" if bonus_days > 0 else ""
    prov_label = PROVIDER_LABELS.get(order.provider, order.provider.capitalize())
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 {prov_label} orqali to'lash", url=checkout_url)],
        [InlineKeyboardButton(text="🔙 Tariflarga qaytish", callback_data="open_subscription")],
    ])
    await callback.message.edit_text(
        "💳 <b>To'lovga tayyor</b>\n"
        "━━━━━━━━━━━━━━━\n"
        f"📦 Tarif: <b>{plan['title']}</b>{bonus_line}\n"
        f"🏦 To'lov usuli: <b>{prov_label}</b>\n"
        f"📅 Muddat: <b>{total_days} kun</b>\n"
        f"💰 Narx: <b>{format_price(plan['price'])} so'm</b>\n\n"
        f"Quyidagi <b>«💳 {prov_label} orqali to'lash»</b> tugmasi orqali to'lovni yakunlang.\n"
        "To'lov muvaffaqiyatli bo'lgach, <b>premium avtomatik ochiladi</b> va "
        "sizga xabar keladi 🔔",
        parse_mode="HTML",
        reply_markup=kb,
    )
    # To'lov xabari id'sini saqlaymiz — to'lov muvaffaqiyatli bo'lgach webhook
    # bu xabarni o'chiradi (foydalanuvchiga keraksiz "To'lovga tayyor" qolmasin).
    try:
        order.pay_message_id = callback.message.message_id
        await session.commit()
    except Exception:
        pass
    await callback.answer()


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
