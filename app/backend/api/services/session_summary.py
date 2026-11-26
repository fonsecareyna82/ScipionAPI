"""What the AI assistant is told about a finished acquisition session, to summarize it in the session's notice.

Only numbers and names of things: the session, the microscope, its dates, its DATA folders and, for each one
processed, its streaming monitor in a few figures (movies, the CTF of the micrographs against the thresholds, the
dose, the particles picked, how far each stage got). Never who the people are.
"""
import logging
import statistics
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _when(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _stats(values: List[float]) -> Optional[Dict[str, float]]:
    values = sorted(value for value in values if isinstance(value, (int, float)))
    if not values:
        return None
    pick = lambda share: values[min(len(values) - 1, int(share * (len(values) - 1) + 0.5))]  # noqa: E731
    return {"count": len(values), "median": round(statistics.median(values), 2), "p10": round(pick(0.1), 2),
            "p90": round(pick(0.9), 2), "min": round(values[0], 2), "max": round(values[-1], 2)}


def monitorFigures(monitor: Dict[str, Any]) -> Dict[str, Any]:
    """The streaming monitor of a project in a few figures."""
    flow = monitor.get("flow") or {}
    thresholds = {key: value for key, value in (monitor.get("thresholds") or {}).items() if value is not None}
    points = ((monitor.get("series") or {}).get("points")) or []
    ctf = [point for point in points if not point.get("failed")]
    alerts: Dict[str, int] = {}
    for point in points:
        for alert in point.get("alerts") or []:
            alerts[alert] = alerts.get(alert, 0) + 1
    dosePoints = ((monitor.get("dose") or {}).get("points")) or []
    counts = list((((monitor.get("picking") or {}).get("counts")) or {}).values())
    return {
        "acquisition": {"items": flow.get("items"), "unit": flow.get("unit"), "state": flow.get("acquisition"),
                        "lastItemAt": _when(flow.get("lastItemAt")), "stalled": bool(flow.get("stalled"))},
        "stages": [{"stage": stage.get("stage"), "protocol": stage.get("label"), "status": stage.get("status"),
                    "items": stage.get("items"), "behind": stage.get("behind")}
                   for stage in monitor.get("stages") or []],
        "thresholds": thresholds,
        "ctf": {"micrographs": len(points), "failedFits": len(points) - len(ctf),
                "resolutionA": _stats([point.get("resolution") for point in ctf]),
                "defocusA": _stats([((point.get("defocusU") or 0) + (point.get("defocusV") or 0)) / 2
                                    for point in ctf if point.get("defocusU") is not None]),
                "astigmatismA": _stats([point.get("astigmatism") for point in ctf]),
                "totalDrift": _stats([point.get("totalDrift") for point in ctf]),
                "beyondThresholds": alerts} if points else None,
        "dose": {"movies": len(dosePoints), "meanDose": _stats([point.get("meanDose") for point in dosePoints]),
                 "discarded": sum(1 for point in dosePoints if point.get("discarded"))} if dosePoints else None,
        "particles": {"micrographs": len(counts), "total": sum(counts), "perMicrograph": _stats(counts),
                      "boxSize": (monitor.get("picking") or {}).get("boxSize")} if counts else None,
        "classes2D": len(monitor.get("classesOutputs") or []),
    }


def sessionData(db, sessionId: int) -> Dict[str, Any]:
    from app.backend.api.services.facility_session_service import FacilitySessionService
    from app.backend.api.services.streaming_monitor import streamingMonitor
    from app.backend.database import getMapper

    session = FacilitySessionService(db).getSession(int(sessionId))
    folders = []
    for dataset in session.get("datasets") or []:
        folder = {"kind": dataset.get("kind"), "number": dataset.get("number"),
                  "detector": dataset.get("detectorName"), "movies": dataset.get("movieCount"),
                  "movieGigabytes": round((dataset.get("movieBytes") or 0) / 1e9, 1),
                  "firstMovieAt": _when(dataset.get("firstMovieAt")), "lastMovieAt": _when(dataset.get("lastMovieAt")),
                  "processing": (dataset.get("processing") or {}).get("state")
                  if isinstance(dataset.get("processing"), dict) else dataset.get("processing")}
        if dataset.get("projectId"):
            mapper = getMapper()
            try:
                folder["processed"] = monitorFigures(streamingMonitor(mapper, int(dataset["projectId"])))
            except Exception:
                logger.warning("Could not read the monitor of project %s", dataset["projectId"], exc_info=True)
            finally:
                try:
                    mapper.db.close()
                except Exception:
                    pass
        folders.append(folder)
    return {"session": session.get("name"), "technique": session.get("technique"),
            "microscope": session.get("microscopeName"), "startedAt": _when(session.get("startedAt")),
            "finishedAt": _when(session.get("finishedAt")), "template": session.get("templateId"),
            "ctfLimits": {"minDefocus": session.get("ctfMinDefocus"), "maxDefocus": session.get("ctfMaxDefocus"),
                          "maxResolution": session.get("ctfMaxResolution")},
            "folders": folders}
