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
from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.sql import func

from app.backend.database import Base


class SystemTask(Base):
    __tablename__ = "system_tasks"

    id = Column(Integer, primary_key=True)

    taskId = Column(String, nullable=False, unique=True)

    taskType = Column(String, nullable=False, server_default="plugin")
    operation = Column(String, nullable=False)

    subject = Column(String, nullable=False)
    subjectLabel = Column(String, nullable=True)

    status = Column(String, nullable=False, server_default="PENDING")
    step = Column(Text, nullable=True)
    error = Column(Text, nullable=True)

    result = Column(JSONB, nullable=True)
    meta = Column(JSONB, nullable=True)
    payload = Column(JSONB, nullable=False, server_default="{}")

    backend = Column(String, nullable=False)

    acknowledged = Column(Boolean, nullable=False, server_default="false")
    retryOfTaskId = Column(String, nullable=True)

    logPath = Column(Text, nullable=True)

    createdAt = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    startedAt = Column(DateTime(timezone=True), nullable=True)
    finishedAt = Column(DateTime(timezone=True), nullable=True)
    updatedAt = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False)