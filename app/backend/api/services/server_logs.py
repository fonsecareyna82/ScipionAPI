"""The end of the server's own logs for the AI assistant, only for administrators: the API's (app.log) and the
workers' (celery.log, celery-protocols.log, and a node's protocol worker under logs/nodes/<node>/).

Before the model reads them, what could be private is blotted out: mail addresses, passwords and secrets written
as key=value, bearer tokens, and long keys or hashes.
"""
import os
import re
from pathlib import Path
from typing import Dict, Optional

LOG_FILES = {"api": "app.log", "plugins-worker": "celery.log", "protocols-worker": "celery-protocols.log"}
MAX_BYTES = 20000
MAX_MATCHES = 60

_REDACTIONS = [
    (re.compile(r"[\w.+-]+@[\w-]+(\.[\w-]+)+"), "[mail]"),
    # The token after "Bearer" first, so that "Authorization: Bearer <token>" loses the token itself
    (re.compile(r"(?i)bearer\s+[\w.\-~+/=]+"), "Bearer [hidden]"),
    (re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|key|authorization)(\s*[=:]\s*)"
                r"(?!Bearer \[hidden\])(\"[^\"]*\"|'[^']*'|\S+)"), r"\1\2[hidden]"),
    (re.compile(r"\b(sk|AIza|ghp|xox[bp])[\w-]{10,}"), "[key]"),
    (re.compile(r"\b[A-Za-z0-9_\-]{40,}\b"), "[long value]"),
]


def redact(text: str) -> str:
    for pattern, replacement in _REDACTIONS:
        text = pattern.sub(replacement, text)
    return text


def logsFolder() -> Path:
    configured = (os.environ.get("LOGS_PATH") or "").strip()
    if configured:
        return Path(configured)
    return Path(os.environ.get("SCIPION_HOME") or "scipion_home") / "logs"


def logPath(which: str, node: Optional[str] = None, folder: Optional[Path] = None) -> Path:
    if which not in LOG_FILES:
        raise ValueError("Which log: %s" % ", ".join(LOG_FILES))
    folder = folder or logsFolder()
    if node:
        if not re.fullmatch(r"[A-Za-z0-9_.\-]+", node) or node.startswith("."):
            raise ValueError("Not a node name: %s" % node)
        folder = folder / "nodes" / node
    return folder / LOG_FILES[which]


def readLog(which: str, node: Optional[str] = None, search: str = "", folder: Optional[Path] = None) -> Dict:
    """{log, text} the end of a log (or its last lines with the words searched), redacted."""
    path = logPath(which, node, folder)
    if not path.is_file():
        nodes = sorted(item.name for item in (folder or logsFolder()).joinpath("nodes").glob("*") if item.is_dir())
        raise ValueError("There is no %s log%s%s" % (which, " on node %s" % node if node else "",
                                                     "; nodes with logs: %s" % ", ".join(nodes) if nodes else ""))
    with open(path, "rb") as handle:
        size = os.path.getsize(path)
        if search:
            # Look further back for the words, and keep only the lines that have them
            handle.seek(max(0, size - 50 * MAX_BYTES))
            lines = handle.read().decode("utf-8", errors="replace").splitlines()
            words = [word.lower() for word in search.split() if word]
            hits = [line for line in lines if all(word in line.lower() for word in words)][-MAX_MATCHES:]
            text = "\n".join(hits) or "(no line has those words)"
        else:
            handle.seek(max(0, size - MAX_BYTES))
            text = handle.read().decode("utf-8", errors="replace")
    return {"log": "%s%s" % (which, " on %s" % node if node else ""), "text": redact(text)}
