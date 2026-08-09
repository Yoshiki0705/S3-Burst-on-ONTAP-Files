#!/usr/bin/env python3
"""Keep the agent-facing documentation reachable, published, and within budget.

Adapted from the sibling repository `fsxn-s3ap-serverless-patterns`
(`scripts/check_agent_context_budget.py`). Divergences: the budget is 20,000 B rather than 28,000 B
because this repository is starting from nothing and the larger figure is what a grown repository
settled at, not a target to aim for; the per-topic budget for a dedicated `docs/agent/` tree is
dropped because knowledge here lives in the published `docs/` tree that human readers use; and the
messages are English to match the other validators in this directory.

Three failures are guarded here, all of which happened in the sibling repositories.

**AGENTS.md grew to 78 KB.** It is loaded on every turn and cannot be made conditional, so every
byte was paid for in every session — mostly for tables relevant only while doing one kind of work.
Splitting it out fixed the size, and nothing stopped it creeping back one useful paragraph at a
time. Prose asking future contributors to be disciplined does not survive contact with a deadline.
A failing check does.

**Eleven steering files declared `inclusion: auto` without the `name` and `description` that auto
inclusion requires.** Kiro never registered them, so roughly 110 KB of guidance was never loaded.
Nothing failed. An agent missing knowledge it was given looks exactly like an agent that was never
given it.

**The first split moved that content into `.kiro/`, which is deliberately not published.** The move
silently deleted public documentation and left twelve pointers resolving to nothing for anyone who
cloned the repository. Content therefore lives in `docs/` and `.kiro/` holds only the front matter
that decides when to load it. The loader budget below is what keeps it that way: a loader that
grows is knowledge leaking to the side nobody else can read.

Run:  python3 tools/check_agent_context_budget.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

AGENTS_BUDGET = 20_000
LOADER_BUDGET = 2_000

VALID_INCLUSION = {"always", "fileMatch", "manual", "auto"}
ROOT = Path(__file__).resolve().parent.parent
AGENTS = ROOT / "AGENTS.md"


def front_matter(path: Path) -> dict[str, str]:
    """Parse leading YAML front matter into top-level key/value pairs.

    A key whose value is an indented block is reported as ``"<block>"`` so callers can tell
    "present" from "omitted". An empty mapping means the file has no front matter.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    lines = text[3:end].splitlines()
    fields: dict[str, str] = {}
    for index, line in enumerate(lines):
        if not line.strip() or line.lstrip().startswith("#") or line[0] in " \t":
            continue
        key, sep, value = line.partition(":")
        if not sep:
            continue
        value = value.strip()
        if not value:
            for following in lines[index + 1 :]:
                if not following.strip():
                    continue
                if following[:1] in (" ", "\t"):
                    value = "<block>"
                break
        fields[key.strip()] = value
    return fields


