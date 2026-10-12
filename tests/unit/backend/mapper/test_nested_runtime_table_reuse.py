import pytest
from pyworkflow.object import Object, Set

from app.backend.mapper.postgresql_set_runtime_mapper import PostgresqlSetRuntimeMapper
from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class ChildSet(Set):
    ITEM_TYPE = Object


class ScopeDb:
    def __init__(self):
        self.queries = []
        self.row = {"id": 91}

    def fetchAll(self, query, params=None):
        return []

    def fetchOne(self, query, params=None):
        self.queries.append((" ".join(query.split()), params))
        return self.row


def ownedChild():
    db = ScopeDb()
    child = ChildSet()
    child.setObjId(7)
    child._mapper = PostgresqlSetRuntimeMapper(
        db=db, tableId=91, parentItemId=7, writable=True,
        itemBuilder=lambda row: Object(), itemSerializer=lambda item: {})
    child._postgresqlRuntimeInfo = dict(setId=41, tableId=91, parentItemId=7)
    db.queries.clear()
    return db, child


def resolve(db, child, **scope):
    return ScipionSetPostgresqlMapper(db)._getOwnedRuntimeNestedTableId(
        setId=scope.get("setId", 41), rootTableId=scope.get("rootTableId", 90),
        parentItemId=scope.get("parentItemId", 7), parentSet=child)


def test_OwnedFlushedNestedTableIsRecheckedUnderLock():
    db, child = ownedChild()
    assert resolve(db, child) == 91
    query, params = db.queries[-1]
    assert query.endswith("FOR UPDATE")
    assert '"parentTableId" = %s' in query
    assert '"tableKind" = \'child\'' in query
    assert params[:4] == (91, 41, 90, 7)
    assert params[-1] == "Object"
    db.row = None
    assert resolve(db, child) is None


@pytest.mark.parametrize("changed", [
    "database", "root_mapper", "readonly", "pending", "parent", "set_owner",
    "table_owner", "parent_owner", "custom_mapper", "missing_metadata",
])
def test_NestedTableReuseRejectsUnprovenOwnership(changed):
    db, child = ownedChild()
    mapper = child._mapper
    if changed == "database":
        mapper.db = ScopeDb()
    elif changed == "root_mapper":
        mapper.setId = 41
    elif changed == "readonly":
        mapper.writable = False
    elif changed == "pending":
        mapper._pendingAppendItems.append({"scipionItemId": 1})
    elif changed == "parent":
        mapper.parentItemId = 8
    elif changed == "set_owner":
        child._postgresqlRuntimeInfo["setId"] = 42
    elif changed == "table_owner":
        child._postgresqlRuntimeInfo["tableId"] = 92
    elif changed == "parent_owner":
        child._postgresqlRuntimeInfo["parentItemId"] = 8
    elif changed == "custom_mapper":
        class CustomMapper(PostgresqlSetRuntimeMapper):
            pass
        mapper.__class__ = CustomMapper
    else:
        child._postgresqlRuntimeInfo = None
    assert resolve(db, child) is None
    assert db.queries == []
