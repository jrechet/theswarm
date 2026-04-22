"""Phase G — Scout: intel sources, items, and clusters.

Adds three tables:

- ``intel_sources`` — subscribed feeds / upstream sources with health counters.
- ``intel_items`` — classified, dedup'd items (UNIQUE ``url_hash``).
- ``intel_clusters`` — groups of related items.

Idempotent: IF NOT EXISTS everywhere. Safe to re-run.
"""

SQL = """
CREATE TABLE IF NOT EXISTS intel_sources (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'custom',
    url TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    success_count INTEGER NOT NULL DEFAULT 0,
    error_count INTEGER NOT NULL DEFAULT 0,
    last_ok_at TEXT,
    last_error TEXT NOT NULL DEFAULT '',
    last_error_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intel_sources_project
    ON intel_sources(project_id);
CREATE INDEX IF NOT EXISTS idx_intel_sources_kind
    ON intel_sources(kind);

CREATE TABLE IF NOT EXISTS intel_items (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    url_hash TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'fyi',
    urgency TEXT NOT NULL DEFAULT 'normal',
    project_ids_json TEXT NOT NULL DEFAULT '[]',
    cluster_id TEXT NOT NULL DEFAULT '',
    action_taken TEXT NOT NULL DEFAULT '',
    action_taken_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_intel_items_url_hash
    ON intel_items(url_hash);
CREATE INDEX IF NOT EXISTS idx_intel_items_category
    ON intel_items(category);
CREATE INDEX IF NOT EXISTS idx_intel_items_created
    ON intel_items(created_at);
CREATE INDEX IF NOT EXISTS idx_intel_items_source
    ON intel_items(source_id);

CREATE TABLE IF NOT EXISTS intel_clusters (
    id TEXT PRIMARY KEY,
    topic TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    member_ids_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_intel_clusters_created
    ON intel_clusters(created_at);
"""
