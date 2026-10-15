"""Reading all Set properties at once returns what one-by-one reads return."""
from tests.integration.db.test_stored_set_copies import _particles, copyContext  # noqa: F401 (fixture)
from tests.integration.db.test_user_subsets import _classes


def _oneByOne(mapper):
    return {str(key): mapper.getProperty(str(key)) for key in mapper.getPropertyKeys()}


def test_AllPropertiesMatchOneByOneReads(copyContext, tmp_path):
    particles = _particles(copyContext, range(1, 31), str(tmp_path / "particles.mrcs"))
    classes = _classes(copyContext, particles, 3)
    rootMapper = classes._getMapper()
    classMapper = classes.getFirstItem()._getMapper()
    assert classMapper.tableId is not None and rootMapper.setId is not None

    for mapper in (rootMapper, classMapper, particles._getMapper()):
        properties = mapper.getProperties()
        assert properties == _oneByOne(mapper)
        assert list(properties) == list(_oneByOne(mapper))
    assert classMapper.getProperties()

    scopeChecks = []
    original = classMapper._refreshLogicalTableScope
    classMapper._refreshLogicalTableScope = lambda: scopeChecks.append(1) or original()
    classMapper.getProperties()
    assert len(scopeChecks) == 1
