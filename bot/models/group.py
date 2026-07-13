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
    Column, Integer, String, Boolean, DateTime, ForeignKey, UniqueConstraint,
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

    can_manage=True bo'lsa, grantee guruhda grantor uchun yangi
    reja / maqsad / odat yarata oladi.
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
    can_manage = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    group = relationship("Group", back_populates="permissions")
