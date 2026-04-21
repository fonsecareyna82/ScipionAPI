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

import ast
import json
import logging
import os
import tempfile
import threading

from collections import OrderedDict
from configparser import RawConfigParser
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

import pyworkflow
from app.backend.api.services.reload_trigger import triggerBackendReloadIfEnabled
from pyworkflow import VariablesRegistry

from app.backend.mapper.postgresql import PostgresqlFlatMapper
from app.backend.api.schemas.settings_schema import (
    UserSettingsOut,
    UserSettingsIn,
    UserSettingsPatch,
    InstanceSettingsOut,
    InstanceSettingsIn,
    InstanceSettingsPatch,
    HostSettingsOut,
    HostSettingsIn,
    HostSettingsPatch,
)

logger = logging.getLogger(__name__)

_envLock = threading.Lock()
_hostLock = threading.Lock()


def _toStr(value: Any) -> str:
    # toStr
    return "" if value is None else str(value)


def _toBool(value: Any, default: bool = False) -> bool:
    # toBool
    if isinstance(value, bool):
        return value
    if value is None:
        return default

    lowered = str(value).strip().lower()
    if lowered in ("1", "true", "yes", "on"):
        return True
    if lowered in ("0", "false", "no", "off"):
        return False
    return default


def _maybeUnquoteString(value: Any) -> str:
    # maybeUnquoteString
    text = _toStr(value).strip()
    if not text:
        return ""

    if (text.startswith('"') and text.endswith('"')) or (text.startswith("'") and text.endswith("'")):
        try:
            parsed = ast.literal_eval(text)
            return "" if parsed is None else str(parsed)
        except Exception:
            return text

    return text


def _getScipionHome() -> str:
    # getScipionHome
    scipionHome = getattr(pyworkflow.Config, "SCIPION_HOME", None) or os.environ.get("SCIPION_HOME")
    scipionHome = _toStr(scipionHome).strip()

    if not scipionHome:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="SCIPION_HOME is not configured.",
        )

    return os.path.abspath(scipionHome)


def _getHostConfigPath() -> str:
    # getHostConfigPath
    return os.path.join(_getScipionHome(), "config", "hosts.conf")


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


def _newHostConfigParser() -> RawConfigParser:
    # newHostConfigParser
    cp = RawConfigParser(comment_prefixes=";")
    cp.optionxform = str
    return cp


def _readHostConfigParser() -> RawConfigParser:
    # readHostConfigParser
    hostConfigPath = _getHostConfigPath()
    if not os.path.isfile(hostConfigPath):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Host configuration file not found: {hostConfigPath}",
        )

    cp = _newHostConfigParser()
    try:
        if not cp.read(hostConfigPath, encoding="utf-8"):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Missing file {hostConfigPath}",
            )
        return cp
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to read host configuration file: {e}",
        )


def _writeHostConfigParserAtomic(cp: RawConfigParser, path: str) -> None:
    # writeHostConfigParserAtomic
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)

    fd, tempPath = tempfile.mkstemp(
        prefix=".hosts.",
        suffix=".tmp",
        dir=directory,
        text=True,
    )

    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            cp.write(fh)
            fh.flush()
            os.fsync(fh.fileno())

        os.replace(tempPath, path)
    finally:
        if os.path.exists(tempPath):
            try:
                os.remove(tempPath)
            except Exception:
                pass


def _selectPrimaryHostSection(cp: RawConfigParser) -> str:
    # selectPrimaryHostSection
    sections = cp.sections()
    if not sections:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="No host section found in hosts.conf",
        )

    if "localhost" in sections:
        return "localhost"

    return sections[0]


def _getHostOption(cp: RawConfigParser, hostName: str, varName: str, default: Optional[str] = None) -> Optional[str]:
    # getHostOption
    if not cp.has_option(hostName, varName):
        return default

    value = cp.get(hostName, varName)

    # Keep compatibility with Scipion loader behavior for escaped template comments
    value = value.replace("\n##", "\n#")

    return value


