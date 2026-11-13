from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.app.models import (
    ChatRoom,
    Conversation,
    Message,
    PrivateMessage,
    User,
)

DEFAULT_ROOM_NAME = "General"


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalars(select(User).where(User.id == user_id)).first()

def get_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())

def get_user_by_username(db: Session, username: str) -> User | None:
    # Case-insensitive, so "Alice" finds "alice".
    return db.scalars(
        select(User).where(func.lower(User.username) == username.lower())
    ).first()

def create_user(db: Session, username: str, password_hash: str) -> User:
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

def ensure_default_room(db: Session) -> ChatRoom:
    room = db.scalars(
        select(ChatRoom).where(ChatRoom.name == DEFAULT_ROOM_NAME)
    ).first()
    if room is not None:
        return room

    room = ChatRoom(name=DEFAULT_ROOM_NAME)
    db.add(room)
    db.commit()
    db.refresh(room)
    return room

def get_default_room(db: Session) -> ChatRoom | None:
    return db.scalars(
        select(ChatRoom).where(ChatRoom.name == DEFAULT_ROOM_NAME)
    ).first()


def create_message(
    db: Session, room_id: int, sender_id: int, content: str
) -> Message:
    message = Message(room_id=room_id, sender_id=sender_id, content=content)
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_recent_messages(db: Session, room_id: int, limit: int = 50) -> list[Message]:
    newest_first = db.scalars(
        select(Message)
        .where(Message.room_id == room_id)
        .order_by(Message.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(newest_first))

def _ordered_pair(user_a_id: int, user_b_id: int) -> tuple[int, int]:
    return (user_a_id, user_b_id) if user_a_id < user_b_id else (user_b_id, user_a_id)


def get_conversation_between_users(
    db: Session, user_a_id: int, user_b_id: int
) -> Conversation | None:
    if user_a_id == user_b_id:
        return None
    low_id, high_id = _ordered_pair(user_a_id, user_b_id)
    return db.scalars(
        select(Conversation).where(
            Conversation.user_low_id == low_id,
            Conversation.user_high_id == high_id,
        )
    ).first()


def get_or_create_conversation(
    db: Session, user_id: int, other_user_id: int
) -> Conversation:
    # Callers should map ValueError to a 400 response.
    if user_id == other_user_id:
        raise ValueError("Cannot create a conversation with yourself")

    conversation = get_conversation_between_users(db, user_id, other_user_id)
    if conversation is not None:
        return conversation

    low_id, high_id = _ordered_pair(user_id, other_user_id)
    conversation = Conversation(user_low_id=low_id, user_high_id=high_id)
    db.add(conversation)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        # Either another request created the same pair first (re-query finds it),
        # or a foreign key failed (e.g. unknown user): then re-raise the error.
        conversation = get_conversation_between_users(db, user_id, other_user_id)
        if conversation is None:
            raise
        return conversation

    db.refresh(conversation)
    return conversation


def get_conversation_for_user(
    db: Session, conversation_id: int, user_id: int
) -> Conversation | None:
    return db.scalars(
        select(Conversation).where(
            Conversation.id == conversation_id,
            or_(
                Conversation.user_low_id == user_id,
                Conversation.user_high_id == user_id,
            ),
        )
    ).first()


def create_private_message(
    db: Session, conversation_id: int, sender_id: int, content: str
) -> PrivateMessage:
    # The caller must already have verified that sender_id is a participant
    # (see get_conversation_for_user).
    message = PrivateMessage(
        conversation_id=conversation_id, sender_id=sender_id, content=content
    )
    db.add(message)
    db.commit()
    db.refresh(message)
    return message


def get_recent_private_messages(
    db: Session, conversation_id: int, limit: int = 50
) -> list[PrivateMessage]:
    newest_first = db.scalars(
        select(PrivateMessage)
        .where(PrivateMessage.conversation_id == conversation_id)
        .order_by(PrivateMessage.id.desc())
        .limit(limit)
    ).all()
    return list(reversed(newest_first))


def list_conversations_for_user(
    db: Session, user_id: int
) -> list[tuple[Conversation, datetime]]:
    # Only conversations that contain at least one message, newest activity first.
    my_conversation_ids = select(Conversation.id).where(
        or_(
            Conversation.user_low_id == user_id,
            Conversation.user_high_id == user_id,
        )
    )
    last_activity = (
        select(
            PrivateMessage.conversation_id.label("conversation_id"),
            func.max(PrivateMessage.id).label("last_message_id"),
            func.max(PrivateMessage.created_at).label("last_message_at"),
        )
        .where(PrivateMessage.conversation_id.in_(my_conversation_ids))
        .group_by(PrivateMessage.conversation_id)
        .subquery()
    )
    rows = db.execute(
        select(Conversation, last_activity.c.last_message_at)
        .join(last_activity, last_activity.c.conversation_id == Conversation.id)
        .order_by(last_activity.c.last_message_id.desc())
    ).all()
    return [(row[0], row[1]) for row in rows]