"""The customer-facing summary of a demo (written by the PO when it lands).

One row per report: `written` with its headline and body, or `skipped`
with the reason (Claude's window shut, the draft named machinery twice).
Beside the report, never inside it: the report is what the team built,
this is what the customer is told.
"""

SQL = """
CREATE TABLE IF NOT EXISTS demo_summaries (
    report_id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'written',
    headline TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    written_by TEXT NOT NULL DEFAULT 'PO',
    created_at TEXT NOT NULL
);
"""
