"""The irreversible-operations guard must block, ask and allow, proven by execution.

`scripts/guard_irreversible_ops.py` carries an in-file case table and a `--selftest` flag. That
table shows the matching logic is right. It does not show the script behaves as a PreToolUse hook,
and the hook contract is where this class of guard fails:

  exit 0 + empty stdout            -> allow
  exit 0 + permissionDecision:ask  -> prompt the human first
  exit 2 + stderr                  -> block; stderr goes back to the agent
  any other non-zero exit          -> a warning only; execution CONTINUES

A guard that signals "block" with exit 1 looks like it works and stops nothing, so these tests drive
the real script in a subprocess with a JSON event on stdin and assert the exit code, stdout and
stderr separately.

No command that trips the guard is written in this file. Once the guard is wired to a hook, a
matching string typed on a command line gets the verification run itself blocked, and rewriting the
sample to slip past the pattern is the bypass the guard exists to prevent. Cases are therefore read
from the guard's own tables at run time. Only the feature-area *names* are written here, because
they are labels, not commands.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

GUARD = Path(__file__).resolve().parent.parent / "scripts" / "guard_irreversible_ops.py"

# The feature areas the guard is documented to cover (AGENTS.md, "Irreversible operations").
# Pinned here and not derived from the guard: a copy that lost an area would lose it from its own
# table too, and a test that iterates that table has nothing left to notice. Adding an area to the
# guard means adding it here, which is the point.
EXPECTED_AREAS = (
    "FSx for ONTAP SnapLock",
    "Snapshot locking / Tamperproof Snapshot",
    "S3 Object Lock",
    "S3 Glacier Vault Lock",
    "AWS Backup Vault Lock",
    "EBS snapshot lock",
    "Terminal / permanently-disabled states",
)


def _load_guard():
    spec = importlib.util.spec_from_file_location("guard_irreversible_ops", GUARD)
    assert spec
    assert spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


guard = _load_guard()


def _run(stdin: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GUARD)],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )


def _run_command(command: str) -> subprocess.CompletedProcess[str]:
    """Invoke the guard exactly as a PreToolUse hook does."""
    return _run(json.dumps({"tool_input": {"command": command}}))


def _verdict_of(command: str) -> str:
    done = _run_command(command)
    if done.returncode == 2:
        return "block"
    if done.returncode == 0 and "permissionDecision" in done.stdout:
        return "ask"
    if done.returncode == 0:
        return "allow"
    return f"invalid(exit={done.returncode})"


def _first_command(want: int) -> str:
    return next(command for w, _d, command in guard.SELFTEST_CASES if w == want)


def _first_ask_command() -> str:
    return next(command for v, _d, command in guard.ASK_CASES if v == "ask")


# ---------------------------------------------------------------- 1. exit-code contract


def test_block_uses_exit_2_and_stderr() -> None:
    done = _run_command(_first_command(2))
    assert done.returncode == 2, "only exit 2 blocks; any other non-zero is a warning"
    assert "BLOCKED" in done.stderr
    assert done.stdout == "", "a block must not also emit a permission decision"


def test_ask_uses_exit_0_and_a_permission_decision() -> None:
    done = _run_command(_first_ask_command())
    assert done.returncode == 0, "asking is exit 0; a non-zero exit would not prompt"
    decision = json.loads(done.stdout)["hookSpecificOutput"]
    assert decision["permissionDecision"] == "ask"
    assert decision["permissionDecisionReason"].strip()
    assert done.stderr == ""


def test_allow_is_silent() -> None:
    done = _run_command(_first_command(0))
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")


def test_no_verdict_ever_uses_exit_1() -> None:
    """Exit 1 is the value that looks like a block and is not one."""
    codes = {
        _run_command(command).returncode
        for _w, _d, command in [*guard.SELFTEST_CASES, *guard.ASK_CASES]
    }
    assert codes <= {0, 2}, f"unexpected exit codes: {sorted(codes - {0, 2})}"


def test_corpus_runs_through_the_real_process() -> None:
    """The in-file tables, executed as a hook would execute them, not just matched."""
    for want, description, command in guard.SELFTEST_CASES:
        expected = "block" if want == 2 else "allow"
        assert _verdict_of(command) == expected, description
    for expected, description, command in guard.ASK_CASES:
        assert _verdict_of(command) == expected, description


def test_corpus_covers_all_three_verdicts() -> None:
    """A table that lost its allow cases would let over-blocking through unnoticed."""
    verdicts = {"block" if w == 2 else "allow" for w, _d, _c in guard.SELFTEST_CASES}
    verdicts |= {v for v, _d, _c in guard.ASK_CASES}
    assert verdicts == {"block", "ask", "allow"}


# ---------------------------------------------------------------- 2. malformed events


@pytest.mark.parametrize(
    "stdin",
    [
        pytest.param("not json at all", id="invalid-json"),
        pytest.param('{"tool_input": {"command": ', id="truncated-json"),
        pytest.param("", id="empty"),
        pytest.param("   \n", id="whitespace-only"),
        pytest.param("{}", id="empty-object"),
        pytest.param('{"tool_name": "execute_bash"}', id="no-command-key"),
        pytest.param('{"tool_input": {}}', id="empty-tool-input"),
        pytest.param('{"tool_input": {"command": ""}}', id="empty-command"),
        pytest.param('{"tool_input": {"command": null}}', id="null-command"),
    ],
)
def test_malformed_event_does_not_stop_ordinary_work(stdin: str) -> None:
    done = _run(stdin)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", ""), (
        "an event the guard cannot read must not block or warn: stopping all work "
        "gets the guard switched off"
    )


def test_unparseable_event_is_still_inspected() -> None:
    """Failing safe: if the JSON is broken, the raw text is treated as the command."""
    done = _run(_first_command(2))
    assert done.returncode == 2
    assert "BLOCKED" in done.stderr


def test_command_under_an_alternate_key_is_still_inspected() -> None:
    """A payload shape the guard did not anticipate must fall back to the whole payload."""
    done = _run(json.dumps({"unexpected_shape": {"nested": _first_command(2)}}))
    assert done.returncode == 2


# ---------------------------------------------------------------- 3. every area has a block case


def test_the_guard_still_lists_every_documented_area() -> None:
    """Catches a copy that dropped an area, which no loop over the guard's own table can."""
    missing = [a for a in EXPECTED_AREAS if a not in guard.IMMUTABILITY_PATTERNS]
    unlisted = [a for a in guard.IMMUTABILITY_PATTERNS if a not in EXPECTED_AREAS]
    assert missing == [], f"areas missing from the guard: {missing}"
    assert unlisted == [], f"areas the test does not know about (add them): {unlisted}"


@pytest.mark.parametrize("area", EXPECTED_AREAS)
def test_every_area_has_a_case_that_blocks(area: str) -> None:
    """A feature area with patterns but no case is an untested claim.

    The case has to match this area specifically and be blocked by the real process. Checking only
    that some case blocks would pass a copy that kept the case and lost the area's patterns.
    """
    blocking = [
        command
        for want, _d, command in guard.SELFTEST_CASES
        if want == 2 and area in guard.find_matches(command)[0]
    ]
    assert blocking, f"no block case reaches the {area!r} area"
    assert any(_verdict_of(command) == "block" for command in blocking), (
        f"the {area!r} area has a case, but the guard no longer blocks it"
    )
