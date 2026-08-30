from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.types import Message, CallbackQuery
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from sqlalchemy.ext.asyncio import AsyncSession
import asyncio

from bot.services.admin_service import (
    is_admin, get_all_users, get_users_count,
    get_all_admins, add_admin, remove_admin,
    get_user_plan_stats, get_user_status
)
from bot.services.user_service import get_user_by_telegram_id
from bot.keyboards.admin_keys import (
    admin_main_keyboard, admin_users_keyboard,
    admin_users_list_keyboard, admin_admins_keyboard,
    back_to_admin_keyboard, back_to_users_keyboard,
    admin_premium_keyboard, back_to_premium_keyboard,
    admin_premium_users_list_keyboard, back_to_premium_users_keyboard,
    admin_promo_list_keyboard,
    admin_plans_prices_keyboard, admin_plan_edit_keyboard,
    admin_keys_keyboard, admin_keys_confirm_keyboard,
    admin_webapp_keyboard,
)

router = Router()


class AdminState(StatesGroup):
    waiting_admin_id_add = State()
    waiting_admin_id_remove = State()
    # Broadcast
    broadcast_choosing = State()      # Umumiy yoki ID
    broadcast_waiting_id = State()    # ID kutish
    broadcast_waiting_text = State()  # Xabar matni kutish
    # Premium
    premium_grant = State()           # "ID plan" kutish
    premium_revoke = State()          # ID kutish
    promo_create = State()            # promokod yaratish
    promo_discount_create = State()    # maxsus (chegirmali) promokod yaratish
    # Tarif narxini o'zgartirish (yangi narxni so'mda kutish)
    plan_price_edit = State()
    # To'lovni qo'lda faollashtirish (external_id yoki payment_id orqali)
    payment_activate = State()


def broadcast_type_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📢 Barcha userlarga", callback_data="broadcast_all"),
            InlineKeyboardButton(text="👤 ID orqali", callback_data="broadcast_by_id"),
        ],
        [
            InlineKeyboardButton(text="🔙 Orqaga", callback_data="admin_panel")
        ]
    ])


def broadcast_confirm_keyboard():
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Yuborish", callback_data="broadcast_send"),
            InlineKeyboardButton(text="❌ Bekor", callback_data="admin_panel"),
        ]
    ])


# ===================== KIRISH =====================

