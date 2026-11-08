"""A facility's settings: what is its own way (see facility_conventions) and its policies, with defaults.

The policies are what the CNB's facility does, a default any facility can change: who owns a DATA's project
and how its user and group see it, how far a detector's calibration may be from EPU's pixel, when a DATA is
taken for stalled, and how often the watcher looks at the folders.
"""
import os
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services import facility_conventions as conventions
from app.backend.mapper.facility_settings_mapper import FacilitySettingsPostgresqlMapper

DEFAULTS = {
    "sessionNamePattern": conventions.DEFAULT_SESSION_NAME_PATTERN,
    # How long the facility keeps a session's data once it finished (0: not said), told to its users
    "rawRetentionDays": 0,
    "processedRetentionDays": 0,
    # The days before a session's data go when its user (and the group's PI) are mailed a notice
    "retentionNoticeDays": [30, 7, 1],
    # How the users take their data home (iRODS, rsync, a disk...), shown in their sessions
    "downloadInstructions": "",
    # Policies. Who owns a DATA's project: the staff who made the session (the user and group see it at
    # projectShareLevel), or the session's user (the staff who made it manage it)
    "projectOwner": "staff",
    "projectShareLevel": "view",
    # A detector's calibration further than this from EPU's nominal pixel is not used
    "calibrationTolerancePercent": 10.0,
    # A DATA acquiring with no new movie for this long is stalled (an alert)
    "stallMinutes": 20,
    # How often the watcher looks at the sessions' folders
    "watchSeconds": int(os.environ.get("SCIPIONWEB_FACILITY_WATCH_SECONDS") or 30),
    # The CTF limits a new session starts with (the CNB's: defocus 5000-40000 A, CTF resolution 8 A)
    "ctfMinDefocus": 5000.0,
    "ctfMaxDefocus": 40000.0,
    "ctfMaxResolution": 8.0,
    # Where the facility is: the day a booking starts on (its session's day) is the day there
    "timezone": "Europe/Madrid",
    # Who is mailed the alerts: these addresses, else every user who runs sessions (as each chose)
    "alertRecipients": "",
}
TEXT_LIMIT = 5000
MAX_RETENTION_DAYS = 36500
MAX_NOTICES = 5
# How each setting is checked: ("int" | "number", lowest, highest), ("choice", options) or ("text", length)
RULES = {
    "sessionNamePattern": ("text", conventions.PATTERN_LIMIT),
    "rawRetentionDays": ("int", 0, MAX_RETENTION_DAYS),
    "processedRetentionDays": ("int", 0, MAX_RETENTION_DAYS),
    "retentionNoticeDays": ("days", 1, 365),
    "downloadInstructions": ("text", TEXT_LIMIT),
    "projectOwner": ("choice", ("staff", "user")),
    "projectShareLevel": ("choice", ("view", "work")),
    "calibrationTolerancePercent": ("number", 0.5, 50),
    "stallMinutes": ("int", 2, 1440),
    "watchSeconds": ("int", 5, 3600),
    "ctfMinDefocus": ("number", 0, 1e6),
    "ctfMaxDefocus": ("number", 1, 1e6),
    "ctfMaxResolution": ("number", 0.5, 100),
    "timezone": ("text", 64),
    "alertRecipients": ("text", TEXT_LIMIT),
}


def _badRequest(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)


def noticeDays(value: Any, lowest: int = 1, highest: int = 365) -> List[int]:
    """Days before a date, from a list or a text like "30, 7, 1": each once, the furthest first."""
    parts = value if isinstance(value, (list, tuple)) else str(value or "").replace(";", ",").split(",")
    days = set()
    for part in parts:
        if str(part).strip() == "":
            continue
        try:
            day = int(str(part).strip())
        except ValueError:
            raise _badRequest("The notice days are whole numbers separated by commas")
        if not lowest <= day <= highest:
            raise _badRequest("A notice goes %d to %d days before" % (lowest, highest))
        days.add(day)
    if len(days) > MAX_NOTICES:
        raise _badRequest("Up to %d notices" % MAX_NOTICES)
    return sorted(days, reverse=True)


class FacilitySettingsService:
    def __init__(self, db):
        self.mapper = FacilitySettingsPostgresqlMapper(db)

    def values(self) -> Dict[str, Any]:
        """The facility's settings over the defaults (what the watcher and the processing read every turn)."""
        return dict(DEFAULTS, **{key: value for key, value in self.mapper.getSettings().items() if key in DEFAULTS})

    def getSettings(self) -> Dict[str, Any]:
        """The facility's settings over the defaults, with what they make and the presets there are."""
        settings = self.values()
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
        values: Dict[str, Any] = {}
        for key, rule in RULES.items():
            if payload.get(key) is None:
                continue
            kind = rule[0]
            if kind in ("int", "number"):
                try:
                    values[key] = int(payload[key]) if kind == "int" else float(payload[key])
                except (TypeError, ValueError):
                    raise _badRequest("%s is a number" % key)
                if not rule[1] <= values[key] <= rule[2]:
                    raise _badRequest("%s is %s to %s" % (key, rule[1], rule[2]))
            elif kind == "days":
                values[key] = noticeDays(payload[key], rule[1], rule[2])
            elif kind == "choice":
                values[key] = str(payload[key])
                if values[key] not in rule[1]:
                    raise _badRequest("%s is one of %s" % (key, ", ".join(rule[1])))
            else:
                values[key] = str(payload[key]).strip()
                if len(values[key]) > rule[1]:
                    raise _badRequest("%s is up to %d characters" % (key, rule[1]))
        if "sessionNamePattern" in values:
            if not values["sessionNamePattern"]:
                raise _badRequest("The session name pattern is empty")
            self.preview({"sessionNamePattern": values["sessionNamePattern"]})
        if "alertRecipients" in values:
            from app.backend.api.services.mail_service import addresses

            listed = addresses(values["alertRecipients"])
            if any("@" not in address for address in listed):
                raise _badRequest("The alert recipients are mail addresses, separated by commas")
            values["alertRecipients"] = ", ".join(listed)
        if "timezone" in values:
            from app.backend.mapper.facility_booking_mapper import FacilityBookingPostgresqlMapper

            if not FacilityBookingPostgresqlMapper(self.mapper.db).timezoneExists(values["timezone"]):
                raise _badRequest("Unknown time zone: %s (written as Europe/Madrid)" % values["timezone"])
        self.mapper.saveSettings(values, userId)
        return self.getSettings()

    def sessionNamePattern(self) -> str:
        return self.values()["sessionNamePattern"]
