"""Regression: 2D objects must not perform unused 3D tomogram lookups.

The fast-path must preserve 3D values and setVolume side effects.
"""
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

import app.backend.mapper.scipion_set_mapper as set_mapper_module
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


@pytest.fixture
def mapper_and_attacher(monkeypatch):
    mapper = object.__new__(ScipionSetPostgresqlMapper)
    attacher = Mock(return_value=False)
    monkeypatch.setattr(mapper, '_attachCoordinate3dTomogram', attacher)
    monkeypatch.setattr(set_mapper_module, 'BOTTOM_LEFT_CORNER', object())
    return mapper, attacher


def test_Plain2DParticleSkipsUnnecessary3dTomogramLookup(mapper_and_attacher):
    mapper, attach = mapper_and_attacher
    particle = SimpleNamespace(getObjId=lambda: 10, getLocation=lambda: (1, 'foo.mrcs'))

    assert mapper._getCoordinate3dBottomLeftCoordinates(particle, {}, None) is None
    attach.assert_not_called()


def test_PartialCoordinateGettersWithoutSetterDoNotTriggerTomogramLookup(mapper_and_attacher):
    mapper, attach = mapper_and_attacher
    partial = SimpleNamespace(getX=lambda c: 1.0, getY=lambda c: 2.0)

    assert mapper._getCoordinate3dBottomLeftCoordinates(partial, {}, None) is None
    attach.assert_not_called()


def test_Full3dCoordinatePreservesAttachmentAndComputedValues(mapper_and_attacher):
    mapper, attach = mapper_and_attacher
    item = SimpleNamespace(
        getX=lambda convention: 10,
        getY=lambda convention: 20.5,
        getZ=lambda convention: 30,
    )
    values = {'_x': 10}
    parent = object()

    assert mapper._getCoordinate3dBottomLeftCoordinates(item, values, parent) == (10.0, 20.5, 30.0)
    attach.assert_called_once_with(item=item, values=values, scipionSet=parent)


def test_SetVolumeSideEffectIsPreservedEvenWithout3dGetters(mapper_and_attacher):
    mapper, attach = mapper_and_attacher
    received = []
    item = SimpleNamespace(setVolume=lambda volume: received.append(volume))
    attach.side_effect = lambda **kwargs: kwargs['item'].setVolume('TOMO')

    assert mapper._getCoordinate3dBottomLeftCoordinates(item, {'tsId': 'a'}, object()) is None
    assert received == ['TOMO']
    attach.assert_called_once()


def test_FailingCoordinateGettersKeepExistingNonThrowingBehavior(mapper_and_attacher):
    mapper, attach = mapper_and_attacher

    def fail(convention):
        raise RuntimeError('cannot convert coordinate')

    item = SimpleNamespace(getX=fail, getY=lambda convention: 2, getZ=lambda convention: 3)
    assert mapper._getCoordinate3dBottomLeftCoordinates(item, {}, None) is None
    attach.assert_called_once()
