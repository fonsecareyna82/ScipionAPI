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
import time
from contextlib import contextmanager


logger = logging.getLogger(__name__)


class RuntimePostgresqlObservabilityService:
    """Measure PostgreSQL runtime operations without persisting telemetry."""

    @contextmanager
    def measure(
            self,
            *,
            operation,
            db=None,
            **dimensions,
    ):
        operation = str(
            operation or ""
        ).strip()

        if not operation:
            raise ValueError(
                "operation is required"
            )

        metric = {
            key: value
            for key, value in dimensions.items()
            if value is not None
        }

        metric["operation"] = operation

        queryStatsBefore = self._getQueryStats(
            db
        )

        startedAt = time.perf_counter()
        succeeded = False
        errorClass = None

        try:
            yield metric
            succeeded = True

        except Exception as error:
            errorClass = error.__class__.__name__
            raise

        finally:
            queryStatsAfter = self._getQueryStats(
                db
            )

            metric["operation"] = operation
            metric["success"] = succeeded
            metric["durationSeconds"] = max(
                0.0,
                time.perf_counter() - startedAt,
            )

            metric["queryCount"] = max(
                0,
                int(queryStatsAfter["queryCount"])
                - int(queryStatsBefore["queryCount"]),
            )

            metric["failedQueryCount"] = max(
                0,
                int(queryStatsAfter["failedQueryCount"])
                - int(queryStatsBefore["failedQueryCount"]),
            )

            metric["querySeconds"] = max(
                0.0,
                float(queryStatsAfter["querySeconds"])
                - float(queryStatsBefore["querySeconds"]),
            )

            if errorClass is not None:
                metric["errorClass"] = errorClass

            logger.debug(
                "PostgreSQL runtime metric %s",
                json.dumps(
                    metric,
                    ensure_ascii=False,
                    separators=(",", ":"),
                    default=str,
                ),
            )

    @staticmethod
    def _getQueryStats(db):
        if db is None:
            return {
                "queryCount": 0,
                "failedQueryCount": 0,
                "querySeconds": 0.0,
            }

        getter = getattr(
            db,
            "getQueryStats",
            None,
        )

        if not callable(getter):
            return {
                "queryCount": 0,
                "failedQueryCount": 0,
                "querySeconds": 0.0,
            }

        stats = getter() or {}

        return {
            "queryCount": int(
                stats.get("queryCount") or 0
            ),
            "failedQueryCount": int(
                stats.get("failedQueryCount") or 0
            ),
            "querySeconds": float(
                stats.get("querySeconds") or 0.0
            ),
        }