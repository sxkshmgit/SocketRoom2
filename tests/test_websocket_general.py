from datetime import timedelta

import pytest
from sqlalchemy.exc import IntegrityError

from backend.app import crud, security
from backend.app import main as main_module
from tests.helpers import (
    assert_closed_1008,
    assert_error,
    auth_headers,
    connect_authenticated,
    register_and_login,
    wait_for_connections,
)


def get_token(client, username):
    _, token = register_and_login(client, username)
    return token


def get_history(client, token):
    response = client.get("/messages", headers=auth_headers(token))
    assert response.status_code == 200
    return response.json()


# ---------- test environment safety ----------

def test_ws_helpers_use_sqlite_and_enforce_foreign_keys(client):
    with main_module.SessionLocal() as db:
        assert db.get_bind().dialect.name == "sqlite"
        room = crud.get_default_room(db)
        assert room is not None
        with pytest.raises(IntegrityError):
            crud.create_message(db, room.id, 9999, "orphan")


# ---------- authentication ----------

def test_auth_ok_returns_identity(client):
    token = get_token(client, "alice")
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "data": {"token": token}})
        frame = ws.receive_json()
    assert frame["type"] == "auth_ok"
    assert frame["data"]["username"] == "alice"


@pytest.mark.parametrize(
    "auth_frame",
    [
        {"type": "auth", "data": {"token": "not-a-valid-token"}},
        {"type": "auth", "data": {}},
        {"type": "auth"},
        {"type": "message", "content": "hello"},
        ["not", "a", "dict"],
    ],
)
def test_bad_auth_frame_closes_with_1008(client, auth_frame):
    with client.websocket_connect("/ws") as ws:
        ws.send_json(auth_frame)
        assert_closed_1008(ws)


def test_expired_token_closes_with_1008(client):
    token = security.create_access_token(
        data={"sub": "1"}, expires_delta=timedelta(seconds=-1)
    )
    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "data": {"token": token}})
        assert_closed_1008(ws)


def test_auth_timeout_closes_with_1008(client, monkeypatch):
    monkeypatch.setattr(main_module, "AUTH_TIMEOUT_SECONDS", 0.2)
    with client.websocket_connect("/ws") as ws:
        assert_closed_1008(ws)


# ---------- messaging and persistence ----------

def test_message_is_broadcast_to_all_connected_clients(client):
    alice_token = get_token(client, "alice")
    bob_token = get_token(client, "bob")

    with connect_authenticated(client, alice_token) as alice, \
            connect_authenticated(client, bob_token) as bob:
        alice.send_json({"type": "message", "content": "  hello everyone  "})
        alice_frame = alice.receive_json()
        bob_frame = bob.receive_json()

    for frame in (alice_frame, bob_frame):
        assert frame["type"] == "message"
        assert frame["data"]["content"] == "hello everyone"
        assert frame["data"]["sender_username"] == "alice"
    assert alice_frame["data"]["id"] == bob_frame["data"]["id"]


def test_message_is_persisted_and_in_history(client):
    token = get_token(client, "alice")
    with connect_authenticated(client, token) as ws:
        ws.send_json({"type": "message", "content": "saved"})
        ws.receive_json()

    history = get_history(client, token)
    assert [m["content"] for m in history] == ["saved"]
    assert history[0]["sender_username"] == "alice"


def test_invalid_frames_return_errors_and_connection_stays_open(client):
    token = get_token(client, "alice")
    with connect_authenticated(client, token) as ws:
        ws.send_text("this is not json")
        assert_error(ws, "Invalid message format")

        ws.send_json({"type": "something-else"})
        assert_error(ws, "Unsupported message type")

        for bad_content in ("   ", "x" * 2001, None):
            ws.send_json({"type": "message", "content": bad_content})
            assert_error(ws, "Message content is invalid")

        ws.send_json({"type": "message", "content": "still works"})
        assert ws.receive_json()["data"]["content"] == "still works"

    assert [m["content"] for m in get_history(client, token)] == ["still works"]


# ---------- disconnect ----------

def test_disconnect_removes_connection_and_others_keep_working(client):
    alice_token = get_token(client, "alice")
    bob_token = get_token(client, "bob")

    with connect_authenticated(client, bob_token) as bob:
        with connect_authenticated(client, alice_token) as alice:
            alice.send_json({"type": "message", "content": "one"})
            alice.receive_json()
            bob.receive_json()
            wait_for_connections(2)

        wait_for_connections(1)
        bob.send_json({"type": "message", "content": "two"})
        assert bob.receive_json()["data"]["content"] == "two"

    wait_for_connections(0)