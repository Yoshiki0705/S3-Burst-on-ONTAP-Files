#!/usr/bin/env python3
"""Enumerate the input Technical Reports and confirm the total and the absence of duplicates.

This is the first gate of the TR reading procedure (design: TR 読み込み方針 > 読み込み手順, step 1),
run before the scope ledger is written. It only lists the PDFs and checks two things about the set:
that there are exactly `EXPECTED_TR_COUNT` of them, and that no filename repeats. Reading the body
of any report is a later task; this file never opens a PDF.

The behaviour on a problem is the one the design fixes under Error Handling: a mismatch or a
duplicate does not raise. `check()` returns a list of findings and leaves the enumeration it already
built in place, so the caller holds the recorded result rather than losing it to an exception. An
empty list means the set is sound.

A count of zero is treated as a broken reader, not as "no reports yet" -- the same rule the derived
counts checker follows. If the directory is empty or absent, the likelier explanation is that the
input moved, and reporting silence there is the failure this gate exists to prevent.

The input directory is a parameter, not a constant baked into the logic. `DEFAULT_TR_DIR` is the
operator's path; `check()` and `enumerate_pdfs()` take `tr_dir` so a test can point them at a
throwaway directory holding 18, 17, 19 or duplicate-named files.

Run:  python3 tools/check_tr_inventory.py [--tr-dir PATH] [--list]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# The operator's input directory. Not hardcoded into the checks -- it is the default argument of the
# functions below, overridable on the command line and in tests, so the logic never depends on it.
DEFAULT_TR_DIR = Path.home() / "Downloads" / "ontap-technical-reports"

# The agreed size of the input set (requirement 1.5). A number that is the subject of the check, so
# it is named once here rather than written into each message.
EXPECTED_TR_COUNT = 18


def enumerate_pdfs(tr_dir: Path) -> list[Path]:
    """Every `*.pdf` directly under `tr_dir`, sorted by name.

    Sorted so the enumeration is stable between runs and a duplicate pair is adjacent in any listing.
    Non-recursive: the input is a flat directory of reports, and descending into a subdirectory would
    silently change what the count means.
    """
    if not tr_dir.is_dir():
        return []
    return sorted(path for path in tr_dir.glob("*.pdf") if path.is_file())


def duplicate_names(pdfs: list[Path]) -> list[str]:
    """Filenames that appear more than once, in first-seen order.

    `glob` on a case-insensitive filesystem will not list the same path twice, but two reports whose
    names differ only by directory casing, or a listing assembled from more than one source, can
    still collide on `name`. The check is on the filename because that is the identity the scope
    ledger records.
    """
    seen: dict[str, int] = {}
    for pdf in pdfs:
        seen[pdf.name] = seen.get(pdf.name, 0) + 1
    return [name for name, count in seen.items() if count > 1]


def check(tr_dir: Path = DEFAULT_TR_DIR) -> list[str]:
    """Return the findings for `tr_dir`; an empty list means the input set is sound.

    Does not raise on a mismatch or a duplicate. The caller keeps whatever enumeration this built --
    the design calls for holding the recorded result and presenting the error, not discarding it.
    """
    findings: list[str] = []
    pdfs = enumerate_pdfs(tr_dir)
    total = len(pdfs)

    if total != EXPECTED_TR_COUNT:
        if total == 0:
            findings.append(
                f"{tr_dir}: no .pdf found. The input is a tracked set of {EXPECTED_TR_COUNT} "
                f"reports, so zero means this enumeration stopped matching -- the directory moved "
                f"or is absent -- not that there is nothing to read"
            )
        else:
            findings.append(
                f"{tr_dir}: enumerated {total} report(s), expected {EXPECTED_TR_COUNT}. "
                f"Recording of the scope judgements is halted; the enumeration above is retained"
            )

    duplicates = duplicate_names(pdfs)
    for name in sorted(duplicates):
        findings.append(
            f"{tr_dir}: filename {name!r} appears more than once. Each report is one row in the "
            f"scope ledger, so a repeated filename cannot be recorded unambiguously"
        )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tr-dir",
        type=Path,
        default=DEFAULT_TR_DIR,
        help=f"input directory of TR PDFs (default: {DEFAULT_TR_DIR})",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="print the enumerated filenames and exit",
    )
    args = parser.parse_args()

    if args.list:
        for pdf in enumerate_pdfs(args.tr_dir):
            print(pdf.name)
        return 0

    findings = check(args.tr_dir)
    if findings:
        print(
            f"TR inventory gate: recording halted ({len(findings)} finding(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    count = len(enumerate_pdfs(args.tr_dir))
    print(
        f"TR inventory: {count} report(s), the expected total, no duplicate filenames"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
