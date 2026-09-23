"""Where an interrupted cycle went on (V2 runtime, M4).

A restart reaps the interrupted row to 'failed' and the boot resumer
continues its durable graph under a new tracker id. Without a link, the
harness scored the old id as a failure and the theater showed it dead
while the cycle was running under another name. Added with an
introspected ALTER, like v027.
"""

ALTERS = (
    ("resumed_as", "ALTER TABLE cycles ADD COLUMN resumed_as TEXT NOT NULL DEFAULT ''"),
)
