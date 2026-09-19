"""Every flag a script accepts is reachable through the Makefile target that documents it.

WHY THIS EXISTS

`scripts/preflight.py post` grew a `--smb-svm` flag, and the Makefile recipe was not updated. The
flag existed, the documentation referred to the `make` target, and `make preflight-post SMB_SVM=...`
**silently ignored it** -- a variable make has never heard of is not an error. So the check that was
added to stop an SMB measurement being taken on the single-channel path was unreachable from the
only entry point the guides mention.

That is the same shape as the failure the preflight script was written for: a gate only covers the
route it sits on. Here the route was the Makefile.

The test compares the optional flags each script declares against the flags its target passes. It
does not require every flag to be wired -- some are deliberately not, and those are listed with the
reason -- but an unlisted, unwired flag fails.

Run:  python3 -m pytest tests/test_makefile_flag_coverage.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "Makefile"

# target -> (script, subcommand or None)
WIRED = {
    "preflight-pre": ("scripts/preflight.py", "pre"),
    "preflight-post": ("scripts/preflight.py", "post"),
    "sweep": ("scripts/sweep_after_teardown.py", None),
}

# Flags deliberately absent from a target, with the reason.
EXEMPT = {
    # Positional-free and always on: the target passes --region from REGION.
    "--region",
    "--help",
    # The sweep's recovery window has a sensible default and no failure mode worth a variable.
    "--secret-recovery-days",
}


def recipe(target: str) -> str:
    text = MAKEFILE.read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:.*?\n((?:\t.*\n)+)", text, re.MULTILINE)
    assert match, f"no recipe found for {target}"
    return match.group(1)


def declared_flags(script: str, subcommand: str | None) -> set[str]:
    argv = [sys.executable, str(ROOT / script)]
    if subcommand:
        argv.append(subcommand)
    argv.append("--help")
    out = subprocess.run(argv, capture_output=True, text=True, cwd=ROOT).stdout
    return set(re.findall(r"(--[a-z][a-z0-9-]+)", out))


def test_every_flag_is_reachable_through_its_make_target() -> None:
    problems: list[str] = []
    for target, (script, subcommand) in WIRED.items():
        body = recipe(target)
        for flag in sorted(declared_flags(script, subcommand) - EXEMPT):
            if flag not in body:
                problems.append(
                    f"{target}: {script} accepts {flag}, the recipe never passes it"
                )
    assert not problems, (
        "a flag unreachable from the documented entry point is a flag nobody runs: "
        + "; ".join(problems)
    )


def test_the_exempt_list_is_not_load_bearing_for_a_real_gap() -> None:
    """The exemptions must name flags that exist, so the list cannot hide a rename."""
    every = set()
    for script, subcommand in WIRED.values():
        every |= declared_flags(script, subcommand)
    stale = [flag for flag in EXEMPT if flag not in every and flag != "--help"]
    assert not stale, f"exempted flags that no script declares any more: {stale}"
