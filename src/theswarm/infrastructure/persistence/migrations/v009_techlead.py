"""Phase D — TechLead: architecture, debt, dep radar, review calibration.

Adds five tables:

- ``techlead_adrs`` — architecture decision records (per project, numbered).
- ``techlead_debt`` — tech-debt register with severity + blast radius + owner.
- ``techlead_dep_findings`` — dependency radar findings (CVE / advisory / OSV).
- ``techlead_review_verdicts`` — recorded reviews + outcomes for calibration.
- ``techlead_critical_paths`` — file/module patterns flagged for 2nd-opinion.

Idempotent: IF NOT EXISTS everywhere. Safe to re-run.
"""

SQL = """
CREATE TABLE IF NOT EXISTS techlead_adrs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    number INTEGER NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    context TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    consequences TEXT NOT NULL DEFAULT '',
    supersedes TEXT,
    tags_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_adrs_project_number
    ON techlead_adrs(project_id, number);
CREATE INDEX IF NOT EXISTS idx_adrs_project_status
    ON techlead_adrs(project_id, status);

CREATE TABLE IF NOT EXISTS techlead_debt (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    blast_radius TEXT NOT NULL DEFAULT '',
    location TEXT NOT NULL DEFAULT '',
    owner_codename TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    resolved INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_debt_project_resolved
    ON techlead_debt(project_id, resolved);
CREATE INDEX IF NOT EXISTS idx_debt_severity ON techlead_debt(severity);

CREATE TABLE IF NOT EXISTS techlead_dep_findings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    package TEXT NOT NULL,
    installed_version TEXT NOT NULL DEFAULT '',
    advisory_id TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'info',
    summary TEXT NOT NULL DEFAULT '',
    fixed_version TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '',
    observed_at TEXT NOT NULL,
    dismissed INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_dep_unique
    ON techlead_dep_findings(project_id, package, advisory_id);
CREATE INDEX IF NOT EXISTS idx_dep_project_sev
    ON techlead_dep_findings(project_id, severity);

CREATE TABLE IF NOT EXISTS techlead_review_verdicts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    pr_url TEXT NOT NULL,
    reviewer_codename TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT 'approve',
    severity TEXT NOT NULL DEFAULT 'low',
    override_reason TEXT NOT NULL DEFAULT '',
    second_opinion INTEGER NOT NULL DEFAULT 0,
    outcome TEXT NOT NULL DEFAULT 'unknown',
    outcome_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    outcome_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_verdicts_project
    ON techlead_review_verdicts(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_verdicts_outcome
    ON techlead_review_verdicts(outcome);

CREATE TABLE IF NOT EXISTS techlead_critical_paths (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    pattern TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_crit_project ON techlead_critical_paths(project_id);
"""
