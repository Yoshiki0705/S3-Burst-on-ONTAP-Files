"""The pull request title check, executed rather than read.

The rule lives in a shell script embedded in a workflow, so it is the least testable thing in this
repository and the easiest to break silently — a workflow only runs on GitHub, and by then the
feedback is a red pull request. These tests extract the script and run it under bash with the same
environment variables GitHub sets, which means the assertions cover the real logic rather than the
presence of some strings in a YAML file.

The bot exemption is asserted from both sides. A rule that exempts an account is only sound while a
human cannot borrow the exemption, so the test that matters is the one where a human uses a bot's
title.
"""

from __future__ import annotations

import re
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
WORKFLOW = ROOT / ".github" / "workflows" / "pr-title-check.yml"

BOTS = ("renovate[bot]", "dependabot[bot]", "github-actions[bot]", "pre-commit-ci[bot]")


def script() -> str:
    """Extract the `run: |` block from the validation step."""
    text = WORKFLOW.read_text(encoding="utf-8")
    match = re.search(r"^ +run: \|\n(?P<body>(?:.*\n)+?)(?=^\S|\Z)", text, re.M)
    assert match, "could not find the run: | block in the workflow"
    return textwrap.dedent(match.group("body"))


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
    assert not re.search(r"^\s+if:", text, re.M), (
        "the workflow gained a conditional; exempt bots inside the script with exit 0 instead, "
        "so the check reports success rather than skipped"
    )
