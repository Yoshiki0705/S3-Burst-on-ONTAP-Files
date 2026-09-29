#!/usr/bin/env python3
"""Fail when a blog draft has moved since it was last published.

The drafts under `.private/` mirror published posts, and their own headers say which direction
updates flow: edits are made on the published post and copied here. That direction is what makes a
drift check possible, and it is also what makes the drift dangerous -- a draft that has moved ahead
of the published post looks finished while readers are still served the old text.

That is not hypothetical. A 48-line section on FlexClone sat in both drafts, unpublished, long enough
that a later pass over the same files produced a correction list without it: the list was built by
comparing the drafts against the repository's own findings, and never against the published posts.
The section only surfaced when the two bodies were finally diffed line by line. One comparison
direction was missing, and nothing in the toolchain asked for it.

So each draft records the digest of the body as published, and this check recomputes it. A mismatch
means one of two things, and the fix differs:

  * the draft was edited and the post was not -- publish it, then update the marker;
  * the post was edited elsewhere and the draft is stale -- re-copy the post into the draft.

Either way the answer is not to update the marker on its own. Doing that silences the check while
leaving the two bodies apart, which is the state this exists to make visible.

What is deliberately *not* checked: whether the marker matches the live post. That needs network
access and a credential per platform, and a check that cannot run offline is a check that gets
skipped. This compares the draft against its own recorded digest, which is enough to catch the
draft moving -- the case that actually happened.

This glob also does not touch `blog-unpublished-*.md`. Those files have no marker to compare,
because there is nothing published yet to record a digest against -- but "unpublished" describes
this repository's own publish decision, not whether the platform has a draft. All four
block-protocol articles were sitting as real drafts on Hatena and dev.to, editable and diffable,
while a text search for their titles on the drafts list came back empty and was read as "no draft
exists." A hit count of zero from a UI search is not evidence of absence; open the drafts list and
look. Once a real draft is confirmed, diff it against the local file in both directions before
editing either one -- a platform-side draft can move ahead of the local copy (an agent or the
author may have edited it directly), and copying local-to-platform in that case overwrites newer
content with older content. There is no automated check for this: it needs an authenticated
browser session per platform, so it stays a manual step every time a `blog-unpublished-*.md` file
is touched.

The drafts are gitignored, so a clone without them is normal and skipped rather than failed.

Run:  python3 tools/check_blog_draft_sync.py
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT_DIR = ROOT / ".private"
DRAFT_GLOB = "blog-draft-*.md"

# The digest of the body as published, written into the header when the post is updated.
MARKER = re.compile(r"published-body-sha256:\s*([0-9a-f]{16,64})")
# The body is everything from the first Markdown heading; the header above it is local bookkeeping
# that never reaches the published post.
BODY_START = re.compile(r"^##? ", re.MULTILINE)
DIGEST_CHARS = 16


def body_of(text: str) -> str | None:
    """The part of a draft that corresponds to the published post."""
    match = BODY_START.search(text)
    if not match:
        return None
    return text[match.start() :].strip() + "\n"


def digest(body: str) -> str:
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:DIGEST_CHARS]


def check(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    rel = path.relative_to(ROOT)
    body = body_of(text)
    if body is None:
        return [f"{rel}: no Markdown heading found, so there is no body to compare"]

    match = MARKER.search(text)
    if not match:
        return [
            f"{rel}: no `published-body-sha256:` in the header.\n"
            f"  Add it inside the header comment once the post is published:\n"
            f"      published-body-sha256: {digest(body)}\n"
            "  Without it, a draft that moves ahead of the published post looks finished."
        ]

    recorded = match.group(1)[:DIGEST_CHARS]
    current = digest(body)
    if recorded != current:
        return [
            f"{rel}: the body has changed since it was last published.\n"
            f"  recorded: {recorded}\n"
            f"  current : {current}\n"
            "  Publish the draft and then update the marker, or re-copy the published post into\n"
            "  the draft. Updating the marker alone hides the difference instead of closing it."
        ]
    return []


def main() -> int:
    if not DRAFT_DIR.is_dir():
        print("blog-sync: no .private/ directory - skipping (drafts are not committed)")
        return 0

    drafts = sorted(DRAFT_DIR.glob(DRAFT_GLOB))
    if not drafts:
        print(f"blog-sync: no {DRAFT_GLOB} under .private/ - skipping")
        return 0

    problems: list[str] = []
    for draft in drafts:
        problems.extend(check(draft))

    if problems:
        print(f"blog-sync: {len(problems)} issue(s):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(f"blog-sync: {len(drafts)} draft(s) match their published digest")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
