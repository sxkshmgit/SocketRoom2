from contextlib import asynccontextmanager

from fastapi import FastAPI

from backend.app import models  # noqa: F401
from backend.app.database import Base, engine

@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health_check():
    return {"status": "ok"}