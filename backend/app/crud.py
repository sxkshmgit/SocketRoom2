from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import ChatRoom, User

DEFAULT_ROOM_NAME = "General"


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalars(select(User).where(User.id == user_id)).first()

def get_users(db: Session) -> list[User]:
    return list(db.scalars(select(User).order_by(User.id)).all())

def get_user_by_username(db: Session, username: str) -> User | None:
    return db.scalars(select(User).where(User.username == username)).first()


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