"""Tables of STAR, XMD, CSV and TSV files for the file browser."""
from app.backend.utils.star_table import readMetadataTableFile, readStarTable

RELION = """
# version 30001

data_optics

loop_
_rlnOpticsGroup #1
_rlnImagePixelSize #2
1 1.35

data_particles

loop_
_rlnCoordinateX #1
_rlnCoordinateY #2
_rlnMicrographName #3
10 20 'mic one.mrc'
30 40 mic2.mrc
50 60 mic3.mrc
"""

XMIPP = """# XMIPP_STAR_1 *
#
data_header
_pickingMicrographState Manual
_autopickPercent 50
data_particles
loop_
 _xcoor
 _ycoor
 100 200
 300 400
"""


def test_relion_star_blocks_and_quoted_values():
    table = readStarTable(RELION.splitlines(keepends=True))
    assert [(b.name, b.kind, b.totalRows) for b in table.blocks] == [("optics", "loop", 1), ("particles", "loop", 3)]
    particles = table.blocks[1]
    assert particles.columns == ["rlnCoordinateX", "rlnCoordinateY", "rlnMicrographName"]
    assert particles.rows[0] == ["10", "20", "mic one.mrc"]
    # The main table is the biggest loop.
    assert table.toDict()["columns"] == particles.columns


def test_xmipp_metadata_with_pairs_and_a_loop(tmp_path):
    path = tmp_path / "picking.xmd"
    path.write_text(XMIPP)
    table = readMetadataTableFile(str(path))
    assert table.format == "xmd"
    header, particles = table.blocks
    assert (header.kind, header.columns, header.rows) == ("pairs", ["Label", "Value"],
                                                         [["pickingMicrographState", "Manual"], ["autopickPercent", "50"]])
    assert (particles.columns, particles.rows, particles.totalRows) == (["xcoor", "ycoor"], [["100", "200"], ["300", "400"]], 2)


def test_big_loops_keep_their_first_rows_and_count_the_rest():
    lines = ["data_\n", "loop_\n", "_a\n", "_b\n"] + ["%d %d\n" % (i, i) for i in range(1000)]
    table = readStarTable(lines, rowLimit=10)
    block = table.blocks[0]
    assert (len(block.rows), block.totalRows, block.truncated) == (10, 1000, True)
    # Reading stops at the byte limit: the count is then unknown.
    stopped = readStarTable(lines, rowLimit=10, readLimit=200)
    assert stopped.incomplete and stopped.blocks[0].totalRows is None


def test_short_rows_are_padded_and_files_without_tables_have_no_blocks():
    table = readStarTable(["data_x\n", "loop_\n", "_a\n", "_b\n", "1\n"])
    assert table.blocks[0].rows == [["1", ""]]
    assert readStarTable(["just some text\n"]).blocks == []


def test_csv_and_tsv(tmp_path):
    csvPath = tmp_path / "t.csv"
    csvPath.write_text('x,y,name\n1,2,"a, b"\n3,4,c\n\n')
    table = readMetadataTableFile(str(csvPath), rowLimit=1)
    block = table.blocks[0]
    assert (block.columns, block.rows, block.totalRows, block.truncated) == (["x", "y", "name"], [["1", "2", "a, b"]], 2, True)
    tsvPath = tmp_path / "t.tsv"
    tsvPath.write_text("a\tb\n1\t2\n")
    assert readMetadataTableFile(str(tsvPath)).blocks[0].rows == [["1", "2"]]
