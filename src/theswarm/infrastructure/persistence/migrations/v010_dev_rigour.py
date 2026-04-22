"""Phase E — Dev rigour: thoughts, TDD gate, refactor preflight, self-review, coverage.

Adds five tables:

- ``dev_thoughts`` — stream of exploration/research entries per project.
- ``tdd_artifacts`` — RED→GREEN→REFACTOR artifacts per task.
- ``dev_refactor_preflights`` — pre-refactor checks on deletion-heavy diffs.
- ``dev_self_reviews`` — Dev self-review passes before PR.
- ``dev_coverage_deltas`` — changed-lines coverage deltas per PR.

Idempotent: IF NOT EXISTS everywhere. Safe to re-run.
"""

SQL = """
CREATE TABLE IF NOT EXISTS dev_thoughts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    codename TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'note',
    task_id TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_thoughts_project_created
    ON dev_thoughts(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_thoughts_task ON dev_thoughts(task_id);

CREATE TABLE IF NOT EXISTS tdd_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    codename TEXT NOT NULL DEFAULT '',
    phase TEXT NOT NULL DEFAULT 'red',
    test_files_json TEXT NOT NULL DEFAULT '[]',
    red_commit TEXT NOT NULL DEFAULT '',
    green_commit TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_tdd_project_task
    ON tdd_artifacts(project_id, task_id);
CREATE INDEX IF NOT EXISTS idx_tdd_project_phase
    ON tdd_artifacts(project_id, phase);

CREATE TABLE IF NOT EXISTS dev_refactor_preflights (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    pr_url TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    codename TEXT NOT NULL DEFAULT '',
    deletion_lines INTEGER NOT NULL DEFAULT 0,
    files_touched_json TEXT NOT NULL DEFAULT '[]',
    callers_checked_json TEXT NOT NULL DEFAULT '[]',
    decision TEXT NOT NULL DEFAULT 'proceed',
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_preflight_project_created
    ON dev_refactor_preflights(project_id, created_at);

CREATE TABLE IF NOT EXISTS dev_self_reviews (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    pr_url TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    codename TEXT NOT NULL DEFAULT '',
    findings_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_selfrev_project_created
    ON dev_self_reviews(project_id, created_at);

CREATE TABLE IF NOT EXISTS dev_coverage_deltas (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    pr_url TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    codename TEXT NOT NULL DEFAULT '',
    total_before_pct REAL NOT NULL DEFAULT 0.0,
    total_after_pct REAL NOT NULL DEFAULT 0.0,
    changed_lines_pct REAL NOT NULL DEFAULT 0.0,
    changed_lines INTEGER NOT NULL DEFAULT 0,
    missed_lines INTEGER NOT NULL DEFAULT 0,
    threshold_pct REAL NOT NULL DEFAULT 80.0,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_covd_project_created
    ON dev_coverage_deltas(project_id, created_at);
"""
