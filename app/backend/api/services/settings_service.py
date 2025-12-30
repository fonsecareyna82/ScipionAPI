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

# settingsService
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.api.schemas.settings_schema import (
    UserSettingsOut,
    UserSettingsIn,
    UserSettingsPatch,
    InstanceSettingsOut,
    InstanceSettingsIn,
    InstanceSettingsPatch,
)


def _getUserId(currentUser: Any) -> int:
    # getUserId
    uid = getattr(currentUser, "id", None)
    if uid is None and isinstance(currentUser, dict):
        uid = currentUser.get("id")
    if uid is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid currentUser: missing id",
        )
    return int(uid)


def _getUserRole(currentUser: Any) -> str:
    # getUserRole
    role = getattr(currentUser, "role", None)
    if role is None and isinstance(currentUser, dict):
        role = currentUser.get("role")
    return str(role or "user")


def _modelDump(modelObj: Any) -> Dict[str, Any]:
    # modelDump
    if hasattr(modelObj, "model_dump"):
        return modelObj.model_dump()
    return modelObj.dict()


def _modelValidate(modelCls: Any, data: Dict[str, Any]):
    # modelValidate
    if hasattr(modelCls, "model_validate"):
        return modelCls.model_validate(data)
    return modelCls.parse_obj(data)


class SettingsService:
    # settingsService
    def getUserSettings(self, mapper: PostgresqlFlatMapper, currentUser: Any) -> UserSettingsOut:
        # getUserSettings
        userId = _getUserId(currentUser)
        raw = mapper.getUserSettings(userId) or {}
        return _modelValidate(UserSettingsOut, raw)

    def putUserSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
        payload: UserSettingsIn,
    ) -> UserSettingsOut:
        # putUserSettings
        userId = _getUserId(currentUser)
        stored = mapper.upsertUserSettings(userId, _modelDump(payload))
        return _modelValidate(UserSettingsOut, stored or {})

    def patchUserSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
        patch: UserSettingsPatch,
    ) -> UserSettingsOut:
        # patchUserSettings
        userId = _getUserId(currentUser)
        current = mapper.getUserSettings(userId) or {}

        patchDict = _modelDump(patch)
        patchClean = {k: v for k, v in patchDict.items() if v is not None}

        merged = {**current, **patchClean}
        normalized = _modelValidate(UserSettingsOut, merged)

        stored = mapper.upsertUserSettings(userId, _modelDump(normalized))
        return _modelValidate(UserSettingsOut, stored or {})

    def _requireAdmin(self, currentUser: Any) -> None:
        # requireAdmin
        role = _getUserRole(currentUser)
        if role not in ("admin", "manager"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin privileges required",
            )

    def getInstanceSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
    ) -> InstanceSettingsOut:
        # getInstanceSettings
        self._requireAdmin(currentUser)
        raw = mapper.getInstanceSettings() or {}
        return _modelValidate(InstanceSettingsOut, raw)

    def putInstanceSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
        payload: InstanceSettingsIn,
    ) -> InstanceSettingsOut:
        # putInstanceSettings
        self._requireAdmin(currentUser)
        stored = mapper.upsertInstanceSettings(_modelDump(payload))
        return _modelValidate(InstanceSettingsOut, stored or {})

    def patchInstanceSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
        patch: InstanceSettingsPatch,
    ) -> InstanceSettingsOut:
        # patchInstanceSettings
        self._requireAdmin(currentUser)
        current = mapper.getInstanceSettings() or {}

        patchDict = _modelDump(patch)
        patchClean = {k: v for k, v in patchDict.items() if v is not None}

        merged = {**current, **patchClean}
        normalized = _modelValidate(InstanceSettingsOut, merged)

        stored = mapper.upsertInstanceSettings(_modelDump(normalized))
        return _modelValidate(InstanceSettingsOut, stored or {})
