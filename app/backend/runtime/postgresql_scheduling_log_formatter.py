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
from typing import Any, Dict, List


WAITING_STATE_KEYS = (
    "pendingParents",
    "missingInputs",
    "inputRestoreErrors",
    "validationErrors",
)


def _text(
        value,
        fallback: str,
) -> str:
    text = str(
        value
        if value is not None
        else ""
    ).strip()

    return text or fallback


def _quoted(
        value,
        fallback: str,
) -> str:
    text = _text(
        value,
        fallback,
    )

    text = text.replace(
        '"',
        "'",
    )

    return '"%s"' % text


def _sentence(
        value,
) -> str:
    text = str(
        value
        or ""
    ).strip()

    if not text:
        return ""

    if text.endswith(
            (
                ".",
                "!",
                "?",
            )
    ):
        return text

    return text + "."


def _freeze(
        value,
):
    if isinstance(
            value,
            dict,
    ):
        return tuple(
            sorted(
                (
                    str(key),
                    _freeze(item),
                )
                for key, item
                in value.items()
            )
        )

    if isinstance(
            value,
            (
                list,
                tuple,
                set,
            ),
    ):
        frozenItems = [
            _freeze(item)
            for item in value
        ]

        return tuple(
            sorted(
                frozenItems,
                key=repr,
            )
        )

    return str(
        value
        if value is not None
        else ""
    )


