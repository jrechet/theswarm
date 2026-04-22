"""Phase J — Writer: doc artifacts, quickstart checks, changelog entries.

Three tables to keep docs honest and shippable:

- ``doc_artifacts`` — per-project doc catalog (UNIQUE project_id+path).
- ``quickstart_checks`` — append-only log of quickstart runs.
- ``changelog_entries`` — append-only changelog bullets (version bundled at cut).

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS doc_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'readme',
    path TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    last_reviewed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_doc_artifacts_key
    ON doc_artifacts(project_id, path);
CREATE INDEX IF NOT EXISTS idx_doc_artifacts_status
    ON doc_artifacts(status);

CREATE TABLE IF NOT EXISTS quickstart_checks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    step_count INTEGER NOT NULL DEFAULT 0,
    duration_seconds REAL NOT NULL DEFAULT 0.0,
    outcome TEXT NOT NULL DEFAULT 'skipped',
    failure_step TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_quickstart_checks_project
    ON quickstart_checks(project_id);

CREATE TABLE IF NOT EXISTS changelog_entries (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'feat',
    summary TEXT NOT NULL DEFAULT '',
    pr_url TEXT NOT NULL DEFAULT '',
    version TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_changelog_entries_project
    ON changelog_entries(project_id);
CREATE INDEX IF NOT EXISTS idx_changelog_entries_version
    ON changelog_entries(project_id, version);
"""
