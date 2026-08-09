#!/usr/bin/env python3
"""Verify that every count written in prose still matches what is on disk.

Adapted from the count-claim mechanism in the sibling repository
`fsxn-s3ap-serverless-patterns` (`scripts/check_portal_drift.py`, `_templates_under` /
`_COUNTED_IN_PROSE` / `check_count_claims`). Divergences: the pattern axes are this repository's
three (`collect` / `serve` / `pipelines`) rather than that repository's six solution families; test
and Lambda counts are not carried over because there is nothing here yet to count; and the glob
list starts with every file that could hold a count instead of growing to include them later. In
the original, `solutions/README.md` sat outside the glob list and drifted to `43` while disk held a
different number — the check was real and simply was not looking at that file.

The rule this enforces: a number that can be derived at runtime is not written down. When prose
does state one anyway — and sometimes a sentence reads better with the figure in it — the figure is
checked against the filesystem rather than trusted.

A zero count is reported as a broken reader, not as "no patterns yet". If prose claims a number and
the counter returns zero, the likelier explanation is that a directory moved and the glob stopped
matching. Silence in that case is the failure mode this whole check exists to prevent.

Exemptions, for prose where a digit next to the subject is not a claim about the repository:

    <!-- counts-exempt-file -->     anywhere in the first 40 lines
    ... some sentence ...           <!-- counts-exempt-line -->

Run:  python3 tools/check_derived_counts.py [--list]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PATTERN_AXES = ("collect", "serve", "pipelines")

EXEMPT_FILE = "counts-exempt-file"
EXEMPT_LINE = "counts-exempt-line"
EXEMPT_SCAN_LINES = 40

# Files that may state a count. Everything that could hold one is listed from the start.
COUNT_GLOBS = [
    "README.md",
    "AGENTS.md",
    "llms.txt",
    "CONTRIBUTING.md",
    "docs/ja/**/*.md",
    "docs/en/**/*.md",
    "patterns/*/*/README.md",
    "environments/**/*.md",
    # Drafts are where numbers get quoted out of context on the way to being published, so they are
    # checked before they leave rather than after.
    "drafts/**/*.md",
]


def _templates_under(*relative: str) -> int:
    """Pattern directories under `relative`, counted by their template.yaml.

    One template is one deployable pattern, which is the unit the prose counts. Counting
    directories instead would include scaffolding that is not deployable.
    """
    total = 0
    for part in relative:
        base = ROOT / part
        if not base.is_dir():
            continue
        total += sum(1 for _ in base.glob("*/template.yaml"))
    return total


def _claim_regex(subject: str) -> re.Pattern[str]:
    """Match a count next to `subject` in any of the orders Japanese and English prose use.

    Japanese puts the number first with an optional counter word ("3 つの収集パターン"); English
    also puts it first ("3 collect patterns"); both sometimes trail it in brackets or after a
    colon ("収集パターン（3）", "Collect patterns: 3").
    """
    return re.compile(
        rf"(?:(\d+)\s*(?:\*\*\s*)?(?:個|件|つ|つの)?\s*(?:の)?\s*{subject}"
        rf"|{subject}\s*[（(]\s*(\d+)"
        rf"|{subject}\s*[:：]\s*(\d+))",
        re.IGNORECASE,
    )


COUNT_CLAIMS: list[dict] = [
    {
        "name": "collect-patterns",
        "regex": _claim_regex(r"(?:収集パターン|collect patterns?)"),
        "count": lambda: _templates_under("patterns/collect"),
        "source": "patterns/collect/*/template.yaml",
    },
    {
        "name": "serve-patterns",
        "regex": _claim_regex(r"(?:配布パターン|serve patterns?)"),
        "count": lambda: _templates_under("patterns/serve"),
        "source": "patterns/serve/*/template.yaml",
    },
    {
        "name": "pipeline-patterns",
        "regex": _claim_regex(r"(?:パイプラインパターン|pipeline patterns?)"),
        "count": lambda: _templates_under("patterns/pipelines"),
        "source": "patterns/pipelines/*/template.yaml",
    },
    {
        "name": "patterns-total",
        "regex": _claim_regex(r"(?:実装パターン|patterns in total|total patterns?)"),
        "count": lambda: _templates_under(
            *(f"patterns/{axis}" for axis in PATTERN_AXES)
        ),
        "source": "patterns/{collect,serve,pipelines}/*/template.yaml",
    },
]


def scanned_files() -> list[Path]:
    found: list[Path] = []
    for pattern in COUNT_GLOBS:
        if any(char in pattern for char in "*?["):
            found.extend(sorted(ROOT.glob(pattern)))
        else:
            path = ROOT / pattern
            if path.is_file():
                found.append(path)
    # A glob and a literal can name the same file; keep first occurrence only.
    return list(dict.fromkeys(found))


def claimed_numbers(match: re.Match[str]) -> str | None:
    for group in match.groups():
        if group:
            return group
    return None


def check() -> list[str]:
    findings: list[str] = []
    expected = {claim["name"]: claim["count"]() for claim in COUNT_CLAIMS}

    for path in scanned_files():
        rel = path.relative_to(ROOT)
        lines = path.read_text(encoding="utf-8").splitlines()
        if any(EXEMPT_FILE in line for line in lines[:EXEMPT_SCAN_LINES]):
            continue
        for lineno, line in enumerate(lines, start=1):
            if EXEMPT_LINE in line:
                continue
            for claim in COUNT_CLAIMS:
                match = claim["regex"].search(line)
                if not match:
                    continue
                stated = claimed_numbers(match)
                if stated is None:
                    continue
                actual = expected[claim["name"]]
                if actual == 0:
                    findings.append(
                        f"{rel}:{lineno}: states {stated} for {claim['name']} but "
                        f"{claim['source']} counted zero, which means the pattern that reads the "
                        f"implementation has stopped matching it"
                    )
                elif int(stated) != actual:
                    findings.append(
                        f"{rel}:{lineno}: states {stated} for {claim['name']}, "
                        f"{claim['source']} counts {actual}"
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="print the derived counts and exit"
    )
    args = parser.parse_args()

    if args.list:
        for claim in COUNT_CLAIMS:
            print(f"{claim['name']:<18} {claim['count']():>4}  ({claim['source']})")
        return 0

    findings = check()
    if findings:
        print(f"Count claims are stale ({len(findings)} finding(s)):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\n  Prefer removing the number and linking to the directory. When the sentence "
            "genuinely needs it, correct it here — the filesystem is the source.",
            file=sys.stderr,
        )
        return 1

    files = len(scanned_files())
    print(f"counts: {files} file(s) scanned, every stated count matches the filesystem")
    return 0


if __name__ == "__main__":
    sys.exit(main())
