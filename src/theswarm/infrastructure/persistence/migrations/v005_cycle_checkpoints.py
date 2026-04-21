"""Sprint G1 — cycle_checkpoints table for phase-level resilience."""

SQL = """
CREATE TABLE IF NOT EXISTS cycle_checkpoints (
    cycle_id TEXT NOT NULL,
    phase TEXT NOT NULL,
    state_json TEXT NOT NULL,
    ok INTEGER NOT NULL,
    completed_at TEXT NOT NULL,
    PRIMARY KEY (cycle_id, phase)
);

CREATE INDEX IF NOT EXISTS idx_cycle_checkpoints_cycle
    ON cycle_checkpoints(cycle_id, completed_at ASC);
"""
