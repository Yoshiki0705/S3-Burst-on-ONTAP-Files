#!/usr/bin/env python3
"""Superseded statements must name the section that superseded them.

A cross-repository probe fires when a string disappears. A statement that a later measurement
overturned is still there, so a probe stays green and the contradiction ships. This checks the other
direction: for each registered string, the anchor of the superseding section has to appear within a
few lines of it.

Two failures, and they mean opposite things:

    missing anchor  The statement stands unannotated. A reader reaching it has no way to the
                    measurement that overturned it. Add the note.
    string absent   The statement was reworded or removed, so this row now describes nothing.
                    Delete the row -- a registry that keeps claims about text that is gone is worse
                    than no registry.

The registry only knows what is declared in it. See the header of the contract file for why that is a
ratchet rather than a guarantee.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = ROOT / "docs" / "agent" / "superseded-claims.txt"
# 注記は見つけた文の直後に置く。離れると、読者が本文を読み終える前に古い主張を信じる。
WINDOW = 12


class Row(NamedTuple):
    path: str
    text: str
    anchor: str


def parse(body: str) -> tuple[list[Row], list[str]]:
    rows: list[Row] = []
    problems: list[str] = []
    for number, line in enumerate(body.splitlines(), 1):
        if line.startswith("#") or not line.strip():
            continue
        fields = line.split("\t")
        if len(fields) != 3:
            problems.append(
                f"line {number}: expected 3 tab-separated fields, got {len(fields)}"
            )
            continue
        path, text, anchor = fields
        if not text.strip():
            problems.append(f"line {number}: empty superseded string")
            continue
        if not anchor.startswith("#"):
            problems.append(f"line {number}: anchor {anchor!r} does not start with '#'")
            continue
        rows.append(Row(path, text, anchor))
    return rows, problems


def check(rows: list[Row]) -> list[str]:
    failures: list[str] = []
    cache: dict[str, list[str] | None] = {}
    for row in rows:
        if row.path not in cache:
            target = ROOT / row.path
            cache[row.path] = (
                target.read_text(encoding="utf-8").splitlines()
                if target.is_file()
                else None
            )
        lines = cache[row.path]
        if lines is None:
            failures.append(
                f"{row.path}: file not found, so the registered string cannot be found"
            )
            continue
        hits = [i for i, line in enumerate(lines) if row.text in line]
        if not hits:
            failures.append(
                f"{row.path}: {row.text!r} is gone. The row describes text that no longer "
                "exists -- remove it from docs/agent/superseded-claims.txt rather than leaving a "
                "claim about a file it no longer describes."
            )
            continue
        for index in hits:
            window = lines[index : index + WINDOW]
            if any(row.anchor in line for line in window):
                continue
            failures.append(
                f"{row.path}:{index + 1}: {row.text!r} stands without naming what superseded it. "
                f"Add a note carrying {row.anchor} within {WINDOW} lines. A probe cannot catch this "
                "-- the string is present, so every gate stays green while the contradiction ships."
            )
    return failures


def main() -> int:
    if not CONTRACT.is_file():
        print(f"superseded: {CONTRACT.relative_to(ROOT)} not found", file=sys.stderr)
        return 1
    rows, problems = parse(CONTRACT.read_text(encoding="utf-8"))
    for problem in problems:
        print(f"superseded: {problem}", file=sys.stderr)
    if problems:
        return 1
    if not rows:
        # 空の登録簿は「supersession が無い」の報告ではなく、読めていない可能性。
        print(
            "superseded: no rows registered, which is reported rather than passed",
            file=sys.stderr,
        )
        return 1
    failures = check(rows)
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)
    if failures:
        print(f"superseded: {len(failures)} unannotated statement(s)", file=sys.stderr)
        return 1
    print(f"superseded: {len(rows)} superseded statement(s) name their replacement")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
