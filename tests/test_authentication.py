def test_register_user_success(client):
    response = client.post(
        "/users",
        json={"username": "alice", "password": "alice-password"},
    )

    assert response.status_code == 201
    data = response.json()
    assert data["username"] == "alice"
    assert "password_hash" not in data


def test_register_duplicate_username(client):
    payload = {"username": "alice", "password": "alice-password"}

    first_response = client.post("/users", json=payload)
    second_response = client.post("/users", json=payload)

    assert first_response.status_code == 201
    assert second_response.status_code == 409


def test_login_success(client):
    payload = {"username": "alice", "password": "alice-password"}
    client.post("/users", json=payload)

    response = client.post("/auth/login", json=payload)

    assert response.status_code == 200
    data = response.json()
    assert data["access_token"]
    assert data["token_type"] == "bearer"


def test_login_wrong_password(client):
    client.post(
        "/users",
        json={"username": "alice", "password": "alice-password"},
    )

    response = client.post(
        "/auth/login",
        json={"username": "alice", "password": "wrong-password"},
    )

    assert response.status_code == 401


def test_login_unknown_username(client):
    response = client.post(
        "/auth/login",
        json={"username": "nobody", "password": "some-password"},
    )

    assert response.status_code == 401