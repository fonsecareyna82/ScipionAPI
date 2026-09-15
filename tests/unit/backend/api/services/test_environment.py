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

import app.backend.api.services.environment as environmentModule


def test_RemoveCustomEnvironmentVariablesRemovesOnlyRequestedOverrides(
        tmp_path,
        monkeypatch,
):
    configPath = (
        tmp_path
        / "config"
        / "scipionweb_environment.json"
    )

    configPath.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    configPath.write_text(
        json.dumps(
            {
                "MOTIONCOR_HOME": (
                    "/custom/motioncor"
                ),
                "CUDA_LIB": (
                    "/custom/cuda"
                ),
                "OTHER_VARIABLE": (
                    "keep-me"
                ),
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv(
        "MOTIONCOR_HOME",
        "/custom/motioncor",
    )

    monkeypatch.setenv(
        "CUDA_LIB",
        "/custom/cuda",
    )

    monkeypatch.setenv(
        "OTHER_VARIABLE",
        "keep-me",
    )

    removed = (
        environmentModule
        .removeCustomEnvironmentVariables(
            str(tmp_path),
            {
                "MOTIONCOR_HOME",
                "MOTIONCOR_CUDA_LIB",
            },
        )
    )

    assert removed == {
        "MOTIONCOR_HOME",
    }

    stored = json.loads(
        configPath.read_text(
            encoding="utf-8"
        )
    )

    assert stored == {
        "CUDA_LIB": "/custom/cuda",
        "OTHER_VARIABLE": "keep-me",
    }

    assert (
        "MOTIONCOR_HOME"
        not in environmentModule.os.environ
    )

    assert (
        environmentModule.os.environ[
            "CUDA_LIB"
        ]
        == "/custom/cuda"
    )

    assert (
        environmentModule.os.environ[
            "OTHER_VARIABLE"
        ]
        == "keep-me"
    )