"""The team's roles, once (A4).

The same five roles were written four ways in five places: the key the code
passes around ("techlead"), the voice an agent speaks under in the feed and
the watchdog ("TechLead"), the name a page shows ("Tech Lead"), the glyph of
its station ("TL") — in the theater's stations, its aliases, the API's
persona names, the watchdog's roles, Settings → Agents and the effort
profile. Phase B makes the team configurable: there is one table to change.

`key` is what is stored and compared. `voice` is what `rt.progress(voice, …)`
says and what the watchdog hears; it is part of the event history, so it
does not change. A role of the cycle owns phases; DevOps does not.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RoleDef:
    key: str
    voice: str
    name: str
    glyph: str
    in_cycle: bool = True


ROLES: tuple[RoleDef, ...] = (
    RoleDef("po", "PO", "Product Owner", "PO"),
    RoleDef("techlead", "TechLead", "Tech Lead", "TL"),
    RoleDef("dev", "Dev", "Developer", "DEV"),
    RoleDef("qa", "QA", "QA", "QA"),
    RoleDef("devops", "DevOps", "DevOps", "OPS", in_cycle=False),
)
CYCLE_ROLES: tuple[RoleDef, ...] = tuple(r for r in ROLES if r.in_cycle)
ROLE_KEYS: tuple[str, ...] = tuple(r.key for r in ROLES)
CYCLE_ROLE_KEYS: tuple[str, ...] = tuple(r.key for r in CYCLE_ROLES)
CYCLE_VOICES: frozenset[str] = frozenset(r.voice for r in CYCLE_ROLES)

_BY_KEY = {r.key: r for r in ROLES}
# Other spellings met in events and settings written before this table.
_OTHER_SPELLINGS = {
    "product_owner": "po", "productowner": "po",
    "tech_lead": "techlead", "tl": "techlead",
    "developer": "dev",
    "tester": "qa",
}


def role(key: str) -> RoleDef | None:
    return _BY_KEY.get(key)


def key_of(raw: str | None, *, cycle_only: bool = False) -> str | None:
    """The role a spelling names — a key, a voice, a name, an older alias —
    None for anything else. `cycle_only`: the four roles that own phases."""
    text = str(raw or "").strip().lower().replace("-", "_").replace(" ", "_")
    key = text if text in _BY_KEY else _OTHER_SPELLINGS.get(text)
    if key is None:
        key = next((r.key for r in ROLES if text in (r.voice.lower(), r.name.lower().replace(" ", "_"))), None)
    if key is None or (cycle_only and not _BY_KEY[key].in_cycle):
        return None
    return key


def voice_of(key: str) -> str:
    found = _BY_KEY.get(key)
    return found.voice if found else key
