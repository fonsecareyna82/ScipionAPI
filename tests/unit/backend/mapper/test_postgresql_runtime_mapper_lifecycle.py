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
from app.backend.mapper.postgresql_runtime_mapper import (
    PostgresqlRuntimeMapper,
)


class FakeReadFallbackMapper:
    def __init__(self):
        self.closeCalls = 0

    def close(self):
        self.closeCalls += 1


class FakeRuntimeSetFactory:
    def __init__(self):
        self.clearCalls = 0

    def clearCaches(self):
        self.clearCalls += 1


def test_CloseReleasesRuntimeMapperCaches():
    readFallbackMapper = FakeReadFallbackMapper()
    runtimeSetFactory = FakeRuntimeSetFactory()

    mapper = object.__new__(PostgresqlRuntimeMapper)

    mapper.readFallbackMapper = readFallbackMapper
    mapper.runtimeSetFactory = runtimeSetFactory

    mapper._runtimeProtocolsById = {
        100: object(),
        200: object(),
    }

    mapper._sqliteProtocolMirrorIds = {
        100,
    }

    mapper.close()

    assert readFallbackMapper.closeCalls == 1
    assert runtimeSetFactory.clearCalls == 1
    assert mapper._runtimeProtocolsById == {}
    assert mapper._sqliteProtocolMirrorIds == set()