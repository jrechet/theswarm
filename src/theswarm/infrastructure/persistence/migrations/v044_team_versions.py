"""A team is versioned, and a cycle keeps the one it started with (phase B, B2).

`team_versions`: every change to a scope's personas (the instance's '' or one
project's) as a numbered YAML — what the export hands out and the history
shows. `cycle_teams`: the team a cycle's graph thread started with, resolved
— a resume after a deploy runs the same team, whatever was edited since."""

SQL = """
CREATE TABLE IF NOT EXISTS team_versions (
    scope TEXT NOT NULL DEFAULT '',
    version INTEGER NOT NULL,
    body TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    PRIMARY KEY (scope, version)
);
CREATE TABLE IF NOT EXISTS cycle_teams (
    thread_id TEXT PRIMARY KEY,
    project TEXT NOT NULL DEFAULT '',
    label TEXT NOT NULL DEFAULT '',
    team TEXT NOT NULL,
    pinned_at TEXT NOT NULL
);
"""
