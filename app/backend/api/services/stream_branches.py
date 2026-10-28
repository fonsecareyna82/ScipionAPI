# ******************************************************************************
# *
# * Authors:     Yunior C. Fonseca Reyna
# *
# * Unidad de  Bioinformatica of Centro Nacional de Biotecnologia , CSIC
# *
# * This program is free software; you can redistribute it and/or modify
# * it under the terms of the GNU General Public License as published by
# * the Free Software Foundation; either version 3 of the License, or
# * (at your option) any later version.
# *
# * This program is distributed in the hope that it will be useful,
# * but WITHOUT ANY WARRANTY; without even the implied warranty of
# * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# * GNU General Public License for more details.
# *
# * You should have received a copy of the GNU General Public License
# * along with this program; if not, write to the Free Software
# * Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************
"""The acquisitions of a project and the branch of each one, for both streaming monitors.

A project may import several times (two grids, a second session on other movies): each import is an
acquisition, and its branch is the import and everything made from it, through the inputs of the
protocols. The monitor follows one branch at a time, so the chain it builds never mixes two acquisitions;
what comes after two branches are joined (a union of Sets) belongs to both. By default it follows the
acquisition that is still open and received something last, so a new import is followed from its first
item; the bell looks at every open one.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

# Open acquisitions of a project the bell looks at, each one costing a monitor of its own
MAX_ALERT_BRANCHES = 5


def readsNone(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]], output: Dict[str, Any]) -> bool:
    """Whether the protocol of ``output`` reads none of ``outputs``: it imports what it writes."""
    known = {(other["protocolId"], other["outputName"]) for other in outputs}
    return not any(tuple(ref) in known for ref in inputs.get(output["protocolId"], []))


def branchProtocols(inputs: Dict[str, List[tuple]], rootProtocolId: str) -> Set[str]:
    """The protocols made from ``rootProtocolId``, directly or through others, and itself."""
    readers: Dict[str, Set[str]] = {}
    for protocolId, refs in inputs.items():
        for parentProtocolId, _outputName in refs:
            readers.setdefault(str(parentProtocolId), set()).add(str(protocolId))
    branch = {str(rootProtocolId)}
    pending = [str(rootProtocolId)]
    while pending:
        for reader in readers.get(pending.pop(), ()):
            if reader not in branch:
                branch.add(reader)
                pending.append(reader)
    return branch


def branchOutputs(outputs: List[Dict[str, Any]], inputs: Dict[str, List[tuple]],
                  root: Optional[Dict[str, Any]],
                  acquisitions: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """The outputs of the branch of an acquisition; every output when there is none.

    Outputs made from no acquisition (particles or volumes imported, a protocol whose inputs are not
    known) belong to every branch, as they did before the monitor told branches apart.
    """
    if root is None:
        return outputs
    protocols = branchProtocols(inputs, root["protocolId"])
    anyBranch = set().union(*(branchProtocols(inputs, other["protocolId"]) for other in (acquisitions or [root])))
    return [output for output in outputs
            if output["protocolId"] in protocols or output["protocolId"] not in anyBranch]


def _last(output: Dict[str, Any], lastItemAt: Dict[int, Optional[str]]) -> str:
    return lastItemAt.get(output["setId"]) or ""


def followedAcquisition(acquisitions: List[Dict[str, Any]], lastItemAt: Dict[int, Optional[str]],
                        askedSetId: Optional[int]) -> Optional[Dict[str, Any]]:
    """The one asked for, else the open one that received something last, else the one that did (the one
    with more items when that is not known)."""
    asked = next((output for output in acquisitions if output["setId"] == askedSetId), None)
    if asked is not None or not acquisitions:
        return asked
    return max(acquisitions, key=lambda output: (bool(output.get("streaming")), _last(output, lastItemAt),
                                                 output.get("items") or 0, output["setId"]))


def alertAcquisitions(acquisitions: List[Dict[str, Any]],
                      lastItemAt: Dict[int, Optional[str]]) -> List[Optional[Dict[str, Any]]]:
    """The acquisitions the bell looks at: the open ones (the busiest first), else the one followed."""
    open_ = sorted((output for output in acquisitions if output.get("streaming")),
                   key=lambda output: _last(output, lastItemAt), reverse=True)
    return open_[:MAX_ALERT_BRANCHES] or [followedAcquisition(acquisitions, lastItemAt, None)]


def describeAcquisitions(acquisitions: List[Dict[str, Any]],
                         lastItemAt: Dict[int, Optional[str]]) -> List[Dict[str, Any]]:
    """The acquisitions as the monitor lists them to choose one."""
    return [{"setId": output["setId"], "stage": output["stage"], "protocolId": output["protocolId"],
             "label": output["label"],
             "outputName": output["outputName"], "items": output["items"], "streaming": output["streaming"],
             "lastItemAt": lastItemAt.get(output["setId"])}
            for output in sorted(acquisitions, key=lambda output: output["setId"])]
