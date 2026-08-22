"""
Obuna (premium) oqimi — to'lov tizimiga tayyorlangan.

Foydalanuvchi yo'li:
  1. "💎 Premium" → tariflar ro'yxati + "🎟 Promokod kiritish" tugmasi
  2. (ixtiyoriy) Promokod kiritadi. Promokod 2 xil bo'ladi:
     • `+` (is_free=False) → foydalanuvchi obunani SOTIB OLADI; har bir tarifga
       promokoddagi bonus kunlar qo'shiladi ("1 oylik +15 kun").
     • `-` (is_free=True) → foydalanuvchi obuna sotib olmaydi; kod kiritilishi
       bilan unga bonus_kun ta kunga premium AVTOMATIK (to'lovsiz) ochiladi.
  3. `+` turi: tarifni tanlaydi → to'lov oynasi ochiladi
  4. "💳 To'lovni amalga oshirish" → to'lov muvaffaqiyatli bo'lgach premium =
     tarif kunlari + promokod bonus kunlari muddatga ochiladi va DB ga saqlanadi.

Kelajakda to'lov kompaniyasi API qo'shilsa — faqat 4-bosqich (sub_pay_*) ichida
haqiqiy to'lov tasdiqlanishi tekshiriladi, qolgan oqim o'zgarmaydi.
"""
import logging
from datetime import datetime

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.filters import Command
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
    grant_bonus_premium,
    increment_promocode_use,
    user_is_premium,
)
from bot.keyboards.subscribe_keys import (
    plans_keyboard,
    payment_keyboard,
    promocode_keyboard,
    premium_active_keyboard,
    premium_promo_keyboard,
    free_premium_keyboard,
    referral_share_keyboard,
    PROVIDER_LABELS,
)
from bot.services.referral_service import (
    get_bot_username,
    build_referral_link,
    get_referral_stats,
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
    force_plans: bool = False,
):
    """
    Obuna sahifasini ko'rsatadi (holatga qarab).

    `force_plans=True` bo'lsa — foydalanuvchi allaqachon premium bo'lsa ham
    tariflar ro'yxati ko'rsatiladi (obunani UZAYTIRISH oqimi). Yangi kunlar
    mavjud premium tugash sanasi ustiga qo'shiladi (`activate_subscription`
    ichida hisoblanadi).
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        user = await get_or_create_user(
            session, telegram_id, message.chat.full_name or "", ""
        )

    status = await get_status(session, user)

    if status.is_premium and not force_plans:
        # Faol obuna — asosiy holatda sotib olish tugmalari YO'Q,
        # lekin "💳 Obunani uzaytirish" tugmasi orqali qayta kirsa bo'ladi.
        text = (
            "💎 <b>Premium faol!</b>\n\n"
            f"📦 Tarif: <b>{status.plan_title or 'Premium'}</b>\n"
            f"📅 Tugaydi: <b>{_fmt_date(status.premium_until)}</b>\n"
            f"⏳ Qolgan kun: <b>{status.days_left} kun</b>\n\n"
            "✨ Sizda barcha imkoniyatlar ochiq:\n"
            "• Cheksiz reja, maqsad va odat\n"
            "• Cheksiz AI Coach suhbat\n"
            "• Mini App (kalendar, statistika)\n\n"
            "Rahmat! Intizomingiz davom etsin 🔥"
        )
        await message.answer(
            text, parse_mode="HTML", reply_markup=premium_active_keyboard()
        )
        return

    # Tariflar ro'yxati (yangi obuna YOKI uzaytirish).
    # Eslatma: bepul (`-`) promokodlar bu yerga kelmaydi — ular kiritilishi
    # bilan darhol (to'lovsiz) faollashtiriladi (receive_promocode ichida).
    if status.is_premium and force_plans:
        # UZAYTIRISH matnli sarlavha — foydalanuvchi bilishi kerak: kunlar
        # mavjud obuna tugash sanasi USTIGA qo'shiladi.
        text = (
            "💎 <b>Obunani uzaytirish</b>\n\n"
            f"📅 Joriy tugash: <b>{_fmt_date(status.premium_until)}</b>\n"
            f"⏳ Qolgan kun: <b>{status.days_left} kun</b>\n\n"
            "Yangi kunlar joriy obuna tugash sanasi <b>ustiga qo'shiladi</b> — "
            "ya'ni premium uzaytiriladi, boshqattan boshlanmaydi. ✅\n\n"
        )
    else:
        text = (
            "💎 <b>Intizom AI Premium</b>\n\n"
            "Premium bilan ochiladi:\n"
            "• <b>Cheksiz reja, maqsad va odat</b>\n"
            "• <b>Cheksiz AI Coach</b> suhbat (bepulda kuniga 3 ta)\n"
            "• Mini App — kalendar va statistika\n\n"
            f"🆓 <b>Bepul rejim:</b> kuniga {FREE_DAILY_PLAN_LIMIT} ta reja, 3 ta maqsad, "
            "3 ta odat va 3 ta AI xabar.\n\n"
        )
    if bonus_days > 0 and promo_code:
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
            bonus_days=bonus_days, promo_applied=bool(promo_code),
        ),
    )


async def _state_promo(state: FSMContext) -> tuple[int, str | None]:
    """FSM holatidan qo'llangan promokod bonusini o'qiydi."""
    data = await state.get_data()
    return int(data.get("promo_bonus_days") or 0), data.get("promo_code")


async def open_premium_flow(
    message: Message,
    session: AsyncSession,
    telegram_id: int,
    plan_key: str | None = None,
) -> None:
    """
    Deep-link (`/start premium` yoki `/start premium_<plan>`) orqali chaqiriladi.

    Mini App'da tarif tanlagan foydalanuvchi shu funksiya orqali bot ichida
    to'g'ridan-to'g'ri kerakli bosqichga tushadi:

      • plan_key BERILGAN va yaroqli → to'lov usulini tanlash oynasi (payment
        method chooser). Foydalanuvchi bir bosishda to'lov provayderini tanlab,
        Paylov checkoutga o'tadi.

      • plan_key YO'Q yoki yaroqsiz → oddiy Premium menyusi:
          - obunali user → uzaytirish uchun tariflar ro'yxati
          - obunasi yo'q user → sotib olish uchun tariflar ro'yxati

    Bu funksiya `Message` orqali javob yuboradi (edit_text emas) — chunki u
    `/start` xabaridan chaqiriladi va xabar YANGI bo'ladi.
    """
    user = await get_user_by_telegram_id(session, telegram_id)
    if not user:
        # /start ichida user allaqachon yaratilgan bo'lishi kerak; ehtiyot uchun.
        user = await get_or_create_user(
            session, telegram_id,
            message.from_user.full_name if message.from_user else "",
            (message.from_user.username or "") if message.from_user else "",
        )

    is_premium = user_is_premium(user)
    plan = get_plan(plan_key) if plan_key else None

    # Plan yo'q yoki yaroqsiz — tariflar ro'yxatini ochamiz.
    if not plan:
        # Premium bo'lsa force_plans=True bilan uzaytirish ro'yxati chiqadi.
        await render_subscription(
            message, session, telegram_id,
            force_plans=is_premium,
        )
        return

    # Aniq plan berilgan — to'lov usulini tanlash oynasini ko'rsatamiz.
    total_days = plan["days"]
    if PAYLOV_ENABLED:
        note_new = (
            "💳 <b>To'lov usulini tanlang</b> 👇\n"
            "To'lov muvaffaqiyatli bo'lgach, premium <b>avtomatik</b> ochiladi 🔔"
        )
        note_extend = (
            "💳 <b>To'lov usulini tanlang</b> 👇\n"
            "To'lov muvaffaqiyatli bo'lgach, ushbu kunlar <b>joriy obuna tugash "
            "sanasi ustiga qo'shiladi</b> 🔁"
        )
        note = note_extend if is_premium else note_new
    else:
        note = (
            "<i>💳 To'lov tizimi tez orada ulanadi. Hozircha obunani admin yoki "
            "promokod orqali ochishingiz mumkin.</i>"
        )
    title_line = "💳 <b>Obunani uzaytirish</b>" if is_premium else "💳 <b>To'lov</b>"
    text = (
        f"{title_line}\n"
        "━━━━━━━━━━━━━━━\n"
        f"📦 Tarif: <b>{plan['title']}</b>\n"
        f"📅 Qo'shiladigan kun: <b>{total_days} kun</b>\n"
        f"💰 Narx: <b>{format_price(plan['price'])} so'm</b>\n\n"
        f"{note}"
    )
    await message.answer(
        text, parse_mode="HTML", reply_markup=payment_keyboard(plan_key),
    )


# ─────────────────────────────────────────────────────────────
#  KIRISH NUQTALARI
# ─────────────────────────────────────────────────────────────
# "💎 Premium" reply tugmasi va /premium buyrug'i faqat DM chatlarda ishlaydi.
# Guruhda bu tugma matni yoki buyruq bo'lsa ham bot javob bermaydi (guruhda
# faqat "Umumiy hisobot" va "Bog'lanish" tugmalari mavjud).
# Decorator stacking: bir funksiya ikkala trigger ostida ham ishlaydi.
@router.message(Command("premium"), F.chat.type == ChatType.PRIVATE)
@router.message(F.text == "💎 Premium", F.chat.type == ChatType.PRIVATE)
async def subscription_button(message: Message, state: FSMContext, session: AsyncSession):
    await state.clear()

    user = await get_user_by_telegram_id(session, message.from_user.id)
    if not user:
        user = await get_or_create_user(
            session, message.from_user.id,
            message.from_user.full_name, message.from_user.username or "",
        )

    if user_is_premium(user):
        # Faol obuna — joriy obuna ma'lumotini ko'rsatamiz.
        await render_subscription(message, session, message.from_user.id)
        return

    # Obunasiz — qisqa promo + 2 variant (sotib olish / Premium haqida).
    await message.answer(
        "💎 <b>Premium</b>\n\n"
        "Premium bilan <b>cheksiz</b> reja, maqsad, odat va AI Coach ochiladi.\n\n"
        "Quyidagidan birini tanlang 👇",
        parse_mode="HTML",
        reply_markup=premium_promo_keyboard(),
    )


@router.callback_query(F.data == "open_subscription")
async def open_subscription_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    # State TOZALANMAYDI — qo'llangan promokod tariflarga qaytganda saqlanadi.
    bonus_days, promo_code = await _state_promo(state)
    await render_subscription(
        callback.message, session, callback.from_user.id,
        bonus_days=bonus_days, promo_code=promo_code,
    )
    await callback.answer()


@router.callback_query(F.data == "sub_extend")
async def sub_extend_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """
    «💳 Obunani uzaytirish» — premium foydalanuvchi allaqachon obunali bo'lsa ham
    tariflar ro'yxati chiqadi. To'lovdan so'ng kunlar mavjud tugash sanasi ustiga
    additiv qo'shiladi (activate_subscription ichida).
    """
    bonus_days, promo_code = await _state_promo(state)
    await render_subscription(
        callback.message, session, callback.from_user.id,
        bonus_days=bonus_days, promo_code=promo_code,
        force_plans=True,
    )
    await callback.answer()


# ─────────────────────────────────────────────────────────────
#  BEPUL PREMIUM — DO'ST TAKLIF QILISH (REFERRAL)
# ─────────────────────────────────────────────────────────────
# Do'stlar bilan ulashish uchun yagona reklama matni. Bot va Mini App shu
# matnni bir xil ko'rinishda ulashadi. Foydalanuvchi tomonidan forward
# qilinadi; tagidagi tugma botga taklif havolasi orqali olib o'tadi.
REFERRAL_SHARE_TEXT = (
    "Siz Intizomlimisiz ⁉️\n\n"
    "📚 Kitob o'qish bilim beradi.\n\n"
    "💡Lekin bilimni natijaga aylantiradigan narsa — intizom.\n\n"
    "Ko'pchilik:\n"
    "❌ Maqsad qo'yadi\n"
    "❌ Reja tuzadi\n"
    "❌ Lekin oxirigacha yetib bormaydi\n\n"
    "⌛️ IntizomAi esa sizning maqsadlaringiz, rejalaringiz va odatlaringizni "
    "kuzatib boradi.\n\n"
    "🧠 AI vaqt o'tishi bilan sizni o'rganadi:\n"
    "✅ Progressingizni kuzatadi\n"
    "✅ Odatlaringizni tahlil qiladi\n"
    "✅ Sizga mos tavsiyalar beradi\n\n"
    "📊 Statistika\n"
    "⚡️ Maqsadlar\n"
    "⌛️ Eslatmalar\n"
    "🤖 AI mentor\n\n"
    "🌐 Hammasi bitta qulay Web App ichida.\n\n"
    "⭐️ Bilim + Intizom = Natija"
)


@router.callback_query(F.data == "premium_menu")
async def premium_menu_cb(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """«Bepul premium» ekranidan «💎 Premium» menyusiga qaytish."""
    await state.clear()
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and user_is_premium(user):
        status = await get_status(session, user)
        await callback.message.edit_text(
            "💎 <b>Premium faol!</b>\n\n"
            f"📅 Tugaydi: <b>{_fmt_date(status.premium_until)}</b>\n"
            f"⏳ Qolgan kun: <b>{status.days_left} kun</b>\n\n"
            "Do'st taklif qilib premiumingizni uzaytiring yoki Mini App'ni oching 👇",
            parse_mode="HTML",
            reply_markup=premium_active_keyboard(),
        )
    else:
        await callback.message.edit_text(
            "💎 <b>Premium</b>\n\n"
            "Premium bilan <b>cheksiz</b> reja va maqsadlar, cheksiz AI Coach, "
            "Streak Freeze va premium temalar ochiladi.\n\nQuyidagidan birini tanlang 👇",
            parse_mode="HTML",
            reply_markup=premium_promo_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "free_premium")
async def free_premium_cb(callback: CallbackQuery, session: AsyncSession):
    """Bepul premium ekranini ko'rsatadi (taklif qilib mukofot olish)."""
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        user = await get_or_create_user(
            session, callback.from_user.id,
            callback.from_user.full_name, callback.from_user.username or "",
        )

    from bot.config import REFERRAL_INVITEE_REWARD_DAYS, REFERRAL_REWARD_DAYS
    stats = await get_referral_stats(session, user)

    text = (
        "🎁 <b>Bepul Premium olish</b>\n\n"
        "Taklif qilgan do'stingiz birinchi rejasini bajarsa:\n"
        f"• <b>Unga</b> — <b>{REFERRAL_INVITEE_REWARD_DAYS} kun</b> Premium sovg'a\n"
        f"• <b>Sizga</b> — har <b>{stats.threshold} ta faol do'st</b> uchun "
        f"<b>{REFERRAL_REWARD_DAYS} kun</b> Premium\n\n"
        f"📊 Faol takliflaringiz: <b>{stats.total} ta</b>\n"
        f"🎯 Keyingi {REFERRAL_REWARD_DAYS} kunlik Premiumgacha: <b>{stats.remaining} ta</b> faol do'st qoldi\n"
    )
    if stats.rewards_count > 0:
        text += f"🏆 Olingan bepul Premiumlar: <b>{stats.rewards_count} ta</b>\n"
    text += (
        "\nQuyidagi tugma orqali shaxsiy havolangizni oling va ulashing 👇"
    )

    try:
        await callback.message.edit_text(
            text, parse_mode="HTML", reply_markup=free_premium_keyboard(),
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="HTML", reply_markup=free_premium_keyboard(),
        )
    await callback.answer()


