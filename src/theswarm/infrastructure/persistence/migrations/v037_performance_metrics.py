"""Client-reported timing samples (#317), so a frontend click's latency can
be correlated with what the backend did in the same window.
"""

SQL = """
CREATE TABLE IF NOT EXISTS performance_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_timestamp TEXT NOT NULL,
    route TEXT NOT NULL,
    action TEXT NOT NULL,
    duration_ms REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_performance_metrics_route ON performance_metrics(route, id);
"""