class PostgresqlSchedulingLogFormatter:
    """
    Convert internal PostgreSQL readiness reports into messages intended
    for users reading schedule.log.
    """

    def buildFingerprint(
            self,
            readiness: Dict[str, Any],
    ):
        return tuple(
            (
                key,
                _freeze(
                    readiness.get(key)
                    or []
                ),
            )
            for key
            in WAITING_STATE_KEYS
        )

    def buildWaitingMessage(
            self,
            readiness: Dict[str, Any],
            heartbeat: bool = False,
    ) -> str:
        lines = self.buildWaitingLines(
            readiness
        )

        heading = (
            "Protocol is still scheduled "
            "for the following reason(s):"
            if heartbeat
            else
            "Protocol is scheduled for "
            "the following reason(s):"
        )

        return "\n".join(
            [
                heading,
            ]
            + [
                "  - %s" % line
                for line in lines
            ]
        )

    def buildWaitingLines(
            self,
            readiness: Dict[str, Any],
    ) -> List[str]:
        lines = []

        pendingParents = sorted(
            readiness.get(
                "pendingParents"
            )
            or [],
            key=self._pendingSortKey,
        )

        for item in pendingParents:
            self._appendUnique(
                lines,
                self._formatPendingParent(
                    item
                ),
            )

        missingInputs = sorted(
            readiness.get(
                "missingInputs"
            )
            or [],
            key=self._inputSortKey,
        )

        for item in missingInputs:
            self._appendUnique(
                lines,
                self._formatMissingInput(
                    item
                ),
            )

        inputRestoreErrors = sorted(
            readiness.get(
                "inputRestoreErrors"
            )
            or [],
            key=self._inputSortKey,
        )

        for item in inputRestoreErrors:
            self._appendUnique(
                lines,
                self._formatInputRestoreError(
                    item
                ),
            )

        validationErrors = sorted(
            str(error).strip()
            for error in (
                readiness.get(
                    "validationErrors"
                )
                or []
            )
            if str(
                error
                or ""
            ).strip()
        )

        for error in validationErrors:
            self._appendUnique(
                lines,
                (
                    "Input data is not ready yet: %s"
                    % _sentence(error)
                ),
            )

        if not lines:
            lines.append(
                "Dependencies or input data "
                "must change before execution "
                "can start."
            )

        return lines

    def _formatPendingParent(
            self,
            item,
    ) -> str:
        if not isinstance(
                item,
                dict,
        ):
            return (
                "A required protocol is not "
                "ready yet."
            )

        protocolId = _text(
            item.get(
                "protocolId"
            ),
            "unknown",
        )

        status = _text(
            item.get(
                "status"
            ),
            "unknown",
        )

        reason = str(
            item.get(
                "reason"
            )
            or ""
        ).strip()

        if (
                reason
                == "input_parent_not_finished"
        ):
            return (
                "Input protocol %s is %s; "
                "it must finish before this "
                "protocol can start."
                % (
                    protocolId,
                    status,
                )
            )

        if (
                reason
                == "prerequisite_not_terminal"
        ):
            return (
                "Prerequisite protocol %s is %s; "
                "it must stop before this "
                "protocol can start."
                % (
                    protocolId,
                    status,
                )
            )

        if (
                reason
                == "dependency_not_finished"
        ):
            return (
                "Dependency protocol %s is %s; "
                "it must finish before this "
                "protocol can start."
                % (
                    protocolId,
                    status,
                )
            )

        return (
            "Protocol %s is %s and is not "
            "ready yet."
            % (
                protocolId,
                status,
            )
        )

    def _formatMissingInput(
            self,
            item,
    ) -> str:
        if not isinstance(
                item,
                dict,
        ):
            return (
                "A required input is not "
                "available yet."
            )

        inputName = _quoted(
            item.get(
                "inputName"
            ),
            "input",
        )

        reason = str(
            item.get(
                "reason"
            )
            or ""
        ).strip()

        if (
                reason
                == "parent_output_not_available"
        ):
            outputName = _quoted(
                item.get(
                    "parentOutputName"
                ),
                "required output",
            )

            parentProtocolId = _text(
                item.get(
                    "parentProtocolId"
                ),
                "unknown",
            )

            return (
                "Output %s from protocol %s "
                "is not available yet for "
                "input %s."
                % (
                    outputName,
                    parentProtocolId,
                    inputName,
                )
            )

        if (
                reason
                == "parent_output_empty"
        ):
            outputName = _quoted(
                item.get(
                    "parentOutputName"
                ),
                "required output",
            )

            parentProtocolId = _text(
                item.get(
                    "parentProtocolId"
                ),
                "unknown",
            )

            return (
                "Output %s from protocol %s "
                "does not contain items yet "
                "for input %s."
                % (
                    outputName,
                    parentProtocolId,
                    inputName,
                )
            )

        if reason in {
            "missing_parent_protocol",
            "parent_protocol_not_found",
        }:
            return (
                "The parent protocol required "
                "by input %s is not available."
                % inputName
            )

        return (
            "Input %s is not available yet."
            % inputName
        )

    def _formatInputRestoreError(
            self,
            item,
    ) -> str:
        if not isinstance(
                item,
                dict,
        ):
            return (
                "A required input could not "
                "be prepared yet."
            )

        inputName = _quoted(
            item.get(
                "inputName"
            ),
            "input",
        )

        error = _sentence(
            item.get(
                "error"
            )
            or (
                "The input could not "
                "be reconstructed"
            )
        )

        return (
            "Input %s could not be "
            "prepared yet: %s"
            % (
                inputName,
                error,
            )
        )

    @staticmethod
    def _pendingSortKey(
            item,
    ):
        if not isinstance(
                item,
                dict,
        ):
            return (
                99,
                "",
            )

        reasonPriority = {
            "input_parent_not_finished": 0,
            "prerequisite_not_terminal": 1,
            "dependency_not_finished": 2,
        }

        reason = str(
            item.get(
                "reason"
            )
            or ""
        )

        protocolId = str(
            item.get(
                "protocolId"
            )
            or ""
        )

        return (
            reasonPriority.get(
                reason,
                99,
            ),
            protocolId,
        )

    @staticmethod
    def _inputSortKey(
            item,
    ):
        if not isinstance(
                item,
                dict,
        ):
            return (
                "",
                0,
            )

        return (
            str(
                item.get(
                    "inputName"
                )
                or ""
            ),
            int(
                item.get(
                    "itemIndex"
                )
                or 0
            ),
        )

    @staticmethod
    def _appendUnique(
            lines,
            line,
    ) -> None:
        line = str(
            line
            or ""
        ).strip()

        if (
                line
                and line not in lines
        ):
            lines.append(
                line
            )