import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from backend.app import crud
from backend.app.database import Base
from backend.app.models import Conversation, PrivateMessage


@pytest.fixture
def db():
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

    Base.metadata.create_all(bind=test_engine)
    TestingSessionLocal = sessionmaker(
        bind=test_engine,
        autocommit=False,
        autoflush=False,
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        test_engine.dispose()


@pytest.fixture
def users(db):
    # The password hash is irrelevant here, so skip the slow Argon2 call.
    return [
        crud.create_user(db, name, "not-a-real-hash")
        for name in ("alice", "bob", "carol")
    ]


def count_conversations(db):
    return db.scalar(select(func.count()).select_from(Conversation))


def test_same_conversation_regardless_of_who_starts_it(db, users):
    alice, bob, _ = users

    first = crud.get_or_create_conversation(db, bob.id, alice.id)
    second = crud.get_or_create_conversation(db, alice.id, bob.id)

    assert first.id == second.id
    assert (first.user_low_id, first.user_high_id) == (alice.id, bob.id)
    assert count_conversations(db) == 1


def test_conversation_with_yourself_is_rejected(db, users):
    alice = users[0]

    with pytest.raises(ValueError):
        crud.get_or_create_conversation(db, alice.id, alice.id)

    assert crud.get_conversation_between_users(db, alice.id, alice.id) is None
    assert count_conversations(db) == 0


def test_conversation_with_unknown_user_raises_integrity_error(db, users):
    alice = users[0]

    with pytest.raises(IntegrityError):
        crud.get_or_create_conversation(db, alice.id, 9999)

    assert count_conversations(db) == 0


def test_concurrent_create_returns_existing_conversation(db, users, monkeypatch):
    alice, bob, _ = users
    existing = crud.get_or_create_conversation(db, alice.id, bob.id)

    # Simulate another request creating the pair between our lookup and insert:
    # the first lookup misses, the insert hits the unique constraint, and the
    # function must recover by re-querying.
    real_lookup = crud.get_conversation_between_users
    calls = []

    def lookup_missing_first_time(session, user_a_id, user_b_id):
        calls.append((user_a_id, user_b_id))
        if len(calls) == 1:
            return None
        return real_lookup(session, user_a_id, user_b_id)

    monkeypatch.setattr(
        crud, "get_conversation_between_users", lookup_missing_first_time
    )

    result = crud.get_or_create_conversation(db, bob.id, alice.id)

    assert len(calls) == 2
    assert result.id == existing.id
    assert count_conversations(db) == 1


def test_database_rejects_duplicate_or_unordered_pairs(db, users):
    alice, bob, _ = users
    crud.get_or_create_conversation(db, alice.id, bob.id)

    db.add(Conversation(user_low_id=alice.id, user_high_id=bob.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    db.add(Conversation(user_low_id=bob.id, user_high_id=alice.id))
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    assert count_conversations(db) == 1


def test_get_conversation_for_user_only_returns_participants(db, users):
    alice, bob, carol = users
    conversation = crud.get_or_create_conversation(db, alice.id, bob.id)

    assert crud.get_conversation_for_user(db, conversation.id, alice.id).id == conversation.id
    assert crud.get_conversation_for_user(db, conversation.id, bob.id).id == conversation.id
    assert crud.get_conversation_for_user(db, conversation.id, carol.id) is None
    assert crud.get_conversation_for_user(db, 9999, alice.id) is None


def test_private_message_history_is_oldest_first_and_limited(db, users):
    alice, bob, _ = users
    conversation = crud.get_or_create_conversation(db, alice.id, bob.id)
    for index in range(5):
        sender = alice if index % 2 == 0 else bob
        crud.create_private_message(db, conversation.id, sender.id, f"message {index}")

    history = crud.get_recent_private_messages(db, conversation.id)
    assert [m.content for m in history] == [f"message {i}" for i in range(5)]
    assert [m.sender_username for m in history] == ["alice", "bob", "alice", "bob", "alice"]

    newest_three = crud.get_recent_private_messages(db, conversation.id, limit=3)
    assert [m.content for m in newest_three] == ["message 2", "message 3", "message 4"]


def test_private_message_history_is_isolated_per_conversation(db, users):
    alice, bob, carol = users
    alice_bob = crud.get_or_create_conversation(db, alice.id, bob.id)
    alice_carol = crud.get_or_create_conversation(db, alice.id, carol.id)
    crud.create_private_message(db, alice_bob.id, alice.id, "to bob")
    crud.create_private_message(db, alice_carol.id, alice.id, "to carol")

    assert [m.content for m in crud.get_recent_private_messages(db, alice_bob.id)] == ["to bob"]
    assert [m.content for m in crud.get_recent_private_messages(db, alice_carol.id)] == ["to carol"]


def test_private_message_requires_existing_conversation(db, users):
    alice = users[0]

    with pytest.raises(IntegrityError):
        crud.create_private_message(db, 9999, alice.id, "orphan")
    db.rollback()

    assert db.scalar(select(func.count()).select_from(PrivateMessage)) == 0


def test_list_conversations_newest_activity_first_and_skips_empty(db, users):
    alice, bob, carol = users
    alice_bob = crud.get_or_create_conversation(db, alice.id, bob.id)
    alice_carol = crud.get_or_create_conversation(db, alice.id, carol.id)
    bob_carol = crud.get_or_create_conversation(db, bob.id, carol.id)

    crud.create_private_message(db, alice_bob.id, alice.id, "first")
    crud.create_private_message(db, bob_carol.id, bob.id, "not alice's")
    latest = crud.create_private_message(db, alice_carol.id, carol.id, "newest")

    alice_list = crud.list_conversations_for_user(db, alice.id)
    assert [conversation.id for conversation, _ in alice_list] == [
        alice_carol.id,
        alice_bob.id,
    ]
    assert alice_list[0][1] == latest.created_at

    # Activity in an older conversation moves it back to the top.
    crud.create_private_message(db, alice_bob.id, bob.id, "reply")
    assert [c.id for c, _ in crud.list_conversations_for_user(db, alice.id)] == [
        alice_bob.id,
        alice_carol.id,
    ]


def test_list_conversations_excludes_conversations_without_messages(db, users):
    alice, bob, _ = users
    crud.get_or_create_conversation(db, alice.id, bob.id)

    assert crud.list_conversations_for_user(db, alice.id) == []
    assert crud.list_conversations_for_user(db, bob.id) == []
