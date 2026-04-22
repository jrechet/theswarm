"""Phase L — cross-project refactor programs.

One table recording coordinated, multi-project refactor programs.
``target_projects_text`` is newline-delimited project ids. Idempotent.
"""

SQL = """
CREATE TABLE IF NOT EXISTS refactor_programs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    target_projects_text TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    completed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_refactor_programs_title
    ON refactor_programs(title);
CREATE INDEX IF NOT EXISTS idx_refactor_programs_status
    ON refactor_programs(status);
"""
