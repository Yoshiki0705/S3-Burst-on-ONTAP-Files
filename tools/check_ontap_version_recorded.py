#!/usr/bin/env python3
"""Verify every measurement-conditions table under docs/ja/verification/ records an ONTAP version.

A persona review (2026-09-21, round 2) found that Block C's own measurements span three ONTAP
versions (9.18.1P5 / P6 / 9.18.1) without a single-version guarantee, and that several
measurement tables across the block-protocol series omit the version entirely
(`FileSystemTypeVersion` returning null on FSx for ONTAP, since that field is documented as
Lustre-only). The articles already say so explicitly where it happened; this check makes the same
discipline mechanical going forward, catching a table that silently drops the row rather than
relying on the author noticing.

The rule: any file under docs/ja/verification/ that mentions "ONTAP" in prose must record the
version somewhere in the file -- either as an `| ONTAP | <version> |` row in a measurement-
conditions table, an inline `ONTAP <version>` statement, or an explicit gap note ("記録していない",
"記録できていません", "not recorded", "版を記録"). A file that never mentions ONTAP at all (e.g. a
purely S3-API-side measurement) is out of scope -- it makes no version claim to check.

Exemption for a file-level opt-out, when a document legitimately spans many small notes without
one coherent measurement (rare):

    <!-- ontap-version-exempt-file -->     anywhere in the first 40 lines

Run:  python3 tools/check_ontap_version_recorded.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFICATION_DIR = ROOT / "docs" / "ja" / "verification"

EXEMPT_FILE = "ontap-version-exempt-file"
EXEMPT_SCAN_LINES = 40

# A version string like 9.18.1, 9.18.1P5, 9.15.1, etc.
VERSION_RE = re.compile(r"\b9\.\d{1,2}\.\d(?:P\d+(?:D\d+)?)?\b")

# Explicit gap notes -- recording the absence of a version is itself compliant. Kept broad
# because each article phrases the gap differently ("特定できず", "記録していない", "未確認").
GAP_NOTE_RE = re.compile(
    r"記録していない|記録できていない|記録できていません|版を記録|特定できず|特定できない|"
    r"not recorded|failed to record|version was not recorded"
)

# This check only applies to a file that carries its own measurement-conditions table --
# "| 項目 | 値 |" is the convention this repository already uses (見つけた 15 files のうち全数)。
# A planning doc, a template, a runbook, or an index page references ONTAP in prose without
# stating this file's own measured version, and checking those produces exactly the false
# positives this check must not have: a claim about what *should* be recorded, not what *was*.
CONDITIONS_TABLE_RE = re.compile(r"^\|\s*項目\s*\|\s*値\s*\|", re.MULTILINE)

# A bare mention of "ONTAP" without any nearby version or gap note is what this check flags.
ONTAP_MENTION_RE = re.compile(r"ONTAP")


def scanned_files() -> list[Path]:
    if not VERIFICATION_DIR.is_dir():
        return []
    return sorted(VERIFICATION_DIR.glob("*.md"))


def check() -> list[str]:
    findings: list[str] = []
    for path in scanned_files():
        rel = path.relative_to(ROOT)
        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()

        if any(EXEMPT_FILE in line for line in lines[:EXEMPT_SCAN_LINES]):
            continue

        if not CONDITIONS_TABLE_RE.search(text):
            # No measurement-conditions table of this repository's own convention -- this file
            # is a plan, template, runbook, or index rather than a record of what was measured.
            continue

        if not ONTAP_MENTION_RE.search(text):
            # No ONTAP claim in this file at all -- out of scope.
            continue

        if VERSION_RE.search(text) or GAP_NOTE_RE.search(text):
            continue

        findings.append(
            f"{rel}: has a measurement-conditions table and mentions ONTAP, but records neither "
            f'a version (e.g. `9.18.1P6`) nor an explicit gap note (e.g. "版を記録できていません"). '
            f"Add one of the two, or mark the file with <!-- ontap-version-exempt-file --> if it "
            f"genuinely makes no measurement claim."
        )
    return findings


def main() -> int:
    findings = check()
    if findings:
        print(
            f"ONTAP version recording is missing ({len(findings)} finding(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    files = len(scanned_files())
    print(
        f"ontap-version: {files} file(s) under docs/ja/verification/ checked, each records a version or an explicit gap"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
