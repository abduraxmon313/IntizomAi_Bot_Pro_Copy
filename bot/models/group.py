"""
Do'stlar / Guruhlar (Groups) — jamoaviy intizom moduli.

Uch obyekt:

  • Group           — bir jamoa (masalan "IntizomAI jamoasi", "Oila", "Talabalar").
                       Bitta foydalanuvchi bir necha guruhda bo'lishi mumkin.
  • GroupMember     — guruh a'zosi (roli: owner / admin / member).
  • GroupPermission — a'zolar orasidagi ruxsat: "Men sizga mening reja/maqsad/
                       odatlarimni yaratishga ruxsat beraman". Bir guruh ichidagi
                       (grantor, grantee) juftligi uchun bitta yozuv.

Guruhga qo'shilish taklif kodi orqali (invite_code) — deep-link
`https://t.me/<bot>?start=grp_<code>` yuboriladi, bot /start payload'ini o'qib
foydalanuvchini guruhga qo'shadi.
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, ForeignKey, Integer, String,
    UniqueConstraint,
)
from sqlalchemy.orm import relationship
from datetime import datetime

from database.db import Base


class Group(Base):
    __tablename__ = "groups"

    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(80), nullable=False)
    description = Column(String(300), nullable=True)
    # Yaratgan foydalanuvchi (users.id). Guruh o'chirilsa a'zolar bilan birga ketadi.
    owner_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # Taklif kodi — qisqa noyob token (masalan 10 belgi).
    # Deep-link: https://t.me/<bot>?start=grp_<invite_code>
    invite_code = Column(String(16), unique=True, nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # ── Telegram digest/plans bog'lanishi (owner konfiguratsiyalaydi) ──
    # Guruh statistikasi (reja + odat) shu Telegram chatga har kuni yuboriladi.
    # Bog'lanmagan bo'lsa telegram_chat_id = NULL va digest_enabled = FALSE.
    telegram_chat_id = Column(BigInteger, nullable=True, index=True)
    telegram_chat_title = Column(String(200), nullable=True)
    # ── Kunlik HISOBOT (report) sozlamalari ──
    # Belgilangan vaqtda har bir a'zoning bugungi natijasi (ishlar bajarilgan/
    # bajarilmagan) alohida xabar bo'lib yuboriladi (per-user).
    digest_enabled = Column(Boolean, default=False, nullable=False)
    digest_time = Column(String(5), default="21:00", nullable=False)
    # Eski toggle'lar (digest_show_zero, digest_mention) endi doim TRUE deb
    # hisoblanadi (UI'dan olib tashlangan). DB'da saqlanadi backward compat uchun.
    digest_show_zero = Column(Boolean, default=True, nullable=False)
    digest_mention = Column(Boolean, default=True, nullable=False)
    digest_last_sent_at = Column(DateTime, nullable=True)
    digest_last_error = Column(String(300), nullable=True)
    # ── Kunlik REJA (plans) sozlamalari ──
    # Belgilangan vaqtda har bir a'zoning bugungi reja+odatlar ro'yxati
    # (nima qilishi kerak) alohida xabar bo'lib yuboriladi (per-user).
    plans_enabled = Column(Boolean, default=False, nullable=False)
    plans_time = Column(String(5), default="07:00", nullable=False)
    plans_last_sent_at = Column(DateTime, nullable=True)
    plans_last_error = Column(String(300), nullable=True)

    members = relationship(
        "GroupMember", back_populates="group", cascade="all, delete-orphan",
    )
    permissions = relationship(
        "GroupPermission", back_populates="group", cascade="all, delete-orphan",
    )


class GroupMember(Base):
    __tablename__ = "group_members"
    __table_args__ = (
        UniqueConstraint("group_id", "user_id", name="uq_group_member"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    # 'owner' | 'admin' | 'member'
    # `owner` faqat guruh yaratuvchisi; `admin` — kelajakda taklif/o'chirish uchun.
    # Hozircha faqat `owner` va `member` ishlatiladi.
    role = Column(String(12), default="member", nullable=False)
    joined_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="members")


class GroupPermission(Base):
    """
    Bir guruh ichidagi ikki foydalanuvchi orasidagi ruxsat.
      grantor  = "Men" (kimning ma'lumotlari ustida ishlash mumkin)
      grantee  = "Boshqa odam" (menim ma'lumotlarim ustida ishlashga ruxsat berilgan)

    Ikki mustaqil huquq:
      • `can_view`   — grantee grantor'ning reja / odat / maqsadlarini KO'RA oladi.
      • `can_manage` — grantee grantor uchun yangi reja / maqsad / odat YARATA oladi
                       (bu avtomatik ko'rish huquqini ham beradi: yaratgan
                       nimasini yaratayotganini bilmasa mantiqsiz).

    Effective ko'rinish: `can_view OR can_manage`. Default (yozuv yo'q): hech
    kim boshqaning ma'lumotini ko'rmaydi.
    """
    __tablename__ = "group_permissions"
    __table_args__ = (
        UniqueConstraint(
            "group_id", "grantor_user_id", "grantee_user_id",
            name="uq_group_permission_pair",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    group_id = Column(
        Integer, ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    grantor_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    grantee_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True,
    )
    can_manage = Column(Boolean, default=False, nullable=False)
    # `can_view` — grantee grantor'ning ma'lumotlarini ko'ra oladi.
    # Effective ko'rinish `can_view OR can_manage`.
    can_view = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="permissions")
