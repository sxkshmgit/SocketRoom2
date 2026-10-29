def get_auth_headers(client, username="alice", password="alice-password"):
    client.post("/users", json={"username": username, "password": password})
    login_response = client.post(
        "/auth/login",
        json={"username": username, "password": password},
    )
    token = login_response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_me_without_token(client):
    response = client.get("/auth/me")

    assert response.status_code == 401


def test_me_with_valid_token(client):
    headers = get_auth_headers(client)

    response = client.get("/auth/me", headers=headers)

    assert response.status_code == 200
    data = response.json()
    assert data["username"] == "alice"
    assert "password_hash" not in data


def test_list_users_without_token(client):
    response = client.get("/users")

    assert response.status_code == 401


def test_list_users_with_invalid_token(client):
    response = client.get(
        "/users",
        headers={"Authorization": "Bearer not-a-valid-token"},
    )

    assert response.status_code == 401


def test_list_users_with_valid_token(client):
    headers = get_auth_headers(client)

    response = client.get("/users", headers=headers)

    assert response.status_code == 200
    usernames = [user["username"] for user in response.json()]
    assert "alice" in usernames