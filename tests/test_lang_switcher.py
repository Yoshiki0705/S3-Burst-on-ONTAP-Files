"""The generated switcher block, and the wrong-language link check.

The block format is pinned because it has to match the sibling repository `fsxn-adoption-playbook`
byte for byte: a reader moving between these repositories should meet the same control, and the
generator is the only thing that writes it. A hand-edited switcher is the defect this replaces, so
"the format changed and nobody noticed" has to be a test failure rather than a review question.
"""

from __future__ import annotations

import pytest
import sync_lang_switcher as switcher


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(switcher, "ROOT", tmp_path)
    return tmp_path


def write(root, relative: str, body: str = "# Title\n") -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --- path model ---------------------------------------------------------------------------------


def test_the_japanese_hub_is_the_repository_root_readme(repo) -> None:
    """GitHub renders the root README on the landing page, so that file *is* the Japanese hub."""
    assert switcher.path_for("ja", "README.md") == repo / "README.md"
    assert switcher.path_for("en", "README.md") == repo / "docs/en/README.md"


def test_only_the_two_languages_are_configured() -> None:
    assert switcher.LANGS == ("ja", "en")
    for lang in switcher.LANGS:
        assert lang in switcher.LANG_NAMES
        assert lang in switcher.HOME_LABEL


# --- block generation --------------------------------------------------------------------------


def test_the_hub_block_lists_both_languages_and_no_home_link(repo) -> None:
    write(repo, "README.md")
    write(repo, "docs/en/README.md")
    line, error = switcher.build_block("README.md")
    assert error is None
    assert line == "🌐 [日本語](README.md) | [English](docs/en/README.md)"


def test_the_english_hub_points_back_at_the_root_readme(repo) -> None:
    write(repo, "README.md")
    write(repo, "docs/en/README.md")
    line, error = switcher.build_block("docs/en/README.md")
    assert error is None
    assert line == "🌐 [日本語](../../README.md) | [English](README.md)"


def test_a_page_below_hub_level_gains_a_home_link(repo) -> None:
    write(repo, "README.md")
    write(repo, "docs/ja/design/architecture.md")
    write(repo, "docs/en/design/architecture.md")
    line, _ = switcher.build_block("docs/ja/design/architecture.md")
    assert line == (
        "🌐 [日本語](architecture.md) | [English](../../en/design/architecture.md)"
        " | [🏠 リポジトリトップ](../../../README.md)"
    )


def test_a_page_with_no_translation_gets_no_switcher(repo) -> None:
    """An eight-link switcher in a file with one translation is seven broken links."""
    write(repo, "README.md")
    write(repo, "docs/ja/design/architecture.md")
    line, error = switcher.build_block("docs/ja/design/architecture.md")
    assert line is None
    assert error is None


# --- marker contract ---------------------------------------------------------------------------


def test_a_missing_marker_pair_is_reported(repo) -> None:
    write(repo, "README.md")
    write(repo, "docs/en/README.md")
    problems = switcher.sync_file("README.md", write=False)
    assert len(problems) == 1
    assert "missing switcher markers" in problems[0]


def test_exactly_two_blocks_are_required(repo) -> None:
    """One after the H1 and one at the end. A single block means a reader who scrolls is stranded."""
    body = f"# Title\n\n{switcher.START}\n{switcher.END}\n\nbody\n"
    write(repo, "README.md", body)
    write(repo, "docs/en/README.md")
    problems = switcher.sync_file("README.md", write=False)
    assert any("expected 2" in problem for problem in problems)


def test_write_fills_both_blocks_and_verification_then_passes(repo) -> None:
    body = (
        f"# Title\n\n{switcher.START}\n{switcher.END}\n\nbody\n\n"
        f"{switcher.START}\n{switcher.END}\n"
    )
    write(repo, "README.md", body)
    write(repo, "docs/en/README.md", body)

    assert switcher.sync_file("README.md", write=True) == []
    assert switcher.sync_file("README.md", write=False) == []
    assert (repo / "README.md").read_text(encoding="utf-8").count(
        "🌐 [日本語](README.md)"
    ) == 2


def test_a_stale_block_is_reported_before_it_is_rewritten(repo) -> None:
    body = (
        f"# Title\n\n{switcher.START}\n🌐 wrong\n{switcher.END}\n\nbody\n\n"
        f"{switcher.START}\n🌐 wrong\n{switcher.END}\n"
    )
    write(repo, "README.md", body)
    write(repo, "docs/en/README.md")
    problems = switcher.sync_file("README.md", write=False)
    assert len(problems) == 2
    assert all("out of date" in problem for problem in problems)


# --- links that prefer another language --------------------------------------------------------


def test_an_english_page_linking_into_japanese_is_reported_when_english_exists(
    repo,
) -> None:
    """check_links.py cannot see this: the fallback resolves, so nothing else notices."""
    write(repo, "README.md")
    write(
        repo, "docs/en/README.md", "# Title\n\n[Design](../ja/design/architecture.md)\n"
    )
    write(repo, "docs/ja/design/architecture.md")
    write(repo, "docs/en/design/architecture.md")

    problems = switcher.check_language_links("docs/en/README.md")
    assert len(problems) == 1
    assert "exists in en" in problems[0]


def test_a_fallback_is_allowed_while_the_translation_does_not_exist(repo) -> None:
    write(repo, "README.md")
    write(
        repo, "docs/en/README.md", "# Title\n\n[Design](../ja/design/architecture.md)\n"
    )
    write(repo, "docs/ja/design/architecture.md")

    assert switcher.check_language_links("docs/en/README.md") == []


def test_linking_to_the_other_language_hub_is_allowed(repo) -> None:
    """The Japanese landing page pointing English readers at the English hub is navigation.

    The rule catches a page that kept pointing at another language's copy after its own was
    written. A hub was never such a copy, so a hub-to-hub link is intent, not drift.
    """
    write(
        repo,
        "README.md",
        "# Title\n\nEnglish hub: [docs/en/README.md](docs/en/README.md)\n",
    )
    write(repo, "docs/en/README.md")
    assert switcher.check_language_links("README.md") == []


def test_linking_to_another_language_below_hub_level_is_still_reported(repo) -> None:
    """The exemption is scoped to the hub; everything else keeps the original behaviour."""
    write(repo, "README.md")
    write(
        repo, "docs/en/README.md", "# Title\n\n[Design](../ja/design/architecture.md)\n"
    )
    write(repo, "docs/ja/design/architecture.md")
    write(repo, "docs/en/design/architecture.md")
    assert len(switcher.check_language_links("docs/en/README.md")) == 1


def test_a_deliberately_bilingual_line_is_allowed(repo) -> None:
    """Pairing both languages on one line is how reference pages cite themselves."""
    write(repo, "README.md")
    write(
        repo,
        "docs/en/README.md",
        "# Title\n\n[日本語](../ja/design/architecture.md) / "
        "[English](design/architecture.md)\n",
    )
    write(repo, "docs/ja/design/architecture.md")
    write(repo, "docs/en/design/architecture.md")

    assert switcher.check_language_links("docs/en/README.md") == []
