import os

os.environ["JWT_SECRET_KEY"] = "test-only-secret-key-not-for-production-use"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import main as main_module
from backend.app import models  # noqa: F401
from backend.app.connection_manager import manager
from backend.app.database import Base, get_db
from backend.app.main import app


@pytest.fixture(autouse=True)
def reset_connection_manager():
    manager.active_connections.clear()
    yield
    manager.active_connections.clear()


@pytest.fixture
def client(monkeypatch):
    test_engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(test_engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autocommit=False,
        autoflush=False,
    )
    Base.metadata.create_all(bind=test_engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    # The WebSocket helpers and lifespan use these module globals directly.
    monkeypatch.setattr(main_module, "engine", test_engine)
    monkeypatch.setattr(main_module, "SessionLocal", TestingSessionLocal)
    app.dependency_overrides[get_db] = override_get_db
    try:
        # "with" runs lifespan (creates the General room) and keeps one event loop.
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.pop(get_db, None)
        test_engine.dispose()