"""Phase H — Designer: tokens, components, briefs, VR, anti-template checks.

Adds five tables:

- ``design_tokens`` — design-system entries (UNIQUE on ``project_id, name``).
- ``design_components`` — component inventory (UNIQUE on ``project_id, name``).
- ``design_briefs`` — per-story design brief (UNIQUE on ``project_id, story_id``).
- ``visual_regressions`` — designer/QA co-review records per story.
- ``anti_template_checks`` — ship-bar results (qualities + violations as JSON).

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS design_tokens (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'other',
    value TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_design_tokens_name
    ON design_tokens(project_id, name);
CREATE INDEX IF NOT EXISTS idx_design_tokens_kind
    ON design_tokens(kind);

CREATE TABLE IF NOT EXISTS design_components (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    path TEXT NOT NULL DEFAULT '',
    usage_count INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_design_components_name
    ON design_components(project_id, name);
CREATE INDEX IF NOT EXISTS idx_design_components_status
    ON design_components(status);

CREATE TABLE IF NOT EXISTS design_briefs (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    story_id TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    intent TEXT NOT NULL DEFAULT '',
    hierarchy TEXT NOT NULL DEFAULT '',
    states TEXT NOT NULL DEFAULT '',
    motion TEXT NOT NULL DEFAULT '',
    reference_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    approval_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_design_briefs_story
    ON design_briefs(project_id, story_id);
CREATE INDEX IF NOT EXISTS idx_design_briefs_status
    ON design_briefs(status);

CREATE TABLE IF NOT EXISTS visual_regressions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    story_id TEXT NOT NULL DEFAULT '',
    viewport TEXT NOT NULL DEFAULT '',
    before_path TEXT NOT NULL DEFAULT '',
    after_path TEXT NOT NULL DEFAULT '',
    mask_notes TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    reviewer_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_visual_regressions_story
    ON visual_regressions(project_id, story_id);
CREATE INDEX IF NOT EXISTS idx_visual_regressions_status
    ON visual_regressions(status);

CREATE TABLE IF NOT EXISTS anti_template_checks (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    story_id TEXT NOT NULL DEFAULT '',
    pr_url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'unknown',
    violations_json TEXT NOT NULL DEFAULT '[]',
    qualities_json TEXT NOT NULL DEFAULT '[]',
    summary TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_anti_template_project
    ON anti_template_checks(project_id);
CREATE INDEX IF NOT EXISTS idx_anti_template_story
    ON anti_template_checks(project_id, story_id);
"""
