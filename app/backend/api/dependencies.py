# dependencies.py

import os
from dotenv import load_dotenv
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper

# OAuth2 scheme to extract token from Authorization header
oauth2Scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")

load_dotenv()
SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"


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
    # Decode and validate the JWT
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials"
            )
    except JWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials"
        )

    # Fetch user by email using the flat mapper
    user_record = mapper.getUserByEmail(email)
    if not user_record:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    # Return the user information as a dict
    return user_record
