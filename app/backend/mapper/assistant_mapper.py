"""The queries of the AI assistant: what each user asked each day, and a protocol as the assistant reads it."""
from typing import Any, Dict, Optional

USAGE_SQL = """
    SELECT questions, "inputTokens", "outputTokens"
      FROM assistant_usage
     WHERE "userId" = %s AND day = CURRENT_DATE
"""

ADD_USAGE_SQL = """
    INSERT INTO assistant_usage ("userId", day, questions, "inputTokens", "outputTokens")
    VALUES (%s, CURRENT_DATE, %s, %s, %s)
    ON CONFLICT ("userId", day) DO UPDATE
       SET questions = assistant_usage.questions + EXCLUDED.questions,
           "inputTokens" = assistant_usage."inputTokens" + EXCLUDED."inputTokens",
           "outputTokens" = assistant_usage."outputTokens" + EXCLUDED."outputTokens"
"""

TOTALS_SQL = """
    SELECT COUNT(DISTINCT "userId") AS users, COALESCE(SUM(questions), 0) AS questions,
           COALESCE(SUM("inputTokens"), 0) AS "inputTokens", COALESCE(SUM("outputTokens"), 0) AS "outputTokens"
      FROM assistant_usage
     WHERE day >= CURRENT_DATE - (%s * INTERVAL '1 day')
"""

PROTOCOL_SQL = """
    SELECT "protocolId", "protocolClassName" AS "className", LOWER(COALESCE(status, '')) AS status,
           COALESCE(NULLIF(params->>'runName', ''), "protocolClassName") AS label, params
      FROM protocols
     WHERE "projectId" = %s AND "protocolId" = %s
"""


class AssistantPostgresqlMapper:
    def __init__(self, db):
        self.db = db

    def usageToday(self, userId: int) -> Dict[str, int]:
        row = self.db.fetchOne(USAGE_SQL, (int(userId),))
        if not row:
            return {"questions": 0, "inputTokens": 0, "outputTokens": 0}
        return {key: int(row[key] or 0) for key in ("questions", "inputTokens", "outputTokens")}

    def addUsage(self, userId: int, questions: int, inputTokens: int, outputTokens: int) -> None:
        self.db.execute(ADD_USAGE_SQL, (int(userId), int(questions), int(inputTokens), int(outputTokens)))

    def totals(self, days: int) -> Dict[str, int]:
        row = self.db.fetchOne(TOTALS_SQL, (int(days),)) or {}
        return {key: int(row.get(key) or 0) for key in ("users", "questions", "inputTokens", "outputTokens")}

    def protocol(self, projectId: int, protocolId) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne(PROTOCOL_SQL, (int(projectId), str(protocolId)))
        return dict(row) if row else None
