"""A sign-off after the E2E code is not part of the file.

price-stats (2026-09-29): the E2E writer ended its answer with its
persona's sign-off — "Dima here — that's the full E2E suite for
concert-tour-app, …" — on the line after the last test. The file did not
even collect (SyntaxError: invalid character '—'), QA spent a repair call
on it, and the day's PO would read "repaired once" again. Trailing prose
is cut off the code; a real syntax error inside the code is not hidden.
"""

from __future__ import annotations

import ast

from theswarm.agents.qa import _extract_python_code

CODE = '''import pytest

BASE_URL = "http://127.0.0.1:8000"


def test_feature_prices(api_context):
    assert api_context.get("/api/v1/stats/prices").ok
'''


def test_a_trailing_sign_off_is_cut():
    answer = CODE + ("\nDima here — that's the full E2E suite for `concert-tour-app`, written against "
                     "the running app at `127.0.0.1:8000`.\nFeature tests come first.\n")

    code = _extract_python_code(answer)

    ast.parse(code)
    assert code.rstrip().endswith('assert api_context.get("/api/v1/stats/prices").ok')
    assert "Dima" not in code


def test_a_syntax_error_inside_the_code_is_left_for_pytest_to_report():
    broken = CODE.replace("def test_feature_prices(api_context):", "def test_feature_prices(api_context:") + (
        "\n\ndef test_other(api_context):\n    assert True\n")

    code = _extract_python_code(broken)

    assert "def test_other" in code  # nothing cut: the error is the file's, not a sign-off


def test_code_that_parses_is_untouched():
    assert _extract_python_code(CODE) == CODE.strip()
