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
from fastapi import APIRouter, Depends, HTTPException, status, Body
from app.backend.api.schemas.user_schema import (UserCreate, UserOut, LoginResponse, LoginRequest, ResendCodeRequest,
                                                 UserUpdate)
from app.backend.database import getMapper
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.utils.security import hashPassword, verifyPassword
from app.backend.utils.jwt import createAccessToken, createRefreshToken, verifyToken
from app.backend.api.dependencies import getCurrentUser

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/signup", status_code=status.HTTP_201_CREATED)
async def signup(
    userData: UserCreate,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    # Check if email is already registered
    existingUser = mapper.getUserByEmail(userData.email)
    if existingUser:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Email already registered",
        )

    # Hash the password and generate a verification code
    hashedPassword = hashPassword(userData.password)
    verificationCode = str(uuid.uuid4())

    # Insert user into the database via the mapper
    userId = mapper.insertUser(
        email=userData.email,
        hashedPassword=hashedPassword,
        firstName=userData.firstName,
        lastName=userData.lastName,
        institution=userData.institution,
        role="user",
        isActive=True,
        isVerified=True,
        verificationCode=verificationCode,
    )

    # Return confirmation message and new user ID
    return {
        "message": "User created.",
        "userId": userId,
    }


@router.post("/verify", status_code=status.HTTP_200_OK)
def verifyEmail(
    verificationCode: str,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    user = mapper.getUserByVerificationCode(verificationCode)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid verification code"
        )
    mapper.verifyUser(user["id"])
    return {"message": "Email verified successfully"}


@router.post("/resend-code", status_code=status.HTTP_200_OK)
async def resendVerificationCode(
    request: ResendCodeRequest,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    user = mapper.getUserByEmail(request.email)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    if user["isVerified"]:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="User is already verified"
        )
    newCode = str(uuid.uuid4())
    mapper.updateUserVerificationCode(user["id"], newCode)
    return {"message": "Verification code updated"}


@router.post("/login", response_model=LoginResponse)
def login(
    loginData: LoginRequest,
    mapper: PostgresqlFlatMapper = Depends(getMapper)
):
    user = mapper.getUserByEmail(loginData.email)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid credentials")

    if not verifyPassword(loginData.password, user["hashedPassword"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid credentials")

    if not user["isVerified"]:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Email not verified")

    accessToken = createAccessToken(data={"sub": user["email"]})
    refreshToken = createRefreshToken(data={"sub": user["email"]})
    return LoginResponse(accessToken=accessToken, refreshToken=refreshToken, tokenType="bearer")


@router.get(
    "/me",
    response_model=UserOut,
    status_code=status.HTTP_200_OK
)
def getMe(
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Return the authenticated user's profile.
    """
    # Fetch up-to-date user fields from the database
    userProfile = mapper.getUserById(currentUser["id"])
    if not userProfile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return userProfile


@router.put(
    "/me",
    response_model=UserOut,
    status_code=status.HTTP_200_OK
)
def updateMe(
    updates: UserUpdate,
    currentUser: dict = Depends(getCurrentUser),
    mapper: PostgresqlFlatMapper = Depends(getMapper),
):
    """
    Update the authenticated user's profile fields.
    Only fields present in the request (exclude_unset) will be updated.
    """
    # Extract only provided fields from the payload
    updateFields = updates.dict(exclude_unset=True)

    # Persist updates via the mapper
    mapper.updateUserFields(currentUser["id"], updateFields)

    # Fetch the latest profile data
    userProfile = mapper.getUserById(currentUser["id"])
    if not userProfile:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found"
        )

    return userProfile


@router.post("/refresh")
def refreshToken(payload: dict = Body(...)):
    refresh_token = payload.get("token")
    if not refresh_token:
        raise HTTPException(status_code=400, detail="Missing token")

    decoded = verifyToken(refresh_token, expected_type="refresh")
    user_email = decoded.get("sub")
    if not user_email:
        raise HTTPException(status_code=401, detail="Invalid refresh token")

    new_access_token = createAccessToken(data={"sub": user_email})
    return {"accessToken": new_access_token}