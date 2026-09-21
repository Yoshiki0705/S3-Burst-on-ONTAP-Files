"""Tests for the blog draft public-range check.

Written against fixtures rather than the real drafts, for the same reason as
test_blog_draft_sync.py: the drafts live under `.private/`, which is gitignored, so a clone that
runs these tests does not have them.

A persona review (round 4) asked for this check's own validation samples -- exercised once by hand
and then thrown away -- to become a permanent regression fixture instead. These tests are that
fixture: the three violation patterns (an unlabelled HTML comment, strikethrough, an addendum
heading), the `allow:` exemption that must not trip the HTML-comment check, the two ways a file
can declare its range (`PUBLIC RANGE START` or `PUBLIC RANGE: not applicable`), the automatic range
for an already-published `blog-draft-*.md`, and the case this check exists to make impossible now:
a draft with no declaration at all, silently treated as clean.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_public_range", ROOT / "tools" / "check_public_range.py"
)
assert SPEC and SPEC.loader
pr = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pr)


def unpublished(
    tmp_path: Path, body: str, name: str = "blog-unpublished-xx-ja.md"
) -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


def published(tmp_path: Path, body: str, name: str = "blog-draft-xx.md") -> Path:
    path = tmp_path / name
    path.write_text(body, encoding="utf-8")
    return path


# -- Undeclared range: the gap round 4 asked to close --------------------------------------------


def test_an_unpublished_draft_with_no_declaration_fails(tmp_path, monkeypatch):
    """The state this check exists to make impossible: silently treated as clean."""
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path, "# Title\n\n## Body\n\nProse with no range declared.\n"
    )
    problems = pr.check(path, is_published=False)
    assert len(problems) == 1
    assert "no public range declared" in problems[0]


def test_an_unpublished_draft_opted_out_with_a_reason_passes(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "<!-- PUBLIC RANGE: not applicable. Superseded, never the published source. -->\n\n"
        "# Title\n\n## Body\n\nAnything here is out of scope.\n",
    )
    assert pr.check(path, is_published=False) == []


def test_an_unpublished_draft_with_public_range_start_is_checked_from_the_next_line(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\nProduction note with a stray ~~strike~~ here, above the marker.\n\n"
        "## Body\n\n<!-- PUBLIC RANGE START -->\n\nClean prose below the marker.\n",
    )
    assert pr.check(path, is_published=False) == []


# -- Published drafts get their range for free, from the same boundary as blog-sync --------------


def test_a_published_draft_is_checked_from_its_first_heading_with_no_declaration_needed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = published(
        tmp_path, "<!-- production note -->\n\n## Introduction\n\nClean prose.\n"
    )
    assert pr.check(path, is_published=True) == []


def test_a_published_draft_with_no_heading_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = published(tmp_path, "<!-- production note only, no heading -->\n")
    problems = pr.check(path, is_published=True)
    assert len(problems) == 1
    assert "no Markdown heading" in problems[0]


# -- The three violation patterns, inside a declared range ----------------------------------------


def test_an_unlabelled_html_comment_inside_the_range_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\n"
        "Prose. <!-- a production note left behind by mistake -->\n",
    )
    problems = pr.check(path, is_published=False)
    assert len(problems) == 1
    assert "HTML comment starts inside the public range" in problems[0]


def test_the_allow_naming_marker_does_not_trip_the_html_comment_check(
    tmp_path, monkeypatch
):
    """This repository's own inline lint-exemption marker ships inside published prose."""
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\n"
        "| Node CPU | CloudWatch | <!-- allow:naming the namespace name itself -->\n",
    )
    assert pr.check(path, is_published=False) == []


def test_strikethrough_inside_the_range_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\n"
        "The old figure was ~~500 MB/s~~ 650 MB/s.\n",
    )
    problems = pr.check(path, is_published=False)
    assert len(problems) == 1
    assert "strikethrough inside the public range" in problems[0]


def test_an_addendum_heading_inside_the_range_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\nProse.\n\n"
        "## 追記（2026-09-01）\n\nA production-log entry left inside the range.\n",
    )
    problems = pr.check(path, is_published=False)
    assert len(problems) == 1
    assert "addendum heading inside the public range" in problems[0]


def test_an_english_addendum_heading_is_also_caught(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\nProse.\n\n"
        "## Addendum 3\n\nA production-log entry left inside the range.\n",
    )
    problems = pr.check(path, is_published=False)
    assert len(problems) == 1
    assert "addendum heading inside the public range" in problems[0]


def test_all_three_patterns_are_reported_together(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    path = unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\n"
        "Prose. <!-- stray note --> ~~old~~ new.\n\n## 追記\n\nMore.\n",
    )
    problems = pr.check(path, is_published=False)
    assert len(problems) == 3


# -- The gate as a whole --------------------------------------------------------------------------


def test_a_clone_without_the_private_directory_is_skipped(tmp_path, monkeypatch):
    """The drafts are not committed, so their absence is normal and must not fail the gate."""
    monkeypatch.setattr(pr, "DRAFT_DIR", tmp_path / "absent")
    assert pr.main() == 0


def test_main_reports_every_finding_across_both_globs(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    monkeypatch.setattr(pr, "DRAFT_DIR", tmp_path)
    unpublished(tmp_path, "# Title\n\n## Body\n\nNo declaration at all.\n")
    published(tmp_path, "<!-- note -->\n\n## Introduction\n\n~~old~~ new.\n")
    assert pr.main() == 1


def test_main_passes_when_every_draft_has_declared_and_is_clean(tmp_path, monkeypatch):
    monkeypatch.setattr(pr, "ROOT", tmp_path)
    monkeypatch.setattr(pr, "DRAFT_DIR", tmp_path)
    unpublished(
        tmp_path,
        "# Title\n\n## Body\n\n<!-- PUBLIC RANGE START -->\n\nClean.\n",
        name="blog-unpublished-a-ja.md",
    )
    published(
        tmp_path, "<!-- note -->\n\n## Introduction\n\nClean.\n", name="blog-draft-b.md"
    )
    assert pr.main() == 0
