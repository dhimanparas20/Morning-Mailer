from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from google_auth.app.dependencies import (
    create_access_token,
    create_refresh_token,
    revoke_token,
    verify_token,
)

router = APIRouter(prefix="/api", tags=["api"])
security = HTTPBearer()


@router.get("/me")
async def get_me(credentials: HTTPAuthorizationCredentials = Depends(security)):
    token = credentials.credentials
    payload = verify_token(token, token_type="access")

    user_id = payload.get("sub")
    user_email = payload.get("email")

    if not user_id or not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    return {
        "id": user_id,
        "email": user_email,
        "name": payload.get("name", user_email.split("@")[0]),
        "picture": payload.get("picture"),
    }


@router.post("/refresh")
async def refresh_token(
    credentials: HTTPAuthorizationCredentials = Depends(security),
):
    token = credentials.credentials
    payload = verify_token(token, token_type="refresh")

    user_id = payload.get("sub")
    user_email = payload.get("email")

    if not user_id or not user_email:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
        )

    # Revoke the old refresh token (rotation)
    old_jti = payload.get("jti")
    if old_jti:
        revoke_token(old_jti)

    # Issue new token pair
    user_data = {
        "sub": user_id,
        "email": user_email,
        "name": payload.get("name", ""),
        "picture": payload.get("picture", ""),
    }
    new_access_token = create_access_token(data=user_data)
    new_refresh_token = create_refresh_token(data=user_data)

    return {
        "access_token": new_access_token,
        "refresh_token": new_refresh_token,
        "token_type": "bearer",
    }
