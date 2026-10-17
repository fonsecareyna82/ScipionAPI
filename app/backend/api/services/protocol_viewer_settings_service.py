"""Server switches for the protocol viewers built at runtime.

Viewers are enabled by default. An administrator can turn them off with
SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP=0 (no viewer forms or actions on the
web) or SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL=0 (no viewer code is run).
"""
from __future__ import annotations

import os

HTTP_SWITCH = 'SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP'
EVAL_SWITCH = 'SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL'
_OFF = frozenset({'0', 'false', 'no', 'off'})


def _switchOn(name: str) -> bool:
    return os.environ.get(name, '1').strip().lower() not in _OFF


def viewerEvaluationEnabled() -> bool:
    """Whether viewer code may run in the viewer worker processes."""
    return _switchOn(EVAL_SWITCH)


def viewersOnWebEnabled() -> bool:
    """Whether the web may show viewer forms and run their actions."""
    return _switchOn(HTTP_SWITCH) and viewerEvaluationEnabled()
