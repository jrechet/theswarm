"""Phase J — Analyst: metric definitions, instrumentation plans, outcomes.

Three tables to surface "does this project actually measure what it claims?":

- ``metric_definitions`` — per-project metric catalog (UNIQUE project_id+name).
- ``instrumentation_plans`` — per-story measurement plan
  (UNIQUE project_id+story_id+metric_name).
- ``outcome_observations`` — did it move? (appended per story/metric).

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS metric_definitions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'counter',
    unit TEXT NOT NULL DEFAULT '',
    definition TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL DEFAULT '',
    target TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_metric_definitions_key
    ON metric_definitions(project_id, name);

CREATE TABLE IF NOT EXISTS instrumentation_plans (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    hypothesis TEXT NOT NULL DEFAULT '',
    method TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_instrumentation_plans_key
    ON instrumentation_plans(project_id, story_id, metric_name);
CREATE INDEX IF NOT EXISTS idx_instrumentation_plans_status
    ON instrumentation_plans(status);

CREATE TABLE IF NOT EXISTS outcome_observations (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    story_id TEXT NOT NULL,
    metric_name TEXT NOT NULL,
    baseline TEXT NOT NULL DEFAULT '',
    observed TEXT NOT NULL DEFAULT '',
    direction TEXT NOT NULL DEFAULT 'inconclusive',
    window TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_outcome_observations_project
    ON outcome_observations(project_id);
CREATE INDEX IF NOT EXISTS idx_outcome_observations_story
    ON outcome_observations(project_id, story_id);
"""
