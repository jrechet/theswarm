"""What the owner says to a running cycle (A3.1): one row per message, kept
until an agent of that cycle has read it (`delivered_at`, `delivered_to`).
`urgent` (A3.3): "stop, do this instead" — it cuts the call that is running."""

SQL = """
CREATE TABLE IF NOT EXISTS cycle_inbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    body TEXT NOT NULL,
    author TEXT NOT NULL DEFAULT '',
    urgent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    delivered_at TEXT,
    delivered_to TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_cycle_inbox_cycle ON cycle_inbox (cycle_id, delivered_at);
"""
