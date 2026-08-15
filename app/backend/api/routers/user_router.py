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

# app/backend/api/routers/user_router.py

from fastapi import APIRouter, Depends
from typing import List, Dict, Any
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.database import getMapper
from app.backend.api.dependencies import getCurrentUser

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/")
def listUsers(
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    currentUser: dict = Depends(getCurrentUser),
) -> List[Dict[str, Any]]:
    """
    Return a lightweight list of users for project sharing.
    The current user is excluded from the result.
    """
    return mapper.listUsers(excludeUserId=currentUser["id"])
