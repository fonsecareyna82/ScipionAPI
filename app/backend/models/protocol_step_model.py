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
from sqlalchemy import Boolean, Column, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.backend.database import Base


class ProtocolStep(Base):
    __tablename__ = "protocol_steps"

    id = Column(Integer, primary_key=True, index=True)
    projectId = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    protocolDbId = Column(Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False)
    protocolId = Column(String, nullable=False)
    stepIndex = Column(Integer, nullable=False)

    name = Column(Text, nullable=False)
    status = Column(Text, nullable=False)

    prerequisites = Column(JSONB, nullable=False, server_default="[]")
    args = Column(JSONB, nullable=True)

    initTime = Column(DateTime(timezone=True), nullable=True)
    endTime = Column(DateTime(timezone=True), nullable=True)
    elapsedSeconds = Column(Float, nullable=True)

    error = Column(Text, nullable=True)
    interactive = Column(Boolean, nullable=False, server_default="false")
    needsGpu = Column(Boolean, nullable=False, server_default="true")
    event = Column(Text, nullable=True)

    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        UniqueConstraint("projectId", "protocolDbId", "stepIndex", name="ux_protocol_steps_project_protocol_step"),
        Index("idx_protocol_steps_protocol", "projectId", "protocolDbId", "stepIndex"),
        Index("idx_protocol_steps_protocol_id", "projectId", "protocolId"),
    )