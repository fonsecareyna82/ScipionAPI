"""Validating that a filesystem folder is a real, loadable Scipion
project, for the "import an existing project" flow.
"""
import logging
from pathlib import Path
from typing import Any, Dict

import pyworkflow
from fastapi import HTTPException, status
from pyworkflow.project import Project as ScipionProject

logger = logging.getLogger(__name__)


def validateImportableScipionProject(sourcePath: Path) -> Dict[str, Any]:
    """
    Validate that a folder is a real Scipion project by trying to load it.

    Returns a small metadata dict that can be reused by importProject.
    """
    if sourcePath is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid source project path",
        )

    if not sourcePath.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Source project path does not exist",
        )

    if not sourcePath.is_dir():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Source project path must be a directory",
        )

    importedProject = None

    try:
        importedProject = ScipionProject(
            pyworkflow.Config.getDomain(),
            str(sourcePath),
        )
        importedProject.load(
            dbPath=importedProject.getDbPath()
        )

        try:
            description = importedProject.getComment() or ""
        except Exception:
            description = ""

        try:
            importedStatus = importedProject.getStatus()
            statusValue = str(importedStatus) if importedStatus else "active"
        except Exception:
            statusValue = "active"

        return {
            "description": description,
            "status": statusValue or "active",
        }

    except HTTPException:
        raise

    except Exception as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Source path is not a valid Scipion project: {error}",
        ) from error

    finally:
        if importedProject is not None:
            try:
                importedProject.closeMapper()
            except Exception:
                logger.debug(
                    "Could not close source project mapper after validation. "
                    "path=%s",
                    sourcePath,
                    exc_info=True,
                )
