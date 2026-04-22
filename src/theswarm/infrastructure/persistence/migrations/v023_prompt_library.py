"""Phase L — prompt library + audit trail.

Two tables:
- ``prompt_templates`` — versioned prompt templates, UNIQUE on name.
- ``prompt_audit_entries`` — append-only history of edits.

Idempotent.
"""

SQL = """
CREATE TABLE IF NOT EXISTS prompt_templates (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL DEFAULT 1,
    deprecated INTEGER NOT NULL DEFAULT 0,
    updated_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_prompt_templates_name
    ON prompt_templates(name);
CREATE INDEX IF NOT EXISTS idx_prompt_templates_role
    ON prompt_templates(role);

CREATE TABLE IF NOT EXISTS prompt_audit_entries (
    id TEXT PRIMARY KEY,
    prompt_name TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    before_version INTEGER NOT NULL DEFAULT 0,
    after_version INTEGER NOT NULL DEFAULT 0,
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_prompt_audit_prompt_name
    ON prompt_audit_entries(prompt_name);
CREATE INDEX IF NOT EXISTS idx_prompt_audit_created_at
    ON prompt_audit_entries(created_at);
"""
