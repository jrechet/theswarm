"""Phase B — dashboard chat + HITL audit.

Adds three tables:

- ``chat_threads`` — one thread per ``(project_id, codename)`` or a portfolio
  thread (``project_id = '__portfolio__'``).
- ``chat_messages`` — append-only message log per thread. ``author_kind`` is
  ``human``, ``agent``, or ``system``. ``intent_action`` is populated when the
  NLU classified the message into a known action.
- ``hitl_audit`` — every human intervention on a running cycle: nudge, pause,
  skip, override, ask-answered, etc. Preserved forever for traceability.

Idempotent: all statements use IF NOT EXISTS.
"""

SQL = """
CREATE TABLE IF NOT EXISTS chat_threads (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    codename TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    last_message_at TEXT NOT NULL DEFAULT '',
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_threads_project_codename
    ON chat_threads(project_id, codename);
CREATE INDEX IF NOT EXISTS idx_chat_threads_project
    ON chat_threads(project_id);

CREATE TABLE IF NOT EXISTS chat_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    author_kind TEXT NOT NULL,
    author_id TEXT NOT NULL DEFAULT '',
    author_display TEXT NOT NULL DEFAULT '',
    body TEXT NOT NULL,
    intent_action TEXT NOT NULL DEFAULT '',
    intent_confidence REAL NOT NULL DEFAULT 0.0,
    reply_to TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_chat_messages_thread
    ON chat_messages(thread_id, created_at);

CREATE TABLE IF NOT EXISTS hitl_audit (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL DEFAULT '',
    actor TEXT NOT NULL DEFAULT 'human',
    action TEXT NOT NULL,
    target TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_hitl_audit_project
    ON hitl_audit(project_id, created_at);
CREATE INDEX IF NOT EXISTS idx_hitl_audit_cycle
    ON hitl_audit(cycle_id);
"""
