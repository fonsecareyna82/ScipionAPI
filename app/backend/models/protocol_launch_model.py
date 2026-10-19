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
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.backend.database import Base


class ProtocolLaunch(Base):
    """The parameters a protocol had each time it was launched, and who launched it."""

    __tablename__ = "protocol_launches"

    id = Column(Integer, primary_key=True, index=True)
    projectId = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    protocolDbId = Column(Integer, ForeignKey("protocols.id", ondelete="CASCADE"), nullable=False)
    protocolId = Column(String, nullable=False)
    userId = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    # launch, restart, continue or schedule
    mode = Column(Text, nullable=False)
    params = Column(JSONB, nullable=False, server_default="{}")
    launchedAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    __table_args__ = (
        Index("idx_protocol_launches_protocol", "protocolDbId", "launchedAt"),
        Index("idx_protocol_launches_project", "projectId"),
    )
