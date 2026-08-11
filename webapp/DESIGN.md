# Intizom AI — Mini App dizayn tizimi

Bu hujjat WebApp (Telegram Mini App) interfeysining **qoidalarini** belgilaydi.
Yangi ekran yoki komponent qo'shganda shu qoidalarga amal qilinadi — shunda
ilova bir butun, professional mahsulot bo'lib qoladi.

Manba fayllar:

| Fayl | Vazifasi |
|---|---|
| `static/app.css` | Dizayn tokenlari + barcha komponentlar |
| `static/index.html` | Sahifa strukturasi + SVG ikonka sprite'i |
| `static/app.js` | Render mantiqi (`icon()`, `emptyState()`, `renderError()`, skeleton) |

---

## 1. Nima uchun bu qoidalar kerak bo'ldi

Oldingi interfeys quyidagi sabablarga ko'ra "o'yin / multfilm" ko'rinishida edi:

- **Gradient hamma joyda.** `--grad` ~30 ta komponentga qo'llanardi (tugma, chip,
  segment, checkbox, avatar, progress, statistika raqamlari, nav tugmasi…).
  Hamma narsa urg'ulangan bo'lsa — **hech narsa** urg'ulanmaydi.
- **To'xtovsiz harakat.** ~20 ta cheksiz (`infinite`) animatsiya bir vaqtda
  ishlab turardi: fonda suzuvchi rangli dog'lar, sozlama ikonkasining aylanishi
  (`gearSpin`), tugmalarning "nafas olishi" (`glowPulse`), hero ustidan o'tuvchi
  yorug'lik, header tugmalarining suzishi va boshqalar. Bu diqqatni tortadi va
  batareyani yeydi.
- **Sakrash effekti.** `cubic-bezier(.34,1.56,.64,1)` — overshoot qiladigan
  easing deyarli har bir o'tishda ishlatilgan edi.
- **Emoji ikonka o'rnida.** Sarlavhalar (`Maqsadlar 🎯`), sozlamalar, statistika
  kartochkalari, toastlar — hammasida emoji. Emoji har platformada boshqacha
  chiziladi, `currentColor` ni olmaydi va norasmiy ohang beradi.
- **Nishonlash effektlari haddan tashqari.** Har bir belgilashda 28–35 dona
  konfetti + ekran markazida katta XP oynasi.

---

## 2. Oltita qoida

### 2.1. Rang — bitta urg'u

- Neytral shkala (`--n-0` … `--n-900`) + **bitta** urg'u rangi (`--primary`).
- **Gradient faqat bitta joyda**: asosiy sahifadagi `.hero-v2` kartochkasi.
  Bu ilovaning yagona "fokus nuqtasi" — Discipline Score.
- Qolgan hamma narsa **to'q (solid)** rang: tugma `--primary`, fon `--surface`,
  chegara `--border`.
- Urg'u fonida matn uchun `--primary-fg` ishlatiladi (qorong'i rejimda urg'u
  yorug'lashadi, shuning uchun matn to'q bo'ladi).

```css
/* TO'G'RI */          /* NOTO'G'RI */
background: var(--primary);   background: var(--grad);
```

### 2.2. Harakat — faqat holat o'zgarganda

- Davomiylik: `--dur-fast` 120ms, `--dur` 180ms, `--dur-slow` 260ms.
- Easing: `--ease: cubic-bezier(.2,.7,.3,1)` — sekinlashadi, **sakramaydi**.
- **Cheksiz dekorativ animatsiya taqiqlanadi.** Ruxsat etilganlar faqat:
  skeleton shimmer, chat "yozyapti" nuqtalari.
- `prefers-reduced-motion: reduce` to'liq hurmat qilinadi (CSS'da global blok).

### 2.3. Ikonka — SVG sprite, emoji emas

`index.html` boshida `<symbol id="i-*">` sprite'i turadi. Ishlatilishi:

```html
<svg class="ic ic-18"><use href="#i-plus"/></svg>
```

```js
icon('plus', 18)   // app.js ichida
```

**Emoji FAQAT foydalanuvchi/domen mazmuni uchun:**

| Ruxsat etiladi (mazmun) | Taqiqlanadi (interfeys) |
|---|---|
| Foydalanuvchi tanlagan odat belgisi (`HABIT_ICONS`) | Sarlavha, tugma, sozlama qatori |
| Backend'dan keladigan `rank_emoji`, quest ikonkasi | Statistika kartochkasi belgisi |
| Yutuq nishonlari, reyting medallari | Bo'sh holat, toast, dialog ikonkasi |
| Kayfiyat tanlagichi | Badge / chip |

Yangi ikonka kerak bo'lsa — sprite'ga `<symbol>` qo'shiladi (stroke uslubi,
`viewBox="0 0 24 24"`, `stroke-width="1.75"`).

