"""Tests for the hash-anchored file editing tool."""

from __future__ import annotations

import hashlib
import os
import textwrap

import pytest

from theswarm.tools.hashline import (
    ApplyResult,
    HashlineEdit,
    apply_hashline_edits,
    hash_tagged_read,
    parse_hashline_edits,
    validate_hash,
)


# ---- helpers ------------------------------------------------------------- #


def _expected_hash(content: str) -> str:
    """Compute the 2-char hash the same way the module does."""
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()[:2]


# ---- validate_hash ------------------------------------------------------ #


class TestValidateHash:
    def test_matching_hash(self) -> None:
        line = "def hello():"
        h = _expected_hash(line)
        assert validate_hash(line, h) is True

    def test_mismatched_hash(self) -> None:
        assert validate_hash("def hello():", "zz") is False

    def test_strips_whitespace_before_hashing(self) -> None:
        h = _expected_hash("return 42")
        # Leading/trailing whitespace should not change the hash
        assert validate_hash("    return 42   ", h) is True

    def test_empty_line(self) -> None:
        h = _expected_hash("")
        assert validate_hash("", h) is True
        assert validate_hash("   ", h) is True


# ---- hash_tagged_read --------------------------------------------------- #


class TestHashTaggedRead:
    def test_basic_file(self, tmp_path: pytest.TempPathFactory) -> None:
        src = tmp_path / "sample.py"
        src.write_text("def hello():\n    return 42\n", encoding="utf-8")

        result = hash_tagged_read(str(src))
        lines = result.splitlines()

        assert len(lines) == 2
        # Each line must match the pattern  N#HH| content
        for line in lines:
            assert "#" in line
            assert "|" in line

        # Verify first line hash
        h1 = _expected_hash("def hello():\n")
        assert lines[0] == f"1#{h1}| def hello():"

    def test_empty_file(self, tmp_path: pytest.TempPathFactory) -> None:
        src = tmp_path / "empty.py"
        src.write_text("", encoding="utf-8")
        result = hash_tagged_read(str(src))
        assert result == ""

    def test_preserves_indentation_in_output(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        src = tmp_path / "indented.py"
        src.write_text("    x = 1\n", encoding="utf-8")
        result = hash_tagged_read(str(src))
        assert "|     x = 1" in result


# ---- parse_hashline_edits ------------------------------------------------ #


class TestParseHashlineEdits:
    def test_single_block(self) -> None:
        llm_output = textwrap.dedent("""\
            Here is the fix:
            --- EDIT: src/app.py ---
            1#a7| def hello_world():
            3#b2| return "fixed"
            --- END EDIT ---
            Done!
        """)
        edits = parse_hashline_edits(llm_output)

        assert len(edits) == 2
        assert edits[0] == HashlineEdit(
            filepath="src/app.py",
            line_number=1,
            expected_hash="a7",
            new_content="def hello_world():",
        )
        assert edits[1].line_number == 3
        assert edits[1].new_content == 'return "fixed"'

    def test_multiple_blocks(self) -> None:
        llm_output = textwrap.dedent("""\
            --- EDIT: a.py ---
            1#ab| line one
            --- END EDIT ---
            --- EDIT: b.py ---
            2#cd| line two
            --- END EDIT ---
        """)
        edits = parse_hashline_edits(llm_output)
        assert len(edits) == 2
        assert edits[0].filepath == "a.py"
        assert edits[1].filepath == "b.py"

    def test_empty_input(self) -> None:
        assert parse_hashline_edits("") == []

    def test_ignores_lines_outside_blocks(self) -> None:
        llm_output = "1#ab| stray line\nsome text\n"
        assert parse_hashline_edits(llm_output) == []


# ---- apply_hashline_edits ------------------------------------------------ #


class TestApplyHashlineEdits:
    def _write_sample(self, workspace: str, relpath: str, content: str) -> str:
        full = os.path.join(workspace, relpath)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return relpath

    def test_happy_path(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        relpath = self._write_sample(ws, "hello.py", "def greet():\n    pass\n")

        # Compute the real hash for line 1
        h = _expected_hash("def greet():\n")
        edits = [
            HashlineEdit(
                filepath=relpath,
                line_number=1,
                expected_hash=h,
                new_content="def greet(name):",
            )
        ]

        result = apply_hashline_edits(edits, ws)

        assert result.applied == 1
        assert result.mismatches == 0
        assert relpath in result.files_modified
        assert result.errors == []

        # Verify file contents changed
        with open(os.path.join(ws, relpath), encoding="utf-8") as f:
            lines = f.readlines()
        assert lines[0] == "def greet(name):\n"
        assert lines[1] == "    pass\n"  # untouched

    def test_hash_mismatch(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        relpath = self._write_sample(ws, "hello.py", "def greet():\n    pass\n")

        edits = [
            HashlineEdit(
                filepath=relpath,
                line_number=1,
                expected_hash="zz",  # wrong hash
                new_content="def greet(name):",
            )
        ]

        result = apply_hashline_edits(edits, ws)

        assert result.applied == 0
        assert result.mismatches == 1
        assert result.files_modified == []
        assert len(result.errors) == 1
        assert "hash mismatch" in result.errors[0]

    def test_line_out_of_range(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        relpath = self._write_sample(ws, "small.py", "one\n")

        edits = [
            HashlineEdit(
                filepath=relpath,
                line_number=99,
                expected_hash="ab",
                new_content="nope",
            )
        ]

        result = apply_hashline_edits(edits, ws)
        assert result.mismatches == 1
        assert "out of range" in result.errors[0]

    def test_file_not_found(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        edits = [
            HashlineEdit(
                filepath="nonexistent.py",
                line_number=1,
                expected_hash="ab",
                new_content="nope",
            )
        ]

        result = apply_hashline_edits(edits, ws)
        assert result.applied == 0
        assert "File not found" in result.errors[0]

    def test_multiple_edits_same_file(
        self, tmp_path: pytest.TempPathFactory
    ) -> None:
        ws = str(tmp_path)
        content = "aaa\nbbb\nccc\n"
        relpath = self._write_sample(ws, "multi.py", content)

        h1 = _expected_hash("aaa\n")
        h3 = _expected_hash("ccc\n")
        edits = [
            HashlineEdit(relpath, 1, h1, "AAA"),
            HashlineEdit(relpath, 3, h3, "CCC"),
        ]

        result = apply_hashline_edits(edits, ws)
        assert result.applied == 2
        assert result.mismatches == 0

        with open(os.path.join(ws, relpath), encoding="utf-8") as f:
            lines = f.readlines()
        assert lines[0] == "AAA\n"
        assert lines[1] == "bbb\n"
        assert lines[2] == "CCC\n"


# ---- path traversal ------------------------------------------------------ #


class TestPathTraversal:
    def test_rejects_dotdot(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        edits = [
            HashlineEdit(
                filepath="../etc/passwd",
                line_number=1,
                expected_hash="ab",
                new_content="root:x:0:0",
            )
        ]

        result = apply_hashline_edits(edits, ws)
        assert result.applied == 0
        assert any(
            "unsafe path" in e.lower() or "rejected" in e.lower()
            for e in result.errors
        )

    def test_rejects_absolute_path(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        edits = [
            HashlineEdit(
                filepath="/etc/passwd",
                line_number=1,
                expected_hash="ab",
                new_content="root:x:0:0",
            )
        ]

        result = apply_hashline_edits(edits, ws)
        assert result.applied == 0
        assert len(result.errors) == 1

    def test_allows_subdirectory(self, tmp_path: pytest.TempPathFactory) -> None:
        ws = str(tmp_path)
        sub = os.path.join(ws, "src")
        os.makedirs(sub)
        fpath = os.path.join(sub, "ok.py")
        with open(fpath, "w", encoding="utf-8") as f:
            f.write("x = 1\n")

        h = _expected_hash("x = 1\n")
        edits = [
            HashlineEdit(
                filepath="src/ok.py",
                line_number=1,
                expected_hash=h,
                new_content="x = 2",
            )
        ]

        result = apply_hashline_edits(edits, ws)
        assert result.applied == 1
        assert result.errors == []
