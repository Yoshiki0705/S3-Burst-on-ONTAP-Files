#!/usr/bin/env python3
"""Resolve the GitHub links that blog drafts point at, against the checkouts they name.

An article is the only path most readers have to the verification record, and **nothing checked
those links.** `check_links.py` skips `.private/` on purpose -- the drafts are gitignored, so a clone
without them is normal -- and the drafts carry 48 links into this repository and its siblings. A
document rename inside a commit gate that passes is enough to break every one of them, silently,
on the reader's side.

WHY THIS IS A SEPARATE FILE RATHER THAN A FLAG ON check_links.py.

That check walks tracked Markdown and fails when a link does not resolve. These links live outside
the tree it walks, resolve against *other* repositories, and have to be skipped rather than failed
when the drafts or the siblings are absent. Folding both behaviours into one file would mean a flag
that changes what "missing" means, which is how a check ends up passing for the wrong reason.

TWO WAYS TO GET THIS WRONG, BOTH OF WHICH HAPPENED WHILE WRITING IT.

  1. **Comparing the path without the repository name.** Strip `blob/main/` off a sibling's URL,
     test the remainder against this checkout, and every sibling link reads as a 404. That produced
     a report of four broken links in published articles, and a plan to "fix" URLs that were already
     correct. The repository name is part of the address, so it decides which root to resolve against.
  2. **Re-deriving the anchor slug.** `check_links.slugify` already encodes the rule that GitHub
     turns each whitespace character into its own hyphen without collapsing runs, which is why
     `（1 / 4 / 8 台）` ends up as `1--4--8-台`. A second implementation reported two real anchors as
     misses. It is imported here rather than rewritten.

An anchor that names a heading which has since been renamed is the failure mode worth most here: the
link still resolves, GitHub serves the page from the top, and the reader never learns that the
sentence they were sent to check is gone.

Run:  python3 tools/check_blog_links.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from check_links import OWNER, PUBLISHED_REPOS, anchors_of
from check_outgoing_probes import LOCAL_NAMES, checkout

ROOT = Path(__file__).resolve().parent.parent
DRAFT_DIR = ROOT / ".private"
DRAFT_GLOB = "blog-*.md"

# `blob/<ref>/<path>#<anchor>`. The ref is captured because a draft may pin a SHA -- the
# block-protocol draft's own header says to do that at publication -- and a pinned ref cannot be
# resolved against a working tree, so it is reported rather than guessed at.
LINK = re.compile(
    rf"https://github\.com/{OWNER}/([^/\s)\"']+)/blob/([^/\s)\"']+)/([^\s)\"'#]+)(#[^\s)\"']*)?"
)

_THIS_REPO = {"s3-burst-on-ontap-files", "S3-Burst-on-ONTAP-Files"}


def root_for(repo: str) -> tuple[Path | None, str | None]:
    """The checkout a repository name resolves to, and why it could not be resolved.

    Compared case-insensitively, for the reason `check_links.PUBLISHED_REPOS` records: GitHub
    resolves a repository name regardless of case and both spellings are in use here.
    """
    lowered = repo.lower()
    if lowered in {name.lower() for name in _THIS_REPO}:
        return ROOT, None
    if lowered not in {name.lower() for name in PUBLISHED_REPOS}:
        return None, f"{repo!r} is not a published repository of {OWNER}"
    for canonical in LOCAL_NAMES:
        if canonical.lower() == lowered:
            found = checkout(canonical)
            if found is None:
                return None, f"no checkout of {canonical} beside this one"
            return found, None
    return (
        None,
        f"{repo!r} has no local directory names recorded; add it to LOCAL_NAMES",
    )


def check(draft: Path) -> tuple[int, list[str], list[str]]:
    """Returns (links seen, failures, things that could not be checked)."""
    seen = 0
    problems: list[str] = []
    unchecked: list[str] = []
    for match in LINK.finditer(draft.read_text(encoding="utf-8")):
        seen += 1
        repo, ref, path, anchor = (
            match.group(1),
            match.group(2),
            match.group(3),
            match.group(4),
        )
        where = f"{draft.name}: {repo}/{path}{anchor or ''}"
        if ref != "main":
            # A pinned ref is a deliberate choice, not a defect. It cannot be resolved against a
            # working tree, so say so rather than reading the tree and calling that a pass.
            unchecked.append(
                f"{where} -- pinned to {ref!r}, not resolvable against a checkout"
            )
            continue
        base, why = root_for(repo)
        if base is None:
            if why and why.startswith("no checkout"):
                unchecked.append(f"{where} -- {why}")
            else:
                problems.append(f"{where} -- {why}")
            continue
        target = base / path
        if not target.is_file():
            problems.append(f"{where} -- no such file in {base.name}")
            continue
        if anchor and len(anchor) > 1 and anchor[1:] not in anchors_of(target):
            problems.append(
                f"{where} -- the file resolves but no heading makes that anchor. "
                "GitHub serves the page from the top, so a reader is not told."
            )
    return seen, problems, unchecked


def main() -> int:
    if not DRAFT_DIR.is_dir():
        print(
            "blog-links: no .private/ directory - skipping (drafts are not committed)"
        )
        return 0
    drafts = sorted(DRAFT_DIR.glob(DRAFT_GLOB))
    if not drafts:
        print(f"blog-links: no {DRAFT_GLOB} under .private/ - skipping")
        return 0

    total = 0
    problems: list[str] = []
    unchecked: list[str] = []
    for draft in drafts:
        seen, bad, skipped = check(draft)
        total += seen
        problems.extend(bad)
        unchecked.extend(skipped)

    if problems:
        print(f"blog-links: {len(problems)} broken link(s):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    # **Drafts present and no links found is a broken reader, not a clean result.** The drafts exist
    # to carry the reader into the record; a run that reports zero is reporting that the pattern
    # stopped matching.
    if total == 0:
        print(
            f"blog-links: {len(drafts)} draft(s) but not one GitHub link matched. "
            "That is this checker failing to read them, not an absence of links.",
            file=sys.stderr,
        )
        return 1

    for note in unchecked:
        print(f"  not checked: {note}")
    print(
        f"blog-links: {total} link(s) in {len(drafts)} draft(s) resolve, anchors included"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
