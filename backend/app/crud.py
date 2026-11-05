from sqlalchemy import func, select
from sqlalchemy.orm import Session

from backend.app.models import ChatRoom, Message , User

DEFAULT_ROOM_NAME = "General"


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalars(select(User).where(User.id == user_id)).first()

def get_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())

def get_user_by_username(db: Session, username: str) -> User | None:
    # Exact match first, so legacy mixed-case accounts always resolve to themselves.
    user = db.scalars(select(User).where(User.username == username)).first()
    if user is not None:
        return user
    # Fallback: case-insensitive match (e.g. "Alice" finds "alice").
    return db.scalars(
        select(User).where(func.lower(User.username) == username.lower())
    ).first()

def create_user(db: Session, username: str, password_hash: str) -> User:
    user = User(username=username, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def update_username(db: Session, user_id: int, new_username: str) -> User | None:
    user = get_user_by_id(db, user_id)
    if user is None:
        return None
    user.username = new_username
    db.commit()
    db.refresh(user)
    return user


def delete_user(db: Session, user_id: int) -> bool:
    user = get_user_by_id(db, user_id)
    if user is None:
        return False
    db.delete(user)
    db.commit()
    return True

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