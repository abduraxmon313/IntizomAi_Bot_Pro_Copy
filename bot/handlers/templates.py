"""
Faza 3: Reja shablonlari (templates).

Tayyor reja to'plamlari (imtihonga tayyorgarlik, ertalabki rejim, fitnes...).
Bir tegishda bir nechta reja qo'shiladi — "bo'sh sahifa" muammosini yo'qotadi.

/shablon → ro'yxat → tanlash → bir nechta reja yaratiladi.
"""
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy.ext.asyncio import AsyncSession

from bot.services.user_service import get_user_by_telegram_id
from bot.services.plan_service import create_plans, get_today_plans
from bot.services.premium_service import check_plan_limit
from bot.utils.formatters import format_plan_list

router = Router()


# Shablon katalogi: key -> {nom, emoji, items:[(title, time, score)]}
TEMPLATES: dict[str, dict] = {
    "morning": {
        "title": "Ertalabki rejim", "emoji": "🌅",
        "items": [
            ("Erta uyg'onish (06:00)", "06:00", 6),
            ("1 stakan suv ichish", "06:10", 3),
            ("10 daqiqa mashq", "06:20", 5),
            ("Reja tuzish (kun rejasi)", "06:40", 5),
        ],
    },
    "exam": {
        "title": "Imtihonga tayyorgarlik", "emoji": "📚",
        "items": [
            ("1 mavzuni takrorlash", "09:00", 8),
            ("Konspekt yozish", "11:00", 6),
            ("Test ishlash (20 ta)", "15:00", 8),
            ("Xatolar ustida ishlash", "18:00", 6),
        ],
    },
    "fitness": {
        "title": "Fitnes kuni", "emoji": "💪",
        "items": [
            ("Ertalabki yugurish (3 km)", "07:00", 6),
            ("Kuch mashqlari", "17:00", 8),
            ("2 litr suv ichish", None, 3),
            ("Erta uxlash (22:30)", "22:30", 5),
        ],
    },
    "deep_work": {
        "title": "Chuqur ish (Deep Work)", "emoji": "🎯",
        "items": [
            ("Eng muhim vazifa (90 daq)", "09:00", 8),
            ("Tanaffus + yurish", "10:30", 3),
            ("Ikkinchi fokus blok", "11:00", 8),
            ("Kunni yakunlash & reja", "18:00", 5),
        ],
    },
}


def _list_keyboard() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        text=f"{t['emoji']} {t['title']} ({len(t['items'])} reja)",
        callback_data=f"tpl_{key}",
    )] for key, t in TEMPLATES.items()]
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("shablon"))
async def templates_command(message: Message):
    await message.answer(
        "📦 <b>Reja shablonlari</b>\n\n"
        "Tayyor to'plamni tanlang — barcha rejalar bir tegishda qo'shiladi 👇",
        parse_mode="HTML",
        reply_markup=_list_keyboard(),
    )


@router.callback_query(F.data == "templates_open")
async def templates_open_cb(callback: CallbackQuery):
    await callback.message.answer(
        "📦 <b>Reja shablonlari</b>\n\nTayyor to'plamni tanlang 👇",
        parse_mode="HTML",
        reply_markup=_list_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("tpl_"))
async def apply_template_cb(callback: CallbackQuery, session: AsyncSession):
    key = callback.data.replace("tpl_", "")
    tpl = TEMPLATES.get(key)
    if not tpl:
        await callback.answer("Shablon topilmadi", show_alert=True)
        return

    user = await get_user_by_telegram_id(session, callback.from_user.id)
    if not user:
        await callback.answer("Iltimos /start bosing.", show_alert=True)
        return

    items = tpl["items"]
    limit = await check_plan_limit(session, user, adding=len(items))
    if not limit.allowed:
        from bot.keyboards.subscribe_keys import buy_subscription_keyboard
        try:
            from bot.services.analytics_service import track
            await track(callback.from_user.id, "paywall_view", user_id=user.id, source="template")
        except Exception:
            pass
        await callback.message.edit_text(
            f"🔒 <b>Bepul limit yetmaydi</b>\n\n"
            f"Bu shablon {len(items)} ta reja qo'shadi, lekin bepul rejimda "
            f"kuniga {limit.limit} ta cheklov bor (bugun {limit.used}/{limit.limit}).\n\n"
            "💎 Premium bilan cheksiz reja va shablonlar ochiladi.",
            parse_mode="HTML",
            reply_markup=buy_subscription_keyboard(),
        )
        await callback.answer()
        return

    plans_data = [
        {"title": t, "scheduled_time": tm, "score_value": sc, "for_tomorrow": False}
        for (t, tm, sc) in items
    ]
    await create_plans(session, user, plans_data)
    try:
        from bot.services.analytics_service import track
        await track(callback.from_user.id, "template_applied", user_id=user.id, template=key)
    except Exception:
        pass

    all_plans = await get_today_plans(session, user)
    await callback.message.edit_text(
        f"✅ <b>{tpl['emoji']} {tpl['title']}</b> qo'shildi!\n\n{format_plan_list(all_plans)}",
        parse_mode="HTML",
    )
    await callback.answer("Shablon qo'shildi! 📦")
