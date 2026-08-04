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

from app.backend.runtime.runtime_sqlite_compatibility_reporter import RuntimeSqliteCompatibilityReporter


def test_ReportWritesStructuredSqliteCompatibilityEvent(caplog):
    reporter = RuntimeSqliteCompatibilityReporter()

    with caplog.at_level(logging.INFO, logger="app.backend.runtime.runtime_sqlite_compatibility_reporter"):
        event = reporter.report(pathKind="native_sqlite_working_set", projectId=4, protocolId=17, protocolClass="ProtocolStub", outputName=None, setClass="SetOfParticles", creatorKind="spa", reason="undeclared_output_set_class", legacyPath="/tmp/particles.sqlite")

    message = caplog.records[-1].getMessage()
    marker, payloadText = message.split(" ", 1)

    assert marker == RuntimeSqliteCompatibilityReporter.EVENT_MARKER
    assert json.loads(payloadText) == event