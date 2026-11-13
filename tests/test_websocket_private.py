import pytest
from sqlalchemy.exc import SQLAlchemyError

from backend.app import crud
from backend.app.connection_manager import manager
from tests.helpers import (
    assert_error,
    auth_headers,
    connect_authenticated,
    register_and_login,
    wait_for_connections,
)


def send_private(ws, conversation_id, content):
    ws.send_json(
        {"type": "private_message", "conversation_id": conversation_id, "content": content}
    )


def private_history(client, token, conversation_id):
    response = client.get(
        f"/conversations/{conversation_id}/messages", headers=auth_headers(token)
    )
    assert response.status_code == 200
    return response.json()


@pytest.fixture
def users(client):
    return {name: register_and_login(client, name) for name in ("alice", "bob", "carol")}


@pytest.fixture
def conversation_id(client, users):
    _, alice_token = users["alice"]
    bob_id, _ = users["bob"]
    response = client.post(
        "/conversations", json={"user_id": bob_id}, headers=auth_headers(alice_token)
    )
    return response.json()["id"]


# ---------- delivery ----------

def test_private_message_reaches_both_participants_only(client, users, conversation_id):
    alice_id, alice_token = users["alice"]
    _, bob_token = users["bob"]
    _, carol_token = users["carol"]

    with connect_authenticated(client, alice_token) as alice, \
            connect_authenticated(client, bob_token) as bob, \
            connect_authenticated(client, carol_token) as carol:
        send_private(alice, conversation_id, "  hi bob  ")
        alice_frame = alice.receive_json()
        bob_frame = bob.receive_json()

        # A General message sent afterwards must be carol's *first* frame,
        # which proves she never received the private one.
        alice.send_json({"type": "message", "content": "hello everyone"})
        carol_frame = carol.receive_json()
        alice.receive_json()
        bob.receive_json()

    for frame in (alice_frame, bob_frame):
        assert frame["type"] == "private_message"
        assert frame["data"]["conversation_id"] == conversation_id
        assert frame["data"]["sender_id"] == alice_id
        assert frame["data"]["sender_username"] == "alice"
        assert frame["data"]["content"] == "hi bob"
    assert alice_frame["data"]["id"] == bob_frame["data"]["id"]

    assert carol_frame["type"] == "message"
    assert carol_frame["data"]["content"] == "hello everyone"


def test_private_message_reaches_every_tab_of_both_users(client, users, conversation_id):
    _, alice_token = users["alice"]
    _, bob_token = users["bob"]

    with connect_authenticated(client, alice_token) as alice_tab1, \
            connect_authenticated(client, alice_token) as alice_tab2, \
            connect_authenticated(client, bob_token) as bob:
        send_private(bob, conversation_id, "reply")
        frames = [ws.receive_json() for ws in (alice_tab1, alice_tab2, bob)]

    assert all(f["type"] == "private_message" for f in frames)
    assert {f["data"]["content"] for f in frames} == {"reply"}


def test_private_message_is_saved_for_offline_recipient(client, users, conversation_id):
    _, alice_token = users["alice"]
    _, bob_token = users["bob"]

    with connect_authenticated(client, alice_token) as alice:
        send_private(alice, conversation_id, "while you were away")
        alice.receive_json()

    history = private_history(client, bob_token, conversation_id)
    assert [m["content"] for m in history] == ["while you were away"]

    conversations = client.get("/conversations", headers=auth_headers(bob_token)).json()
    assert [c["id"] for c in conversations] == [conversation_id]
    assert conversations[0]["other_username"] == "alice"


def test_private_message_is_not_in_general_history(client, users, conversation_id):
    _, alice_token = users["alice"]

    with connect_authenticated(client, alice_token) as alice:
        send_private(alice, conversation_id, "private")
        alice.receive_json()

    response = client.get("/messages", headers=auth_headers(alice_token))
    assert response.json() == []


# ---------- authorization and validation ----------

def test_non_participant_cannot_send(client, users, conversation_id):
    _, alice_token = users["alice"]
    _, carol_token = users["carol"]

    with connect_authenticated(client, carol_token) as carol:
        send_private(carol, conversation_id, "intruding")
        assert_error(carol, "Conversation not found")

    assert private_history(client, alice_token, conversation_id) == []


@pytest.mark.parametrize("bad_id", [None, "1", True, 1.0, 9999])
def test_invalid_conversation_id_is_rejected(client, users, conversation_id, bad_id):
    _, alice_token = users["alice"]

    with connect_authenticated(client, alice_token) as alice:
        frame = {"type": "private_message", "content": "hello"}
        if bad_id is not None:
            frame["conversation_id"] = bad_id
        alice.send_json(frame)
        assert_error(alice, "Conversation not found")

    assert private_history(client, alice_token, conversation_id) == []


def test_errors_keep_connection_open(client, users, conversation_id):
    _, alice_token = users["alice"]

    with connect_authenticated(client, alice_token) as alice:
        for bad_content in ("   ", "x" * 2001, None):
            send_private(alice, conversation_id, bad_content)
            assert_error(alice, "Message content is invalid")

        send_private(alice, 9999, "nowhere")
        assert_error(alice, "Conversation not found")

        send_private(alice, conversation_id, "still works")
        assert alice.receive_json()["data"]["content"] == "still works"

    history = private_history(client, alice_token, conversation_id)
    assert [m["content"] for m in history] == ["still works"]


def test_save_failure_returns_error(client, users, conversation_id, monkeypatch):
    _, alice_token = users["alice"]

    def failing_create(*args, **kwargs):
        raise SQLAlchemyError("database unavailable")

    monkeypatch.setattr(crud, "create_private_message", failing_create)

    with connect_authenticated(client, alice_token) as alice:
        send_private(alice, conversation_id, "lost")
        assert_error(alice, "Message could not be saved")


# ---------- connection manager ----------

def test_manager_tracks_user_for_each_socket(client, users):
    alice_id, alice_token = users["alice"]
    bob_id, bob_token = users["bob"]

    with connect_authenticated(client, alice_token), \
            connect_authenticated(client, bob_token):
        wait_for_connections(2)
        assert sorted(manager.active_connections.values()) == sorted([alice_id, bob_id])

    wait_for_connections(0)
