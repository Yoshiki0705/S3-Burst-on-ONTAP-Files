#!/usr/bin/env python3
"""Verify no strikethrough or production-note pattern sits inside a blog draft's public range.

A persona review (2026-09-21, round 3) asked whether the boundary between a blog draft's
production notes and the text that actually gets pasted onto the publishing platform was enforced
by anything, or only by a heading's wording. It was not enforced by anything. The only signal was
a heading like "## 本文（ここから下をはてなブログへ貼る）" / "## Body (paste everything below
this line)" -- text a human has to read and act on, with no tool checking it.

That gap was not hypothetical. Once a `PUBLIC RANGE START` marker was added to make the boundary
explicit, two HTML comments turned up sitting inside the marked range in
`blog-unpublished-s3files-ja.md` -- production notes about the article's own spine and title,
placed there by mistake. One of the comments even said so about itself: it had been left below the
boundary once already, survives HTML-comment stripping only by luck of the extraction tool, and
still risks shipping into the published page's HTML source if that tool ever changes.

The first version of this check made opting in with the marker voluntary, and a follow-up review
(round 4) named the consequence directly: a file that never gets a marker is silently excluded, so
a future draft added without one looks checked when it never was. That review also asked whether
the four *already-published* posts under `.private/blog-draft-*.md` carried the same pattern --
they were scanned and came back clean, but the scan only happened because someone thought to ask.
This version closes both gaps. Every draft under `.private/` must now say, one way or the other,
what its public range is -- there is no third option where a file is simply unmentioned:

  * `blog-draft-*.md` (already-published posts, mirrored here per this repository's own
    direction-of-update rule) get their range for free, from the same boundary
    `tools/check_blog_draft_sync.py` already uses: the public range is everything from the first
    Markdown heading onward. These files are never unchecked, because a published post's HTML
    source is a fact, not a draft-in-progress choice;
  * `blog-unpublished-*.md` (not yet published) must declare their range explicitly, either with
    `PUBLIC RANGE START` (checked from the next line to the end of the file) or with
    `PUBLIC RANGE: not applicable` plus a reason (for a file that is superseded, folded into
    another published article, or otherwise never itself the source published from). A file with
    neither is a finding on its own -- "forgot to decide" is not a silent pass.

Once a range is established, within it:

  * no HTML comment (`<!-- ... -->`) may start, other than this repository's own
    `<!-- allow:... -->` inline exemption marker (used by lint tools such as the naming audit and
    meant to ship inside published prose) -- any other comment left there is a production note
    that risks surviving into the platform's rendered HTML depending on how the draft is
    extracted;
  * no strikethrough (`~~text~~`) may appear -- corrections belong as prose, not as a struck-out
    value plus a replacement, per this repository's own round-1 decision to stop doing that;
  * no "addendum" heading (`## 追記`, `### 追記`, `## Addendum`) may appear -- that heading marks
    a production-log entry, not publishable prose.

Run:  python3 tools/check_public_range.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFT_DIR = ROOT / ".private"
PUBLISHED_GLOB = "blog-draft-*.md"
UNPUBLISHED_GLOB = "blog-unpublished-*.md"

MARKER_RE = re.compile(r"PUBLIC RANGE START")
NOT_APPLICABLE_RE = re.compile(r"PUBLIC RANGE:\s*not applicable")
# The same boundary tools/check_blog_draft_sync.py uses for a published post's mirror: the header
# above it is local bookkeeping that never reaches the published page.
BODY_START_RE = re.compile(r"^##? ", re.MULTILINE)
# `<!-- allow:... -->` is this repository's own inline exemption marker for lint tools (naming
# audits, etc.) and is meant to ship inside published prose -- it is not a production note. Only
# an *unlabelled* HTML comment is what this check is after.
HTML_COMMENT_START_RE = re.compile(r"<!--(?!\s*allow:)")
STRIKETHROUGH_RE = re.compile(r"~~[^~\n]+~~")
ADDENDUM_HEADING_RE = re.compile(r"^#{2,3}\s*(追記|Addendum)\b")


def public_range_lines(
    text: str, *, is_published: bool
) -> list[tuple[int, str]] | None:
    """Lines inside the declared public range, as (1-based line number, text) pairs.

    None means "not applicable" -- an explicit, checked opt-out, distinct from "not declared",
    which is reported by `declaration_problem` instead of silently skipped.
    """
    lines = text.splitlines()

    for index, line in enumerate(lines):
        if MARKER_RE.search(line):
            return [(i + 1, lines[i]) for i in range(index + 1, len(lines))]

    if is_published:
        match = BODY_START_RE.search(text)
        if match:
            start_line = text.count("\n", 0, match.start())
            return [(i + 1, lines[i]) for i in range(start_line, len(lines))]
        return None

    if NOT_APPLICABLE_RE.search(text):
        return None

    return "undeclared"  # type: ignore[return-value]


def declaration_problem(path: Path, text: str, *, is_published: bool) -> str | None:
    rel = path.relative_to(ROOT)
    result = public_range_lines(text, is_published=is_published)
    if result == "undeclared":
        return (
            f"{rel}: no public range declared. Add `PUBLIC RANGE START` before the text that "
            "gets published, or `PUBLIC RANGE: not applicable` with a reason if this file is "
            "never itself the source published from."
        )
    if is_published and result is None:
        return f"{rel}: no Markdown heading found, so there is no body to establish a range from."
    return None


def check(path: Path, *, is_published: bool) -> list[str]:
    rel = path.relative_to(ROOT)
    text = path.read_text(encoding="utf-8")
    problem = declaration_problem(path, text, is_published=is_published)
    if problem:
        return [problem]

    lines = public_range_lines(text, is_published=is_published)
    if lines is None:
        return []
    assert lines != "undeclared"

    findings: list[str] = []
    for lineno, line in lines:
        if HTML_COMMENT_START_RE.search(line):
            findings.append(
                f"{rel}:{lineno}: HTML comment starts inside the public range. "
                "Move the production note above the marker."
            )
        if STRIKETHROUGH_RE.search(line):
            findings.append(
                f"{rel}:{lineno}: strikethrough inside the public range. "
                "Write the correction as prose instead (see round-1 decision)."
            )
        if ADDENDUM_HEADING_RE.match(line):
            findings.append(
                f"{rel}:{lineno}: an addendum heading inside the public range. "
                "Addendum sections are production log entries; move above the marker or fold "
                "the finding into the article body."
            )
    return findings


def main() -> int:
    if not DRAFT_DIR.is_dir():
        print(
            "public-range: no .private/ directory - skipping (drafts are not committed)"
        )
        return 0

    published = sorted(DRAFT_DIR.glob(PUBLISHED_GLOB))
    unpublished = sorted(DRAFT_DIR.glob(UNPUBLISHED_GLOB))
    if not published and not unpublished:
        print(
            f"public-range: no {PUBLISHED_GLOB} or {UNPUBLISHED_GLOB} under .private/ - skipping"
        )
        return 0

    problems: list[str] = []
    checked = 0
    for draft in published:
        checked += 1
        problems.extend(check(draft, is_published=True))
    for draft in unpublished:
        checked += 1
        problems.extend(check(draft, is_published=False))

    if problems:
        print(f"public-range: {len(problems)} issue(s):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        return 1

    print(
        f"public-range: {checked} draft(s) declared a range (or opted out with a reason), all clean"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
