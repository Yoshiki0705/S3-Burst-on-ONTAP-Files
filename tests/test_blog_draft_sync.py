"""Tests for the blog draft drift check.

Written against fixtures rather than the real drafts. The drafts live under `.private/`, which is
gitignored, so a clone that runs these tests does not have them -- and a test that only passes on one
machine is not a guard. What is exercised here is the decision the tool makes, in all four states it
can be in, with the failing cases first: the worst way for this check to break is to report success
while a draft sits ahead of its published post, which is the state it exists to catch.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_blog_draft_sync", ROOT / "tools" / "check_blog_draft_sync.py"
)
assert SPEC and SPEC.loader
bd = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bd)

BODY = "## Introduction\n\nSome published prose.\n"


def draft(tmp_path: Path, header: str, body: str = BODY) -> Path:
    path = tmp_path / "blog-draft-xx.md"
    path.write_text(f"<!-- {header} -->\n\n{body}", encoding="utf-8")
    return path


def test_a_draft_ahead_of_its_published_post_fails(tmp_path, monkeypatch):
    """The case that actually happened: content added here and never published."""
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    stale = bd.digest("## Introduction\n\nThe prose as published.\n")
    path = draft(tmp_path, f"published-body-sha256: {stale}")
    problems = bd.check(path)
    assert len(problems) == 1
    assert "changed since it was last published" in problems[0]
    assert stale in problems[0] and bd.digest(BODY) in problems[0]


def test_a_missing_marker_fails_and_names_the_digest_to_record(tmp_path, monkeypatch):
    """Absent bookkeeping is the same risk as wrong bookkeeping, so it is not tolerated."""
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    path = draft(tmp_path, "no marker in this header")
    problems = bd.check(path)
    assert len(problems) == 1
    assert "no `published-body-sha256:`" in problems[0]
    # The message has to carry the value, or the fix needs a second tool.
    assert bd.digest(BODY) in problems[0]


def test_a_draft_with_no_heading_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    path = tmp_path / "blog-draft-xx.md"
    path.write_text(
        "<!-- published-body-sha256: " + "0" * 16 + " -->\nprose only\n",
        encoding="utf-8",
    )
    problems = bd.check(path)
    assert len(problems) == 1
    assert "no Markdown heading" in problems[0]


def test_a_synced_draft_passes(tmp_path, monkeypatch):
    """The other half of the guard: it must not fire on the state it is meant to allow."""
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    path = draft(tmp_path, f"published-body-sha256: {bd.digest(BODY)}")
    assert bd.check(path) == []


def test_the_header_is_excluded_from_the_digest(tmp_path, monkeypatch):
    """Local bookkeeping never reaches the published post, so it must not change the digest."""
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    recorded = bd.digest(BODY)
    a = draft(tmp_path, f"synced 2026-01-01. published-body-sha256: {recorded}")
    assert bd.check(a) == []
    b = tmp_path / "blog-draft-yy.md"
    b.write_text(
        f"<!-- a much longer header, rewritten again, url: https://example.com/post\n"
        f"published-body-sha256: {recorded} -->\n\n{BODY}",
        encoding="utf-8",
    )
    assert bd.check(b) == []


@pytest.mark.parametrize("body", [BODY, BODY + "\n\n", "\n" + BODY])
def test_surrounding_blank_lines_do_not_count_as_drift(tmp_path, monkeypatch, body):
    """An editor that adds or trims trailing newlines must not be reported as unpublished content."""
    monkeypatch.setattr(bd, "ROOT", tmp_path)
    path = draft(tmp_path, f"published-body-sha256: {bd.digest(BODY)}", body=body)
    assert bd.check(path) == []


def test_a_clone_without_the_private_directory_is_skipped(tmp_path, monkeypatch):
    """The drafts are not committed, so their absence is normal and must not fail the gate."""
    monkeypatch.setattr(bd, "DRAFT_DIR", tmp_path / "absent")
    assert bd.main() == 0
