# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
# routers/auth_router.py

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.backend.api.schemas.user import UserCreate, UserOut, SignupResponse, LoginResponse, LoginRequest
from app.backend.database import getDb
from app.backend.models.user import User
from app.backend.utils.security import hashPassword, verifyPassword
from app.backend.utils.jwt import createAccessToken
from app.backend.api.dependencies import getCurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", response_model=SignupResponse)
def signup(userData: UserCreate, db: Session = Depends(getDb)):
    existingUser = db.query(User).filter(User.email == userData.email).first()
    if existingUser:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashedPw = hashPassword(userData.password)
    newUser = User(
        email=userData.email,
        hashedPassword=hashedPw,
        firstName=userData.firstName,
        lastName=userData.lastName,
        institution=userData.institution,
        role="user",
        isActive=True
    )
    db.add(newUser)
    db.commit()
    db.refresh(newUser)

    token = createAccessToken({"sub": str(newUser.id)})
    return SignupResponse(accessToken=token, tokenType="bearer")


@router.post("/login")
def login(user_data: LoginRequest, db: Session = Depends(getDb)):
    user = db.query(User).filter(User.email == user_data.email).first()
    if not user or not verifyPassword(user_data.password, user.hashedPassword):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    token = createAccessToken({"sub": str(user.id)})
    return LoginResponse(accessToken=token, tokenType="bearer")


@router.get("/me", response_model=UserOut)
def getMe(currentUser: User = Depends(getCurrentUser)):
    return currentUser
