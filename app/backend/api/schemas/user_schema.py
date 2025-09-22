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

# schemas/user_model.py
from typing import Optional

from pydantic import BaseModel, EmailStr, Field, validator

from app.backend.api.routers.project_router import router


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    firstName: str
    lastName: str
    institution: str

    # Validate password complexity
    @validator("password")
    @classmethod
    def validatePassword(cls, passwordValue: str) -> str:
        # Password must contain at least one letter and one number
        if not any(char.isalpha() for char in passwordValue) or not any(char.isdigit() for char in passwordValue):
            raise ValueError("Password must contain at least one letter and one number")
        return passwordValue

    # Validate email domain
    @validator("email")
    @classmethod
    def validateEmailDomain(cls, emailValue: str) -> str:
        # Reject temporary or disposable email domains
        forbiddenDomains = ["tempmail.com", "mailinator.com", "10minutemail.com"]
        domain = emailValue.split("@")[-1]
        if domain in forbiddenDomains:
            raise ValueError("Email domain is not allowed")
        return emailValue


class UserOut(BaseModel):
    id: int
    email: EmailStr
    role: str
    isActive: bool
    firstName: str
    lastName: str
    institution: str
    phone: Optional[str]
    position: Optional[str]
    country: Optional[str]
    city: Optional[str]
    postalCode: Optional[str]

    class Config:
        orm_mode = True  # Enables compatibility with SQLAlchemy models


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    accessToken: str
    tokenType: str


class SignupResponse(BaseModel):
    accessToken: str  # JWT token for authentication
    tokenType: str  # Token type used in Authorization header


class ErrorResponse(BaseModel):
    detail: str


@router.post(
    "/signup",
    response_model=SignupResponse,
    responses={400: {"model": ErrorResponse}}
)
class ResendCodeRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    email: str
    firstName: str
    lastName: str
    institution: Optional[str]
    phone: Optional[str]
    position: Optional[str]
    country: Optional[str]
    city: Optional[str]
    postalCode: Optional[str]

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    firstName: Optional[str]
    lastName: Optional[str]
    institution: Optional[str]
    phone: Optional[str]
    position: Optional[str]
    country: Optional[str]
    city: Optional[str]
    postalCode: Optional[str]
