
import re
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

USERNAME_PATTERN = re.compile(r"[A-Za-z0-9_.-]+")

class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("username", mode="before")
    @classmethod
    def normalize_username(cls, value):
        if not isinstance(value, str):
            return value  # let Pydantic report the wrong type
        value = value.strip()
        if not USERNAME_PATTERN.fullmatch(value):
            raise ValueError(
                "Use only letters, numbers, underscores, hyphens and periods."
            )
        return value.lower()


class UserUpdate(BaseModel):
    username: str = Field(min_length=1, max_length=50)


class UserResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    created_at: datetime

class LoginRequest(BaseModel):
    username: str = Field(max_length=50)
    password: str = Field(max_length=128)

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"

class MessageCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    content: str = Field(min_length=1, max_length=2000)


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    room_id: int
    sender_id: int
    sender_username: str
    content: str
    created_at: datetime