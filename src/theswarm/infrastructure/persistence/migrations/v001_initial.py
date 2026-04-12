"""Initial database schema."""

SQL = """
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    repo TEXT NOT NULL,
    default_branch TEXT NOT NULL DEFAULT 'main',
    framework TEXT NOT NULL DEFAULT 'generic',
    ticket_source TEXT NOT NULL DEFAULT 'github',
    team_channel TEXT NOT NULL DEFAULT '',
    schedule TEXT NOT NULL DEFAULT '',
    test_command TEXT NOT NULL DEFAULT '',
    source_dir TEXT NOT NULL DEFAULT 'src/',
    config_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cycles (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    triggered_by TEXT NOT NULL DEFAULT '',
    started_at TEXT,
    completed_at TEXT,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    total_cost_usd REAL NOT NULL DEFAULT 0.0,
    prs_opened_json TEXT NOT NULL DEFAULT '[]',
    prs_merged_json TEXT NOT NULL DEFAULT '[]',
    phases_json TEXT NOT NULL DEFAULT '[]',
    budgets_json TEXT NOT NULL DEFAULT '[]',
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    action TEXT NOT NULL,
    detail TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reports (
    id TEXT PRIMARY KEY,
    cycle_id TEXT NOT NULL,
    project_id TEXT NOT NULL,
    summary_json TEXT NOT NULL DEFAULT '{}',
    stories_json TEXT NOT NULL DEFAULT '[]',
    quality_json TEXT NOT NULL DEFAULT '[]',
    learnings_json TEXT NOT NULL DEFAULT '[]',
    artifacts_json TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schedules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    next_run TEXT,
    created_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id)
);

CREATE TABLE IF NOT EXISTS memory_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL,
    content TEXT NOT NULL,
    agent TEXT NOT NULL DEFAULT '',
    cycle_date TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_cycles_project ON cycles(project_id, started_at DESC);
CREATE INDEX IF NOT EXISTS idx_activities_cycle ON activities(cycle_id, created_at);
CREATE INDEX IF NOT EXISTS idx_reports_project ON reports(project_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_memory_project ON memory_entries(project_id, category);
CREATE INDEX IF NOT EXISTS idx_schedules_project ON schedules(project_id);
"""
