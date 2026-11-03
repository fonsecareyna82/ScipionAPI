"""A facility's conventions: the patterns of its sessions' names and of its microscopes' folders."""
import datetime

import pytest

from app.backend.api.services import facility_conventions as conventions

VALUES = {"date": datetime.date(2026, 11, 3), "user": "Gaoxin-Lu", "pi": "Ashleigh-Shannon", "group": "",
          "microscope": "KRIOS", "booking": "", "technique": "tomo", "id": 7}


def test_ASessionIsNamedByThePiecesOfThePattern():
    assert conventions.sessionName("{date:%Y_%m_%d}_{user}_{id:06d}", VALUES) == "2026_11_03_Gaoxin-Lu_000007"
    assert conventions.sessionName("{date:%Y%m%d}_{microscope}_{pi}_{technique}_{id:03d}", VALUES) == \
        "20261103_KRIOS_Ashleigh-Shannon_tomo_007"
    # An empty piece leaves no doubled nor hanging separator
    assert conventions.sessionName("{group}_{date:%Y%m%d}__{booking}_{id}", VALUES) == "20261103_7"


@pytest.mark.parametrize("pattern, message", [
    ("{date:%Y}_{owner}", "{owner} is not a piece"),
    ("{user.__class__}", "is not a piece"),
    ("{id[0]}", "is not a piece"),
    ("{date:%Y} {user}", "is not a folder name"),
    ("{id:q}", "cannot be read"),
    ("", "empty"),
])
def test_APatternTakesOnlyItsPiecesAndMakesFolderNames(pattern, message):
    with pytest.raises(ValueError) as error:
        conventions.sessionName(pattern, VALUES)
    assert message in str(error.value)


def test_TheFoldersOfASessionAreNamedByTheMicroscopesPatterns():
    assert conventions.folderName("{session}_DATA_{n:02d}", "S1", 3, "TALOS") == "S1_DATA_03"
    assert conventions.folderName("{microscope}_{session}_Grid{n}", "S1", 12, "KRIOS") == "KRIOS_S1_Grid12"
    with pytest.raises(ValueError):
        conventions.folderName("{session}_{date}", "S1", 1, "KRIOS")


def test_TheExamplesShowWhatAFacilitysPatternsMake():
    examples = conventions.examples("{date:%Y_%m_%d}_{user}_{id:06d}", "{session}_DATA_{n:02d}", "")

    assert examples == {"session": "2026_11_03_Gaoxin-Lu_000123", "atlas": None,
                        "data": ["2026_11_03_Gaoxin-Lu_000123_DATA_01", "2026_11_03_Gaoxin-Lu_000123_DATA_02"]}
    assert conventions.nameWord("Ashleigh Shannon (PI)") == "Ashleigh-Shannon-PI"
    assert conventions.microscopeCode({"code": "", "name": "Titan Krios G5"}) == "Titan-Krios-G5"
