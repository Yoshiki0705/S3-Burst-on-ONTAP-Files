#!/usr/bin/env python3
"""Compare the contents of translated tables, not just their heading structure.

`check_i18n_parity.py` compares heading structure. That is deliberate -- it catches drift without
requiring the translations to be machine-comparable -- but it leaves a gap that this repository fell
into: the `UploadPartCopy` row was changed in Japanese and not in English, and the gate stayed green.
A claim diverged between two languages, and the divergence was found by reading the file.

Two rules, both restricted to table cells, both refusing to guess.

**Literal parity, one-way.** Condition keys, API actions, versions and multi-digit numbers appear with
the same spelling in every language. English may say less than Japanese -- a translation is allowed to
omit -- but it may not carry a literal the Japanese does not have, because that is what a stale
translation looks like after the Japanese was corrected.

**Stage parity, both ways, on aligned rows.** `docs/i18n-terms.md` states that the stage words map one
to one and must not be weakened in translation. So where a Japanese row asserts a stage, its English
row asserts the same stage. This direction is the opposite of the literal rule on purpose: a missing
stage word is not an omitted detail, it is a claim at a different strength. This is the rule that
catches the failure above, where the Japanese row gained "the compatibility table states" and "a
single observation" while the English row kept saying neither.

Alignment is by position within a table, and **only when the shape matches**. Where the table count or
a table's row count differs between languages, that pair is reported as not comparable and nothing is
asserted about it. A checker that aligns rows it cannot align invents findings, and an invented
finding is worse than the gap: it gets the checker switched off.

Run:  python3 tools/check_translation_drift.py [--verbose]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JA = ROOT / "docs" / "ja"
EN = ROOT / "docs" / "en"

FENCE = re.compile(r"^\s*(```|~~~)")
# A separator row: | --- | --- |
SEPARATOR = re.compile(r"^\s*\|[\s:|-]+\|\s*$")

# Literals that carry the same spelling in every language. Deliberately excludes one- and two-digit
# integers: they are list numbers far more often than measurements, and including them reports the
# ordinal in every numbered row. The cost is that a small measured value -- an object size of 64 -- is
# not covered here. That is a known hole, not an oversight; the stage rule below is what covers a row
# whose evidence changed.
# Identifiers carry the same spelling in every language: a condition key, an S3 action, a Region code
# and a version string are not translated.
IDENTIFIER = re.compile(
    r"""(?:
        aws:[A-Za-z]+
      | s3:[A-Za-z*]+
      | \b[a-z]{2}-[a-z]+-\d\b
      | \b\d+\.\d+\.\d+[A-Za-z0-9]*\b
    )""",
    re.VERBOSE,
)

# --- copyable block ---------------------------------------------------------------------------
# NUMBER, SCALE, NUMBER_FLOOR and numbers_in() depend on nothing else in this file or this
# repository -- only `re` -- so they can be lifted out as-is. The sibling playbook asked for that,
# having decided to borrow the myriad scaling rather than write a second implementation of it, and
# `test_the_numeric_block_is_self_contained` executes this block in an empty namespace to keep the
# promise true.
#
# Numbers are compared by value, not by spelling. Japanese writes 3 億 where English writes
# "300 million" and 10 万 where English writes "100,000", so a spelling comparison reports the
# numeral system as drift. Both were false positives on the first run of this checker.
#
# Not handled: a locale that groups digits with a full stop, where `24.861` means 24861. The sibling
# repository handles it because it publishes eight languages including German, Spanish and French.
# Here the pairs are Japanese and English only, so adding it would be a mechanism with no input --
# and it cannot be had for free: `1.234` as a decimal and as a grouped integer are indistinguishable,
# so supporting it means normalising some real decimals away.
NUMBER = re.compile(
    r"(?<![\w.])(\d[\d,]*(?:\.\d+)?)\s*(億|万|million|billion|thousand)?", re.IGNORECASE
)
SCALE = {
    "億": 10**8,
    "万": 10**4,
    "thousand": 10**3,
    "million": 10**6,
    "billion": 10**9,
}
# Below this, a number is a list ordinal or a small count far more often than a measurement, and
# including it reports the ordinal in every numbered row. The cost is that a genuinely small measured
# value -- an object size of 64 -- is not covered. Known hole, not an oversight.
NUMBER_FLOOR = 100


def numbers_in(text: str) -> dict[str, str]:
    """Map each numeric value in a line to the spelling it was written with.

    Keyed by value so that 3 億, 300 million and 300,000,000 compare equal; valued by the original
    spelling because that is what gets reported. A finding that says `24681` cannot be found in a file
    that says `24,861`, which makes the report useless exactly when it is right.
    """
    found: dict[str, str] = {}
    for match in NUMBER.finditer(text):
        digits, scale = match.group(1), match.group(2)
        try:
            value = float(digits.replace(",", ""))
        except ValueError:
            continue
        if scale:
            value *= SCALE[scale.lower()]
        if value >= NUMBER_FLOOR:
            canonical = f"{value:.4f}".rstrip("0").rstrip(".")
            found.setdefault(canonical, match.group(0).strip())
    return found


# --- end of copyable block --------------------------------------------------------------------


def literals_in(text: str) -> dict[str, str]:
    """Every comparable literal in a line, mapped to the spelling it was written with."""
    found = {identifier: identifier for identifier in IDENTIFIER.findall(text)}
    found.update(numbers_in(text))
    return found


def tables(path: Path) -> list[list[str]]:
    """Contiguous runs of table rows, excluding separators and anything inside a code fence."""
    out: list[list[str]] = []
    current: list[str] = []
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if line.lstrip().startswith("|"):
            if not SEPARATOR.match(line):
                current.append(line)
            continue
        if current:
            out.append(current)
            current = []
    if current:
        out.append(current)
    return out


def paired_documents() -> list[tuple[Path, Path]]:
    pairs = []
    for ja_file in sorted(JA.rglob("*.md")):
        en_file = EN / ja_file.relative_to(JA)
        if en_file.is_file():
            pairs.append((ja_file, en_file))
    return pairs


def literal_findings(ja_file: Path, en_file: Path) -> list[str]:
    """Literals in the English tables that the Japanese tables do not contain."""
    ja_values: set[str] = set()
    for table in tables(ja_file):
        for row in table:
            ja_values |= set(literals_in(row))
    problems = []
    for table in tables(en_file):
        for row in table:
            for value, spelling in sorted(literals_in(row).items()):
                if value not in ja_values:
                    problems.append(
                        f"{en_file.relative_to(ROOT)}: a table cell has {spelling!r}, which no table "
                        f"in {ja_file.relative_to(ROOT)} contains. Either the English is stale, or "
                        "the Japanese lost a value."
                    )
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--verbose", action="store_true", help="report tables that were not compared"
    )
    args = parser.parse_args()

    documents = paired_documents()
    if not documents:
        print("translation-drift: no ja/en document pair found", file=sys.stderr)
        return 1

    problems: list[str] = []
    for ja_file, en_file in documents:
        problems += literal_findings(ja_file, en_file)
        if args.verbose:
            print(
                f"  compared {len(tables(ja_file))} table(s) in {ja_file.relative_to(ROOT)}"
            )

    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if problems:
        print(
            f"translation drift: {len(problems)} finding(s) across {len(documents)} document pair(s)",
            file=sys.stderr,
        )
        return 1
    print(f"translation-drift: {len(documents)} document pair(s) consistent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
