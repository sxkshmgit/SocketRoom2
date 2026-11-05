import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import (
    Depends,
    FastAPI,
    HTTPException,
    Query,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError , SQLAlchemyError
from backend.app import crud, models, schemas , security
from backend.app.database import Base, SessionLocal, engine, get_db
from backend.app.connection_manager import manager
from backend.app.dependencies import get_current_user, get_user_from_token

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        crud.ensure_default_room(db)
    finally:
        db.close()
    yield

app = FastAPI(lifespan=lifespan)

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/users", response_model=list[schemas.UserResponse])
def list_users(
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    return crud.get_users(db)

@app.post(
    "/users",
    response_model=schemas.UserResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_user(user_in: schemas.UserCreate, db: Session = Depends(get_db)):
    if crud.get_user_by_username(db, user_in.username) is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )

    password_hash = security.hash_password(user_in.password)

    try:
        return crud.create_user(db, user_in.username, password_hash)
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Username already taken",
        )


@app.post("/auth/login", response_model=schemas.TokenResponse)
def login(login_in: schemas.LoginRequest, db: Session = Depends(get_db)):
    user = crud.get_user_by_username(db, login_in.username)

    if user is None or not security.verify_password(
        login_in.password, user.password_hash
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = security.create_access_token(data={"sub": str(user.id)})
    return schemas.TokenResponse(access_token=access_token, token_type="bearer")

@app.get("/auth/me", response_model=schemas.UserResponse)
def read_current_user(current_user: models.User = Depends(get_current_user)):
    return current_user

@app.get("/messages", response_model=list[schemas.MessageResponse])
def list_messages(
    limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
):
    room = crud.get_default_room(db)
    if room is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Default chat room is not available",
        )

    return crud.get_recent_messages(db, room.id, limit)

AUTH_TIMEOUT_SECONDS = 10


def authenticate_token(token: str) -> tuple[int, str] | None:
    db = SessionLocal()
    try:
        user = get_user_from_token(db, token)
        if user is None:
            return None
        return user.id, user.username
    except SQLAlchemyError:
        return None
    finally:
        db.close()


def save_chat_message(user_id: int, content: str) -> dict | None:
    db = SessionLocal()
    try:
        room = crud.get_default_room(db)
        if room is None:
            return None
        message = crud.create_message(db, room.id, user_id, content)
        return schemas.MessageResponse.model_validate(message).model_dump(mode="json")
    except SQLAlchemyError:
        db.rollback()
        return None
    finally:
        db.close()


@app.websocket("/ws")
async def websocket_chat(websocket: WebSocket):
    await websocket.accept()
    try:
        try:
            auth_frame = await asyncio.wait_for(
                websocket.receive_json(), timeout=AUTH_TIMEOUT_SECONDS
            )
        except (asyncio.TimeoutError, ValueError, KeyError, TypeError):
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        token = None
        if isinstance(auth_frame, dict) and auth_frame.get("type") == "auth":
            auth_data = auth_frame.get("data")
            if isinstance(auth_data, dict):
                token = auth_data.get("token")

        identity = authenticate_token(token) if isinstance(token, str) else None
        if identity is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
            return

        user_id, username = identity
        await websocket.send_json(
            {"type": "auth_ok", "data": {"user_id": user_id, "username": username}}
        )
        manager.connect(websocket)

        while True:
            try:
                frame = await websocket.receive_json()
            except (ValueError, KeyError, TypeError):
                await websocket.send_json(
                    {"type": "error", "content": "Invalid message format"}
                )
                continue

            if not isinstance(frame, dict) or frame.get("type") != "message":
                await websocket.send_json(
                    {"type": "error", "content": "Unsupported message type"}
                )
                continue

            try:
                message_in = schemas.MessageCreate(content=frame.get("content"))
            except ValidationError:
                await websocket.send_json(
                    {"type": "error", "content": "Message content is invalid"}
                )
                continue

            payload = save_chat_message(user_id, message_in.content)
            if payload is None:
                await websocket.send_json(
                    {"type": "error", "content": "Message could not be saved"}
                )
                continue

            await manager.broadcast({"type": "message", "data": payload})
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(websocket)
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

@app.get("/", include_in_schema=False)
def serve_index():
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")