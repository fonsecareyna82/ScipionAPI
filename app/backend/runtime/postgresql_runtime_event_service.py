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
import select
from typing import Any, Dict, Iterable, Optional

import psycopg2
from psycopg2 import sql
from psycopg2.extensions import (
    ISOLATION_LEVEL_AUTOCOMMIT,
)


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
    Publish non-critical PostgreSQL runtime events.

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
            "eventType": str(
                eventType
            ),
            "projectId": int(
                projectId
            ),
        }

        normalizedProtocolId = (
            _toOptionalInt(
                protocolId
            )
        )

        normalizedProtocolDbId = (
            _toOptionalInt(
                protocolDbId
            )
        )

        if normalizedProtocolId is not None:
            event["protocolId"] = (
                normalizedProtocolId
            )

        if normalizedProtocolDbId is not None:
            event["protocolDbId"] = (
                normalizedProtocolDbId
            )

        for key, value in eventData.items():
            if value is not None:
                event[key] = value

        channel = buildRuntimeEventChannel(
            projectId
        )

        payload = json.dumps(
            event,
            ensure_ascii=False,
            separators=(
                ",",
                ":",
            ),
            default=str,
        )

        try:
            db.execute(
                """
                SELECT pg_notify(
                    %s,
                    %s
                )
                """,
                (
                    channel,
                    payload,
                ),
            )

            return True

        except Exception:
            logger.warning(
                "Could not publish PostgreSQL "
                "runtime event. "
                "projectId=%s eventType=%s "
                "protocolId=%s "
                "protocolDbId=%s",
                projectId,
                eventType,
                protocolId,
                protocolDbId,
                exc_info=True,
            )

            connection = getattr(
                db,
                "conn",
                None,
            )

            if connection is not None:
                try:
                    connection.rollback()
                except Exception:
                    pass

            return False


class PostgresqlRuntimeEventListener:
    """
    Listen for dependency changes in one PostgreSQL project.

    A dedicated autocommit connection is required because the worker's
    normal mapper connection continues being used for runtime queries.
    """

    def __init__(
            self,
            *,
            projectId: int,
            databaseUrl: Optional[str] = None,
    ):
        self.projectId = int(
            projectId
        )

        self.databaseUrl = (
            databaseUrl
            or os.environ.get(
                "DATABASE_URL"
            )
        )

        self.channel = (
            buildRuntimeEventChannel(
                self.projectId
            )
        )

        self.connection = None
        self.cursor = None

        self.watchedProtocolIds = set()
        self.watchedProtocolDbIds = set()

    def open(
            self,
    ) -> None:
        if self.connection is not None:
            return

        if not self.databaseUrl:
            raise RuntimeError(
                "DATABASE_URL is required "
                "to listen for PostgreSQL "
                "runtime events."
            )

        connection = psycopg2.connect(
            self.databaseUrl
        )

        connection.set_isolation_level(
            ISOLATION_LEVEL_AUTOCOMMIT
        )

        cursor = connection.cursor()

        cursor.execute(
            sql.SQL(
                "LISTEN {}"
            ).format(
                sql.Identifier(
                    self.channel
                )
            )
        )

        self.connection = connection
        self.cursor = cursor

    def close(
            self,
    ) -> None:
        cursor = self.cursor
        connection = self.connection

        self.cursor = None
        self.connection = None

        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass

        if connection is not None:
            try:
                connection.close()
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
            for protocolId in (
                _toOptionalInt(value)
                for value
                in protocolIds or []
            )
            if protocolId is not None
        }

        self.watchedProtocolDbIds = {
            protocolDbId
            for protocolDbId in (
                _toOptionalInt(value)
                for value
                in protocolDbIds or []
            )
            if protocolDbId is not None
        }

    def isRelevantEvent(
            self,
            event: Dict[str, Any],
    ) -> bool:
        try:
            eventProjectId = int(
                event.get(
                    "projectId"
                )
            )

        except (
                TypeError,
                ValueError,
        ):
            return False

        if eventProjectId != self.projectId:
            return False

        if (
                not self.watchedProtocolIds
                and not self.watchedProtocolDbIds
        ):
            return True

        eventProtocolId = (
            _toOptionalInt(
                event.get(
                    "protocolId"
                )
            )
        )

        eventProtocolDbId = (
            _toOptionalInt(
                event.get(
                    "protocolDbId"
                )
            )
        )

        return (
            eventProtocolId
            in self.watchedProtocolIds
            or eventProtocolDbId
            in self.watchedProtocolDbIds
        )

    def _popRelevantNotification(
            self,
    ) -> Optional[Dict[str, Any]]:
        connection = self.connection

        if connection is None:
            return None

        while connection.notifies:
            notification = (
                connection.notifies.pop(0)
            )

            try:
                event = json.loads(
                    notification.payload
                )

            except Exception:
                logger.debug(
                    "Ignoring malformed PostgreSQL "
                    "runtime notification: %s",
                    notification.payload,
                )

                continue

            if (
                    isinstance(
                        event,
                        dict,
                    )
                    and self.isRelevantEvent(
                        event
                    )
            ):
                return event

        return None

    def wait(
            self,
            timeoutSeconds: float,
    ) -> Optional[Dict[str, Any]]:
        self.open()

        queuedEvent = (
            self
            ._popRelevantNotification()
        )

        if queuedEvent is not None:
            return queuedEvent

        timeoutSeconds = max(
            0.0,
            float(
                timeoutSeconds
                or 0
            ),
        )

        readable, _, _ = select.select(
            [
                self.connection,
            ],
            [],
            [],
            timeoutSeconds,
        )

        if not readable:
            return None

        self.connection.poll()

        return (
            self
            ._popRelevantNotification()
        )