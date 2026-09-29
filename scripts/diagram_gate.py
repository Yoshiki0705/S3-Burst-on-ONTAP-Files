#!/usr/bin/env python3
"""Block on a mislabelled or overlapping diagram right after `build_diagrams.py` writes it.

WHY THIS EXISTS
----------------
Three figures shipped in one PR with defects that no existing gate caught, and all three were
only found because a human opened the PNGs and looked:

* an "AWS Cloud" boundary drawn with the cloud pictogram but captioned as something else
  (`s3burst-two-ceilings`, captioned "FSx for ONTAP file server");
* an icon's own two-line label running past the bottom edge of the group meant to contain it
  (`s3burst-block-c-layout`, the "Amazon FSx for NetApp ONTAP" caption sitting on the border);
* a frame title centred on top of a straight vertical edge that passes through the frame on its
  way to a node below it (`s3burst-block-b-multipath`, "FSx for ONTAP HA pair" under two arrows).

`make diagram-flow` and `make diagram-fonts` both run in `make all`, which is the commit gate — but
`make all` is a step a human or an agent chooses to run, and choosing to run it is exactly the step
that was skipped between "the export looks right in the terminal log" and "the image is correct".
This closes that gap by running the same checks the moment the command that produces the diagram
finishes, before anyone has decided whether to look at the picture.

WHAT THIS DOES
--------------
Reads a Kiro `PostToolUse` hook payload on stdin. When the command that just ran invoked
`build_diagrams.py` with `--write`, runs `tools/check_diagram_flow.py` and
`tools/check_diagram_fonts.py` against the files it just wrote and prints their findings.

This is a `PostToolUse` hook, and Kiro's exit-code contract only lets `PreToolUse` block a call
before it happens — a `PostToolUse` hook cannot undo a write that already landed. So this exits 0
always and instead prints a clearly-marked report to stdout: loud enough that an agent reading the
tool output cannot mistake it for a routine log line, but not a block, because the files are on
disk either way and the only useful next step is fixing them, not preventing an export that has
already occurred.

Exit codes: always 0 (a `PostToolUse` hook cannot block; see above). A non-zero would only hide
this hook's own crash from the report it is supposed to produce.

Run:
  python3 scripts/diagram_gate.py --hook          # read a Kiro hook payload on stdin
  python3 scripts/diagram_gate.py --check         # run the checks directly, for a terminal or CI
  python3 scripts/diagram_gate.py --selftest       # prove the command-matcher fires and does not
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

# Matches the command that writes diagrams, not the one that only checks them (`--check` alone
# implies nothing changed on disk, so there is nothing new to report). `--write` may appear with or
# without `--export`; both write the `.drawio` files these checks read.
BUILD_COMMAND = re.compile(r"\bbuild_diagrams\.py\b.*--write\b")

CHECK_SCRIPTS = ("check_diagram_flow.py", "check_diagram_fonts.py")


def command_from_payload(payload: object) -> str:
    """Best-effort extraction of the shell command from a Kiro hook payload.

    Mirrors `commit_gate.py`'s `message_from_command` lookup shape rather than importing it: the
    two hooks read different keys out of the same family of payloads, and the only shared logic is
    "try a few plausible field names", which is not worth a shared helper for two call sites.
    """
    if not isinstance(payload, dict):
        return ""
    for key in ("command", "input", "toolInput", "arguments"):
        value = payload.get(key)
        if isinstance(value, str):
            return value
        if isinstance(value, dict) and isinstance(value.get("command"), str):
            return value["command"]
    return ""


def run_checks() -> tuple[int, str]:
    """Run both diagram checks and return (combined exit code, combined output)."""
    combined_rc = 0
    parts: list[str] = []
    for name in CHECK_SCRIPTS:
        proc = subprocess.run(
            [sys.executable, str(ROOT / "tools" / name)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        combined_rc = combined_rc or proc.returncode
        parts.append(proc.stdout + proc.stderr)
    return combined_rc, "\n".join(parts)


def run_hook() -> int:
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing to inspect; never block on a payload we cannot read

    command = command_from_payload(payload)
    if not BUILD_COMMAND.search(command):
        return 0

    rc, output = run_checks()
    if rc == 0:
        # Silent on success: a PostToolUse hook that prints on every pass trains the reader to
        # skip its output, which is exactly the habit that let three defects through by eye only.
        return 0

    print(
        "\n=== diagram-gate: build_diagrams.py just wrote a file that fails a diagram check ===",
        file=sys.stdout,
    )
    print(output, file=sys.stdout)
    print(
        "=== Fix the generator in tools/build_diagrams.py and re-run --write before moving on ===\n",
        file=sys.stdout,
    )
    return 0  # PostToolUse cannot block; see module docstring


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--hook", action="store_true", help="read a Kiro hook payload on stdin"
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="run the checks directly and report the exit code",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="prove the command matcher fires on --write and not on --check alone",
    )
    args = parser.parse_args()

    if args.selftest:
        cases = [
            ("python3 tools/build_diagrams.py --write --export", True),
            ("python3 tools/build_diagrams.py --write", True),
            ("python3 tools/build_diagrams.py --check", False),
            ("python3 tools/check_diagram_flow.py", False),
            ("git status", False),
        ]
        failures = 0
        for command, should_match in cases:
            matched = bool(BUILD_COMMAND.search(command))
            if matched != should_match:
                verdict = "matched" if matched else "did not match"
                wanted = "match" if should_match else "not match"
                print(
                    f"  selftest FAILED: {command!r} {verdict}, expected to {wanted}",
                    file=sys.stderr,
                )
                failures += 1
        if failures:
            print(f"selftest: {failures} case(s) failed", file=sys.stderr)
            return 1
        print(f"selftest: {len(cases)} case(s) behave as documented")
        return 0

    if args.hook:
        return run_hook()

    if args.check:
        rc, output = run_checks()
        print(output)
        return rc

    parser.error("give --hook, --check or --selftest")
    return 2


if __name__ == "__main__":
    sys.exit(main())
