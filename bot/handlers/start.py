import os

from aiogram import Router, F
from aiogram.enums import ChatType
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    WebAppInfo,
)
from aiogram.filters import CommandStart, CommandObject
from sqlalchemy.ext.asyncio import AsyncSession

from bot.keyboards.main_menu import main_menu_keyboard
from bot.keyboards.reply_keys import main_reply_keyboard
from bot.keyboards.subscribe_keys import contact_keyboard, premium_promo_keyboard
from bot.services.gamification_service import xp_progress, rank_for_level
from bot.services.user_service import get_or_create_user, get_user_by_telegram_id
from bot.services.premium_service import user_is_premium, days_left
from bot.services.referral_service import parse_referrer_id, register_referral
from bot.services.group_service import (
    GroupError, join_by_code, parse_invite_code_from_payload,
)

router = Router()


def parse_premium_payload(args: str | None) -> tuple[bool, str | None]:
    """
    `/start` payload'ini tekshiradi (Mini App tariflar tugmasidan kelgan
    deep-link uchun).

    Qabul qilinadigan formatlar:
      • `premium`        → oddiy Premium menyusi (tariflar ro'yxati)
      • `premium_<plan>` → to'g'ridan-to'g'ri o'sha tarifning to'lov usulini
                           tanlash oynasi (masalan: `premium_1m`, `premium_3m`, `premium_12m`)

    Qaytaradi: (is_premium_start, plan_key or None).
    Boshqa payload'lar (ref_..., grp_...) uchun (False, None) qaytadi — bu
    parser ular bilan ziddiyatsiz.
    """
    if not args:
        return False, None
    s = args.strip().lower()
    if s == "premium":
        return True, None
    if s.startswith("premium_"):
        plan = s.split("_", 1)[1].strip()
        return True, (plan or None)
    return False, None


WEBAPP_URL = os.getenv("WEBAPP_URL", "").strip()


def _persona_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Talaba", callback_data="ob_persona:student")],
        [InlineKeyboardButton(text="💼 Mutaxassis / ishchi", callback_data="ob_persona:pro")],
        [InlineKeyboardButton(text="🌱 O'zimni rivojlantiraman", callback_data="ob_persona:self")],
        [InlineKeyboardButton(text="⚡ Hammasi", callback_data="ob_persona:mixed")],
    ])


PERSONA_EXAMPLE = {
    "student": "Masalan: «Soat 7 da turaman, 2 soat dars qilaman, 21 da kitob o'qiyman»",
    "pro": "Masalan: «8 da sport, 10 da eng muhim vazifa, 18 da kunlik reja»",
    "self": "Masalan: «6 da turaman, 7 da yugurish, 22 da kitob o'qish»",
    "mixed": "Masalan: «Erta turish, sport, kitob, suv ichish»",
}


def _webapp_kb(is_premium: bool) -> InlineKeyboardMarkup | None:
    """
    Mini App tugmasi HAMMAGA ko'rsatiladi (bepul foydalanuvchi ham ochib,
    qiymatini ko'rishi → premiumga undash). Obunasizlarga qo'shimcha "Obuna"
    promo tugmalari ham qo'shiladi.
    """
    rows = []
    if WEBAPP_URL:
        rows.append([InlineKeyboardButton(
            text="✨ Mini App ochish",
            web_app=WebAppInfo(url=WEBAPP_URL),
        )])
    if not is_premium:
        # Obuna promo tugmalarini ham qo'shamiz (Mini App ichidagi premium
        # imkoniyatlar uchun).
        promo = premium_promo_keyboard()
        try:
            rows.extend(promo.inline_keyboard)
        except Exception:
            pass
    return InlineKeyboardMarkup(inline_keyboard=rows) if rows else None


