"""Phase F — QA enrichments: archetype mix, flake tracker, quarantine, gates, outcome cards.

Adds five tables:

- ``qa_test_plans`` — required vs. produced test archetypes per task.
- ``qa_flake_records`` — rolling runs vs. failures per test id.
- ``qa_quarantine`` — tests pulled out of the blocking suite.
- ``qa_quality_gates`` — per-gate run results (axe, lighthouse, k6, gitleaks, osv, sbom, license).
- ``qa_outcome_cards`` — one-slide demo artifact per story.

Idempotent: IF NOT EXISTS everywhere. Safe to re-run.
"""

SQL = """
CREATE TABLE IF NOT EXISTS qa_test_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    required_json TEXT NOT NULL DEFAULT '[]',
    produced_json TEXT NOT NULL DEFAULT '[]',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_plans_project_task
    ON qa_test_plans(project_id, task_id);

CREATE TABLE IF NOT EXISTS qa_flake_records (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    runs INTEGER NOT NULL DEFAULT 0,
    failures INTEGER NOT NULL DEFAULT 0,
    last_failure_reason TEXT NOT NULL DEFAULT '',
    last_run_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_qa_flake_project_test
    ON qa_flake_records(project_id, test_id);
CREATE INDEX IF NOT EXISTS idx_qa_flake_project_updated
    ON qa_flake_records(project_id, updated_at);

CREATE TABLE IF NOT EXISTS qa_quarantine (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    test_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    quarantined_at TEXT NOT NULL,
    released_at TEXT,
    released_reason TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_qa_quarantine_project_status
    ON qa_quarantine(project_id, status);
CREATE INDEX IF NOT EXISTS idx_qa_quarantine_test
    ON qa_quarantine(test_id);

CREATE TABLE IF NOT EXISTS qa_quality_gates (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    gate TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'unknown',
    summary TEXT NOT NULL DEFAULT '',
    pr_url TEXT NOT NULL DEFAULT '',
    task_id TEXT NOT NULL DEFAULT '',
    score REAL,
    finding_count INTEGER NOT NULL DEFAULT 0,
    details_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_gates_project_created
    ON qa_quality_gates(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qa_gates_project_gate
    ON qa_quality_gates(project_id, gate);

CREATE TABLE IF NOT EXISTS qa_outcome_cards (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    story_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    acceptance_json TEXT NOT NULL DEFAULT '[]',
    metric_name TEXT NOT NULL DEFAULT '',
    metric_before TEXT NOT NULL DEFAULT '',
    metric_after TEXT NOT NULL DEFAULT '',
    screenshot_path TEXT NOT NULL DEFAULT '',
    narrated_video_path TEXT NOT NULL DEFAULT '',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_qa_cards_project_created
    ON qa_outcome_cards(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_qa_cards_project_story
    ON qa_outcome_cards(project_id, story_id);
"""