> **Diqqat:** `svg.ic` ataylab `display:inline-block` — shunda ikonka matn
> oqimida (`⏰ 07:00 · 🔥 4 kun` kabi meta qatorlarda) yangi qatorga tushmaydi.
> `display:block` qilib qo'yilsa qatorlar buziladi.

### 2.4. Tipografika

- O'lchamlar: 10.5 / 11 / 11.5 / 12 / 12.5 / 13 / 13.5 / 14 / 15 / 17 / 19 / 22 / 24px.
- Qalinlik: **400–700** oralig'ida (`800`/`900` ishlatilmaydi).
- Bo'lim sarlavhasi (`.section-title h2`): 13px, `600`, `uppercase`, `--text-2`.
- Raqamlar `tabular-nums` (body'da global) — count-up animatsiyasida sakramaydi.

### 2.5. Chuqurlik va shakl

- 1px hairline chegara (`--border`) + juda yumshoq **neytral** soya.
- **Rangli "glow" soya ishlatilmaydi.**
- Radius: `--r-xs` 6 → `--r-2xl` 18px (ilgari 22–26px edi).

### 2.6. Foydalanish imkoniyati (a11y)

- Tegish nishoni **≥ 40px** (ilgari tahrirlash/o'chirish tugmalari 28px edi).
- `:focus-visible` halqasi mavjud (klaviatura bilan navigatsiya).
- Matn kontrasti WCAG AA (≥ 4.5:1). `--text-3` yordamchi matn uchun ham
  4.5:1 dan past emas.
- `user-scalable=no` **olib tashlangan** — foydalanuvchi kattalashtira oladi.
- Interaktiv `div`larda `role` + `tabindex` bor.

---

## 3. Holatlar (states) — majburiy

Har bir ma'lumot yuklaydigan ekran **uchta** holatni qo'llashi shart:

```js
// 1) Yuklanmoqda — skeleton (bo'sh ekran emas, layout sakramaydi)
el.innerHTML = skeletonRows(3);

// 2) Bo'sh — nima qilish kerakligini aytadi
el.innerHTML = emptyState('list', 'Bu kun uchun reja yo\'q',
                          'Yuqoridagi «Reja qo\'shish» tugmasi orqali qo\'shing');

// 3) Xato — "Yana urinish" tugmasi bilan, joyida qoladi
renderError('plansList', loadPlansAPI);
```

**Xato xabarlarida texnik ma'lumot ko'rsatilmaydi.** `toast('Xato: API 500')`
foydalanuvchiga hech narsa bermaydi — o'rniga `toast('Saqlanmadi. Yana urinib
ko'ring.', true)`.

---

## 4. Komponent uslublari

| Komponent | Qoida |
|---|---|
| Segmentli boshqaruv (`.seg`, `.hseg`, `.habit-view-seg`, `.ge-tabs`) | Neytral yo'lak + ko'tarilgan `--surface` "thumb" + `--primary` matn. Gradient fonda oq matn EMAS. |
| Checkbox (`.cbx`) | To'q `--primary` fon + `icon('check')`. Aylanish/sakrash animatsiyasi yo'q. |
| Pastki navigatsiya (`.nav`) | 5 teng element. AI tugmasi ham **oddiy** element — ilgari suzib turgan katta doira kontentni to'sardi. |
| Modal (`.modal`) | Amal qatori (`.row.mt-8`) `position:sticky` — uzun formada ham "Saqlash" ko'rinib turadi. |
| Toast | Emoji prefiksi yo'q. Xato uchun `.danger` sinfi (inline style emas). |
| Statistika raqami (`.stat-card .v`) | To'q `--text` rang. Gradient bilan "kesilgan" matn EMAS. |

---

## 5. Tokenlarni o'zgartirish

Mavzu (theme) qo'shilsa, **ikki** blok kerak: yorug' va qorong'i rejim uchun.

```css
[data-theme='yangi'] {
  --primary: #…;        /* yorug' rejim: to'qroq (matn oq bo'ladi) */
  --primary-2: #…;
  --primary-soft: rgba(…, .10);
  --primary-tint: rgba(…, .16);
}

/* Qorong'i rejimda urg'u YORUG'LASHADI, matn to'q bo'ladi.
   Selektor og'irligi (0,2,0) — mavzu blokidan (0,1,0) kuchli. */
[data-mode='dark'][data-theme='yangi'] {
  --primary: #…;        /* yorug'roq variant */
  --primary-soft: rgba(…, .14);
  --primary-tint: rgba(…, .22);
  --primary-fg: #…;     /* to'q matn */
}
```

---

## 6. Kesh (cache) haqida

`app.css` / `app.js` uchun `?v=` **qo'lda yozilmaydi**. `webapp/app.py` ikkala
faylning SHA256 hash'idan `ASSET_VERSION` hisoblaydi va `index.html` ichidagi
`?v=…` ni har so'rovda almashtiradi. Ya'ni fayl o'zgarsa — clientlar avtomatik
yangi versiyani oladi.
