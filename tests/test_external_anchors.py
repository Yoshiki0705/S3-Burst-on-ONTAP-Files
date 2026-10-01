"""The citation pattern of the external-anchor check, in the forms citations actually take here.

The check compares each citation's path against the sibling's anchor contract, so a path read with
one stray character attached is reported as an untracked document. That happened with the first
citation held in a JSON string: the closing quote and comma were read as part of the path.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import check_external_anchors as ea

URL = ea.REPO_URL + "docs/ja/domains/performance/notes/example-note.md"


def test_a_markdown_link_ends_at_the_closing_parenthesis() -> None:
    match = ea.CITATION.search(f"see [the note]({URL}#a-heading) for details")
    assert match
    assert match.group(1) == "docs/ja/domains/performance/notes/example-note.md"
    assert match.group(2) == "a-heading"


def test_a_url_in_a_json_string_ends_at_the_quote() -> None:
    match = ea.CITATION.search(f'  "reference_requirements": ["{URL}",\n')
    assert match
    assert match.group(1) == "docs/ja/domains/performance/notes/example-note.md"
    assert match.group(2) is None


def test_an_anchor_in_a_json_string_ends_at_the_quote() -> None:
    match = ea.CITATION.search(f'"{URL}#a-heading",')
    assert match
    assert match.group(2) == "a-heading"


def test_a_bare_url_in_prose_ends_at_whitespace() -> None:
    match = ea.CITATION.search(f"Read {URL} first.")
    assert match
    assert match.group(1) == "docs/ja/domains/performance/notes/example-note.md"


# --- which side of the sibling checkout the contract is read from ------------------------------

PUBLISHED = "docs/ja/published-note.md\n"
BRANCH_ONLY = "docs/ja/older-note.md\n"


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=t",
            "-c",
            # Empty on purpose: a commit needs an identity, and anything address-shaped would be
            # caught by the secret scanner, as an example address was on the first attempt.
            "user.email=",
            *args,
        ],
        check=True,
        capture_output=True,
    )


def _sibling(tmp_path: Path, *, with_origin_main: bool) -> Path:
    """A sibling clone whose working tree holds a different contract from its origin/main."""
    repo = tmp_path / "sibling"
    contract_path = repo / ea.CONTRACT
    contract_path.parent.mkdir(parents=True)
    _git(tmp_path, "init", "-q", str(repo))
    contract_path.write_text(PUBLISHED, encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-q", "-m", "published contract")
    if with_origin_main:
        _git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    # A feature branch checked out in the clone: its contract predates the published one.
    contract_path.write_text(BRANCH_ONLY, encoding="utf-8")
    return repo


def test_the_contract_is_read_from_origin_main_not_the_working_tree(tmp_path) -> None:
    published, source = ea.contract(_sibling(tmp_path, with_origin_main=True))
    assert "docs/ja/published-note.md" in published
    assert "docs/ja/older-note.md" not in published
    assert source.endswith("at origin/main")


def test_without_origin_main_it_falls_back_to_the_working_tree_and_says_so(
    tmp_path,
) -> None:
    published, source = ea.contract(_sibling(tmp_path, with_origin_main=False))
    assert "docs/ja/older-note.md" in published
    assert "working tree" in source and "unreadable" in source
