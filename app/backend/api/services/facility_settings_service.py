"""A facility's settings: what is its own way (see facility_conventions), with neutral defaults."""
from typing import Any, Dict, Optional

from fastapi import HTTPException, status

from app.backend.api.services import facility_conventions as conventions
from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

DEFAULTS = {"sessionNamePattern": conventions.DEFAULT_SESSION_NAME_PATTERN}


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


class FacilitySettingsService:
    def __init__(self, db):
        self.mapper = FacilitySettingsPostgresqlMapper(db)

    def getSettings(self) -> Dict[str, Any]:
        """The facility's settings over the defaults, with what they make and the presets there are."""
        settings = dict(DEFAULTS, **{key: value for key, value in self.mapper.getSettings().items() if key in DEFAULTS})
        return {"settings": settings, "defaults": DEFAULTS, "examples": self.preview(settings),
                "presets": [{"id": presetId, "label": preset["label"], "settings": preset["settings"],
                             "microscope": preset["microscope"]} for presetId, preset in conventions.PRESETS.items()]}

    def preview(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """What the given patterns make for an example session; 400 for a wrong one."""
        try:
            return conventions.examples(
                payload.get("sessionNamePattern") or DEFAULTS["sessionNamePattern"],
                payload.get("dataFolderPattern") or conventions.DEFAULT_DATA_FOLDER_PATTERN,
                payload.get("atlasFolderPattern") if payload.get("atlasFolderPattern") is not None
                else conventions.DEFAULT_ATLAS_FOLDER_PATTERN,
                conventions.nameWord(payload.get("microscopeCode")) or "KRIOS")
        except ValueError as error:
            raise _badRequest(str(error))

    def saveSettings(self, payload: Dict[str, Any], userId: Optional[int] = None) -> Dict[str, Any]:
        values = {key: str(payload[key]).strip() for key in DEFAULTS if payload.get(key) is not None}
        if "sessionNamePattern" in values:
            self.preview({"sessionNamePattern": values["sessionNamePattern"]})
        self.mapper.saveSettings(values, userId)
        return self.getSettings()

    def sessionNamePattern(self) -> str:
        return self.getSettings()["settings"]["sessionNamePattern"]
