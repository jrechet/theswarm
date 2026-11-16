"""A team an agent proposes (phase B, B5): a team file, why, and the owner's
decision. Nothing of it applies until the owner accepts — the model of the
DevOps proposals."""

SQL = """
CREATE TABLE IF NOT EXISTS team_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    proposed_by TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    created_at TEXT NOT NULL,
    decided_by TEXT NOT NULL DEFAULT '',
    decided_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_team_proposals_open ON team_proposals (status, scope);
"""
