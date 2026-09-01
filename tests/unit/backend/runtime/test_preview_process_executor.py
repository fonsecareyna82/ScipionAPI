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
# * along with this program; if not, write to the
# * Free Software Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA
# * 02111-1307  USA
# *
# *  All comments concerning this program package may be sent to the
# *  e-mail address 'scipion@cnb.csic.es'
# *
# ******************************************************************************

from app.backend.runtime import preview_process_executor


class FakeExecutor:
    def __init__(
            self,
            max_workers,
            mp_context,
    ):
        self.max_workers = max_workers
        self.mp_context = mp_context


def test_InteractiveAndBackgroundPreviewExecutorsAreSeparated(
        monkeypatch,
):
    createdExecutors = []

    def createFakeExecutor(
            max_workers,
            mp_context,
    ):
        executor = FakeExecutor(
            max_workers=max_workers,
            mp_context=mp_context,
        )
        createdExecutors.append(
            executor
        )
        return executor

    monkeypatch.setattr(
        preview_process_executor,
        "ProcessPoolExecutor",
        createFakeExecutor,
    )

    monkeypatch.setattr(
        preview_process_executor,
        "_interactivePreviewExecutor",
        None,
    )

    monkeypatch.setattr(
        preview_process_executor,
        "_backgroundThumbnailExecutor",
        None,
    )

    interactiveExecutor = (
        preview_process_executor
        ._getInteractivePreviewExecutor()
    )

    backgroundExecutor = (
        preview_process_executor
        ._getBackgroundThumbnailExecutor()
    )

    assert interactiveExecutor is not backgroundExecutor
    assert len(createdExecutors) == 2

    assert (
            interactiveExecutor.max_workers
            == preview_process_executor.INTERACTIVE_PREVIEW_WORKERS
    )

    assert (
            backgroundExecutor.max_workers
            == preview_process_executor.BACKGROUND_THUMBNAIL_WORKERS
    )

    assert interactiveExecutor.max_workers == 2
    assert backgroundExecutor.max_workers == 1

    assert (
        preview_process_executor
        ._getInteractivePreviewExecutor()
        is interactiveExecutor
    )

    assert (
        preview_process_executor
        ._getBackgroundThumbnailExecutor()
        is backgroundExecutor
    )

    assert len(createdExecutors) == 2