#!/usr/bin/env python3
"""Require links that send an English reader into Japanese to say so.

This repository is deliberately asymmetric: Japanese is authoritative, English covers the hub, and
the technical documents under `docs/ja/` stay Japanese-only until they have settled. That policy is
recorded in `docs/i18n-manifest.txt`. The consequence is that `docs/en/README.md` legitimately links
into `docs/ja/`, and those links are the seam where the policy meets a reader.

Three existing checks each stop one step short of this seam:

* `check_links.py` proves the target resolves. A link into Japanese resolves perfectly.
* `sync_lang_switcher.py` omits the switcher when there is no counterpart, so a Japanese-only page
  carries no language affordance at all — by design, to avoid a link that 404s.
* `check_en_doc_language.py` looks for Japanese characters in English files. A link whose text is
  "Architecture" and whose target is `../ja/architecture.md` contains none, so it passes.

So the failure is invisible to the tooling and visible only to the reader: they click an English
label and land on a Japanese page. It is not the missing translation that misleads them, it is the
unlabelled link. That is worth separating, because the translation is a content decision with a
cost, while the label is free.

A link is marked in one of three ways:

1. `(Japanese)` after it on the same line. One spelling only. `(JA)`, `(Japanese version)` and
   similar were in use and are rejected, because two spellings of the same marker is how a
   convention stops being checkable.

   The line is the unit rather than the character position after the link, because in a two-column
   table the marker belongs in the prose cell — `| [PoC checklist](...) | The order to confirm
   things in (Japanese) |` needs no second copy of the word. A line is what a reader takes in
   before deciding to click. To keep that from letting one marker cover several links, a line needs
   at least as many markers as it has links into Japanese.
2. The link text names the language, which is what the switcher block does: `[日本語](...)` cannot
   mislead anyone about where it goes.
3. The link text carries the path, as in a table of repository files, where
   [`docs/ja/verification-status.md`](../ja/verification-status.md) already tells the reader where
   they are going.

Closing a finding by marking the link is always correct. Closing it by writing the English target is
better when the document has settled — see the promotion checklist in `docs/i18n-manifest.txt`.

Taking that better route creates the third failure: the target is retargeted to the English sibling
and the label is not, so a correctly spelled marker now sits on a line where nothing goes to
Japanese. It misdescribes the link instead of describing it, and nothing else notices — the target
resolves, the file is English, the spelling is the accepted one. A marker is therefore reported as
stale when every link on its line resolves inside `docs/en/`. Files outside `docs/` are excluded:
the root `README.md` and `CONTRIBUTING.md` are Japanese without being tiered, so a marker pointing
at one of them is right.

Run:  python3 tools/check_cross_language_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Matches sync_lang_switcher.py so both tools agree on what a link is.
LINK = re.compile(r"(?<!!)\[([^\]]*)\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(?:```|~~~)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")

# The one accepted marker.
MARKER = re.compile(r"\(Japanese\)")

# Spellings that mean the right thing but are not the accepted form. Named so the failure message
# can say "use (Japanese)" instead of "add a marker" when one of these is what is already there.
NEAR_MISS = re.compile(r"\((?:JA|ja|Japanese version|in Japanese|Japanese only)\)")


def lang_root(lang: str) -> Path:
    """Resolved at call time so that ROOT can be redirected in tests."""
    return ROOT / "docs" / lang


def english_docs() -> list[Path]:
    en_root = lang_root("en")
    if not en_root.is_dir():
        return []
    return sorted(en_root.rglob("*.md"))


def resolves_under(source: Path, target: str, lang: str) -> bool:
    """Whether `target`, written in `source`, resolves to a file under docs/<lang>/."""
    if target.startswith(SKIP_SCHEMES) or target.startswith("#"):
        return False
    path = (source.parent / target.split("#", 1)[0]).resolve()
    return lang_root(lang).resolve() in path.parents


def targets_japanese(source: Path, target: str) -> bool:
    return resolves_under(source, target, "ja")


def targets_english(source: Path, target: str) -> bool:
    """Used to decide that a marker is stale, so it has to be certain rather than probable.

    `docs/en/` is the only place a target is known to be English. Files outside `docs/` — the root
    `README.md`, `CONTRIBUTING.md`, `docs/i18n-terms.md` — are Japanese but are not tiered, so a
    marker on a link to one of them is correct and is left alone. Judging those by their contents
    was the alternative and would have failed the generated language switcher, whose home link
    points at the Japanese hub and which no one can edit to add a marker.
    """
    return resolves_under(source, target, "en")


def main() -> int:
    unmarked: list[str] = []
    near_miss: list[str] = []
    stale: list[str] = []
    marked = 0
    scanned = 0

    for path in english_docs():
        scanned += 1
        relative = str(path.relative_to(ROOT))
        in_fence = False
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                continue
            needs_marker: list[tuple[str, str]] = []
            for match in LINK.finditer(line):
                text, target = match.group(1), match.group(2)
                if not targets_japanese(path, target):
                    continue
                # Self-marking: the text names the language (the switcher) or spells out the
                # path, so the reader already knows what they are clicking.
                if "日本語" in text or "docs/ja/" in text:
                    marked += 1
                    continue
                needs_marker.append((text, target))

            if not needs_marker:
                # A marker on a line with no link into Japanese is left over from a promotion: the
                # link was retargeted to the English sibling and the label was not. It now tells the
                # reader the opposite of the truth, and nothing else here would notice — the target
                # resolves, the file is English, and the marker is spelled correctly.
                links = [m.group(2) for m in LINK.finditer(line)]
                if (
                    MARKER.search(line)
                    and links
                    and all(targets_english(path, target) for target in links)
                ):
                    stale.append(f"{relative}:{number}: {line.strip()}")
                continue

            covered = len(MARKER.findall(line))
            marked += min(covered, len(needs_marker))
            uncovered = needs_marker[covered:]
            if not uncovered:
                continue

            wrong_spelling = bool(NEAR_MISS.search(line))
            bucket = near_miss if wrong_spelling else unmarked
            for text, target in uncovered:
                bucket.append(f"{relative}:{number}: [{text}]({target})")

    if unmarked or near_miss or stale:
        total = len(unmarked) + len(near_miss) + len(stale)
        print(
            f"English documents describe where their links go incorrectly ({total} line(s)):",
            file=sys.stderr,
        )
        for finding in unmarked:
            print(f"  missing marker  {finding}", file=sys.stderr)
        for finding in near_miss:
            print(f"  wrong spelling  {finding}", file=sys.stderr)
        for finding in stale:
            print(f"  stale marker    {finding}", file=sys.stderr)
        if unmarked or near_miss:
            print(
                "\n  Append `(Japanese)` after the link, exactly that spelling. A reader who follows an\n"
                "  English label onto a Japanese page was not warned by the missing translation; they\n"
                "  were misled by the unlabelled link. If the document has settled, translating it is\n"
                "  the better fix — see the promotion checklist in docs/i18n-manifest.txt.",
                file=sys.stderr,
            )
        if stale:
            print(
                "\n  Remove the `(Japanese)` on the stale lines. Nothing on them goes to Japanese any\n"
                "  more, so the marker now misdescribes the link rather than describing it. This is\n"
                "  what a promotion leaves behind when the target is retargeted and the label is not.",
                file=sys.stderr,
            )
        return 1

    print(
        f"cross-language links OK: {marked} link(s) into Japanese are marked, "
        f"{scanned} English file(s) checked"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
