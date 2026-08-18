"""The pattern-status checker, exercised through the ways it could pass while checking nothing.

Two of these matter more than the rest. `test_an_undefined_word_is_rejected` is the check's whole
purpose: `verified` is a claim stage, not a status, and using it on a template that only ever passed
`cfn-lint` tells the reader the behaviour was confirmed. `test_a_broken_definition_table_fails`
covers the failure mode this repository has been bitten by elsewhere -- a checker whose input
disappears reports success, and that is indistinguishable from a real pass.
"""

from __future__ import annotations

import check_pattern_status as status
import pytest

DEFINITION_TABLE = """# Pattern template

| Status | Meaning | Evidence |
|---|---|---|
| `code-only` | Written, not linted | - |
| `syntax-validated` | Linters pass | - |
| `deployed` | Deployed, behaviour unconfirmed | When and where |
| `functionally-tested` | Behaviour confirmed | Link to the record |
| `blocked` | Stopped by something external | What is stopping it |
"""


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway tree with a definition table and one pattern."""
    monkeypatch.setattr(status, "ROOT", tmp_path)
    monkeypatch.setattr(
        status, "TEMPLATE_README", tmp_path / "patterns" / "_template" / "README.md"
    )
    (tmp_path / "patterns" / "_template").mkdir(parents=True)
    status.TEMPLATE_README.write_text(DEFINITION_TABLE, encoding="utf-8")
    return tmp_path


def write_pattern(repo, body: str, slug: str = "example") -> None:
    directory = repo / "patterns" / "collect" / slug
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "README.md").write_text(body, encoding="utf-8")


def test_the_words_are_read_from_the_definition_table(repo) -> None:
    assert status.defined_words() == {
        "code-only",
        "syntax-validated",
        "deployed",
        "functionally-tested",
        "blocked",
    }


def test_a_broken_definition_table_fails(repo) -> None:
    """No words found means the checker cannot verify anything, so it must not report success."""
    status.TEMPLATE_README.write_text(
        "# Pattern template\n\nNo table here.\n", encoding="utf-8"
    )
    with pytest.raises(SystemExit):
        status.defined_words()


def test_a_defined_word_passes(repo) -> None:
    write_pattern(
        repo, "# Example\n\n> **Status: `deployed`** - deployed in ap-northeast-1.\n"
    )
    assert status.main() == 0


def test_the_japanese_form_passes(repo) -> None:
    """The skeleton writes the line in Japanese, so both spellings have to be accepted."""
    write_pattern(repo, "# Example\n\n> 状態: `code-only` - 書いただけです。\n")
    assert status.main() == 0


def test_an_undefined_word_is_rejected(repo, capsys) -> None:
    write_pattern(
        repo,
        "# Example\n\n> **Status: `verified`** - looks plausible, is a claim stage.\n",
    )
    assert status.main() == 1
    assert "not defined" in capsys.readouterr().err


def test_a_missing_status_line_is_rejected(repo, capsys) -> None:
    write_pattern(repo, "# Example\n\nStraight into the prose.\n")
    assert status.main() == 1
    assert "no status line" in capsys.readouterr().err


def test_a_status_word_further_down_does_not_count(repo, capsys) -> None:
    """Only the opening lines are a claim; the same word in later prose is discussion."""
    body = "# Example\n\nStraight into the prose.\n" + "\n" * 12
    body += "> **Status: `deployed`** - too late to be the opening claim.\n"
    write_pattern(repo, body)
    assert status.main() == 1
    assert "no status line" in capsys.readouterr().err


def test_no_pattern_readme_at_all_fails(repo, capsys) -> None:
    """An empty glob is the other way this passes vacuously."""
    assert status.main() == 1
    assert "no README with a status line" in capsys.readouterr().err


def test_every_pattern_is_checked_not_just_the_first(repo, capsys) -> None:
    write_pattern(repo, "# One\n\n> **Status: `deployed`** - fine.\n", slug="one")
    write_pattern(repo, "# Two\n\n> **Status: `wip`** - not a word.\n", slug="two")
    assert status.main() == 1
    assert "two/README.md" in capsys.readouterr().err
