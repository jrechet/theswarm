"""Free personas (phase B, B3): what the owner adds to a flow at one of its
insertion points — a second reviewer before the merge, a writer after QA.
For the instance (scope '') or one project; a project's persona of the same
key replaces the instance's."""

SQL = """
CREATE TABLE IF NOT EXISTS team_extras (
    scope TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL,
    name TEXT NOT NULL,
    prompt TEXT NOT NULL,
    point TEXT NOT NULL,
    effect TEXT NOT NULL,
    model TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
"""
