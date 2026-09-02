"""Every Makefile target must be declared `.PHONY`, and `make all` must run every gate.

The first half is carried over from the sibling repository `FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns`
(`scripts/tests/test_makefile_phony.py`). There, `security` was not declared phony and collided
with a `security/` directory, so make answered "`security' is up to date" and ran bandit zero
times — while `make security` sat in the pre-commit list and in the agent instructions, appearing
to pass. The first real run found nine Medium-and-above findings, two of them genuine SQL injection
vectors. A silent no-op is the worst kind of gate, because its output is indistinguishable from
success.

The second half is new: a target can be correct, declared, and still never run because nobody
wired it into the aggregate. `make all` is what the commit gate invokes, so a validator missing from
its prerequisite list is a validator that exists and does nothing.

The third part closes the other end of the same hole. CI does not run `make all`; it invokes each
validator as its own step, so that a failure names the concern instead of reporting that the
aggregate failed. The cost of that choice is a second list to keep in step: a validator added to
`make all` runs for whoever commits locally and for nobody else, and a contributor without the local
toolchain -- or a merge from a fork -- passes checks the maintainer's machine would have failed. So the
script each `make all` member runs is asserted to appear in the CI workflow.
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
    "finops-write",  # rewrites files; `finops` is the gate that runs in the aggregate
    "diagrams",  # rewrites files, and needs the AWS icon package, which is not committed
    # `diagrams-check` would belong in the aggregate on its own terms, but it reads the same
    # uncommitted icon package to rebuild what it compares against, so in CI it could only ever
    # fail for a missing download. It is a local check, run alongside `diagrams`.
    "diagrams-check",
    "links-external",  # needs a network
    # Needs a network, and compares against a page AWS owns. In the aggregate it would turn the
    # commit gate red on a pull request that changed nothing, which is the failure that teaches
    # contributors to ignore red. Scheduled weekly in `interconnect-regions.yml` instead, and the CI
    # parity assertions below expect it to appear in a workflow rather than in `all`.
    "interconnect-regions",
    "new-pattern",  # takes arguments
    "commit-gate",  # takes arguments; enforced by the PreToolUse hook, not by the aggregate
    # Takes a pull request number and queries the API. It answers a question about a commit that
    # has already been pushed, which is after `make all` has run, not before.
    "pr-verify",
    # An aggregate of `all` plus the message check, meant to be the single command before a
    # commit. Reaching it from `all` would be circular.
    "ready",
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


# --- CI parity ---------------------------------------------------------------------------------

CI = ROOT / ".github" / "workflows" / "ci.yml"

# Gates CI reaches by another route. Each is a dedicated workflow, so the concern is covered but the
# script name does not appear in ci.yml.
COVERED_ELSEWHERE = {
    "secrets": "gitleaks.yml",
    "zizmor": "zizmor.yml",
    # `pinning` checks that actions are SHA-pinned. zizmor's own pedantic pass reports unpinned
    # actions, so the concern is covered in that workflow.
    "pinning": "zizmor.yml",
    # `lint` is an aggregate; its members are checked individually below.
    "lint": "its members are asserted individually",
}

# Gates whose input is deliberately not committed, so CI has nothing to check and adding a step there
# would report a skip forever while looking like coverage. These are honestly local-only, which is a
# different claim from COVERED_ELSEWHERE: nobody verifies them for a contributor who does not hold the
# files. The path is asserted to be gitignored below, so this exemption cannot be borrowed by a gate
# that ought to run in CI.
LOCAL_ONLY = {
    "blog-sync": ".private/",
}


def recipe(target: str) -> str:
    """The recipe body of a target: every indented line following its rule."""
    match = re.search(
        rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n|\n(?=\t))*)",
        text(),
        re.MULTILINE,
    )
    return match.group(1) if match else ""


def scripts_invoked(target: str) -> set[str]:
    """The tools/ and scripts/ files a target runs, directly or through its prerequisites."""
    found: set[str] = set()
    for name in {target} | prerequisites(target):
        found |= set(re.findall(r"(?:tools|scripts)/([A-Za-z0-9_]+\.py)", recipe(name)))
    return found


# Gates whose work is an external binary rather than a script in this repository. Matched by the
# command name, because `scripts_invoked` finds nothing for them and a gate that matches nothing
# would be skipped -- which is the blind spot this file exists to close, reproduced inside itself.
EXTERNAL_COMMANDS = {
    "cfn": "cfn-lint",
    "iac-security": "checkov",
    "markdown": "markdownlint",
}


def commands_invoked(target: str) -> set[str]:
    """What a gate runs in CI terms: repository scripts, or the external command it wraps."""
    scripts = scripts_invoked(target)
    if scripts:
        return scripts
    names = {target} | prerequisites(target)
    return {EXTERNAL_COMMANDS[name] for name in names if name in EXTERNAL_COMMANDS}


def executable_lines(text: str) -> str:
    """The workflow with comments stripped.

    Without this the search matches its own documentation: the comment explaining why the checkov
    step names its frameworks contains the word `checkov`, so deleting the step left the assertion
    green. Found by deleting it and watching the test pass.
    """
    return "\n".join(
        line for line in text.splitlines() if not line.lstrip().startswith("#")
    )


def test_every_make_all_gate_runs_in_ci() -> None:
    assert CI.is_file(), "the CI workflow must exist for this to mean anything"
    workflow = executable_lines(CI.read_text(encoding="utf-8"))
    missing: list[str] = []
    for gate in sorted(prerequisites("all")):
        if gate in COVERED_ELSEWHERE or gate in LOCAL_ONLY:
            continue
        invoked = commands_invoked(gate)
        assert invoked, (
            f"gate {gate!r} runs neither a script under tools/ or scripts/ nor a command listed in "
            "EXTERNAL_COMMANDS, so this test cannot tell whether CI runs it. Add it to "
            "EXTERNAL_COMMANDS rather than leaving it unchecked."
        )
        if not any(script in workflow for script in invoked):
            missing.append(f"{gate} ({', '.join(sorted(invoked))})")
    assert not missing, (
        "these `make all` gates do not run in ci.yml: "
        + "; ".join(missing)
        + ". CI invokes validators individually rather than running `make all`, so a gate added to "
        "the Makefile alone runs only for whoever commits locally."
    )


def test_the_ci_exemptions_name_real_gates() -> None:
    """A stale exemption would silently excuse a gate from CI."""
    unknown = sorted(set(COVERED_ELSEWHERE) - set(targets()))
    assert not unknown, (
        "COVERED_ELSEWHERE names targets the Makefile does not define: "
        + ", ".join(unknown)
    )


def test_the_workflows_the_exemptions_point_at_exist() -> None:
    for gate, where in COVERED_ELSEWHERE.items():
        if where.endswith(".yml"):
            assert (ROOT / ".github" / "workflows" / where).is_file(), (
                f"{gate} is exempted because {where} covers it, but that workflow is missing"
            )


def test_every_external_command_gate_is_a_real_target() -> None:
    """A stale entry would map a gate that no longer exists and check nothing."""
    unknown = sorted(set(EXTERNAL_COMMANDS) - set(targets()))
    assert not unknown, (
        "EXTERNAL_COMMANDS names targets the Makefile does not define: "
        + ", ".join(unknown)
    )


def test_the_pre_commit_target_covers_the_whole_gate() -> None:
    """`make ready` must depend on `all`, or it repeats the mistake it exists to prevent.

    `commit-gate` validates a subject line and nothing else. Invoking it before a commit satisfies the
    habit while covering none of the work, which is how a commit that fails `make all` gets made by
    someone who believes they ran the gate.
    """
    assert "all" in prerequisites("ready"), (
        "make ready must have `all` as a prerequisite; without it the command run before a commit "
        "checks only the message"
    )


def test_local_only_gates_really_have_uncommittable_input():
    """Keep the CI exemption honest.

    A gate is exempt from the CI-parity assertion only because its input is not in the repository. If
    that path ever became tracked, the gate would be verifiable in CI and the exemption would be
    hiding a missing step rather than describing a real constraint.
    """
    ignore = Path(__file__).resolve().parent.parent / ".gitignore"
    patterns = {
        line.strip().lstrip("/").rstrip("/")
        for line in ignore.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    for gate, path in LOCAL_ONLY.items():
        assert path.rstrip("/") in patterns, (
            f"gate {gate!r} claims its input {path!r} is not committed, but {path!r} is not in "
            ".gitignore. Either the path is tracked and the gate belongs in ci.yml, or .gitignore "
            "changed and this exemption is now false."
        )
