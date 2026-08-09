#!/usr/bin/env python3
"""Pre-publication audit for a public repository.

Adapted from the sibling repository `fsxn-adoption-playbook` (`tools/audit_public_output.py`).
Divergences, all additive:

* **`vendor-ref` line marker.** The forbidden-product check is now case-insensitive, because a
  lower-case mention in prose is the same mistake as a capitalised one. That makes it match the
  path of a legitimate citation URL, so a marker is needed for the case where the product name
  appears as evidence rather than as a proposal. The original had no such category, and the
  sibling patterns repository already used `allow:vendor-ref` in its prose — the marker existed
  as a convention before any script honoured it.
* **`neutrality` covers self-reference.** Declaring neutrality is itself banned here: this
  repository shows it by stating each option's exclusion conditions at the same granularity,
  including its own. A sentence announcing the policy reads as a defence and invites the framing
  it is trying to avoid.
* **`conflation` category.** ONTAP FlexCache duality and attaching an FSx for ONTAP S3 Access
  Point to a volume are separate mechanisms. Treating one as evidence for the other is the single
  most likely factual error in this repository, so a line naming both must also say they differ.

Escape hatches, because there are two genuinely different reasons for a false positive.

Line level - a single line legitimately contains a flagged pattern:

    Some verbatim citation title containing the short form   <!-- allow:naming -->
    [Client protocols](https://docs.netapp.com/...)          <!-- allow:vendor-ref -->

File level - the whole document's job is to *define* the rules, so it must quote what it forbids.
Declare it once anywhere in the first 40 lines:

    <!-- audit-file-allow: naming,neutrality,pii -->

`allow:all` opts a single line out entirely. Use every marker sparingly: each one is a claim that
the match is a false positive, and a reviewer should be able to see why at a glance.

Run:  python3 tools/audit_public_output.py [--path DIR]
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# tools/ and scripts/ hold the validators themselves; their pattern literals are the rules, not
# violations of them. .private/ and .kiro/ are never published.
SKIP_DIRS = (
    ".private",
    ".kiro",
    "node_modules",
    ".git",
    "tools",
    "scripts",
    # Generated caches. Their presence depends on whether tests have run, so leaving them in
    # scope makes the number of files audited vary for reasons unrelated to any change.
    ".pytest_cache",
    ".ruff_cache",
    "__pycache__",
    ".hypothesis",
    # .terraform/ holds the downloaded provider, which ships its own README and links.
    ".terraform",
)
SCAN_SUFFIXES = {".md", ".txt", ".yml", ".yaml", ".json"}

CATEGORIES = ("naming", "vendor-ref", "neutrality", "pii", "role-label", "conflation")
ALLOW = re.compile(
    r"allow:(naming|vendor-ref|neutrality|pii|role-label|conflation|all)"
)
# Bounded so the trailing "-->" of the HTML comment is not swallowed into the category list.
FILE_ALLOW = re.compile(r"audit-file-allow:\s*([a-z-]+(?:\s*,\s*[a-z-]+)*)")
FILE_ALLOW_SCAN_LINES = 40

# ---------------------------------------------------------------- naming

NAMING_RULES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bFSxN\b"), "use 'FSx for ONTAP'"),
    (re.compile(r"\bFSx\s+ONTAP\b"), "use 'FSx for ONTAP' (missing 'for')"),
    (re.compile(r"\bFSx\s+NetApp\b"), "use 'Amazon FSx for NetApp ONTAP'"),
]

# Suppressed by `naming` or by `vendor-ref`. The second exists for citation URLs and verbatim
# source titles, where the name is evidence rather than a recommendation.
FORBIDDEN_PRODUCTS = (
    re.compile(
        r"\bBlueXP\b|NetApp\s+Workload\s+Factory|NetApp\s+Console\b", re.IGNORECASE
    ),
    (
        "do not propose; reframe to CloudWatch / ONTAP REST API / FabricPool / DataSync / "
        "Snapshot-FlexClone-SnapMirror. If this is a citation URL or a verbatim source title, "
        "mark the line with allow:vendor-ref"
    ),
)

# Bare "FSx" that is prose rather than part of an accepted phrase or an identifier.
BARE_FSX = re.compile(
    r"\bFSx\b"
    r"(?!\s+for\s+(?:NetApp\s+)?ONTAP)"  # FSx for ONTAP / FSx for NetApp ONTAP
    r"(?!\s+for\s+(?:Windows|Lustre|OpenZFS))"  # sibling AWS services are legitimate
    r"(?!-for-ONTAP)"  # repo / URL slugs
    r"(?![-\w]*\.(?:md|py|ya?ml|json|svg|png|drawio))"  # filenames
)
# Contexts where "FSx" is a token, not prose.
IDENT_CONTEXT = re.compile(
    r"FSx[A-Za-z0-9_]*\s*[=:]|AWS::FSx|aws\s+fsx|\bfsx-|FSxOntap|FSX_|github\.com|https?://"
)

# ---------------------------------------------------------------- neutrality

NEUTRALITY_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"競合(ツール|製品|他社)|より優れて|優位性|劣[るっ]て"),
        "use right-tool-for-the-job framing; state trade-offs symmetrically",
    ),
    (
        re.compile(r"\b(?:beats|outperforms)\s+\w", re.IGNORECASE),
        "avoid vendor-versus phrasing",
    ),
    (
        re.compile(
            r"\b(?:is|are)\s+(?:far\s+)?(?:better|superior|inferior)\s+(?:than|to)\b",
            re.IGNORECASE,
        ),
        "state which option suits which context instead",
    ),
    (
        re.compile(
            r"\bgame[- ]changer\b|\bbest[- ]in[- ]class\b|\bindustry[- ]leading\b",
            re.IGNORECASE,
        ),
        "avoid marketing superlatives; show, don't tell",
    ),
    (
        re.compile(r"中立性|ベンダー中立|vendor[- ]neutral", re.IGNORECASE),
        (
            "do not declare neutrality; show it by stating every option's exclusion conditions "
            "at the same granularity, this architecture's own included"
        ),
    ),
]

# ---------------------------------------------------------------- conflation

DUALITY = re.compile(r"duality", re.IGNORECASE)
S3_AP = re.compile(r"S3\s*(?:AP\b|Access\s*Point)", re.IGNORECASE)
DISTINCTION = re.compile(r"別の機構|別機構|different\s+mechanism|separate\s+mechanism")

# ---------------------------------------------------------------- pii / internal identifiers

PII_RULES: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"\bcase\s*[#:]?\s*\d{5,}\b", re.IGNORECASE),
        "remove support case numbers; say 'filed with the vendor (tracked)'",
    ),
    (
        re.compile(r"\b[A-Z]{2,4}-I-\d{4,}\b"),
        "remove vendor-internal ticket IDs; say 'an internal product request (tracked)'",
    ),
    (
        re.compile(r"/Users/[A-Za-z][\w.-]*/"),
        "personal absolute path; use a relative path or ${PROJECT_DIR}",
    ),
    (
        re.compile(r"\b[\w.+-]+@(?!example\.(?:com|org)\b)[\w-]+\.[a-z]{2,}\b"),
        "remove email addresses; use '(internal reviewer)' or an example.com address",
    ),
    (
        re.compile(
            r"\b(?:10\.\d{1,3}|192\.168|172\.(?:1[6-9]|2\d|3[01]))\.\d{1,3}\.\d{1,3}\b"
        ),
        "mask internal IPs as 10.0.x.x or <management-ip>",
    ),
]

# 12-digit AWS account IDs other than the sanctioned placeholder.
ACCOUNT_ID = re.compile(r"(?<![\d.\w])\d{12}(?![\d.\w])")
PLACEHOLDER_ACCOUNT = "123456789012"

# Inline callouts labeled with a role/persona imply a review that did not happen.
ROLE_LABEL = re.compile(
    r"^\s*>\s*\*\*[^*]*(?:lens|の視点|perspective)[^*]*\*\*", re.IGNORECASE
)


def iter_files(root: Path):
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix.lower() in SCAN_SUFFIXES:
            yield path


def file_allowances(lines: list[str]) -> set[str]:
    """Categories a document opts out of wholesale via an audit-file-allow declaration."""
    allowed: set[str] = set()
    for line in lines[:FILE_ALLOW_SCAN_LINES]:
        match = FILE_ALLOW.search(line)
        if not match:
            continue
        for raw in match.group(1).split(","):
            category = raw.strip()
            if category in CATEGORIES:
                allowed.add(category)
            elif category:
                raise SystemExit(
                    f"audit-file-allow: unknown category {category!r} "
                    f"(allowed: {', '.join(CATEGORIES)})"
                )
    return allowed


def audit_line(
    line: str, file_allowed: frozenset[str] = frozenset()
) -> list[tuple[str, str]]:
    """Return (category, message) findings for one line, honouring allow markers."""
    allowed = {match.group(1) for match in ALLOW.finditer(line)} | set(file_allowed)
    if "all" in allowed:
        return []

    findings: list[tuple[str, str]] = []

    if "naming" not in allowed:
        for pattern, message in NAMING_RULES:
            if pattern.search(line):
                findings.append(("naming", message))
        if BARE_FSX.search(line) and not IDENT_CONTEXT.search(line):
            findings.append(("naming", "bare 'FSx'; use 'FSx for ONTAP'"))

    if not ({"naming", "vendor-ref"} & allowed):
        pattern, message = FORBIDDEN_PRODUCTS
        if pattern.search(line):
            findings.append(("vendor-ref", message))

    if "neutrality" not in allowed:
        for pattern, message in NEUTRALITY_RULES:
            if pattern.search(line):
                findings.append(("neutrality", message))

    if "pii" not in allowed:
        for pattern, message in PII_RULES:
            if pattern.search(line):
                findings.append(("pii", message))
        for match in ACCOUNT_ID.finditer(line):
            if match.group() != PLACEHOLDER_ACCOUNT:
                findings.append(
                    ("pii", f"possible AWS account ID; use {PLACEHOLDER_ACCOUNT}")
                )
                break

    if "role-label" not in allowed and ROLE_LABEL.match(line):
        findings.append(
            (
                "role-label",
                (
                    "role/persona-labeled callout implies a review that did not happen; "
                    "relabel to a neutral topic note (e.g. '**Security note**')"
                ),
            )
        )

    # A line naming both mechanisms has to say they are different. Satisfied by the prose itself,
    # so correct writing needs no marker; only a line that mixes them silently fails.
    if (
        "conflation" not in allowed
        and DUALITY.search(line)
        and S3_AP.search(line)
        and not DISTINCTION.search(line)
    ):
        findings.append(
            (
                "conflation",
                (
                    "FlexCache duality and attaching an FSx for ONTAP S3 Access Point are "
                    "separate mechanisms; say so on this line (別の機構 / different mechanism) "
                    "and do not use one as evidence for the other"
                ),
            )
        )

    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", default=str(ROOT), help="directory to audit")
    args = parser.parse_args()

    root = Path(args.path).resolve()
    findings: list[str] = []
    scanned = 0

    for path in iter_files(root):
        scanned += 1
        rel = path.relative_to(root)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            findings.append(f"{rel}: not valid UTF-8")
            continue
        file_allowed = frozenset(file_allowances(lines))
        for lineno, line in enumerate(lines, start=1):
            for category, message in audit_line(line, file_allowed):
                findings.append(f"{rel}:{lineno}: [{category}] {message}")

    if findings:
        print(f"Audit failed ({len(findings)} finding(s)):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1

    print(f"audit: {scanned} file(s) clean")
    return 0


if __name__ == "__main__":
    sys.exit(main())
