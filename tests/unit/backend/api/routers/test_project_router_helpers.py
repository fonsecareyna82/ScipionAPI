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
def test_NormalizeErrorsWithNone(projectRouterModule):
    assert projectRouterModule._normalizeErrors(None) == ["Unknown error"]


def test_NormalizeErrorsWithScalar(projectRouterModule):
    assert projectRouterModule._normalizeErrors("boom") == ["boom"]


def test_NormalizeErrorsWithList(projectRouterModule):
    assert projectRouterModule._normalizeErrors(["a", 2, None]) == ["a", "2", "None"]


def test_EnsureDefaultLogChannelsAddsMissingDefaults(projectRouterModule):
    channels = [{"id": "stdout", "label": "Stdout Custom"}]

    result = projectRouterModule._ensureDefaultLogChannels(channels)

    ids = [item["id"] for item in result]
    assert "stdout" in ids
    assert "stderr" in ids
    assert "schedule" in ids

    stdout = next(item for item in result if item["id"] == "stdout")
    assert stdout["label"] == "Stdout Custom"


def test_CoerceOffsetsFromOffsetsDict(projectRouterModule):
    payload = {"offsets": {"stdout": "12", "stderr": "bad"}}

    result = projectRouterModule._coerceOffsets(payload)

    assert result == {"stdout": 12, "stderr": 0}


def test_CoerceOffsetsFromChannelsDict(projectRouterModule):
    payload = {"channels": {"stdout": 7}}

    result = projectRouterModule._coerceOffsets(payload)

    assert result == {"stdout": 7}


def test_CoerceIntReturnsDefaultOnBadValue(projectRouterModule):
    payload = {"maxBytes": "bad"}

    result = projectRouterModule._coerceInt(payload, "maxBytes", 65536)

    assert result == 65536


def test_CoerceIntReturnsParsedValue(projectRouterModule):
    payload = {"maxLines": "200"}

    result = projectRouterModule._coerceInt(payload, "maxLines", 10)

    assert result == 200