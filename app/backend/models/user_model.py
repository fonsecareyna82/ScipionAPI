# models/user_model.py

from sqlalchemy import Column, Integer, String, Boolean
from sqlalchemy.orm import relationship
from app.backend.models.project_model import Project

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

    firstName = Column(String, nullable=True)
    lastName = Column(String, nullable=True)
    institution = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    position = Column(String, nullable=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    postalCode = Column(String, nullable=True)

    isVerified = Column(Boolean, default=False)
    verificationCode = Column(String, nullable=True)

    projects = relationship("Project", back_populates="owner")



