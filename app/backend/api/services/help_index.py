"""The help of every installed protocol, for the help chat: its label, its description and its parameters (label,
help and section), as each protocol's form gives them.

It is read once in a separate process (importing every plugin there, as the protocols tree does: ~2 s for ~400
protocols) and kept until the plugins change (their revision).
"""
import logging
import threading
from typing import Any, Dict, List, Optional

from app.backend.api.services.json_subprocess_runner import JsonSubprocessRunner
from app.backend.api.services.plugins_revision import getPluginsRevision

logger = logging.getLogger(__name__)

_lock = threading.Lock()
_cache: Dict[str, Any] = {"revision": None, "protocols": None}

_READ_HELP_CODE = """
import contextlib
import sys

with contextlib.redirect_stdout(sys.stderr):
    from pyworkflow import Config
    from pyworkflow.protocol.params import ElementGroup

    Config.setDomain("pwem")
    _protocols = Config.getDomain().getProtocols()


def _text(value):
    try:
        value = value.get() if hasattr(value, "get") else value
    except Exception:
        return ""
    return str(value or "").strip()


def _params(definition):
    found = []

    def walk(group, section, groupLabel):
        for name, param in group.iterParams():
            if param is None:
                continue
            if isinstance(param, ElementGroup):
                walk(param, section, _text(param.label) or groupLabel)
                continue
            label = _text(param.label)
            # Hidden params (the ones conditions use) have no label
            if not label:
                continue
            found.append({"name": name, "label": label, "help": _text(param.help),
                          "section": section, "group": groupLabel or ""})

    for section in definition.iterSections():
        walk(section, _text(section.label), "")
    return found


_scipionPayload = []
for _className, _cls in sorted(_protocols.items()):
    try:
        if _cls.isDisabled() or _cls.isBase():
            continue
    except Exception:
        pass
    try:
        _label = _cls.__dict__.get("_label") or _className
        _doc = _cls.getDoc() or ""
        try:
            with contextlib.redirect_stdout(sys.stderr):
                _definition = _cls()._definition
            _found = _params(_definition)
        except Exception:
            _found = []
        _scipionPayload.append({"className": _className, "label": str(_label), "doc": str(_doc).strip(),
                                "params": _found})
    except Exception:
        continue
"""


def _read() -> List[Dict[str, Any]]:
    payload = JsonSubprocessRunner().run(code=_READ_HELP_CODE, operationName="Read protocols help")
    return payload if isinstance(payload, list) else []


def protocolsHelp(read=_read) -> List[Dict[str, Any]]:
    """[{className, label, doc, params: [{name, label, help, section, group}]}] of the installed protocols."""
    revision = int(getPluginsRevision() or 0)
    with _lock:
        if _cache["protocols"] is not None and _cache["revision"] == revision:
            return _cache["protocols"]
        protocols = read()
        _cache["protocols"], _cache["revision"] = protocols, revision
        return protocols


def protocolHelp(className: Optional[str], read=_read) -> Optional[Dict[str, Any]]:
    for protocol in protocolsHelp(read):
        if protocol["className"] == className:
            return protocol
    return None
