"""The commit gate, checked in both directions.

A hook that never fires is worse than no hook, because its presence is taken as coverage. Every rule
here is asserted to reject something and to accept something, and the reuse of the document audit is
asserted directly — if someone copies the rules into the gate instead of calling the audit, the two
sets will drift and only one of them will be maintained.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import commit_gate as gate
from conftest import REAL_LOOKING_ACCOUNT
import pytest

ROOT = Path(__file__).resolve().parent.parent


# --- subject shape ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subject",
    [
        "docs: separate the two S3-over-files mechanisms",
        "feat(collect): add the S3 access point ingest pattern",
        "fix: correct the teardown order on the serve side",
        "ci: pin every action to a commit SHA",
        "bench: record the first end-to-end visibility measurement",
    ],
)
def test_a_well_formed_subject_passes(subject: str) -> None:
    assert gate.check_subject(subject) == []


@pytest.mark.parametrize(
    "subject",
    [
        "update architecture.md",
        "Docs: capitalised type",
        "feature: not an allowed type",
        "docs:missing space",
        "",
    ],
)
def test_a_malformed_subject_is_rejected(subject: str) -> None:
    assert gate.check_subject(subject)


def test_an_overlong_subject_is_rejected() -> None:
    subject = "docs: " + "x" * 80
    problems = gate.check_subject(subject)
    assert any("characters" in problem for problem in problems)


def test_a_trailing_period_is_rejected() -> None:
    assert any(
        "period" in problem
        for problem in gate.check_subject("docs: add the architecture guide.")
    )


def test_a_subject_that_judges_earlier_work_is_rejected() -> None:
    """`git log` is permanent, so the line stays readable as a verdict indefinitely."""
    problems = gate.check_subject("docs: fix broken navigation nobody tested")
    assert any("what this change adds" in problem for problem in problems)


def test_process_metadata_in_a_subject_is_rejected() -> None:
    for subject in (
        "docs: add phase3 notes",
        "docs: update for 2026-08-09",
        "docs: wip on the matrix",
    ):
        assert any(
            "process metadata" in problem for problem in gate.check_subject(subject)
        )


def test_a_body_must_be_separated_by_a_blank_line() -> None:
    problems = gate.check_message("docs: add the guide\nthe body starts too early")
    assert any("blank line" in problem for problem in problems)


def test_a_properly_separated_body_passes() -> None:
    assert (
        gate.check_message("docs: add the guide\n\nWhy: the hub had no entry point.")
        == []
    )


# --- branch shape ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name", ["docs/mechanism-distinction", "feat/s3ap-ingest", "ci/pin-actions"]
)
def test_a_well_formed_branch_passes(name: str) -> None:
    assert gate.check_branch(name) == []


@pytest.mark.parametrize(
    "name",
    [
        "Docs/Mixed-Case",
        "docs_underscore/thing",
        "no-slash",
        "docs/trailing-",
        "docs/phase3-20260809",
        "docs/agent-session-2",
        "docs/fix-broken-links",
    ],
)
def test_a_malformed_or_leaky_branch_is_rejected(name: str) -> None:
    assert gate.check_branch(name)


def test_an_overlong_branch_is_rejected() -> None:
    name = "docs/" + "-".join(["word"] * 12)
    assert any("characters" in problem for problem in gate.check_branch(name))


def test_committing_straight_to_main_is_refused() -> None:
    for name in ("main", "master"):
        problems = gate.check_branch(name)
        assert problems and "branch first" in problems[0]


# --- content rules are borrowed, not copied ------------------------------------------------------


def test_the_gate_calls_the_document_audit() -> None:
    """Two copies of a rule set means one is stale, and the stale one is whichever nobody runs."""
    source = Path(gate.__file__).read_text(encoding="utf-8")
    assert "audit.audit_line" in source
    assert "audit_public_output" in source


@pytest.mark.parametrize(
    ("message", "category"),
    [
        ("docs: describe FSxN volume layout", "naming"),
        ("docs: note that BlueXP manages the cluster", "vendor-ref"),
        ("docs: explain why this beats DataSync", "neutrality"),
        ("docs: reference case 123456", "pii"),
        (f"docs: add account {REAL_LOOKING_ACCOUNT} to the example", "pii"),
        ("docs: state that duality enables S3 Access Point on a cache", "conflation"),
    ],
)
def test_content_rules_reach_the_message(message: str, category: str) -> None:
    problems = gate.check_message(message)
    assert any(f"[{category}]" in problem for problem in problems), problems


def test_a_clean_message_passes_every_content_rule() -> None:
    assert (
        gate.check_message("docs: record the FSx for ONTAP support matrix sources")
        == []
    )


# --- command parsing ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ('git commit -m "docs: add guide"', "docs: add guide"),
        ("git commit --message='docs: add guide'", "docs: add guide"),
        ('git commit -m"docs: add guide"', "docs: add guide"),
        (
            'git commit -m "docs: add guide" -m "Why: it was missing."',
            "docs: add guide\n\nWhy: it was missing.",
        ),
        ('git -C /tmp commit -m "docs: add guide"', "docs: add guide"),
    ],
)
def test_the_message_is_extracted_from_the_command(command: str, expected: str) -> None:
    assert gate.message_from_command(command) == expected


@pytest.mark.parametrize(
    "command",
    [
        "git status",
        "git commit",  # opens an editor; nothing to inspect yet
        "git commit --amend",
        "echo 'git commit -m x'",
        "git log --oneline",
    ],
)
def test_a_command_with_no_inline_message_yields_nothing(command: str) -> None:
    if command.startswith("echo"):
        # A quoted commit inside another command is not a commit. shlex sees the whole thing as one
        # argument, so no message is found — asserted so the parser is not "improved" into matching
        # substrings, which would block unrelated commands.
        assert gate.message_from_command(command) is None
        return
    assert gate.message_from_command(command) is None


def test_a_malformed_command_does_not_raise() -> None:
    assert gate.message_from_command('git commit -m "unbalanced') is None


# --- the hook contract --------------------------------------------------------------------------


def run_hook(
    payload: dict, branch: str = "docs/example"
) -> subprocess.CompletedProcess:
    """Invoke the hook with the branch pinned.

    The branch is always set explicitly. Leaving it to whatever the working copy is checked out on
    made one of these tests pass for a reason that had nothing to do with the hook: before the first
    commit existed, `git rev-parse` failed, `current_branch()` returned None, and the branch rules
    never ran. The test went red the moment the repository had a commit — on CI, not locally.
    """
    env = {**os.environ, "COMMIT_GATE_BRANCH": branch}
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "commit_gate.py"), "--hook"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def test_the_hook_blocks_with_exit_two() -> None:
    """Kiro treats exit 2 as "block"; any other non-zero code fails silently and lets it through."""
    proc = run_hook({"command": 'git commit -m "update stuff"'})
    assert proc.returncode == 2
    assert "commit gate" in proc.stderr


def test_the_hook_allows_a_clean_commit_on_a_compliant_branch() -> None:
    proc = run_hook({"command": 'git commit -m "docs: add the support matrix"'})
    assert proc.returncode == 0, proc.stderr


def test_the_hook_blocks_a_clean_message_on_main() -> None:
    """The branch half of the gate, asserted explicitly instead of inherited from the environment."""
    proc = run_hook(
        {"command": 'git commit -m "docs: add the support matrix"'}, branch="main"
    )
    assert proc.returncode == 2
    assert "branch first" in proc.stderr


def test_an_empty_branch_override_is_treated_as_unknown() -> None:
    """An unset branch must not be read as a branch named "", which no rule would match."""
    proc = run_hook(
        {"command": 'git commit -m "docs: add the support matrix"'}, branch=""
    )
    assert proc.returncode == 0, proc.stderr


def test_the_hook_ignores_a_command_that_is_not_a_commit() -> None:
    proc = run_hook({"command": "git status --short"})
    assert proc.returncode == 0


def test_the_hook_does_not_block_on_an_unreadable_payload() -> None:
    """Blocking every tool call because a payload shape changed would be worse than missing one."""
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "commit_gate.py"), "--hook"],
        input="not json",
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0


def test_the_hook_reads_a_nested_command_field() -> None:
    proc = run_hook({"toolInput": {"command": 'git commit -m "update stuff"'}})
    assert proc.returncode == 2
