"""Phase K — Architect: paved road, portfolio ADRs, direction briefs.

Three tables to capture portfolio-wide design decisions:

- ``paved_road_rules`` — portfolio conventions (UNIQUE name).
- ``portfolio_adrs`` — architectural decisions, portfolio or project-scoped.
- ``direction_briefs`` — forward-looking briefs per period/scope.

Idempotent: IF NOT EXISTS everywhere. Tags stored as comma-separated text for
SQLite portability; tuple fields round-tripped as newline-delimited text.
"""

SQL = """
CREATE TABLE IF NOT EXISTS paved_road_rules (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    rule TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL DEFAULT '',
    severity TEXT NOT NULL DEFAULT 'advisory',
    tags TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_paved_road_rules_name
    ON paved_road_rules(name);
CREATE INDEX IF NOT EXISTS idx_paved_road_rules_severity
    ON paved_road_rules(severity);

CREATE TABLE IF NOT EXISTS portfolio_adrs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'proposed',
    context TEXT NOT NULL DEFAULT '',
    decision TEXT NOT NULL DEFAULT '',
    consequences TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    supersedes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_portfolio_adrs_status
    ON portfolio_adrs(status);
CREATE INDEX IF NOT EXISTS idx_portfolio_adrs_project
    ON portfolio_adrs(project_id);

CREATE TABLE IF NOT EXISTS direction_briefs (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    scope TEXT NOT NULL DEFAULT 'portfolio',
    project_id TEXT NOT NULL DEFAULT '',
    period TEXT NOT NULL DEFAULT '',
    author TEXT NOT NULL DEFAULT '',
    focus_areas_text TEXT NOT NULL DEFAULT '',
    risks_text TEXT NOT NULL DEFAULT '',
    narrative TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_direction_briefs_scope
    ON direction_briefs(scope);
CREATE INDEX IF NOT EXISTS idx_direction_briefs_project
    ON direction_briefs(project_id);
"""
