"""Every checkov suppression must name a check and give a reason, and checkov must be pinned.

`checkov -d .` reports "Failed checks: 0" whether nothing is wrong or everything has been suppressed.
That makes the suppressions the interesting part of the configuration, and `# checkov:skip=ID`
without a reason is accepted by the scanner while telling a reviewer nothing -- the quiet failure this
repository has already been bitten by in a different gate.

Also asserted: the pin. An unpinned scanner gains policies between releases, so the same commit
passes on one machine and fails on another, and the natural reaction to that is to stop believing
the gate rather than to read it.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = ROOT / "requirements-dev.txt"

# `# checkov:skip=CKV_AWS_149: reason` -- the id, then whatever follows the colon.
SKIP = re.compile(r"checkov:skip=([A-Za-z0-9_]+)\s*:?\s*(.*)$")
CHECK_ID = re.compile(r"^CKV[A-Z0-9_]*_\d+$")
# Long enough that a reason has to be a sentence rather than a word. The shortest legitimate one in
# the repository is comfortably above this.
MINIMUM_REASON = 20


def tracked_templates() -> list[Path]:
    listing = subprocess.run(
        ["git", "ls-files", "*.yaml", "*.yml", "*.tf"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / name for name in listing]


def skips() -> list[tuple[Path, int, str, str]]:
    found: list[tuple[Path, int, str, str]] = []
    for path in tracked_templates():
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            match = SKIP.search(line)
            if match:
                found.append(
                    (path.relative_to(ROOT), lineno, match.group(1), match.group(2))
                )
    return found


def test_checkov_is_pinned_to_an_exact_version() -> None:
    requirements = REQUIREMENTS.read_text(encoding="utf-8")
    assert re.search(r"^checkov==\d+\.\d+\.\d+$", requirements, re.MULTILINE), (
        "checkov must be pinned exactly in requirements-dev.txt: its policy set grows between "
        "releases, so an unpinned install turns the gate red with no commit behind it"
    )


def test_there_is_something_to_check() -> None:
    """If the discovery finds no template the assertions below are vacuous."""
    assert tracked_templates(), "no tracked YAML or Terraform found"


def test_every_skip_names_a_plausible_check_id() -> None:
    wrong = [
        f"{path}:{lineno}: {check!r}"
        for path, lineno, check, _ in skips()
        if not CHECK_ID.match(check)
    ]
    assert not wrong, (
        "these suppressions do not name a checkov check id (CKV_AWS_123 and the like): "
        + "; ".join(wrong)
        + ". A malformed id suppresses nothing and reads as though it does."
    )


def test_every_skip_gives_a_reason() -> None:
    unexplained = [
        f"{path}:{lineno}: {check}"
        for path, lineno, check, reason in skips()
        if len(reason.strip()) < MINIMUM_REASON
    ]
    assert not unexplained, (
        "these suppressions have no reason, or too short a one: "
        + "; ".join(unexplained)
        + ". checkov accepts a bare skip and reports zero failures, so the reason is the only thing "
        "that tells a reviewer whether the finding was considered or waved away."
    )


def test_the_makefile_gate_degrades_rather_than_failing_when_checkov_is_absent() -> (
    None
):
    """checkov is a heavy install. A hard failure would make `make all` unusable without it."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    match = re.search(r"^iac-security:.*?\n((?:\t.*\n)+)", makefile, re.MULTILINE)
    assert match, "iac-security target not found"
    recipe = match.group(1)
    assert "command -v checkov" in recipe, (
        "the target must check for checkov and skip with a message, as the gitleaks target does"
    )
    assert "skipping" in recipe


def test_the_gate_names_its_frameworks() -> None:
    """Auto-detection makes the scanned set depend on the version, and a moving scope is not a gate."""
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    assert "--framework cloudformation" in makefile
    assert "--framework github_actions" in makefile
