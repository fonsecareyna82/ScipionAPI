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
import json

from app.backend.runtime.celery_queue_routing_service import (
    loadCeleryQueueRouting,
    resolveCeleryQueueForHost,
)


def test_LoadCeleryQueueRoutingReturnsEmptyWithoutScipionHome():
    assert loadCeleryQueueRouting(None) == {}
    assert loadCeleryQueueRouting("") == {}


def test_LoadCeleryQueueRoutingReturnsEmptyWhenFileMissing(tmp_path):
    assert loadCeleryQueueRouting(str(tmp_path)) == {}


def test_LoadCeleryQueueRoutingReadsMapping(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "celery_queue_routing.json").write_text(
        json.dumps({"gpu-cluster": "protocols-gpu", "debug": "protocols"}),
        encoding="utf-8",
    )

    routing = loadCeleryQueueRouting(str(tmp_path))

    assert routing == {
        "gpu-cluster": "protocols-gpu",
        "debug": "protocols",
    }


def test_LoadCeleryQueueRoutingIgnoresBlankEntriesAndInvalidJson(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "celery_queue_routing.json").write_text(
        json.dumps({"gpu-cluster": "protocols-gpu", "": "protocols", "empty-value": ""}),
        encoding="utf-8",
    )

    routing = loadCeleryQueueRouting(str(tmp_path))

    assert routing == {"gpu-cluster": "protocols-gpu"}


def test_LoadCeleryQueueRoutingReturnsEmptyOnMalformedJson(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "celery_queue_routing.json").write_text(
        "{not valid json",
        encoding="utf-8",
    )

    assert loadCeleryQueueRouting(str(tmp_path)) == {}


def test_LoadCeleryQueueRoutingReturnsEmptyWhenNotAnObject(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "celery_queue_routing.json").write_text(
        json.dumps(["gpu-cluster", "protocols-gpu"]),
        encoding="utf-8",
    )

    assert loadCeleryQueueRouting(str(tmp_path)) == {}


def test_ResolveCeleryQueueForHostReturnsMappedQueue(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "celery_queue_routing.json").write_text(
        json.dumps({"gpu-cluster": "protocols-gpu"}),
        encoding="utf-8",
    )

    assert resolveCeleryQueueForHost(str(tmp_path), "gpu-cluster") == "protocols-gpu"


def test_ResolveCeleryQueueForHostReturnsNoneWhenUnmapped(tmp_path):
    configDir = tmp_path / "config"
    configDir.mkdir()
    (configDir / "celery_queue_routing.json").write_text(
        json.dumps({"gpu-cluster": "protocols-gpu"}),
        encoding="utf-8",
    )

    assert resolveCeleryQueueForHost(str(tmp_path), "localhost") is None


def test_ResolveCeleryQueueForHostReturnsNoneForBlankHost(tmp_path):
    assert resolveCeleryQueueForHost(str(tmp_path), "") is None
    assert resolveCeleryQueueForHost(str(tmp_path), None) is None
