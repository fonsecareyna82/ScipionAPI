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
from app.backend.runtime.postgresql_scheduling_log_formatter import (
    PostgresqlSchedulingLogFormatter,
)


def buildReadiness(
        *,
        pendingParents=None,
        missingInputs=None,
        inputRestoreErrors=None,
        validationErrors=None,
):
    return {
        "pendingParents": (
            pendingParents
            or []
        ),
        "missingInputs": (
            missingInputs
            or []
        ),
        "inputRestoreErrors": (
            inputRestoreErrors
            or []
        ),
        "validationErrors": (
            validationErrors
            or []
        ),
    }


def test_WaitingMessageFormatsParentAndPrerequisite():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    readiness = buildReadiness(
        pendingParents=[
            {
                "protocolDbId": 109,
                "protocolId": 9,
                "status": "scheduled",
                "reason": (
                    "prerequisite_not_terminal"
                ),
            },
            {
                "protocolDbId": 20,
                "protocolId": 2,
                "status": "running",
                "reason": (
                    "input_parent_not_finished"
                ),
            },
        ],
    )

    assert (
        formatter.buildWaitingMessage(
            readiness
        )
        == (
            "Protocol is scheduled for "
            "the following reason(s):\n"
            "  - Input protocol 2 is running; "
            "it must finish before this "
            "protocol can start.\n"
            "  - Prerequisite protocol 9 is "
            "scheduled; it must stop before "
            "this protocol can start."
        )
    )


def test_WaitingMessageFormatsMissingOutput():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    readiness = buildReadiness(
        missingInputs=[
            {
                "inputName": (
                    "inputParticles"
                ),
                "itemIndex": 0,
                "parentProtocolId": 2,
                "parentOutputName": (
                    "outputParticles"
                ),
                "reason": (
                    "parent_output_not_available"
                ),
            },
        ],
    )

    assert (
        formatter.buildWaitingMessage(
            readiness
        )
        == (
            "Protocol is scheduled for "
            "the following reason(s):\n"
            "  - Output \"outputParticles\" "
            "from protocol 2 is not available "
            "yet for input \"inputParticles\"."
        )
    )


def test_WaitingMessageFormatsEmptyStreamingOutput():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    readiness = buildReadiness(
        missingInputs=[
            {
                "inputName": (
                    "inputSetOfTiltSeries"
                ),
                "itemIndex": 0,
                "parentProtocolId": 1568,
                "parentOutputName": (
                    "TiltSeries"
                ),
                "reason": (
                    "parent_output_empty"
                ),
            },
        ],
    )

    assert (
        formatter.buildWaitingMessage(
            readiness
        )
        == (
            "Protocol is scheduled for "
            "the following reason(s):\n"
            "  - Output \"TiltSeries\" "
            "from protocol 1568 does not "
            "contain items yet for input "
            "\"inputSetOfTiltSeries\"."
        )
    )


def test_WaitingMessageFormatsValidationErrors():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    readiness = buildReadiness(
        validationErrors=[
            (
                "At least 10 particles "
                "are required"
            ),
        ],
    )

    assert (
        formatter.buildWaitingMessage(
            readiness
        )
        == (
            "Protocol is scheduled for "
            "the following reason(s):\n"
            "  - Input data is not ready yet: "
            "At least 10 particles are required."
        )
    )


def test_HeartbeatUsesStillScheduledHeading():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    readiness = buildReadiness(
        pendingParents=[
            {
                "protocolId": 2,
                "status": "running",
                "reason": (
                    "input_parent_not_finished"
                ),
            },
        ],
    )

    message = (
        formatter.buildWaitingMessage(
            readiness,
            heartbeat=True,
        )
    )

    assert message.startswith(
        "Protocol is still scheduled "
        "for the following reason(s):"
    )


def test_FingerprintIgnoresListOrdering():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    first = buildReadiness(
        pendingParents=[
            {
                "protocolId": 2,
                "status": "running",
                "reason": (
                    "input_parent_not_finished"
                ),
            },
            {
                "protocolId": 9,
                "status": "scheduled",
                "reason": (
                    "prerequisite_not_terminal"
                ),
            },
        ],
    )

    second = buildReadiness(
        pendingParents=list(
            reversed(
                first["pendingParents"]
            )
        ),
    )

    assert (
        formatter.buildFingerprint(
            first
        )
        == formatter.buildFingerprint(
            second
        )
    )


def test_FingerprintChangesWhenProtocolStatusChanges():
    formatter = (
        PostgresqlSchedulingLogFormatter()
    )

    running = buildReadiness(
        pendingParents=[
            {
                "protocolId": 2,
                "status": "running",
                "reason": (
                    "input_parent_not_finished"
                ),
            },
        ],
    )

    finished = buildReadiness(
        pendingParents=[
            {
                "protocolId": 2,
                "status": "finished",
                "reason": (
                    "input_parent_not_finished"
                ),
            },
        ],
    )

    assert (
        formatter.buildFingerprint(
            running
        )
        != formatter.buildFingerprint(
            finished
        )
    )