@router.message(Command("admin"), F.chat.type == ChatType.PRIVATE)
async def admin_panel(message: Message, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        await message.answer("❌ Sizda admin huquqi yo'q.")
        return

    await message.answer(
        "🛡 <b>Admin Panel</b>\n\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )


@router.callback_query(F.data == "admin_panel")
async def admin_panel_callback(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await state.clear()
    await callback.message.edit_text(
        "🛡 <b>Admin Panel</b>\n\nKerakli bo'limni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_main_keyboard()
    )
    await callback.answer()


# ===================== 🌐 WEBAPP IMKONIYATLARI =====================
# Admin panelidagi "🌐 WebApp imkoniyatlari" bo'limi — WebApp'ning global
# xatti-harakatiga ta'sir qiluvchi bayroqlar bo'limi. Kelajakda bu yerga
# yangi imkoniyatlar qo'shiladi.
#
# Ilgari "Guruh ruxsatlar menyusi" toggle mavjud edi — foydalanuvchi
# so'roviga muvofiq olib tashlandi. Endi guruh a'zolari bir-birining
# reja/odatlarini har doim ko'radi (visibility guruh egasi tomonidan
# A'zolar bo'limidagi on/off toggle orqali boshqariladi).

def _webapp_menu_text() -> str:
    return (
        "🌐 <b>WebApp imkoniyatlari</b>\n\n"
        "Hozircha bu yerda sozlamalar yo'q.\n"
        "<i>Kelajakda yangi imkoniyatlar qo'shiladi.</i>"
    )


@router.callback_query(F.data == "admin_webapp")
async def admin_webapp_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await state.clear()

    await callback.message.edit_text(
        _webapp_menu_text(),
        parse_mode="HTML",
        reply_markup=admin_webapp_keyboard(),
    )
    await callback.answer()


# ===================== TO'LOVNI QO'LDA FAOLLASHTIRISH =====================
# Summa mos kelmagani uchun (provayder komissiyasi) webhook premiumni avtomatik
# ochmaydi — admin shu yerda external_id yoki payment_id orqali qo'lda ochadi.

@router.callback_query(F.data == "admin_activate_payment")
async def admin_activate_payment_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "💳 <b>To'lovni faollashtirish</b>\n\n"
        "Buyurtmaning <code>external_id</code> yoki <code>payment_id</code> sini yuboring.\n\n"
        "(To'lov bo'lgan, lekin premium ochilmagan holatda ishlating.)",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard(),
    )
    await state.set_state(AdminState.payment_activate)
    await callback.answer()


@router.message(AdminState.payment_activate)
async def admin_activate_payment_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    from bot.services.payment_service import find_order, activate_order

    ref = (message.text or "").strip()
    order = await find_order(session, ref)
    if order is None:
        await message.answer(
            "❌ Bunday buyurtma topilmadi.",
            reply_markup=back_to_admin_keyboard(),
        )
        await state.clear()
        return

    ok = await activate_order(session, order)
    if not ok and order.status == "paid":
        await message.answer(
            "ℹ️ Bu to'lov allaqachon faollashtirilgan.",
            reply_markup=back_to_admin_keyboard(),
        )
    elif not ok:
        await message.answer(
            "❌ Faollashtirib bo'lmadi (user topilmadi).",
            reply_markup=back_to_admin_keyboard(),
        )
    else:
        from sqlalchemy import select
        from bot.models.user import User
        from bot.config import SUBSCRIPTION_PLANS
        user = (await session.execute(
            select(User).where(User.id == order.user_id)
        )).scalar_one_or_none()
        tg = user.telegram_id if user else "—"
        plan_title = SUBSCRIPTION_PLANS.get(order.plan_key, {}).get("title", order.plan_key)
        await message.answer(
            "✅ Faollashtirildi! Foydalanuvchiga premium ochildi va xabar yuborildi.\n\n"
            f"👤 User TG ID: <code>{tg}</code>\n"
            f"📦 Tarif: <b>{plan_title}</b>",
            parse_mode="HTML",
            reply_markup=back_to_admin_keyboard(),
        )

    await state.clear()


# ===================== WLCM TO'LOV KALITLARI (ONBOARDING) =====================
# Barcha adminlar (ADMIN_ID va qo'shilgan adminlar) ko'radi va boshqaradi — bu
# bo'lim maxfiy api_key/api_secret ni ochib beradi va cheklangan martalik
# tokenni sarflaydi.

def _mask(value: str, head: int = 6, tail: int = 4) -> str:
    value = value or ""
    if not value:
        return "(yo'q)"
    if len(value) <= head + tail:
        return "***"
    return f"{value[:head]}…{value[-tail:]}"


async def _is_super_admin(callback: CallbackQuery, session: AsyncSession) -> bool:
    # Barcha adminlar TENG: ADMIN_ID ham, /admin orqali qo'shilgan adminlar ham
    # bu bo'limga (maxfiy to'lov kalitlari) kira oladi.
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return False
    return True


@router.callback_query(F.data == "admin_keys")
async def admin_keys_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await _is_super_admin(callback, session):
        return
    await state.clear()

    from bot.config import (
        PAYLOV_BASE_URL, PAYLOV_ENABLED, PAYLOV_PARTNER_ID,
        PAYLOV_PROD_TOKEN, PAYLOV_API_KEY, PAYLOV_WEBHOOK_URL,
    )

    has_token = bool(PAYLOV_PROD_TOKEN)
    status_line = (
        "✅ Kalitlar o'rnatilgan (to'lov yoqilgan)"
        if PAYLOV_ENABLED else
        "⚠️ Kalitlar hali yo'q (to'lov o'chiq)"
    )

    text = (
        "🔑 <b>WLCM to'lov kalitlari</b>\n\n"
        f"🌐 Server: <code>{PAYLOV_BASE_URL}</code>\n"
        f"🏷 Partner ID: <code>{PAYLOV_PARTNER_ID or '—'}</code>\n"
        f"🎫 Token: <code>{_mask(PAYLOV_PROD_TOKEN)}</code>\n"
        f"📦 Holat: {status_line}\n"
    )
    if PAYLOV_ENABLED:
        text += f"🔐 API key: <code>{_mask(PAYLOV_API_KEY)}</code>\n"
        text += (
            f"\n📡 <b>Webhook URL</b> (WLCM'ga shuni bering):\n"
            f"<code>{PAYLOV_WEBHOOK_URL}</code>\n"
            "\n⚠️ <b>Premium avtomatik ochilishi shu webhook'ga bog'liq!</b>\n"
            "WLCM bu manzilga to'lov natijasini yuborishi kerak. Aks holda "
            "foydalanuvchi to'laydi, lekin obuna ochilmaydi.\n"
            "\n🔌 <b>«Ulanishni tekshirish (/me)»</b> bilan kalitlar to'g'riligini "
            "bilib oling."
        )
    else:
        text += (
            "\n<b>Onboarding (2 bosqichli):</b>\n"
            "1️⃣ <b>Tokenni tekshirish</b> — token amaldaligini bilib oladi "
            "(tokenni sarflamaydi).\n"
            "2️⃣ <b>API key/secret olish</b> — yangi <code>API_KEY</code> va "
            "<code>API_SECRET</code> yaratadi.\n\n"
            "⚠️ Token cheklangan martalik. \"Olish\" tugmasi tokenni <b>sarflaydi</b>, "
            "shuning uchun faqat bir marta bosing va kalitlarni Railway env'ga qo'ying."
        )
        if not has_token:
            text += "\n\n❌ <b>PROD_TOKEN topilmadi.</b> Avval Railway env'da PROD_TOKEN ni to'ldiring."

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=admin_keys_keyboard(enabled=PAYLOV_ENABLED, has_token=has_token),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_keys_check")
async def admin_keys_check(callback: CallbackQuery, session: AsyncSession):
    if not await _is_super_admin(callback, session):
        return

    from bot.services.onboarding import validate_token, OnboardingError

    await callback.answer("🔍 Tekshirilmoqda...")
    try:
        path, info = await validate_token()
    except OnboardingError as e:
        await callback.message.edit_text(
            "🔍 <b>Token tekshiruvi</b>\n\n"
            f"❌ Muvaffaqiyatsiz:\n<code>{str(e)[:400]}</code>",
            parse_mode="HTML",
            reply_markup=admin_keys_keyboard(),
        )
        return

    await callback.message.edit_text(
        "🔍 <b>Token tekshiruvi</b>\n\n"
        "✅ Token <b>amalda</b>!\n"
        f"🔗 Endpoint: <code>{path}</code>\n"
        f"📨 Javob: <code>{info}</code>\n\n"
        "Endi <b>«🔑 API key/secret olish»</b> orqali kalit yaratishingiz mumkin.",
        parse_mode="HTML",
        reply_markup=admin_keys_keyboard(),
    )


@router.callback_query(F.data == "admin_keys_test")
async def admin_keys_test(callback: CallbackQuery, session: AsyncSession):
    """Joriy API_KEY/API_SECRET bilan GET /me chaqiradi — kalitlar ishlashini tasdiqlaydi."""
    if not await _is_super_admin(callback, session):
        return

    from bot.config import PAYLOV_ENABLED
    if not PAYLOV_ENABLED:
        await callback.answer("Kalitlar o'rnatilmagan (API_KEY/API_SECRET).", show_alert=True)
        return

    from bot.services.paylov import get_me, PaylovError

    await callback.answer("🔌 Tekshirilmoqda...")
    try:
        me = await get_me()
    except PaylovError as e:
        await callback.message.edit_text(
            "🔌 <b>Ulanish testi (/me)</b>\n\n"
            f"❌ Muvaffaqiyatsiz:\n<code>{str(e)[:400]}</code>\n\n"
            "Sabablar: API_KEY/API_SECRET noto'g'ri, IP whitelist yoki partner inactive.",
            parse_mode="HTML",
            reply_markup=admin_keys_keyboard(enabled=True),
        )
        return

    name = me.get("name", "—")
    pid = me.get("id", "—")
    uuid = me.get("uuid", "—")
    is_active = me.get("is_active")
    api_keys = me.get("api_keys", []) or []
    subs = me.get("sub_partners", []) or []

    await callback.message.edit_text(
        "🔌 <b>Ulanish testi (/me)</b>\n\n"
        "✅ Kalitlar <b>ishlayapti</b>!\n\n"
        f"🏷 Partner: <b>{name}</b>\n"
        f"🆔 ID: <code>{pid}</code>\n"
        f"🔑 UUID: <code>{uuid}</code>\n"
        f"📦 Faol: <b>{'ha' if is_active else 'yoʻq'}</b>\n"
        f"🗝 API keylar soni: <b>{len(api_keys)}</b>\n"
        f"👥 Sub-partnerlar: <b>{len(subs)}</b>\n\n"
        "To'lov tizimi to'liq tayyor. Endi foydalanuvchilar to'lov qila oladi.",
        parse_mode="HTML",
        reply_markup=admin_keys_keyboard(enabled=True),
    )


@router.callback_query(F.data == "admin_keys_confirm")
async def admin_keys_confirm(callback: CallbackQuery, session: AsyncSession):
    if not await _is_super_admin(callback, session):
        return
    await callback.message.edit_text(
        "⚠️ <b>Diqqat — tokenni sarflaysiz!</b>\n\n"
        "Bu amal WLCM'da yangi <code>API_KEY</code> va <code>API_SECRET</code> "
        "yaratadi va onboarding tokenni <b>bir martaga sarflaydi</b>.\n\n"
        "Kalitlar shu yerda ko'rsatiladi — ularni darhol <b>Railway env</b>'ga "
        "(<code>API_KEY</code>, <code>API_SECRET</code>) qo'ying.\n\n"
        "Davom etamizmi?",
        parse_mode="HTML",
        reply_markup=admin_keys_confirm_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_keys_generate")
async def admin_keys_generate(callback: CallbackQuery, session: AsyncSession):
    if not await _is_super_admin(callback, session):
        return

    from bot.services.onboarding import complete_onboarding, OnboardingError

    await callback.answer("🔑 Kalit yaratilmoqda...")
    try:
        await callback.message.edit_text("⏳ Onboarding bajarilmoqda...")
    except Exception:
        pass

    try:
        data = await complete_onboarding(name="intizom-ai-prod")
    except OnboardingError as e:
        await callback.message.edit_text(
            "🔑 <b>API key/secret olish</b>\n\n"
            f"❌ Xatolik:\n<code>{str(e)[:500]}</code>\n\n"
            "Token amaldaligini tekshiring yoki WLCM bilan bog'laning.",
            parse_mode="HTML",
            reply_markup=admin_keys_keyboard(),
        )
        return

    api_key = data.get("api_key", "")
    api_secret = data.get("api_secret", "")
    key_id = data.get("id", "")
    key_name = data.get("name", "")

    # Kalitlarni alohida xabarda (oson nusxalash uchun) yuboramiz.
    await callback.message.edit_text(
        "✅ <b>Kalitlar yaratildi!</b>\n\n"
        f"🆔 Key ID: <code>{key_id}</code>\n"
        f"🏷 Nomi: <code>{key_name}</code>\n\n"
        "⬇️ Quyidagilarni <b>Railway env</b>'ga qo'ying:",
        parse_mode="HTML",
    )
    await callback.message.answer(
        f"<code>API_KEY={api_key}</code>\n\n<code>API_SECRET={api_secret}</code>",
        parse_mode="HTML",
    )
    await callback.message.answer(
        "📌 <b>Keyingi qadamlar:</b>\n"
        "1. Yuqoridagi <code>API_KEY</code> va <code>API_SECRET</code> ni Railway "
        "Variables bo'limiga qo'shing.\n"
        "2. Servisni qayta ishga tushiring (redeploy).\n"
        "3. Menga xabar bering — to'liq to'lov oqimini (avtomatik obuna) yoqamiz.\n\n"
        "⚠️ Bu kalitlarni boshqa hech kimga bermang. <code>API_SECRET</code> qayta ko'rsatilmaydi.",
        parse_mode="HTML",
        reply_markup=admin_keys_keyboard(enabled=True),
    )


# ===================== USERLAR =====================

@router.callback_query(F.data == "admin_users")
async def admin_users(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.edit_text(
        "👥 <b>Userlar bo'limi</b>\n\nNima qilamiz?",
        parse_mode="HTML",
        reply_markup=admin_users_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_users_count")
async def admin_users_count(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    from bot.services.admin_service import get_detailed_users_stats, get_activity_stats
    stats = await get_detailed_users_stats(session)
    activity = await get_activity_stats(session)

    # Top userlar
    top_text = ""
    medals = ["🥇", "🥈", "🥉"]
    for i, user in enumerate(stats["top_users"]):
        name = user.full_name if user.full_name else "Noma'lum"
        top_text += f"{medals[i]} {name} — <b>{user.total_score} ball</b>\n"

    sc = stats["status_counts"]
    osishda_count = sc.get("📈 O'sishda", 0)

    text = (
        f"🔢 <b>Userlar statistikasi</b>\n\n"
        f"👥 Jami: <b>{stats['total']} ta</b>\n"
        f"✅ Aktiv (rejasi bor): <b>{stats['active']} ta</b>\n"
        f"😴 Harakatsiz: <b>{stats['inactive']} ta</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📈 <b>Faollik (kamida 1 marta):</b>\n"
        f"• Oxirgi 3 kun: <b>{activity['active_3']} ta</b>\n"
        f"• Oxirgi 7 kun: <b>{activity['active_7']} ta</b>\n"
        f"• Oxirgi 30 kun: <b>{activity['active_30']} ta</b>\n"
        f"🔥 Oxirgi 7 kun HAR KUNI faol: <b>{activity['daily_active_7']} ta</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📊 <b>Statuslar bo'yicha:</b>\n"
        f"🏆 Ustoz: <b>{sc['🏆 Ustoz']} ta</b>\n"
        f"💎 Intizomli: <b>{sc['💎 Intizomli']} ta</b>\n"
        f"🔥 Focused: <b>{sc['🔥 Focused']} ta</b>\n"
        f"📈 O'sishda: <b>{osishda_count} ta</b>\n"
        f"🌱 Yangi boshlovchi: <b>{sc['🌱 Yangi boshlovchi']} ta</b>\n"
        f"😴 Harakatsiz: <b>{sc['😴 Harakatsiz']} ta</b>\n\n"
    )

    if stats["top_users"]:
        text += f"━━━━━━━━━━━━━━━\n🏅 <b>Top userlar:</b>\n{top_text}"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=admin_users_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_users_list")
async def admin_users_list(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    users = await get_all_users(session)

    if not users:
        await callback.message.edit_text(
            "👥 Hozircha hech qanday user yo'q.",
            reply_markup=back_to_admin_keyboard()
        )
        return

    await callback.message.edit_text(
        f"👥 <b>Barcha userlar</b> ({len(users)} ta)\n\nUserni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_users_list_keyboard(users, page=0)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_users_page_"))
async def admin_users_page(callback: CallbackQuery, session: AsyncSession):
    page = int(callback.data.split("_")[-1])
    users = await get_all_users(session)

    await callback.message.edit_text(
        f"👥 <b>Barcha userlar</b> ({len(users)} ta)\n\nUserni tanlang:",
        parse_mode="HTML",
        reply_markup=admin_users_list_keyboard(users, page=page)
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_user_"))
async def admin_user_detail(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    user_id = int(callback.data.split("_")[-1])

    from sqlalchemy import select
    from bot.models.user import User
    result = await session.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()

    if not user:
        await callback.answer("User topilmadi!", show_alert=True)
        return

    stats = await get_user_plan_stats(session, user)
    status = get_user_status(user.total_score, user.streak)

    username_str = f"@{user.username}" if user.username else "Yoq"
    reg_date = user.created_at.strftime("%d.%m.%Y")
    full_name = user.full_name if user.full_name else "Noma'lum"

    text = (
        f"👤 <b>User ma'lumotlari</b>\n\n"
        f"📛 Ismi: <b>{full_name}</b>\n"
        f"🔗 Username: <b>{username_str}</b>\n"
        f"🆔 Telegram ID: <b>{user.telegram_id}</b>\n"
        f"📅 Ulangan sana: <b>{reg_date}</b>\n"
        f"📊 Status: <b>{status}</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"📋 Jami rejalar: <b>{stats['total_plans']}</b>\n"
        f"✅ Bajarilgan: <b>{stats['done']}</b>\n"
        f"❌ Bajarilmagan: <b>{stats['failed']}</b>\n"
        f"⏳ Kutilmoqda: <b>{stats['pending']}</b>\n\n"
        f"⭐ Umumiy ball: <b>{user.total_score}</b>\n"
        f"🔥 Streak: <b>{user.streak} kun</b>"
    )

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=back_to_users_keyboard()
    )
    await callback.answer()


# ===================== ADMINLAR =====================

@router.callback_query(F.data == "admin_admins")
async def admin_admins(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.edit_text(
        "🛡 <b>Adminlar bo'limi</b>\n\nNima qilamiz?",
        parse_mode="HTML",
        reply_markup=admin_admins_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_list")
async def admin_list(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    admins = await get_all_admins(session)

    if not admins:
        text = "🛡 <b>Adminlar ro'yxati</b>\n\nHozircha qo'shimcha admin yo'q."
    else:
        text = f"🛡 <b>Adminlar ro'yxati</b> ({len(admins)} ta)\n\n"
        for i, adm in enumerate(admins, 1):
            added = adm.added_at.strftime("%d.%m.%Y")
            adm_name = adm.full_name if adm.full_name else "Noma'lum"
            text += f"{i}. <b>{adm_name}</b>\n"
            text += f"   ID: {adm.telegram_id} | {added}\n\n"

    await callback.message.edit_text(
        text,
        parse_mode="HTML",
        reply_markup=admin_admins_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "admin_add")
async def admin_add_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.edit_text(
        "➕ <b>Admin qo'shish</b>\n\n"
        "Yangi adminning Telegram ID sini yuboring:\n\n"
        "<i>ID ni bilish uchun @userinfobot ga /start yuboring</i>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )
    await state.set_state(AdminState.waiting_admin_id_add)
    await callback.answer()


@router.message(AdminState.waiting_admin_id_add)
async def admin_add_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    try:
        new_admin_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam yuboring:")
        return

    try:
        chat = await message.bot.get_chat(new_admin_id)
        full_name = chat.full_name if chat.full_name else "Noma'lum"
    except Exception:
        full_name = "Noma'lum"

    admin_obj = await add_admin(session, new_admin_id, full_name)

    if admin_obj:
        await message.answer(
            f"✅ <b>{full_name}</b> admin qilindi!\nID: {new_admin_id}",
            parse_mode="HTML",
            reply_markup=admin_admins_keyboard()
        )
    else:
        await message.answer(
            "⚠️ Bu user allaqachon admin!",
            reply_markup=admin_admins_keyboard()
        )
    await state.clear()


@router.callback_query(F.data == "admin_remove")
async def admin_remove_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await callback.message.edit_text(
        "➖ <b>Admin o'chirish</b>\n\n"
        "O'chiriladigan adminning Telegram ID sini yuboring:",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )
    await state.set_state(AdminState.waiting_admin_id_remove)
    await callback.answer()


@router.message(AdminState.waiting_admin_id_remove)
async def admin_remove_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    try:
        remove_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam yuboring:")
        return

    from bot.config import ADMIN_ID
    if remove_id == ADMIN_ID:
        await message.answer(
            "❌ Super adminni o'chirib bo'lmaydi!",
            reply_markup=admin_admins_keyboard()
        )
        await state.clear()
        return

    success = await remove_admin(session, remove_id)

    if success:
        await message.answer(
            f"✅ Admin (ID: {remove_id}) o'chirildi!",
            reply_markup=admin_admins_keyboard()
        )
    else:
        await message.answer(
            "⚠️ Bu ID da admin topilmadi!",
            reply_markup=admin_admins_keyboard()
        )
    await state.clear()


# ===================== BROADCASTING =====================

@router.callback_query(F.data == "admin_broadcast")
async def broadcast_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    count = await get_users_count(session)

    await callback.message.edit_text(
        f"📢 <b>Xabar yuborish</b>\n\n"
        f"👥 Jami userlar: <b>{count} ta</b>\n\n"
        f"Kimga yuboramiz?",
        parse_mode="HTML",
        reply_markup=broadcast_type_keyboard()
    )
    await state.set_state(AdminState.broadcast_choosing)
    await callback.answer()


# Barcha userlarga
@router.callback_query(F.data == "broadcast_all")
async def broadcast_all_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await state.update_data(broadcast_target="all", target_id=None)
    await state.set_state(AdminState.broadcast_waiting_text)

    await callback.message.edit_text(
        "📢 <b>Barcha userlarga xabar</b>\n\n"
        "Xabar matnini yuboring:\n\n"
        "<i>HTML format ishlaydi:\n"
        "&lt;b&gt;bold&lt;/b&gt; → <b>bold</b>\n"
        "&lt;i&gt;italic&lt;/i&gt; → <i>italic</i>\n"
        "&lt;u&gt;underline&lt;/u&gt; → <u>underline</u>\n"
        "&lt;code&gt;code&lt;/code&gt; → <code>code</code></i>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )
    await callback.answer()


# ID orqali
@router.callback_query(F.data == "broadcast_by_id")
async def broadcast_by_id_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    await state.set_state(AdminState.broadcast_waiting_id)

    await callback.message.edit_text(
        "👤 <b>ID orqali xabar</b>\n\n"
        "Telegram ID ni yuboring:",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )
    await callback.answer()


# ID kiritish
@router.message(AdminState.broadcast_waiting_id)
async def broadcast_id_received(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    try:
        target_id = int(message.text.strip())
    except ValueError:
        await message.answer("❌ Noto'g'ri format. Faqat raqam yuboring:")
        return

    # User mavjudligini tekshirish
    try:
        chat = await message.bot.get_chat(target_id)
        name = chat.full_name if chat.full_name else "Noma'lum"
    except Exception:
        await message.answer(
            "❌ Bu ID da user topilmadi. Tekshirib qayta yuboring:",
            reply_markup=back_to_admin_keyboard()
        )
        return

    await state.update_data(broadcast_target="id", target_id=target_id, target_name=name)
    await state.set_state(AdminState.broadcast_waiting_text)

    await message.answer(
        f"👤 <b>{name}</b> (ID: {target_id})\n\n"
        f"Xabar matnini yuboring:\n\n"
        f"<i>HTML format ishlaydi:\n"
        f"&lt;b&gt;bold&lt;/b&gt; → <b>bold</b>\n"
        f"&lt;i&gt;italic&lt;/i&gt; → <i>italic</i>\n"
        f"&lt;u&gt;underline&lt;/u&gt; → <u>underline</u>\n"
        f"&lt;code&gt;code&lt;/code&gt; → <code>code</code></i>",
        parse_mode="HTML",
        reply_markup=back_to_admin_keyboard()
    )


# Xabar matni keldi — preview ko'rsatish
@router.message(AdminState.broadcast_waiting_text)
async def broadcast_text_received(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    data = await state.get_data()
    target = data.get("broadcast_target")
    target_id = data.get("target_id")
    target_name = data.get("target_name", "")

    await state.update_data(broadcast_text=message.text)

    if target == "all":
        count = await get_users_count(session)
        preview_header = f"📢 <b>Barcha {count} ta userlarga yuboriladi</b>\n\n"
    else:
        preview_header = f"👤 <b>{target_name}</b> ga yuboriladi\n\n"

    # Preview ko'rsatish
    await message.answer(
        f"👁 <b>Preview:</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"{message.text}\n"
        f"━━━━━━━━━━━━━━━\n\n"
        f"{preview_header}"
        f"Yuborishni tasdiqlaysizmi?",
        parse_mode="HTML",
        reply_markup=broadcast_confirm_keyboard()
    )


# Yuborish tasdiqlandi
async def _run_broadcast_all(bot, final_text, progress_msg):
    """
    Barcha userlarga xabar yuborish — FON (background) vazifa sifatida.
    Handler darhol javob qaytaradi, yuborish esa orqa fonda davom etadi
    (flood-control + bloklagan userni nofaol qilish bilan).
    """
    import asyncio
    from aiogram.exceptions import TelegramRetryAfter, TelegramForbiddenError
    from sqlalchemy import select
    from database.db import AsyncSessionLocal
    from bot.models.user import User

    sent = failed = blocked = 0
    async with AsyncSessionLocal() as session:
        users = (await session.execute(select(User))).scalars().all()
        total = len(users)
        for i, user in enumerate(users, 1):
            try:
                await bot.send_message(user.telegram_id, final_text, parse_mode="HTML")
                sent += 1
            except TelegramRetryAfter as e:
                await asyncio.sleep(e.retry_after + 1)
                try:
                    await bot.send_message(user.telegram_id, final_text, parse_mode="HTML")
                    sent += 1
                except Exception:
                    failed += 1
            except TelegramForbiddenError:
                blocked += 1
                user.is_active = False
            except Exception:
                failed += 1

            if i % 25 == 0:
                try:
                    await progress_msg.edit_text(f"⏳ Yuborilmoqda... {i}/{total}")
                except Exception:
                    pass
                try:
                    await session.commit()  # bloklaganlarni saqlab boramiz
                except Exception:
                    await session.rollback()
            await asyncio.sleep(0.05)

        try:
            await session.commit()
        except Exception:
            await session.rollback()

    try:
        await progress_msg.edit_text(
            f"✅ <b>Xabar yuborildi!</b>\n\n"
            f"👥 Jami: <b>{total} ta</b>\n"
            f"✅ Muvaffaqiyatli: <b>{sent} ta</b>\n"
            f"🚫 Bloklagan: <b>{blocked} ta</b>\n"
            f"❌ Yuborilmadi: <b>{failed} ta</b>",
            parse_mode="HTML",
            reply_markup=back_to_admin_keyboard(),
        )
    except Exception:
        pass


@router.callback_query(F.data == "broadcast_send")
async def broadcast_send_confirmed(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    data = await state.get_data()
    target = data.get("broadcast_target")
    target_id = data.get("target_id")
    broadcast_text = data.get("broadcast_text", "")

    await state.clear()

    final_text = f"📢 <b>Intizom AI:</b>\n\n{broadcast_text}"

    if target == "id":
        # Bitta userga
        try:
            await callback.bot.send_message(
                chat_id=target_id,
                text=final_text,
                parse_mode="HTML"
            )
            await callback.message.edit_text(
                f"✅ <b>Xabar yuborildi!</b>\n\nID: {target_id}",
                parse_mode="HTML",
                reply_markup=back_to_admin_keyboard()
            )
        except Exception as e:
            await callback.message.edit_text(
                f"❌ Xabar yuborishda xatolik: {str(e)}",
                reply_markup=back_to_admin_keyboard()
            )
        await callback.answer()
    else:
        # Barcha userlarga — FON vazifasi (handler bloklanmaydi, callback eskirmaydi)
        progress_msg = await callback.message.edit_text(
            "⏳ Yuborish boshlandi... (orqa fonda davom etadi)"
        )
        asyncio.create_task(_run_broadcast_all(callback.bot, final_text, progress_msg))
        await callback.answer("📢 Yuborish boshlandi", show_alert=False)



# ===================== PREMIUM / OBUNA =====================

@router.callback_query(F.data == "admin_premium")
async def admin_premium(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "💎 <b>Premium boshqaruvi</b>\n\nNima qilamiz?",
        parse_mode="HTML",
        reply_markup=admin_premium_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "admin_premium_stats")
async def admin_premium_stats(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    from sqlalchemy import select, func
    from bot.models.subscription import Subscription
    from bot.services.premium_service import get_premium_count
    from bot.services.admin_service import get_users_count
    from bot.config import SUBSCRIPTION_PLANS

    premium_count = await get_premium_count(session)
    total_users = await get_users_count(session)
    total_subs = await session.scalar(select(func.count(Subscription.id))) or 0

    # Faol obunalar tarif bo'yicha + taxminiy daromad
    rows = (await session.execute(
        select(Subscription).where(Subscription.is_active == True)  # noqa: E712
    )).scalars().all()
    by_plan = {}
    revenue = 0
    for s in rows:
        by_plan[s.plan] = by_plan.get(s.plan, 0) + 1
        revenue += s.price or 0

    plan_lines = ""
    for key, p in SUBSCRIPTION_PLANS.items():
        plan_lines += f"  • {p['title']}: <b>{by_plan.get(key, 0)} ta</b>\n"

    rev_str = f"{revenue:,}".replace(",", " ")

    text = (
        "📊 <b>Obuna statistikasi</b>\n\n"
        f"💎 Premium foydalanuvchilar: <b>{premium_count} ta</b>\n"
        f"🆓 Bepul foydalanuvchilar: <b>{max(0, total_users - premium_count)} ta</b>\n"
        f"👥 Jami: <b>{total_users} ta</b>\n\n"
        f"━━━━━━━━━━━━━━━\n"
        f"🧾 Jami obunalar (tarix): <b>{total_subs} ta</b>\n"
        f"📦 <b>Faol obunalar (tarif):</b>\n{plan_lines}\n"
        f"💰 Taxminiy daromad (faol): <b>{rev_str} so'm</b>"
    )
    await callback.message.edit_text(
        text, parse_mode="HTML", reply_markup=back_to_premium_keyboard()
    )
    await callback.answer()


# ===================== 👥 PREMIUM USERLAR RO'YXATI =====================
# Admin panel > 💎 Premium > 👥 Premium userlar
#
# Hozirda faol premium'ga ega BARCHA foydalanuvchilar (id, ism, tarif, manba,
# tugash sanasi) ko'rsatiladi. Har bir userni bosib batafsil ko'rish mumkin —
# o'sha yerda uning butun obuna tarixi (Subscription rows) chiqadi.

# Subscription.source qiymati → (emoji, uzbek yorlig'i). Barcha mumkin bo'lgan
# qiymatlar: paylov, admin, promocode, promo_free, trial, referral,
# referral_invitee, gift, card.
_SOURCE_META: dict[str, tuple[str, str]] = {
    "paylov":           ("💳", "Sotib olgan (Paylov)"),
    "admin":            ("🛡", "Admin qo'lda bergan"),
    "promocode":        ("🎟", "Promokod bilan sotib olgan"),
    "promo_free":       ("🎁", "Bepul promokod (-)"),
    "trial":            ("🌱", "Sinov (trial) — DEPRECATED"),
    "referral":         ("👥", "Do'st taklif qilib yutgan"),
    "referral_invitee": ("👥", "Taklif qilingan (invitee bonusi)"),
    "gift":             ("🎁", "Sovg'a (qo'lda)"),
    "card":             ("💳", "Karta orqali (eski)"),
}


def _source_meta(source: str | None) -> tuple[str, str]:
    """Manba qiymatidan (emoji, yorliq) qaytaradi. Noma'lum bo'lsa fallback."""
    if not source:
        return ("💎", "Noma'lum")
    return _SOURCE_META.get(source, ("💎", source))


def _plan_title_for(plan_key: str | None) -> str:
    """
    Plan key'idan foydalanuvchiga tushunarli nom yasaydi.
      • '1m'/'3m'/'12m' → SUBSCRIPTION_PLANS'dagi title (masalan: '3 oy')
      • 'trial'/'referral'/'promo_free' → tarif emas, lekin plan ustunida shu
        saqlanadi — chiroyli yorliqqa aylantiramiz.
    """
    if not plan_key:
        return "—"
    from bot.config import SUBSCRIPTION_PLANS
    p = SUBSCRIPTION_PLANS.get(plan_key)
    if p:
        return p.get("title", plan_key)
    friendly = {
        "trial":            "Sinov (trial)",
        "referral":         "Referral mukofoti",
        "referral_invitee": "Referral (invitee)",
        "promo_free":       "Bepul promokod",
    }
    return friendly.get(plan_key, plan_key)


async def _fetch_premium_records(session: AsyncSession) -> list[dict]:
    """
    Hozirda premium bo'lgan barcha foydalanuvchilarni bir marotaba yuklab,
    har birining faol Subscription yozuvi bilan birga qaytaradi.

    Qaytadigan har bir yozuv:
      {
        "user":         User obj,
        "sub":          Subscription | None (faol yozuv),
        "days_left":    int (bugun kiritilib hisoblangan qoldiq kun),
        "source":       str | None (Subscription.source qiymati),
        "source_emoji": str,
        "source_label": str,
      }

    Tartib: premium_until desc — eng ko'p vaqt qolgan tepada.
    """
    from datetime import datetime
    from sqlalchemy import and_, select
    from bot.models.subscription import Subscription
    from bot.models.user import User

    now = datetime.utcnow()

    users_res = await session.execute(
        select(User)
        .where(User.premium_until.isnot(None))
        .where(User.premium_until > now)
        .order_by(User.premium_until.desc())
    )
    users = users_res.scalars().all()
    if not users:
        return []

    user_ids = [u.id for u in users]
    subs_res = await session.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id.in_(user_ids),
                Subscription.is_active == True,  # noqa: E712
            )
        ).order_by(Subscription.expires_at.desc())
    )
    active_by_user: dict[int, Subscription] = {}
    for s in subs_res.scalars().all():
        # Har bir user'da nazariy jihatdan bittadan faol obuna bo'ladi;
        # ammo bir vaqt eski migratsiyadan bir nechta qolgan bo'lsa —
        # eng yangi (expires_at desc) tanlanadi.
        active_by_user.setdefault(s.user_id, s)

    records: list[dict] = []
    for u in users:
        sub = active_by_user.get(u.id)
        delta = (u.premium_until - now)
        days_left = max(0, delta.days + (1 if delta.seconds > 0 else 0))
        source = (sub.source if sub else None)
        emoji, label = _source_meta(source)
        records.append({
            "user": u,
            "sub": sub,
            "days_left": days_left,
            "source": source,
            "source_emoji": emoji,
            "source_label": label,
        })
    return records


def _breakdown_text(records: list[dict]) -> str:
    """Manba bo'yicha yig'ma xulosa matni (ko'p bo'lganlari tepada)."""
    counts: dict[str, int] = {}
    for r in records:
        key = r["source"] or "unknown"
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return ""
    lines = []
    for key, cnt in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        emoji, label = _source_meta(key if key != "unknown" else None)
        lines.append(f"{emoji} {label}: <b>{cnt} ta</b>")
    return "\n".join(lines)


def _list_page_text(records: list[dict], page: int, per_page: int = 8) -> str:
    """Ro'yxat sarlavhasi + sahifa raqami + manba yig'masi."""
    total = len(records)
    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(0, min(page, total_pages - 1))
    breakdown = _breakdown_text(records) if records else ""
    header = (
        "👥 <b>Premium userlar</b>\n"
        f"Jami: <b>{total} ta</b>"
    )
    if total > 0:
        header += f"  ·  Sahifa <b>{page + 1}/{total_pages}</b>"
    if breakdown:
        header += f"\n\n📊 <b>Manba bo'yicha:</b>\n{breakdown}"
    if total == 0:
        header += "\n\n<i>Hozircha premium'li foydalanuvchi yo'q.</i>"
    else:
        header += "\n\n<i>Batafsil ko'rish uchun tugmani bosing 👇</i>"
    return header


@router.callback_query(F.data == "admin_premium_users")
async def admin_premium_users(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    """👥 Premium userlar — ro'yxatning birinchi sahifasi."""
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await state.clear()

    records = await _fetch_premium_records(session)
    text = _list_page_text(records, page=0)
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_premium_users_list_keyboard(records, page=0),
        )
    except Exception:
        # Xabar matni bir xil bo'lsa Telegram xato beradi — jim o'tamiz.
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("admin_premium_users_page_"))
async def admin_premium_users_page(callback: CallbackQuery, session: AsyncSession):
    """Paginatsiya — keyingi/oldingi sahifa."""
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    try:
        page = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        page = 0

    records = await _fetch_premium_records(session)
    text = _list_page_text(records, page=page)
    try:
        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_premium_users_list_keyboard(records, page=page),
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("admin_premium_user_"))
async def admin_premium_user_detail(callback: CallbackQuery, session: AsyncSession):
    """
    Bitta premium user'ning to'liq detali:
      • Shaxsiy ma'lumot (ism, username, TG ID, ulangan sana)
      • Joriy Premium (tarif, tugash sanasi, manba, promokod, to'langan summa)
      • Obuna tarixi (oxirgi 10 ta Subscription yozuvi)
    """
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    # NOTE: callback data prefiksi `admin_premium_user_` — bu `admin_users_page_`
    # yoki `admin_user_` prefiklari bilan chalkashmaydi (barchasi noyob).
    try:
        user_id = int(callback.data.rsplit("_", 1)[-1])
    except ValueError:
        await callback.answer("Xato ID!", show_alert=True)
        return

    from sqlalchemy import and_, select
    from bot.models.subscription import Subscription
    from bot.models.user import User

    user = await session.get(User, user_id)
    if not user:
        await callback.answer("User topilmadi!", show_alert=True)
        return

    from bot.services.premium_service import user_is_premium, days_left, format_price

    # Faol obuna (joriy premium manba'si) — bitta yozuv
    active_sub_res = await session.execute(
        select(Subscription).where(
            and_(
                Subscription.user_id == user.id,
                Subscription.is_active == True,  # noqa: E712
            )
        ).order_by(Subscription.expires_at.desc())
    )
    active_sub = active_sub_res.scalars().first()

    # Butun tarix (eng yangisi tepada)
    hist_res = await session.execute(
        select(Subscription)
        .where(Subscription.user_id == user.id)
        .order_by(Subscription.started_at.desc())
        .limit(10)
    )
    history = hist_res.scalars().all()

    # ── Shaxsiy blok ─────────────────────────────────────────
    username_str = f"@{user.username}" if user.username else "—"
    full_name = (user.display_name or user.full_name or "Noma'lum").strip() or "Noma'lum"
    reg_date = user.created_at.strftime("%d.%m.%Y") if user.created_at else "—"

    lines: list[str] = [
        f"👤 <b>{full_name}</b>",
        "",
        f"🔗 Username: <b>{username_str}</b>",
        f"🆔 Telegram ID: <code>{user.telegram_id}</code>",
        f"📅 Ulangan: <b>{reg_date}</b>",
        "",
        "━━━━━━━━━━━━━━━",
        "💎 <b>Joriy Premium</b>",
        "",
    ]

    if not user_is_premium(user):
        lines.append("<i>Bu foydalanuvchida hozir faol premium yo'q "
                     "(muddati tugagan bo'lishi mumkin).</i>")
    else:
        dl = days_left(user)
        until = user.premium_until.strftime("%d.%m.%Y") if user.premium_until else "—"
        lines.append(f"📅 Amal qiladi: <b>{until} gacha</b>")
        lines.append(f"⏳ Qolgan: <b>{dl} kun</b>")

        if active_sub is not None:
            emoji, label = _source_meta(active_sub.source)
            plan_title = _plan_title_for(active_sub.plan)
            lines.append(f"📦 Tarif: <b>{plan_title}</b>  ·  {active_sub.days} kun")
            lines.append(f"🎯 Manba: <b>{emoji} {label}</b>")
            if active_sub.promocode:
                lines.append(f"🎟 Promokod: <code>{active_sub.promocode}</code>")
            if active_sub.price and active_sub.price > 0:
                lines.append(f"💰 To'langan: <b>{format_price(active_sub.price)} so'm</b>")
            else:
                lines.append("💰 To'lov: <b>—</b> (bepul manba)")
            if active_sub.started_at:
                lines.append(f"🕒 Boshlandi: <b>{active_sub.started_at.strftime('%d.%m.%Y %H:%M')}</b>")
        else:
            lines.append("<i>Faol Subscription yozuvi topilmadi (qo'lda ochilgan bo'lishi mumkin).</i>")

    # ── Tarix bloki ──────────────────────────────────────────
    if history:
        lines.append("")
        lines.append("━━━━━━━━━━━━━━━")
        lines.append(f"📚 <b>Obuna tarixi</b> (oxirgi {len(history)} ta):")
        lines.append("")
        for i, s in enumerate(history, 1):
            emoji, _ = _source_meta(s.source)
            plan_title = _plan_title_for(s.plan)
            started = s.started_at.strftime("%d.%m.%Y") if s.started_at else "—"
            expires = s.expires_at.strftime("%d.%m.%Y") if s.expires_at else "—"
            active_mark = " ✅" if s.is_active else ""
            price_str = f" · {format_price(s.price)} so'm" if s.price and s.price > 0 else ""
            promo_str = f" · 🎟 <code>{s.promocode}</code>" if s.promocode else ""
            lines.append(
                f"{i}. {emoji} <b>{plan_title}</b> · {s.days} kun{price_str}\n"
                f"    {started} → {expires}{active_mark}{promo_str}"
            )

    text = "\n".join(lines)
    # Xabar juda uzun bo'lib qolmasligi uchun (Telegram limit ~4096) —
    # tarix ro'yxati 10 taga cheklangan, mavjud matn baribir sig'adi.
    try:
        await callback.message.edit_text(
            text, parse_mode="HTML",
            reply_markup=back_to_premium_users_keyboard(),
            disable_web_page_preview=True,
        )
    except Exception:
        # Fallback — matn juda uzun bo'lsa yoki formatlash xato bersa
        await callback.message.answer(
            text, parse_mode="HTML",
            reply_markup=back_to_premium_users_keyboard(),
            disable_web_page_preview=True,
        )
    await callback.answer()


@router.callback_query(F.data == "admin_premium_grant")
async def admin_premium_grant_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Premium berish</b>\n\n"
        "Telegram ID va tarifni yuboring.\n"
        "Format: <code>ID tarif</code>\n\n"
        "Tariflar: <code>1m</code> / <code>3m</code> / <code>12m</code>\n"
        "Masalan: <code>123456789 3m</code>",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )
    await state.set_state(AdminState.premium_grant)
    await callback.answer()


@router.message(AdminState.premium_grant)
async def admin_premium_grant_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "❌ Format noto'g'ri. Masalan: <code>123456789 3m</code>",
            parse_mode="HTML",
        )
        return

    from bot.config import SUBSCRIPTION_PLANS
    from bot.services.user_service import get_user_by_telegram_id
    from bot.services.premium_service import activate_subscription

    try:
        target_id = int(parts[0])
    except ValueError:
        await message.answer("❌ ID raqam bo'lishi kerak.")
        return

    plan_key = parts[1].strip().lower()
    if plan_key not in SUBSCRIPTION_PLANS:
        await message.answer(
            "❌ Noma'lum tarif. 1m / 3m / 12m dan birini yozing."
        )
        return

    user = await get_user_by_telegram_id(session, target_id)
    if not user:
        await message.answer(
            "❌ Bu ID da foydalanuvchi topilmadi (avval botda /start bosishi kerak).",
            reply_markup=back_to_premium_keyboard(),
        )
        await state.clear()
        return

    sub = await activate_subscription(
        session, user, plan_key=plan_key, source="admin",
    )
    await state.clear()

    plan = SUBSCRIPTION_PLANS[plan_key]
    await message.answer(
        f"✅ <b>Premium berildi!</b>\n\n"
        f"👤 ID: <b>{target_id}</b>\n"
        f"📦 Tarif: <b>{plan['title']}</b>\n"
        f"📅 Tugaydi: <b>{sub.expires_at.strftime('%d.%m.%Y')}</b>",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )

    # Foydalanuvchini xabardor qilamiz
    try:
        await message.bot.send_message(
            chat_id=target_id,
            text=(
                "🎉 <b>Sizga Premium berildi!</b>\n\n"
                f"📦 Tarif: <b>{plan['title']}</b>\n"
                f"📅 Amal qiladi: <b>{sub.expires_at.strftime('%d.%m.%Y')} gacha</b>\n\n"
                "✨ Endi Mini App va barcha imkoniyatlar ochiq!"
            ),
            parse_mode="HTML",
        )
    except Exception:
        pass


@router.callback_query(F.data == "admin_premium_revoke")
async def admin_premium_revoke_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "➖ <b>Premium olib tashlash</b>\n\n"
        "Foydalanuvchining Telegram ID sini yuboring:",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )
    await state.set_state(AdminState.premium_revoke)
    await callback.answer()


@router.message(AdminState.premium_revoke)
async def admin_premium_revoke_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return
    try:
        target_id = int((message.text or "").strip())
    except ValueError:
        await message.answer("❌ ID raqam bo'lishi kerak.")
        return

    from bot.services.user_service import get_user_by_telegram_id
    from bot.services.premium_service import revoke_premium

    user = await get_user_by_telegram_id(session, target_id)
    if not user:
        await message.answer(
            "❌ Foydalanuvchi topilmadi.",
            reply_markup=back_to_premium_keyboard(),
        )
        await state.clear()
        return

    await revoke_premium(session, user)
    await state.clear()
    await message.answer(
        f"✅ Premium olib tashlandi (ID: {target_id}).",
        reply_markup=back_to_premium_keyboard(),
    )


@router.callback_query(F.data == "admin_promo_create")
async def admin_promo_create_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "🎟 <b>Promokod yaratish</b>\n\n"
        "Format: <code>KOD ± bonus_kun [max_uses] [amal_kun]</code>\n\n"
        "<b>Ishora (± majburiy):</b>\n"
        "• <code>+</code> → foydalanuvchi obunani <b>SOTIB OLADI</b>, unga "
        "qo'shimcha <b>bonus_kun</b> qo'shiladi.\n"
        "• <code>-</code> → foydalanuvchi obuna <b>sotib olmaydi</b>, unga "
        "<b>bonus_kun</b> kunga premium <b>avtomatik (bepul)</b> ochiladi.\n\n"
        "• <b>bonus_kun</b>: kunlar soni.\n"
        "• <b>max_uses</b>: nechta marta ishlatilsin (0 = cheksiz)\n"
        "• <b>amal_kun</b>: promokod necha kun amal qiladi (0 = muddatsiz)\n\n"
        "Masalan:\n"
        "<code>YANGI2026 +15 100 30</code> — sotib olsa +15 kun, 100 marta, 30 kun amal qiladi\n"
        "<code>SOVGA -30 0 7</code> — bepul 30 kun premium, cheksiz, 7 kun amal qiladi",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )
    await state.set_state(AdminState.promo_create)
    await callback.answer()


@router.message(AdminState.promo_create)
async def admin_promo_create_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    _fmt_help = (
        "❌ Format: <code>KOD ± bonus_kun [max_uses] [amal_kun]</code>\n"
        "Masalan: <code>YANGI2026 +15 100 30</code> yoki <code>SOVGA -30 0 7</code>"
    )

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(_fmt_help, parse_mode="HTML")
        return

    from datetime import datetime, timedelta
    from bot.services.premium_service import create_promocode

    code = parts[0].strip()

    # ── Ishora (+/-) va bonus_kun'ni ajratamiz ────────────────
    # Qo'llab-quvvatlanadigan ko'rinishlar:
    #   "KOD + 15 ..."  (ishora alohida)
    #   "KOD +15 ..."   (ishora songa yopishgan)
    rest = parts[1:]
    sign = None
    nums: list[str] = []
    if rest[0] in ("+", "-"):
        sign = rest[0]
        nums = rest[1:]
    elif rest[0] and rest[0][0] in ("+", "-"):
        sign = rest[0][0]
        nums = [rest[0][1:]] + rest[1:]

    if sign is None:
        await message.answer(
            "❌ <b>Ishora majburiy!</b> <code>+</code> (sotib olish + bonus) yoki "
            "<code>-</code> (bepul) qo'ying.\n\n" + _fmt_help,
            parse_mode="HTML",
        )
        return

    is_free = (sign == "-")

    if not nums or not nums[0]:
        await message.answer(_fmt_help, parse_mode="HTML")
        return

    try:
        bonus_days = max(0, int(nums[0]))
    except ValueError:
        await message.answer(
            "❌ <b>bonus_kun</b> butun son bo'lishi kerak.\n\n" + _fmt_help,
            parse_mode="HTML",
        )
        return

    # `-` (bepul) turida kun soni 0 bo'lsa — ochadigan hech narsa yo'q.
    if is_free and bonus_days <= 0:
        await message.answer(
            "❌ Bepul (<code>-</code>) promokod uchun <b>bonus_kun</b> 0 dan katta "
            "bo'lishi kerak. Masalan: <code>SOVGA -30 0 7</code>",
            parse_mode="HTML",
        )
        return

    max_uses = 0
    if len(nums) >= 2:
        try:
            max_uses = max(0, int(nums[1]))
        except ValueError:
            max_uses = 0

    expires_at = None
    valid_days = 0
    if len(nums) >= 3:
        try:
            valid_days = max(0, int(nums[2]))
        except ValueError:
            valid_days = 0
        if valid_days > 0:
            expires_at = datetime.utcnow() + timedelta(days=valid_days)

    promo = await create_promocode(
        session, code=code, bonus_days=bonus_days, max_uses=max_uses,
        created_by=message.from_user.id, expires_at=expires_at, is_free=is_free,
    )
    await state.clear()

    if not promo:
        await message.answer(
            f"⚠️ <code>{code}</code> allaqachon mavjud.",
            parse_mode="HTML",
            reply_markup=back_to_premium_keyboard(),
        )
        return

    uses_label = "cheksiz" if max_uses == 0 else f"{max_uses} marta"
    valid_label = "muddatsiz" if valid_days == 0 else f"{valid_days} kun"
    if is_free:
        type_label = (
            f"🎁 <b>BEPUL obuna</b> — <b>{bonus_days} kun</b>ga to'lovsiz ochiladi "
            "(<code>-</code> turi)"
        )
    else:
        type_label = (
            f"💳 <b>Sotib olish + bonus</b> — tarif ustiga <b>+{bonus_days} kun</b> "
            "(<code>+</code> turi)"
        )

    await message.answer(
        f"✅ <b>Promokod yaratildi!</b>\n\n"
        f"🎟 Kod: <code>{promo.code}</code>\n"
        f"{type_label}\n"
        f"🔢 Limit: <b>{uses_label}</b>\n"
        f"⏳ Amal qiladi: <b>{valid_label}</b>",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )


# ─────────────────────────────────────────────────────────────
#  🎯 MAXSUS (CHEGIRMALI) PROMOKOD YARATISH
# ─────────────────────────────────────────────────────────────
@router.callback_query(F.data == "admin_promo_discount_create")
async def admin_promo_discount_create_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "🎯 <b>Maxsus promokod yaratish</b>\n\n"
        "Bu turdagi promokod foydalanuvchiga <b>chegirma</b> beradi.\n"
        "1 oylik va 3 oylik tariflarga chegirma qo'llanadi.\n"
        "12 oylik tarif o'zgarmaydi.\n\n"
        "Format: <code>KOD [max_uses] [amal_kun]</code>\n\n"
        "• <b>KOD</b>: promokod matni\n"
        "• <b>max_uses</b>: nechta marta ishlatilsin (0 = cheksiz)\n"
        "• <b>amal_kun</b>: promokod necha kun amal qiladi (0 = muddatsiz)\n\n"
        "Masalan:\n"
        "<code>CHEGIRMA50 100 30</code> — 100 marta, 30 kun amal qiladi\n"
        "<code>VIP2026 0 0</code> — cheksiz, muddatsiz\n"
        "<code>SALE</code> — cheksiz, muddatsiz",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )
    await state.set_state(AdminState.promo_discount_create)
    await callback.answer()


@router.message(AdminState.promo_discount_create)
async def admin_promo_discount_create_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    parts = (message.text or "").split()
    if not parts:
        await message.answer(
            "❌ Format: <code>KOD [max_uses] [amal_kun]</code>\n"
            "Masalan: <code>CHEGIRMA50 100 30</code>",
            parse_mode="HTML",
        )
        return

    from datetime import datetime, timedelta
    from bot.services.premium_service import create_promocode

    code = parts[0].strip()

    max_uses = 0
    if len(parts) >= 2:
        try:
            max_uses = max(0, int(parts[1]))
        except ValueError:
            max_uses = 0

    expires_at = None
    valid_days = 0
    if len(parts) >= 3:
        try:
            valid_days = max(0, int(parts[2]))
        except ValueError:
            valid_days = 0
        if valid_days > 0:
            expires_at = datetime.utcnow() + timedelta(days=valid_days)

    # Maxsus promokod: 50% chegirma, bonus_days=0, is_free=False
    promo = await create_promocode(
        session, code=code, bonus_days=0, max_uses=max_uses,
        created_by=message.from_user.id, expires_at=expires_at,
        is_free=False, discount_percent=50,
    )
    await state.clear()

    if not promo:
        await message.answer(
            f"⚠️ <code>{code}</code> allaqachon mavjud.",
            parse_mode="HTML",
            reply_markup=back_to_premium_keyboard(),
        )
        return

    uses_label = "cheksiz" if max_uses == 0 else f"{max_uses} marta"
    valid_label = "muddatsiz" if valid_days == 0 else f"{valid_days} kun"

    await message.answer(
        f"✅ <b>Maxsus promokod yaratildi!</b>\n\n"
        f"🎯 Kod: <code>{promo.code}</code>\n"
        f"🔥 Chegirma: <b>50%</b>\n"
        f"📦 Qo'llanadi: <b>1 oylik va 3 oylik</b> tariflarga\n"
        f"💎 12 oylik: <b>o'zgarmaydi</b>\n\n"
        f"Natija:\n"
        f"✅ 1 oy — <b>19 900 so'm</b> (50% chegirma 🔥)\n"
        f"⭐ 3 oy — <b>39 900 so'm</b> (50% chegirma 🔥)\n"
        f"💎 12 oy — <b>179 900 so'm</b> (o'zgarmaydi)\n\n"
        f"🔢 Limit: <b>{uses_label}</b>\n"
        f"⏳ Amal qiladi: <b>{valid_label}</b>",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )


# ─────────────────────────────────────────────────────────────
#  PROMOKODLAR RO'YXATI + KUCHSIZLANTIRISH
# ─────────────────────────────────────────────────────────────
def _promos_text(promos: list) -> str:
    if not promos:
        return "🎟 <b>Promokodlar</b>\n\nHozircha promokod yaratilmagan."
    from datetime import datetime
    now = datetime.utcnow()
    text = "🎟 <b>Promokodlar</b>\n\n"
    for p in promos:
        uses = f"{p.used_count}/{p.max_uses}" if p.max_uses else f"{p.used_count}/∞"
        discount_pct = int(getattr(p, "discount_percent", 0) or 0)
        if discount_pct > 0:
            kind = f"🎯 {discount_pct}% chegirma"
        elif getattr(p, "is_free", False):
            kind = f"🎁 BEPUL {p.bonus_days} kun"
        else:
            kind = f"💳 +{p.bonus_days} kun (to'lov bilan)"
        if p.expires_at:
            if p.expires_at < now:
                valid = "⛔️ muddati tugagan"
            else:
                valid = f"{p.expires_at.strftime('%d.%m.%Y')} gacha"
        else:
            valid = "muddatsiz"
        text += (
            f"<code>{p.code}</code> · {kind} · ishlatildi {uses}\n"
            f"   ⏳ {valid}\n"
        )
    text += (
        "\n<i>O'chirilsa — faqat yangi foydalanuvchilar uchun ishlamaydi. "
        "Avval foydalanganlarning obunasiga ta'sir qilmaydi.</i>"
    )
    return text


@router.callback_query(F.data == "admin_promo_list")
async def admin_promo_list(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    from bot.services.premium_service import list_promocodes
    promos = await list_promocodes(session)

    await callback.message.edit_text(
        _promos_text(promos),
        parse_mode="HTML",
        reply_markup=admin_promo_list_keyboard(promos),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_promo_del_"))
async def admin_promo_del(callback: CallbackQuery, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    try:
        promo_id = int(callback.data.split("_")[-1])
    except ValueError:
        await callback.answer("Xato!", show_alert=True)
        return

    from bot.services.premium_service import delete_promocode, list_promocodes
    code = await delete_promocode(session, promo_id)
    if code:
        await callback.answer(f"🗑 {code} o'chirildi", show_alert=True)
    else:
        await callback.answer("Promokod topilmadi", show_alert=True)

    promos = await list_promocodes(session)
    try:
        await callback.message.edit_text(
            _promos_text(promos),
            parse_mode="HTML",
            reply_markup=admin_promo_list_keyboard(promos),
        )
    except Exception:
        pass



# ─────────────────────────────────────────────────────────────
#  💰 TARIFLAR NARXI — admin overrides
# ─────────────────────────────────────────────────────────────
def _plans_prices_text(effective_plans: dict, overrides: dict) -> str:
    from bot.config import SUBSCRIPTION_PLANS
    from bot.services.premium_service import format_price
    lines = ["💰 <b>Tariflar narxi</b>", ""]
    for key, plan in effective_plans.items():
        default_price = int(SUBSCRIPTION_PLANS.get(key, {}).get("price", 0))
        current_price = int(plan.get("price", 0))
        title = plan.get("title", key)
        emoji = plan.get("emoji", "💎")
        if key in overrides and current_price != default_price:
            lines.append(
                f"{emoji} <b>{title}</b>: <b>{format_price(current_price)} so'm</b> "
                f"🔧 <s>{format_price(default_price)}</s>"
            )
        else:
            lines.append(f"{emoji} <b>{title}</b>: <b>{format_price(current_price)} so'm</b>")
    lines.append("")
    lines.append(
        "<i>Tarifni tanlab yangi narxni yuboring. "
        "Narx o'zgartirilsa foydalanuvchilar darhol yangi narxni ko'radi. "
        "Avval yaratilgan buyurtmalarga (pending) ta'sir qilmaydi — ular yaratilgan "
        "paytdagi narxda qoladi.</i>"
    )
    return "\n".join(lines)


@router.callback_query(F.data == "admin_plans_prices")
async def admin_plans_prices_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await state.clear()
    from bot.services.plan_pricing import (
        get_effective_plans, list_overrides, refresh_plans_cache,
    )
    # Ehtiyot uchun keshni yangilab olamiz (DB'da qo'lda o'zgargan bo'lishi mumkin).
    await refresh_plans_cache(session)
    plans = get_effective_plans()
    overrides = await list_overrides(session)
    await callback.message.edit_text(
        _plans_prices_text(plans, overrides),
        parse_mode="HTML",
        reply_markup=admin_plans_prices_keyboard(plans, overrides),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("admin_plan_edit_"))
async def admin_plan_edit_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    plan_key = callback.data[len("admin_plan_edit_"):]
    from bot.config import SUBSCRIPTION_PLANS
    if plan_key not in SUBSCRIPTION_PLANS:
        await callback.answer("Bunday tarif yo'q!", show_alert=True)
        return

    from bot.services.plan_pricing import get_effective_plan, list_overrides
    from bot.services.premium_service import format_price
    plan = get_effective_plan(plan_key) or SUBSCRIPTION_PLANS[plan_key]
    overrides = await list_overrides(session)
    default_price = int(SUBSCRIPTION_PLANS[plan_key].get("price", 0))
    current_price = int(plan.get("price", 0))
    is_overridden = plan_key in overrides

    await state.update_data(plan_key=plan_key)
    await state.set_state(AdminState.plan_price_edit)
    current_title = plan.get("title", plan_key)
    current_tag = plan.get("tag", "") or ""
    tag_line = f"\n🏷 Teg: <b>{current_tag}</b>" if current_tag else ""
    await callback.message.edit_text(
        f"💰 <b>Tarif: {plan.get('emoji','💎')} {current_title}</b>\n\n"
        f"Joriy narx: <b>{format_price(current_price)} so'm</b>"
        + (f" <i>(default: {format_price(default_price)})</i>" if is_overridden and current_price != default_price else "") +
        f"\n📝 Nom: <b>{current_title}</b>{tag_line}\n\n"
        "<b>Yangi qiymatlarni yuboring.</b> Uch xil format qo'llab-quvvatlanadi:\n\n"
        "1) Faqat narx (nom va teg o'zgarmaydi):\n"
        "   <code>29900</code>\n\n"
        "2) Nom va narx (teg tegilmaydi):\n"
        "   <code>1 oy | 29900</code>\n\n"
        "3) Nom, narx va teg (teg uchun uchinchi <code>|</code>):\n"
        "   <code>3 oy | 79900 | 33% tejaysiz</code>\n\n"
        "Tegni <b>o'chirish</b> uchun uchinchi qism sifatida <code>-</code> yuboring:\n"
        "   <code>1 oy | 29900 | -</code>\n\n"
        "<i>Foydalanuvchilar yangi tugma yozuvi va narxni darhol ko'radi. "
        "Avval yaratilgan pending buyurtmalar o'z summasida qoladi (anti-tamper).</i>",
        parse_mode="HTML",
        reply_markup=admin_plan_edit_keyboard(plan_key, is_overridden and current_price != default_price),
    )
    await callback.answer()


@router.message(AdminState.plan_price_edit)
async def admin_plan_price_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    data = await state.get_data()
    plan_key = data.get("plan_key")
    from bot.config import SUBSCRIPTION_PLANS
    if not plan_key or plan_key not in SUBSCRIPTION_PLANS:
        await state.clear()
        await message.answer("❌ Tarif yo'qoldi. Qaytadan urinib ko'ring.", reply_markup=back_to_premium_keyboard())
        return

    raw = (message.text or "").strip()
    if not raw:
        await message.answer("❌ Bo'sh xabar. Qayta yuboring.")
        return

    # Uch xil format:
    #   "29900"                          → faqat narx
    #   "1 oy | 29900"                   → nom + narx
    #   "3 oy | 79900 | 33% tejaysiz"    → nom + narx + teg
    parts = [p.strip() for p in raw.split("|")]
    new_title = None
    new_tag = None
    price_str = raw
    if len(parts) == 1:
        price_str = parts[0]
    elif len(parts) == 2:
        new_title, price_str = parts[0], parts[1]
    elif len(parts) >= 3:
        new_title, price_str, new_tag = parts[0], parts[1], parts[2]
    else:
        await message.answer(
            "❌ Format xato. Namunalar: <code>29900</code> yoki "
            "<code>1 oy | 29900</code> yoki <code>3 oy | 79900 | 33% tejaysiz</code>",
            parse_mode="HTML",
        )
        return

    normalized_price = price_str.replace(" ", "").replace(",", "").replace("_", "")
    try:
        price = int(normalized_price)
    except ValueError:
        await message.answer(
            "❌ Narx qismi butun raqam bo'lishi kerak (so'mda). Masalan: <code>29900</code>",
            parse_mode="HTML",
        )
        return

    from bot.services.plan_pricing import set_plan_meta, get_effective_plan
    from bot.services.premium_service import format_price
    try:
        await set_plan_meta(
            session, plan_key,
            price=price,
            title=(new_title if new_title else None),
            tag=(new_tag if new_tag is not None else None),
            updated_by=message.from_user.id,
        )
    except ValueError as e:
        await message.answer(f"❌ {e}", parse_mode="HTML")
        return
    except Exception as e:
        await message.answer(f"❌ Xato: {e}")
        return

    await state.clear()
    plan = get_effective_plan(plan_key)
    default_price = int(SUBSCRIPTION_PLANS[plan_key].get("price", 0))
    delta = ""
    if price != default_price:
        delta = f"\n<i>Default narx: {format_price(default_price)} so'm</i>"
    tag_line = ""
    if plan.get("tag"):
        tag_line = f"\n🏷 Teg: <b>{plan['tag']}</b>"
    await message.answer(
        f"✅ <b>Tarif yangilandi!</b>\n\n"
        f"{plan.get('emoji','💎')} <b>{plan.get('title', plan_key)}</b>{tag_line}\n"
        f"💰 <b>{format_price(price)} so'm</b>{delta}\n\n"
        f"Foydalanuvchilar (bot va Mini App) endi yangi tugma yozuvi va narxni ko'radi.",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )


@router.callback_query(F.data.startswith("admin_plan_reset_"))
async def admin_plan_reset(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return

    plan_key = callback.data[len("admin_plan_reset_"):]
    from bot.config import SUBSCRIPTION_PLANS
    if plan_key not in SUBSCRIPTION_PLANS:
        await callback.answer("Bunday tarif yo'q!", show_alert=True)
        return

    from bot.services.plan_pricing import reset_plan_price, get_effective_plans, list_overrides
    await reset_plan_price(session, plan_key)
    await state.clear()

    plans = get_effective_plans()
    overrides = await list_overrides(session)
    await callback.message.edit_text(
        _plans_prices_text(plans, overrides),
        parse_mode="HTML",
        reply_markup=admin_plans_prices_keyboard(plans, overrides),
    )
    await callback.answer("↺ Default narxga qaytarildi", show_alert=True)
