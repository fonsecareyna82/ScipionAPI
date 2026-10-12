from app.backend.mapper.scipion_set_mapper import ScipionSetPostgresqlMapper


class RecordingDb:
    def __init__(self):
        self.executeCalls = []
        self.valuesCalls = []

    def execute(self, query, params=None, commit=True):
        self.executeCalls.append((query, params))

    def executeValues(self, query, values, template=None, commit=True):
        self.valuesCalls.append({"query": " ".join(query.split()), "rows": list(values),
                                 "template": template, "commit": commit})


def column(label, name, position, className="Float"):
    return {"labelProperty": label, "columnName": name, "className": className,
            "valueType": "float", "position": position, "indexed": False}


def test_TableColumnsUseOneStatementAndKeepLastRepeatedLabel():
    db = RecordingDb()
    ScipionSetPostgresqlMapper(db)._upsertSetTableColumns(9, [
        column("_score", "c00", 0, "Integer"),
        column("_code", "c01", 1, "String"),
        column("_score", "c00", 0, "Float"),
    ])

    assert db.executeCalls == []
    [call] = db.valuesCalls
    assert "INSERT INTO scipion_set_table_columns" in call["query"]
    assert "ux_scipion_set_table_columns_table_label" in call["query"]
    assert call["commit"] is False
    assert [(row[0], row[1], row[3]) for row in call["rows"]] == [
        (9, "_score", "Float"),
        (9, "_code", "String"),
    ]


def test_SetColumnsUseOneStatementAndKeepLastRepeatedLabel():
    db = RecordingDb()
    ScipionSetPostgresqlMapper(db)._upsertSetColumns(4, [
        column("_score", "c00", 0, "Integer"),
        column("_score", "c00", 0, "Float"),
    ])

    assert db.executeCalls == []
    [call] = db.valuesCalls
    assert "INSERT INTO scipion_set_columns" in call["query"]
    assert call["commit"] is False
    assert [(row[0], row[1], row[3]) for row in call["rows"]] == [(4, "_score", "Float")]


def test_EmptyColumnListsSendNoRows():
    db = RecordingDb()
    mapper = ScipionSetPostgresqlMapper(db)
    mapper._upsertSetTableColumns(9, [])
    mapper._upsertSetColumns(4, [])

    assert db.executeCalls == []
    assert all(call["rows"] == [] for call in db.valuesCalls)
