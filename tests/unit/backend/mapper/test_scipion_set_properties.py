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
from pyworkflow.object import Float, Integer, Object

from app.backend.mapper.scipion_set_mapper import (
    NESTED_LOGICAL_TABLES_VERSION,
    SET_PROPERTIES_VERSION,
    ScipionSetPostgresqlMapper,
)


class ExampleAcquisition(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._voltage = Float()
        self._magnification = Float()


class ExampleSet(Object):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._size = Integer(3)
        self._streamState = Integer(2)
        self._acquisition = ExampleAcquisition()

        self._acquisition._voltage.set(300.0)
        self._acquisition._magnification.set(50000.0)

    def getFileName(self):
        return None

    def getStreamState(self):
        return self._streamState.get()


def test_GetSetPropertiesIncludesNestedAttributes():
    scipionSet = ExampleSet()
    scipionSet.setObjId(41)

    mapper = ScipionSetPostgresqlMapper(
        db=None,
    )

    properties = mapper._getSetProperties(
        scipionSet
    )

    assert properties["scipionObjId"] == 41
    assert properties["_size"] == 3
    assert properties["_streamState"] == 2
    assert properties["_acquisition._voltage"] == 300.0
    assert properties["_acquisition._magnification"] == 50000.0

    # Complex parent objects normally have value None and should not be
    # persisted as a scalar property.
    assert "_acquisition" not in properties


def test_OldSetPropertiesVersionForcesSynchronization():
    mapper = ScipionSetPostgresqlMapper(
        db=None,
    )

    existingProperties = {
        "incremental": True,
        "nestedTablesVersion": NESTED_LOGICAL_TABLES_VERSION,
        "setPropertiesVersion": SET_PROPERTIES_VERSION - 1,
        "itemsCount": 3,
        "maxItemId": 3,
        "sourceMTime": 10.0,
    }

    assert mapper._shouldSkipSetSync(
        existingProperties=existingProperties,
        itemsCountHint=3,
        maxItemIdHint=3,
        sourceMTime=10.0,
    ) is False


def test_CurrentSetPropertiesVersionAllowsUnchangedSetSkip():
    mapper = ScipionSetPostgresqlMapper(
        db=None,
    )

    existingProperties = {
        "incremental": True,
        "nestedTablesVersion": NESTED_LOGICAL_TABLES_VERSION,
        "setPropertiesVersion": SET_PROPERTIES_VERSION,
        "itemsCount": 3,
        "maxItemId": 3,
        "sourceMTime": 10.0,
    }

    assert mapper._shouldSkipSetSync(
        existingProperties=existingProperties,
        itemsCountHint=3,
        maxItemIdHint=3,
        sourceMTime=10.0,
    ) is True