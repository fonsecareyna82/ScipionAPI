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

import app.backend.runtime.postgresql_runtime_event_service as runtimeEventService

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


def test_RuntimeEventPublisherSendsCompactJsonPayload(monkeypatch):
    db = FakeDb()
    publishedMessages = []
    closed = []

    class RedisClientStub:
        def publish(self, channel, payload):
            publishedMessages.append((channel, payload))

        def close(self):
            closed.append(True)

    monkeypatch.setenv("BROKER_URL", "redis://valkey.test:6379/0")
    monkeypatch.setattr(
        runtimeEventService.Redis,
        "from_url",
        lambda url, decode_responses=True: RedisClientStub(),
    )

    published = PostgresqlRuntimeEventPublisher.publish(
        db=db,
        projectId=7,
        eventType="set_updated",
        protocolDbId=20,
        outputName="outputSet",
        itemsCount=12,
    )

    assert published is True
    assert db.calls == []
    assert len(publishedMessages) == 1
    assert closed == [True]

    channel, rawPayload = publishedMessages[0]
    assert channel == "scipion_runtime_project_7"
    assert json.loads(rawPayload) == {
        "eventType": "set_updated",
        "projectId": 7,
        "protocolDbId": 20,
        "outputName": "outputSet",
        "itemsCount": 12,
    }

def test_RuntimeEventListenerUsesValkeyPubSub(monkeypatch):
    events = []
    messages = iter([
        {
            "type": "subscribe",
            "channel": "scipion_runtime_project_7",
            "data": 1,
        },
        {
            "type": "message",
            "channel": "scipion_runtime_project_7",
            "data": json.dumps({
                "eventType": "protocol_changed",
                "projectId": 7,
                "protocolId": 12,
            }),
        },
    ])

    class PubSubStub:
        def subscribe(self, channel):
            events.append(("subscribe", channel))

        def get_message(self, ignore_subscribe_messages=False, timeout=0):
            events.append(("get_message", ignore_subscribe_messages))
            return next(messages)

        def close(self):
            events.append("pubsub-close")

    class RedisClientStub:
        def pubsub(self, ignore_subscribe_messages=False):
            assert ignore_subscribe_messages is False
            return PubSubStub()

        def close(self):
            events.append("client-close")

    monkeypatch.setattr(
        runtimeEventService.Redis,
        "from_url",
        lambda url, decode_responses=True: RedisClientStub(),
    )

    listener = PostgresqlRuntimeEventListener(
        projectId=7,
        brokerUrl="redis://valkey.test:6379/0",
    )
    listener.setWatchedProtocols(protocolIds=[12])

    assert listener.wait(1) == {
        "eventType": "protocol_changed",
        "projectId": 7,
        "protocolId": 12,
    }

    listener.close()
    assert events == [
        ("subscribe", "scipion_runtime_project_7"),
        ("get_message", False),
        ("get_message", True),
        "pubsub-close",
        "client-close",
    ]



def test_RuntimeEventListenerAcceptsWatchedProtocolId():
    listener = (
        PostgresqlRuntimeEventListener(
            projectId=7,
            brokerUrl="redis://unused",
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
            brokerUrl="redis://unused",
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
            brokerUrl="redis://unused",
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