---
inclusion: fileMatch
fileMatchPattern: 'webapp/**'
---

# WebApp interfeysi bo'yicha qoidalar

`webapp/static/` ichidagi fayllarni (`app.css`, `app.js`, `index.html`)
o'zgartirganda quyidagi dizayn tizimiga amal qiling.

#[[file:../../webapp/DESIGN.md]]

## Qisqa eslatma (eng ko'p buziladigan qoidalar)

1. **Gradient qo'shmang.** `--grad` faqat `.hero-v2` uchun. Tugma/chip/segment —
   to'q `var(--primary)`.
2. **Cheksiz animatsiya qo'shmang.** `animation: … infinite` faqat skeleton va
   chat "yozyapti" nuqtalari uchun ruxsat etilgan.
3. **Interfeysga emoji qo'shmang.** `icon('nom', 18)` yoki
   `<svg class="ic"><use href="#i-nom"/></svg>` ishlatiladi. Emoji faqat
   foydalanuvchi tanlagan mazmun uchun (odat belgisi, rank, yutuq nishoni).
4. **Uchta holatni qo'llang**: `skeletonRows()` (yuklanmoqda), `emptyState()`
   (bo'sh), `renderError()` (xato + "Yana urinish").
5. **Xato matnida HTTP kodi bo'lmasin.** `toast('Xato: API 500')` emas —
   `toast('Saqlanmadi. Yana urinib ko'ring.', true)`.
6. **Element ID'larini o'zgartirmang** — `app.js` `getElementById` orqali
   ularga qattiq bog'langan.
7. **`?v=` ni qo'lda yangilamang** — `webapp/app.py` avtomatik hisoblaydi.
