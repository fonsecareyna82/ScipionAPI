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
import logging
import os
import re
from typing import Any, Callable, Dict, List, Optional, Union

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class RuntimeProtocolLogService:
    """
    Handles protocol log channel discovery and incremental log polling.
    """

    def resolvePostgresqlProtocolRunPath(
            self,
            *,
            mapper,
            projectId: int,
            scipionProtocolId: Union[int, str],
            resolvePostgresqlProjectPathForFilesystemCallback: Callable,
    ) -> Optional[str]:
        projectPath = resolvePostgresqlProjectPathForFilesystemCallback(
            mapper=mapper,
            projectId=projectId,
        )

        if not projectPath:
            return None

        runsPath = os.path.join(projectPath, "Runs")
        if not os.path.isdir(runsPath):
            return None

        runtimeIdText = str(scipionProtocolId).strip()
        runtimeIdInt = None

        try:
            runtimeIdInt = int(runtimeIdText)
        except Exception:
            pass

        matches: List[str] = []

        try:
            for entry in os.scandir(runsPath):
                if not entry.is_dir():
                    continue

                name = entry.name

                if name.startswith("%s_" % runtimeIdText):
                    matches.append(entry.path)
                    continue

                if runtimeIdInt is not None:
                    match = re.match(r"^0*(\d+)_", name)
                    if match and int(match.group(1)) == runtimeIdInt:
                        matches.append(entry.path)
                        continue

        except Exception:
            logger.debug(
                "Could not scan Runs folder for protocol logs. runsPath=%s",
                runsPath,
                exc_info=True,
            )
            return None

        if not matches:
            return None

        return sorted(matches)[0]

    @staticmethod
    def firstExistingLogPath(
            protocolPath: str,
            candidates: List[str],
    ) -> Optional[str]:
        for candidate in candidates:
            path = os.path.join(protocolPath, candidate)
            if os.path.exists(path):
                return path

        return None

    def resolvePostgresqlProtocolLogPaths(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            resolveScipionProtocolIdCallback: Callable,
            resolvePostgresqlProjectPathForFilesystemCallback: Callable,
    ) -> Optional[Dict[str, Any]]:
        if mapper is None:
            return None

        try:
            scipionProtocolId = resolveScipionProtocolIdCallback(
                mapper=mapper,
                projectId=projectId,
                protocolId=protocolId,
            )

        except Exception:
            logger.debug(
                "Could not resolve PostgreSQL protocol id for logs. projectId=%s protocolId=%s",
                projectId,
                protocolId,
                exc_info=True,
            )
            return None

        protocolPath = self.resolvePostgresqlProtocolRunPath(
            mapper=mapper,
            projectId=projectId,
            scipionProtocolId=scipionProtocolId,
            resolvePostgresqlProjectPathForFilesystemCallback=(
                resolvePostgresqlProjectPathForFilesystemCallback
            ),
        )

        if not protocolPath:
            return None

        logCandidates = {
            "stdout": [
                "logs/run.stdout",
                "logs/stdout.log",
                "logs/stdout.txt",
                "run.stdout",
                "stdout.log",
                "stdout.txt",
            ],
            "stderr": [
                "logs/run.stderr",
                "logs/stderr.log",
                "logs/stderr.txt",
                "run.stderr",
                "stderr.log",
                "stderr.txt",
            ],
            "schedule": [
                "logs/schedule.log",
                "logs/schedule.txt",
                "logs/run.schedule",
                "schedule.log",
                "schedule.txt",
                "run.schedule",
            ],
        }

        paths = {
            channelId: self.firstExistingLogPath(protocolPath, candidates)
            for channelId, candidates in logCandidates.items()
        }

        # If we cannot find any known log file, do not guess. Let runtime fallback
        # resolve the exact Scipion log paths.
        if not any(paths.values()):
            return None

        return {
            "protocolId": scipionProtocolId,
            "protocolPath": protocolPath,
            "paths": paths,
        }

    @staticmethod
    def buildProtocolLogChannel(
            channelId: str,
            label: str,
            order: int,
            filePath: Optional[str],
    ) -> Dict[str, Any]:
        return {
            "id": channelId,
            "label": label,
            "order": order,
        }

    def buildProtocolLogChannelsPayload(
            self,
            *,
            projectId: int,
            protocolId: Union[int, str],
            logPaths: Dict[str, Optional[str]],
    ) -> Dict[str, Any]:
        return {
            "projectId": projectId,
            "protocolId": int(protocolId),
            "channels": [
                self.buildProtocolLogChannel("stdout", "Output", 1, logPaths.get("stdout")),
                self.buildProtocolLogChannel("stderr", "Errors", 2, logPaths.get("stderr")),
                self.buildProtocolLogChannel("schedule", "Schedule", 3, logPaths.get("schedule")),
            ],
        }

    @staticmethod
    def normalizeProtocolLogOffsets(rawOffsets: Dict[str, int]) -> Dict[str, int]:
        if not isinstance(rawOffsets, dict):
            return {"stdout": 0, "stderr": 0, "schedule": 0}

        keyMap = {
            "stdout": "stdout",
            "stdoutLog": "stdout",
            "out": "stdout",
            "stderr": "stderr",
            "stderrLog": "stderr",
            "err": "stderr",
            "schedule": "schedule",
            "scheduleLog": "schedule",
        }

        normalized = {"stdout": 0, "stderr": 0, "schedule": 0}

        for key, value in rawOffsets.items():
            canonical = keyMap.get(str(key), None)

            if canonical is None:
                continue

            try:
                normalized[canonical] = max(0, int(value))
            except Exception:
                normalized[canonical] = 0

        return normalized

    @staticmethod
    def readProtocolLogChunk(
            filePath: Optional[str],
            startOffset: int,
            maxBytes: Optional[int] = 65536,
            maxLines: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        if not filePath or not os.path.exists(filePath):
            return {
                "content": "",
                "offset": int(startOffset or 0),
            }

        try:
            sizeBytes = int(os.path.getsize(filePath))
        except Exception:
            sizeBytes = 0

        safeOffset = int(startOffset or 0)

        if safeOffset < 0:
            safeOffset = 0

        if safeOffset > sizeBytes:
            safeOffset = 0

        bytesCap = None if maxBytes is None else max(1, int(maxBytes))
        linesCap = None if maxLines is None else max(1, int(maxLines))

        contentParts: List[str] = []
        bytesRead = 0
        linesRead = 0

        try:
            with open(filePath, "rb") as handle:
                handle.seek(safeOffset)

                while True:
                    if linesCap is not None and linesRead >= linesCap:
                        break

                    if bytesCap is not None and bytesRead >= bytesCap:
                        break

                    posBefore = handle.tell()
                    lineBytes = handle.readline()

                    if not lineBytes:
                        break

                    if bytesCap is not None and (bytesRead + len(lineBytes)) > bytesCap:
                        handle.seek(posBefore)
                        break

                    contentParts.append(lineBytes.decode("utf-8", errors="ignore"))
                    bytesRead += len(lineBytes)
                    linesRead += 1

                newOffset = handle.tell()

        except Exception as e:
            return {
                "content": "",
                "offset": safeOffset,
                "error": str(e),
            }

        return {
            "content": "".join(contentParts),
            "offset": int(newOffset),
        }

    def pollProtocolLogPaths(
            self,
            *,
            projectId: int,
            protocolId: Union[int, str],
            logPaths: Dict[str, Optional[str]],
            offsets: Dict[str, int],
            maxBytes: Optional[int] = 65536,
            maxLines: Optional[int] = 2000,
    ) -> Dict[str, Any]:
        normalizedOffsets = self.normalizeProtocolLogOffsets(offsets or {})

        return {
            "projectId": projectId,
            "protocolId": int(protocolId),
            "channels": {
                "stdout": self.readProtocolLogChunk(
                    logPaths.get("stdout"),
                    normalizedOffsets.get("stdout", 0),
                    maxBytes=maxBytes,
                    maxLines=maxLines,
                ),
                "stderr": self.readProtocolLogChunk(
                    logPaths.get("stderr"),
                    normalizedOffsets.get("stderr", 0),
                    maxBytes=maxBytes,
                    maxLines=maxLines,
                ),
                "schedule": self.readProtocolLogChunk(
                    logPaths.get("schedule"),
                    normalizedOffsets.get("schedule", 0),
                    maxBytes=maxBytes,
                    maxLines=maxLines,
                ),
            },
        }

    def ensureRuntimeProjectForLogs(
            self,
            *,
            currentProject,
            mapper,
            projectId: int,
            currentUser: Optional[dict],
            getProjectByIdCallback: Callable,
    ) -> None:
        if currentProject is not None:
            return

        if currentUser is None:
            return

        getProjectByIdCallback(
            mapper,
            projectId,
            currentUser,
            refresh=False,
            checkPid=False,
        )

    def listProtocolLogChannels(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            currentProject,
            currentUser: Optional[dict],
            resolveScipionProtocolIdCallback: Callable,
            resolvePostgresqlProjectPathForFilesystemCallback: Callable,
            getProjectByIdCallback: Callable,
            getProtocolByRuntimeIdCallback: Callable,
    ) -> Dict[str, Any]:
        pgLogs = self.resolvePostgresqlProtocolLogPaths(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            resolveScipionProtocolIdCallback=resolveScipionProtocolIdCallback,
            resolvePostgresqlProjectPathForFilesystemCallback=(
                resolvePostgresqlProjectPathForFilesystemCallback
            ),
        )

        if pgLogs is not None:
            return self.buildProtocolLogChannelsPayload(
                projectId=projectId,
                protocolId=pgLogs["protocolId"],
                logPaths=pgLogs["paths"],
            )

        self.ensureRuntimeProjectForLogs(
            currentProject=currentProject,
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            getProjectByIdCallback=getProjectByIdCallback,
        )

        scipionProtocolId = resolveScipionProtocolIdCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = getProtocolByRuntimeIdCallback(scipionProtocolId)

        stdoutPath = protocol.getStdoutLog() if hasattr(protocol, "getStdoutLog") else None
        stderrPath = protocol.getStderrLog() if hasattr(protocol, "getStderrLog") else None
        schedulePath = protocol.getScheduleLog() if hasattr(protocol, "getScheduleLog") else None

        return self.buildProtocolLogChannelsPayload(
            projectId=projectId,
            protocolId=scipionProtocolId,
            logPaths={
                "stdout": stdoutPath,
                "stderr": stderrPath,
                "schedule": schedulePath,
            },
        )

    def pollProtocolLogs(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            offsets: Dict[str, int],
            maxBytes: Optional[int],
            maxLines: Optional[int],
            currentProject,
            currentUser: Optional[dict],
            resolveScipionProtocolIdCallback: Callable,
            resolvePostgresqlProjectPathForFilesystemCallback: Callable,
            getProjectByIdCallback: Callable,
            getProtocolByRuntimeIdCallback: Callable,
    ) -> Dict[str, Any]:
        pgLogs = self.resolvePostgresqlProtocolLogPaths(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
            resolveScipionProtocolIdCallback=resolveScipionProtocolIdCallback,
            resolvePostgresqlProjectPathForFilesystemCallback=(
                resolvePostgresqlProjectPathForFilesystemCallback
            ),
        )

        if pgLogs is not None:
            return self.pollProtocolLogPaths(
                projectId=projectId,
                protocolId=pgLogs["protocolId"],
                logPaths=pgLogs["paths"],
                offsets=offsets,
                maxBytes=maxBytes,
                maxLines=maxLines,
            )

        self.ensureRuntimeProjectForLogs(
            currentProject=currentProject,
            mapper=mapper,
            projectId=projectId,
            currentUser=currentUser,
            getProjectByIdCallback=getProjectByIdCallback,
        )

        scipionProtocolId = resolveScipionProtocolIdCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = getProtocolByRuntimeIdCallback(scipionProtocolId)

        stdoutPath = protocol.getStdoutLog() if hasattr(protocol, "getStdoutLog") else None
        stderrPath = protocol.getStderrLog() if hasattr(protocol, "getStderrLog") else None
        schedulePath = protocol.getScheduleLog() if hasattr(protocol, "getScheduleLog") else None

        return self.pollProtocolLogPaths(
            projectId=projectId,
            protocolId=scipionProtocolId,
            logPaths={
                "stdout": stdoutPath,
                "stderr": stderrPath,
                "schedule": schedulePath,
            },
            offsets=offsets,
            maxBytes=maxBytes,
            maxLines=maxLines,
        )

    def getProtocolLogs(
            self,
            *,
            mapper,
            projectId: int,
            protocolId: int,
            offset: int = 0,
            errOffset: int = 0,
            scheduleOffset: int = 0,
            resolveScipionProtocolIdCallback: Callable,
            getProtocolByRuntimeIdCallback: Callable,
    ) -> Dict[str, Any]:
        scipionProtocolId = resolveScipionProtocolIdCallback(
            mapper=mapper,
            projectId=projectId,
            protocolId=protocolId,
        )

        protocol = getProtocolByRuntimeIdCallback(scipionProtocolId)

        logPath = protocol.getStdoutLog()
        errLogPath = protocol.getStderrLog()
        scheduleLogPath = protocol.getScheduleLog()

        offset = self._normalizeSingleOffset(offset, logPath)
        errOffset = self._normalizeSingleOffset(errOffset, errLogPath)
        scheduleOffset = self._normalizeSingleOffset(scheduleOffset, scheduleLogPath)

        stdoutContent, stderrContent, scheduleContent = "", "", ""
        newOffsetOut, newOffsetErr, newOffsetSchedule = offset, errOffset, scheduleOffset

        if logPath and os.path.exists(logPath):
            with open(logPath, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(offset)
                stdoutContent = handle.read()
                newOffsetOut = handle.tell()

        if errLogPath and os.path.exists(errLogPath):
            with open(errLogPath, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(errOffset)
                stderrContent = handle.read()
                newOffsetErr = handle.tell()

        if scheduleLogPath and os.path.exists(scheduleLogPath):
            with open(scheduleLogPath, "r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(scheduleOffset)
                scheduleContent = handle.read()
                newOffsetSchedule = handle.tell()

        if (
                not stdoutContent
                and not stderrContent
                and not scheduleContent
                and not (logPath and os.path.exists(logPath))
                and not (errLogPath and os.path.exists(errLogPath))
                and not (scheduleLogPath and os.path.exists(scheduleLogPath))
        ):
            raise HTTPException(status_code=404, detail="No logs found")

        return {
            "stdoutLog": stdoutContent,
            "stderrLog": stderrContent,
            "stdoutOffset": newOffsetOut,
            "stderrOffset": newOffsetErr,
            "scheduleLog": scheduleContent,
            "scheduleOffset": newOffsetSchedule,
        }

    @staticmethod
    def _normalizeSingleOffset(value, filePath):
        safeOffset = max(0, int(value or 0))

        if filePath and os.path.exists(filePath):
            try:
                fileSize = os.path.getsize(filePath)
                if safeOffset > fileSize:
                    return 0
            except Exception:
                pass

        return safeOffset