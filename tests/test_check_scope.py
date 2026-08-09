"""No check may look at a generated file.

Found by running `make clean` and then `make all`: the audit reported 26 files on one run and 27 on
another, and markdownlint 18 then 19. The extra file was `.pytest_cache/README.md`, which pytest
writes and `make clean` removes. Nothing was ever wrong with the repository — the *scope* of two
checks depended on whether tests had run.

That matters more than the tidiness of a file count. A gate that reports a different set of files
for the same commit cannot be used to tell whether a change is clean, and the first time it does
report something the natural reaction is to re-run it rather than to read it. Caches are therefore
out of scope everywhere, and this file asserts it in every place the scope is declared, because there
are four of them and they are easy to update three at a time.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import audit_public_output as audit
import check_links as links
import pytest

ROOT = Path(__file__).resolve().parent.parent
# Every directory a tool generates. `.terraform` joined the list when the link checker walked
# into a downloaded provider's own README and reported its relative links as broken.
CACHES = (".pytest_cache", ".ruff_cache", "__pycache__", ".terraform")


@pytest.mark.parametrize("cache", CACHES)
def test_the_audit_skips_generated_caches(cache: str) -> None:
    assert cache in audit.SKIP_DIRS


@pytest.mark.parametrize("cache", CACHES)
def test_the_link_check_skips_generated_caches(cache: str) -> None:
    assert cache in links.SKIP_DIRS


def test_the_audit_does_not_walk_into_a_cache(tmp_path) -> None:
    """Asserted through the walker rather than the constant, so a refactor cannot pass vacuously."""
    (tmp_path / ".pytest_cache").mkdir()
    (tmp_path / ".pytest_cache" / "README.md").write_text("FSxN\n", encoding="utf-8")
    (tmp_path / "real.md").write_text("clean\n", encoding="utf-8")
    found = {path.name for path in audit.iter_files(tmp_path)}
    assert found == {"real.md"}


def test_the_link_check_does_not_walk_into_a_cache(tmp_path) -> None:
    (tmp_path / ".ruff_cache").mkdir()
    (tmp_path / ".ruff_cache" / "notes.md").write_text(
        "[x](nowhere.md)\n", encoding="utf-8"
    )
    (tmp_path / "real.md").write_text("clean\n", encoding="utf-8")
    found = {path.name for path in links.iter_markdown(tmp_path)}
    assert found == {"real.md"}


def test_markdownlint_ignores_generated_caches() -> None:
    """The JSONC config carries comments, so strip them before parsing."""
    text = (ROOT / ".markdownlint-cli2.jsonc").read_text(encoding="utf-8")
    stripped = re.sub(r"//[^\n]*", "", text)
    config = json.loads(stripped)
    ignores = " ".join(config["ignores"])
    for cache in CACHES:
        assert cache in ignores, f"{cache} is not ignored by markdownlint"


def test_the_makefile_and_ci_agree_on_the_markdown_ignores() -> None:
    """Two invocations of the same linter with different scopes is the drift this prevents."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for cache in (".pytest_cache", ".ruff_cache", ".terraform"):
        assert cache in makefile, f"Makefile markdown target does not exclude {cache}"
        assert cache in workflow, f"ci.yml markdown job does not exclude {cache}"


def test_no_generated_file_is_tracked_by_a_check_today() -> None:
    """The end state: every file the audit examines is one a reader could open in the repository."""
    for path in audit.iter_files(ROOT):
        parts = path.relative_to(ROOT).parts
        assert not any(part in CACHES for part in parts), path
