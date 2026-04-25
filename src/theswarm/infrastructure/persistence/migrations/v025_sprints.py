"""Phase 1.4 — sprint tracking.

A sprint is the group of issues created together via the composer.
Lets the dashboard answer 'where is my request now?' by pinning a
short id to the user's prompt and the issues drafted from it.
"""

SQL = """
CREATE TABLE IF NOT EXISTS sprints (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    request TEXT NOT NULL,
    issue_numbers_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sprints_project
    ON sprints(project_id, created_at DESC);
"""
