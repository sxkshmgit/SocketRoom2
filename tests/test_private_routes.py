import pytest

from backend.app import crud
from backend.app import main as main_module
from tests.helpers import auth_headers, register_and_login


def user_with_headers(client, username):
    """Return (user_id, auth headers) for a new user."""
    user_id, token = register_and_login(client, username)
    return user_id, auth_headers(token)


@pytest.fixture
def alice(client):
    return user_with_headers(client, "alice")


@pytest.fixture
def bob(client):
    return user_with_headers(client, "bob")


@pytest.fixture
def carol(client):
    return user_with_headers(client, "carol")


def start_conversation(client, headers, other_user_id):
    return client.post("/conversations", json={"user_id": other_user_id}, headers=headers)


def add_private_message(conversation_id, sender_id, content):
    # These tests are about the HTTP routes, so write messages directly
    # through CRUD. The client fixture points SessionLocal at the test database.
    with main_module.SessionLocal() as db:
        return crud.create_private_message(db, conversation_id, sender_id, content).id


# ---------- authentication ----------

@pytest.mark.parametrize(
    "method, path",
    [
        ("post", "/conversations"),
        ("get", "/conversations"),
        ("get", "/conversations/1/messages"),
    ],
)
def test_conversation_routes_require_authentication(client, method, path):
    kwargs = {"json": {"user_id": 1}} if method == "post" else {}

    response = getattr(client, method)(path, **kwargs)

    assert response.status_code == 401


# ---------- POST /conversations ----------

def test_start_conversation_returns_other_user(client, alice, bob):
    alice_id, alice_headers = alice
    bob_id, _ = bob

    response = start_conversation(client, alice_headers, bob_id)

    assert response.status_code == 200
    data = response.json()
    assert data["other_user_id"] == bob_id
    assert data["other_username"] == "bob"
    assert data["last_message_at"] is None
    assert isinstance(data["id"], int)


def test_both_users_get_the_same_conversation(client, alice, bob):
    alice_id, alice_headers = alice
    bob_id, bob_headers = bob

    from_alice = start_conversation(client, alice_headers, bob_id).json()
    from_bob = start_conversation(client, bob_headers, alice_id).json()
    again = start_conversation(client, alice_headers, bob_id).json()

    assert from_alice["id"] == from_bob["id"] == again["id"]
    assert from_bob["other_username"] == "alice"


def test_start_existing_conversation_reports_last_message_time(client, alice, bob):
    alice_id, alice_headers = alice
    bob_id, _ = bob
    conversation_id = start_conversation(client, alice_headers, bob_id).json()["id"]
    add_private_message(conversation_id, alice_id, "hello")

    data = start_conversation(client, alice_headers, bob_id).json()

    assert data["last_message_at"] is not None


def test_cannot_start_conversation_with_yourself(client, alice):
    alice_id, alice_headers = alice

    response = start_conversation(client, alice_headers, alice_id)

    assert response.status_code == 400


def test_cannot_start_conversation_with_unknown_user(client, alice):
    _, alice_headers = alice

    response = start_conversation(client, alice_headers, 9999)

    assert response.status_code == 404


def test_start_conversation_rejects_invalid_body(client, alice):
    _, alice_headers = alice

    response = client.post(
        "/conversations", json={"user_id": "bob"}, headers=alice_headers
    )

    assert response.status_code == 422


# ---------- GET /conversations ----------

def test_list_conversations_shows_only_own_with_messages_newest_first(
    client, alice, bob, carol
):
    alice_id, alice_headers = alice
    bob_id, bob_headers = bob
    carol_id, _ = carol

    with_bob = start_conversation(client, alice_headers, bob_id).json()["id"]
    with_carol = start_conversation(client, alice_headers, carol_id).json()["id"]
    bob_carol = start_conversation(client, bob_headers, carol_id).json()["id"]
    add_private_message(with_bob, alice_id, "hi bob")
    add_private_message(bob_carol, bob_id, "not for alice")
    add_private_message(with_carol, carol_id, "hi alice")

    response = client.get("/conversations", headers=alice_headers)

    assert response.status_code == 200
    data = response.json()
    assert [c["id"] for c in data] == [with_carol, with_bob]
    assert [c["other_username"] for c in data] == ["carol", "bob"]
    assert all(c["last_message_at"] is not None for c in data)


def test_list_conversations_is_empty_without_messages(client, alice, bob):
    _, alice_headers = alice
    bob_id, _ = bob
    start_conversation(client, alice_headers, bob_id)

    response = client.get("/conversations", headers=alice_headers)

    assert response.status_code == 200
    assert response.json() == []


# ---------- GET /conversations/{id}/messages ----------

def test_participants_can_read_history_oldest_first(client, alice, bob):
    alice_id, alice_headers = alice
    bob_id, bob_headers = bob
    conversation_id = start_conversation(client, alice_headers, bob_id).json()["id"]
    add_private_message(conversation_id, alice_id, "first")
    add_private_message(conversation_id, bob_id, "second")

    for headers in (alice_headers, bob_headers):
        response = client.get(
            f"/conversations/{conversation_id}/messages", headers=headers
        )
        assert response.status_code == 200
        data = response.json()
        assert [m["content"] for m in data] == ["first", "second"]
        assert [m["sender_username"] for m in data] == ["alice", "bob"]
        assert data[0]["conversation_id"] == conversation_id
        assert set(data[0]) == {
            "id",
            "conversation_id",
            "sender_id",
            "sender_username",
            "content",
            "created_at",
        }


def test_history_respects_limit(client, alice, bob):
    alice_id, alice_headers = alice
    bob_id, _ = bob
    conversation_id = start_conversation(client, alice_headers, bob_id).json()["id"]
    for index in range(3):
        add_private_message(conversation_id, alice_id, f"message {index}")

    response = client.get(
        f"/conversations/{conversation_id}/messages?limit=2", headers=alice_headers
    )

    assert [m["content"] for m in response.json()] == ["message 1", "message 2"]


@pytest.mark.parametrize("limit", [0, 101])
def test_history_rejects_out_of_range_limit(client, alice, bob, limit):
    _, alice_headers = alice
    bob_id, _ = bob
    conversation_id = start_conversation(client, alice_headers, bob_id).json()["id"]

    response = client.get(
        f"/conversations/{conversation_id}/messages?limit={limit}",
        headers=alice_headers,
    )

    assert response.status_code == 422


def test_non_participant_gets_404_for_history(client, alice, bob, carol):
    alice_id, alice_headers = alice
    bob_id, _ = bob
    _, carol_headers = carol
    conversation_id = start_conversation(client, alice_headers, bob_id).json()["id"]
    add_private_message(conversation_id, alice_id, "secret")

    response = client.get(
        f"/conversations/{conversation_id}/messages", headers=carol_headers
    )

    assert response.status_code == 404
    assert "secret" not in response.text


def test_unknown_conversation_gets_404(client, alice):
    _, alice_headers = alice

    response = client.get("/conversations/9999/messages", headers=alice_headers)

    assert response.status_code == 404


# ---------- General chat is unaffected ----------

def test_private_messages_do_not_appear_in_general_history(client, alice, bob):
    alice_id, alice_headers = alice
    bob_id, _ = bob
    conversation_id = start_conversation(client, alice_headers, bob_id).json()["id"]
    add_private_message(conversation_id, alice_id, "private")

    response = client.get("/messages", headers=alice_headers)

    assert response.status_code == 200
    assert response.json() == []
