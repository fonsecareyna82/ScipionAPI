"""Importing EMhub into ScipionWeb: its users, the labs of its PIs, its resources, bookings and (as history) sessions.

It reads a copy of EMhub's database (its SQLite file, opened read only: EMhub itself is never touched) and first
makes a plan: what is matched with what ScipionWeb has (a user by address, a resource by its or its microscope's
name), what would be made, and what is left out and why. Nothing is written unless asked (``apply``), and then all
in one transaction. Every record made or matched is linked (``import_links``), so importing again makes nothing
twice.

What becomes what:
* users: an address here already = the same account; else a new one, active as in EMhub, with the default roles
  and a password nobody knows (they choose one with "Forgot password?", or an administrator gives one). EMhub's
  staff roles (admin, manager, head) are listed for the administrator to give, never given here;
* PIs (role pi, or anyone's pi): a group "<PI> lab", the PI as its pi and their lab members as members;
* resources: matched by name, else made (a microscope: charged per session);
* bookings (slot, downtime, maintenance kept as such): confirmed, on their resource, with their owner;
* sessions (with ``withSessions``): history, archived, on the microscope of their resource; no notice is sent for
  them.
Applications, projects and transactions are counted, not imported (yet).
"""
from __future__ import annotations

import datetime
import json
import secrets
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.backend.mapper.import_mapper import ImportPostgresqlMapper

SOURCE = "emhub"
STAFF_ROLES = ("admin", "manager", "head")
BOOKING_KINDS = {"booking": "booking", "slot": "special", "downtime": "downtime", "maintenance": "maintenance"}
COUNTED_ONLY = ("applications", "projects", "transactions")


# Reading EMhub -------------------------------------------------------------------------------------------------
def _json(value: Any, default: Any) -> Any:
    if value is None or value == "":
        return default
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


