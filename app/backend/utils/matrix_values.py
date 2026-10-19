"""Matrix values of metadata (transforms, Euler matrices, origins) for display.

Scipion stores a Matrix as text: JSON-like (``[[1.0, 0.0], ...]``), and
sometimes in numpy's print format (``[[1. 0.]\\n [0. 1.]]``) or with
``nan``/``inf`` entries. Display only: the stored values never change.
"""
from __future__ import annotations

import json
import re
from typing import Any, List, Optional, Union

import numpy as np

_NUMBER = r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?|[-+]?(?:nan|inf(?:inity)?)"
_NAN_TOKEN = re.compile(r"(?<![A-Za-z])nan(?![A-Za-z])", re.IGNORECASE)
_INF_TOKEN = re.compile(r"(?<![A-Za-z])inf(?:inity)?(?![A-Za-z])", re.IGNORECASE)


def _number(text: str) -> float:
    lowered = text.lower().lstrip("+")
    if lowered.lstrip("-") in ("inf", "infinity"):
        return float("-inf") if lowered.startswith("-") else float("inf")
    return float(lowered)


def _parseText(text: str) -> Optional[Any]:
    # JSON, with nan/inf spelled the way Python's json reads them.
    jsonText = _INF_TOKEN.sub("Infinity", _NAN_TOKEN.sub("NaN", text))
    try:
        return json.loads(jsonText)
    except ValueError:
        pass
    # numpy's print format: one bracketed row per line, no commas.
    rows = [[_number(number) for number in re.findall(_NUMBER, rowText, re.IGNORECASE)]
            for rowText in re.findall(r"\[([^\[\]]+)\]", text)]
    rows = [row for row in rows if row]
    if not rows:
        return None
    return rows[0] if len(rows) == 1 and not text.lstrip().startswith("[[") else rows


def parseMatrix(value: Any) -> Optional[np.ndarray]:
    """The value as a float array (a matrix or a vector); None when there is none."""
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text or text.lower() in ("none", "null"):
            return None
        value = _parseText(text)
        if value is None:
            return None
    try:
        array = np.asarray(value, dtype=float)
    except (TypeError, ValueError):
        return None
    if array.ndim == 0 or array.size == 0:
        return None
    return array


def _jsonEntry(value: float) -> Union[float, str]:
    if np.isnan(value):
        return "NaN"
    if np.isinf(value):
        return "Inf" if value > 0 else "-Inf"
    return float(value)


def matrixForJson(value: Any, decimals: int = 2) -> Optional[Union[List[Any], str]]:
    """Nested lists that JSON can carry (non-finite entries as text), rounded.

    None when there is no matrix; a text that is not a matrix is returned as it is.
    """
    array = parseMatrix(value)
    if array is None:
        if isinstance(value, str) and value.strip() and value.strip().lower() not in ("none", "null"):
            return value.strip()
        return None
    rounded = np.around(array, decimals=int(decimals))
    if rounded.ndim == 1:
        return [_jsonEntry(entry) for entry in rounded]
    return [[_jsonEntry(entry) for entry in np.ravel(row)] for row in rounded]
