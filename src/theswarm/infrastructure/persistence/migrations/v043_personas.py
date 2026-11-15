"""A persona is data (phase B, B1): for the instance (scope '') or one project
(scope 'owner/name'), a role's name, description, instructions, and the model
and effort it runs on. An empty column inherits: the project from the
instance, the instance from the built-in role (`domain.agents.roles`) and
Settings → Agents' model (`agent_settings`)."""

SQL = """
CREATE TABLE IF NOT EXISTS personas (
    scope TEXT NOT NULL DEFAULT '',
    key TEXT NOT NULL,
    name TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    instructions TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    effort TEXT NOT NULL DEFAULT '',
    updated_by TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    PRIMARY KEY (scope, key)
);
"""
