# dependencies.py

import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt

from app.backend.bootstrap import bootstrapEnv
from app.backend.database import getMapperDependency as getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

# OAuth2 scheme to extract token from Authorization header
oauth2Scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

ALGORITHM = "HS256"


def _requireJwtSecretKey() -> str:
    # requireJwtSecretKey
    bootstrapEnv()
    secretKey = (os.getenv("SECRET_KEY") or "").strip()
    if not secretKey:
        scipionHome = os.getenv("SCIPION_HOME")
        raise RuntimeError(
            "Missing SECRET_KEY for JWT decoding. "
            f"SCIPION_HOME={scipionHome}. "
            "Ensure SCIPION_HOME/.env exists and contains SECRET_KEY, "
            "and that the app is started with the correct environment."
        )
    return secretKey


async def getCurrentUser(
    token: str = Depends(oauth2Scheme),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
) -> dict:
    """
    Decode the JWT token, verify its 'sub' claim (email),
    fetch the corresponding user via the mapper,
    and return the user record as a dict.
    Raises 401 if token is invalid or missing 'sub',
    raises 404 if no user is found for that email.
    """
    # decodeAndValidateJwt
    try:
        payload = jwt.decode(token, _requireJwtSecretKey(), algorithms=[ALGORITHM])
        email = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
        )

    # fetchUserByEmail
    userRecord = mapper.getUserByEmail(email)
    if not userRecord:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    return userRecord


async def requireAdmin(currentUser: dict = Depends(getCurrentUser)) -> dict:
    # requireAdmin
    role = str(currentUser.get("role") or "user").lower()
    if role != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return currentUser
