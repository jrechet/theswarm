"""How many cycles may run at once (Settings → Cycles): `*` for all the
repositories together, else one repository's own number. A missing row is
the default — the environment's SWARM_MAX_CONCURRENT_CYCLES, one per
repository."""

SQL = """
CREATE TABLE IF NOT EXISTS cycle_limits (
    scope TEXT PRIMARY KEY,
    max_cycles INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    updated_by TEXT NOT NULL DEFAULT ''
);
"""
