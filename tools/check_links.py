#!/usr/bin/env python3
"""Resolve internal Markdown links and optionally probe external URLs.

Adapted from the sibling repository `FSx-for-ONTAP-Adoption-Playbook` (`tools/check_links.py`).
Divergence: the original imported `iter_markdown` from a `frontmatter` module that also parsed the
YAML note schema. This repository has no note schema, so the one function that was needed is
inlined here and the module is not carried over — a dependency exists to be read, and a file whose
only purpose is to satisfy an import gets stale unread.

Internal links break constantly in a hub-and-spoke repository, because the whole point of the
structure is that documents link to each other heavily. This check is offline by default so it can
run as a fast commit gate; external URLs need --external and a network.

Run:  python3 tools/check_links.py [--external]
"""

from __future__ import annotations

import argparse
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = (
    ".private",
    ".kiro",
    "node_modules",
    ".git",
    # Generated caches; see the note in audit_public_output.py.
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".hypothesis",
    # .terraform/ holds the downloaded provider, which ships its own README and links.
    ".terraform",
)

# [text](target) - skips image embeds (leading !) and reference-style definitions.
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE = re.compile(r"^\s*(?:```|~~~)")
ANCHOR = re.compile(r"^(#{1,6})\s+(.*)$")

SKIP_SCHEMES = {"mailto", "tel", "data"}
USER_AGENT = "s3-burst-on-ontap-files-link-check"


def iter_markdown(root: Path):
    """Yield every Markdown file under root, skipping unpublished directories."""
    for path in sorted(root.rglob("*.md")):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        yield path


def slugify(text: str) -> str:
    """GitHub-flavoured heading slug: lowercase, punctuation dropped, spaces to hyphens.

    Each whitespace character becomes its own hyphen — GitHub does not collapse runs. This matters
    because dropping a punctuation mark between two spaces (as in "Serve side - `FlexCache`")
    leaves two spaces behind, and therefore a double hyphen in the real anchor.
    """
    text = re.sub(r"<[^>]+>", "", text).strip().lower()
    text = re.sub(r"[^\w\s-]", "", text)
    return re.sub(r"\s", "-", text)


def anchors_of(path: Path) -> set[str]:
    found: set[str] = set()
    in_fence = False
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return found
    for line in lines:
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = ANCHOR.match(line)
        if match:
            found.add(slugify(match.group(2)))
        for named in re.finditer(r'(?:id|name)="([^"]+)"', line):
            found.add(named.group(1).lower())
    return found


def iter_links(path: Path):
    """Yield (lineno, target) for every inline link outside fenced code."""
    in_fence = False
    for lineno, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for match in LINK.finditer(line):
            yield lineno, match.group(1)


def check_internal(source: Path, target: str) -> str | None:
    """Return an error message when an internal link does not resolve."""
    raw_path, _, fragment = target.partition("#")
    raw_path = unquote(raw_path)

    if not raw_path:  # same-document anchor
        if fragment and slugify(fragment) not in anchors_of(source):
            return f"anchor '#{fragment}' not found in this document"
        return None

    resolved = (
        (ROOT / raw_path[1:])
        if raw_path.startswith("/")
        else (source.parent / raw_path)
    )
    resolved = resolved.resolve()

    try:
        resolved.relative_to(ROOT)
    except ValueError:
        return f"link escapes the repository root: {target}"

    if resolved.is_dir():
        # GitHub renders a directory link as a file listing, so a README is not required.
        # Git does not track empty directories though, so a directory that exists locally but
        # holds nothing would 404 after a clone - require at least one tracked file.
        if not any(
            child.is_file() and child.name != ".DS_Store"
            for child in resolved.rglob("*")
        ):
            return f"directory is empty and will not survive a clone: {raw_path} (add .gitkeep)"
        return None

    if not resolved.exists():
        return f"file not found: {raw_path}"

    if (
        fragment
        and resolved.suffix == ".md"
        and slugify(fragment) not in anchors_of(resolved)
    ):
        return f"anchor '#{fragment}' not found in {raw_path}"
    return None


