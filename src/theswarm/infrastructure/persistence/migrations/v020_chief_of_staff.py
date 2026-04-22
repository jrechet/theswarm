"""Phase K — Chief of Staff: routing, budget, onboarding, archive.

Four tables for portfolio-level operations:

- ``routing_rules`` — keyword rules mapping chat to role (+codename).
- ``budget_policies`` — portfolio or per-project budgets.
- ``onboarding_steps`` — new-project onboarding wizard progress.
- ``archived_projects`` — append-only record of archived projects.

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS routing_rules (
    id TEXT PRIMARY KEY,
    pattern TEXT NOT NULL,
    target_role TEXT NOT NULL,
    target_codename TEXT NOT NULL DEFAULT '',
    priority INTEGER NOT NULL DEFAULT 100,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_routing_rules_pattern
    ON routing_rules(pattern);
CREATE INDEX IF NOT EXISTS idx_routing_rules_status
    ON routing_rules(status);
CREATE INDEX IF NOT EXISTS idx_routing_rules_priority
    ON routing_rules(priority);

CREATE TABLE IF NOT EXISTS budget_policies (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    daily_tokens_limit INTEGER NOT NULL DEFAULT 0,
    daily_cost_usd_limit REAL NOT NULL DEFAULT 0,
    state TEXT NOT NULL DEFAULT 'active',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_budget_policies_project
    ON budget_policies(project_id);
CREATE INDEX IF NOT EXISTS idx_budget_policies_state
    ON budget_policies(state);

CREATE TABLE IF NOT EXISTS onboarding_steps (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    step_name TEXT NOT NULL,
    step_order INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    note TEXT NOT NULL DEFAULT '',
    completed_at TEXT,
    created_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_onboarding_steps_project_name
    ON onboarding_steps(project_id, step_name);
CREATE INDEX IF NOT EXISTS idx_onboarding_steps_project
    ON onboarding_steps(project_id);
CREATE INDEX IF NOT EXISTS idx_onboarding_steps_status
    ON onboarding_steps(status);

CREATE TABLE IF NOT EXISTS archived_projects (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    reason TEXT NOT NULL DEFAULT 'other',
    memory_frozen INTEGER NOT NULL DEFAULT 1,
    export_path TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    archived_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_archived_projects_project
    ON archived_projects(project_id);
CREATE INDEX IF NOT EXISTS idx_archived_projects_archived_at
    ON archived_projects(archived_at);
"""
