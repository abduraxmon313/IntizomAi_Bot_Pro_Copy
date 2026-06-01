from aiogram import Router, F
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
    admin_promo_list_keyboard,
    admin_keys_keyboard, admin_keys_confirm_keyboard,
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

@router.message(Command("admin"))
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


# ===================== WLCM TO'LOV KALITLARI (ONBOARDING) =====================
# Faqat super admin (ADMIN_ID) ko'radi va boshqaradi — bu bo'lim maxfiy
# api_key/api_secret ni ochib beradi va cheklangan martalik tokenni sarflaydi.

def _mask(value: str, head: int = 6, tail: int = 4) -> str:
    value = value or ""
    if not value:
        return "(yo'q)"
    if len(value) <= head + tail:
        return "***"
    return f"{value[:head]}…{value[-tail:]}"


async def _is_super_admin(callback: CallbackQuery) -> bool:
    from bot.config import ADMIN_ID
    if callback.from_user.id != ADMIN_ID:
        await callback.answer(
            "❌ Bu bo'lim faqat bosh admin (super admin) uchun.",
            show_alert=True,
        )
        return False
    return True


@router.callback_query(F.data == "admin_keys")
async def admin_keys_menu(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await _is_super_admin(callback):
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
        )

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
    if not await _is_super_admin(callback):
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
    if not await _is_super_admin(callback):
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
    if not await _is_super_admin(callback):
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
    if not await _is_super_admin(callback):
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


@router.callback_query(F.data == "admin_premium_grant")
async def admin_premium_grant_start(callback: CallbackQuery, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, callback.from_user.id):
        await callback.answer("❌ Ruxsat yo'q!", show_alert=True)
        return
    await callback.message.edit_text(
        "➕ <b>Premium berish</b>\n\n"
        "Telegram ID va tarifni yuboring.\n"
        "Format: <code>ID tarif</code>\n\n"
        "Tariflar: <code>7d</code> / <code>1m</code> / <code>3m</code> / <code>6m</code> / <code>12m</code>\n"
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
            "❌ Noma'lum tarif. 1m / 3m / 6m / 12m dan birini yozing."
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
        "Format: <code>KOD bonus_kun [max_uses] [amal_kun]</code>\n\n"
        "• <b>bonus_kun</b>: tarifga qo'shiladigan kunlar.\n"
        "   <code>0</code> = obuna <b>BEPUL</b> ochiladi (to'lovsiz)\n"
        "• <b>max_uses</b>: nechta marta ishlatilsin (0 = cheksiz)\n"
        "• <b>amal_kun</b>: promokod necha kun amal qiladi (0 = muddatsiz)\n\n"
        "Masalan:\n"
        "<code>YANGI2026 15 100 30</code> — +15 kun, 100 marta, 30 kun amal qiladi\n"
        "<code>SOVGA 0 0 7</code> — bepul obuna, cheksiz, 7 kun amal qiladi",
        parse_mode="HTML",
        reply_markup=back_to_premium_keyboard(),
    )
    await state.set_state(AdminState.promo_create)
    await callback.answer()


@router.message(AdminState.promo_create)
async def admin_promo_create_process(message: Message, state: FSMContext, session: AsyncSession):
    if not await is_admin(session, message.from_user.id):
        return

    parts = (message.text or "").split()
    if len(parts) < 2:
        await message.answer(
            "❌ Format: <code>KOD bonus_kun [max_uses] [amal_kun]</code>\n"
            "Masalan: <code>YANGI2026 15 100 30</code>",
            parse_mode="HTML",
        )
        return

    from datetime import datetime, timedelta
    from bot.services.premium_service import create_promocode

    code = parts[0].strip()
    try:
        bonus_days = max(0, int(parts[1]))
    except ValueError:
        await message.answer("❌ <b>bonus_kun</b> butun son bo'lishi kerak. Masalan: <code>YANGI 15 100 30</code>", parse_mode="HTML")
        return

    max_uses = 0
    if len(parts) >= 3:
        try:
            max_uses = max(0, int(parts[2]))
        except ValueError:
            max_uses = 0

    expires_at = None
    valid_days = 0
    if len(parts) >= 4:
        try:
            valid_days = max(0, int(parts[3]))
        except ValueError:
            valid_days = 0
        if valid_days > 0:
            expires_at = datetime.utcnow() + timedelta(days=valid_days)

    promo = await create_promocode(
        session, code=code, bonus_days=bonus_days, max_uses=max_uses,
        created_by=message.from_user.id, expires_at=expires_at,
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
    if bonus_days == 0:
        type_label = "🎁 <b>BEPUL obuna</b> (to'lovsiz ochiladi)"
    else:
        type_label = f"🎁 Bonus: <b>+{bonus_days} kun</b> (tarif ustiga qo'shiladi)"

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
        kind = "🎁 BEPUL" if (p.bonus_days or 0) == 0 else f"+{p.bonus_days} kun"
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
