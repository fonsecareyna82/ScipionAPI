"""The queries of cleaning a scratch disk: which projects and protocols its folders belong to."""
from typing import Any, Dict, List


class ScratchPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def protocolsOfProjects(self, shortNames: List[str]) -> List[Dict[str, Any]]:
        """The protocols of the projects whose folder is named so (several users may have one each), with their
        status; a project being deleted counts as gone."""
        if not shortNames:
            return []
        rows = self.db.fetchAll(
            "SELECT REGEXP_REPLACE(RTRIM(p.name, '/'), '^.*/', '') AS \"shortName\", pr.\"protocolId\", "
            "pr.\"protocolClassName\", LOWER(COALESCE(pr.status, '')) AS status "
            "FROM projects p LEFT JOIN protocols pr ON pr.\"projectId\" = p.id "
            "WHERE p.status IS DISTINCT FROM 'deleting' "
            "AND REGEXP_REPLACE(RTRIM(p.name, '/'), '^.*/', '') = ANY(%s)", (list(shortNames),))
        return [dict(row) for row in rows or []]
