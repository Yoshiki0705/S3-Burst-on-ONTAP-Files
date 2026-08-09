#!/usr/bin/env python3
"""Every GitHub Action must be pinned to a full commit SHA, with the version in a comment.

A tag is a moving pointer. `uses: some/action@v4` runs whatever `v4` points at when the workflow
runs, and a tag can be repointed by whoever owns the repository — so a compromised or simply changed
action executes in a job that has a token, without any commit in this repository. Pinning to a
40-character SHA makes the dependency immutable; the trailing `# v4.4.0` comment is what keeps it
readable and lets a bot propose an upgrade.

Two failure modes are checked separately because they need different fixes:

* an unpinned reference — replace the tag with the SHA it currently resolves to;
* a pinned reference with no version comment — the SHA is safe but nobody can tell what it is, so
  the next person either leaves it stale forever or unpins it to find out.

Local actions (`./.github/actions/…`) and reusable workflows in this repository are exempt: they are
already this repository's own code, at this repository's own commit.

Run:  python3 tools/check_actions_pinning.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"

USES = re.compile(r"^\s*(?:-\s*)?uses:\s*(?P<ref>[^\s#]+)\s*(?P<comment>#.*)?$")
SHA = re.compile(r"^[0-9a-f]{40}$")
VERSION_COMMENT = re.compile(r"#\s*v?\d+")


def workflow_files() -> list[Path]:
    if not WORKFLOWS.is_dir():
        return []
    return sorted(
        path for pattern in ("*.yml", "*.yaml") for path in WORKFLOWS.glob(pattern)
    )


def check_line(line: str) -> str | None:
    """Return a problem description for one `uses:` line, or None when it is fine."""
    match = USES.match(line)
    if not match:
        return None
    ref = match.group("ref")
    comment = match.group("comment") or ""

    if ref.startswith("./") or ref.startswith("."):
        return None  # local action or reusable workflow in this repository

    if "@" not in ref:
        return f"{ref} has no version at all; pin it to a full commit SHA"

    action, _, version = ref.rpartition("@")
    if not SHA.match(version):
        return (
            f"{action} is pinned to {version!r}, which is a moving pointer. Pin the full commit "
            f"SHA and put the version in a trailing comment: {action}@<sha> # {version}"
        )
    if not VERSION_COMMENT.search(comment):
        return (
            f"{action} is pinned to a SHA but carries no version comment, so nobody can tell which "
            f"release it is. Add a trailing '# v<version>'"
        )
    return None


def main() -> int:
    files = workflow_files()
    if not files:
        print(
            "no workflow files found under .github/workflows; nothing was checked",
            file=sys.stderr,
        )
        return 1

    findings: list[str] = []
    checked = 0
    for path in files:
        rel = path.relative_to(ROOT)
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not USES.match(line):
                continue
            checked += 1
            problem = check_line(line)
            if problem:
                findings.append(f"{rel}:{lineno}: {problem}")

    if not checked:
        print(
            f"no `uses:` references found across {len(files)} workflow file(s); either the "
            f"workflows call no actions or this check has stopped matching them",
            file=sys.stderr,
        )
        return 1

    if findings:
        print(f"Action pinning failed ({len(findings)} finding(s)):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\n  Resolve a tag to its SHA with:\n"
            "    gh api repos/<owner>/<repo>/commits/<tag> --jq .sha",
            file=sys.stderr,
        )
        return 1

    print(
        f"actions: {checked} reference(s) across {len(files)} workflow(s) pinned to a SHA"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
