"""Phase L — semantic memory retrieval (opt-in).

One table storing index entries that are opt-in for retrieval. Tags are
stored as a newline-delimited string in ``tags_text``. Idempotent.
"""

SQL = """
CREATE TABLE IF NOT EXISTS semantic_memory_entries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    content TEXT NOT NULL DEFAULT '',
    tags_text TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    source TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_semantic_memory_project
    ON semantic_memory_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_semantic_memory_enabled
    ON semantic_memory_entries(enabled);
"""
