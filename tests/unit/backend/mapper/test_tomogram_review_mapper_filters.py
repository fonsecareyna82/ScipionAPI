from app.backend.mapper.tomogram_review_mapper import TomogramReviewPostgresqlMapper


class CapturingDb:
    def __init__(self):
        self.sql = None
        self.params = None

    def fetchAll(self, sql, params):
        self.sql = sql
        self.params = params
        return [{"scipionItemId": 31}]


def test_GetFilteredScipionItemIdsCombinesAdvancedReviewCriteria():
    db = CapturingDb()
    mapper = TomogramReviewPostgresqlMapper(db)

    result = mapper.getFilteredScipionItemIds(
        projectId=7,
        setId=47,
        reviewFilter="reviewed",
        reviewCriteria={
            "qualities": ["Excellent", "Good"],
            "tags": ["feature_a"],
            "minimumTagCounts": {"mito": 2},
        },
    )

    assert result == [31]
    assert "quality" in db.sql
    assert "tags" in db.sql
    assert "tagCounts" in db.sql
    assert "Excellent" in repr(db.params)
    assert "Good" in repr(db.params)
    assert "feature_a" in repr(db.params)
    assert "mito" in repr(db.params)
    assert "2" in repr(db.params)
