"""The cycles waiting their turn: a Play queued behind another cycle lived in
the tracker's memory only, and a restart — a deploy — dropped it without a
word (2026-10-11: four of the owner's six Plays were waiting)."""

SQL = """
CREATE TABLE IF NOT EXISTS cycle_queue (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    issue_number INTEGER,
    description TEXT NOT NULL DEFAULT '',
    queued_at TEXT NOT NULL
);
"""
