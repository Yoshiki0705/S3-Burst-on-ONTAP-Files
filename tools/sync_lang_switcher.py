#!/usr/bin/env python3
"""Generate and verify the language switcher, and catch links that prefer the wrong language.

Adapted from the sibling repository `fsxn-adoption-playbook` (`tools/sync_lang_switcher.py`).
Divergence from the original: that repository carries eight languages and a `_template/`
convention for scaffolding; this one is Japanese-canonical with English as the only translation,
so `LANGS` is reduced to two and the per-language `HOME_LABEL` table shrinks with it. The path
model, the marker contract and the wrong-language link check are unchanged.

Two checks live here because they are two halves of the same problem: keeping a bilingual tree
navigable without hand-maintaining it.

1. The switcher block. It is generated from what exists on disk, so a page with no English
   counterpart simply has no switcher rather than a link that 404s.

2. Links that prefer another language. `check_links.py` proves a target resolves; it cannot see
   that `docs/en/...` sent an English reader into `docs/ja/...` for a page that exists in English.
   That is the failure translations introduce over time: a page gets translated and the links that
   were legitimately falling back to Japanese are never repointed. The fallback still resolves, so
   no other check notices.

A document's language is its directory. The single exception is the Japanese hub: it is the
repository-root README.md, because that is what GitHub renders on the landing page, so
docs/ja/README.md deliberately does not exist.

Run:  python3 tools/sync_lang_switcher.py            # verify both
      python3 tools/sync_lang_switcher.py --write    # regenerate the blocks
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parent.parent

# Order is fixed so the switcher reads identically everywhere.
LANGS = ("ja", "en")
LANG_NAMES = {"ja": "日本語", "en": "English"}
# The "back to the hub" label per language. A language needs an entry here before it can hold a
# document below hub level; without one the tool fails rather than inventing a UI string.
HOME_LABEL = {"ja": "🏠 リポジトリトップ", "en": "🏠 Repository home"}

START = "<!-- lang-switcher:start -->"
END = "<!-- lang-switcher:end -->"

LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(?:```|~~~)")
SKIP_SCHEMES = ("http://", "https://", "mailto:", "tel:", "data:")
HUB = "README.md"


# --- path model ---------------------------------------------------------------------------------


def path_for(lang: str, subpath: str) -> Path:
    """Absolute path of `subpath` in `lang`."""
    if lang == "ja" and subpath == HUB:
        return ROOT / HUB
    return ROOT / "docs" / lang / subpath


def split_rel(rel: str) -> tuple[str, str] | None:
    """Split a repo-relative path into (lang, subpath), or None when it is not localized."""
    if rel == HUB:
        return "ja", HUB
    parts = PurePosixPath(rel).parts
    if len(parts) >= 3 and parts[0] == "docs" and parts[1] in LANGS:
        return parts[1], "/".join(parts[2:])
    return None


def available(subpath: str) -> list[str]:
    return [lang for lang in LANGS if path_for(lang, subpath).exists()]


def relative(target: Path, from_file: Path) -> str:
    return os.path.relpath(target, start=from_file.parent).replace(os.sep, "/")


def eligible() -> list[str]:
    """Localized Markdown documents, root hub first.

    Underscore-prefixed components are scaffolding (`_template/`, `_assets/`) and are skipped,
    the same convention the other validators use.
    """
    found = [HUB] if (ROOT / HUB).exists() else []
    docs = ROOT / "docs"
    if docs.is_dir():
        for path in sorted(docs.rglob("*.md")):
            rel = str(path.relative_to(ROOT))
            if any(part.startswith("_") for part in PurePosixPath(rel).parts):
                continue
            if split_rel(rel) is not None:
                found.append(rel)
    return found


# --- switcher block ----------------------------------------------------------------------------


def build_block(rel: str) -> tuple[str | None, str | None]:
    """Return (expected_line, error). expected_line is None when no switcher belongs here."""
    split = split_rel(rel)
    if split is None:
        return None, None
    lang, subpath = split

    langs = available(subpath)
    if len(langs) < 2:
        return None, None

    source = ROOT / rel
    parts = [
        f"[{LANG_NAMES[other]}]({relative(path_for(other, subpath), source)})"
        for other in langs
    ]

    # The hub is the home, so it does not link to itself twice.
    if subpath != HUB:
        label = HOME_LABEL.get(lang)
        if label is None:
            return None, (
                f"{rel}: no home-link label defined for {lang!r}; "
                f"add one to HOME_LABEL in tools/sync_lang_switcher.py"
            )
        parts.append(f"[{label}]({relative(path_for(lang, HUB), source)})")

    return "🌐 " + " | ".join(parts), None


def find_blocks(lines: list[str]) -> list[tuple[int, int]]:
    blocks: list[tuple[int, int]] = []
    start: int | None = None
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped == START:
            start = index
        elif stripped == END and start is not None:
            blocks.append((start, index))
            start = None
    return blocks


def sync_file(rel: str, write: bool) -> list[str]:
    expected, error = build_block(rel)
    if error:
        return [error]

    path = ROOT / rel
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    blocks = find_blocks(lines)
    problems: list[str] = []

    if expected is None:
        if not blocks:
            return []
        if not write:
            return [
                f"{rel}: has a switcher block but only one language exists; remove the markers"
            ]
        for start, end in reversed(blocks):
            del lines[start : end + 1]
            # Deleting the block can leave two blank lines behind, which markdownlint rejects.
            if (
                0 < start < len(lines)
                and lines[start - 1].strip() == ""
                and lines[start].strip() == ""
            ):
                del lines[start]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return []

    if not blocks:
        return [
            (
                f"{rel}: missing switcher markers; add {START} / {END} "
                f"immediately after the H1 and at the end of the file"
            )
        ]
    if len(blocks) != 2:
        problems.append(
            f"{rel}: found {len(blocks)} switcher block(s), expected 2 "
            f"(one after the H1, one at the end)"
        )

    changed = False
    for start, end in reversed(blocks):
        current = lines[start + 1 : end]
        if current == [expected]:
            continue
        if not write:
            problems.append(f"{rel}:{start + 2}: switcher block is out of date")
            continue
        lines[start + 1 : end] = [expected]
        changed = True

    if write and changed:
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return problems


# --- links that prefer another language --------------------------------------------------------


def normalize(resolved: str) -> str:
    """Treat `dir` and `dir/README.md` as the same target."""
    return resolved.removesuffix("/README.md")


def iter_links(text: str):
    """Yield (lineno, line, target) for inline links outside fences and switcher blocks."""
    lines = text.splitlines()
    inside = set()
    for start, end in find_blocks(lines):
        inside.update(range(start, end + 1))
    in_fence = False
    for index, line in enumerate(lines):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence or index in inside:
            continue
        for match in LINK.finditer(line):
            yield index + 1, line, match.group(1)


def check_language_links(rel: str) -> list[str]:
    split = split_rel(rel)
    if split is None:
        return []
    lang, _ = split
    source = ROOT / rel
    problems: list[str] = []

    for lineno, line, target in iter_links((ROOT / rel).read_text(encoding="utf-8")):
        raw = target.split("#", 1)[0]
        if not raw or raw.startswith(SKIP_SCHEMES):
            continue
        resolved = os.path.normpath(
            str(PurePosixPath(rel).parent / raw.rstrip("/"))
        ).replace(os.sep, "/")
        other = split_rel(resolved) or split_rel(f"{resolved}/{HUB}")
        if other is None or other[0] == lang:
            continue

        own_subpath = other[1]
        own = path_for(lang, own_subpath)
        if not own.exists():
            continue  # legitimate fallback: this language has no such page

        # Deliberately bilingual lines pair both languages on one line.
        own_rel = normalize(relative(own, source))
        if any(
            normalize(candidate.split("#", 1)[0].rstrip("/")) == own_rel
            for candidate in LINK.findall(line)
        ):
            continue

        problems.append(
            f"{rel}:{lineno}: links to {other[0]} ({raw}) but "
            f"{own.relative_to(ROOT)} exists in {lang}"
        )
    return problems


# --- entry point -------------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="regenerate the switcher blocks in place"
    )
    args = parser.parse_args()

    files = eligible()
    if not files:
        print(
            "switcher: no localized documents found; expected at least the root README.md",
            file=sys.stderr,
        )
        return 1

    switcher_problems: list[str] = []
    link_problems: list[str] = []

    for rel in files:
        switcher_problems += sync_file(rel, args.write)
    for rel in files:
        link_problems += check_language_links(rel)

    if switcher_problems:
        print(f"switcher: {len(switcher_problems)} issue(s):", file=sys.stderr)
        for problem in switcher_problems:
            print(f"  {problem}", file=sys.stderr)
    if link_problems:
        print(
            f"language links: {len(link_problems)} issue(s) "
            f"(a translated page must not link to another language's copy):",
            file=sys.stderr,
        )
        for problem in link_problems:
            print(f"  {problem}", file=sys.stderr)

    if switcher_problems or link_problems:
        return 1

    with_switcher = sum(1 for rel in files if build_block(rel)[0] is not None)
    print(
        f"switcher: {with_switcher} document(s) in sync across {len(LANGS)} language(s), "
        f"{len(files)} localized file(s) checked"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
