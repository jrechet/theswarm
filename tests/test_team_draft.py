"""A first team drafted from what a repository says (phase B, B5): facts, not guesses."""

from __future__ import annotations

from theswarm.application.services import team_draft, team_yaml

PYPROJECT = '[project]\nname = "x"\nrequires-python = ">=3.12"\ndependencies = ["fastapi"]\n[tool.ruff]\nline-length = 100\n[dependency-groups]\ndev = ["pytest"]\n'


class _Repo:
    def __init__(self, files):
        self.files = files

    async def get_file_content(self, path, ref="main"):
        if path not in self.files:
            raise FileNotFoundError(path)
        return self.files[path]


async def test_the_facts_are_what_the_files_say():
    files = await team_draft.read_facts(_Repo({"pyproject.toml": PYPROJECT, ".github/workflows/ci.yml": "on: push",
                                               "theswarm.yaml": "demo:\n  command: x\n", "GOLDEN_RULES.md": "# Rules"}))
    facts = team_draft.describe(files)
    assert facts == {"language": "Python", "python": ">=3.12", "tests": "pytest", "lint": "ruff", "framework": "FastAPI",
                     "ci": ".github/workflows/ci.yml", "demo": "declared in theswarm.yaml", "rules": "GOLDEN_RULES.md"}


def test_the_draft_is_a_valid_team_file_made_of_those_facts():
    facts = {"language": "Python", "tests": "pytest", "ci": ".github/workflows/ci.yml", "rules": "GOLDEN_RULES.md"}
    text = team_draft.draft("o/app", facts)
    personas, extras = team_yaml.load_team(text, "o/app")
    by_key = {p.key: p for p in personas}
    assert set(by_key) == {"techlead", "dev"} and extras == []  # nothing was learned for QA: left out
    assert "pytest" in by_key["dev"].instructions and "GOLDEN_RULES.md" in by_key["techlead"].instructions


def test_a_repository_that_says_nothing_gets_an_empty_team():
    assert team_draft.describe({}) == {}
    assert team_yaml.load_team(team_draft.draft("o/app", {}), "o/app") == ([], [])
    assert team_draft.describe({"package.json": '{"scripts": {"test": "vitest run"}}'}) == {
        "language": "JavaScript/TypeScript", "tests": "vitest run"}
