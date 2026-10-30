import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import main as main_module
from backend.app.models import ChatRoom


@pytest.fixture
def lifespan_session_factory(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autocommit=False,
        autoflush=False,
    )

    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)

    try:
        yield TestingSessionLocal
    finally:
        test_engine.dispose()


def get_all_rooms(session_factory):
    with session_factory() as db:
        return db.scalars(select(ChatRoom).order_by(ChatRoom.id)).all()


def test_general_room_created_on_startup(lifespan_session_factory):
    with TestClient(main_module.app):
        pass

    rooms = get_all_rooms(lifespan_session_factory)

    assert len(rooms) == 1
    assert rooms[0].name == "General"


def test_second_startup_does_not_duplicate_general_room(lifespan_session_factory):
    with TestClient(main_module.app):
        pass
    first_rooms = get_all_rooms(lifespan_session_factory)

    with TestClient(main_module.app):
        pass
    second_rooms = get_all_rooms(lifespan_session_factory)

    assert len(first_rooms) == 1
    assert len(second_rooms) == 1
    assert second_rooms[0].id == first_rooms[0].id
    assert second_rooms[0].name == "General"