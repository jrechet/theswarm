"""Requests — a customer's need in their own words (V3 M5).

A member writes a request; it lands in the owner's inbox as ``received``.
The owner turns it into a feature (a GitHub issue on one of the
customer's projects): ``planned``, with the repository and the issue
number. A cycle started on that issue makes it ``building``; the demo of
that cycle makes it ``delivered``. The owner may ``decline`` it with a
reason. Nothing here is a GitHub object: the request is the customer's,
the issue is the swarm's.
"""

SQL = """
CREATE TABLE IF NOT EXISTS requests (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL REFERENCES customers(id),
    project_id TEXT NOT NULL DEFAULT '',
    member_id TEXT NOT NULL DEFAULT '',
    author_name TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'received',
    feature_repo TEXT NOT NULL DEFAULT '',
    feature_issue_number INTEGER,
    demo_report_id TEXT NOT NULL DEFAULT '',
    decline_reason TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_requests_customer ON requests(customer_id, created_at);
CREATE INDEX IF NOT EXISTS idx_requests_feature ON requests(feature_repo, feature_issue_number);
"""
