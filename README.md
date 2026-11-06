# SocketRoom2

A simple real-time chat application built with **FastAPI, WebSockets, SQLite, SQLAlchemy, and vanilla JavaScript**.

SocketRoom2 is a learning and portfolio project focused on backend fundamentals, authentication, database persistence, and real-time communication between connected clients.

## Features

- User registration and login.
- Password hashing with Argon2.
- JWT-based authentication for HTTP routes and WebSocket connections.
- A single shared chatroom named **General**.
- Real-time message broadcasting to connected clients.
- Persistent message storage with SQLite.
- Retrieval of recent message history (up to 100 messages per request).
- Automatic WebSocket reconnection with exponential backoff and jitter.
- Automatic retries when loading chat history fails, followed by a manual Retry option.
- Username normalization and validation.
- Different WebSocket close handling for invalid authentication and temporary database errors.

## Tech stack

| Area | Technology |
|---|---|
| Backend | Python, FastAPI |
| Real-time communication | WebSockets |
| Database | SQLite |
| ORM | SQLAlchemy |
| Data validation | Pydantic |
| Authentication | JWT, PyJWT |
| Password hashing | Argon2 through pwdlib |
| Frontend | HTML, CSS, vanilla JavaScript |
| Tests | Pytest |

## Project structure

~~~text
SocketRoom2/
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── connection_manager.py
│   │   ├── crud.py
│   │   ├── database.py
│   │   ├── dependencies.py
│   │   ├── models.py
│   │   ├── schemas.py
│   │   └── security.py
│   ├── requirements.txt
│   └── requirements-dev.txt
├── frontend/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── tests/
│   ├── conftest.py
│   ├── test_authentication.py
│   ├── test_protected_routes.py
│   └── test_room_initialization.py
└── .gitignore
~~~

## Getting started

### Prerequisites

- Python 3.10 or newer.
- Git.
- A modern web browser.

### 1. Clone the repository

~~~bash
git clone https://github.com/sxkshmgit/SocketRoom2.git
cd SocketRoom2
~~~

### 2. Create and activate a virtual environment

Create it from the project root:

~~~bash
python -m venv .venv
~~~

Activate it using the command for your terminal.

**Windows PowerShell**

~~~powershell
.venv\Scripts\Activate.ps1
~~~

**Git Bash**

~~~bash
source .venv/Scripts/activate
~~~

### 3. Install dependencies

Install the application and development dependencies:

~~~bash
python -m pip install -r backend/requirements-dev.txt
~~~

### 4. Set the JWT secret

The application reads the signing secret from the **JWT_SECRET_KEY** environment variable. Set it before starting the server.

The following commands generate a random secret for a local development session.

**Windows PowerShell**

~~~powershell
$env:JWT_SECRET_KEY = python -c "import secrets; print(secrets.token_urlsafe(32))"
~~~

**Git Bash**

~~~bash
export JWT_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"
~~~

Keep the same terminal session open while running the application. If you generate a different secret later, JWTs signed with the previous secret will no longer validate.

For deployment, configure a persistent secret through the hosting environment. Do not commit the secret to the repository.

### 5. Run the application

From the project root, with the virtual environment activated and the secret set:

~~~bash
python -m uvicorn main:app --app-dir backend/app --reload
~~~

Open the application:

~~~text
http://127.0.0.1:8000
~~~

On startup, the application creates the SQLite tables and initializes the **General** room if it does not already exist. The database file is stored at **backend/socketroom.db** and is ignored by Git.

The interactive API documentation is available at:

~~~text
http://127.0.0.1:8000/docs
~~~

## How it works

### Authentication

1. A user registers with a username and password.
2. The backend trims and lowercases new usernames and validates the allowed characters.
3. The password is hashed using Argon2 before it is stored.
4. During login, the backend verifies the password and issues a JWT.
5. The frontend stores the token in session storage.
6. Protected HTTP requests send the token in the Authorization header.
7. For WebSocket authentication, the client sends the token in the first JSON frame after connecting.

New usernames may contain letters, numbers, underscores, hyphens, and periods, with a maximum length of 50 characters. New passwords must be 8–128 characters long. Login permits existing shorter passwords for compatibility and accepts username capitalization differences for normalized accounts.

