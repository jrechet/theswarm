"""The issue a cycle was started on, on its row.

The theater draws a running cycle from the in-memory tracker; after a
restart — every deploy — a finished cycle's `/c/{id}` fell back to the V1
archive and its demo card was gone for every link already shared. The
theater now draws a finished cycle from the database, and the pinned
issue needs its number. Added with an introspected ALTER, like v027,
v029 and v030; NULL for the cycles before it and for untargeted ones.
"""

ALTERS = (
    ("issue_number", "ALTER TABLE cycles ADD COLUMN issue_number INTEGER"),
)
