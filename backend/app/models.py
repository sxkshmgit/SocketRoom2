from datetime import datetime, timezone

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    String,
    Unicode,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.database import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(
        Unicode(50), unique=True, index=True, nullable=False
    )
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

class ChatRoom(Base):
    __tablename__ = "chat_rooms"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(
        Unicode(100), unique=True, index=True, nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    room_id: Mapped[int] = mapped_column(
        ForeignKey("chat_rooms.id"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    sender: Mapped[User] = relationship(lazy="joined")

    @property
    def sender_username(self) -> str:
        return self.sender.username

class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "user_low_id", "user_high_id", name="uq_conversations_pair"
        ),
        CheckConstraint(
            "user_low_id < user_high_id", name="ck_conversations_order"
        ),
        Index("ix_conversations_user_high_id", "user_high_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_low_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    user_high_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    user_low: Mapped[User] = relationship(foreign_keys=[user_low_id], lazy="joined")
    user_high: Mapped[User] = relationship(foreign_keys=[user_high_id], lazy="joined")

    def other_user(self, user_id: int) -> User:
        return self.user_high if user_id == self.user_low_id else self.user_low


class PrivateMessage(Base):
    __tablename__ = "private_messages"
    __table_args__ = (
        Index("ix_private_messages_conversation_id_id", "conversation_id", "id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("conversations.id"), nullable=False
    )
    sender_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False
    )
    content: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )

    sender: Mapped[User] = relationship(lazy="joined")

    @property
    def sender_username(self) -> str:
        return self.sender.username