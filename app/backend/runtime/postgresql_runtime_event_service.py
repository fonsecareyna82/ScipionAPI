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
import logging
import os
import time
from typing import Any, Dict, Iterable, Optional

from redis import Redis



logger = logging.getLogger(__name__)

RUNTIME_EVENT_CHANNEL_PREFIX = (
    "scipion_runtime_project_"
)

DEFAULT_RUNTIME_EVENT_WAIT_SECONDS = 90.0
FALLBACK_RUNTIME_POLL_SECONDS = 15.0


def buildRuntimeEventChannel(
        projectId: int,
) -> str:
    return (
        RUNTIME_EVENT_CHANNEL_PREFIX
        + str(int(projectId))
    )


def _toOptionalInt(
        value,
):
    try:
        return int(value)

    except (
            TypeError,
            ValueError,
    ):
        return None


class PostgresqlRuntimeEventPublisher:
    """
    Publish non-critical runtime events through Valkey.

    Event delivery is only an optimization. A notification failure must
    never fail protocol persistence or execution because workers retain
    a periodic safety check.
    """

    @classmethod
    def publish(
            cls,
            *,
            db,
            projectId: int,
            eventType: str,
            protocolId=None,
            protocolDbId=None,
            **eventData,
    ) -> bool:
        if db is None:
            return False

        event = {
            "eventType": str(eventType),
            "projectId": int(projectId),
        }

        normalizedProtocolId = _toOptionalInt(protocolId)
        normalizedProtocolDbId = _toOptionalInt(protocolDbId)

        if normalizedProtocolId is not None:
            event["protocolId"] = normalizedProtocolId

        if normalizedProtocolDbId is not None:
            event["protocolDbId"] = normalizedProtocolDbId

        for key, value in eventData.items():
            if value is not None:
                event[key] = value

        channel = buildRuntimeEventChannel(projectId)
        payload = json.dumps(
            event,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

        brokerUrl = (
            os.environ.get("BROKER_URL")
            or "redis://localhost:6379/0"
        ).strip()
        client = None

        try:
            client = Redis.from_url(brokerUrl, decode_responses=True)
            client.publish(channel, payload)
            return True

        except Exception:
            logger.warning(
                "Could not publish Valkey runtime event. "
                "projectId=%s eventType=%s protocolId=%s protocolDbId=%s",
                projectId,
                eventType,
                protocolId,
                protocolDbId,
                exc_info=True,
            )
            return False

        finally:
            if client is not None:
                close = getattr(client, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass


class PostgresqlRuntimeEventListener:
    """
    Listen for dependency changes in one PostgreSQL project through Valkey.

    Waiting workers use Valkey Pub/Sub so they do not retain dedicated
    PostgreSQL LISTEN connections while blocked.
    """

    def __init__(
            self,
            *,
            projectId: int,
            brokerUrl: Optional[str] = None,
    ):
        self.projectId = int(projectId)
        self.brokerUrl = (
            brokerUrl
            or os.environ.get("BROKER_URL")
            or "redis://localhost:6379/0"
        ).strip()
        self.channel = buildRuntimeEventChannel(self.projectId)
        self.client = None
        self.pubsub = None
        self.watchedProtocolIds = set()
        self.watchedProtocolDbIds = set()

    def open(self) -> None:
        if self.pubsub is not None:
            return

        client = Redis.from_url(self.brokerUrl, decode_responses=True)
        pubsub = client.pubsub(ignore_subscribe_messages=False)

        try:
            pubsub.subscribe(self.channel)
            self._waitForSubscription(pubsub)
        except Exception:
            try:
                pubsub.close()
            except Exception:
                pass

            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass
            raise

        self.client = client
        self.pubsub = pubsub

    def _waitForSubscription(self, pubsub) -> None:
        deadline = time.monotonic() + 5.0

        while True:
            remainingSeconds = max(0.0, deadline - time.monotonic())
            message = pubsub.get_message(
                ignore_subscribe_messages=False,
                timeout=remainingSeconds,
            )

            if message is None:
                raise TimeoutError(
                    "Timed out subscribing to Valkey runtime event channel %s."
                    % self.channel
                )

            messageType = str(message.get("type") or "").strip().lower()
            channel = message.get("channel")
            if isinstance(channel, bytes):
                channel = channel.decode("utf-8")

            if messageType == "subscribe" and str(channel) == self.channel:
                return

            if time.monotonic() >= deadline:
                raise TimeoutError(
                    "Timed out subscribing to Valkey runtime event channel %s."
                    % self.channel
                )

    def close(self) -> None:
        pubsub = self.pubsub
        client = self.client
        self.pubsub = None
        self.client = None

        if pubsub is not None:
            try:
                pubsub.close()
            except Exception:
                pass

        if client is not None:
            close = getattr(client, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def setWatchedProtocols(
            self,
            *,
            protocolIds: Iterable = (),
            protocolDbIds: Iterable = (),
    ) -> None:
        self.watchedProtocolIds = {
            protocolId
            for protocolId in (_toOptionalInt(value) for value in protocolIds or [])
            if protocolId is not None
        }
        self.watchedProtocolDbIds = {
            protocolDbId
            for protocolDbId in (_toOptionalInt(value) for value in protocolDbIds or [])
            if protocolDbId is not None
        }

    def isRelevantEvent(self, event: Dict[str, Any]) -> bool:
        try:
            eventProjectId = int(event.get("projectId"))
        except (TypeError, ValueError):
            return False

        if eventProjectId != self.projectId:
            return False

        if not self.watchedProtocolIds and not self.watchedProtocolDbIds:
            return True

        eventProtocolId = _toOptionalInt(event.get("protocolId"))
        eventProtocolDbId = _toOptionalInt(event.get("protocolDbId"))

        return (
            eventProtocolId in self.watchedProtocolIds
            or eventProtocolDbId in self.watchedProtocolDbIds
        )

    def _decodeMessage(self, message) -> Optional[Dict[str, Any]]:
        if not isinstance(message, dict):
            return None

        if message.get("type") not in {"message", "pmessage"}:
            return None

        payload = message.get("data")
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8")

        try:
            event = json.loads(payload)
        except Exception:
            logger.debug(
                "Ignoring malformed Valkey runtime notification: %s",
                payload,
            )
            return None

        if isinstance(event, dict) and self.isRelevantEvent(event):
            return event

        return None

    def wait(self, timeoutSeconds: float) -> Optional[Dict[str, Any]]:
        self.open()
        timeoutSeconds = max(0.0, float(timeoutSeconds or 0))
        deadline = time.monotonic() + timeoutSeconds

        while True:
            remainingSeconds = max(0.0, deadline - time.monotonic())
            message = self.pubsub.get_message(
                ignore_subscribe_messages=True,
                timeout=remainingSeconds,
            )

            if message is None:
                return None

            event = self._decodeMessage(message)
            if event is not None:
                return event

            if time.monotonic() >= deadline:
                return None
