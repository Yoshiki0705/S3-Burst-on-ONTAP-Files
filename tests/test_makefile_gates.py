"""Every Makefile target must be declared `.PHONY`, and `make all` must run every gate.

The first half is carried over from the sibling repository `fsxn-s3ap-serverless-patterns`
(`scripts/tests/test_makefile_phony.py`). There, `security` was not declared phony and collided
with a `security/` directory, so make answered "`security' is up to date" and ran bandit zero
times — while `make security` sat in the pre-commit list and in the agent instructions, appearing
to pass. The first real run found nine Medium-and-above findings, two of them genuine SQL injection
vectors. A silent no-op is the worst kind of gate, because its output is indistinguishable from
success.

The second half is new: a target can be correct, declared, and still never run because nobody
wired it into the aggregate. `make all` is what the commit gate and CI invoke, so a validator
missing from its prerequisite list is a validator that exists and does nothing.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"

# Pattern-rule and special targets are not phony candidates.
IGNORED_PREFIXES = (".", "%")

# Targets that deliberately stay out of `make all`: they need a network, they rewrite files, or
# they are aggregates themselves. Everything else must be reachable from `all`.
NOT_IN_ALL = {
    "help",
    "all",
    "lint",  # an aggregate, and its own members are asserted below
    "format-python",  # rewrites files
    "switcher-write",  # rewrites files
    "links-external",  # needs a network
    "new-pattern",  # takes arguments
    "commit-gate",  # takes arguments; enforced by the PreToolUse hook, not by the aggregate
    "clean",
}


def text() -> str:
    return MAKEFILE.read_text(encoding="utf-8")


def targets() -> list[str]:
    """Every explicit target defined in the Makefile, in order of appearance."""
    found = re.findall(r"^([A-Za-z0-9_.\-]+):(?!=)", text(), re.MULTILINE)
    return [t for t in dict.fromkeys(found) if not t.startswith(IGNORED_PREFIXES)]


def declared() -> set[str]:
    """Every name listed in the Makefile's `.PHONY` declaration."""
    match = re.search(r"^\.PHONY:((?:[^\n\\]*\\\n)*[^\n]*)", text(), re.MULTILINE)
    if not match:
        return set()
    return set(match.group(1).replace("\\", " ").split())


def prerequisites(target: str) -> set[str]:
    match = re.search(rf"^{re.escape(target)}:([^\n#]*)", text(), re.MULTILINE)
    if not match:
        return set()
    return {word for word in match.group(1).split() if not word.startswith("$")}


def test_every_target_is_declared_phony() -> None:
    missing = [t for t in targets() if t not in declared()]
    assert not missing, (
        "Makefile targets missing from .PHONY: "
        + ", ".join(missing)
        + ". A target that is not phony is skipped when a path of the same name "
        "exists, and make reports success without running the recipe."
    )


def test_no_target_shares_a_name_with_a_path() -> None:
    """The condition that makes the omission dangerous, checked directly.

    Passing this does not make the declaration optional — it records which targets are one
    `mkdir` away from breaking if the declaration were ever dropped.
    """
    for target in [t for t in targets() if (ROOT / t).exists()]:
        assert target in declared(), (
            f"target {target!r} collides with an existing path and is not .PHONY, "
            "so make will report it up to date and never run it"
        )


def test_no_phony_target_produces_a_file_of_its_own_name() -> None:
    """Declaring a real file target phony would break incremental builds."""
    produced = [t for t in declared() if (ROOT / t).is_file()]
    assert not produced, (
        "these .PHONY names are also files, so the declaration may be wrong: "
        + ", ".join(produced)
    )


def test_the_declaration_is_not_empty() -> None:
    """A regex that silently matches nothing would make the checks above vacuous."""
    assert declared(), ".PHONY declaration not found or unparsed"
    assert targets(), "no Makefile targets found; the target regex is broken"


def test_every_gate_is_reachable_from_make_all() -> None:
    direct = prerequisites("all")
    reachable = set(direct)
    for target in direct:
        reachable |= prerequisites(target)

    orphans = sorted(set(targets()) - reachable - NOT_IN_ALL)
    assert not orphans, (
        "these targets are not reachable from `make all`: "
        + ", ".join(orphans)
        + ". A validator nobody invokes is a validator that does nothing. Either add it to the "
        "`all` prerequisites or record why it stays out in NOT_IN_ALL."
    )


def test_the_exclusion_list_names_only_real_targets() -> None:
    """A stale entry in NOT_IN_ALL would silently excuse a gate that no longer exists."""
    unknown = sorted(NOT_IN_ALL - set(targets()))
    assert not unknown, (
        "NOT_IN_ALL names targets the Makefile does not define: " + ", ".join(unknown)
    )
