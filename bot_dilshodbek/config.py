"""
Dilshodbek bot konfiguratsiyasi.

Token va admin sozlamalari asosiy loyiha config'idan olinadi — shu tariqa
ma'lumotlar bazasi, admin ro'yxati va ADMIN_ID ikkala bot uchun ham YAGONA
bo'ladi (userlar bazasi umumiy).
"""
from bot.config import DILSHODBEK_BOT_TOKEN, ADMIN_ID  # noqa: F401

__all__ = ["DILSHODBEK_BOT_TOKEN", "ADMIN_ID"]
