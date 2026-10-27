from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from sqlalchemy.orm import Session

from backend.app import crud, models, schemas
from backend.app.database import Base, engine, get_db

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/users", response_model=list[schemas.UserResponse])
def list_users(db: Session = Depends(get_db)):
    return crud.get_users(db)