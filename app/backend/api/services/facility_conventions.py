"""A facility's conventions: how it names its sessions and the folders its microscopes write.

A convention is a pattern with pieces in braces, formatted as Python does ({id:06d}, {date:%Y_%m_%d}):

* a session's name: {date} (its day), {user} and {pi} (the user's and the group's PI's name, as
  Name-Surname), {group}, {microscope} (its code), {booking}, {technique} (spa, tomo) and {id} (its number);
* a microscope's DATA and ATLAS folders: {session} (the session's name), {n} (the grid's position in the
  autoloader) and {microscope}.

Only these pieces are taken (no attributes nor indexes), and what a pattern makes must be a folder name. The
defaults are a neutral choice; ``PRESETS`` holds the ones of facilities that use ScipionWeb.
"""
import datetime
import re
import string
import unicodedata
from typing import Any, Dict, Iterable

SESSION_NAME_FIELDS = ("date", "user", "pi", "group", "microscope", "booking", "technique", "id")
FOLDER_FIELDS = ("session", "n", "microscope")

DEFAULT_SESSION_NAME_PATTERN = "{date:%Y%m%d}_{microscope}_{id:04d}"
DEFAULT_DATA_FOLDER_PATTERN = "{session}_DATA_{n:02d}"
DEFAULT_ATLAS_FOLDER_PATTERN = "{session}_ATLAS"

# Conventions of facilities, applied from the Configuration tab
PRESETS = {
    "cnb": {
        "label": "CNB-CSIC (as EMhub names them: YYYY_MM_DD_Name-Surname_id, <session>_DATA_NN, <session>_ATLAS)",
        "settings": {"sessionNamePattern": "{date:%Y_%m_%d}_{user}_{id:06d}"},
        "microscope": {"dataFolderPattern": "{session}_DATA_{n:02d}", "atlasFolderPattern": "{session}_ATLAS",
                       "gridSlots": 12},
    },
}

# A folder name EPU, SerialEM and every file system take
FOLDER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
PATTERN_LIMIT = 200


def nameWord(text: Any) -> str:
    """Text as a part of a name: plain letters and digits, words joined by '-' (Gaoxin Lü: Gaoxin-Lu)."""
    ascii = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode()
    return "-".join(re.findall(r"[A-Za-z0-9]+", ascii))


class _PatternFormatter(string.Formatter):
    def __init__(self, allowed: Iterable[str]):
        super().__init__()
        self.allowed = set(allowed)

    def get_field(self, fieldName, args, kwargs):
        if fieldName not in self.allowed:
            raise ValueError("{%s} is not a piece of this pattern (it takes %s)"
                             % (fieldName, ", ".join("{%s}" % name for name in sorted(self.allowed))))
        return kwargs[fieldName], fieldName


def render(pattern: str, values: Dict[str, Any], allowed: Iterable[str]) -> str:
    """What pattern makes with values; raises ValueError for a pattern that is wrong or makes no folder name.

    A piece left empty (a session without a group) leaves no doubled or hanging separators."""
    pattern = str(pattern or "")
    if not pattern.strip():
        raise ValueError("The pattern is empty")
    if len(pattern) > PATTERN_LIMIT:
        raise ValueError("A pattern is up to %d characters" % PATTERN_LIMIT)
    try:
        made = _PatternFormatter(allowed).vformat(pattern, (), dict(values))
    except (KeyError, IndexError, TypeError) as error:
        raise ValueError("The pattern cannot be read: %s" % error)
    except ValueError as error:
        message = str(error)
        raise ValueError(message if "is not a piece" in message else "The pattern cannot be read: %s" % message)
    made = re.sub(r"([_.-])[_.-]+", r"\1", made).strip("_.-")
    if not FOLDER_NAME.match(made):
        raise ValueError("'%s' is not a folder name: letters, digits, '_', '-' and '.' only" % made)
    return made


def sessionName(pattern: str, values: Dict[str, Any]) -> str:
    return render(pattern, values, SESSION_NAME_FIELDS)


def folderName(pattern: str, session: str, number: int, microscope: str) -> str:
    return render(pattern, {"session": session, "n": int(number), "microscope": microscope}, FOLDER_FIELDS)


def microscopeCode(microscope: Dict[str, Any]) -> str:
    """A microscope in names: its code, else its name as a word."""
    return nameWord(microscope.get("code")) or nameWord(microscope.get("name"))


# What the examples of the Configuration tab are made with
EXAMPLE_SESSION = {"date": datetime.date(2026, 11, 3), "user": "Gaoxin-Lu", "pi": "Ashleigh-Shannon",
                   "group": "Shannon-lab", "microscope": "KRIOS", "booking": "B-1203", "technique": "tomo", "id": 123}


def examples(sessionNamePattern: str, dataFolderPattern: str = DEFAULT_DATA_FOLDER_PATTERN,
             atlasFolderPattern: str = DEFAULT_ATLAS_FOLDER_PATTERN, microscope: str = "KRIOS") -> Dict[str, Any]:
    """The names a facility's patterns make for an example session; raises ValueError for a wrong one."""
    session = sessionName(sessionNamePattern, dict(EXAMPLE_SESSION, microscope=microscope))
    return {
        "session": session,
        "atlas": folderName(atlasFolderPattern, session, 0, microscope) if str(atlasFolderPattern or "").strip() else None,
        "data": [folderName(dataFolderPattern, session, number, microscope) for number in (1, 2)],
    }
