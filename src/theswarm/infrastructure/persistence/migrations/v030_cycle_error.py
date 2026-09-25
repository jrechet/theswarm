"""Why a cycle failed, on its row.

The tracker kept a failure's text in memory only: after a restart the API
answered `"error": null` for every failed cycle, and the continuation
46ff31375dce, killed by a second deploy on 2026-09-25 and deliberately not
resumed again, read "failed" and nothing else. Added with an introspected
ALTER, like v027 and v029.
"""

ALTERS = (
    ("error", "ALTER TABLE cycles ADD COLUMN error TEXT NOT NULL DEFAULT ''"),
)
