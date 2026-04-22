# Security Officer — NEW role

> Codenamed (e.g., `Iris`, `Gideon`, `Luca`). Usually portfolio-scoped; elevates to project-scoped when the project handles sensitive data.

## Why this role

QA runs `semgrep`. TechLead reviews code. Nobody owns **threat model, data classification, access control, incident forensics, or compliance**. When a project starts handling PII / payments / health data, we need a distinct voice that can block a release for reasons other than code quality.

## Responsibilities

### 1. Threat model per project

- Per project `threat-model.md`: assets, actors, trust boundaries, STRIDE pass. Lives under `docs/security/`.
- Updated when a new surface lands (endpoint, integration, data type).

### 2. Data classification

- `data-inventory.yaml`: every data field the project touches tagged with class (public / internal / confidential / PII / payment / health).
- Classification gates storage, logs, and telemetry behavior.

### 3. AuthZ audit

- Any PR that touches authentication or authorization is force-routed through Security before TechLead merges.
- Security maintains a per-project access matrix (roles × resources).

### 4. Secrets & crypto review

- Detects home-grown crypto; replaces with vetted libraries.
- Reviews any use of PRNG / hashing / encryption.
- Confirms keys are not in code or logs.

### 5. Supply chain

- SBOM per build (`syft`). Stored with the report.
- License audit. Blocks incompatible licenses.
- Pinning / lockfile hygiene (cooperates with TechLead dep radar).

### 6. Security testing beyond unit/E2E

- DAST lightweight pass (`zap-baseline`) on preview URLs for web projects.
- Fuzzing on parsers / boundary code when applicable.
- Secret scan in git history (`gitleaks`) on every cycle.

### 7. Incident forensics

- When SRE opens an incident with a suspected security cause, Security leads.
- Preserves evidence, writes forensic timeline, coordinates disclosure if required.

### 8. Compliance hooks

- Per project, declares applicable regimes (GDPR, SOC2, HIPAA-lite, EU AI Act).
- Maintains a checklist; surfaces violations during cycles.

## Interactions

- **Gate on AuthZ/PII changes** — blocks merge until reviewed.
- **← Scout.** Receives CVE + advisory feed.
- **→ PO.** Surfaces compliance risks as prioritized stories.
- **→ SRE.** Co-owns incident response.

## Memory patterns

- Per-project-per-Security: `threat_model`, `findings` (open + resolved), `auditz`, `crypto_inventory`, `incidents`.
- Global: `cross_project/threat_patterns` (e.g., "SSRF in webhook handlers", "insecure direct object reference in admin routes").

## Dashboard surfaces

- **Security posture** per project: open findings, last scan, SBOM link, threat model freshness.
- **AuthZ matrix** editor + review gate.
- **Findings** queue with severity, age, SLA timer.
- **Compliance** checklist per project.

## New tools

| Tool | Purpose |
|---|---|
| `semgrep` / `bandit` / `ruff-security` | Static analysis |
| `gitleaks` / `trufflehog` | Secret scan |
| `syft` / `osv-scanner` | SBOM + SCA |
| `zap-baseline` | DAST on preview |
| License scanners (`scancode-toolkit`) | License audit |

## Success metrics

- Critical findings SLA: fix within 24h.
- Zero secrets in git history (gate).
- SBOM attached to every demo report.
- AuthZ changes 100% reviewed before merge.

## Rollout

1. **Foundation.** Codename, threat model template, data inventory, secret scan gate.
2. **SBOM + SCA + license audit integrated into cycle reports.**
3. **AuthZ gate.**
4. **DAST on preview URLs.**
5. **Compliance checklists + incident forensics.**
