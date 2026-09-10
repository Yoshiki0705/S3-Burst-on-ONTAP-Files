"""Every subcommand a runbook offers must reach a function that exists, and exists in time.

Written because both halves of that sentence were broken in one commit, and nothing reported it. The
block phases were appended to `perf-matrix/runbook.sh` after its `case` statement, so bash had not
defined them by the time the dispatch ran and no subcommand could ever have invoked one; and one of
them called `run_on_client`, which did not exist. Neither is a parse error, so `bash -n` passed.
`shellcheck` passed. Both were found by reading, which is not a control.

Ordering is the part worth stating: bash executes a script top to bottom, so a function defined below
the dispatch is not merely untidy, it is unreachable. A shell script has no link step to notice.

These scripts cannot be executed here -- every phase calls AWS -- so this reads them as text. That is
the whole of what can be checked without spending money, and it is the half that was wrong.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Any tracked shell script with a subcommand dispatch. Discovered rather than listed: a new runbook
# should be covered by having a dispatch, not by being remembered here.
DISPATCH = re.compile(r'^case\s+"\$\{1:-\}"\s+in\s*$', re.MULTILINE)
DEFINITION = re.compile(r"^([a-z_][a-z0-9_]*)\(\)\s*\{", re.MULTILINE)
# A dispatch arm's body, up to the `;;`. Function names are extracted from that, so an arm that runs a
# builtin, an `exec`, or a nested `case` is handled without naming those forms here.
ARM = re.compile(r"^\s{2}([a-z0-9|*-]+)\)(.*?);;", re.MULTILINE | re.DOTALL)
CALL = re.compile(
    r"\b([a-z_][a-z0-9_]*)\s+(?:\"|\$|[a-z0-9-]|$)|\b([a-z_][a-z0-9_]*)\s*;;"
)

# Names an arm may invoke that are not functions in the same file.
NOT_A_FUNCTION = {
    "exec",
    "usage",  # defined in every one of these, but asserted separately below
    "exit",
    "die",
    "echo",
    "printf",
    "cd",
    "set",
    "esac",
    "case",
    "in",
}


def scripts() -> list[Path]:
    found = [
        path
        for path in sorted(ROOT.rglob("*.sh"))
        if ".git" not in path.parts
        and DISPATCH.search(path.read_text(encoding="utf-8"))
    ]
    assert found, (
        'no shell script with a `case "${1:-}"` dispatch was found. This repository has several, '
        "so the discovery pattern stopped matching rather than there being nothing to check."
    )
    return found


@pytest.mark.parametrize("script", scripts(), ids=lambda p: str(p.relative_to(ROOT)))
def test_every_dispatch_target_is_defined_before_the_dispatch(script: Path) -> None:
    text = script.read_text(encoding="utf-8")
    dispatch_at = DISPATCH.search(text).start()  # type: ignore[union-attr]
    defined_before = {
        name
        for match in DEFINITION.finditer(text)
        if match.start() < dispatch_at
        for name in [match.group(1)]
    }
    defined_after = {
        match.group(1)
        for match in DEFINITION.finditer(text)
        if match.start() > dispatch_at
    }

    problems: list[str] = []
    for arm in ARM.finditer(text[dispatch_at:]):
        body = arm.group(2)
        for pair in CALL.finditer(body):
            name = pair.group(1) or pair.group(2)
            if not name or name in NOT_A_FUNCTION:
                continue
            if name in defined_before:
                continue
            if name in defined_after:
                problems.append(
                    f"{arm.group(1)}) calls {name}(), which is defined *after* the dispatch at "
                    "line "
                    f"{text[: text.index(name + '() {')].count(chr(10)) + 1}. Bash reads top to "
                    "bottom, so the dispatch cannot see it and the subcommand can never run."
                )
            elif re.search(rf"^{re.escape(name)}\(\)", text, re.MULTILINE) is None:
                problems.append(
                    f"{arm.group(1)}) calls {name}(), which this file does not define. "
                    "Not a parse error, so bash -n and shellcheck both pass."
                )
    assert not problems, "\n  ".join([""] + problems)


@pytest.mark.parametrize("script", scripts(), ids=lambda p: str(p.relative_to(ROOT)))
def test_the_usage_text_lists_every_subcommand(script: Path) -> None:
    """A phase nobody can find is a phase nobody runs.

    The block phases were added to the dispatch and to the usage text in the same edit; this is what
    keeps the next one from arriving in only the first.
    """
    text = script.read_text(encoding="utf-8")
    dispatch_at = DISPATCH.search(text).start()  # type: ignore[union-attr]
    usage = text[:dispatch_at]

    missing = []
    for arm in ARM.finditer(text[dispatch_at:]):
        label = arm.group(1)
        if label == "*":
            continue
        for name in label.split("|"):
            if name not in usage:
                missing.append(name)
    assert not missing, (
        f"{script.relative_to(ROOT)}: these subcommands are dispatched but never named in the "
        "usage text above it: " + ", ".join(sorted(set(missing)))
    )