# /start guruhda alohida ishlaydi (task 10 uchun chat_events.py'da handler bor).
# Bu esa faqat DM'da normal /start oqimi.
@router.message(CommandStart(), F.chat.type == ChatType.PRIVATE)
async def start_handler(message: Message, command: CommandObject, session: AsyncSession):
    # Foydalanuvchi avval mavjudmidi? (referral faqat YANGI userlar uchun)
    existing = await get_user_by_telegram_id(session, message.from_user.id)
    is_new = existing is None

    user = await get_or_create_user(
        session=session,
        telegram_id=message.from_user.id,
        full_name=message.from_user.full_name,
        username=message.from_user.username or "",
    )

    # ── Referral (taklif havolasi) — yangi foydalanuvchini taklif qiluvchiga bog'lash
    if is_new:
        referrer_id = parse_referrer_id(command.args)
        if referrer_id:
            try:
                await register_referral(
                    session, referrer_id, user, bot=message.bot,
                )
            except Exception:
                # Referral xatosi /start oqimini to'xtatmasin
                pass

    # ── Guruh taklifi (Do'stlar moduli) — payload `grp_<code>` ────
    # Yangi va eski foydalanuvchilar uchun ham ishlaydi (agar allaqachon
    # a'zo bo'lgan bo'lsa — no-op). Xato bo'lsa oqimni to'xtatmaymiz.
    joined_group_name: str | None = None
    grp_code = parse_invite_code_from_payload(command.args)
    if grp_code:
        try:
            g = await join_by_code(session, user, grp_code)
            joined_group_name = g.name
        except GroupError:
            joined_group_name = None
        except Exception:
            joined_group_name = None

    # ── Mini App'dan kelgan Premium tugmasi (deep-link `premium` / `premium_<plan>`) ──
    # Foydalanuvchi Mini App Settings > Obunani uzaytirish'da tarifni bosdi va
    # bot chatiga o'tkazildi. Oddiy /start salomlashuvini o'tkazib yuborib,
    # to'g'ridan-to'g'ri Premium/to'lov oqimini ochamiz.
    is_premium_start, premium_plan_key = parse_premium_payload(command.args)
    if is_premium_start:
        # `name` bu blok ichida kerak (pastdagi standart oqimda aniqlanadi,
        # lekin biz erta `return` qilamiz — shu sabab bu yerda o'zimiz olamiz).
        premium_name = (user.display_name or user.full_name or "do'st")
        # main reply keyboard'ni faqat yangi user uchun ko'rsatamiz (u hali
        # klaviaturani ko'rmagan bo'lishi mumkin). Keyin darhol Premium oynasi.
        if is_new or not user.onboarded:
            try:
                await message.answer(
                    f"👋 <b>Salom, {premium_name}!</b>\n\n"
                    "Mini App'dan Premium tanlashingizni ko'rdim. To'lovni shu yerda yakunlaymiz 👇",
                    parse_mode="HTML",
                    reply_markup=main_reply_keyboard(),
                )
            except Exception:
                pass
        from bot.handlers.subscribe import open_premium_flow
        try:
            await open_premium_flow(
                message, session, message.from_user.id, premium_plan_key,
            )
        except Exception:
            # Xato bo'lsa oqimni tush davom ettirmaymiz — foydalanuvchini
            # oddiy welcome bilan chalkashtirmaymiz. Xato loglanadi.
            import logging
            logging.getLogger(__name__).exception(
                "premium deep-link ochishda xato (user=%s, plan=%s)",
                message.from_user.id, premium_plan_key,
            )
            await message.answer(
                "⚠️ Premium oynasini ochib bo'lmadi. Iltimos, «💎 Premium» "
                "tugmasini bosib qayta urinib ko'ring.",
            )
        return

    # Eslatma: 3 kunlik trial funksiyasi butunlay olib tashlangan. Bepul
    # Premium olishning yagona yo'li — do'st taklif qilish (referral bonusi).

    name = (user.display_name or user.full_name or "do'st")

    # ── Guruh taklifi orqali kelgan bo'lsa — BIRINCHI qilib guruhga qo'shilish
    # haqida xabar yuboramiz (foydalanuvchi darhol bilishi uchun), keyin
    # odatiy /start oqimi davom etadi.
    if joined_group_name:
        try:
            await message.answer(
                f"👥 <b>Siz «{joined_group_name}» guruhiga qo'shildingiz!</b>\n\n"
                "Mini App'ning <b>Do'stlar</b> bo'limidan guruh a'zolarini "
                "va ularning bugungi holatini ko'ring.",
                parse_mode="HTML",
            )
        except Exception:
            pass

    # ── YANGI yoki onboarding tugatmagan foydalanuvchi: bot ichida onboarding ──
    if is_new or not user.onboarded:
        welcome = (
            f"🎯 <b>Salom, {name}!</b>\n\n"
            "Men — <b>Intizom AI</b>.\n\n"
            "🗒 <b>Rejangizni yozing</b> → 🔔 <b>vaqtida eslataman</b> → "
            "✅ <b>bajarganingizni kuzataman</b> → 🔥 <b>streakingizni saqlayman</b>.\n\n"
            "Bugundan boshlab bitta oddiy va'da: <b>har kuni kamida 1 ta narsa bajarish</b>."
        )
        await message.answer(welcome, parse_mode="HTML", reply_markup=main_reply_keyboard())
        await message.answer(
            "🧭 <b>Avval bitta savol — siz kimsiz?</b>\n\n"
            "Bu sizga mos maslahat va eslatmalar berishimga yordam beradi 👇",
            parse_mode="HTML",
            reply_markup=_persona_kb(),
        )
        return

    # ── Mavjud (onboarding tugatgan) foydalanuvchi ──
    lvl, in_lvl, needed, pct = xp_progress(user.xp or 0)
    rank, emoji = rank_for_level(lvl)
    # Xush kelibsiz matni (odatiy /start) — guruh xabari yuqorida alohida
    # yuborilgan bo'lsa ham, bu qismda takrorlamaymiz.
    text = (
        f"🎯 <b>Xush kelibsiz, {name}!</b>\n\n"
        f"{emoji} <b>{rank}</b>  ·  {lvl}-daraja\n"
        f"🔥 Streak: <b>{user.streak or 0} kun</b>   ⭐️ Ball: <b>{user.total_score or 0}</b>\n"
        f"💎 Intizom kuchi: <b>{user.discipline_score or 50}/100</b>\n\n"
        "Bugun nima qilamiz? 👇"
    )
    await message.answer(text, parse_mode="HTML", reply_markup=main_reply_keyboard())

    is_premium = user_is_premium(user)
    webapp_kb = _webapp_kb(is_premium)
    if webapp_kb:
        if is_premium:
            promo_text = (
                "🚀 <b>Mini App</b> — kalendar, statistika, odatlar va AI Coach.\n"
                f"💎 Premium faol — <b>{days_left(user)} kun</b> qoldi."
            )
        else:
            promo_text = (
                "🚀 <b>Mini App</b> — kalendar, statistika, odatlar va AI Coach bir joyda.\n\n"
                "Bepul ochib ko'ring 👇 Cheksiz imkoniyat uchun 💎 <b>Premium</b>."
            )
        await message.answer(promo_text, parse_mode="HTML", reply_markup=webapp_kb)


