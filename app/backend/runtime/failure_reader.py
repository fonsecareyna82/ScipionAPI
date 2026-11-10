"""Why a protocol failed, read from its logs without any service: the error that stopped it, the command that
failed and the last traceback, each with its line in the log, and, when it is a known error, what it means and
what to try (failure_hints.json).

Logs may be huge: only their last part is read (the failure is at the end), with its line numbers kept.
"""
import json
import logging
import os
import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

HINTS_FILE = Path(__file__).with_name("failure_hints.json")
# The last part of each log that is read
TAIL_BYTES = 2 * 1024 * 1024
# Lines shown of a traceback, and error lines kept
MAX_TRACEBACK_LINES = 40
MAX_ERROR_LINES = 8

ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
# A line holding a timestamp and level before the message, as the protocol logs write them
LOG_PREFIX = re.compile(r"^\s*(\d{4}-\d\d-\d\d[ T][\d:.,]+\s+)?(\d{2}:\d{2}:\d{2}\s+)?((INFO|ERROR|WARNING|DEBUG)[:\s]+)?")
RUNNING_COMMAND = re.compile(r"\*\* Running command:\s*\*?\*?\s*'?(?P<inline>.*?)'?\s*$")
PROTOCOL_FAILED = re.compile(r"Protocol failed:\s*(?P<message>.*)$")
VALIDATION = re.compile(r"Protocol has validation errors:?\s*(?P<message>.*)$")
ERROR_LINE = re.compile(r"\b(error|exception|failed|failure|killed|abort(ed)?|fatal|segmentation fault|core dumped|"
                        r"out of memory|not found|no such file|permission denied|traceback|bad_alloc|cannot|could not|unable to)\b",
                        re.IGNORECASE)
# The protocol's own markers of a failure, which say nothing of why
MARKER = re.compile(r"^-+\s*PROTOCOL (FAILED|FINISHED|ABORTED)|^(FAILED|STARTED|FINISHED):\s+\w+, step \d+|"
                    r"^\*\*\* Last status is", re.IGNORECASE)
# A failure that only says a program ended badly: what the program wrote says more
GENERIC_FAILURE = re.compile(r"returned non-zero exit status|exit (code|status)|Process returned with code",
                             re.IGNORECASE)
# Lines that look like errors but are not
NOT_AN_ERROR = re.compile(r"\b(0 errors?|no errors?|error[- ]?(bars?|threshold|tolerance|rate)|warning)\b"
                          r"|\berror\s*[:=]\s*[-+]?\d", re.IGNORECASE)


def clean(line: str) -> str:
    return ANSI.sub("", line).rstrip("\r\n")


def readTail(path: Optional[str], tailBytes: int = TAIL_BYTES) -> List[Tuple[int, str]]:
    """The last part of a log as (line number, text), numbered as in the whole file."""
    if not path or not os.path.isfile(path):
        return []
    try:
        with open(path, "rb") as handle:
            size = handle.seek(0, os.SEEK_END)
            start = max(0, size - tailBytes)
            skipped = 0
            handle.seek(0)
            remaining = start
            while remaining > 0:
                chunk = handle.read(min(remaining, 1024 * 1024))
                if not chunk:
                    break
                skipped += chunk.count(b"\n")
                remaining -= len(chunk)
            data = handle.read()
    except OSError:
        return []
    lines = data.decode("utf-8", errors="replace").split("\n")
    if start > 0 and lines:
        # The first line is cut
        lines = lines[1:]
        skipped += 1
    if lines and lines[-1] == "":
        lines = lines[:-1]
    return [(skipped + position + 1, clean(line)) for position, line in enumerate(lines)]


def _message(text: str) -> str:
    return LOG_PREFIX.sub("", text, count=1).strip()


def _lastCommand(lines: List[Tuple[int, str]]) -> Optional[Dict[str, Any]]:
    found = None
    for position, (number, text) in enumerate(lines):
        match = RUNNING_COMMAND.search(text)
        if not match:
            continue
        inline = match.group("inline").strip().strip("*").strip()
        if inline:
            found = {"text": inline, "line": number}
        elif position + 1 < len(lines):
            following = _message(lines[position + 1][1])
            if following:
                found = {"text": following, "line": lines[position + 1][0]}
    return found


def _lastTraceback(lines: List[Tuple[int, str]]) -> List[Dict[str, Any]]:
    """The last Python traceback: its header, its frames and the exception line that ends it."""
    start = None
    for position, (_, text) in enumerate(lines):
        if "Traceback (most recent call last)" in text:
            start = position
    if start is None:
        return []
    block = [lines[start]]
    for number, text in lines[start + 1:]:
        message = text
        block.append((number, message))
        stripped = _message(message)
        # The exception line ends it: not indented, not a frame
        if stripped and not message.startswith((" ", "\t")) and not stripped.startswith(("File ", "During handling",
                                                                                          "The above exception")):
            if ":" in stripped or stripped.endswith(("Error", "Exception")):
                break
        if len(block) >= MAX_TRACEBACK_LINES * 3:
            break
    block = block[-MAX_TRACEBACK_LINES:]
    return [{"text": text, "line": number} for number, text in block]


def _failedLine(lines: List[Tuple[int, str]], channel: str) -> Optional[Dict[str, Any]]:
    """What the protocol said when it failed ("Protocol failed: ..."), the message going on in the next lines
    when it starts empty."""
    found = None
    for position, (number, text) in enumerate(lines):
        match = PROTOCOL_FAILED.search(text)
        if not match:
            continue
        parts = [match.group("message").strip()]
        for _, following in lines[position + 1:position + 8]:
            if parts[-1] and len(parts) > 1:
                break
            piece = _message(following).lstrip(">").strip()
            if piece and not piece.startswith("File "):
                parts.append(piece)
        message = " ".join(part for part in parts if part).strip()
        found = {"text": message[:500], "line": number, "channel": channel}
    return found


