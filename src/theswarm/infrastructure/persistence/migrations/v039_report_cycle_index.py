"""Reports by cycle, with an index. The project page and the theater look a
cycle's report up one cycle at a time (`list_by_cycle`), and without an
index each lookup read every report's JSON from disk: 116–275 ms on prod
under a running cycle (the slow-query log, 2026-10-10), six of them per
project page."""

SQL = """
CREATE INDEX IF NOT EXISTS idx_reports_cycle ON reports(cycle_id, created_at DESC);
"""