### Real-time message flow

1. The browser opens a WebSocket connection to the backend.
2. The client sends its JWT in an authentication frame.
3. The backend validates the token and confirms the connection.
4. The client sends a message frame.
5. The backend validates the message and saves it to SQLite.
6. The connection manager broadcasts the saved message to the active WebSocket connections.
7. Connected clients render the message.

The frontend reconnects after unexpected WebSocket closures. Invalid authentication closes the connection with code **1008**; a temporary database error during WebSocket authentication uses **1013**, allowing the client to retry without clearing its token.

### Chat history

The authenticated HTTP endpoint returns recent messages in chronological order. It accepts a **limit** query parameter between 1 and 100.

Example:

~~~http
GET /messages?limit=50
~~~

If loading history fails because of a network or server error, the frontend retries a limited number of times with increasing delays. It then displays a manual Retry option.

## API endpoints

| Method | Endpoint | Description | Authentication |
|---|---|---|---|
| GET | / | Serves the frontend | No |
| GET | /health | Health check | No |
| POST | /users | Registers a user | No |
| POST | /auth/login | Authenticates a user and returns a JWT | No |
| GET | /auth/me | Returns the authenticated user | Yes |
| GET | /users | Lists registered users | Yes |
| GET | /messages | Returns recent chat history | Yes |

Static frontend assets are served under **/static**.

## WebSocket protocol

The WebSocket endpoint is:

~~~text
ws://127.0.0.1:8000/ws
~~~

When the application is served over HTTPS, the frontend uses secure WebSockets (**wss://**).

### 1. Authentication frame

The first client frame must contain the JWT:

~~~json
{
  "type": "auth",
  "data": {
    "token": "YOUR_JWT_TOKEN"
  }
}
~~~

### 2. Authentication success

The server responds with:

~~~json
{
  "type": "auth_ok",
  "data": {
    "user_id": 1,
    "username": "alice"
  }
}
~~~

### 3. Send a message

~~~json
{
  "type": "message",
  "content": "Hello everyone!"
}
~~~

### 4. Receive a broadcast message

The server broadcasts the saved message in this format:

~~~json
{
  "type": "message",
  "data": {
    "id": 1,
    "room_id": 1,
    "sender_id": 1,
    "sender_username": "alice",
    "content": "Hello everyone!",
    "created_at": "2026-11-06T10:00:00"
  }
}
~~~

## Running tests

The backend test suite uses Pytest. From the project root, with development dependencies installed, run:

~~~bash
python -m pytest -v
~~~

The current tests cover user registration and login, duplicate usernames, protected HTTP routes, and initialization of the default chatroom.

## Project scope and limitations

SocketRoom2 is intentionally a small, single-room application. Its current design has these limitations:

- **Single process:** active WebSocket connections are held in memory by one connection manager. Run the application with a single Uvicorn worker; multiple workers would maintain separate connection lists and would not broadcast messages across processes.
- **Recent history only:** the API returns up to 100 recent messages per request. Older-message pagination is not implemented.
- **No explicit send acknowledgement:** the WebSocket protocol does not yet provide a client message ID and server acknowledgement for each send. A connection failure at the wrong moment can therefore leave the sender unsure whether a message was saved.
- **No distributed broker:** there is no Redis or other pub/sub layer for coordinating multiple application processes.
- **Basic abuse protection:** rate limiting, connection caps, and production-grade abuse controls are not implemented.
- **SQLite:** SQLite is used for simple local persistence; the project is not designed as a high-concurrency messaging service.

The project is intended for learning, demonstration, and portfolio use. It is not presented as a hardened public messaging service.

## Learning goals

This project provides hands-on practice with:

- Building REST endpoints with FastAPI.
- Validating request and response data with Pydantic.
- Hashing passwords and issuing JWTs.
- Modeling relational data and performing CRUD operations with SQLAlchemy.
- Persisting messages in SQLite.
- Authenticating and managing WebSocket connections.
- Broadcasting messages to multiple connected clients.
- Connecting a vanilla JavaScript frontend to a Python backend.
- Handling reconnects and failed history requests.
- Testing backend behavior with Pytest.

## License

No license has been added to this repository yet.