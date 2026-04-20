"""Sprint D V2 — cycle_events table for replay."""

SQL = """
CREATE TABLE IF NOT EXISTS cycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    payload_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cycle_events_cycle
    ON cycle_events(cycle_id, occurred_at ASC);
"""
