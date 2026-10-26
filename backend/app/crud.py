from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.models import User


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.scalars(select(User).where(User.id == user_id)).first()


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