#!/usr/bin/env python3
"""Catch Japanese text left in English documentation.

Adapted from the sibling repository `FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns`
(`scripts/check_en_doc_language.py`). Divergences: that repository names translations
`<name>.en.md` alongside the Japanese file, so it selected them by filename; here a document's
language is its directory, so the selector is `docs/en/**/*.md`. It also discovered files through
`git ls-files`; this one globs the filesystem so that it works before the repository has been
initialised, which is exactly when the first English page gets written.

English documents here are produced by translating their Japanese counterparts, and a translation
pass that misses a line leaves no trace: the file renders, the links work, and only a reader who
does not read Japanese notices.

Some Japanese in an English document is correct, and the distinction is what makes this checkable
rather than a blanket ban:

* the language switcher is bilingual by design — it has to name the other language in that
  language;
* a link whose text says "Japanese version" is meant to leave English;
* a Japanese statute is a proper noun and is given with an English gloss, which is more useful to
  a reader than the gloss alone.

What remains after those is ALLOWED_ANCHORS: links into Japanese documents that have no English
counterpart to point at. They are debt, not exceptions. Listing them individually means a new one
fails this check, and closing an entry means writing the English target rather than extending the
list.

Run:  python3 tools/check_en_doc_language.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN_ROOT = ROOT / "docs" / "en"

CJK = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff]")

# Bilingual by design: the switcher names the other language in that language.
SWITCHER = re.compile(r"🌐|\[日本語\]\(|\(日本語\)|\[English\]\(")

# A link that says it goes to the Japanese version is doing what it says.
DELIBERATE_JA_LINK = re.compile(
    r"\[Japanese version\]|\[README \(日本語\)\]|Japanese is authoritative"
)

# A Japanese statute paired with its English gloss, in either order.
LAW_WITH_GLOSS = re.compile(
    r"[\u4e00-\u9fff]+(法|規則|条例|基準)[^(（]{0,12}[(（]\s*[A-Za-z]"
    r"|[A-Za-z][A-Za-z ]{3,}[(（][^)）]{0,20}[\u4e00-\u9fff]+(法|規則|条例|基準)[^)）]{0,10}[)）]"
)

# Files where the Japanese is the subject of the passage, not a translation miss. Scoped to the
# lines that carry it, so the rest of each file is still checked.
BY_DESIGN_FILES: dict[str, re.Pattern[str]] = {}

# Links into Japanese documents that have no English counterpart. Each entry is a reader who
# leaves English by following a link whose own text is in English.
ALLOWED_ANCHORS: dict[str, tuple[str, ...]] = {}


def english_docs() -> list[Path]:
    if not EN_ROOT.is_dir():
        return []
    return sorted(EN_ROOT.rglob("*.md"))


def is_allowed(relative: str, line: str) -> bool:
    """Whether this line's Japanese is there on purpose."""
    if SWITCHER.search(line) or DELIBERATE_JA_LINK.search(line):
        return True
    if LAW_WITH_GLOSS.search(line):
        return True
    by_design = BY_DESIGN_FILES.get(relative)
    if by_design and by_design.search(line):
        return True
    return any(needle in line for needle in ALLOWED_ANCHORS.get(relative, ()))


def main() -> int:
    findings: list[str] = []
    scanned = 0
    for path in english_docs():
        scanned += 1
        relative = str(path.relative_to(ROOT))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not CJK.search(line) or is_allowed(relative, line):
                continue
            findings.append(f"{relative}:{number}: {line.strip()[:110]}")

    if findings:
        print(
            f"English documents carry untranslated Japanese ({len(findings)} line(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\n  Japanese that is there on purpose (a statute name with its English gloss, the "
            "language switcher, an explicit link to the Japanese version) belongs in the allow "
            "lists in tools/check_en_doc_language.py, with the reason. Anchors into Japanese "
            "documents are listed individually in ALLOWED_ANCHORS; before adding one, consider "
            "writing the English target instead.",
            file=sys.stderr,
        )
        return 1

    print(f"EN docs OK: no untranslated Japanese in {scanned} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