def _parseQueuesValue(rawValue: Any) -> list[dict[str, Any]]:
    # parseQueuesValue
    text = _toStr(rawValue).strip()
    if not text:
        return []

    try:
        parsed = json.loads(text, object_pairs_hook=OrderedDict)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Invalid QUEUES value in hosts.conf: {e}",
        )

    if not isinstance(parsed, dict):
        return []

    queues: list[dict[str, Any]] = []

    for queueName, paramsRaw in parsed.items():
        queueNameText = _toStr(queueName).strip()
        if not queueNameText:
            continue

        paramsList: list[dict[str, str]] = []

        if isinstance(paramsRaw, list):
            for item in paramsRaw:
                if isinstance(item, (list, tuple)):
                    values = list(item)
                    while len(values) < 4:
                        values.append("")

                    variableName = _toStr(values[0]).strip()
                    if not variableName:
                        continue

                    paramsList.append(
                        {
                            "variableName": variableName,
                            "value": _toStr(values[1]),
                            "label": _toStr(values[2]),
                            "help": _toStr(values[3]),
                        }
                    )
                    continue

                if isinstance(item, dict):
                    variableName = _toStr(
                        item.get("variableName") or item.get("key") or item.get("name")
                    ).strip()
                    if not variableName:
                        continue

                    paramsList.append(
                        {
                            "variableName": variableName,
                            "value": _toStr(item.get("value")),
                            "label": _toStr(item.get("label")),
                            "help": _toStr(item.get("help")),
                        }
                    )

        elif isinstance(paramsRaw, dict):
            # Backward-compatible fallback
            for paramKey, paramValue in paramsRaw.items():
                variableName = _toStr(paramKey).strip()
                if not variableName:
                    continue

                paramsList.append(
                    {
                        "variableName": variableName,
                        "value": _toStr(paramValue),
                        "label": variableName,
                        "help": "",
                    }
                )

        queues.append(
            {
                "name": queueNameText,
                "params": paramsList,
            }
        )

    return queues


def _encodeQueuesValue(queues: list[dict[str, Any]]) -> str:
    # encodeQueuesValue
    result: "OrderedDict[str, list[list[str]]]" = OrderedDict()

    for queue in queues or []:
        queueName = _toStr(queue.get("name")).strip()
        if not queueName:
            continue

        paramsOut: list[list[str]] = []

        for param in queue.get("params") or []:
            variableName = _toStr(param.get("variableName")).strip()
            if not variableName:
                continue

            paramsOut.append(
                [
                    variableName,
                    _toStr(param.get("value")),
                    _toStr(param.get("label")),
                    _toStr(param.get("help")),
                ]
            )

        result[queueName] = paramsOut

    return json.dumps(result, ensure_ascii=False, indent=4)


def _buildHostSettingsFromParser(cp: RawConfigParser, hostName: str) -> Dict[str, Any]:
    # buildHostSettingsFromParser
    payload = {
        "hostAlias": hostName,
        "schedulerName": _toStr(_getHostOption(cp, hostName, "NAME", "")).strip(),
        "mandatory": _toBool(_getHostOption(cp, hostName, "MANDATORY", False), False),
        "parallelCommand": _toStr(_getHostOption(cp, hostName, "PARALLEL_COMMAND", "")).strip(),
        "submitCommand": _toStr(_getHostOption(cp, hostName, "SUBMIT_COMMAND", "")).strip(),
        "cancelCommand": _toStr(_getHostOption(cp, hostName, "CANCEL_COMMAND", "")).strip(),
        "checkCommand": _toStr(_getHostOption(cp, hostName, "CHECK_COMMAND", "")).strip(),
        "jobDoneRegex": _maybeUnquoteString(_getHostOption(cp, hostName, "JOB_DONE_REGEX", "")),
        "submitTemplate": _toStr(_getHostOption(cp, hostName, "SUBMIT_TEMPLATE", "")),
        "queues": _parseQueuesValue(_getHostOption(cp, hostName, "QUEUES", "")),
    }

    return payload


def _copySectionItems(cp: RawConfigParser, sectionName: Optional[str]) -> "OrderedDict[str, str]":
    # copySectionItems
    items: "OrderedDict[str, str]" = OrderedDict()
    if sectionName and cp.has_section(sectionName):
        for key, value in cp.items(sectionName):
            items[key] = value
    return items


def _upsertHostSection(
    cp: RawConfigParser,
    sourceSectionName: Optional[str],
    data: Dict[str, Any],
) -> str:
    # upsertHostSection
    targetSectionName = _toStr(data.get("hostAlias")).strip() or (sourceSectionName or "localhost")

    if sourceSectionName and sourceSectionName != targetSectionName and cp.has_section(targetSectionName):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Host section '{targetSectionName}' already exists.",
        )

    existingItems = _copySectionItems(cp, sourceSectionName)

    if sourceSectionName and cp.has_section(sourceSectionName):
        cp.remove_section(sourceSectionName)

    if not cp.has_section(targetSectionName):
        cp.add_section(targetSectionName)

    # Preserve unmanaged keys from the previous section
    for key, value in existingItems.items():
        cp.set(targetSectionName, key, value)

    cp.set(targetSectionName, "PARALLEL_COMMAND", _toStr(data.get("parallelCommand")).strip())
    cp.set(targetSectionName, "NAME", _toStr(data.get("schedulerName")).strip())
    cp.set(targetSectionName, "MANDATORY", "True" if bool(data.get("mandatory")) else "False")
    cp.set(targetSectionName, "SUBMIT_COMMAND", _toStr(data.get("submitCommand")).strip())
    cp.set(targetSectionName, "SUBMIT_TEMPLATE", _toStr(data.get("submitTemplate")))
    cp.set(targetSectionName, "CANCEL_COMMAND", _toStr(data.get("cancelCommand")).strip())
    cp.set(targetSectionName, "CHECK_COMMAND", _toStr(data.get("checkCommand")).strip())
    cp.set(targetSectionName, "JOB_DONE_REGEX", json.dumps(_toStr(data.get("jobDoneRegex")), ensure_ascii=False))
    cp.set(targetSectionName, "QUEUES", _encodeQueuesValue(data.get("queues") or []))

    return targetSectionName


