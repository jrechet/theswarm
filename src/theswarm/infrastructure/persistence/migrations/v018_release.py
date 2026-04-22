"""Phase J — Release: versions, feature flags, rollback actions.

Three tables to close the loop on "we shipped it and can roll it back":

- ``release_versions`` — per-project cut release (UNIQUE project_id+version).
- ``feature_flags`` — per-project flag registry (UNIQUE project_id+name).
- ``rollback_actions`` — per-release revert reference, append-only log.

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS release_versions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    version TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft',
    summary TEXT NOT NULL DEFAULT '',
    released_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_release_versions_key
    ON release_versions(project_id, version);
CREATE INDEX IF NOT EXISTS idx_release_versions_status
    ON release_versions(status);

CREATE TABLE IF NOT EXISTS feature_flags (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    name TEXT NOT NULL,
    owner TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL DEFAULT 'active',
    rollout_percent INTEGER NOT NULL DEFAULT 0,
    cleanup_after_days INTEGER NOT NULL DEFAULT 90,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_feature_flags_key
    ON feature_flags(project_id, name);
CREATE INDEX IF NOT EXISTS idx_feature_flags_state
    ON feature_flags(state);

CREATE TABLE IF NOT EXISTS rollback_actions (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    release_version TEXT NOT NULL,
    revert_ref TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ready',
    note TEXT NOT NULL DEFAULT '',
    executed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rollback_actions_project
    ON rollback_actions(project_id);
CREATE INDEX IF NOT EXISTS idx_rollback_actions_release
    ON rollback_actions(project_id, release_version);
"""
