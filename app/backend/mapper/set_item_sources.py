"""Where the rows of a logical table are read from.

The rows of a Set's root logical table are the Set's own items (scipion_set_items). Every other logical table
keeps its rows in scipion_set_table_items. Readers take both through LOGICAL_TABLE_ITEMS, so the root rows are
always read from the Set's items, never from a copy of them.
"""

# The columns of scipion_set_table_items, for every logical table. Filtering on "tableId" narrows each branch
# through its index.
LOGICAL_TABLE_ITEMS = """(
    SELECT child_item.id, child_item."tableId", child_item."scipionItemId", child_item."parentItemId",
           child_item.enabled, child_item.label, child_item.comment, child_item.creation, child_item."values",
           child_item."createdAt", child_item."updatedAt"
      FROM scipion_set_table_items child_item
      JOIN scipion_set_tables child_table ON child_table.id = child_item."tableId"
     WHERE child_table."tableKind" <> 'root'
    UNION ALL
    SELECT root_item.id, root_table.id, root_item."scipionItemId", NULL::integer,
           root_item.enabled, root_item.label, root_item.comment, root_item.creation, root_item."values",
           root_item."createdAt", root_item."updatedAt"
      FROM scipion_set_items root_item
      JOIN scipion_set_tables root_table
        ON root_table."setId" = root_item."setId" AND root_table."tableKind" = 'root'
)"""


def logicalTableItems(alias: str) -> str:
    """LOGICAL_TABLE_ITEMS under alias, for a FROM or JOIN clause."""
    return "%s AS %s" % (LOGICAL_TABLE_ITEMS, alias)