def tracked() -> set[str] | None:
    """Paths git tracks, or None when git cannot answer.

    Only git decides what a reader of the repository can open. The filesystem says yes to files
    `.gitignore` excludes, which is how a link to a gitignored document ships and 404s for
    everyone but its author.
    """
    try:
        proc = subprocess.run(
            [
                "git",
                "-C",
                str(ROOT),
                "ls-files",
                "--cached",
                "--others",
                "--exclude-standard",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return {line for line in proc.stdout.splitlines() if line}


def kiro_present() -> bool:
    """Whether this checkout carries the local agent configuration at all.

    `.kiro/` is gitignored by design, so a clone and a CI runner have none of it. The loader checks
    are skipped there rather than reporting an expected absence as a finding: a check that is noisy
    in CI gets removed from CI.
    """
    return (ROOT / ".kiro/steering").is_dir() or (ROOT / ".kiro/skills").is_dir()


def check_budgets(problems: list[str]) -> None:
    """Append a problem for any agent-facing file over its budget."""
    size = len(AGENTS.read_bytes())
    if size > AGENTS_BUDGET:
        problems.append(
            f"AGENTS.md is {size:,} B, over the {AGENTS_BUDGET:,} B budget. It is loaded every "
            f"turn, so every byte is paid for in every session. Move whatever depends on the task "
            f"at hand into docs/ and leave one index line behind."
        )

    if not kiro_present():
        return

    loaders = sorted((ROOT / ".kiro/steering").glob("*.md")) + sorted(
        (ROOT / ".kiro/skills").glob("*/SKILL.md")
    )
    for path in loaders:
        fields = front_matter(path)
        if fields.get("inclusion") in {None, "always"} and "steering" in path.parts:
            continue  # always-on project steering may legitimately hold content
        size = len(path.read_bytes())
        if size > LOADER_BUDGET:
            problems.append(
                f"{path.relative_to(ROOT)} is {size:,} B, over the {LOADER_BUDGET:,} B budget. "
                f".kiro/ is not published, so the body belongs in docs/ and this file should hold "
                f"only the load condition and a pointer."
            )


def check_index_targets(problems: list[str]) -> None:
    """Append a problem for any AGENTS.md pointer a reader could not follow."""
    text = AGENTS.read_text(encoding="utf-8")
    published = tracked()

    links = re.findall(r"\]\((?!https?://|/|#|mailto:)([^)#\s]+)", text)
    if not any(link.startswith("docs/") for link in links):
        problems.append(
            "AGENTS.md does not reference docs/ anywhere. The entry point to the split-out "
            "knowledge is missing, which is how the knowledge stops being read."
        )
    for link in sorted(set(links)):
        target = ROOT / link
        if not target.exists():
            problems.append(f"AGENTS.md links to {link}, which does not exist.")
        elif published is not None and link not in published:
            problems.append(
                f"AGENTS.md links to {link}, which git does not track (gitignored). "
                f"It is a 404 for anyone who clones the repository."
            )
        if link.startswith(".kiro/"):
            problems.append(
                f"AGENTS.md links into .kiro/ ({link}). That directory is not published, so the "
                f"target belongs under docs/."
            )


def check_loaders(problems: list[str]) -> None:
    """Append a problem for each loader Kiro would never register, or that dangles."""
    if not kiro_present():
        return

    published = tracked()

    for path in sorted((ROOT / ".kiro/steering").glob("*.md")):
        fields = front_matter(path)
        name = path.relative_to(ROOT)
        inclusion = fields.get("inclusion")
        if inclusion is not None:
            if inclusion not in VALID_INCLUSION:
                problems.append(
                    f"{name}: inclusion '{inclusion}' is not a valid value."
                )
            if inclusion == "auto":
                for required in ("name", "description"):
                    if not fields.get(required):
                        problems.append(
                            f"{name}: inclusion:auto without '{required}'. In this state the "
                            f"file is never registered and never loaded."
                        )
            if inclusion == "fileMatch" and not fields.get("fileMatchPattern"):
                problems.append(
                    f"{name}: inclusion:fileMatch without fileMatchPattern."
                )
        _check_pointer(path, name, published, problems)

    for path in sorted((ROOT / ".kiro/skills").glob("*/SKILL.md")):
        fields = front_matter(path)
        name = path.relative_to(ROOT)
        expected = path.parent.name
        if fields.get("name") != expected:
            problems.append(
                f"{name}: name is {fields.get('name')!r} but the directory is {expected!r}. "
                f"The skill is not recognised."
            )
        if not fields.get("description"):
            problems.append(f"{name}: no description, so it is never invoked.")
        _check_pointer(path, name, published, problems)


def _check_pointer(
    path: Path, name: Path, published: set[str] | None, problems: list[str]
) -> None:
    """Verify every docs/ path a loader points at exists and is published."""
    body = path.read_text(encoding="utf-8")
    for target in sorted(set(re.findall(r"(docs/[A-Za-z0-9._/-]+\.md)", body))):
        if not (ROOT / target).exists():
            problems.append(
                f"{name}: points at {target}, which does not exist. Loading it yields nothing."
            )
        elif published is not None and target not in published:
            problems.append(
                f"{name}: points at {target}, which git does not track. The premise that the "
                f"body lives on the published side has broken."
            )


def main() -> int:
    problems: list[str] = []
    if not AGENTS.exists():
        print("AGENTS.md not found", file=sys.stderr)
        return 1

    check_budgets(problems)
    check_index_targets(problems)
    check_loaders(problems)

    if problems:
        print("agent context budget / reachability problems:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    size = len(AGENTS.read_bytes())
    if not kiro_present():
        print(
            f"agent context OK: AGENTS.md {size:,} B / {AGENTS_BUDGET:,} B. "
            f".kiro/ is absent from this checkout, so loaders were not checked."
        )
        return 0

    loaders = len(list((ROOT / ".kiro/steering").glob("*.md"))) + len(
        list((ROOT / ".kiro/skills").glob("*/SKILL.md"))
    )
    print(
        f"agent context OK: AGENTS.md {size:,} B / {AGENTS_BUDGET:,} B, {loaders} loader(s)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
