"""The pull request title and commit subject checks, executed rather than read.

The rules live in shell scripts embedded in a workflow, so they are the least testable thing in this
repository and the easiest to break silently — a workflow only runs on GitHub, and by then the
feedback is a red pull request. These tests pull each script out of the YAML and run it under bash
with the same environment variables GitHub sets, which means the assertions cover the real logic
rather than the presence of some strings in a file.

**The scripts are located by parsing the YAML, not by matching text.** An earlier version used a
regular expression that assumed one job. Adding a second job made the pattern swallow both scripts
into one, and the tests failed with exit status 127 from a command that was never meant to be in
scope — a failure that says nothing about the rule it was testing.

The bot exemption is asserted from both sides. A rule that exempts an account is only sound while a
human cannot borrow the exemption, so the test that matters is the one where a human uses a bot's
title.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "pr-title-check.yml"

BOTS = ("renovate[bot]", "dependabot[bot]", "github-actions[bot]", "pre-commit-ci[bot]")


def script(job: str = "title") -> str:
    """The `run:` body of the named job's validation step, read as YAML rather than matched.

    Parsing means a new job cannot silently extend the extracted script, which is what happened when
    this was a regular expression.
    """
    doc = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    steps = doc["jobs"][job]["steps"]
    bodies = [step["run"] for step in steps if "run" in step]
    assert len(bodies) == 1, (
        f"job {job} has {len(bodies)} run steps; expected exactly 1"
    )
    return bodies[0]


def run(title: str, author: str = "Yoshiki0705") -> subprocess.CompletedProcess:
    return subprocess.run(
        ["bash", "-c", script()],
        env={
            "PR_TITLE": title,
            "PR_AUTHOR": author,
            "PATH": "/usr/bin:/bin:/usr/local/bin",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


# --- the extraction itself ----------------------------------------------------------------------


def test_the_script_was_extracted() -> None:
    """If the regex stops matching, every test below would silently exercise an empty script."""
    body = script()
    assert "pattern=" in body
    assert "PR_AUTHOR" in body
    assert len(body.splitlines()) > 10


# --- humans -------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "title",
    [
        "docs: separate the two S3-over-files mechanisms",
        "feat(collect): add the S3 access point ingest pattern",
        "ci: exempt known bots from the title convention",
        "bench: record the first visibility measurement",
    ],
)
def test_a_conventional_title_passes(title: str) -> None:
    assert run(title).returncode == 0


@pytest.mark.parametrize(
    "title",
    [
        "update the readme",
        "Docs: capitalised type",
        "feature: not an allowed type",
        "docs:missing space",
        "Configure Renovate",
    ],
)
def test_a_non_conventional_title_fails_for_a_human(title: str) -> None:
    proc = run(title)
    assert proc.returncode == 1
    assert "conventional commits" in proc.stdout


def test_an_overlong_title_fails() -> None:
    proc = run("docs: " + "x" * 80)
    assert proc.returncode == 1
    assert "under 70" in proc.stdout


def test_a_title_at_the_limit_passes() -> None:
    title = "docs: " + "x" * (70 - len("docs: ") - 1)
    assert len(title) == 69
    assert run(title).returncode == 0


# --- bots ---------------------------------------------------------------------------------------


@pytest.mark.parametrize("bot", BOTS)
def test_a_known_bot_is_exempt(bot: str) -> None:
    """Renovate's onboarding title cannot be renamed before the check runs."""
    proc = run("Configure Renovate", author=bot)
    assert proc.returncode == 0
    assert "known bot" in proc.stdout


@pytest.mark.parametrize("bot", BOTS)
def test_a_bot_with_a_conventional_title_also_passes(bot: str) -> None:
    """Renovate's ongoing pull requests look like this, so the exemption rarely does any work."""
    assert (
        run("chore(deps): update actions/checkout digest", author=bot).returncode == 0
    )


def test_a_human_cannot_borrow_a_bot_title() -> None:
    """The exemption is keyed on the account. Keying it on the title would be trivially bypassed."""
    proc = run("Configure Renovate", author="Yoshiki0705")
    assert proc.returncode == 1


def test_a_lookalike_account_is_not_exempt() -> None:
    """`renovate` and `renovate[bot]` are different accounts; only the app is exempt."""
    for impostor in ("renovate", "renovate-bot", "dependabot", "Renovate[bot]"):
        assert run("Configure Renovate", author=impostor).returncode == 1, impostor


# --- the job must pass, not skip -----------------------------------------------------------------


def test_the_job_is_not_conditionally_skipped() -> None:
    """A skipped check is not a passing check.

    Exempting bots with a job-level `if:` would report "skipped", which blocks a bot pull request
    the moment this becomes a required status check — the opposite of the intent.
    """
    text = WORKFLOW.read_text(encoding="utf-8")
    assert not re.search(r"^\s+if:", text, re.MULTILINE), (
        "the workflow gained a conditional; exempt bots inside the script with exit 0 instead, "
        "so the check reports success rather than skipped"
    )


# --- the commit subjects ---------------------------------------------------------------------------
#
# **The title is not what lands.** A squash merge with a single commit to squash takes that commit's
# subject, not the pull request title. On 2026-09-11 a `verify:` subject reached `main` that way while
# the title job was green, so the subjects are checked too.


def run_commits(
    subjects: list[str], author: str = "Yoshiki0705"
) -> subprocess.CompletedProcess:
    """Run the commit-subject script with `git log` stubbed out.

    The real script reads history between two SHAs. Building a repository per case would test git
    rather than the rule, so `git` is replaced by a stub on PATH that prints the subjects given here.
    """
    import stat
    import tempfile

    tmp = tempfile.mkdtemp()
    stub = Path(tmp) / "git"
    lines = "\n".join(f"abc1234 {s}" for s in subjects)
    stub.write_text(f"#!/bin/sh\ncat <<'EOF'\n{lines}\nEOF\n")
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    return subprocess.run(
        ["bash", "-c", script("commits")],
        env={
            "BASE_SHA": "aaa",
            "HEAD_SHA": "bbb",
            "PR_AUTHOR": author,
            "PATH": f"{tmp}:/usr/bin:/bin:/usr/local/bin",
        },
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_conventional_subjects_pass() -> None:
    proc = run_commits(
        ["docs: record the measurement", "fix(collect): handle an empty response"]
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_a_non_conventional_subject_fails() -> None:
    """This is the case that reached `main`: the title was fixed, the commit was not."""
    proc = run_commits(["verify: fetch an object larger than 50 GiB"])
    assert proc.returncode == 1
    assert "conventional commits" in proc.stdout
    assert "not from the pull request title" in proc.stdout


def test_one_bad_subject_among_good_ones_fails() -> None:
    proc = run_commits(["docs: fine", "wip", "fix: also fine"])
    assert proc.returncode == 1


def test_an_overlong_subject_fails() -> None:
    proc = run_commits(["docs: " + "x" * 80])
    assert proc.returncode == 1
    assert "under 72" in proc.stdout


@pytest.mark.parametrize("bot", BOTS)
def test_a_known_bot_is_exempt_from_the_subject_rule(bot: str) -> None:
    assert run_commits(["Configure Renovate"], author=bot).returncode == 0


def test_both_jobs_use_the_same_type_list() -> None:
    """Two copies of the allowed types would drift. Assert they are identical."""
    types = []
    for job in ("title", "commits"):
        match = re.search(r"pattern='\^\((?P<types>[a-z|]+)\)", script(job))
        assert match, f"no pattern= line in job {job}"
        types.append(match.group("types"))
    assert types[0] == types[1], f"the allowed types differ: {types[0]} vs {types[1]}"
