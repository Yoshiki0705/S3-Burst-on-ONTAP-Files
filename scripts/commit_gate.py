#!/usr/bin/env python3
"""Block a commit whose message or branch name would be a problem once it is public.

Branch names and commit messages are public output. They are indexed, quoted in release notes, and
effectively permanent — a squash merge keeps the pull request title in `main` forever, and a merge
commit embeds the branch name. Unlike a document, none of it can be corrected later without
rewriting history.

The content rules are **not reimplemented here.** This calls
`tools/audit_public_output.audit_line`, the same function `make audit` uses on documents. Two copies
of a rule set means one of them is out of date, and the one nobody runs is the one that rots. What
this file adds is the part that has no document equivalent: the shape of a subject line, the shape of
a branch name, and the fact that both are read as a verdict on whatever came before.

Standalone, so it can be tested and run by hand:

    python3 scripts/commit_gate.py --message "docs: separate the two mechanisms"
    python3 scripts/commit_gate.py --branch docs/mechanism-distinction

As a Kiro `PreToolUse` hook it reads the hook payload on stdin, finds the `git commit` in the
command, and exits 2 to block with the reason on stderr.

    python3 scripts/commit_gate.py --hook
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import audit_public_output as audit  # noqa: E402

TYPES = (
    "feat",
    "fix",
    "docs",
    "chore",
    "refactor",
    "test",
    "ci",
    "perf",
    "style",
    "bench",
)
SUBJECT = re.compile(rf"^({'|'.join(TYPES)})(\([a-z0-9-]+\))?: .+")
SUBJECT_LIMIT = 72

BRANCH = re.compile(r"^(?:[a-z0-9]+)/[a-z0-9]+(?:-[a-z0-9]+)*$")
BRANCH_LIMIT = 40
PROTECTED_BRANCHES = {"main", "master"}

# A branch or subject naming what was previously wrong reads as a verdict on earlier work, and it
# stays visible on the pull request page indefinitely. Name what the change adds instead.
BLAMING = re.compile(
    r"\b(?:fix(?:ing)?-?(?:broken|bad|wrong|stupid)|broken|wrong|bad|stupid|useless|"
    r"garbage|mess|nonsense)\b",
    re.IGNORECASE,
)
# Process metadata dates immediately and means nothing to a reader.
PROCESS_NOISE = re.compile(
    r"\b(?:\d{8}|\d{4}-\d{2}-\d{2}|phase\d+|round-?\d+|session-?\d+|wip|tmp|temp|"
    r"r\d+f\d+)\b",
    re.IGNORECASE,
)

# The audit categories that make sense for a message. `role-label` matches a blockquote callout,
# which a commit message does not have.
MESSAGE_CATEGORIES = {"naming", "vendor-ref", "neutrality", "pii", "conflation"}


def check_subject(subject: str) -> list[str]:
    problems: list[str] = []
    if not subject.strip():
        return ["commit subject is empty"]
    if not SUBJECT.match(subject):
        problems.append(
            f"subject must be '<type>(<scope>): <what changed>' with type in "
            f"{', '.join(TYPES)}; got {subject!r}"
        )
    if len(subject) > SUBJECT_LIMIT:
        problems.append(
            f"subject is {len(subject)} characters; keep it under {SUBJECT_LIMIT}"
        )
    if subject.endswith("."):
        problems.append("subject must not end with a period")
    if BLAMING.search(subject):
        problems.append(
            "subject describes what was wrong before. State what this change adds — the line is "
            "permanent and reads as a verdict on earlier work"
        )
    if PROCESS_NOISE.search(subject):
        problems.append(
            "subject carries process metadata (a date, phase, round, session or WIP marker). "
            "It dates immediately and means nothing to a reader of git log"
        )
    return problems


def check_branch(name: str) -> list[str]:
    problems: list[str] = []
    if name in PROTECTED_BRANCHES:
        return [
            f"refusing to work directly on {name!r}; branch first "
            f"(<type>/<what>, for example docs/mechanism-distinction)"
        ]
    if not BRANCH.match(name):
        problems.append(
            f"branch must be '<type>/<what>' in lowercase kebab-case ASCII; got {name!r}"
        )
    if len(name) > BRANCH_LIMIT:
        problems.append(
            f"branch name is {len(name)} characters; keep it under {BRANCH_LIMIT}"
        )
    if BLAMING.search(name):
        problems.append(
            "branch name describes what was wrong before. Name what it adds — the name stays on "
            "the pull request page permanently"
        )
    if PROCESS_NOISE.search(name):
        problems.append(
            "branch name carries a date, phase, round or session marker. It rots immediately and "
            "leaks process into public output"
        )
    return problems


def check_content(message: str) -> list[str]:
    """Run the document audit over the message, keeping only the categories that apply."""
    problems: list[str] = []
    for lineno, line in enumerate(message.splitlines(), start=1):
        for category, detail in audit.audit_line(line):
            if category in MESSAGE_CATEGORIES:
                problems.append(f"line {lineno}: [{category}] {detail}")
    return problems


def check_message(message: str) -> list[str]:
    lines = message.splitlines()
    subject = lines[0] if lines else ""
    problems = check_subject(subject)
    if len(lines) > 1 and lines[1].strip():
        problems.append("leave a blank line between the subject and the body")
    return problems + check_content(message)


def current_branch() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    name = proc.stdout.strip()
    return name or None


def message_from_command(command: str) -> str | None:
    """Extract the message from a `git commit -m …` command line.

    Returns None when the command is not a commit or carries no inline message — an interactive
    commit opens an editor, and this gate has nothing to inspect at that point.
    """
    try:
        argv = shlex.split(command)
    except ValueError:
        return None
    if "git" not in argv or "commit" not in argv:
        return None
    parts: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token in ("-m", "--message") and index + 1 < len(argv):
            parts.append(argv[index + 1])
            index += 2
            continue
        if token.startswith("--message="):
            parts.append(token.split("=", 1)[1])
        elif token.startswith("-m") and len(token) > 2:
            parts.append(token[2:])
        index += 1
    return "\n\n".join(parts) if parts else None


def run_hook() -> int:
    """Inspect a Kiro hook payload on stdin. Exit 2 blocks the tool call."""
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0  # nothing to inspect; never block on a payload we cannot read

    command = ""
    if isinstance(payload, dict):
        for key in ("command", "input", "toolInput", "arguments"):
            value = payload.get(key)
            if isinstance(value, str):
                command = value
                break
            if isinstance(value, dict) and isinstance(value.get("command"), str):
                command = value["command"]
                break

    message = message_from_command(command)
    if message is None:
        return 0

    problems = check_message(message)
    branch = current_branch()
    if branch:
        problems += check_branch(branch)

    if problems:
        print(
            "commit gate: this commit would be a problem once public:", file=sys.stderr
        )
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "\n  Branch names and commit messages cannot be corrected without rewriting history.",
            file=sys.stderr,
        )
        return 2
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--message", help="commit message to check")
    parser.add_argument("--branch", help="branch name to check")
    parser.add_argument(
        "--hook", action="store_true", help="read a Kiro hook payload on stdin"
    )
    args = parser.parse_args()

    if args.hook:
        return run_hook()

    problems: list[str] = []
    if args.message:
        problems += check_message(args.message)
    if args.branch:
        problems += check_branch(args.branch)
    if not args.message and not args.branch:
        parser.error("give --message, --branch or --hook")

    if problems:
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print("commit gate: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
