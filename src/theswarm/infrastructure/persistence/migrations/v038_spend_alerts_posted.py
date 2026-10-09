"""The spend alerts already posted on the PO's channel, by key: a restart no
longer posts the same alert twice (SpendWatch kept them in memory)."""

SQL = """
CREATE TABLE IF NOT EXISTS spend_alerts_posted (
    key TEXT PRIMARY KEY,
    posted_at TEXT NOT NULL
);
"""
