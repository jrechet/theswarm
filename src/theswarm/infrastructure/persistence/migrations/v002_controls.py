"""Sprint B — project secrets, audit log, and cycle cost tracking."""

SQL = """
CREATE TABLE IF NOT EXISTS project_secrets (
    project_id TEXT NOT NULL,
    key_name TEXT NOT NULL,
    encrypted_value BLOB NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY (project_id, key_name)
);

CREATE TABLE IF NOT EXISTS project_audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    detail TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_project_audit_project ON project_audit(project_id, created_at DESC);
"""