def _validation(lines: List[Tuple[int, str]], channel: str) -> Optional[Dict[str, Any]]:
    """Why the protocol did not even start: the lines after "Protocol has validation errors"."""
    found = None
    for position, (number, text) in enumerate(lines):
        match = VALIDATION.search(text)
        if not match:
            continue
        parts = [match.group("message").strip()]
        for _, following in lines[position + 1:position + 6]:
            piece = _message(following)
            if MARKER.search(piece):
                break
            parts.append(piece)
        message = " ".join(part for part in parts if part).strip()
        found = {"text": message[:500], "line": number + 1, "channel": channel}
    return found


def _errorLines(lines: List[Tuple[int, str]], channel: str) -> List[Dict[str, Any]]:
    found = []
    for number, text in lines:
        message = _message(text)
        if (message and ERROR_LINE.search(message) and not NOT_AN_ERROR.search(message)
                and not MARKER.search(message) and not PROTOCOL_FAILED.search(message)):
            found.append({"text": message[:500], "line": number, "channel": channel})
    return found[-MAX_ERROR_LINES:]


@lru_cache(maxsize=1)
def _rulesFrom(path: str, stamp: float) -> List[Dict[str, Any]]:
    try:
        with open(path) as handle:
            rules = json.load(handle).get("rules") or []
    except (OSError, ValueError):
        logger.warning("Could not read the known errors of failed protocols from %s", path, exc_info=True)
        return []
    compiled = []
    for rule in rules:
        try:
            compiled.append(dict(rule, regex=re.compile(rule["pattern"], re.IGNORECASE | re.MULTILINE)))
        except (KeyError, re.error):
            logger.warning("A known error rule cannot be used: %s", rule.get("id"))
    return compiled


def knownErrors(path: Path = HINTS_FILE) -> List[Dict[str, Any]]:
    try:
        stamp = path.stat().st_mtime
    except OSError:
        return []
    return _rulesFrom(str(path), stamp)


def matchHint(texts: Iterable[str], rules: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """The first known error found in these texts (in rule order), with the text it was found in."""
    texts = [text for text in texts if text]
    for rule in rules if rules is not None else knownErrors():
        for text in texts:
            match = rule["regex"].search(text)
            if match:
                return {"id": rule.get("id"), "category": rule.get("category"), "title": rule.get("title"),
                        "hint": rule.get("hint"), "matched": match.group(0)[:200]}
    return None


def explainFailure(stdoutPath: Optional[str], stderrPath: Optional[str],
                   stepErrors: Iterable[str] = (), rules: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """What the logs and the failed steps say of a failure: cause (a known error, or None), error, command and
    traceback (each with its log and line)."""
    stdout = readTail(stdoutPath)
    stderr = readTail(stderrPath)
    stepErrors = [clean(str(error)).strip() for error in stepErrors if error and str(error).strip()]

    command = _lastCommand(stdout)
    if command:
        command["channel"] = "stdout"
    traceback = []
    tracebackChannel = None
    for channel, lines in (("stderr", stderr), ("stdout", stdout)):
        traceback = _lastTraceback(lines)
        if traceback:
            tracebackChannel = channel
            break

    validation = _validation(stdout, "stdout") or _validation(stderr, "stderr")
    failedLine = _failedLine(stderr, "stderr") or _failedLine(stdout, "stdout")
    if failedLine and not failedLine["text"]:
        failedLine = None

    errors = _errorLines(stderr, "stderr") + _errorLines(stdout, "stdout")
    stderrErrors = [line for line in errors if line["channel"] == "stderr"]
    exception = dict(traceback[-1], channel=tracebackChannel) if traceback else None
    if exception and not _message(exception["text"]).partition(":")[2].strip():
        # "SomeError:" with its message on the next line
        exception = None
    # The error to show: what the protocol said when it failed, unless it only says a program ended badly; else
    # the exception that ended the traceback; else the last error the program wrote; else the step's error
    # What the program itself wrote, when the failure only says it ended badly
    written = [line for line in (stderrErrors or errors) if not GENERIC_FAILURE.search(line["text"])
               and not line["text"].startswith(("Traceback", "subprocess."))]
    error = None
    if validation and validation["text"]:
        error = validation
    elif failedLine and not GENERIC_FAILURE.search(failedLine["text"]):
        error = failedLine
    elif exception and not GENERIC_FAILURE.search(exception["text"]):
        error = exception
    elif written:
        error = written[-1]
    elif exception:
        error = exception
    elif stderrErrors or errors:
        error = (stderrErrors or errors)[-1]
    elif failedLine:
        error = failedLine
    elif stepErrors:
        error = {"text": stepErrors[-1][:500], "line": None, "channel": None}

    # A known error is looked for in what matters most first (the error shown and what the protocol said), then
    # in the other error lines, and last in the end of the logs: a warning further up never hides the cause
    tiers = [
        [validation["text"] if validation else "", error["text"] if error else "", "\n".join(line["text"] for line in traceback),
         failedLine["text"] if failedLine else "", "\n".join(stepErrors)],
        ["\n".join(line["text"] for line in reversed(errors))],
        ["\n".join(text for _, text in stderr[-200:]), "\n".join(text for _, text in stdout[-200:])],
    ]
    cause = None
    for tier in tiers:
        cause = matchHint(tier, rules)
        if cause:
            break

    return {"cause": cause, "error": error, "command": command, "traceback": traceback,
            "errors": errors, "stepErrors": stepErrors[-3:],
            "hasLogs": bool(stdout or stderr)}
