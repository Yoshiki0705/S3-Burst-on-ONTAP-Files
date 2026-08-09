"""The count checker, verified against the ways it can fail quietly.

Three of these tests exist because of a specific defect in the sibling repository
`fsxn-s3ap-serverless-patterns`. Its drift checker was correct, but `solutions/README.md` was not in
the list of files it scanned, so that file drifted to a pattern count disk did not support and the
check stayed green. A checker's blind spot is invisible from inside the checker, so the glob list is
asserted here rather than reviewed.
"""

from __future__ import annotations

import check_derived_counts as counts
import pytest


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A throwaway repository root the checker will read instead of the real one."""
    monkeypatch.setattr(counts, "ROOT", tmp_path)
    return tmp_path


def add_pattern(root, axis: str, slug: str) -> None:
    directory = root / "patterns" / axis / slug
    directory.mkdir(parents=True)
    (directory / "template.yaml").write_text("Resources: {}\n", encoding="utf-8")


def write_readme(root, body: str) -> None:
    (root / "README.md").write_text(body, encoding="utf-8")


# --- the glob list ------------------------------------------------------------------------------


def test_the_two_files_most_likely_to_hold_a_count_are_scanned() -> None:
    for name in ("README.md", "AGENTS.md"):
        assert name in counts.COUNT_GLOBS, (
            f"{name} is not scanned for count claims. This is the exact gap that let a sibling "
            f"repository's README drift away from disk while its checker reported success."
        )


def test_every_claim_names_a_source_and_a_counter() -> None:
    for claim in counts.COUNT_CLAIMS:
        assert claim["source"], claim["name"]
        assert callable(claim["count"]), claim["name"]


# --- claim parsing -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "line",
    [
        "3 つの収集パターン",
        "収集パターン（3）",
        "収集パターン: 3",
        "3 collect patterns",
        "Collect patterns: 3",
        "**3** 収集パターン",
    ],
)
def test_a_count_is_recognised_in_every_order_prose_uses(line: str) -> None:
    claim = next(c for c in counts.COUNT_CLAIMS if c["name"] == "collect-patterns")
    match = claim["regex"].search(line)
    assert match is not None, line
    assert counts.claimed_numbers(match) == "3"


# --- drift detection ---------------------------------------------------------------------------


def test_a_matching_count_passes(repo) -> None:
    add_pattern(repo, "collect", "s3ap-ingest")
    add_pattern(repo, "collect", "s3ap-batch")
    write_readme(repo, "This repository ships 2 collect patterns.\n")
    assert counts.check() == []


def test_a_stale_count_is_reported(repo) -> None:
    add_pattern(repo, "collect", "s3ap-ingest")
    write_readme(repo, "This repository ships 2 collect patterns.\n")
    findings = counts.check()
    assert len(findings) == 1
    assert "states 2" in findings[0]
    assert "counts 1" in findings[0]


def test_a_zero_count_is_reported_as_a_broken_reader(repo) -> None:
    """If prose claims a number and the counter returns zero, the glob has stopped matching.

    Renaming `patterns/collect` would produce exactly this, and reading it as "no patterns yet"
    is how a moved directory goes unnoticed.
    """
    write_readme(repo, "This repository ships 4 collect patterns.\n")
    findings = counts.check()
    assert len(findings) == 1
    assert "counted zero" in findings[0]


def test_prose_with_no_count_is_not_a_claim(repo) -> None:
    add_pattern(repo, "collect", "s3ap-ingest")
    write_readme(repo, "The collect patterns live under patterns/collect/.\n")
    assert counts.check() == []


def test_each_axis_is_counted_separately(repo) -> None:
    add_pattern(repo, "collect", "one")
    add_pattern(repo, "serve", "two")
    add_pattern(repo, "serve", "three")
    write_readme(repo, "1 collect patterns and 2 serve patterns.\n")
    assert counts.check() == []


def test_the_total_spans_every_axis(repo) -> None:
    add_pattern(repo, "collect", "one")
    add_pattern(repo, "serve", "two")
    add_pattern(repo, "pipelines", "three")
    write_readme(repo, "3 patterns in total.\n")
    assert counts.check() == []


def test_a_directory_without_a_template_is_not_a_pattern(repo) -> None:
    """The unit is a deployable template, not a directory that happens to exist."""
    (repo / "patterns" / "collect" / "draft").mkdir(parents=True)
    write_readme(repo, "1 collect patterns.\n")
    findings = counts.check()
    assert len(findings) == 1
    assert "counted zero" in findings[0]


# --- exemptions --------------------------------------------------------------------------------


def test_a_line_exemption_is_honoured(repo) -> None:
    write_readme(repo, "9 collect patterns <!-- counts-exempt-line -->\n")
    assert counts.check() == []


def test_a_file_exemption_is_honoured(repo) -> None:
    write_readme(repo, "<!-- counts-exempt-file -->\n\n9 collect patterns\n")
    assert counts.check() == []
