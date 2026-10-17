"""Server switches for the protocol viewers built at runtime.

Viewers are enabled by default. An administrator can turn them off with
SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP=0 (no viewer forms or actions on the
web) or SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL=0 (no viewer code is run).

Desktop programs a viewer launches (e.g. ChimeraX) open on the server's own
screen when it has one, which is the case when ScipionAPI and the browser run
on the same computer. SCIPION_PROTOCOL_VIEWER_DESKTOP=0 turns that off.
"""
from __future__ import annotations

import os

HTTP_SWITCH = 'SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_HTTP'
EVAL_SWITCH = 'SCIPION_EXPERIMENTAL_PROTOCOL_VIEWER_EVAL'
DESKTOP_SWITCH = 'SCIPION_PROTOCOL_VIEWER_DESKTOP'
DESKTOP_DISPLAY_VARIABLES = ('DISPLAY', 'WAYLAND_DISPLAY')
# The viewer workers run without a display; the server's one travels here.
DESKTOP_DISPLAY_PREFIX = 'SCIPION_VIEWER_DESKTOP_'
_OFF = frozenset({'0', 'false', 'no', 'off'})


def _switchOn(name: str) -> bool:
    return os.environ.get(name, '1').strip().lower() not in _OFF


def viewerEvaluationEnabled() -> bool:
    """Whether viewer code may run in the viewer worker processes."""
    return _switchOn(EVAL_SWITCH)


def viewersOnWebEnabled() -> bool:
    """Whether the web may show viewer forms and run their actions."""
    return _switchOn(HTTP_SWITCH) and viewerEvaluationEnabled()


def serverDesktopDisplay() -> dict:
    """Display variables of the API process, if desktop programs may use them."""
    if not _switchOn(DESKTOP_SWITCH):
        return {}
    return {name: os.environ[name] for name in DESKTOP_DISPLAY_VARIABLES if os.environ.get(name)}


def workerDesktopDisplay() -> dict:
    """In a viewer worker: the server display handed over by the API process."""
    if not _switchOn(DESKTOP_SWITCH):
        return {}
    return {name: os.environ[DESKTOP_DISPLAY_PREFIX + name] for name in DESKTOP_DISPLAY_VARIABLES
            if os.environ.get(DESKTOP_DISPLAY_PREFIX + name)}