def _probe(url: str, method: str, timeout: float) -> str | None:
    request = urllib.request.Request(
        url, method=method, headers={"User-Agent": USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status >= 400:
                return f"HTTP {response.status}"
    except urllib.error.HTTPError as exc:
        if exc.code in (403, 405, 429):
            return None  # bot-blocked or method-not-allowed, not a broken link
        return f"HTTP {exc.code}"
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        return f"unreachable ({exc})"
    return None


def check_external(url: str, timeout: float = 10.0) -> str | None:
    """Probe with HEAD, then confirm a failure with GET before reporting it.

    Some hosts redirect a HEAD to a landing or sign-in page that returns 404 while the real page
    answers GET with 200. Reporting those as broken trains people to ignore the check, so a
    failure is only reported when GET agrees. HEAD stays first because it avoids downloading
    bodies for the common case.
    """
    problem = _probe(url, "HEAD", timeout)
    if problem is None:
        return None
    return _probe(url, "GET", timeout)


# Repositories of this owner that are actually published, with the names GitHub knows them by. A
# local working directory is often named differently -- `~/Projects/fsxn-adoption-playbook` is
# `FSx-for-ONTAP-Adoption-Playbook` on GitHub -- and writing the directory name into a URL produces a
# 404 that only an external probe catches. Eighteen links in this repository were wrong that way, in
# the README, in SECURITY.md and in llms.txt, and none of them failed a commit gate. Checked offline
# against this list so it fails on the machine that introduced it.
OWNER = "Yoshiki0705"
PUBLISHED_REPOS = frozenset(
    {
        "s3-burst-on-ontap-files",
        "FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns",
        "FSx-for-ONTAP-Adoption-Playbook",
    }
)
# The character class excludes quotes and commas as well as the obvious delimiters: in prose and
# in Python fixtures a URL is routinely followed by one, and capturing it turns a correct name
# into an unknown one.
OWNER_URL = re.compile(rf"https://github\.com/{OWNER}/([^/#?\s)\"',]+)")


def check_owner_repo(url: str) -> str | None:
    """Whether a link to one of this owner's repositories names a published one."""
    match = OWNER_URL.match(url)
    if not match:
        return None
    name = match.group(1)
    if name in PUBLISHED_REPOS:
        return None
    return (
        f"unknown repository {name!r} for {OWNER}; a local directory name is not a repository name. "
        f"Published: {', '.join(sorted(PUBLISHED_REPOS))}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--external", action="store_true", help="also probe external URLs"
    )
    args = parser.parse_args()

    errors: list[str] = []
    internal_count = 0
    external_seen: dict[str, str | None] = {}

    # llms.txt is Markdown-shaped but not .md, so it would be silently exempt. It is the entry
    # point crawlers and agents read first, which makes it the worst place for a dead link.
    extra = [ROOT / "llms.txt"] if (ROOT / "llms.txt").exists() else []

    for path in [*iter_markdown(ROOT), *extra]:
        rel = path.relative_to(ROOT)
        for lineno, target in iter_links(path):
            scheme = urlparse(target).scheme
            if scheme in SKIP_SCHEMES:
                continue
            if scheme in ("http", "https"):
                # Runs without a network, so a wrong repository name fails the fast gate rather
                # than waiting for the weekly external probe.
                problem = check_owner_repo(target)
                if problem:
                    errors.append(f"{rel}:{lineno}: {problem} -> {target}")
                if not args.external:
                    continue
                if target not in external_seen:
                    external_seen[target] = check_external(target)
                problem = external_seen[target]
                if problem:
                    errors.append(f"{rel}:{lineno}: {problem} -> {target}")
                continue
            internal_count += 1
            problem = check_internal(path, target)
            if problem:
                errors.append(f"{rel}:{lineno}: {problem}")

    if errors:
        print(f"Link check failed ({len(errors)} issue(s)):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    summary = f"links: {internal_count} internal link(s) resolved"
    if args.external:
        summary += f", {len(external_seen)} external URL(s) reachable"
    print(summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
