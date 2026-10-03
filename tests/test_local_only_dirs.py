"""Local-only directories are ignored by git and skipped by every tree walker.

The Python walkers import `LOCAL_ONLY_DIRS`; `.gitignore` and `.markdownlint-cli2.jsonc` cannot,
so they repeat the names. These tests fail when a name is added to the constant but not to them.
"""

from __future__ import annotations

from pathlib import Path

import audit_public_output
import check_diagram_flow
import check_diagram_fonts
import check_links
from local_only_dirs import LOCAL_ONLY_DIRS

ROOT = Path(__file__).resolve().parent.parent


def test_every_local_only_dir_is_gitignored() -> None:
    lines = {line.strip() for line in (ROOT / ".gitignore").read_text().splitlines()}
    assert {f"{name}/" for name in LOCAL_ONLY_DIRS} <= lines


def test_every_local_only_dir_is_excluded_from_markdownlint() -> None:
    config = (ROOT / ".markdownlint-cli2.jsonc").read_text()
    for name in LOCAL_ONLY_DIRS:
        assert f'"{name}/**"' in config


def test_every_walker_skips_the_local_only_dirs() -> None:
    assert LOCAL_ONLY_DIRS <= set(audit_public_output.SKIP_DIRS)
    assert LOCAL_ONLY_DIRS <= set(check_links.SKIP_DIRS)
    assert LOCAL_ONLY_DIRS <= check_diagram_fonts.SKIP
    assert LOCAL_ONLY_DIRS <= check_diagram_flow.SKIP
