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

import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.backend.api.schemas.user import UserCreate, UserOut, SignupResponse, LoginResponse, LoginRequest, \
    ResendCodeRequest, ErrorResponse
from app.backend.database import getDb
from app.backend.models.user import User
from app.backend.utils.email import sendVerificationEmail
from app.backend.utils.security import hashPassword, verifyPassword
from app.backend.utils.jwt import createAccessToken
from app.backend.api.dependencies import getCurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup")
async def signup(userData: UserCreate, db: Session = Depends(getDb)):
    existingUser = db.query(User).filter(User.email == userData.email).first()
    if existingUser:
        raise HTTPException(status_code=400, detail="Email already registered")

    hashedPw = hashPassword(userData.password)
    verification_code = str(uuid.uuid4())
    newUser = User(
        email=userData.email,
        hashedPassword=hashedPw,
        firstName=userData.firstName,
        lastName=userData.lastName,
        institution=userData.institution,
        role="user",
        isActive=True,
        isVerified=False,
        verificationCode=verification_code
    )
    db.add(newUser)
    db.commit()
    db.refresh(newUser)

    try:
        await sendVerificationEmail(userData.email, verification_code)
    except Exception as e:
        print("Error sending email:", e)

    return {"message": "User created. Please verify your email."}


@router.post("/verify")
def verifyEmail(code: str, db: Session = Depends(getDb)):
    user = db.query(User).filter(User.verificationCode == code).first()
    if not user:
        raise HTTPException(status_code=400, detail="Invalid verification code")

    user.isVerified = True
    user.verificationCode = None
    db.commit()
    return {"message": "Email verified successfully"}


@router.post("/resend-code")
async def resendVerificationCode(data: ResendCodeRequest, db: Session = Depends(getDb)):
    user = db.query(User).filter(User.email == data.email).first()

    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    if user.isVerified:
        raise HTTPException(status_code=400, detail="User is already verified")

    newCode = str(uuid.uuid4())
    user.verificationCode = newCode
    db.commit()

    await sendVerificationEmail(user.email, newCode)

    return {"message": "Verification code resent"}


@router.post("/login", response_model=LoginResponse)
def login(loginData: LoginRequest, db: Session = Depends(getDb)):
    user = db.query(User).filter(User.email == loginData.email).first()

    if not user or not verifyPassword(loginData.password, user.hashedPassword):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    if not user.isVerified:
        raise HTTPException(status_code=403, detail="Email not verified")

    access_token = createAccessToken(data={"sub": user.email})
    return LoginResponse(accessToken=access_token, tokenType="bearer")


@router.get("/me", response_model=UserOut)
def getMe(currentUser: User = Depends(getCurrentUser)):
    return currentUser
