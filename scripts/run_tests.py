#!/usr/bin/env python3
"""Discover every test directory and run each in its own pytest process.

Two failure modes from the sibling repository `FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns` are designed out
here rather than inherited.

**A hand-maintained list of test directories drifts.** That repository kept one list in its
Makefile and another in its CI workflow. They disagreed — CI named 37 directories, the Makefile
reached 16, and 13 directories holding roughly 790 passing tests were in neither, so those tests
ran nowhere. The fix there was a shared manifest file; the fix here is not to keep a list at all.
Directories are discovered from the filesystem, so a new pattern's tests run the first time
somebody types `make test`.

**One pytest process cannot load several patterns at once.** Patterns each ship their own
`functions/` package. Collecting two of them in a single run means the second import of
`functions.<name>` resolves to whatever `sys.modules` cached from the first, and the failure
surfaces as an unrelated `ModuleNotFoundError`. One process per directory is therefore a
correctness requirement, not a preference.

A directory that exists but holds no `test_*.py` is reported and skipped: pytest exits 5 on an
empty collection, which under `set -e` fails the whole run and teaches people to stop running it.
Finding *no* directories at all is a hard failure, because at that point the discovery expression
has broken and a run that examines nothing looks exactly like a run that passed.

Run:  python3 scripts/run_tests.py [-- extra pytest args]
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Where test directories may live. Globs are resolved at run time; nothing is enumerated.
TEST_DIR_GLOBS = ("tests", "shared/tests", "patterns/*/*/tests")


def discover() -> tuple[list[Path], list[Path]]:
    """Return (directories holding tests, directories that exist but hold none)."""
    populated: list[Path] = []
    empty: list[Path] = []
    seen: set[Path] = set()
    for pattern in TEST_DIR_GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            if not path.is_dir() or path in seen:
                continue
            if any(part.startswith("_") for part in path.relative_to(ROOT).parts):
                continue
            seen.add(path)
            if any(path.glob("test_*.py")):
                populated.append(path)
            else:
                empty.append(path)
    return populated, empty


def main() -> int:
    extra = sys.argv[1:]
    populated, empty = discover()

    for path in empty:
        print(f"skip {path.relative_to(ROOT)}: no test_*.py yet")

    if not populated:
        print(
            "no test directories found; the discovery globs in scripts/run_tests.py have "
            "stopped matching, so this run proved nothing",
            file=sys.stderr,
        )
        return 1

    failed: list[str] = []
    for path in populated:
        rel = path.relative_to(ROOT)
        print(f"==> pytest {rel}")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", str(path), "-q", *extra], cwd=ROOT
        )
        if proc.returncode != 0:
            failed.append(str(rel))

    if failed:
        print(f"\nfailed in: {', '.join(failed)}", file=sys.stderr)
        return 1

    print(f"\ntests: {len(populated)} directory/directories passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
