"""The closed Claude subscription window, so it outlives a deploy.

One row: when the window reopens and the message that said so. Primed at
boot by `tools/quota_wall.prime`; without it every deploy forgot the wall
and the next harness run started a cycle that died on its first call.
"""

SQL = """
CREATE TABLE IF NOT EXISTS quota_wall (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    until_utc TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""
