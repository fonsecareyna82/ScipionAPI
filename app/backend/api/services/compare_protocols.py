"""Comparing two to four protocols of a project for the AI assistant: the parameters that differ (by their form's
names, options by their text), what each takes, what each produced and how long each ran. Every figure comes from
the database (workflow_report.describeProtocol); the model only explains it."""
from datetime import datetime
from typing import Any, Dict, List, Optional

MIN_PROTOCOLS = 2
MAX_PROTOCOLS = 4


def _minutes(run: Optional[Dict[str, Any]]) -> Optional[float]:
    if not run or not run.get("started") or not run.get("ended"):
        return None
    try:
        started = datetime.fromisoformat(run["started"])
        ended = datetime.fromisoformat(run["ended"])
    except ValueError:
        return None
    return round((ended - started).total_seconds() / 60, 1)


def compare(described: List[Dict[str, Any]]) -> Dict[str, Any]:
    """{protocols, parameters (the ones that differ), same (how many are equal), inputs, outputs}."""
    ids = [item["protocolId"] for item in described]
    labels: Dict[str, Dict[str, str]] = {}
    values: Dict[str, Dict[str, str]] = {}
    for item in described:
        for param in item["params"]:
            labels.setdefault(param["name"], {"label": param["label"], "section": param["section"]})
            values.setdefault(param["name"], {})[item["protocolId"]] = param["value"]
    differing, same = [], 0
    for name, byProtocol in values.items():
        if name == "runName":
            continue
        row = {pid: byProtocol.get(pid, "") for pid in ids}
        if len(set(row.values())) > 1:
            differing.append(dict(labels[name], name=name, values=row))
        else:
            same += 1
    outputs: Dict[str, Dict[str, Any]] = {}
    for item in described:
        for output in item["outputs"]:
            key = "%s (%s)" % (output["name"], output["type"])
            outputs.setdefault(key, {pid: None for pid in ids})[item["protocolId"]] = output["size"]
    return {
        "protocols": [{"protocolId": item["protocolId"], "label": item["label"], "protocol": item["protocol"],
                       "className": item["className"], "status": item["status"],
                       "minutes": _minutes(item.get("run"))} for item in described],
        "parameters": differing, "same": same,
        "inputs": {item["protocolId"]: ["#%s %s" % (ref["protocolId"], ref["output"]) for ref in item["inputs"]]
                   for item in described},
        "outputs": [{"output": key, "sizes": sizes} for key, sizes in outputs.items()],
    }
