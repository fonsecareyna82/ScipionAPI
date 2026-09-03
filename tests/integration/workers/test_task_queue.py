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
import os


def test_TaskQueueConnectsToConfiguredBrokerAndBackend():
    from app.workers.task_queue import celeryApp

    expectedBrokerUrl = (
        os.getenv("BROKER_URL")
        or "redis://localhost:6379/0"
    )

    expectedBackendUrl = (
        os.getenv("RESULT_BACKEND_URL")
        or expectedBrokerUrl
    )

    assert celeryApp.conf.broker_url == expectedBrokerUrl
    assert celeryApp.conf.result_backend == expectedBackendUrl

    with celeryApp.connection_for_write() as connection:
        connection.ensure_connection(
            max_retries=1,
        )

    backendClient = celeryApp.backend.client

    assert backendClient.ping() is True