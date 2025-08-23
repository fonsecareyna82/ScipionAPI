# models/user.py

from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from app.backend.models.project import Project

from app.backend.database import Base

class User(Base):
    __tablename__ = "users"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Unique email address
    email = Column(String, unique=True, index=True, nullable=False)

    # Hashed password for authentication
    hashedPassword = Column(String, nullable=False)

    # Active status flag
    isActive = Column(Boolean, default=True)

    # Role of the user (e.g., "admin", "user")
    role = Column(String, default="user")

    projects = relationship("Project", back_populates="owner")

    username = Column(String, unique=True, index=True, nullable=False)

