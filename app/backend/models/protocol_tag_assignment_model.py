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
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, PrimaryKeyConstraint, Text, func
from app.backend.database import Base


class ProtocolTagAssignment(Base):
    __tablename__ = "protocol_tag_assignments"

    protocolDbId = Column(Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False)
    tagId = Column(Text, ForeignKey("protocol_tags.id", ondelete="CASCADE"), nullable=False)
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        # compositePrimaryKey
        PrimaryKeyConstraint("protocolDbId", "tagId", name="pk_protocol_tag_assignments"),
        # indexesForFiltering
        Index("idx_protocol_tag_assignments_tagId", "tagId"),
        Index("idx_protocol_tag_assignments_protocolDbId", "protocolDbId"),
    )
