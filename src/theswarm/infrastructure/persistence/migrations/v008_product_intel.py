"""Phase C — PO intelligence tables.

Adds five tables:

- ``product_proposals`` — PO inbox: candidate stories awaiting triage.
- ``product_okrs`` + ``product_key_results`` — outcome framing per project.
- ``product_policies`` — per-project hard product rules (one row per project).
- ``product_signals`` — observed competitor/ecosystem/customer events.
- ``product_digests`` — generated weekly digests (archive).

Idempotent: IF NOT EXISTS everywhere. Safe to re-run.
"""

SQL = """
CREATE TABLE IF NOT EXISTS product_proposals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    dedup_key TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    evidence_excerpt TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0.5,
    status TEXT NOT NULL DEFAULT 'proposed',
    codename TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    decided_at TEXT NOT NULL DEFAULT '',
    decision_note TEXT NOT NULL DEFAULT '',
    linked_story_id TEXT NOT NULL DEFAULT ''
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_proposals_dedup
    ON product_proposals(project_id, dedup_key);
CREATE INDEX IF NOT EXISTS idx_proposals_project_status
    ON product_proposals(project_id, status);
CREATE INDEX IF NOT EXISTS idx_proposals_created
    ON product_proposals(created_at);

CREATE TABLE IF NOT EXISTS product_okrs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    objective TEXT NOT NULL,
    quarter TEXT NOT NULL DEFAULT '',
    owner_codename TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_okrs_project ON product_okrs(project_id, active);

CREATE TABLE IF NOT EXISTS product_key_results (
    id TEXT PRIMARY KEY,
    okr_id TEXT NOT NULL,
    description TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    baseline TEXT NOT NULL DEFAULT '',
    current TEXT NOT NULL DEFAULT '',
    progress REAL NOT NULL DEFAULT 0.0,
    ordinal INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_kr_okr ON product_key_results(okr_id, ordinal);

CREATE TABLE IF NOT EXISTS product_policies (
    project_id TEXT PRIMARY KEY,
    id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT 'Project policy',
    body_markdown TEXT NOT NULL DEFAULT '',
    banned_terms_json TEXT NOT NULL DEFAULT '[]',
    require_review_terms_json TEXT NOT NULL DEFAULT '[]',
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS product_signals (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    severity TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    source_url TEXT NOT NULL DEFAULT '',
    source_name TEXT NOT NULL DEFAULT '',
    tags_json TEXT NOT NULL DEFAULT '[]',
    observed_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_signals_project_observed
    ON product_signals(project_id, observed_at);
CREATE INDEX IF NOT EXISTS idx_signals_kind ON product_signals(kind);

CREATE TABLE IF NOT EXISTS product_digests (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    week_start TEXT NOT NULL,
    narrative TEXT NOT NULL DEFAULT '',
    items_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_digests_project_week
    ON product_digests(project_id, week_start);
"""
