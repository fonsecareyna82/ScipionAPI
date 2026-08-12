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
from pathlib import Path
from typing import Any, Optional
from app.backend.runtime.project_runtime_repository import ProjectRuntimeRepository


class PostgresqlProjectPathResolver:
    def __init__(self, db, projectId: int):
        self.db = db
        self.projectId = int(projectId)
        self.projectRuntimeRepository = ProjectRuntimeRepository()
        self._projectPath: Optional[Path] = None
        self._projectPathLoaded = False

    def getProjectPath(self) -> Optional[Path]:
        if self._projectPathLoaded:
            return self._projectPath

        self._projectPathLoaded = True

        try:
            rawPath = self.projectRuntimeRepository.getProjectNameByDatabase(db=self.db, projectId=self.projectId)
        except Exception:
            self._projectPath = None
            return None

        if not rawPath:
            self._projectPath = None
            return None

        try:
            self._projectPath = Path(str(rawPath)).expanduser()
        except Exception:
            self._projectPath = None

        return self._projectPath

    def resolveExistingPath(self, fileName: Any) -> Optional[str]:
        text = str(fileName or "").strip()
        if not text:
            return None

        path = Path(text).expanduser()
        candidates = []

        if path.is_absolute():
            candidates.append(path)
        else:
            projectPath = self.getProjectPath()
            if projectPath is not None:
                candidates.append(projectPath / path)

            # Some legacy Scipion objects may store external files
            # relative to the user's home directory.
            candidates.append(Path.home() / path)

            candidates.append(path)
            candidates.append(Path.cwd() / path)

        seen = set()

        for candidate in candidates:
            try:
                candidateKey = str(candidate)
                if candidateKey in seen:
                    continue
                seen.add(candidateKey)

                resolved = candidate.resolve()
                if resolved.exists():
                    return str(resolved)
            except Exception:
                continue

        return None