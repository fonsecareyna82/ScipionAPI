"""Volumes given as project files rather than as a stored protocol output.

Protocol viewers often hand volume files to ChimeraX. On the web they are
shown in the volume viewer through a signed viewer file token; this reader
offers those files with the same interface as the stored-output reader.
"""
import os
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.backend.viewers.postgresql_volume_reader import PostgresqlVolumeReader


class ViewerFileVolumeReader(PostgresqlVolumeReader):
    """Read-only volumes from (absolute path, project-relative path) pairs."""

    def __init__(self, files: Sequence[Tuple[str, str]]):
        # The stored-output state of the parent class is not used here.
        self.lastSkipReason = None
        self._files = list(files)
        self._volumes = None

    def hasOutput(self) -> bool:
        return bool(self._files)

    def listVolumes(self) -> Optional[List[Dict[str, Any]]]:
        self.lastSkipReason = None
        if self._volumes is None:
            self._volumes = []
            for index, (absolute, relative) in enumerate(self._files):
                name = os.path.basename(relative)
                self._volumes.append({
                    "id": index,
                    "index": index,
                    "name": name,
                    "label": name,
                    "relPath": relative,
                    "fileName": absolute,
                    "path": absolute,
                })
        return self._volumes or None

    def _resolveExistingPath(self, fileName: Any) -> Optional[str]:
        known = {absolute for absolute, _ in self._files}
        return fileName if fileName in known and os.path.isfile(fileName) else None
