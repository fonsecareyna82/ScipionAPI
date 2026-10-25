"""The 2D coordinates viewer lists the micrographs of a stored Set counted by the database, as reading it whole."""
from pwem import objects as emobj

from app.backend.viewers.postgresql_coords2d_reader import PostgresqlCoords2dReader
from tests.integration.db.test_stored_set_copies import copyContext  # noqa: F401 (fixture)


def _coordinates(ctx, picks):
    """A stored SetOfCoordinates; picks: (micrograph id, how many coordinates), written interleaved."""
    coordinates = emobj.SetOfCoordinates()
    coordinates.setBoxSize(180)
    coordinates, info = ctx["reserve"](coordinates)
    left = dict(picks)
    while any(left.values()):
        for micId in sorted(left):
            if left[micId]:
                coordinate = emobj.Coordinate()
                coordinate.setPosition(10 * left[micId], 20 * micId)
                coordinate.setMicId(micId)
                coordinate.setMicName("mic_%03d.mrc" % micId)
                coordinates.append(coordinate)
                left[micId] -= 1
    stored = ctx["finalize"](coordinates, info)
    setId = int(stored.getPostgresqlRuntimeInfo()["setId"])
    row = ctx["db"].fetchOne('SELECT "projectId", "protocolDbId" AS "protocolId", "outputName" FROM scipion_sets WHERE id = %s', (setId,))
    return PostgresqlCoords2dReader(ctx["db"], int(row["projectId"]), int(row["protocolId"]), row["outputName"])


def test_TheMicrographsCountedByTheDatabaseAreTheOnesTheWholeSetGives(copyContext, monkeypatch):
    reader = _coordinates(copyContext, [(3, 4), (12, 1), (7, 2)])
    summarized = reader.listMicrographs()

    # The same reader reading every coordinate of the Set, as before
    full = PostgresqlCoords2dReader(reader.db, reader.projectId, reader.protocolId, reader.outputName)
    monkeypatch.setattr(full, "_listMicrographsFromSummary", lambda: None)

    assert summarized == full.listMicrographs()
    assert [(mic["id"], mic["particles"], mic["label"]) for mic in summarized["micrographs"]] == [
        ("3", 4, "mic_003.mrc"), ("7", 2, "mic_007.mrc"), ("12", 1, "mic_012.mrc")]
    assert (summarized["totalPicks"], summarized["boxSize"]) == (7, 180)


def test_ListingTheMicrographsDoesNotReadEveryCoordinate(copyContext, monkeypatch):
    reader = _coordinates(copyContext, [(1, 3), (2, 3)])

    def readWhole(*args, **kwargs):
        raise AssertionError("The whole Set was read to list its micrographs")

    monkeypatch.setattr(reader, "_getStoredSet", readWhole)

    assert [mic["particles"] for mic in reader.listMicrographs()["micrographs"]] == [3, 3]
