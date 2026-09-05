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
import pytest

import scipionapi_cli.bootstrap as bootstrapModule


def test_ParseJavaMajorVersion():
    assert bootstrapModule._parseJavaMajorVersion(
        'openjdk version "21.0.8" 2025-07-15'
    ) == 21

    assert bootstrapModule._parseJavaMajorVersion(
        'openjdk version "11.0.28" 2025-07-15'
    ) == 11

    assert bootstrapModule._parseJavaMajorVersion(
        'java version "1.8.0_441"'
    ) == 8


def test_EnsureJavaRuntimeKeepsJava21(monkeypatch):
    runCalls = []

    monkeypatch.setattr(
        bootstrapModule,
        "_getJavaMajorVersion",
        lambda condaExe, envName: 21,
    )

    monkeypatch.setattr(
        bootstrapModule,
        "_run",
        lambda command, cwd=None: runCalls.append(command),
    )

    assert bootstrapModule._ensureJavaRuntime(
        "conda",
        "scipion4Web",
    ) == 21

    assert runCalls == []


def test_EnsureJavaRuntimeUpgradesOldJava(monkeypatch):
    versions = iter([11, 21])
    runCalls = []

    monkeypatch.setattr(
        bootstrapModule,
        "_getJavaMajorVersion",
        lambda condaExe, envName: next(versions),
    )

    monkeypatch.setattr(
        bootstrapModule,
        "_run",
        lambda command, cwd=None: runCalls.append(command),
    )

    assert bootstrapModule._ensureJavaRuntime(
        "conda",
        "scipion4Web",
    ) == 21

    assert runCalls == [[
        "conda",
        "install",
        "-y",
        "-n",
        "scipion4Web",
        "-c",
        "conda-forge",
        "openjdk=21",
    ]]


def test_EnsureJavaRuntimeFailsWhenInstalledJavaIsTooOld(monkeypatch):
    versions = iter([None, 17])

    monkeypatch.setattr(
        bootstrapModule,
        "_getJavaMajorVersion",
        lambda condaExe, envName: next(versions),
    )

    monkeypatch.setattr(
        bootstrapModule,
        "_run",
        lambda command, cwd=None: None,
    )

    with pytest.raises(RuntimeError, match="Java 21"):
        bootstrapModule._ensureJavaRuntime(
            "conda",
            "scipion4Web",
        )