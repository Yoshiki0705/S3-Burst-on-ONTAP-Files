"""Action pinning, checked in both directions and against the real workflows.

The last test is the one that matters: it runs the checker over this repository's own workflows. A
pinning check that passes because it stopped matching `uses:` lines looks exactly like a repository
with no unpinned actions, which is why the checker fails when it finds nothing to examine.
"""

from __future__ import annotations

import check_actions_pinning as pinning
import pytest

GOOD = (
    "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4.4.0"
)


def test_a_sha_with_a_version_comment_passes() -> None:
    assert pinning.check_line(GOOD) is None


@pytest.mark.parametrize(
    "line",
    [
        "      - uses: actions/checkout@v4",
        "      - uses: actions/checkout@main",
        "      - uses: actions/checkout@v4.4.0",
        "        uses: gitleaks/gitleaks-action@latest",
    ],
)
def test_a_moving_pointer_is_rejected(line: str) -> None:
    problem = pinning.check_line(line)
    assert problem and "moving pointer" in problem


def test_a_reference_with_no_version_is_rejected() -> None:
    problem = pinning.check_line("      - uses: actions/checkout")
    assert problem and "no version at all" in problem


def test_a_sha_without_a_version_comment_is_rejected() -> None:
    """The SHA is safe; the problem is that nobody can tell which release it is."""
    problem = pinning.check_line(
        "      - uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262"
    )
    assert problem and "no version comment" in problem


def test_a_short_sha_is_not_accepted_as_a_pin() -> None:
    problem = pinning.check_line("      - uses: actions/checkout@11d5960 # v4")
    assert problem and "moving pointer" in problem


@pytest.mark.parametrize(
    "line",
    [
        "      - uses: ./.github/actions/setup",
        "    uses: ./.github/workflows/reusable.yml",
    ],
)
def test_a_local_action_is_exempt(line: str) -> None:
    assert pinning.check_line(line) is None


def test_a_line_that_is_not_a_uses_reference_is_ignored() -> None:
    for line in ("      - name: Checkout", "        with:", "# uses: something@v1"):
        assert pinning.check_line(line) is None


def test_this_repository_pins_every_action() -> None:
    assert pinning.main() == 0


def test_the_checker_actually_found_references() -> None:
    """Guards against the check passing because its regex stopped matching."""
    files = pinning.workflow_files()
    assert files, "no workflow files found"
    total = sum(
        1
        for path in files
        for line in path.read_text(encoding="utf-8").splitlines()
        if pinning.USES.match(line)
    )
    assert total >= 3, f"expected several action references, found {total}"
