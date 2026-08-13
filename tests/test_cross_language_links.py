"""Tests for the check that links out of English into Japanese say so.

The check exists because the repository is deliberately asymmetric, so the interesting cases are
the ones where a link legitimately leaves English. Those are asserted here alongside the failures,
because a check that rejects the switcher block or a file-listing table would be turned off within
a day and then catch nothing.
"""

from __future__ import annotations

import check_cross_language_links as xlang
import pytest


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(xlang, "ROOT", tmp_path)
    return tmp_path


def write(root, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def run(capsys) -> tuple[int, str]:
    code = xlang.main()
    captured = capsys.readouterr()
    return code, captured.out + captured.err


# --- the failure it was built for ---------------------------------------------------------------


def test_an_english_label_pointing_at_japanese_fails(repo, capsys) -> None:
    write(repo, "docs/ja/architecture.md", "# 構成\n")
    write(repo, "docs/en/README.md", "See [Architecture](../ja/architecture.md).\n")
    code, output = run(capsys)
    assert code == 1
    assert "docs/en/README.md:1" in output
    assert "missing marker" in output


def test_the_marker_clears_it(repo, capsys) -> None:
    write(repo, "docs/ja/architecture.md", "# 構成\n")
    write(
        repo,
        "docs/en/README.md",
        "See [Architecture](../ja/architecture.md) (Japanese).\n",
    )
    code, output = run(capsys)
    assert code == 0
    assert "1 link(s) into Japanese are marked" in output


@pytest.mark.parametrize(
    "marker", ["(JA)", "(ja)", "(Japanese version)", "(in Japanese)", "(Japanese only)"]
)
def test_a_second_spelling_of_the_marker_is_rejected(repo, capsys, marker) -> None:
    """Two spellings of one convention is how the convention stops being checkable."""
    write(repo, "docs/ja/architecture.md", "# 構成\n")
    write(
        repo,
        "docs/en/README.md",
        f"See [Architecture](../ja/architecture.md) {marker}.\n",
    )
    code, output = run(capsys)
    assert code == 1
    assert "wrong spelling" in output


# --- links that are allowed to leave English ----------------------------------------------------


def test_the_switcher_block_is_self_marking(repo, capsys) -> None:
    """`[日本語](...)` cannot mislead anyone about where it goes."""
    write(repo, "docs/ja/deployment/guide.md", "# 手順\n")
    write(
        repo,
        "docs/en/deployment/guide.md",
        "🌐 [日本語](../../ja/deployment/guide.md) | [English](guide.md)\n",
    )
    code, _ = run(capsys)
    assert code == 0


def test_a_link_whose_text_is_the_path_is_self_marking(repo, capsys) -> None:
    write(repo, "docs/ja/verification-status.md", "# 検証状況\n")
    write(
        repo,
        "docs/en/README.md",
        "| [`docs/ja/verification-status.md`](../ja/verification-status.md) | Stage |\n",
    )
    code, _ = run(capsys)
    assert code == 0


def test_a_marker_in_the_next_table_cell_counts(repo, capsys) -> None:
    """The reader takes in the row before clicking, so the row is the unit."""
    write(repo, "docs/ja/poc-checklist.md", "# PoC\n")
    write(
        repo,
        "docs/en/deployment/guide.md",
        "| [PoC checklist](../../ja/poc-checklist.md) | The order to confirm things in (Japanese) |\n",
    )
    code, _ = run(capsys)
    assert code == 0


def test_links_that_stay_in_english_are_not_examined(repo, capsys) -> None:
    write(repo, "docs/en/README.md", "See [Deploy](deployment/guide.md).\n")
    write(repo, "docs/en/deployment/guide.md", "# Guide\n")
    code, output = run(capsys)
    assert code == 0
    assert "0 link(s) into Japanese are marked" in output


# --- the marker that outlived its link ----------------------------------------------------------


def test_a_marker_on_a_link_that_stays_in_english_fails(repo, capsys) -> None:
    """What a promotion leaves behind: the target was retargeted to the English sibling and the
    label was not. Every other check passes — the target resolves, the file is English, the marker is
    spelled correctly — and the line now tells the reader the opposite of the truth."""
    write(repo, "docs/en/README.md", "See [Deploy](deployment/guide.md) (Japanese).\n")
    write(repo, "docs/en/deployment/guide.md", "# Guide\n")
    code, output = run(capsys)
    assert code == 1
    assert "stale marker" in output
    assert "docs/en/README.md:1" in output


def test_a_marker_on_a_link_outside_the_language_trees_is_left_alone(
    repo, capsys
) -> None:
    """`CONTRIBUTING.md` and `docs/i18n-terms.md` are Japanese but are not tiered, so the marker on a
    link to one of them is correct. Judging them by their contents would have failed the generated
    switcher, whose home link points at the Japanese hub."""
    write(repo, "CONTRIBUTING.md", "# 執筆規約\n")
    write(
        repo,
        "docs/en/README.md",
        "Conventions are in [CONTRIBUTING.md](../../CONTRIBUTING.md) (Japanese).\n",
    )
    code, _ = run(capsys)
    assert code == 0


def test_a_marker_with_no_link_at_all_is_left_alone(repo, capsys) -> None:
    """Prose can mention the word without it being a label on anything."""
    write(repo, "docs/en/README.md", "The upstream discussion was (Japanese).\n")
    code, _ = run(capsys)
    assert code == 0


def test_external_and_anchor_targets_are_ignored(repo, capsys) -> None:
    write(
        repo,
        "docs/en/README.md",
        "[Docs](https://example.com/ja/x.md) and [here](#section).\n",
    )
    code, _ = run(capsys)
    assert code == 0


# --- the ways a lenient reading would let a defect through --------------------------------------


def test_one_marker_does_not_cover_two_links_on_a_line(repo, capsys) -> None:
    write(repo, "docs/ja/a.md", "# あ\n")
    write(repo, "docs/ja/b.md", "# い\n")
    write(
        repo,
        "docs/en/README.md",
        "See [A](../ja/a.md) (Japanese) and [B](../ja/b.md).\n",
    )
    code, output = run(capsys)
    assert code == 1
    assert "[B](../ja/b.md)" in output


def test_a_link_inside_a_fenced_block_is_not_a_link(repo, capsys) -> None:
    write(repo, "docs/ja/architecture.md", "# 構成\n")
    write(
        repo,
        "docs/en/README.md",
        "```markdown\n[Architecture](../ja/architecture.md)\n```\n",
    )
    code, _ = run(capsys)
    assert code == 0


def test_an_image_is_not_a_link(repo, capsys) -> None:
    write(repo, "docs/ja/diagram.md", "# 図\n")
    write(repo, "docs/en/README.md", "![Diagram](../ja/diagram.md)\n")
    code, _ = run(capsys)
    assert code == 0


def test_a_missing_english_tree_is_not_a_silent_pass(repo, capsys) -> None:
    """No English documents means nothing to check; the summary has to say so rather than imply
    coverage."""
    code, output = run(capsys)
    assert code == 0
    assert "0 English file(s) checked" in output
