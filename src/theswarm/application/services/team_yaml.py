"""A team as YAML (phase B, B2): what the export hands out and the import reads.

```yaml
format: 1
team: jrechet/concert-tour-app     # or "instance" for every project
template: feature                  # the flow (B3 adds the others)
personas:
  dev:
    name: Aarav
    description: Careful with migrations.
    instructions: |
      Type every function.
    model: opus
    effort: high
```

Only what the owner wrote for this scope is in the file: an absent role, or
an absent field, inherits. An import replaces the scope's personas with the
file's, after every one of them was validated — nothing is half-written.
"""

from __future__ import annotations

import yaml

from theswarm.domain.agents.persona import INSTANCE, Persona, PersonaError
from theswarm.domain.agents.roles import CYCLE_ROLE_KEYS

FORMAT = 1
INSTANCE_NAME = "instance"
TEMPLATE = "feature"
_FIELDS = ("name", "description", "instructions", "model", "effort")
MAX_YAML_CHARS = 60_000


class TeamYamlError(ValueError):
    """A team file that cannot be read, said in words for the owner."""


class _Block(yaml.SafeDumper):
    """Multi-line instructions as a block, the way a person would write them."""


def _str(dumper, value):
    return dumper.represent_scalar("tag:yaml.org,2002:str", value, style="|" if "\n" in value else None)


_Block.add_representer(str, _str)


def dump(scope: str, personas: list[Persona]) -> str:
    """The scope's personas as a team file; stable, so two equal teams are equal text."""
    body: dict = {"format": FORMAT, "team": scope or INSTANCE_NAME, "template": TEMPLATE, "personas": {}}
    by_key = {p.key: p for p in personas if p.scope == scope}
    for key in CYCLE_ROLE_KEYS:
        persona = by_key.get(key)
        if persona is None or persona.empty:
            continue
        body["personas"][key] = {f: getattr(persona, f) for f in _FIELDS if getattr(persona, f)}
    return yaml.dump(body, Dumper=_Block, sort_keys=False, allow_unicode=True, width=100)


def load(text: str, scope: str, *, by: str = "owner") -> list[Persona]:
    """The personas a team file gives `scope`, every one validated; raises
    `TeamYamlError` naming what is wrong."""
    if len(text or "") > MAX_YAML_CHARS:
        raise TeamYamlError(f"A team file of {MAX_YAML_CHARS} characters at most.")
    try:
        raw = yaml.safe_load(text or "")
    except yaml.YAMLError as exc:
        raise TeamYamlError(f"Not valid YAML: {str(exc).splitlines()[0]}") from exc
    if not isinstance(raw, dict):
        raise TeamYamlError("A team file is a mapping with `format`, `team` and `personas`.")
    if raw.get("format") != FORMAT:
        raise TeamYamlError(f"`format: {FORMAT}` is the one this version reads, not {raw.get('format')!r}.")
    named = raw.get("team")
    if named not in (None, scope or INSTANCE_NAME):
        raise TeamYamlError(f"This file is the team of {named!r}, not of {scope or INSTANCE_NAME!r}.")
    if raw.get("template", TEMPLATE) != TEMPLATE:
        raise TeamYamlError(f"`template: {TEMPLATE}` is the only flow yet, not {raw.get('template')!r}.")
    personas = raw.get("personas") or {}
    if not isinstance(personas, dict):
        raise TeamYamlError("`personas` is a mapping of role to its fields.")
    out: list[Persona] = []
    for key, fields in personas.items():
        if key not in CYCLE_ROLE_KEYS:
            raise TeamYamlError(f"{key!r} is not a role of the cycle ({', '.join(CYCLE_ROLE_KEYS)}).")
        if not isinstance(fields, dict):
            raise TeamYamlError(f"{key}: a mapping of {', '.join(_FIELDS)}.")
        unknown = sorted(set(fields) - set(_FIELDS))
        if unknown:
            raise TeamYamlError(f"{key}: {', '.join(unknown)} is not a field ({', '.join(_FIELDS)}).")
        values = {f: str(fields.get(f) or "").strip() for f in _FIELDS}
        if not scope and (values["model"] or values["effort"]):
            raise TeamYamlError(f"{key}: the model for every project is set in Settings → Agents, not in the team file.")
        if values["effort"] and not values["model"]:
            raise TeamYamlError(f"{key}: an effort goes with a model.")
        try:
            persona = Persona(scope=scope or INSTANCE, key=key, updated_by=by, **values)
        except PersonaError as exc:
            raise TeamYamlError(str(exc)) from exc
        if not persona.empty:
            out.append(persona)
    return out
