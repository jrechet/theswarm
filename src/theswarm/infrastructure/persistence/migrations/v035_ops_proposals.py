"""DevOps proposals (D3): what DevOps asks the owner to let it do on a host.

Raised from a finding (a stale CI slot, a runner offline, a deploy that
did not land), approved or refused with one click on the home, run once
approved, its result kept. Nothing on a machine changes without a row here
that says who approved it and what came back.
"""

SQL = """
CREATE TABLE IF NOT EXISTS ops_proposals (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    host TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    why TEXT NOT NULL DEFAULT '',
    command TEXT NOT NULL,
    finding_key TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'proposed',
    result TEXT NOT NULL DEFAULT '',
    decided_by TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    decided_at TEXT,
    ran_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_ops_proposals_status ON ops_proposals(status, created_at);
"""
