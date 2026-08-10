from typing import Optional

from pydantic import BaseModel, EmailStr, Field, validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    firstName: str
    lastName: str
    institution: str

    @validator("password")
    @classmethod
    def validatePassword(cls, passwordValue: str) -> str:
        # validatePassword
        if not any(char.isalpha() for char in passwordValue) or not any(char.isdigit() for char in passwordValue):
            raise ValueError("Password must contain at least one letter and one number")
        return passwordValue

    @validator("email")
    @classmethod
    def validateEmailDomain(cls, emailValue: str) -> str:
        # validateEmailDomain
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
    institution: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    postalCode: Optional[str] = None

    class Config:
        orm_mode = True


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class LoginResponse(BaseModel):
    accessToken: str
    refreshToken: str
    tokenType: str


class SignupResponse(BaseModel):
    message: str
    userId: int


class ErrorResponse(BaseModel):
    detail: str


class ResendCodeRequest(BaseModel):
    email: EmailStr


class UserResponse(BaseModel):
    email: str
    firstName: str
    lastName: str
    institution: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    postalCode: Optional[str] = None

    class Config:
        orm_mode = True


class UserUpdate(BaseModel):
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    institution: Optional[str] = None
    phone: Optional[str] = None
    position: Optional[str] = None
    country: Optional[str] = None
    city: Optional[str] = None
    postalCode: Optional[str] = None