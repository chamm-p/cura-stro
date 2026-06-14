"""Auth-Schemas."""

from pydantic import BaseModel, EmailStr, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=100)
    password: str = Field(..., min_length=4)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class OidcExchangeRequest(BaseModel):
    code: str
    state: str | None = None


class UserOut(BaseModel):
    id: str
    username: str
    email: EmailStr
    role: str
    language: str
    first_name: str | None = None
    last_name: str | None = None
    full_name: str | None = None
    settings: dict | None = None
