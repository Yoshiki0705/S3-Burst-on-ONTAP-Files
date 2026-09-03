#!/usr/bin/env python3
"""Every pattern README opens with a status, and the word is one of the five that are defined.

The status line is the first thing a reader sees and the only place that says whether a template was
ever run. Two ways it goes wrong, both of which look fine in review:

1. A new pattern is scaffolded and the status is edited to something plausible but undefined --
   `tested`, `verified`, `wip`. Plausible is the problem: `verified` is a *claim stage*, a different
   axis, and using it here tells the reader the behaviour was confirmed when what happened was a
   successful `cfn-lint` run.
2. A pattern is deployed and measured, and the status stays at whatever it was scaffolded with.
   That one is not detectable from here -- no checker can tell what was run -- so this only holds the
   vocabulary, which is what keeps the two axes from merging.

The five words are defined in `patterns/_template/README.md`, and they are read from that table
rather than duplicated here: a list in the checker is a second definition that drifts from the first.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_README = ROOT / "patterns" / "_template" / "README.md"

# The status word is written in backticks in the definition table's first column, and in the pattern
# README's opening blockquote. Both spellings are accepted in the latter: the skeleton writes
# `状態: `x``, the Japanese-authored patterns use that form, and the English ones use `Status: `x``.
DEFINITION = re.compile(r"^\| `([a-z-]+)` \|", re.MULTILINE)
STATUS_LINE = re.compile(
    r"^>\s*\*{0,2}(?:Status|状態)\*{0,2}:?\s*\*{0,2}\s*`([a-z-]+)`", re.MULTILINE
)


def defined_words() -> set[str]:
    """The status vocabulary, read from the table that defines it."""
    text = TEMPLATE_README.read_text(encoding="utf-8")
    words = set(DEFINITION.findall(text))
    if not words:
        # A checker that finds nothing to check must fail rather than pass: this is how the
        # definition table getting reformatted would otherwise disable the check silently.
        raise SystemExit(
            f"{TEMPLATE_README.relative_to(ROOT)}: no status words found in the definition table; "
            "the checker cannot verify anything"
        )
    return words


def status_bearing_readmes() -> list[Path]:
    """Every README that opens with a status.

    The glob is two levels deep, so `patterns/_template/README.md` -- which defines the words rather
    than using one -- is outside it. `patterns/_template/skeleton/README.md` is inside it, and is
    checked deliberately: the skeleton is what every new pattern is copied from, so a bad word there
    propagates to each one.
    """
    return sorted(ROOT.glob("patterns/*/*/README.md"))


def main() -> int:
    allowed = defined_words()
    readmes = status_bearing_readmes()
    if not readmes:
        print("pattern-status: no README with a status line found", file=sys.stderr)
        return 1

    problems: list[str] = []
    for readme in readmes:
        rel = readme.relative_to(ROOT)
        # Only the opening lines: a status word quoted later in prose is discussion, not a claim.
        head = "\n".join(readme.read_text(encoding="utf-8").splitlines()[:12])
        found = STATUS_LINE.findall(head)
        if not found:
            problems.append(
                f"{rel}: no status line in the first 12 lines. "
                f"Open with '> **Status: `<word>`**' using one of: {', '.join(sorted(allowed))}"
            )
            continue
        for word in found:
            if word not in allowed:
                problems.append(
                    f"{rel}: status `{word}` is not defined. "
                    f"Use one of: {', '.join(sorted(allowed))}. "
                    "Claim stages (verified / documented / unverified / unconfirmed) are a "
                    "different axis and are not status words."
                )

    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    print(f"pattern-status: {len(readmes)} status line(s) clean")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
