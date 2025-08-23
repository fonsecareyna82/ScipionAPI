# schemas/user.py

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    # Schema for user registration
    email: EmailStr
    password: str


class UserOut(BaseModel):
    # Schema for returning user data
    id: int
    email: EmailStr
    role: str
    isActive: bool

    class Config:
        orm_mode = True  # Enables compatibility with SQLAlchemy models
