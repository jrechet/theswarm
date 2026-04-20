"""Sprint C — story action audit log (approve/reject/comment from demo player)."""

SQL = """
CREATE TABLE IF NOT EXISTS story_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_id TEXT NOT NULL,
    ticket_id TEXT NOT NULL,
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    UNIQUE (report_id, ticket_id, action)
);

CREATE INDEX IF NOT EXISTS idx_story_actions_report
    ON story_actions(report_id, ticket_id);
"""
