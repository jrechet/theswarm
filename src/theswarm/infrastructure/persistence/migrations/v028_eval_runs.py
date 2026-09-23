"""Scored harness runs, stored where the page can read them (V2 M6).

The harness appended its line to docs/harness-runs.jsonl on main; branch
protection now refuses that push ("Changes must be made through a pull
request", run 35874015968), and the image only ships the file as it was
at build time anyway. The harness posts each scored record to the API
instead; the repo page reads the trend from here.
"""

SQL = """
CREATE TABLE IF NOT EXISTS eval_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    repo TEXT NOT NULL,
    feature TEXT NOT NULL DEFAULT '',
    cycle_id TEXT NOT NULL DEFAULT '',
    timestamp TEXT NOT NULL,
    record_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eval_runs_repo ON eval_runs(repo, id);
"""
