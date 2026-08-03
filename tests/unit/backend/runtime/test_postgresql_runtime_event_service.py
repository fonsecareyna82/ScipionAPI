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

from app.backend.runtime.postgresql_runtime_event_service import (
    PostgresqlRuntimeEventListener,
    PostgresqlRuntimeEventPublisher,
    buildRuntimeEventChannel,
)


class FakeDb:
    def __init__(self):
        self.calls = []
        self.conn = None

    def execute(
            self,
            query,
            params=None,
            commit=True,
    ):
        self.calls.append({
            "query": query,
            "params": params,
            "commit": commit,
        })


def test_RuntimeEventChannelIsScopedByProject():
    assert (
        buildRuntimeEventChannel(7)
        == "scipion_runtime_project_7"
    )


def test_RuntimeEventPublisherSendsCompactJsonPayload():
    db = FakeDb()

    published = (
        PostgresqlRuntimeEventPublisher
        .publish(
            db=db,
            projectId=7,
            eventType="set_updated",
            protocolDbId=20,
            outputName="outputSet",
            itemsCount=12,
        )
    )

    assert published is True
    assert len(db.calls) == 1

    channel, rawPayload = (
        db.calls[0]["params"]
    )

    assert channel == (
        "scipion_runtime_project_7"
    )

    assert json.loads(
        rawPayload
    ) == {
        "eventType": "set_updated",
        "projectId": 7,
        "protocolDbId": 20,
        "outputName": "outputSet",
        "itemsCount": 12,
    }


def test_RuntimeEventListenerAcceptsWatchedProtocolId():
    listener = (
        PostgresqlRuntimeEventListener(
            projectId=7,
            databaseUrl="unused",
        )
    )

    listener.setWatchedProtocols(
        protocolIds=[
            12,
        ],
    )

    assert listener.isRelevantEvent({
        "eventType": (
            "protocol_changed"
        ),
        "projectId": 7,
        "protocolId": 12,
    }) is True

    assert listener.isRelevantEvent({
        "eventType": (
            "protocol_changed"
        ),
        "projectId": 7,
        "protocolId": 13,
    }) is False


def test_RuntimeEventListenerAcceptsWatchedProtocolDbId():
    listener = (
        PostgresqlRuntimeEventListener(
            projectId=7,
            databaseUrl="unused",
        )
    )

    listener.setWatchedProtocols(
        protocolDbIds=[
            20,
        ],
    )

    assert listener.isRelevantEvent({
        "eventType": "set_updated",
        "projectId": 7,
        "protocolDbId": 20,
    }) is True

    assert listener.isRelevantEvent({
        "eventType": "set_updated",
        "projectId": 7,
        "protocolDbId": 21,
    }) is False


def test_RuntimeEventListenerRejectsAnotherProject():
    listener = (
        PostgresqlRuntimeEventListener(
            projectId=7,
            databaseUrl="unused",
        )
    )

    listener.setWatchedProtocols(
        protocolIds=[
            12,
        ],
    )

    assert listener.isRelevantEvent({
        "eventType": (
            "protocol_changed"
        ),
        "projectId": 8,
        "protocolId": 12,
    }) is False