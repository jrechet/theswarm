"""Which Claude each persona runs on (Settings → Agents): one row per persona
the owner set; a persona without a row runs on the instance's model."""

SQL = """
CREATE TABLE IF NOT EXISTS agent_settings (
    persona TEXT PRIMARY KEY,
    model TEXT NOT NULL,
    effort TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL
);
"""
