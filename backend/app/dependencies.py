import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from backend.app import crud, security
from backend.app.database import get_db
from backend.app.models import User

bearer_scheme = HTTPBearer(auto_error=False)

def get_user_from_token(db: Session, token: str) -> User | None:
    try:
        payload = security.decode_access_token(token)
        user_id = int(payload["sub"])
    except (jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None

    return crud.get_user_by_id(db, user_id)

def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise credentials_exception

    user = get_user_from_token(db, credentials.credentials)
    if user is None:
        raise credentials_exception

    return user