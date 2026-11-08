"""The facility's alerts: what went wrong in its sessions, for the operators to know at once.

Every turn of the watcher (``refresh``) opens an alert for what is wrong now and resolves the ones whose cause
is over:

* stalled: a DATA acquiring had no new movie for the facility's ``stallMinutes``;
* processingFailed: its project could not be made or launched;
* protocolFailed: a protocol of its project failed.

An alert is never opened twice while open. The new ones are told together (``notifyNew``): mailed to the facility's
alert addresses, else noticed to the users who run sessions (the bell, and their mail as each chose); the web
shows the open ones to the staff until resolved.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.mapper.facility_alerts_mapper import FacilityAlertsPostgresqlMapper

logger = logging.getLogger(__name__)

KINDS = ("stalled", "processingFailed", "protocolFailed")
# An alert older than this is not told any more: it was seen in the web already
MAIL_WITHIN_MINUTES = 60


def alertMessage(kind: str, problem: Dict[str, Any]) -> str:
    where = "%s (session %s, %s)" % (problem["folder"], problem["sessionName"], problem["microscopeName"])
    if kind == "stalled":
        return "%s has had no new movie for %d minutes (%d movies so far)." % (
            where, int(problem.get("minutes") or 0), int(problem.get("movieCount") or 0))
    if kind == "processingFailed":
        return "%s: its project could not be made: %s" % (where, problem.get("detail") or "see the session")
    return "%s: protocol %s (%s) failed in its project." % (where, problem.get("protocolId"), problem.get("detail") or "")


class FacilityAlerts:
    def __init__(self, db):
        self.mapper = FacilityAlertsPostgresqlMapper(db)

    def refresh(self, stallMinutes: Optional[float] = None) -> List[int]:
        """Open the alerts of what is wrong now and resolve the others; answers the ids opened."""
        if stallMinutes is None:
            stallMinutes = float(FacilitySettingsService(self.mapper.db).values()["stallMinutes"])
        opened = []
        for kind in KINDS:
            problems = self.mapper.currentProblems(kind, stallMinutes)
            for problem in problems:
                alertId = self.mapper.openAlert(kind, problem, alertMessage(kind, problem))
                if alertId is not None:
                    opened.append(alertId)
            self.mapper.resolveGone(kind, [(problem["datasetId"], problem["protocolId"]) for problem in problems])
        return opened

    def notifyNew(self) -> Optional[Dict[str, Any]]:
        """Tell of the alerts not told yet, in one notice: mailed to the facility's alert addresses, else to the
        users who run sessions (in the web and by mail, as each chose); answers to whom (None: nothing new)."""
        from app.backend.api.services.mail_service import addresses
        from app.backend.api.services.notifications import Notifications

        alerts = self.mapper.alertsToMail(MAIL_WITHIN_MINUTES)
        if not alerts:
            return None
        ids = [int(alert["id"]) for alert in alerts]
        lines = ["- %s" % alert["message"] for alert in alerts]
        title = "Facility: %d new alert%s" % (len(alerts), "" if len(alerts) == 1 else "s")
        body = ("What went wrong in the facility's sessions:\n\n%s\n\nSay who is on it in the Facility pages."
                % "\n".join(lines))
        notifications = Notifications(self.mapper.db)
        listed = addresses(FacilitySettingsService(self.mapper.db).values().get("alertRecipients"))
        if listed:
            notifications.notifyAddresses(listed, "facility.alert", title, body, "/facility/sessions")
            told = {"addresses": listed}
        else:
            userIds = [int(user["id"]) for user in self.mapper.usersWithPermission("facility.sessions")]
            notifications.notify(userIds, "facility.alert", title, body, "/facility/sessions")
            told = {"users": userIds}
        self.mapper.markMailed(ids)
        return told

    def listAlerts(self, openOnly: bool = True) -> List[Dict[str, Any]]:
        return self.mapper.listAlerts(openOnly)

    def acknowledge(self, alertId: int, userId: Optional[int]) -> Dict[str, Any]:
        """Someone is on it: the alert keeps who and when (the first one to say so)."""
        if self.mapper.getAlert(alertId) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        self.mapper.acknowledge(alertId, userId)
        return self.mapper.getAlert(alertId)
