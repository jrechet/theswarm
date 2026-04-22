"""Phase I — Security: threat models, data inventory, findings, SBOMs, AuthZ.

Adds five tables:

- ``threat_models`` — per-project STRIDE snapshot (UNIQUE on ``project_id``).
- ``data_inventory`` — per-field classification (UNIQUE on ``project_id, field_name``).
- ``security_findings`` — open issues with severity + SLA.
- ``sbom_artifacts`` — bill of materials per cycle/snapshot.
- ``authz_rules`` — access matrix (UNIQUE on ``project_id, actor_role, resource, action``).

Idempotent: IF NOT EXISTS everywhere.
"""

SQL = """
CREATE TABLE IF NOT EXISTS threat_models (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    title TEXT NOT NULL DEFAULT '',
    assets TEXT NOT NULL DEFAULT '',
    actors TEXT NOT NULL DEFAULT '',
    trust_boundaries TEXT NOT NULL DEFAULT '',
    stride_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_threat_models_project
    ON threat_models(project_id);

CREATE TABLE IF NOT EXISTS data_inventory (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    field_name TEXT NOT NULL,
    classification TEXT NOT NULL DEFAULT 'internal',
    storage_notes TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_data_inventory_field
    ON data_inventory(project_id, field_name);
CREATE INDEX IF NOT EXISTS idx_data_inventory_class
    ON data_inventory(classification);

CREATE TABLE IF NOT EXISTS security_findings (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'medium',
    title TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    cve TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    resolution_note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_security_findings_project
    ON security_findings(project_id);
CREATE INDEX IF NOT EXISTS idx_security_findings_status
    ON security_findings(status);
CREATE INDEX IF NOT EXISTS idx_security_findings_severity
    ON security_findings(severity);

CREATE TABLE IF NOT EXISTS sbom_artifacts (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    cycle_id TEXT NOT NULL DEFAULT '',
    tool TEXT NOT NULL DEFAULT 'syft',
    package_count INTEGER NOT NULL DEFAULT 0,
    license_summary TEXT NOT NULL DEFAULT '',
    artifact_path TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_sbom_project
    ON sbom_artifacts(project_id);
CREATE INDEX IF NOT EXISTS idx_sbom_cycle
    ON sbom_artifacts(cycle_id);

CREATE TABLE IF NOT EXISTS authz_rules (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    actor_role TEXT NOT NULL,
    resource TEXT NOT NULL,
    action TEXT NOT NULL,
    effect TEXT NOT NULL DEFAULT 'allow',
    notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS idx_authz_rules_key
    ON authz_rules(project_id, actor_role, resource, action);
"""
