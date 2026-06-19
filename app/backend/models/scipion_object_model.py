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
from sqlalchemy import Boolean, CheckConstraint, Column, DateTime, ForeignKey, Index, Integer, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.backend.database import Base


class ScipionObjectType(Base):
    __tablename__ = "scipion_object_types"

    id = Column(Integer, primary_key=True, index=True)
    className = Column(Text, nullable=False, unique=True)
    moduleName = Column(Text, nullable=True)
    baseClassName = Column(Text, nullable=True)
    mapperKind = Column(Text, nullable=False, default="tree")
    classSchema = Column("schema", JSONB, nullable=False, server_default="{}")
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    properties = relationship("ScipionObjectTypeProperty", back_populates="type", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("mapperKind IN ('tree', 'flat_set', 'scalar', 'pointer')", name="ck_scipion_object_types_mapper_kind"),
        Index("idx_scipion_object_types_className", "className"),
        Index("idx_scipion_object_types_mapperKind", "mapperKind"),
        Index("idx_scipion_object_types_schema_gin", "schema", postgresql_using="gin"),
    )


class ScipionObjectTypeProperty(Base):
    __tablename__ = "scipion_object_type_properties"

    id = Column(Integer, primary_key=True, index=True)
    typeId = Column(Integer, ForeignKey("scipion_object_types.id", ondelete="CASCADE"), nullable=False)
    propertyPath = Column(Text, nullable=False)
    className = Column(Text, nullable=True)
    valueKind = Column(Text, nullable=True)
    isPointer = Column(Boolean, nullable=False, default=False)
    isNested = Column(Boolean, nullable=False, default=False)
    propertySchema = Column("schema", JSONB, nullable=False, server_default="{}")
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    type = relationship("ScipionObjectType", back_populates="properties")

    __table_args__ = (
        UniqueConstraint("typeId", "propertyPath", name="ux_scipion_object_type_properties_type_path"),
        Index("idx_scipion_object_type_properties_path", "propertyPath"),
        Index("idx_scipion_object_type_properties_schema_gin", "schema", postgresql_using="gin"),
    )


class ScipionObject(Base):
    __tablename__ = "scipion_objects"

    id = Column(Integer, primary_key=True, index=True)
    projectId = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    protocolDbId = Column(Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=True)
    scipionObjId = Column(Integer, nullable=False)
    parentObjectId = Column(Integer, ForeignKey("scipion_objects.id", ondelete="CASCADE"), nullable=True)
    name = Column(Text, nullable=True)
    path = Column(Text, nullable=False)
    className = Column(Text, nullable=False)
    value = Column(Text, nullable=True)
    label = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    creation = Column(DateTime(timezone=True), nullable=True)
    objectMetadata = Column("metadata", JSONB, nullable=False, server_default="{}")
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    parent = relationship("ScipionObject", remote_side=[id], back_populates="children")
    children = relationship("ScipionObject", back_populates="parent", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("projectId", "protocolDbId", "scipionObjId", name="ux_scipion_objects_project_protocol_obj"),
        UniqueConstraint("projectId", "protocolDbId", "path", name="ux_scipion_objects_project_protocol_path"),
        Index("idx_scipion_objects_project_class", "projectId", "className"),
        Index("idx_scipion_objects_project_protocol", "projectId", "protocolDbId"),
        Index("idx_scipion_objects_parent", "parentObjectId"),
        Index("idx_scipion_objects_metadata_gin", "metadata", postgresql_using="gin"),
    )


class ScipionObjectRelation(Base):
    __tablename__ = "scipion_object_relations"

    id = Column(Integer, primary_key=True, index=True)
    projectId = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    creatorObjectId = Column(Integer, ForeignKey("scipion_objects.id", ondelete="CASCADE"), nullable=False)
    parentObjectId = Column(Integer, ForeignKey("scipion_objects.id", ondelete="CASCADE"), nullable=False)
    childObjectId = Column(Integer, ForeignKey("scipion_objects.id", ondelete="CASCADE"), nullable=False)
    name = Column(Text, nullable=False)
    parentExtended = Column(Text, nullable=True)
    childExtended = Column(Text, nullable=True)
    relationMetadata = Column("metadata", JSONB, nullable=False, server_default="{}")
    creation = Column(DateTime(timezone=True), nullable=True)
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_scipion_object_relations_project_name", "projectId", "name"),
        Index("idx_scipion_object_relations_parent", "parentObjectId"),
        Index("idx_scipion_object_relations_child", "childObjectId"),
        Index("idx_scipion_object_relations_metadata_gin", "metadata", postgresql_using="gin"),
    )


