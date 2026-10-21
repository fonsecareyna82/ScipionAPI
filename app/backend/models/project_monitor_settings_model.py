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
from sqlalchemy import Column, DateTime, ForeignKey, Integer
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.backend.database import Base


class ProjectMonitorSettings(Base):
    """The streaming monitor thresholds of a project; a project without a row uses the defaults."""

    __tablename__ = "project_monitor_settings"

    projectId = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    settings = Column(JSONB, nullable=False, server_default="{}")
    updatedBy = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    updatedAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
