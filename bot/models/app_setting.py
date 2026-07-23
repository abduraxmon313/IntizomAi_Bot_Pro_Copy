"""
Global sozlamalar (feature flags) — key/value do'koni.

Bu jadval kam sonli global bayroqlarni (admin panelidan yoqilib/o'chiriladigan
xususiyatlar) saqlaydi. Har bir yozuv oddiy `key` (birlamchi kalit) va uning
matnli `value` juftligi. Aslida bool bo'lgan flaglar "0"/"1" yoki "true"/"false"
ko'rinishida saqlanadi.

Nima uchun alohida jadval:
  • Admin panelidan yoqilib/o'chiriladigan konfiguratsiya kod deploy'iga bog'liq
    bo'lmasligi kerak (env override qilib bo'lmaydi).
  • `admins` yoki `users` jadvaliga singleton ustun qo'shish esa yopishqoq
    bog'lanishga olib keladi (bu ma'lumot foydalanuvchiga aloqador emas).

Birinchi flaglar:
  • `group_perms_menu_enabled` — Do'stlar/guruhlar sahifasidagi "🛡 Ruxsatlar"
    tugmasi ko'rinishini boshqaradi. TRUE (default) — foydalanuvchilar
    ruxsatlarni o'zi boshqaradi (default yashirin). FALSE — tugma yashiriladi
    va ruxsat qulflari o'chadi: guruhdagi barcha a'zolar bir-birining reja va
    odatlarini avtomatik ko'radi.
"""
from datetime import datetime

from sqlalchemy import Column, DateTime, String, Text

from database.db import Base


class AppSetting(Base):
    __tablename__ = "app_settings"

    key = Column(String(64), primary_key=True)
    value = Column(Text, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
