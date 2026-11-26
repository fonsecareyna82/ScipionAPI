"""A subset of an output chosen by its values, for the AI assistant: the rows of one of its tables (as the metadata
viewer shows them) that meet every condition, e.g. the CTFs with a resolution better than 5 A or the 2D classes
with more than 1000 particles. The subset is made with the viewer's own action (a subset protocol), and only when
the user applies the card: the rows are read again then, so it keeps what meets the conditions at that moment.
"""
from typing import Any, Callable, Dict, List, Optional

OPERATORS = {
    "<": lambda a, b: a < b, "<=": lambda a, b: a <= b, ">": lambda a, b: a > b, ">=": lambda a, b: a >= b,
    "=": lambda a, b: a == b, "!=": lambda a, b: a != b,
}
PAGE_SIZE = 5000
MAX_ROWS = 300000
MAX_CONDITIONS = 6
EXAMPLES = 5


class SubsetError(ValueError):
    """Why the subset cannot be made, in words for the model and the user."""


def checkedConditions(conditions: Any, columns: List[str]) -> List[Dict[str, Any]]:
    if not isinstance(conditions, list) or not conditions:
        raise SubsetError("Say at least one condition: a column, an operator (< <= > >= = !=) and a value")
    if len(conditions) > MAX_CONDITIONS:
        raise SubsetError("At most %d conditions" % MAX_CONDITIONS)
    checked = []
    for condition in conditions:
        column = str((condition or {}).get("column") or "").strip()
        operator = str((condition or {}).get("op") or "").strip()
        if column not in columns:
            raise SubsetError("The table has no column %s (read its schema for the names)" % column)
        if operator not in OPERATORS:
            raise SubsetError("Unknown operator %s: use < <= > >= = !=" % operator)
        checked.append({"column": column, "op": operator, "value": (condition or {}).get("value")})
    return checked


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def meets(value: Any, condition: Dict[str, Any]) -> bool:
    """Numbers compare as numbers; anything else as text (yes/no for true/false)."""
    wanted = condition["value"]
    left, right = _number(value), _number(wanted)
    if left is not None and right is not None:
        return OPERATORS[condition["op"]](left, right)
    if isinstance(value, bool):
        value = "true" if value else "false"
    text, other = str(value).strip().lower(), str(wanted).strip().lower()
    other = {"yes": "true", "no": "false"}.get(other, other)
    if condition["op"] in ("=", "!="):
        return OPERATORS[condition["op"]](text, other)
    return False


def readRows(readPage: Callable[[int, int], Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every row, page by page (readPage(page, size) -> the viewer's page); refused past MAX_ROWS."""
    rows: List[Dict[str, Any]] = []
    page = 1
    while True:
        data = readPage(page, PAGE_SIZE) or {}
        if int(data.get("totalRows") or 0) > MAX_ROWS:
            raise SubsetError("The table has %s rows; the assistant chooses among at most %d (use the viewer)"
                              % (data.get("totalRows"), MAX_ROWS))
        batch = data.get("rows") or []
        rows.extend(batch)
        if len(batch) < PAGE_SIZE or len(rows) >= int(data.get("totalRows") or 0):
            return rows
        page += 1


def choose(schema: Dict[str, Any], rows: List[Dict[str, Any]], conditions: List[Dict[str, Any]]) -> Dict[str, Any]:
    """{kept: ids, removed: ids, examples}: the rows meeting every condition, and a few of the others' values."""
    columns = [column.get("name") for column in schema.get("columns") or []]
    index = {name: columns.index(name) for name in {condition["column"] for condition in conditions}}
    kept, removed, examples = [], [], []
    for row in rows:
        values = row.get("values") or []
        picked = {name: values[position] if position < len(values) else None for name, position in index.items()}
        if all(meets(picked[condition["column"]], condition) for condition in conditions):
            kept.append(int(row["id"]))
        else:
            removed.append(int(row["id"]))
            if len(examples) < EXAMPLES:
                examples.append(dict(picked, id=row["id"]))
    return {"kept": kept, "removed": removed, "examples": examples}


def plan(schema: Dict[str, Any], readPage: Callable[[int, int], Dict[str, Any]], conditions: Any,
         action: Optional[str]) -> Dict[str, Any]:
    columns = [column.get("name") for column in schema.get("columns") or []]
    checked = checkedConditions(conditions, columns)
    actions = [str(item) for item in schema.get("actions") or []]
    if not actions:
        raise SubsetError("A subset of this table cannot be made")
    if action and action not in actions:
        raise SubsetError("What it makes must be one of: %s" % ", ".join(actions))
    chosen = choose(schema, readRows(readPage), checked)
    if not chosen["kept"]:
        raise SubsetError("No row meets those conditions; nothing would be kept")
    return dict(chosen, conditions=checked, action=action or actions[0], actions=actions,
                total=len(chosen["kept"]) + len(chosen["removed"]))
