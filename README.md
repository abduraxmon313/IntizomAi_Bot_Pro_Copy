# Intizom AI

**An AI-powered discipline operating system for Gen Z students.**

A Telegram bot + Mini App that turns goals into habits via XP,
streaks, daily quests, and an emotional AI coach.

---

## What's inside

### Bot (aiogram 3)
- Voice + text plan extraction (Whisper + GPT-4o-mini)
- Natural-language time parsing (uz/ru/en/tr → uz)
- Per-minute reminders, daily summary, evening reflection,
  morning nudge, streak warning, comeback ping
- Admin panel with user/admin management + broadcast

### Mini App (FastAPI + vanilla JS SPA)
- Discipline ring, XP / level bar, rank chip
- Daily Quest card with progress
- Real AI Coach page — mood, energy, intent, evening reflection
- Smart insights based on the user's last 30 days
- Calendar, weekly diary, monthly grid for goals
- Statistics: trend chart, heatmap, donut, achievements
- 6 themes + dark mode
- Achievement unlock modal with confetti
- 3-step first-run onboarding

### Gamification engine
- XP curve `50 × (n−1) × n` — fast early, earned later
- 30-day discipline score (0-100) — completion + streak +
  intensity + inactivity penalty
- Streak with grace day & freeze tokens
- Persistent achievement unlocks (15 badges, 4 rarities)
- Auto-rank: Boshlovchi → Legend → Mythic

### API surface (`/api/webapp/...`)
- `GET /plans?date_from=&date_to=` · CRUD for plans
- `GET /goals` · CRUD for goals
- `GET /stats` · full gamification snapshot
- `GET /coach` · contextual coach message
- `GET /quest` · daily mission with progress
- `GET|POST /checkin` · mood / energy / intent / reflection

---

## Layout

```
bot/
  handlers/      aiogram routers (start, plan, callback, report, status, admin)
  keyboards/     reusable inline + reply keyboards
  models/        SQLAlchemy: User, Plan, ScoreLog, Admin, Goal, Achievement, DailyCheckin
  services/      gamification, coach, score, plan, goal, scheduler, ai, user, admin
  utils/         formatters
  main.py        bot bootstrap
database/
  db.py          engine + idempotent migrations
webapp/
  app.py         FastAPI app + bot lifespan (RUN_BOT bilan boshqariladi)
  security.py    Telegram initData HMAC tekshiruvi + rate limit + auth dependency
  routes/        plans, goals, stats, subscription, ai
  static/        index.html (single-file SPA)
start.py         lokal kirish nuqtasi — uvicorn serverni ishga tushiradi (bot lifespan orqali)
```

---

## Environment variables

| O'zgaruvchi | Default | Izoh |
|---|---|---|
| `BOT_TOKEN` | — | Telegram bot tokeni (majburiy) |
| `OPENAI_API_KEY` | — | OpenAI kaliti (majburiy) |
| `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASS` | — | Postgres ulanishi |
| `ADMIN_ID` | `0` | Super admin telegram_id |
| `WEBAPP_URL` | `""` | Mini App public HTTPS manzili |
| `PROMO_CODE` | `intizom` | Sinov promokodi |
| `FREE_DAILY_PLAN_LIMIT` | `5` | Bepul kunlik reja limiti |
| `FREE_AI_DAILY_LIMIT` | `3` | Bepul kunlik AI suhbat limiti |
| `STRICT_AUTH` | `true` | **Xavfsizlik**: faqat tasdiqlangan Telegram initData'ga ruxsat. `false` qilinsa query `telegram_id` ga ham ruxsat beriladi (tavsiya etilmaydi) |
| `RUN_BOT` | `true` | Bot shu server jarayonida ishga tushsinmi. Ko'p worker / alohida bot jarayonida `false` qiling (409 Conflict'dan saqlanish) |

---

## Run locally

```bash
pip install -r requirements.txt
# .env: BOT_TOKEN, OPENAI_API_KEY, DB_*, ADMIN_ID
# optional: WEBAPP_URL=https://<your-public-https>/
# optional: STRICT_AUTH=false  (faqat lokal/brauzer demo uchun)
python start.py
```

> `start.py` faqat uvicorn serverni ishga tushiradi; bot esa FastAPI
> `lifespan` ichida bir marta ishga tushadi. Shu sabab bot ikki marta
> polling qilmaydi (Telegram 409 Conflict bo'lmaydi).

## Deploy (Railway)

`railway.json` va `Procfile` `uvicorn webapp.app:app` ni ishga tushiradi.
FastAPI lifespan bot'ni xuddi shu jarayonda ishga tushiradi (`RUN_BOT=true`).
Migratsiyalar startda `_run_migrations()` orqali avtomatik ishlaydi.

> **Xavfsizlik:** `STRICT_AUTH=true` (default) bo'lganda Mini App API faqat
> Telegram orqali ochilgan, HMAC bilan tasdiqlangan so'rovlarni qabul qiladi.
> Agar kerak bo'lsa, Railway env'da `STRICT_AUTH=false` qilib vaqtincha
> yumshatish mumkin (lekin bu IDOR xavfini qaytaradi).
