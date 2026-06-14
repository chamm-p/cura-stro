"""User-Routen – /api/users/me."""

from fastapi import APIRouter, Depends

from app.api.deps import get_current_user
from app.models.user import User
from app.schemas.auth import UserOut

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role.value,
        language=user.language,
        first_name=user.first_name,
        last_name=user.last_name,
        full_name=user.full_name,
        settings=user.settings or {},
    )
