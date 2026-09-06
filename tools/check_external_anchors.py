#!/usr/bin/env python3
"""Verify the section anchors this repository cites in a sibling repository.

Twenty-odd claims here are carried by a link into a section of another repository's note. GitHub
serves the page whatever the fragment says, so a renamed heading redirects a citation to the top of a
long document and no link checker anywhere reports it: `check_links.py` resolves paths, and the
external probe only asks whether the URL responds.

The sibling repository publishes the anchors it considers a contract, generated from its own headings
(`docs/agent/external-anchor-contract.txt`). This reads that file rather than re-deriving the slug
rule, because a second implementation of GitHub's slug algorithm is a second thing to be wrong. The
rule was checked against theirs once -- it reproduced all 89 anchors -- and this checker exists so that
the comparison does not depend on having done it.

Needs a local checkout of the sibling repository, so it skips with a message when there is none, the
way the gitleaks and checkov targets do. Set SIBLING_PLAYBOOK to override the default path.

Run:  python3 tools/check_external_anchors.py
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Both names, because a working directory is named by whoever cloned it. The repository is
# FSx-for-ONTAP-Adoption-Playbook and was renamed from fsxn-adoption-playbook, so a clone made
# before the rename still carries the old name and a fresh one carries the new. Holding only the
# old name meant a fresh clone had no checkout, and this check reported a skip as a pass.
CHECKOUT_NAMES = ("FSx-for-ONTAP-Adoption-Playbook", "fsxn-adoption-playbook")
DEFAULT_CHECKOUT = ROOT.parent / CHECKOUT_NAMES[0]
CONTRACT = Path("docs/agent/external-anchor-contract.txt")
REPO_URL = "https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/"
RAW_CONTRACT = (
    "https://raw.githubusercontent.com/Yoshiki0705/"
    "FSx-for-ONTAP-Adoption-Playbook/main/docs/agent/external-anchor-contract.txt"
)
CITATION = re.compile(re.escape(REPO_URL) + r"(docs/[^)#\s]+)(?:#([^)\s]+))?")
SCAN_SUFFIXES = {".md", ".txt", ".json", ".yaml", ".yml"}


def checkout() -> Path | None:
    explicit = os.environ.get("SIBLING_PLAYBOOK")
    candidates = (
        [Path(explicit).expanduser()]
        if explicit
        else [ROOT.parent / name for name in CHECKOUT_NAMES]
    )
    for path in candidates:
        if (path / CONTRACT).is_file():
            return path
    return None


def fetch_contract() -> dict[str, set[str]]:
    """Read the contract from the published repository.

    The local checkout is whatever is on disk, which can be behind what the sibling published --
    so a citation can resolve here and land at the top of a renamed section for a reader. Fetching
    checks the same thing against what is actually served. Needs the network, so it belongs beside
    the other network job rather than in `make all`.
    """
    import urllib.request

    with urllib.request.urlopen(RAW_CONTRACT, timeout=30) as response:
        if response.status != 200:
            raise SystemExit(
                f"external-anchors: {RAW_CONTRACT} returned {response.status}"
            )
        body = response.read().decode("utf-8")
    return parse_contract(body)


def parse_contract(body: str) -> dict[str, set[str]]:
    """Path to anchors, as the sibling repository publishes them."""
    entries: dict[str, set[str]] = {}
    for line in body.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        path, _, anchor = line.partition("#")
        entries.setdefault(path, set())
        if anchor:
            entries[path].add(anchor)
    return entries


def contract(base: Path) -> dict[str, set[str]]:
    return parse_contract((base / CONTRACT).read_text(encoding="utf-8"))


def citations() -> list[tuple[str, str, str | None]]:
    listing = subprocess.run(
        ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout.split()
    found = []
    for name in listing:
        path = ROOT / name
        if path.suffix not in SCAN_SUFFIXES:
            continue
        for match in CITATION.finditer(path.read_text(encoding="utf-8")):
            found.append((name, match.group(1), match.group(2)))
    return found


def main() -> int:
    if "--fetch" in sys.argv:
        published, source_name = fetch_contract(), "the published repository"
    else:
        base = checkout()
        if base is None:
            # Still not an error: a contributor without the sibling clone should not be blocked by a
            # check about someone else's headings. But the skip has to read as a skip, and the
            # scheduled --fetch run is what stops a permanent skip from standing in for a check.
            print(
                "external-anchors: SKIPPED, no sibling checkout found "
                f"(looked beside this repository for {' or '.join(CHECKOUT_NAMES)}, or set "
                "SIBLING_PLAYBOOK). The scheduled link-rot workflow runs this with --fetch."
            )
            return 0
        published, source_name = contract(base), base.name
    found = citations()
    if not found:
        print("external-anchors: no citation into the sibling repository")
        return 0

    problems = []
    for source, path, anchor in found:
        if path not in published:
            problems.append(
                f"{source}: cites {path}, which the sibling repository does not list as tracked. "
                "Ask for it to be added to tracked_files() there, or the rename of a heading in it "
                "will not be caught."
            )
        elif anchor and anchor not in published[path]:
            problems.append(
                f"{source}: anchor '#{anchor}' is not in the published contract for {path}. "
                "The heading was probably renamed; GitHub still serves the page, so this is a "
                "citation that silently lands at the top."
            )

    for problem in problems:
        print(f"  {problem}", file=sys.stderr)
    if problems:
        print(f"external-anchors: {len(problems)} broken citation(s)", file=sys.stderr)
        return 1
    anchored = sum(1 for _, _, anchor in found if anchor)
    print(
        f"external-anchors: {anchored} anchored citation(s) resolve against the published contract "
        f"({source_name})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
