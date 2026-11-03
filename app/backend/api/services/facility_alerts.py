"""The facility's alerts: what went wrong in its sessions, for the operators to know at once.

Every turn of the watcher (``refresh``) opens an alert for what is wrong now and resolves the ones whose cause
is over:

* stalled: a DATA acquiring had no new movie for the facility's ``stallMinutes``;
* processingFailed: its project could not be made or launched;
* protocolFailed: a protocol of its project failed.

An alert is never opened twice while open. The new ones are mailed to the operators together (``mailNew``)
when the facility has a mail server; the web shows the open ones to the staff until resolved.
"""
import logging
from typing import Any, Dict, List, Optional

from fastapi import HTTPException, status

from app.backend.api.services.facility_mail import FacilityMail
from app.backend.api.services.facility_settings_service import FacilitySettingsService
from app.backend.mapper.facility_alerts_mapper import FacilityAlertsPostgresqlMapper

logger = logging.getLogger(__name__)

KINDS = ("stalled", "processingFailed", "protocolFailed")
# An alert older than this when the mail server is set is not mailed: it was seen in the web already
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
        self.mail = FacilityMail(db)

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

    def mailNew(self) -> Optional[List[str]]:
        """Mail the alerts not mailed yet, in one mail; answers to whom (None: nothing was sent)."""
        if not self.mail.getSettings()["enabled"]:
            return None
        alerts = self.mapper.alertsToMail(MAIL_WITHIN_MINUTES)
        if not alerts:
            return None
        ids = [int(alert["id"]) for alert in alerts]
        lines = ["- %s" % alert["message"] for alert in alerts]
        subject = "ScipionWeb facility: %d new alert%s" % (len(alerts), "" if len(alerts) == 1 else "s")
        body = ("What went wrong in the facility's sessions:\n\n%s\n\nOpen the Facility page of ScipionWeb to see "
                "them and say who is on it.\n" % "\n".join(lines))
        try:
            sent = self.mail.send(subject, body)
        except RuntimeError as error:
            logger.warning("Could not mail the facility's alerts: %s", error)
            self.mapper.markMailed(ids, str(error))
            return None
        self.mapper.markMailed(ids)
        return sent

    def listAlerts(self, openOnly: bool = True) -> List[Dict[str, Any]]:
        return self.mapper.listAlerts(openOnly)

    def acknowledge(self, alertId: int, userId: Optional[int]) -> Dict[str, Any]:
        """Someone is on it: the alert keeps who and when (the first one to say so)."""
        if self.mapper.getAlert(alertId) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Alert not found")
        self.mapper.acknowledge(alertId, userId)
        return self.mapper.getAlert(alertId)
