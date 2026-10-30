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

from fastapi import APIRouter, Depends, HTTPException, status
from typing import List, Dict, Any
from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.database import getMapper
from app.backend.api.dependencies import getCurrentUser
from app.backend.api.permissions import requirePermission
from app.backend.api.services.access_service import AccessService
from app.backend.api.audit import recordAudit, userLabel
from app.backend.api.schemas.user_schema import AdminUserOut, AdminUserUpdate

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

@router.get("/admin", response_model=List[AdminUserOut])
def listAdminUsers(
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    adminUser: dict = Depends(requirePermission("users.manage")),
):
    return AccessService(mapper.db).withAccess(mapper.listUsersForAdmin())


@router.patch("/admin/{userId}", response_model=AdminUserOut)
def updateAdminUser(
    userId: int,
    updates: AdminUserUpdate,
    mapper: PostgresqlFlatMapper = Depends(getMapper),
    adminUser: dict = Depends(requirePermission("users.manage")),
):
    user = mapper.getUserById(userId)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    updateFields = updates.dict(exclude_unset=True)
    if not updateFields:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No user administration fields provided",
        )

    if int(userId) == int(adminUser["id"]) and updateFields.get("isActive") is False:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot deactivate your own account",
        )

    # Roles, groups and activation change together; no one gives what they do not hold
    changes = AccessService(mapper.db).updateUserAccess(adminUser, userId, updateFields, mapper.updateUserFields)
    if updateFields.get("isActive") is not None and bool(updateFields["isActive"]) != bool(user.get("isActive")):
        changes["isActive"] = bool(updateFields["isActive"])
    if changes:
        recordAudit(mapper, adminUser, "users.updated", "user", userId, userLabel(user), changes)

    updatedUser = mapper.getUserById(userId)
    if not updatedUser:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    updatedUser = AccessService(mapper.db).withAccess([updatedUser])[0]
    return updatedUser
