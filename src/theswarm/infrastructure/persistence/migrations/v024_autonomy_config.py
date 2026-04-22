"""Phase L — per-(project, role) autonomy-spectrum config.

One row per (project_id, role) pair, upserted by the service. Idempotent.
"""

SQL = """
CREATE TABLE IF NOT EXISTS autonomy_configs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL,
    level TEXT NOT NULL DEFAULT 'supervised',
    note TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    UNIQUE(project_id, role)
);

CREATE INDEX IF NOT EXISTS idx_autonomy_configs_project
    ON autonomy_configs(project_id);
"""
