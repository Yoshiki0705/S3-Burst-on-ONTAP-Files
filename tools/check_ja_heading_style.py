#!/usr/bin/env python3
"""Japanese section headings (## and below) have to be noun phrases.

WHY THIS IS A CHECK AND NOT A CONVENTION IN PROSE

It was a convention in prose, and it drifted: twenty-two headings across six documents ended in a
predicate, and every one of them passed every other gate here. A heading sits where a reader expects
a label, so a sentence there is read twice -- once as a label and once as a claim.

WHAT IT ALLOWS, AND WHY EACH EXEMPTION EXISTS

- `#` and front-matter `title`: a different rule governs them (one line, one assertion).
- Headings with no kana: an English heading is out of scope.
- Inside a fenced block: a `#` there is a shell comment. Missing this breaks code.
- A heading ending in a counter (`1 つ`, `3 点`): already a noun phrase. The character class that
  catches verb terminal forms also catches `つ`, so the digit before it is what distinguishes them.
- A heading ending in an inline-code identifier: `... される \\`nconnect\\`` is a noun phrase. Code
  spans are replaced rather than removed, because removing one leaves a verb at the end and reports
  a heading that is already correct.

NOUN-IFYING MUST NOT DROP THE ASSERTION

"CopyBackup には仕組みがありません" carries a claim. Renaming it to "CopyBackup の仕組み" turns the
claim into a topic. Keep it with a suffix (`の不在`, `の不成立`, `の再現`) or a modifier
(`未対応の〜`, `既定で無効な〜`). A heading that cannot survive either is carrying a sentence -- move
it into the body.

RENAMING CHANGES THE ANCHOR. `make links` verifies internal anchors, so run it in the same change.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

KANA = re.compile(r"[ぁ-んァ-ヶ]")
# Predicate endings: polite forms, the plain past, and the terminal-form vowels a verb can end on.
# `つ` needs the negative lookbehind so a counter ("1 つ", "3 つ") is not read as 立つ / 待つ.
PREDICATE = re.compile(
    r"(ます|ません|ました|ませんでした|です|でした|ください|か|[うくぐすずぬふぶむるれ]|(?<![0-9 ])つ)$"
)
# Endings that are already nouns. Without these the check fires on correct headings.
NOUN_ENDING = re.compile(
    r"(問い|項目|手順|範囲|一覧|理由|条件|場合|点|扱い|こと|もの|形|型)$"
)
FENCE = re.compile(r"^\s*(```|~~~)")
HEADING = re.compile(r"^(#{2,6})\s+(.*?)\s*$")


def normalize(text: str) -> str:
    """Strip markup that is not part of the wording, keeping the final token intact."""
    text = re.sub(
        r"`[^`]*`", "X", text
    )  # an identifier is a noun; replace, never remove
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return re.sub(r"\*\*|\*", "", text).strip()


def violations(lines: list[str]) -> list[tuple[int, str]]:
    """Return (lineno, heading) for every Japanese heading that ends in a predicate."""
    found: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(lines, start=1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = HEADING.match(line)
        if not match:
            continue
        text = normalize(match.group(2))
        if not KANA.search(text) or NOUN_ENDING.search(text):
            continue
        if PREDICATE.search(text):
            found.append((lineno, match.group(2)))
    return found


def tracked_markdown(root: Path) -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [root / name for name in out]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(ROOT))
    args = parser.parse_args()
    root = Path(args.path).resolve()

    files = tracked_markdown(root)
    # A scan that finds no files could not run, and reporting that as success is how this kind of
    # check goes quiet. See docs/agent/policy-in-code.md.
    if not files:
        print(
            "check_ja_heading_style: no tracked Markdown found; the reader is broken, "
            "not the tree",
            file=sys.stderr,
        )
        return 1

    findings: list[str] = []
    for path in files:
        rel = path.relative_to(root)
        for lineno, heading in violations(path.read_text(encoding="utf-8").split("\n")):
            findings.append(f"{rel}:{lineno}: {heading}")

    if findings:
        print(
            f"Japanese heading style failed ({len(findings)} heading(s) end in a predicate):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\n  Rewrite as a noun phrase, keeping the assertion: a suffix (の不在 / の不成立 /\n"
            "  の再現) or a modifier (未対応の〜 / 既定で無効な〜). One that survives neither is\n"
            "  carrying a sentence -- move it into the body.\n"
            "  Renaming changes the anchor: run `make links` in the same change.",
            file=sys.stderr,
        )
        return 1

    print(f"ja-headings: {len(files)} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
