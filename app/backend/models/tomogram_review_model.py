from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.backend.database import Base


class TomogramReviewSchema(Base):
    __tablename__ = "tomogram_review_schemas"

    id = Column(Integer, primary_key=True, index=True)
    setId = Column(Integer, ForeignKey("scipion_sets.id", ondelete="CASCADE"), nullable=False)
    version = Column(Integer, nullable=False, default=1, server_default="1")
    definition = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    createdByUserId = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    set = relationship("ScipionSet", back_populates="reviewSchema")

    __table_args__ = (
        CheckConstraint("version > 0", name="ck_tomogram_review_schemas_version_positive"),
        CheckConstraint("revision > 0", name="ck_tomogram_review_schemas_revision_positive"),
        UniqueConstraint("setId", name="ux_tomogram_review_schemas_set"),
        Index("idx_tomogram_review_schemas_set", "setId"),
        Index("idx_tomogram_review_schemas_definition_gin", "definition", postgresql_using="gin"),
    )


class TomogramReview(Base):
    __tablename__ = "tomogram_reviews"

    id = Column(Integer, primary_key=True, index=True)
    setId = Column(Integer, ForeignKey("scipion_sets.id", ondelete="CASCADE"), nullable=False)
    scipionItemId = Column(Integer, nullable=False)
    reviewed = Column(Boolean, nullable=False, default=False, server_default="false")
    values = Column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    comment = Column(Text, nullable=True)
    schemaVersion = Column(Integer, nullable=False, default=1, server_default="1")
    revision = Column(Integer, nullable=False, default=1, server_default="1")
    reviewedByUserId = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewedAt = Column(DateTime(timezone=True), nullable=True)
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)

    set = relationship("ScipionSet", back_populates="reviews")

    __table_args__ = (
        CheckConstraint('"schemaVersion" > 0', name="ck_tomogram_reviews_schema_version_positive"),
        CheckConstraint("revision > 0", name="ck_tomogram_reviews_revision_positive"),
        UniqueConstraint("setId", "scipionItemId", name="ux_tomogram_reviews_set_item"),
        Index("idx_tomogram_reviews_set", "setId"),
        Index("idx_tomogram_reviews_set_reviewed", "setId", "reviewed"),
        Index("idx_tomogram_reviews_updated", "updatedAt"),
        Index("idx_tomogram_reviews_values_gin", "values", postgresql_using="gin"),
    )
