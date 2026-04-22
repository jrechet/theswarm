"""Phase I — SRE: deployments, incidents, cost samples.

Adds three tables:

- ``deployments`` — per-project deploy attempts.
- ``incidents`` — production incident lifecycle records (timeline JSON).
- ``cost_samples`` — unified AI + infra cost observations.

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS deployments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    environment TEXT NOT NULL DEFAULT 'production',
    version TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    notes TEXT NOT NULL DEFAULT '',
    triggered_by TEXT NOT NULL DEFAULT '',
    started_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_deployments_project
    ON deployments(project_id);
CREATE INDEX IF NOT EXISTS idx_deployments_status
    ON deployments(status);

CREATE TABLE IF NOT EXISTS incidents (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'sev3',
    status TEXT NOT NULL DEFAULT 'open',
    summary TEXT NOT NULL DEFAULT '',
    timeline_json TEXT NOT NULL DEFAULT '[]',
    postmortem TEXT NOT NULL DEFAULT '',
    detected_at TEXT NOT NULL,
    mitigated_at TEXT,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_incidents_project
    ON incidents(project_id);
CREATE INDEX IF NOT EXISTS idx_incidents_status
    ON incidents(status);
CREATE INDEX IF NOT EXISTS idx_incidents_severity
    ON incidents(severity);

CREATE TABLE IF NOT EXISTS cost_samples (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'other',
    amount_usd REAL NOT NULL DEFAULT 0,
    window TEXT NOT NULL DEFAULT 'daily',
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cost_samples_project
    ON cost_samples(project_id);
CREATE INDEX IF NOT EXISTS idx_cost_samples_source
    ON cost_samples(source);
"""
