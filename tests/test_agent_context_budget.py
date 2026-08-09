"""The AGENTS.md budget and the steering-loader reachability check.

The budget number itself is asserted because it is a decision, not an implementation detail: the
sibling repository settled at 28,000 B after its instructions had grown past 78 KB and been split
apart. Starting a new repository at that ceiling would import the end state of somebody else's
sprawl, so this one starts at 20,000 B. Anyone raising it should have to change a test and say why.

The loader checks matter more here than they look. `.kiro/` is gitignored, which means the person
writing a steering file cannot rely on a reviewer seeing it — this check is the review.
"""

from __future__ import annotations

import check_agent_context_budget as budget
import pytest


@pytest.fixture
def repo(tmp_path, monkeypatch):
    monkeypatch.setattr(budget, "ROOT", tmp_path)
    monkeypatch.setattr(budget, "AGENTS", tmp_path / "AGENTS.md")
    # git is not initialised in a temporary directory, so the "is it published" half degrades to
    # unknown and is skipped. That is the same behaviour a fresh clone sees.
    monkeypatch.setattr(budget, "tracked", lambda: None)
    return tmp_path


def write(root, relative: str, body: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


# --- the budget --------------------------------------------------------------------------------


def test_the_budget_is_twenty_kilobytes() -> None:
    assert budget.AGENTS_BUDGET == 20_000


def test_an_oversized_agents_md_is_reported(repo) -> None:
    write(repo, "AGENTS.md", "x" * (budget.AGENTS_BUDGET + 1))
    problems: list[str] = []
    budget.check_budgets(problems)
    assert len(problems) == 1
    assert "over the" in problems[0]


def test_a_file_within_budget_is_not_reported(repo) -> None:
    write(repo, "AGENTS.md", "x" * 100)
    problems: list[str] = []
    budget.check_budgets(problems)
    assert problems == []


# --- index reachability ------------------------------------------------------------------------


def test_an_index_with_no_docs_reference_is_reported(repo) -> None:
    """The index is the entry point to everything that was split out of AGENTS.md."""
    write(repo, "AGENTS.md", "# AGENTS\n\nNo pointers here.\n")
    problems: list[str] = []
    budget.check_index_targets(problems)
    assert any("does not reference docs/" in problem for problem in problems)


def test_a_dangling_index_link_is_reported(repo) -> None:
    write(repo, "AGENTS.md", "# AGENTS\n\n- [Design](docs/ja/design/architecture.md)\n")
    problems: list[str] = []
    budget.check_index_targets(problems)
    assert any("does not exist" in problem for problem in problems)


def test_an_index_link_into_kiro_is_reported(repo) -> None:
    """`.kiro/` is not published, so a pointer into it is a 404 for everyone who clones."""
    write(repo, ".kiro/steering/loader.md", "---\ninclusion: always\n---\n")
    write(repo, "docs/ja/design/architecture.md", "# Architecture\n")
    write(
        repo,
        "AGENTS.md",
        "# AGENTS\n\n- [Design](docs/ja/design/architecture.md)\n"
        "- [Loader](.kiro/steering/loader.md)\n",
    )
    problems: list[str] = []
    budget.check_index_targets(problems)
    assert any(
        "not published" in problem or ".kiro/" in problem for problem in problems
    )


def test_a_resolvable_index_passes(repo) -> None:
    write(repo, "docs/ja/design/architecture.md", "# Architecture\n")
    write(repo, "AGENTS.md", "# AGENTS\n\n- [Design](docs/ja/design/architecture.md)\n")
    problems: list[str] = []
    budget.check_index_targets(problems)
    assert problems == []


# --- steering loaders --------------------------------------------------------------------------


def test_auto_inclusion_without_name_and_description_is_reported(repo) -> None:
    """Eleven files were in this state in a sibling repository and were never once loaded."""
    write(repo, ".kiro/steering/loader.md", "---\ninclusion: auto\n---\n\nbody\n")
    problems: list[str] = []
    budget.check_loaders(problems)
    assert len(problems) == 2
    assert any("'name'" in problem for problem in problems)
    assert any("'description'" in problem for problem in problems)


def test_a_complete_auto_loader_passes(repo) -> None:
    write(
        repo,
        ".kiro/steering/loader.md",
        "---\ninclusion: auto\nname: design\ndescription: when designing\n---\n",
    )
    problems: list[str] = []
    budget.check_loaders(problems)
    assert problems == []


def test_an_invalid_inclusion_value_is_reported(repo) -> None:
    write(repo, ".kiro/steering/loader.md", "---\ninclusion: sometimes\n---\n")
    problems: list[str] = []
    budget.check_loaders(problems)
    assert any("not a valid value" in problem for problem in problems)


def test_file_match_without_a_pattern_is_reported(repo) -> None:
    write(repo, ".kiro/steering/loader.md", "---\ninclusion: fileMatch\n---\n")
    problems: list[str] = []
    budget.check_loaders(problems)
    assert any("fileMatchPattern" in problem for problem in problems)


def test_a_loader_pointing_at_a_missing_document_is_reported(repo) -> None:
    write(
        repo,
        ".kiro/steering/loader.md",
        "---\ninclusion: manual\n---\n\nSee docs/ja/design/architecture.md\n",
    )
    problems: list[str] = []
    budget.check_loaders(problems)
    assert any("does not exist" in problem for problem in problems)


def test_loaders_are_skipped_when_kiro_is_absent(repo) -> None:
    """A clone and a CI runner have no `.kiro/`. Reporting that would make CI noisy."""
    write(repo, "AGENTS.md", "x")
    assert budget.kiro_present() is False
    problems: list[str] = []
    budget.check_loaders(problems)
    assert problems == []
