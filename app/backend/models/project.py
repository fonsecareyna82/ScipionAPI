# models/project.py

from sqlalchemy import Column, Integer, String, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.backend.database import Base

class Project(Base):
    __tablename__ = "projects"

    # Primary key
    id = Column(Integer, primary_key=True, index=True)

    # Project name
    name = Column(String, nullable=False)

    # Optional description
    description = Column(String, nullable=True)

    # Status of the project
    status = Column(String, default="active")

    # Foreign key to the user who owns the project
    ownerId = Column(Integer, ForeignKey("users.id"))

    # Timestamp when the project was created
    createdAt = Column(DateTime(timezone=True), server_default=func.now())

    # Timestamp when the project was last updated
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationship to the User model
    owner = relationship("User", back_populates="projects")
