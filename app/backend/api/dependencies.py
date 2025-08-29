# dependencies.py

import os
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from app.backend.database import getDb
from app.backend.models.user import User
from app.backend.utils.jwt import decodeAccessToken

# OAuth2 scheme to extract token from Authorization header
oauth2Scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


SECRET_KEY = os.getenv("SECRET_KEY")
ALGORITHM = "HS256"


def getCurrentUser(token: str = Depends(oauth2Scheme), db: Session = Depends(getDb)) -> User:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        userId: str = payload.get("sub")
        if userId is None:
            raise HTTPException(status_code=401, detail="Invalid token")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")

    user = db.query(User).filter(User.id == int(userId)).first()
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    return user