def _normalizeHostSettingsOut(data: Dict[str, Any]) -> HostSettingsOut:
    # normalizeHostSettingsOut
    return _modelValidate(HostSettingsOut, data)


def _isScipionEnvVar(name: str) -> bool:
    # isScipionEnvVar
    upper = (name or "").strip().upper()
    return upper.startswith("SCIPION_")


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

    def _registryCount(self) -> int:
        # registryCount
        try:
            return len(list(VariablesRegistry.__iter__()))
        except Exception:
            return -1

    def _warmupEnvironmentRegistry(self) -> None:
        # warmupEnvironmentRegistry
        from scipion.__main__ import Vars
        from pyworkflow.project import Manager
        from pyworkflow.template import TemplateList

        logger.warning("registry count [start]: %s", self._registryCount())

        Vars.init()
        logger.warning("registry count [after Vars.init]: %s", self._registryCount())

        pyworkflow.Config.getVars()
        logger.warning("registry count [after Config.getVars]: %s", self._registryCount())

        pyworkflow.Config.setDomain("pwem")
        domain = pyworkflow.Config.getDomain()
        logger.warning("registry count [after Config.getDomain]: %s", self._registryCount())

        try:
            domain.getProtocols()
        except Exception:
            logger.exception("Error warming domain.getProtocols()")
        logger.warning("registry count [after domain.getProtocols]: %s", self._registryCount())

        try:
            Manager()
        except Exception:
            logger.exception("Error warming Manager()")
        logger.warning("registry count [after Manager()]: %s", self._registryCount())

        try:
            tempList = TemplateList()
            tempList.addScipionTemplates(None)
            tempList.addPluginTemplates(None)
        except Exception:
            logger.exception("Error warming TemplateList plugins")
        logger.warning("registry count [after TemplateList warmup]: %s", self._registryCount())

    def getEnvironmentVariables(self, currentUser: Any) -> list[dict[str, str]]:
        # getEnvironmentVariables
        self._requireAdmin(currentUser)

        with _envLock:
            self._warmupEnvironmentRegistry()

            rows = []

            for variable in VariablesRegistry.__iter__():
                try:
                    variableName = _toStr(getattr(variable, "name", "")).strip()
                    if not variableName:
                        continue

                    currentValue = getattr(variable, "value", None)
                    if variableName in os.environ:
                        currentValue = os.environ.get(variableName, "")
                        variable.value = currentValue

                        defaultValue = getattr(variable, "default", None)
                        if defaultValue is not None:
                            variable.isDefault = str(defaultValue) == str(currentValue)

                    rows.append(
                        {
                            "name": variableName,
                            "value": "" if currentValue is None else str(currentValue),
                            "default": "" if getattr(variable, "default", None) is None else str(variable.default),
                            "description": "" if getattr(variable, "description", None) is None else str(
                                variable.description),
                            "source": "" if getattr(variable, "source", None) is None else str(variable.source),
                            "isDefault": False if getattr(variable, "isDefault", None) is None else bool(
                                variable.isDefault),
                            "type": "STRING"
                            if getattr(variable, "var_type", None) is None
                            else str(variable.var_type.name),
                        }
                    )
                except Exception:
                    continue

            rows.sort(key=lambda item: (item.get("name") or "").upper())
            return rows

    def patchEnvironmentVariables(self, currentUser: Any, patch: Dict[str, Any]) -> list[dict[str, str]]:
        # patchEnvironmentVariables
        self._requireAdmin(currentUser)

        if not isinstance(patch, dict):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid payload: expected an object mapping variable names to values.",
            )

        changed = False

        with _envLock:
            patchItems: dict[str, str] = {}
            for rawName, rawValue in patch.items():
                name = _toStr(rawName).strip()
                if not name:
                    continue
                patchItems[name] = "" if rawValue is None else str(rawValue)

            if patchItems:
                for variable in VariablesRegistry.__iter__():
                    try:
                        variableName = _toStr(getattr(variable, "name", "")).strip()
                        if not variableName or variableName not in patchItems:
                            continue

                        nextValue = patchItems[variableName]
                        currentValue = "" if getattr(variable, "value", None) is None else str(variable.value)

                        if currentValue == nextValue and os.environ.get(variableName) == nextValue:
                            continue

                        os.environ[variableName] = nextValue
                        variable.value = nextValue

                        defaultValue = getattr(variable, "default", None)
                        if defaultValue is not None:
                            variable.isDefault = str(defaultValue) == str(nextValue)
                        else:
                            variable.isDefault = False

                        changed = True
                    except Exception:
                        continue

                if changed:
                    VariablesRegistry.save(pyworkflow.Config.SCIPION_CONFIG)

        if changed:
            triggerBackendReloadIfEnabled()

        return self.getEnvironmentVariables(currentUser)

    def getHostSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
    ) -> HostSettingsOut:
        # getHostSettings
        self._requireAdmin(currentUser)

        with _hostLock:
            cp = _readHostConfigParser()
            hostName = _selectPrimaryHostSection(cp)
            parsed = _buildHostSettingsFromParser(cp, hostName)
            return _normalizeHostSettingsOut(parsed)

    def putHostSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
        payload: HostSettingsIn,
    ) -> HostSettingsOut:
        # putHostSettings
        self._requireAdmin(currentUser)

        normalized = _modelValidate(HostSettingsOut, _modelDump(payload))
        outputData = _modelDump(normalized)

        with _hostLock:
            cp = _readHostConfigParser()
            sourceSectionName = _selectPrimaryHostSection(cp)
            _upsertHostSection(cp, sourceSectionName, outputData)

            hostConfigPath = _getHostConfigPath()
            _writeHostConfigParserAtomic(cp, hostConfigPath)

        triggerBackendReloadIfEnabled()
        return normalized

    def patchHostSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
        patch: HostSettingsPatch,
    ) -> HostSettingsOut:
        # patchHostSettings
        self._requireAdmin(currentUser)

        patchDict = _modelDump(patch)
        patchClean = {k: v for k, v in patchDict.items() if v is not None}

        with _hostLock:
            cp = _readHostConfigParser()
            sourceSectionName = _selectPrimaryHostSection(cp)
            currentData = _buildHostSettingsFromParser(cp, sourceSectionName)

            merged = {**currentData, **patchClean}
            normalized = _modelValidate(HostSettingsOut, merged)

            _upsertHostSection(cp, sourceSectionName, _modelDump(normalized))

            hostConfigPath = _getHostConfigPath()
            _writeHostConfigParserAtomic(cp, hostConfigPath)

        triggerBackendReloadIfEnabled()
        return normalized

    def getRuntimeInstanceSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
    ) -> Dict[str, Any]:
        # getRuntimeInstanceSettings
        raw = mapper.getInstanceSettings() or {}
        normalized = _modelValidate(InstanceSettingsOut, raw)

        if hasattr(normalized, "model_dump"):
            data = normalized.model_dump()
        else:
            data = normalized.dict()

        # runtimeSafeSubset
        return {
            "enableCelery": data.get("enableCelery"),
            "defaultQueueName": data.get("defaultQueueName"),
            "maxConcurrentRunsPerUser": data.get("maxConcurrentRunsPerUser"),
            "requireConfirmBeforeExecute": data.get("requireConfirmBeforeExecute"),
            "requireConfirmBeforeDelete": data.get("requireConfirmBeforeDelete"),
        }

    def getRuntimeHostSettings(
        self,
        mapper: PostgresqlFlatMapper,
        currentUser: Any,
    ) -> Dict[str, Any]:
        # getRuntimeHostSettings
        with _hostLock:
            cp = _readHostConfigParser()
            hostName = _selectPrimaryHostSection(cp)
            parsed = _buildHostSettingsFromParser(cp, hostName)
            normalized = _normalizeHostSettingsOut(parsed)

        if hasattr(normalized, "model_dump"):
            data = normalized.model_dump()
        else:
            data = normalized.dict()

        # runtimeSafeSubset
        return {
            "hostAlias": data.get("hostAlias"),
            "schedulerName": data.get("schedulerName"),
            "mandatory": data.get("mandatory"),
            "queues": data.get("queues") or [],
            # keepTheseIfFrontendNeedsThemForLaunchPreviewOrAdvancedDialogs
            "parallelCommand": data.get("parallelCommand"),
            "submitCommand": data.get("submitCommand"),
            "cancelCommand": data.get("cancelCommand"),
            "checkCommand": data.get("checkCommand"),
            "jobDoneRegex": data.get("jobDoneRegex"),
            "submitTemplate": data.get("submitTemplate"),
        }