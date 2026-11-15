"""One table of roles (A4): the theater, the watchdog, the API and Settings →
Agents each kept their own spelling of the same five."""

from __future__ import annotations

from theswarm import api, cycle
from theswarm.application.services import effort_profile
from theswarm.domain.agents import roles, settings
from theswarm.presentation.web.routes import stage


def test_every_spelling_names_its_role():
    assert roles.key_of("TechLead") == roles.key_of("tech-lead") == roles.key_of("TL") == roles.key_of("Tech Lead") == "techlead"
    assert roles.key_of("Developer") == roles.key_of("Dev") == "dev" and roles.key_of("tester") == "qa"
    assert roles.key_of("DevOps") == "devops" and roles.key_of("DevOps", cycle_only=True) is None
    assert roles.key_of("System") is None and roles.key_of(None) is None and roles.key_of("owner") is None
    assert roles.voice_of("techlead") == "TechLead" and roles.voice_of("unknown") == "unknown"


def test_every_table_comes_from_it():
    assert stage._STATIONS == (("po", "PO", "Product Owner"), ("techlead", "TL", "Tech Lead"),
                               ("dev", "DEV", "Developer"), ("qa", "QA", "QA"))
    assert stage._DEVOPS == ("devops", "OPS", "DevOps")
    assert cycle.STALL_ROLES == frozenset({"PO", "TechLead", "Dev", "QA"})
    assert api._PERSONA_NAMES == (("po", "Product Owner"), ("techlead", "Tech Lead"), ("dev", "Developer"), ("qa", "QA"))
    assert tuple(effort_profile._PHASES) == ("po", "techlead", "dev", "qa")
    assert settings.PERSONA_KEYS == roles.ROLE_KEYS == ("po", "techlead", "dev", "qa", "devops")
    assert [name for _, name, _ in settings.PERSONAS] == [r.name for r in roles.ROLES]


def test_the_stage_reads_a_voice_as_its_station():
    assert stage._normalize_role("TechLead") == "techlead" and stage._normalize_role("Dev") == "dev"
    assert stage._normalize_role("DevOps") is None and stage._normalize_role("System") is None


def test_the_phases_name_roles_of_the_table():
    from theswarm.domain.cycles.value_objects import CYCLE_NODE_ROLES

    assert set(CYCLE_NODE_ROLES.values()) <= set(roles.CYCLE_ROLE_KEYS)
