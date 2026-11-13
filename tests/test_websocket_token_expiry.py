import time
from datetime import datetime, timedelta, timezone

import jwt
import pytest
from starlette.websockets import WebSocketDisconnect

from backend.app import security
from backend.app.connection_manager import manager


def register(client, username):
    response = client.post(
        "/users", json={"username": username, "password": f"{username}-password"}
    )
    return response.json()["id"]


def short_lived_token(user_id, seconds):
    return security.create_access_token(
        data={"sub": str(user_id)}, expires_delta=timedelta(seconds=seconds)
    )


def assert_closed_1008(ws):
    with pytest.raises(WebSocketDisconnect) as exc_info:
        ws.receive_json()
    assert exc_info.value.code == 1008


def wait_for_no_connections(timeout=2.0):
    deadline = time.monotonic() + timeout
    while manager.active_connections and time.monotonic() < deadline:
        time.sleep(0.01)
    assert manager.active_connections == {}


def test_connection_works_until_token_expires_then_closes_with_1008(client):
    user_id = register(client, "alice")
    token = short_lived_token(user_id, seconds=2)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "data": {"token": token}})
        assert ws.receive_json()["type"] == "auth_ok"

        ws.send_json({"type": "message", "content": "before expiry"})
        assert ws.receive_json()["data"]["content"] == "before expiry"

        started = time.monotonic()
        assert_closed_1008(ws)
        # JWT expiry has one-second resolution, so allow for rounding.
        assert time.monotonic() - started < 3.5

    wait_for_no_connections()


def test_idle_connection_is_closed_at_expiry(client):
    user_id = register(client, "alice")
    token = short_lived_token(user_id, seconds=1)

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "data": {"token": token}})
        assert ws.receive_json()["type"] == "auth_ok"
        assert_closed_1008(ws)

    wait_for_no_connections()


def test_expiry_of_one_connection_does_not_affect_others(client):
    alice_id = register(client, "alice")
    bob_id = register(client, "bob")
    alice_token = short_lived_token(alice_id, seconds=1)
    bob_token = short_lived_token(bob_id, seconds=60)

    with client.websocket_connect("/ws") as bob:
        bob.send_json({"type": "auth", "data": {"token": bob_token}})
        assert bob.receive_json()["type"] == "auth_ok"

        with client.websocket_connect("/ws") as alice:
            alice.send_json({"type": "auth", "data": {"token": alice_token}})
            assert alice.receive_json()["type"] == "auth_ok"
            assert_closed_1008(alice)

        bob.send_json({"type": "message", "content": "still here"})
        assert bob.receive_json()["data"]["content"] == "still here"


def handmade_token(claims):
    return jwt.encode(claims, security.JWT_SECRET_KEY, algorithm=security.JWT_ALGORITHM)


@pytest.mark.parametrize("missing", ["exp", "sub"])
def test_token_missing_required_claim_is_rejected(client, missing):
    user_id = register(client, "alice")
    claims = {
        "sub": str(user_id),
        "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
    }
    del claims[missing]
    token = handmade_token(claims)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401

    with client.websocket_connect("/ws") as ws:
        ws.send_json({"type": "auth", "data": {"token": token}})
        assert_closed_1008(ws)
