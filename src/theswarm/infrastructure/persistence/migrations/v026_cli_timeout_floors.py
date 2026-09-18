"""The learned CLI timeout floor, per workspace, across deploys (#133).

`tools/claude._REPO_FLOORS` remembers the largest budget that already
expired so a later call does not pay to rediscover it. It lived in the
process, and on this repository every cycle ends with a merge and a
deploy: each self-cycle started at the constant again, timed out, and
burned seven minutes and a dead call relearning the same number.
"""

SQL = """
CREATE TABLE IF NOT EXISTS cli_timeout_floors (
    workdir TEXT PRIMARY KEY,
    floor_seconds INTEGER NOT NULL,
    updated_at TEXT NOT NULL
);
"""
