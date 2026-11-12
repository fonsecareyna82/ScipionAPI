"""The rows of a Set's root logical table are read from the Set's own items, never from their copies in the
logical tables: the viewers, the stored table rows and the output checks give the same without the copies."""
from pwem import objects as emobj

from app.backend.mapper import ScipionSetPostgresqlMapper
from app.backend.viewers.postgresql_dao import PostgresqlDAO
from tests.integration.db.test_stored_set_copies import copyContext  # noqa: F401 (fixture)

ROOT_STATS = ("rootTableItemsCount", "rootTableMaxItemId", "rootTableItemsIdSignature",
              "rootTableItemsValueSignature")


def _micrographs(ctx):
    micrographs = emobj.SetOfMicrographs()
    micrographs.setSamplingRate(1.25)
    micrographs, info = ctx["reserve"](micrographs)
    for index, enabled in enumerate([True, False, True, True], start=1):
        micrograph = emobj.Micrograph(location="mic_%03d.mrc" % index)
        micrograph.setEnabled(enabled)
        micrograph.setObjLabel("mic %d" % index)
        micrographs.append(micrograph)
    stored = ctx["finalize"](micrographs, info)
    setId = int(stored.getPostgresqlRuntimeInfo()["setId"])
    return ctx["db"].fetchOne('SELECT id, "projectId", "protocolDbId", "outputName" FROM scipion_sets WHERE id = %s',
                              (setId,))


def _whatReadersSee(db, stored):
    dao = PostgresqlDAO(db, int(stored["projectId"]), int(stored["protocolDbId"]), stored["outputName"])
    tables = list(dao.getTables())
    seen = {
        "count": dao.getTableRowCount("objects"),
        "rows": [dao.getTableRow("objects", index) for index in range(4)],
        "byId": dao.getTableRowById("objects", 3),
        "sorted": dao.getOrderedRowIds("objects", "_filename", False),
        "position": dao.getTableRowPosition("objects", 3, "_filename", False),
        "enabledFirst": dao.getOrderedRowIds("objects", "enabled", True),
    }
    mapper = ScipionSetPostgresqlMapper(db)
    rootTable = db.fetchOne('SELECT id FROM scipion_set_tables WHERE "setId" = %s AND "tableKind" = \'root\'',
                            (int(stored["id"]),))
    seen["tableItems"] = [(row["scipionItemId"], row["parentItemId"], row["enabled"], row["label"], row["values"])
                          for row in mapper.getStoredSetTableItems(int(rootTable["id"]))]
    output = next(row for row in mapper.listProjectSetOutputRows(int(stored["projectId"]))
                  if int(row["id"]) == int(stored["id"]))
    seen["outputChecks"] = {key: output[key] for key in ROOT_STATS}
    return tables, seen, rootTable


def test_RootRowsReadTheSameWithoutTheirCopies(copyContext):
    db = copyContext["db"]
    stored = _micrographs(copyContext)
    tables, before, rootTable = _whatReadersSee(db, stored)
    assert "objects" in tables
    assert before["count"] == 4 and [row["id"] for row in before["rows"]] == [1, 2, 3, 4]
    assert before["sorted"] == [4, 3, 2, 1] and before["position"] == 1
    assert before["enabledFirst"][0] == 2 and before["rows"][1]["enabled"] is False
    assert before["outputChecks"]["rootTableItemsCount"] == 4

    db.execute('DELETE FROM scipion_set_table_items WHERE "tableId" = %s', (int(rootTable["id"]),))

    assert _whatReadersSee(db, stored)[1] == before
