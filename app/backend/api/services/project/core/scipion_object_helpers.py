"""Pure helpers for reading values off arbitrary Scipion objects safely."""
from typing import Any, Dict, Optional


def safeCall(obj: Any, methodName: str, default: Any = None) -> Any:
    try:
        method = getattr(obj, methodName, None)
        if method is None:
            return default
        return method()
    except Exception:
        return default


def getScipionClassName(obj: Any) -> Optional[str]:
    if obj is None:
        return None

    className = safeCall(obj, "getClassName", None)
    if className:
        return str(className)

    return obj.__class__.__name__


def getScipionObjectId(obj: Any) -> Optional[Any]:
    return safeCall(obj, "getObjId", None)


def safeScipionValue(value: Any) -> Any:
    """Convert Scipion/Python values into JSON-safe preview values."""
    if value is None:
        return None

    if isinstance(value, (str, int, float, bool)):
        if isinstance(value, str) and len(value) > 240:
            return value[:240] + "..."
        return value

    if isinstance(value, (list, tuple)):
        return [safeScipionValue(v) for v in value[:20]]

    if isinstance(value, dict):
        return {
            str(k): safeScipionValue(v)
            for k, v in list(value.items())[:30]
        }

    try:
        text = str(value)
        return text[:240] + "..." if len(text) > 240 else text
    except Exception:
        return repr(value)
