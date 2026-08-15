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
import scipionapi_cli.install as installModule


def test_ResolveApiPortUsesRequestedPort():
    assert installModule._resolveApiPort(
        {"API_PORT": "41000"},
        requestedApiPort=42000,
    ) == "42000"


def test_ResolveApiPortPreservesExistingPort():
    assert installModule._resolveApiPort(
        {"API_PORT": "41000"},
    ) == "41000"


def test_ResolveApiPortSelectsFreePort(monkeypatch):
    monkeypatch.setattr(
        installModule,
        "getFreePort",
        lambda: 45000,
    )

    assert installModule._resolveApiPort({}) == "45000"


def test_FindFreePortSkipsExcludedPort(monkeypatch):
    ports = iter([
        45000,
        45001,
    ])

    monkeypatch.setattr(
        installModule,
        "getFreePort",
        lambda: next(ports),
    )

    assert installModule._findFreePort(
        excludedPorts=["45000"],
    ) == "45001"