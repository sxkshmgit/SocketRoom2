from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI , HTTPException ,  status
from sqlalchemy.orm import Session

from sqlalchemy.exc import IntegrityError
from backend.app import crud, models, schemas , security
from backend.app.database import Base, engine, get_db
from backend.app.dependencies import get_current_user

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
