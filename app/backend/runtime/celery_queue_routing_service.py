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
"""
Operator-controlled mapping from a protocol's Scipion host (the same
key configured per-protocol via hosts.conf, e.g. "localhost", "debug",
"gpu-cluster") to a named Celery queue.

This lets a multi-node deployment run a protocols worker on a specific
node consuming from a specific queue (via `scipionapi runtime start
--role protocols --queue protocols-gpu`), and have only protocols whose
host is mapped to that queue dispatched there. Hosts with no mapping
entry fall back to the default "protocols" queue exactly as before this
mechanism existed, so an unconfigured deployment sees no behavior change.
"""
import json
import os
from typing import Dict, Optional

CELERY_QUEUE_ROUTING_FILE_NAME = "celery_queue_routing.json"


def _getCeleryQueueRoutingPath(scipionHome: str) -> str:
    return os.path.join(
        scipionHome,
        "config",
        CELERY_QUEUE_ROUTING_FILE_NAME,
    )


def loadCeleryQueueRouting(scipionHome: Optional[str]) -> Dict[str, str]:
    # Read-only, best-effort load of the host-name -> celery-queue-name
    # mapping. Any problem (missing file, invalid JSON, wrong shape)
    # silently yields an empty mapping so dispatch falls back to the
    # default queue instead of failing a protocol launch.
    if not scipionHome:
        return {}

    path = _getCeleryQueueRoutingPath(scipionHome)

    if not os.path.isfile(path):
        return {}

    try:
        with open(path, "r", encoding="utf-8") as file:
            raw = json.load(file)
    except Exception:
        return {}

    if not isinstance(raw, dict):
        return {}

    routing = {}

    for hostName, queueName in raw.items():
        cleanHostName = str(hostName or "").strip()
        cleanQueueName = str(queueName or "").strip()

        if cleanHostName and cleanQueueName:
            routing[cleanHostName] = cleanQueueName

    return routing


def resolveCeleryQueueForHost(
        scipionHome: Optional[str],
        hostName: Optional[str],
) -> Optional[str]:
    # Return the mapped queue name for hostName, or None when unmapped
    # (callers should fall back to the default queue in that case).
    cleanHostName = str(hostName or "").strip()

    if not cleanHostName:
        return None

    routing = loadCeleryQueueRouting(scipionHome)

    return routing.get(cleanHostName)
