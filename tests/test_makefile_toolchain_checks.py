"""A toolchain gate must tell a broken tool apart from a mismatched one.

A pipeline's exit status is its *last* command's, so the status of the command that matters is
discarded:

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
