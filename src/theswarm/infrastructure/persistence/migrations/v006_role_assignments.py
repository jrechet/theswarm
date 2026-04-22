"""Phase A — role assignments + three-layer memory columns.

Creates the ``role_assignments`` table that binds a codenamed agent to a
project (or the portfolio), and extends ``memory_entries`` with ``codename``,
``role``, ``scope_layer``, ``confidence``, ``supersedes`` columns so memory
can be keyed at three layers: global / project / role × project.

The migration is idempotent (IF NOT EXISTS everywhere, per-column existence
checks run by the caller).
"""

SQL = """
CREATE TABLE IF NOT EXISTS role_assignments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    role TEXT NOT NULL,
    codename TEXT NOT NULL,
    assigned_at TEXT NOT NULL,
    retired_at TEXT,
    config_json TEXT NOT NULL DEFAULT '{}'
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_role_assignments_codename
    ON role_assignments(codename);
CREATE INDEX IF NOT EXISTS idx_role_assignments_project
    ON role_assignments(project_id, role);
CREATE INDEX IF NOT EXISTS idx_role_assignments_active
    ON role_assignments(project_id, role, retired_at);
"""


ALTER_STATEMENTS: tuple[tuple[str, str], ...] = (
    ("codename", "ALTER TABLE memory_entries ADD COLUMN codename TEXT NOT NULL DEFAULT ''"),
    ("role", "ALTER TABLE memory_entries ADD COLUMN role TEXT NOT NULL DEFAULT ''"),
    ("scope_layer", "ALTER TABLE memory_entries ADD COLUMN scope_layer TEXT NOT NULL DEFAULT 'project'"),
    ("confidence", "ALTER TABLE memory_entries ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0"),
    ("supersedes", "ALTER TABLE memory_entries ADD COLUMN supersedes TEXT NOT NULL DEFAULT ''"),
)


INDEX_SQL = """
CREATE INDEX IF NOT EXISTS idx_memory_codename ON memory_entries(codename);
CREATE INDEX IF NOT EXISTS idx_memory_role_project ON memory_entries(project_id, role);
CREATE INDEX IF NOT EXISTS idx_memory_scope_layer ON memory_entries(scope_layer);
"""