@router.callback_query(F.data.startswith("ob_persona:"))
async def ob_persona_handler(callback: CallbackQuery, session: AsyncSession):
    persona = callback.data.split(":", 1)[1]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✋ Va'da beraman", callback_data=f"ob_commit:{persona}")],
    ])
    try:
        await callback.message.edit_text(
            "🔥 <b>Bitta va'da</b>\n\n"
            "Har kuni kamida <b>1 ta</b> narsa bajarish — o'zingizga va kelajagingizga "
            "bergan va'da. Kichik qadamlar katta natijaga olib boradi.\n\n"
            "Tayyormisiz? 👇",
            parse_mode="HTML",
            reply_markup=kb,
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data.startswith("ob_commit:"))
async def ob_commit_handler(callback: CallbackQuery, session: AsyncSession):
    persona = callback.data.split(":", 1)[1]
    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if user and not user.onboarded:
        user.onboarded = True
        try:
            await session.commit()
        except Exception:
            await session.rollback()

    example = PERSONA_EXAMPLE.get(persona, PERSONA_EXAMPLE["mixed"])
    is_premium = user_is_premium(user) if user else False
    await callback.message.edit_text(
        "🎉 <b>Boshladik!</b>\n\n"
        "Endi bugun nima qilmoqchiligingizni shunchaki <b>yozing yoki ayting</b> — "
        "men uni rejaga aylantirib, vaqtida eslatib turaman.\n\n"
        f"<i>{example}</i>",
        parse_mode="HTML",
        reply_markup=_webapp_kb(is_premium),
    )
    await callback.answer("🚀 Boshlandi!")


@router.message(F.text == "📞 Bog'lanish")
async def contact_admin(message: Message):
    await message.answer(
        "📞 <b>Bog'lanish</b>\n\nQuyidagidan birini tanlang 👇",
        parse_mode="HTML",
        reply_markup=contact_keyboard(),
    )


@router.callback_query(F.data == "home")
async def home_handler(callback: CallbackQuery, session: AsyncSession):
    user = await get_user_by_telegram_id(session, callback.from_user.id)

    lvl, in_lvl, needed, pct = xp_progress(user.xp or 0)
    rank, emoji = rank_for_level(lvl)
    name = user.display_name or user.full_name or "do'st"

    await callback.message.edit_text(
        f"🏠 <b>Bosh sahifa</b>\n\n"
        f"{emoji} <b>{name}</b>\n"
        f"{rank}  ·  {lvl}-daraja\n\n"
        f"🔥 Streak: <b>{user.streak or 0} kun</b>   ⭐️ Ball: <b>{user.total_score or 0}</b>\n"
        f"💎 Intizom kuchi: <b>{user.discipline_score or 50}/100</b>",
        parse_mode="HTML",
        reply_markup=main_menu_keyboard(),
    )
    await callback.answer()
