# dependencies.py

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.orm import Session
from app.backend.database import getDb
from app.backend.models.user import User
from app.backend.utils.jwt import decodeAccessToken

# OAuth2 scheme to extract token from Authorization header
oauth2Scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def getCurrentUser(token: str = Depends(oauth2Scheme), db: Session = Depends(getDb)) -> User:
    # Decode JWT token
    payload = decodeAccessToken(token)
    if not payload or "sub" not in payload:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Retrieve user from database
    user = db.query(User).filter(User.id == int(payload["sub"])).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    return user
