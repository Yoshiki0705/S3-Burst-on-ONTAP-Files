#!/usr/bin/env python3
"""Validate a handoff contract: the file that carries one unit of delegation between repositories.

A handoff contract (design: データモデル > ハンドオフ契約) is how this Spoke hands a unit of work to
the Hub, or back. It is JSON with six required fields: who delegates, who receives, which Technical
Report, what deliverable is expected, what the receiving side must let the Spoke reference, and the
standing assertion that the public-output rules (naming, neutrality, PII, evidence stage) apply on
the far side too.

This gate checks two things, both offline:

  1. All six required fields are present and non-empty. A field that is absent, blank, an empty
     list, or ``None`` counts as missing, and ``public_output_rules_apply`` must be exactly ``True``
     -- the field asserts the rules apply, and ``False`` is not an acknowledgement of them.

  2. Any reference that points into another GitHub repository is an absolute URL (requirement 2.4).
     A relative link or a bare path resolves against the wrong repository root once it is read from
     the other side, so it cannot address another repository at all.

The behaviour on a problem is the one the design fixes under Error Handling: ``check()`` does not
raise. It returns a list of findings and leaves the caller holding whatever it had, rather than
losing the record to an exception. An empty list means the contract is sound.

Whether a cited reference actually resolves -- HTTP 404 -- is deliberately NOT checked here. That
needs the network, and this gate is offline and stdlib-only (the repository's运用 principle). The
existing ``make cross-repo-external``-style network gate owns that check; this file only validates
the *form* of a reference.

Run:  python3 tools/check_handoff_contract.py --contract PATH
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping
from pathlib import Path

# The six fields the design fixes as required. Named once here rather than written into each
# message, so the set and the checks cannot drift apart.
REQUIRED_FIELDS = (
    "delegator_repo",
    "delegatee_repo",
    "target_tr",
    "expected_deliverable",
    "reference_requirements",
    "public_output_rules_apply",
)

# A reference that looks like a repository-relative link rather than prose: it begins with a path
# segment, a parent-directory hop, or a leading slash, and it is not an absolute URL. These cannot
# address another GitHub repository (requirement 2.4). Prose that merely describes a requirement is
# not path-like and is left alone.
_PATH_LIKE_PREFIXES = ("../", "./", "/")


def _is_empty(value: object) -> bool:
    """True when a present field carries nothing a reader could act on.

    A blank string, an empty list, and ``None`` are each as absent as a missing key. Whitespace-only
    strings are blank too.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    if isinstance(value, (list, tuple, dict)):
        return len(value) == 0
    return False


def _looks_like_relative_path(reference: str) -> bool:
    """True when a reference is a repository-relative link, not prose and not an absolute URL."""
    text = reference.strip()
    if text.startswith("http://") or text.startswith("https://"):
        return False
    if text.startswith(_PATH_LIKE_PREFIXES):
        return True
    # A bare path with no scheme and no space, ending in a file extension, is a link written without
    # the leading `./` -- e.g. `docs/ja/x.md`. Prose contains spaces and does not end in a path
    # segment, so this does not fire on a sentence.
    return " " not in text and "/" in text and "." in text.rsplit("/", 1)[-1]


def check(contract: object) -> list[str]:
    """Return the findings for ``contract``; an empty list means it is sound.

    Does not raise on a missing field, a malformed value, or a non-object contract. The caller keeps
    whatever it had -- the design calls for reporting the problem and holding the record, not
    discarding it to an exception.
    """
    findings: list[str] = []

    if not isinstance(contract, Mapping):
        findings.append(
            "contract must be a JSON object with the six required fields; "
            f"got {type(contract).__name__}"
        )
        return findings

    for field in REQUIRED_FIELDS:
        if field not in contract or _is_empty(contract[field]):
            findings.append(
                f"required field {field!r} is missing or empty; the handoff is incomplete "
                f"and must not be delegated until it is supplied"
            )

    # public_output_rules_apply asserts the public-output rules apply on the receiving side. Present
    # but false is a refusal of that assertion, which is not a usable handoff.
    rules = contract.get("public_output_rules_apply")
    if rules is not None and rules is not True:
        findings.append(
            "field 'public_output_rules_apply' must be true; it asserts that the public-output "
            "rules (naming, neutrality, PII, evidence stage) apply on the receiving side, and a "
            "value other than true does not make that assertion"
        )

    # Any path-like reference into another repository must be an absolute URL (requirement 2.4).
    references = contract.get("reference_requirements")
    if isinstance(references, (list, tuple)):
        for reference in references:
            if isinstance(reference, str) and _looks_like_relative_path(reference):
                findings.append(
                    f"reference {reference!r} is a relative link; a cross-repository reference "
                    f"must be an absolute URL (絶対 URL) so it resolves from the other side "
                    f"(requirement 2.4)"
                )

    return findings


def _load(contract_path: Path) -> tuple[object, list[str]]:
    """Load the contract JSON; a read or parse failure is a finding, not an exception."""
    try:
        text = contract_path.read_text(encoding="utf-8")
    except OSError as error:
        return None, [f"{contract_path}: cannot read contract ({error})"]
    try:
        return json.loads(text), []
    except json.JSONDecodeError as error:
        return None, [f"{contract_path}: contract is not valid JSON ({error})"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--contract",
        type=Path,
        required=True,
        help="path to the handoff contract JSON to validate",
    )
    args = parser.parse_args()

    contract, load_findings = _load(args.contract)
    findings = load_findings or check(contract)

    if findings:
        print(
            f"handoff contract gate: {args.contract} is incomplete "
            f"({len(findings)} finding(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(
        f"handoff contract: {args.contract} has all required fields and valid references"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
