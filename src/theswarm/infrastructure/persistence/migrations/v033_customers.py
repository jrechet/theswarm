"""Customers and their members (V3 M2, docs/plans/2026-10-v3-one-product.md).

A customer is a company the owner works for; its members sign in and see
only it. A project belongs to one customer: ``projects.customer_id``, added
with an introspected ALTER like v027/v029/v030/v032, defaults every project
that exists to the customer **Internal** (slug ``internal``), created here;
the owner moves them from Settings.

A member is invited by email: the invitation is a link whose token is kept
hashed here and shown to the owner once; accepting it sets ``accepted_at``
and clears the token. ``revoked_at`` closes the door without losing who
was there.
"""

SQL = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    slug TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS members (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    email TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    github_login TEXT NOT NULL DEFAULT '',
    invited_at TEXT NOT NULL,
    invite_token_hash TEXT NOT NULL DEFAULT '',
    invite_expires_at TEXT NOT NULL DEFAULT '',
    accepted_at TEXT NOT NULL DEFAULT '',
    last_seen_at TEXT NOT NULL DEFAULT '',
    revoked_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_members_customer ON members(customer_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_members_customer_email ON members(customer_id, email);
CREATE INDEX IF NOT EXISTS idx_members_invite ON members(invite_token_hash);

INSERT OR IGNORE INTO customers (id, slug, name, created_at)
VALUES ('internal', 'internal', 'Internal', '2026-10-06T00:00:00+00:00');
"""

ALTERS = (
    ("customer_id", "ALTER TABLE projects ADD COLUMN customer_id TEXT NOT NULL DEFAULT 'internal'"),
)