class ScipionSet(Base):
    __tablename__ = "scipion_sets"

    id = Column(Integer, primary_key=True, index=True)
    projectId = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    protocolDbId = Column(Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=True)
    objectId = Column(Integer, ForeignKey("scipion_objects.id", ondelete="SET NULL"), nullable=True)
    outputName = Column(Text, nullable=False)
    setClassName = Column(Text, nullable=False)
    itemClassName = Column(Text, nullable=False)
    properties = Column(JSONB, nullable=False, server_default="{}")
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    columns = relationship("ScipionSetColumn", back_populates="set", cascade="all, delete-orphan")
    setProperties = relationship("ScipionSetProperty", back_populates="set", cascade="all, delete-orphan")
    items = relationship("ScipionSetItem", back_populates="set", cascade="all, delete-orphan")

    __table_args__ = (
        UniqueConstraint("projectId", "protocolDbId", "outputName", name="ux_scipion_sets_project_protocol_output"),
        Index("idx_scipion_sets_project_protocol", "projectId", "protocolDbId"),
        Index("idx_scipion_sets_properties_gin", "properties", postgresql_using="gin"),
    )


class ScipionSetColumn(Base):
    __tablename__ = "scipion_set_columns"

    id = Column(Integer, primary_key=True, index=True)
    setId = Column(Integer, ForeignKey("scipion_sets.id", ondelete="CASCADE"), nullable=False)
    labelProperty = Column(Text, nullable=False)
    columnName = Column(Text, nullable=False)
    className = Column(Text, nullable=True)
    valueType = Column(Text, nullable=True)
    position = Column(Integer, nullable=False)
    indexed = Column(Boolean, nullable=False, default=False)

    set = relationship("ScipionSet", back_populates="columns")

    __table_args__ = (
        UniqueConstraint("setId", "labelProperty", name="ux_scipion_set_columns_set_label"),
        UniqueConstraint("setId", "columnName", name="ux_scipion_set_columns_set_column"),
        Index("idx_scipion_set_columns_label", "labelProperty"),
    )


class ScipionSetProperty(Base):
    __tablename__ = "scipion_set_properties"

    id = Column(Integer, primary_key=True, index=True)
    setId = Column(Integer, ForeignKey("scipion_sets.id", ondelete="CASCADE"), nullable=False)
    key = Column(Text, nullable=False)
    value = Column(Text, nullable=True)

    set = relationship("ScipionSet", back_populates="setProperties")

    __table_args__ = (
        UniqueConstraint("setId", "key", name="ux_scipion_set_properties_set_key"),
        Index("idx_scipion_set_properties_key", "key"),
    )


class ScipionSetItem(Base):
    __tablename__ = "scipion_set_items"

    id = Column(Integer, primary_key=True, index=True)
    setId = Column(Integer, ForeignKey("scipion_sets.id", ondelete="CASCADE"), nullable=False)
    scipionItemId = Column(Integer, nullable=False)
    enabled = Column(Boolean, nullable=False, default=True)
    label = Column(Text, nullable=True)
    comment = Column(Text, nullable=True)
    creation = Column(DateTime(timezone=True), nullable=True)
    values = Column(JSONB, nullable=False, server_default="{}")
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), onupdate=func.now(), nullable=True)

    set = relationship("ScipionSet", back_populates="items")

    __table_args__ = (
        UniqueConstraint("setId", "scipionItemId", name="ux_scipion_set_items_set_item"),
        Index("idx_scipion_set_items_set", "setId"),
        Index("idx_scipion_set_items_values_gin", "values", postgresql_using="gin"),
    )
