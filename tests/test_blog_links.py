"""Tests for the blog-draft GitHub link check.

Written against fixtures rather than the real drafts, for the reason `test_blog_draft_sync.py`
records: `.private/` is gitignored, so a clone running these tests does not have it, and a test that
only passes on one machine is not a guard.

**The failing cases come first, and two of them are mistakes made while writing the checker rather
than hypotheticals.** Comparing a sibling's path against this checkout reported four correct links as
broken; re-deriving the anchor slug instead of importing it reported two live anchors as misses. Both
would have been caught here.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location(
    "check_blog_links", ROOT / "tools" / "check_blog_links.py"
)
assert SPEC and SPEC.loader
bl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bl)

# The owner is a placeholder rather than a literal. `test_owner_repo_links.py` scans tracked
# source lines for this owner's URLs and rejects repository names it does not know, and a
# template reading `{repo}` is not a repository name. Writing the owner in literally made that
# test fail -- in CI rather than locally, because it walks *tracked* files and this one was still
# unstaged when the gate ran here.
URL = "https://github.com/{owner}/{repo}/blob/{ref}/{path}{anchor}"


def draft(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "blog-unpublished-fixture.md"
    path.write_text(body, encoding="utf-8")
    return path


def link(
    repo="s3-burst-on-ontap-files", ref="main", path="docs/ja/x.md", anchor=""
) -> str:
    return f"[see]({URL.format(owner=bl.OWNER, repo=repo, ref=ref, path=path, anchor=anchor)})"


def test_a_link_to_a_file_that_does_not_exist_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    path = draft(tmp_path, link(path="docs/ja/gone.md"))
    seen, problems, unchecked = bl.check(path)
    assert seen == 1
    assert len(problems) == 1
    assert "no such file" in problems[0]
    assert not unchecked


def test_an_anchor_no_heading_makes_fails(tmp_path, monkeypatch):
    """The failure mode worth most: the page resolves and the reader is never told."""
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    (tmp_path / "docs" / "ja").mkdir(parents=True)
    (tmp_path / "docs" / "ja" / "x.md").write_text(
        "## 実在する見出し\n", encoding="utf-8"
    )
    path = draft(tmp_path, link(anchor="#消えた見出し"))
    _, problems, _ = bl.check(path)
    assert len(problems) == 1
    assert "no heading makes that anchor" in problems[0]


def test_the_local_directory_name_is_not_a_repository_name(tmp_path, monkeypatch):
    """`fsxn-s3ap-serverless-patterns` is a directory here and a 404 on GitHub."""
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    path = draft(tmp_path, link(repo="fsxn-s3ap-serverless-patterns"))
    _, problems, _ = bl.check(path)
    assert len(problems) == 1
    assert "not a published repository" in problems[0]


def test_a_sibling_path_is_resolved_against_the_sibling(tmp_path, monkeypatch):
    """The mistake that reported four correct links as broken.

    The same relative path exists in neither this checkout nor a made-up one; what decides the root
    is the repository name in the URL. Resolving it here would be the bug.
    """
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    sibling = tmp_path / "sibling"
    (sibling / "solutions").mkdir(parents=True)
    (sibling / "solutions" / "record.md").write_text("# Record\n", encoding="utf-8")
    monkeypatch.setattr(bl, "checkout", lambda repo: sibling)
    path = draft(
        tmp_path,
        link(
            repo="FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns",
            path="solutions/record.md",
        ),
    )
    _, problems, unchecked = bl.check(path)
    assert not problems
    assert not unchecked


def test_a_missing_sibling_checkout_is_reported_not_passed(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    monkeypatch.setattr(bl, "checkout", lambda repo: None)
    path = draft(
        tmp_path,
        link(
            repo="FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns",
            path="solutions/record.md",
        ),
    )
    _, problems, unchecked = bl.check(path)
    assert not problems
    assert len(unchecked) == 1
    assert "no checkout of" in unchecked[0]


def test_a_pinned_ref_is_reported_rather_than_read_from_the_tree(tmp_path, monkeypatch):
    """A draft that pins a SHA is doing what its own header asks. It is not resolvable here."""
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    (tmp_path / "docs" / "ja").mkdir(parents=True)
    (tmp_path / "docs" / "ja" / "x.md").write_text("## h\n", encoding="utf-8")
    path = draft(tmp_path, link(ref="0123456789abcdef"))
    _, problems, unchecked = bl.check(path)
    assert not problems
    assert len(unchecked) == 1
    assert "pinned to" in unchecked[0]


def test_case_differences_in_the_repository_name_are_accepted(tmp_path, monkeypatch):
    """Both spellings are in use; GitHub resolves either."""
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    (tmp_path / "docs" / "ja").mkdir(parents=True)
    (tmp_path / "docs" / "ja" / "x.md").write_text("## h\n", encoding="utf-8")
    for spelling in ("s3-burst-on-ontap-files", "S3-Burst-on-ONTAP-Files"):
        path = draft(tmp_path, link(repo=spelling))
        _, problems, _ = bl.check(path)
        assert not problems, spelling


def test_drafts_with_no_links_at_all_fail(tmp_path, monkeypatch):
    """A scan that finds nothing is this checker failing to read, not an absence of links."""
    monkeypatch.setattr(bl, "DRAFT_DIR", tmp_path)
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    (tmp_path / "blog-unpublished-empty.md").write_text(
        "no links here\n", encoding="utf-8"
    )
    assert bl.main() == 1


def test_a_missing_private_directory_skips(tmp_path, monkeypatch):
    monkeypatch.setattr(bl, "DRAFT_DIR", tmp_path / "absent")
    assert bl.main() == 0


def test_the_anchor_rule_is_imported_rather_than_reimplemented(tmp_path, monkeypatch):
    """Whitespace runs are not collapsed, so `（1 / 4 / 8 台）` becomes `1--4--8-台`.

    A second implementation of this rule reported two live anchors as misses.
    """
    monkeypatch.setattr(bl, "ROOT", tmp_path)
    (tmp_path / "docs" / "ja").mkdir(parents=True)
    (tmp_path / "docs" / "ja" / "x.md").write_text(
        "## SMB の台数試験（1 / 4 / 8 台）\n", encoding="utf-8"
    )
    path = draft(tmp_path, link(anchor="#smb-の台数試験1--4--8-台"))
    _, problems, _ = bl.check(path)
    assert not problems
