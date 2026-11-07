"""How long a finished session's data are kept, and the notices its user is owed before they go."""
import datetime

import pytest
from fastapi import HTTPException

from app.backend.api.services import facility_retention as retention
from app.backend.api.services.facility_settings_service import noticeDays

DAY = datetime.date(2026, 11, 7)
SETTINGS = {"rawRetentionDays": 90, "processedRetentionDays": 30, "retentionNoticeDays": [30, 7, 1],
            "timezone": "Europe/Madrid"}


def _session(**change):
    return dict({"id": 1, "name": "20260801_KRIOS_0001", "microscopeName": "Krios",
                 "finishedAt": datetime.datetime(2026, 8, 1, 10, tzinfo=datetime.timezone.utc),
                 "finishedOn": datetime.date(2026, 8, 1), "projects": [{"id": 7}]}, **change)


def test_DataAreKeptTheFacilitysDaysFromTheDayTheSessionFinished():
    assert retention.keptUntil(_session(), "raw", SETTINGS) == datetime.date(2026, 10, 30)
    assert retention.keptUntil(_session(), "processed", SETTINGS) == datetime.date(2026, 8, 31)


def test_ASessionsOwnDateWinsOverTheFacilitysDays():
    session = _session(rawKeepUntil=datetime.date(2027, 1, 15))

    assert retention.keptUntil(session, "raw", SETTINGS) == datetime.date(2027, 1, 15)


def test_NoDaysAndNoDateKeepTheDataWithoutADate():
    settings = dict(SETTINGS, rawRetentionDays=0)

    state = retention.retentionState(_session(), "raw", settings, DAY)

    assert state["until"] is None and state["state"] == "kept"


def test_TheDayASessionFinishedIsTheFacilitysDay():
    # 23:30 UTC on 31 July is already 1 August in Madrid
    session = _session(finishedAt=datetime.datetime(2026, 7, 31, 23, 30, tzinfo=datetime.timezone.utc))
    del session["finishedOn"]

    assert retention.keptUntil(session, "processed", SETTINGS) == datetime.date(2026, 8, 31)


@pytest.mark.parametrize("on, state, daysLeft", [
    (datetime.date(2026, 9, 1), "kept", 59),
    (datetime.date(2026, 10, 1), "due", 29),
    (datetime.date(2026, 10, 30), "due", 0),
    (datetime.date(2026, 10, 31), "expired", -1),
])
def test_DataAreKeptThenDueThenExpired(on, state, daysLeft):
    found = retention.retentionState(_session(), "raw", SETTINGS, on)

    assert (found["state"], found["daysLeft"]) == (state, daysLeft)


def test_DeletedDataAndASessionWithoutProjectsOweNothing():
    deleted = _session(rawDeletedAt=datetime.datetime(2026, 11, 1, tzinfo=datetime.timezone.utc),
                       rawDeletedByName="Ana Staff")
    noProjects = _session(projects=[])

    assert retention.retentionState(deleted, "raw", SETTINGS, DAY)["state"] == "deleted"
    assert retention.retentionState(deleted, "raw", SETTINGS, DAY)["deletedBy"] == "Ana Staff"
    assert retention.retentionState(noProjects, "processed", SETTINGS, DAY)["state"] == "none"
    assert retention.noticesDue(dict(deleted, projects=[]), SETTINGS, DAY) == {}


def test_ALateLookSendsOneNoticeForEveryDayItCovers():
    # 5 days before the raw data's date: the 30 and 7 day notices were never sent, one mail covers both
    owed = retention.noticesDue(_session(), SETTINGS, datetime.date(2026, 10, 25))

    assert owed == {"raw": ("2026-10-30", 5, [30, 7])}


def test_ANoticeSentIsNotOwedAgainUntilTheNextDay():
    sent = {"raw": {"until": "2026-10-30", "sent": [30, 7]}}
    session = _session(retentionNotices=sent)

    assert retention.noticesDue(session, SETTINGS, datetime.date(2026, 10, 25)) == {}
    assert retention.noticesDue(session, SETTINGS, datetime.date(2026, 10, 29)) == {"raw": ("2026-10-30", 1, [1])}


def test_ANewDateStartsTheNoticesAgain():
    session = _session(rawKeepUntil=datetime.date(2026, 11, 30),
                       retentionNotices={"raw": {"until": "2026-10-30", "sent": [30, 7, 1]}})

    assert retention.noticesDue(session, SETTINGS, datetime.date(2026, 11, 2)) == {"raw": ("2026-11-30", 28, [30])}


def test_NoNoticeIsOwedOnceTheDatePassed():
    assert retention.noticesDue(_session(projects=[]), SETTINGS, datetime.date(2026, 11, 2)) == {}


def test_TheNoticeSaysWhatGoesWhenAndHowToTakeItHome():
    owed = {"raw": ("2026-10-30", 7, [7]), "processed": ("2026-08-31", 1, [1])}

    text = retention.noticeText(_session(), owed, "iget -r /cnb/home/...")

    assert text["subject"] == "Session 20260801_KRIOS_0001: its data may be deleted tomorrow"
    assert "raw movies are kept until 2026-10-30 (in 7 days)" in text["body"]
    assert "processing projects are kept until 2026-08-31 (tomorrow)" in text["body"]
    assert "iget -r /cnb/home/..." in text["body"]


@pytest.mark.parametrize("given, days", [("30, 7, 1", [30, 7, 1]), ([1, 30, 7, 7], [30, 7, 1]), ("", [])])
def test_NoticeDaysAreReadFromATextOrAList(given, days):
    assert noticeDays(given) == days


@pytest.mark.parametrize("given", ["0", "400", "a week", "1,2,3,4,5,6"])
def test_WrongNoticeDaysAreRefused(given):
    with pytest.raises(HTTPException) as error:
        noticeDays(given)
    assert error.value.status_code == 400