def _when(value: Any) -> Optional[datetime.datetime]:
    """EMhub's UTC times as aware datetimes (SQLite keeps them as text)."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime.datetime):
        moment = value
    else:
        text = str(value).strip().replace("T", " ")
        moment = None
        for size in (26, 19):
            try:
                moment = datetime.datetime.fromisoformat(text[:size])
                break
            except ValueError:
                continue
        if moment is None:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=datetime.timezone.utc)


def readEmhub(path: str) -> Dict[str, List[Dict[str, Any]]]:
    """The tables of an EMhub SQLite file, read only; a table it lacks is empty."""
    file = Path(path)
    if not file.is_file():
        raise FileNotFoundError("No EMhub database at %s" % path)
    connection = sqlite3.connect("file:%s?mode=ro" % file.resolve(), uri=True)
    connection.row_factory = sqlite3.Row
    try:
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        if "users" not in tables:
            raise ValueError("%s is not an EMhub database: it has no users table" % path)
        data = {}
        for table in ("users", "resources", "bookings", "sessions") + COUNTED_ONLY:
            data[table] = [dict(row) for row in connection.execute("SELECT * FROM %s" % table)] \
                if table in tables else []
        return data
    finally:
        connection.close()


# The plan ------------------------------------------------------------------------------------------------------
def _splitName(name: str, email: str) -> tuple:
    words = str(name or "").split()
    if not words:
        return (str(email).split("@")[0], "")
    return (words[0], " ".join(words[1:]))


def _person(user: Dict[str, Any]) -> str:
    return str(user.get("name") or user.get("email") or "user %s" % user.get("id")).strip()


def plan(data: Dict[str, List[Dict[str, Any]]], mapper: ImportPostgresqlMapper, withSessions: bool = False,
         since: Optional[datetime.date] = None) -> Dict[str, Any]:
    """What importing would do, without writing anything."""
    links = {kind: mapper.links(SOURCE, kind) for kind in ("user", "group", "resource", "booking", "session")}
    report: Dict[str, Any] = {"users": [], "groups": [], "resources": [], "bookings": [], "sessions": [],
                              "skipped": [], "staffRoles": [], "countedOnly": {}}
    # Users
    byEmail = mapper.userIdsByEmail()
    emails = set()
    for user in data["users"]:
        email = str(user.get("email") or "").strip().lower()
        if not email or "@" not in email:
            report["skipped"].append({"kind": "user", "id": user.get("id"), "why": "no mail address"})
            continue
        if email in emails:
            report["skipped"].append({"kind": "user", "id": user.get("id"), "why": "address repeated in EMhub"})
            continue
        emails.add(email)
        roles = _json(user.get("roles"), [])
        staff = [role for role in roles if role in STAFF_ROLES or str(role).startswith("staff")]
        if staff:
            report["staffRoles"].append({"email": email, "roles": staff})
        action = "linked" if str(user["id"]) in links["user"] else ("match" if email in byEmail else "create")
        report["users"].append({"id": user["id"], "email": email, "action": action, "active": user.get("status") == "active"})
    imported = {entry["id"] for entry in report["users"]}
    # Labs: every PI with their members
    usersById = {user["id"]: user for user in data["users"] if user["id"] in imported}
    pis = {user["id"] for user in usersById.values() if "pi" in _json(user.get("roles"), [])}
    pis |= {user.get("pi_id") for user in usersById.values() if user.get("pi_id") in usersById}
    groupNames = mapper.groupIdsByName()
    for piId in sorted(pis):
        name = "%s lab" % _person(usersById[piId])
        members = [user["id"] for user in usersById.values() if user.get("pi_id") == piId and user["id"] != piId]
        action = "linked" if str(piId) in links["group"] else ("match" if name.lower() in groupNames else "create")
        report["groups"].append({"piId": piId, "name": name, "members": len(members), "action": action})
    # Resources
    byName = mapper.resourcesByName()
    resources = {}
    for resource in data["resources"]:
        name = str(resource.get("name") or "").strip()
        if not name:
            report["skipped"].append({"kind": "resource", "id": resource.get("id"), "why": "no name"})
            continue
        action = "linked" if str(resource["id"]) in links["resource"] else ("match" if name.lower() in byName else "create")
        resources[resource["id"]] = resource
        report["resources"].append({"id": resource["id"], "name": name, "action": action,
                                    "microscope": "microscope" in str(resource.get("tags") or "")})
    # Bookings
    for booking in data["bookings"]:
        start, end = _when(booking.get("start")), _when(booking.get("end"))
        why = None
        if booking.get("resource_id") not in resources:
            why = "its resource is not imported"
        elif not start or not end or end <= start:
            why = "no valid times"
        elif since and end.date() < since:
            why = "before %s" % since
        elif str(booking.get("type") or "booking") not in BOOKING_KINDS:
            why = "unknown type %s" % booking.get("type")
        if why:
            report["skipped"].append({"kind": "booking", "id": booking.get("id"), "why": why})
            continue
        action = "linked" if str(booking["id"]) in links["booking"] else "create"
        report["bookings"].append({"id": booking["id"], "action": action})
    # Sessions (history)
    if withSessions:
        names = mapper.sessionIdsByName()
        bookingOwner = {booking["id"]: booking.get("owner_id") for booking in data["bookings"]}
        for session in data["sessions"]:
            name = str(session.get("name") or "").strip()
            why = None
            if not name:
                why = "no name"
            elif session.get("resource_id") not in resources:
                why = "its resource is not imported"
            if why:
                report["skipped"].append({"kind": "session", "id": session.get("id"), "why": why})
                continue
            action = "linked" if str(session["id"]) in links["session"] else ("match" if name.lower() in names else "create")
            report["sessions"].append({"id": session["id"], "name": name, "action": action,
                                       "owner": bookingOwner.get(session.get("booking_id"))})
    report["countedOnly"] = {table: len(data.get(table) or []) for table in COUNTED_ONLY}
    return report


def summary(report: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """How many of each kind would be made, matched with what exists, or were imported before."""
    counts = {}
    for kind in ("users", "groups", "resources", "bookings", "sessions"):
        counts[kind] = {}
        for entry in report[kind]:
            counts[kind][entry["action"]] = counts[kind].get(entry["action"], 0) + 1
    counts["skipped"] = {}
    for entry in report["skipped"]:
        counts["skipped"][entry["kind"]] = counts["skipped"].get(entry["kind"], 0) + 1
    return counts


# Applying it -----------------------------------------------------------------------------------------------------
def apply(data: Dict[str, List[Dict[str, Any]]], db, withSessions: bool = False,
          since: Optional[datetime.date] = None) -> Dict[str, Any]:
    """Import what the plan says, in one transaction; answers the plan with the ids made or matched here."""
    from app.backend.utils.security import hashPassword

    mapper = ImportPostgresqlMapper(db)
    report = plan(data, mapper, withSessions, since)
    usersById = {user["id"]: user for user in data["users"]}
    resourcesById = {resource["id"]: resource for resource in data["resources"]}
    with db.transaction():
        # Users
        userIds = dict((int(k), v) for k, v in mapper.links(SOURCE, "user").items() if k.isdigit())
        byEmail = mapper.userIdsByEmail()
        defaultRoles = mapper.defaultRoleIds()
        for entry in report["users"]:
            if entry["action"] == "linked":
                continue
            if entry["action"] == "match":
                targetId = byEmail[entry["email"]]
            else:
                user = usersById[entry["id"]]
                extra = _json(user.get("extra"), {})
                first, last = _splitName(user.get("name"), entry["email"])
                targetId = mapper.insertUser({
                    "email": entry["email"], "hashedPassword": hashPassword(secrets.token_urlsafe(32)),
                    "firstName": first, "lastName": last,
                    "institution": str(extra.get("institution") or extra.get("university") or ""),
                    "isActive": entry["active"], "createdAt": _when(user.get("created"))})
                mapper.giveRoles(targetId, defaultRoles)
            mapper.link(SOURCE, "user", entry["id"], targetId)
            userIds[entry["id"]] = targetId
            entry["targetId"] = targetId
        # Labs
        groupNames = mapper.groupIdsByName()
        for entry in report["groups"]:
            groupId = mapper.links(SOURCE, "group").get(str(entry["piId"]))
            if groupId is None:
                groupId = groupNames.get(entry["name"].lower()) or mapper.insertGroup(entry["name"], "Imported from EMhub")
                mapper.link(SOURCE, "group", entry["piId"], groupId)
            mapper.addMember(groupId, userIds[entry["piId"]], "pi")
            for user in usersById.values():
                if user.get("pi_id") == entry["piId"] and user["id"] != entry["piId"] and user["id"] in userIds:
                    mapper.addMember(groupId, userIds[user["id"]], "member")
            entry["targetId"] = groupId
        # Resources
        resourceIds = dict((int(k), v) for k, v in mapper.links(SOURCE, "resource").items() if k.isdigit())
        mapper.addMicroscopeResources()
        byName = mapper.resourcesByName()
        for entry in report["resources"]:
            if entry["action"] == "linked":
                continue
            if entry["action"] == "match":
                targetId = int(byName[entry["name"].lower()]["id"])
            else:
                resource = resourcesById[entry["id"]]
                extra = _json(resource.get("extra"), {})
                hours = lambda key: float(extra[key]) if extra.get(key) else None  # noqa: E731
                minHours, maxHours = hours("min_booking"), hours("max_booking")
                if minHours and maxHours and minHours > maxHours:
                    minHours = maxHours = None
                targetId = mapper.insertResource({
                    "name": entry["name"], "color": str(resource.get("color") or ""),
                    "unit": "session" if entry["microscope"] else "hour", "minHours": minHours, "maxHours": maxHours,
                    "active": resource.get("status") == "active",
                    "notes": "Imported from EMhub (tags: %s)" % (resource.get("tags") or "")})
            mapper.link(SOURCE, "resource", entry["id"], targetId)
            resourceIds[entry["id"]] = targetId
            entry["targetId"] = targetId
        # Bookings
        bookingsById = {booking["id"]: booking for booking in data["bookings"]}
        for entry in report["bookings"]:
            if entry["action"] == "linked":
                continue
            booking = bookingsById[entry["id"]]
            targetId = mapper.insertBooking({
                "resourceId": resourceIds[booking["resource_id"]],
                "kind": BOOKING_KINDS[str(booking.get("type") or "booking")],
                "startsAt": _when(booking["start"]), "endsAt": _when(booking["end"]),
                "title": str(booking.get("title") or "")[:200], "ownerId": userIds.get(booking.get("owner_id")),
                "requestedBy": userIds.get(booking.get("creator_id")),
                "notes": ("Imported from EMhub. %s" % (booking.get("description") or "")).strip()[:2000]})
            mapper.link(SOURCE, "booking", entry["id"], targetId)
            entry["targetId"] = targetId
        # Sessions (history, archived)
        if withSessions:
            microscopeOf = mapper.resourceMicroscopes()
            names = mapper.sessionIdsByName()
            sessionsById = {session["id"]: session for session in data["sessions"]}
            for entry in report["sessions"]:
                if entry["action"] == "linked":
                    continue
                if entry["action"] == "match":
                    targetId = names[entry["name"].lower()]
                else:
                    session = sessionsById[entry["id"]]
                    microscopeId = microscopeOf.get(resourceIds[session["resource_id"]])
                    if microscopeId is None:
                        entry["action"] = "skipped"
                        report["skipped"].append({"kind": "session", "id": entry["id"],
                                                  "why": "its resource is not a microscope here"})
                        continue
                    start, end = _when(session.get("start")), _when(session.get("end"))
                    targetId = mapper.insertSession({
                        "name": entry["name"], "microscopeId": microscopeId, "technique": "spa",
                        "userId": userIds.get(entry.get("owner")), "scheduledOn": start.date() if start else None,
                        "startedAt": start, "finishedAt": end or start,
                        "notes": "Imported from EMhub (session %s; data: %s)" % (entry["id"], session.get("data_path") or ""),
                        "createdBy": userIds.get(session.get("operator_id"))})
                mapper.link(SOURCE, "session", entry["id"], targetId)
                entry["targetId"] = targetId
    return report
