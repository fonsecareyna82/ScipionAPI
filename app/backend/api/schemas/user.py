# schemas/user.py

from pydantic import BaseModel, EmailStr, Field, field_validator


class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)
    firstName: str
    lastName: str
    institution: str

    # Validate password complexity
    @field_validator("password")
    @classmethod
    def validatePassword(cls, passwordValue: str) -> str:
        # Password must contain at least one letter and one number
        if not any(char.isalpha() for char in passwordValue) or not any(char.isdigit() for char in passwordValue):
            raise ValueError("Password must contain at least one letter and one number")
        return passwordValue

    # Validate email domain
    @field_validator("email")
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
