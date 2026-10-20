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
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, Text, func
from app.backend.database import Base


class ProtocolTag(Base):
    """A tag of a project's protocols. Titles are unique per project, in any case."""

    __tablename__ = "protocol_tags"

    id = Column(Text, primary_key=True)
    title = Column(Text, nullable=False)
    description = Column(Text, nullable=True)
    color = Column(Text, nullable=True)
    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updatedAt = Column(DateTime(timezone=True), nullable=True)
    projectId = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE", name="fk_protocol_tags_projectid"),
        nullable=False,
    )

    __table_args__ = (
        Index("idx_protocol_tags_projectid", "projectId"),
        # uniqueTitlePerProjectCaseInsensitive
        Index("ux_protocol_tags_project_lower_title", "projectId", func.lower(title), unique=True),
    )
