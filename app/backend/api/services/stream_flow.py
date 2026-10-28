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
"""Whether a stream flows: the acquisition goes on, paused or finished, and which stages stopped.

The import of a stream decides itself when the acquisition is over: it closes its Set once its timeout
passes with no new files, or when it is told to stop. So a closed import is a finished acquisition, never a
stopped microscope. While it is open, minutes with nothing new (movies; the tilts of a tilt series) are a
pause (the microscope or its software may have stopped), and the import says how long it still waits. A stage with items waiting that
gives nothing for a while is stalled, finished acquisition or not.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

LIVE_PROTOCOL_STATUSES = ("launched", "running", "scheduled")
# Made in rounds: their rows are classes, and a round can take long with nothing wrong
UNWATCHED_STAGES = ("classes2d",)


_DURATION_PART = re.compile(r"(\d+(?:\.\d+)?)\s*([dhms]?)")
_DURATION_UNIT = {"d": 86400, "h": 3600, "m": 60, "s": 1, "": 1}


def durationSeconds(text: Optional[str]) -> Optional[float]:
    """The seconds of a duration as Scipion writes them ("12h", "1m 10s", "30"), or None.

    Read here and not with pyworkflow's strToDuration, which evaluates the text it is given.
    """
    value = str(text or "").strip().lower()
    if not value:
        return None
    parts = _DURATION_PART.findall(value)
    if not parts or _DURATION_PART.sub("", value).strip():
        return None
    return sum(float(number) * _DURATION_UNIT[unit] for number, unit in parts)


def _time(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _minutesSince(value, now: datetime) -> Optional[float]:
    moment = _time(value)
    return None if moment is None else max(0.0, (now - moment).total_seconds() / 60.0)


@dataclass(frozen=True)
class FlowLimits:
    """The thresholds a monitor tells its flow with: minutes of a pause, minutes of a stalled stage."""
    pause: str
    stall: str


# A tilt series takes long to process: tomography has thresholds of its own
SPA_LIMITS = FlowLimits("maxMoviePauseMinutes", "maxStageStallMinutes")
TOMO_LIMITS = FlowLimits("maxTiltPauseMinutes", "maxTiltSeriesStallMinutes")


def streamFlow(source: Optional[Dict[str, Any]], stages: List[Dict[str, Any]], thresholds: Dict[str, Optional[float]],
               now: datetime, importTimeoutSeconds: Optional[float] = None, closedAt: Optional[str] = None,
               limits: FlowLimits = SPA_LIMITS, unit: Optional[str] = None, activityUnit: Optional[str] = None,
               lastActivityAt: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The state of the acquisition and the stalled stages; stalled stages get ``stalledMinutes``.

    ``source`` is what the acquisition fills (the import's movies, or micrographs; tilt series): its
    ``stage``, ``setId``, ``protocolId``, ``label``, ``items``, ``streaming``, protocol ``status`` and
    ``lastItemAt``. ``lastActivityAt`` is when the acquisition last gave something, when its items are filled
    over time (a tilt series gets its tilts one by one): ``activityUnit`` is what comes (tilts) and ``unit``
    what its items are (tilt series).

    ``acquisition`` is "active", "paused" (open import, nothing new for the pause threshold), "stopped" (open
    import whose protocol does not run any more) or "finished" (closed import). ``complete`` is a finished
    acquisition whose stages all closed. ``closedAt`` is when the import closed its Set: its timeout after
    the last item, or when it was told to stop. A stage's ``readyBehind``, when it has one, is what really
    waits for it (not the tilt series still being acquired).
    """
    if source is None or not source.get("items"):
        return None
    lastItemAt = lastActivityAt or source.get("lastItemAt")
    idle = _minutesSince(lastItemAt, now)
    unit = unit or ("movies" if source["stage"] == "movies" else "micrographs")
    flow: Dict[str, Any] = {"lastItemAt": lastItemAt, "items": source["items"], "unit": unit,
                            "activityUnit": activityUnit or unit,
                            "protocolId": source["protocolId"], "label": source.get("label"),
                            "pauseThreshold": limits.pause, "stallThreshold": limits.stall}
    if not source.get("streaming"):
        flow["acquisition"] = "finished"
        flow["finishedAt"] = closedAt or lastItemAt
    elif source.get("status") and source["status"] not in LIVE_PROTOCOL_STATUSES:
        flow["acquisition"] = "stopped"
        flow["protocolStatus"] = source["status"]
    else:
        pause = thresholds.get(limits.pause)
        paused = pause is not None and idle is not None and idle > pause
        flow["acquisition"] = "paused" if paused else "active"
        if paused:
            flow["idleMinutes"] = idle
            if importTimeoutSeconds:
                flow["importClosesInMinutes"] = max(0.0, importTimeoutSeconds / 60.0 - idle)

    stall = thresholds.get(limits.stall)
    stalled = []
    for stage in stages:
        waiting = stage.get("readyBehind", stage.get("behind"))
        # A closed Set gives nothing more: what it lacks was left out (a filter, a categorization)
        if stage.get("setId") == source.get("setId") or stage["stage"] in UNWATCHED_STAGES \
                or not waiting or not stage.get("streaming"):
            continue
        minutes = _minutesSince(stage.get("lastItemAt"), now)
        if stall is not None and minutes is not None and minutes > stall:
            stage["stalledMinutes"] = minutes
            stalled.append({"stage": stage["stage"], "protocolId": stage["protocolId"],
                            "label": stage.get("label"), "behind": waiting, "minutes": minutes,
                            "lastItemAt": stage.get("lastItemAt"),
                            "protocolStatus": stage.get("status")})
    flow["stalled"] = stalled
    flow["complete"] = flow["acquisition"] == "finished" and not any(stage.get("streaming") for stage in stages)
    return flow


def flowAlertRuns(flow: Optional[Dict[str, Any]], stages: List[Dict[str, Any]],
                  thresholds: Dict[str, Optional[float]]) -> List[Dict[str, Any]]:
    """The flow as the bell tells it: each run starts when its condition began (the last item plus the
    threshold, or the end of the acquisition), so the bell tells it once."""
    if not flow:
        return []
    runs = []
    byProtocol = {stage["protocolId"]: stage for stage in stages}

    def run(kind: str, text: str, name: str, startedAt: Optional[datetime], protocolId: str) -> None:
        if startedAt is None:
            return
        runs.append({"kind": kind, "text": text, "micrographName": name, "count": 1, "ongoing": True,
                     "startedAt": startedAt.isoformat(), "protocolId": protocolId,
                     "protocolClassName": byProtocol.get(protocolId, {}).get("protocolClassName", "")})

    last = _time(flow.get("lastItemAt"))
    if flow["acquisition"] == "paused" and last is not None:
        pause = thresholds[flow["pauseThreshold"]]
        run(flow["pauseThreshold"], "No new %s for over %g min" % (flow["activityUnit"], pause),
            flow.get("label") or "the import", last + timedelta(minutes=pause), flow["protocolId"])
    elif flow["acquisition"] == "finished":
        run("acquisitionFinished", "Acquisition finished", "%d %s" % (flow["items"], flow["unit"]),
            _time(flow.get("finishedAt")), flow["protocolId"])
    for stalled in flow["stalled"]:
        started = _time(stalled.get("lastItemAt"))
        if started is None:
            continue
        stall = thresholds[flow["stallThreshold"]]
        run(flow["stallThreshold"], "No progress for over %g min" % stall,
            "%s, %d waiting" % (stalled.get("label") or stalled["stage"], stalled["behind"]),
            started + timedelta(minutes=stall), stalled["protocolId"])
    return runs
