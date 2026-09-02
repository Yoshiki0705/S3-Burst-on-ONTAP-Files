#!/usr/bin/env python3
"""Reject characters EC2 will not accept in a security group rule description.

EC2 accepts only this set in a rule description:

    a-zA-Z0-9 and . _-:/()#,@[]+=&;{}!$*

An em dash, an apostrophe, a curly quote or a question mark fails the create with

    Invalid rule description. Valid descriptions are strings less than 256 characters from the
    following set: ...

**cfn-lint does not check this.** A template can be lint-clean, deploy-blocked, and give no
indication which character is at fault, because the message lists what is allowed rather than what
was rejected. That cost two stack creations in this repository before this gate existed, both times
on prose punctuation added while explaining why a rule was there.

The check is deliberately narrow. It looks only at Description on

    AWS::EC2::SecurityGroup
    AWS::EC2::SecurityGroupIngress
    AWS::EC2::SecurityGroupEgress

and at the SecurityGroupIngress / SecurityGroupEgress entries nested inside a SecurityGroup. A
parameter typed AWS::EC2::SecurityGroup::Id is not a rule and its description is unrestricted, so a
matcher keyed on the string "AWS::EC2::SecurityGroup" alone reports it and is wrong. The first
version of this check did exactly that; the "::Id" suffix is the whole difference.

Usage:
  python3 tools/check_sg_rule_descriptions.py [path ...]
"""

from __future__ import annotations

import pathlib
import re
import sys

ALLOWED = set(
    "abcdefghijklmnopqrstuvwxyz"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "0123456789"
    ". _-:/()#,@[]+=&;{}!$*"
)
MAX_LENGTH = 255

# The resource types whose Description is a rule description. Anchored at the end so that
# AWS::EC2::SecurityGroup::Id, a parameter type, does not match.
RULE_TYPES = re.compile(r"^AWS::EC2::SecurityGroup(Ingress|Egress)?$")

# Keys that introduce inline rule lists inside a SecurityGroup resource.
INLINE_RULE_KEYS = re.compile(r"^\s*(SecurityGroupIngress|SecurityGroupEgress):\s*$")

DESCRIPTION = re.compile(r"^(\s*)-?\s*Description:\s*(.*)$")
TYPE_LINE = re.compile(r"^\s*Type:\s*(\S+)\s*$")


def folded_value(lines: list[str], start: int, indent: int, first: str) -> str:
    """Join a scalar that may be folded across following, more-indented lines."""
    parts = []
    head = first.strip()
    if head not in (">-", ">", "|-", "|", ""):
        parts.append(head)
    for line in lines[start:]:
        if not line.strip():
            continue
        if (len(line) - len(line.lstrip())) <= indent:
            break
        parts.append(line.strip())
    return " ".join(parts)


def scan(path: pathlib.Path) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    problems: list[str] = []
    in_rule_resource = False
    in_inline_rules = False
    inline_indent = 0

    for number, line in enumerate(lines, start=1):
        type_match = TYPE_LINE.match(line)
        if type_match:
            in_rule_resource = bool(RULE_TYPES.match(type_match.group(1)))
            in_inline_rules = False

        if INLINE_RULE_KEYS.match(line):
            in_inline_rules = True
            inline_indent = len(line) - len(line.lstrip())
            continue
        if (
            in_inline_rules
            and line.strip()
            and (len(line) - len(line.lstrip())) <= inline_indent
        ):
            in_inline_rules = False

        if not (in_rule_resource or in_inline_rules):
            continue

        description_match = DESCRIPTION.match(line)
        if not description_match:
            continue
        indent = len(description_match.group(1))
        text = folded_value(lines, number, indent, description_match.group(2))
        rejected = sorted({character for character in text if character not in ALLOWED})
        if rejected:
            shown = " ".join(
                f"{character!r} (U+{ord(character):04X})" for character in rejected
            )
            problems.append(
                f"{path}:{number}: EC2 rejects {shown}\n"
                f"    {text[:120]}{'...' if len(text) > 120 else ''}"
            )
        elif len(text) > MAX_LENGTH:
            problems.append(
                f"{path}:{number}: {len(text)} characters, EC2 allows {MAX_LENGTH}"
            )
    return problems


def main() -> int:
    if len(sys.argv) > 1:
        targets = [pathlib.Path(argument) for argument in sys.argv[1:]]
    else:
        root = pathlib.Path(__file__).resolve().parent.parent
        targets = [
            path
            for pattern in ("*.yaml", "*.yml")
            for path in sorted(root.rglob(pattern))
            if ".git" not in path.parts and "node_modules" not in path.parts
        ]

    files = [path for path in targets if path.is_file()]
    if not files:
        # A scan that could not run must say so rather than report a clean result.
        print(
            "check_sg_rule_descriptions: no YAML files found - refusing to report a pass"
        )
        return 1

    problems: list[str] = []
    for path in files:
        problems.extend(scan(path))

    if problems:
        print(f"Security group rule descriptions EC2 will reject ({len(problems)}):\n")
        for problem in problems:
            print(problem)
        print(
            "\nEC2 allows only a-zA-Z0-9 and . _-:/()#,@[]+=&;{}!$*\n"
            "Replace an em dash with a colon, and an apostrophe by rewording."
        )
        return 1

    print(
        f"Security group rule descriptions: {len(files)} file(s) scanned, all characters accepted"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
