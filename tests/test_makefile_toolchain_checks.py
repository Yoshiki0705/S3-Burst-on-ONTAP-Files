"""A gate must tell a tool that cannot run apart from one at the wrong version, and a scan that
could not run apart from one that found nothing.

Both were the same defect. A pipeline's exit status is its *last* command's, so the status of the
command that matters is discarded:

    installed=$(ruff --version | awk '{print $2}')

`awk` succeeds on empty input, so a ruff that is installed but cannot run -- a missing shared
library is the usual cause -- yielded an empty version, reached the pin comparison, and printed:

    warning: ruff  installed, this repository pins 0.15.20.
             ... Install the pinned version: pip install -r requirements-dev.txt

The gate still failed, because `ruff check` ran next and failed too, so this was never a hole in the
verdict. It was a hole in the diagnosis: the double space is the empty version, and the remedy named
cannot fix a broken install. The first line printed is the one that gets read.

These tests drive the real Makefile targets through a stub binary, because the defect is in the
recipe's shell. A test that reimplemented the same logic in Python could not reach it.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"
REQUIREMENTS = ROOT / "requirements-dev.txt"

# Both recipes carry their own copy of this shell, so every behavioural case is parametrised over
# the two of them. A fix applied to one and not the other is the drift this catches.
TOOLS = [("python", "RUFF", "ruff"), ("zizmor", "ZIZMOR", "zizmor")]


def _pinned(tool: str) -> str:
    match = re.search(rf"^{tool}==(.+)$", REQUIREMENTS.read_text(), re.MULTILINE)
    assert match, f"{tool} is not pinned in requirements-dev.txt"
    return match.group(1).strip()


def _stub(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + textwrap.dedent(body))
    path.chmod(0o755)
    return path


def _make(target: str, **variables: str) -> subprocess.CompletedProcess:
    command = ["make", target, *(f"{key}={value}" for key, value in variables.items())]
    return subprocess.run(
        command, cwd=ROOT, capture_output=True, text=True, check=False
    )


@pytest.mark.parametrize(("target", "variable", "tool"), TOOLS)
def test_a_tool_that_does_not_run_is_not_reported_as_a_version_mismatch(
    tmp_path: Path, target: str, variable: str, tool: str
) -> None:
    stub = _stub(
        tmp_path,
        "broken",
        """
        echo "dyld: Library not loaded: libpython3.12.dylib" >&2
        exit 1
        """,
    )
    result = _make(target, **{variable: str(stub)})
    combined = result.stdout + result.stderr

    assert result.returncode != 0, (
        f"a broken {variable} must fail the gate:\n{combined}"
    )
    assert "is present but does not run" in combined, combined
    # The point of the fix: the old message named the version pin, which cannot be the remedy.
    assert f"this repository pins {_pinned(tool)}" not in combined, (
        f"a broken binary must not be reported as a version mismatch:\n{combined}"
    )
    # stderr is deliberately not suppressed: the binary's own message is the useful part.
    assert "dyld: Library not loaded" in combined, combined


@pytest.mark.parametrize(("target", "variable", "tool"), TOOLS)
def test_a_tool_that_reports_no_version_is_refused(
    tmp_path: Path, target: str, variable: str, tool: str
) -> None:
    stub = _stub(tmp_path, "silent", "exit 0\n")
    result = _make(target, **{variable: str(stub)})
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "reported no version" in combined, combined


@pytest.mark.parametrize(("target", "variable", "tool"), TOOLS)
def test_a_real_version_mismatch_still_names_both_versions(
    tmp_path: Path, target: str, variable: str, tool: str
) -> None:
    stub = _stub(tmp_path, "old", f'echo "{tool} 0.9.9"\n')
    result = _make(target, **{variable: str(stub)})
    combined = result.stdout + result.stderr

    assert "0.9.9" in combined, f"the installed version must be named:\n{combined}"
    assert _pinned(tool) in combined, f"the pinned version must be named:\n{combined}"
    assert "is present but does not run" not in combined, combined


@pytest.mark.parametrize(("target", "variable", "tool"), TOOLS)
def test_the_pinned_version_produces_no_warning(
    tmp_path: Path, target: str, variable: str, tool: str
) -> None:
    stub = _stub(tmp_path, "pinned", f'echo "{tool} {_pinned(tool)}"\n')
    result = _make(target, **{variable: str(stub)})
    combined = result.stdout + result.stderr

    assert "warning:" not in combined, (
        f"the pinned version must warn about nothing:\n{combined}"
    )
    assert "does not run" not in combined, combined


RECIPE = re.compile(r"^\t")
# Deliberately narrow. A general "no pipe in any recipe" check was written first and rejected: of
# the five pipe-like matches in this Makefile, two are correct code. `help` pipes into awk for column
# formatting, where the exit status is irrelevant, and `new-pattern` contains
# `(collect | serve | pipelines)` inside a quoted string, which is not a pipeline at all. The sibling
# repository's equivalent test misfired on `||` for the same reason -- a pattern coarse enough to
# catch every shape also condemns correct code, and a check that cries wolf gets switched off.
#
# Narrow cuts the other way too. The first attempt here was `\$\$\([^)]*--version[^)]*\|`, scoped to
# a command substitution, and it matched nothing: the tool is named by a make variable, so the line
# reads `$$($(RUFF) --version | awk ...)` and `[^)]*` cannot cross the `)` of `$(RUFF)`. Reverting
# the recipe showed the behavioural tests failing while this one still passed -- narrow enough to
# avoid the false positives, and narrow enough to miss the defect it exists for. `(?!\|)` keeps `||`
# out without reintroducing that blindness.
VERSION_THROUGH_A_PIPE = re.compile(r"--version[^|\n]*\|(?!\|)")


def test_no_recipe_reads_a_version_through_a_pipe() -> None:
    offenders = [
        (number, line.rstrip())
        for number, line in enumerate(MAKEFILE.read_text().splitlines(), start=1)
        if RECIPE.match(line) and VERSION_THROUGH_A_PIPE.search(line)
    ]
    assert not offenders, (
        "a version read through a pipe takes the status of the last command, so a tool that "
        "cannot run yields an empty version and is reported as a mismatch:\n"
        + "\n".join(f"  Makefile:{number}: {line}" for number, line in offenders)
    )


# --- a scan that fails, versus a scan that finds nothing --------------------------------------
#
# The same discarded-status shape, with a worse consequence. `make terraform` read:
#
#     roots=$(find environments -name '*.tf' -exec dirname {} \; 2>/dev/null | sort -u)
#
# `sort` succeeds on empty input, so a missing or unreadable `environments/` produced an empty list,
# which the recipe reported as "terraform: no .tf files yet" and **passed**. `make cfn` had the same
# hole by a different route: it did not pipe, but it discarded `find`'s status all the same by
# testing only whether the output was empty.
#
# `AGENTS.md` already required the opposite -- "A count of zero is reported as a broken reader, not
# as 'none yet'" -- and `tools/check_derived_counts.py` implements it. The rule was written for prose
# counts, so two shell recipes contradicted a rule this repository had already put in writing.


def _isolated(tmp_path: Path) -> Path:
    """A copy of the Makefile in an empty directory, so its relative paths resolve to nothing.

    Nothing is stubbed here: these cases assert the real scan's failure handling.
    """
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    shutil.copy(MAKEFILE, workspace / "Makefile")
    shutil.copy(REQUIREMENTS, workspace / "requirements-dev.txt")
    return workspace


@pytest.mark.parametrize(
    ("target", "tool"),
    [("cfn", "cfn-lint"), ("terraform", "terraform")],
)
def test_a_scan_that_cannot_run_is_not_reported_as_nothing_to_check(
    tmp_path: Path, target: str, tool: str
) -> None:
    if shutil.which(tool) is None:
        pytest.skip(f"{tool} is not installed, so the recipe skips before it scans")

    result = subprocess.run(
        ["make", target],
        cwd=_isolated(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0, (
        f"a failed scan must not pass; before the fix this printed 'no ... yet' and exited 0:"
        f"\n{combined}"
    )
    assert "scan" in combined and "failed" in combined, combined
    assert "yet" not in combined, (
        f"'yet' frames a scan that could not run as an empty one:\n{combined}"
    )


def test_finding_no_terraform_file_is_treated_as_a_scan_that_stopped_matching(
    tmp_path: Path,
) -> None:
    if shutil.which("terraform") is None:
        pytest.skip("terraform is not installed, so the recipe skips before it scans")

    workspace = _isolated(tmp_path)
    # The directory exists and is readable, so `find` succeeds and returns nothing. This is the case
    # the old recipe reported as "terraform: no .tf files yet", and passed.
    (workspace / "environments").mkdir()

    result = subprocess.run(
        ["make", "terraform"],
        cwd=workspace,
        capture_output=True,
        text=True,
        check=False,
    )
    combined = result.stdout + result.stderr

    assert result.returncode != 0, combined
    assert "none yet" in combined, combined


# --- output that does not depend on being watched ---------------------------------------------

WORKFLOWS = ROOT / ".github" / "workflows"
# Matches an invocation that runs the audit, in a recipe or in a workflow `run:`. Keyed on
# `--no-online-audits` rather than on the tool's name: the Makefile calls it through `$(ZIZMOR)`, so
# a case-sensitive `\bzizmor\b` matched the workflow only and found one invocation where there are
# two. That is the third pattern in this file to miss what it was aimed at, which is why the
# assertion below also checks the count -- a pattern that quietly matches less than it should still
# satisfies every "all matches carry the flag" test.
ZIZMOR_AUDIT = re.compile(r"^[^#\n]*--no-online-audits.*$", re.MULTILINE)


def _zizmor_audit_invocations() -> list[tuple[str, str]]:
    sources = [(MAKEFILE.name, MAKEFILE.read_text())]
    sources += [
        (path.name, path.read_text()) for path in sorted(WORKFLOWS.glob("*.yml"))
    ]
    return [
        (name, match.group(0).strip())
        for name, text in sources
        for match in ZIZMOR_AUDIT.finditer(text)
    ]


def test_every_zizmor_invocation_suppresses_the_progress_bar() -> None:
    """Without `--no-progress`, zizmor draws a progress bar when its output is a terminal.

    Measured on this repository's five workflow files: 23,043 bytes and 225 carriage returns on a
    pty, against 850 bytes with the flag. It is suppressed automatically when the output is
    redirected, which is the trap -- the gate's output differed depending on whether anyone was
    watching it, so what a contributor saw and what a log recorded were not the same text. The flag
    makes the two identical rather than merely shorter.

    Both call sites are asserted because the Makefile and the workflow invoke zizmor separately, and
    a flag added to one is a difference between what a contributor runs and what CI runs.
    """
    invocations = _zizmor_audit_invocations()
    assert len(invocations) >= 2, (
        f"expected the Makefile recipe and the workflow step; found {invocations}"
    )
    missing = [
        (where, line) for where, line in invocations if "--no-progress" not in line
    ]
    assert not missing, (
        "these zizmor invocations still draw a progress bar:\n"
        + "\n".join(f"  {where}: {line}" for where, line in missing)
    )
