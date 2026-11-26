"""Searching every project a user can see, for the AI assistant: the projects and protocols whose names, kinds or
comments have all the words, optionally run between two dates or with a status."""
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

MAX_PROTOCOLS = 60
MAX_PROJECTS = 20


def _words(text: str) -> List[str]:
    return [word for word in re.split(r"[\s,;]+", str(text or "").strip()) if word][:8]


def _day(text: Optional[str], name: str) -> Optional[str]:
    if not text:
        return None
    try:
        return date.fromisoformat(str(text).strip()[:10]).isoformat()
    except ValueError:
        raise ValueError("%s must be a date as YYYY-MM-DD" % name)


def _name(path: Any) -> str:
    return str(path or "").rstrip("/").split("/")[-1]


def _when(value: Any) -> Optional[str]:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def search(mapper, projectIds: List[int], words: str = "", since: Optional[str] = None,
           until: Optional[str] = None, status: str = "") -> Dict[str, Any]:
    """{projects, protocols, more}: what matches, the newest first; only in projectIds (the ones the user sees)."""
    terms = _words(words)
    since, until = _day(since, "since"), _day(until, "until")
    if until:
        # "until" is a whole day: before the next one
        until = (date.fromisoformat(until) + timedelta(days=1)).isoformat()
    protocols = mapper.searchProtocols(projectIds, terms, since, until, status, MAX_PROTOCOLS + 1)
    projects = mapper.searchProjects(projectIds, terms, MAX_PROJECTS)
    return {
        "projects": [{"projectId": row["projectId"], "name": _name(row["projectPath"]),
                      "description": str(row.get("description") or "")[:200], "protocols": row.get("protocols"),
                      "createdAt": _when(row.get("createdAt")), "updatedAt": _when(row.get("updatedAt"))}
                     for row in projects],
        "protocols": [{"projectId": row["projectId"], "project": _name(row["projectPath"]),
                       "protocolId": str(row["protocolId"]), "label": row.get("label"),
                       "className": row.get("className"), "status": row.get("status"),
                       "lastRunStarted": _when(row.get("startedAt")), "lastRunEnded": _when(row.get("endedAt")),
                       "created": _when(row.get("createdAt"))}
                      for row in protocols[:MAX_PROTOCOLS]],
        "more": len(protocols) > MAX_PROTOCOLS,
    }
