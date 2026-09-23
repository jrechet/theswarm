"""The cycle's trace id (V2 runtime, M2).

One OpenTelemetry trace per cycle, exported to Seq; the id on the row is
what turns a cycle page into a link to that trace. Added with an
introspected ALTER, the same way v006 added its columns: SQLite has no
``ADD COLUMN IF NOT EXISTS``.
"""

ALTERS = (
    ("trace_id", "ALTER TABLE cycles ADD COLUMN trace_id TEXT NOT NULL DEFAULT ''"),
)