@router.callback_query(F.data == "referral_link")
async def referral_link_cb(callback: CallbackQuery, session: AsyncSession):
    """
    Shaxsiy taklif havolasi bilan ulashiladigan reklama xabarini yuboradi.

    Bir xillik uchun bot va Mini App ikkalasi ham AYNAN bir xil xabarni
    ko'rsatadi: reklama matni + botga olib boradigan deep-link tugmasi.
    """
    username = await get_bot_username(callback.bot)
    link = build_referral_link(username, callback.from_user.id)

    # Yagona xabar — ulashish/forward qilish uchun tayyor. Bot va Mini Appda
    # bir xil, ortiqcha "havola tayyor" xabari yo'q.
    await callback.message.answer(
        REFERRAL_SHARE_TEXT,
        parse_mode="HTML",
        reply_markup=referral_share_keyboard(link),
        disable_web_page_preview=True,
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

    # ── `-` turi (bepul): obuna sotib olinmaydi — darhol avtomatik ochamiz ──
    if result.is_free:
        user = await get_user_by_telegram_id(session, message.from_user.id)
        if not user:
            user = await get_or_create_user(
                session, message.from_user.id,
                message.from_user.full_name, message.from_user.username or "",
            )
        if user_is_premium(user):
            await message.answer(
                "✅ Sizda allaqachon faol obuna bor. Promokod ishlatilmadi.",
                parse_mode="HTML",
                reply_markup=premium_active_keyboard(),
            )
            await state.clear()
            return

        bonus_days = int(result.bonus_days or 0)
        sub = await grant_bonus_premium(
            session, user, bonus_days, source="promo_free", promocode=code,
        )
        await increment_promocode_use(session, code)
        await state.clear()

        await message.answer(
            "🎁 <b>Bepul premium faollashdi!</b>\n\n"
            f"🎟 Promokod: <code>{code}</code>\n"
            f"📅 Amal qiladi: <b>{_fmt_date(sub.expires_at)} gacha</b>\n"
            f"⏳ Davomiylik: <b>{sub.days} kun</b>\n\n"
            "✨ Endi Mini App va barcha premium imkoniyatlar ochiq!\n"
            "Pastdagi tugma orqali Mini App'ni oching 👇",
            parse_mode="HTML",
            reply_markup=premium_active_keyboard(),
        )
        logger.info(
            f"🎁 Bepul promokod faollashdi: user={message.from_user.id} "
            f"code={code} days={bonus_days}"
        )
        return

    # ── `+` turi (sotib olish + bonus): bonusni holatga saqlaymiz ──
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
    # Diqqat: premium foydalanuvchi bu yerga UZAYTIRISH oqimi orqali ham kelishi
    # mumkin. Shuning uchun bloklamaymiz — `activate_subscription` mavjud premium
    # tugash sanasi USTIGA kunlarni additiv qo'shadi.
    is_extending = user_is_premium(user)

    bonus_days, promo_code = await _state_promo(state)

    # Promokod hali ham amaldami — qayta tekshiramiz.
    # Bu bosqichga faqat `+` (sotib olish) turidagi promokodlar keladi; bepul
    # (`-`) turdagilar kiritilishi bilan darhol faollashtirilgan bo'ladi.
    if promo_code:
        recheck = await validate_promocode(session, promo_code)
        if recheck.valid and not recheck.is_free:
            bonus_days = int(recheck.bonus_days or 0)
        else:
            bonus_days, promo_code = 0, None
            await state.update_data(promo_code=None, promo_bonus_days=0)

    # To'lov oynasi (obuna sotib olinadi yoki uzaytiriladi)
    total_days = plan["days"] + bonus_days
    bonus_line = f" <b>+{bonus_days} kun</b> (promokod)" if bonus_days > 0 else ""
    if PAYLOV_ENABLED:
        note_open = (
            "💳 <b>To'lov usulini tanlang</b> 👇\n"
            "To'lov muvaffaqiyatli bo'lgach, premium <b>avtomatik</b> ochiladi 🔔"
        )
        note_extend = (
            "💳 <b>To'lov usulini tanlang</b> 👇\n"
            "To'lov muvaffaqiyatli bo'lgach, ushbu kunlar <b>joriy obuna tugash "
            "sanasi ustiga qo'shiladi</b> 🔁"
        )
        note = note_extend if is_extending else note_open
    else:
        note = (
            "<i>💳 To'lov tizimi tez orada ulanadi. Hozircha obunani admin yoki "
            "promokod orqali ochishingiz mumkin.</i>"
        )
    title_line = "💳 <b>Obunani uzaytirish</b>" if is_extending else "💳 <b>To'lov</b>"
    text = (
        f"{title_line}\n"
        "━━━━━━━━━━━━━━━\n"
        f"📦 Tarif: <b>{plan['title']}</b>{bonus_line}\n"
        f"📅 Qo'shiladigan kun: <b>{total_days} kun</b>\n"
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
    # Premium foydalanuvchini bloklamaymiz — uzaytirish oqimi orqali bu yerga
    # kelishi mumkin. `activate_subscription` webhook'da kunlarni mavjud tugash
    # sanasi ustiga additiv qo'shadi.

    bonus_days, promo_code = await _state_promo(state)

    # Promokod hali ham amaldami — qayta tekshiramiz (xavfsizlik uchun).
    # Bepul (`-`) turdagi kod to'lov oqimiga umuman ta'sir qilmasligi kerak.
    if promo_code:
        recheck = await validate_promocode(session, promo_code)
        if recheck.valid and not recheck.is_free:
            bonus_days = int(recheck.bonus_days or 0)
        else:
            bonus_days, promo_code = 0, None

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
        "Istalgan vaqtda «💎 Premium» tugmasi orqali qaytishingiz mumkin.",
        parse_mode="HTML",
    )
    await callback.answer()
