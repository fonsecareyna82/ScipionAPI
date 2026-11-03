"""The queries of a facility's settings: its own choices (conventions, later its policies), one row each."""
import json
from typing import Any, Dict, Optional

SAVE_SETTING_SQL = """
    INSERT INTO facility_settings (key, value, "updatedBy") VALUES (%s, %s::JSONB, %s)
    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, "updatedBy" = EXCLUDED."updatedBy", "updatedAt" = NOW()
"""


class FacilitySettingsPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def getSettings(self) -> Dict[str, Any]:
        return {row["key"]: row["value"] for row in self.db.fetchAll("SELECT key, value FROM facility_settings") or []}

    def saveSettings(self, values: Dict[str, Any], userId: Optional[int]) -> None:
        with self.db.transaction():
            for key, value in values.items():
                self.db.execute(SAVE_SETTING_SQL, (key, json.dumps(value), userId), commit=False)
