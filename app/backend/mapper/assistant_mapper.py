"""The queries of the AI assistant: what each user asked each day, a protocol as the assistant reads it, where a
protocol's inputs come from, and the chains of protocols it added from templates."""
import json
from typing import Any, Dict, List, Optional

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


# Every protocol a protocol's inputs come from, near or far, with how far (1: its own inputs)
ANCESTORS_SQL = """
    WITH RECURSIVE up("protocolId", depth) AS (
        SELECT "parentProtocolId", 1
          FROM protocol_input_refs
         WHERE "projectId" = %s AND "protocolId" = %s AND "parentProtocolId" IS NOT NULL
        UNION
        SELECT r."parentProtocolId", up.depth + 1
          FROM protocol_input_refs r
          JOIN up ON r."protocolId" = up."protocolId"
         WHERE r."projectId" = %s AND r."parentProtocolId" IS NOT NULL AND up.depth < 50
    )
    SELECT "protocolId", MIN(depth) AS depth FROM up GROUP BY "protocolId" ORDER BY MIN(depth)
"""

# A protocol's inputs as the protocol form sends them: "<parent protocol id>.<output>" each, in their order
INPUT_REFS_SQL = """
    SELECT "inputName", "itemIndex", "parentProtocolId", "parentOutputName"
      FROM protocol_input_refs
     WHERE "projectId" = %s AND "protocolId" = %s
       AND "parentProtocolId" IS NOT NULL AND COALESCE("parentOutputName", '') <> ''
     ORDER BY "inputName", "itemIndex"
"""

MAX_PROTOCOL_ID_SQL = """
    SELECT COALESCE(MAX(CASE WHEN "protocolId" ~ '^[0-9]+$' THEN "protocolId"::BIGINT END), 0) AS top
      FROM protocols
     WHERE "projectId" = %s
"""

CHAIN_COLUMNS = ('id, "projectId", "userId", "templateId", title, "protocolIds", parents, stops, passed, launched, '
                 '"createdAt"')

ADD_CHAIN_SQL = """
    INSERT INTO assistant_chains ("projectId", "userId", "templateId", title, "protocolIds", parents, stops, launched)
    VALUES (%s, %s, %s, %s, %s::JSONB, %s::JSONB, %s::JSONB, %s::JSONB)
    RETURNING id
"""

UPDATE_CHAIN_SQL = """
    UPDATE assistant_chains SET passed = %s::JSONB, launched = %s::JSONB, "updatedAt" = NOW()
     WHERE id = %s AND "projectId" = %s
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

    def ancestors(self, projectId: int, protocolId) -> List[Dict[str, Any]]:
        """[{protocolId, depth}] of the protocols a protocol's inputs come from, the nearest first."""
        values = (int(projectId), str(protocolId), int(projectId))
        return [{"protocolId": str(row["protocolId"]), "depth": int(row["depth"])}
                for row in self.db.fetchAll(ANCESTORS_SQL, values) or []]

    def topProtocolId(self, projectId: int) -> int:
        row = self.db.fetchOne(MAX_PROTOCOL_ID_SQL, (int(projectId),)) or {}
        return int(row.get("top") or 0)

    # Chains ----------------------------------------------------------------------------------------------------
    def addChain(self, projectId: int, userId: Optional[int], templateId: str, title: str, protocolIds: List[str],
                 parents: Dict[str, List[str]], stops: List[str], launched: List[str]) -> int:
        row = self.db.executeReturningOne(ADD_CHAIN_SQL, (
            int(projectId), userId, str(templateId), str(title), json.dumps(protocolIds), json.dumps(parents),
            json.dumps(stops), json.dumps(launched)))
        return int(row["id"])

    def chains(self, projectId: int) -> List[Dict[str, Any]]:
        return [dict(row) for row in self.db.fetchAll(
            "SELECT %s FROM assistant_chains WHERE \"projectId\" = %%s ORDER BY id DESC" % CHAIN_COLUMNS,
            (int(projectId),)) or []]

    def chain(self, projectId: int, chainId: int) -> Optional[Dict[str, Any]]:
        row = self.db.fetchOne("SELECT %s FROM assistant_chains WHERE id = %%s AND \"projectId\" = %%s"
                               % CHAIN_COLUMNS, (int(chainId), int(projectId)))
        return dict(row) if row else None

    def saveChainProgress(self, projectId: int, chainId: int, passed: List[str], launched: List[str]) -> None:
        self.db.execute(UPDATE_CHAIN_SQL, (json.dumps(passed), json.dumps(launched), int(chainId), int(projectId)))

    def pointerParams(self, projectId: int, protocolId) -> Dict[str, Any]:
        """{input: "parent.output"} (a list for several), to send with a save or a launch: the protocol form sends
        them so, and a save without them leaves the protocol's inputs empty."""
        values: Dict[str, List[str]] = {}
        for row in self.db.fetchAll(INPUT_REFS_SQL, (int(projectId), str(protocolId))) or []:
            values.setdefault(str(row["inputName"]), []).append(
                "%s.%s" % (row["parentProtocolId"], row["parentOutputName"]))
        return {name: refs[0] if len(refs) == 1 else refs for name, refs in values.items()}
