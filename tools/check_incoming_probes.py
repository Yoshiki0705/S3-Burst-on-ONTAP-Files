#!/usr/bin/env python3
"""Verify the claim-bearing strings a sibling repository probes for in this repository.

Thirty-two claims here are cited by FSx-for-ONTAP-Adoption-Playbook, which registers an exact
substring per citation and fails its own gate when the substring is gone. That is the intended
design: a retraction here surfaces there rather than leaving a stale sentence behind. But it puts
the discovery in the wrong place -- the person who reworded the sentence learns about it from
another repository's CI, and until it is fixed the Playbook's guidance is published without the
evidence under it.

This checker moves the discovery to the commit that causes it. The sibling publishes the
registration (`docs/agent/cross-repo-probe-contract.txt`), generated from its own index and checked
against it there, and this reads that file rather than parsing the index. A second reader of a
markdown table is a second thing to be wrong.

**Each probe is an opaque byte substring and nothing is normalised.** The sibling's index escapes
some strings and the escaping is not uniform: one probe carries `**` emphasis as part of the claim,
another is quoted in double backticks in the table because it contains a backtick, a third
deliberately excludes the `**` that surrounds it here. Stripping emphasis to be helpful would make
the first match text that no longer contains the claim; failing to strip the table's own wrapper
would make the second never match and report a false break. So the contract carries the literal
bytes to search for, and this does a plain substring test.

Two roles, and they are not the same question:

  retraction  the string must be present. Missing it means the claim was withdrawn or reworded,
              and the citation over there has lost its evidence. **Fails.**
  reread      the string is expected to move. It pins the minimum and maximum of a measurement set,
              so adding a measurement rewrites the range by construction. Firing is not a
              retraction. **Warns.**

Seven of the retraction probes carry an *absence* ("not confirmed", "not listed as supported"). Those
go missing when the absence stops being true, which is progress rather than a withdrawal -- and it is
exactly the case where this repository has to tell the sibling rather than let its CI find out. That
is why they fail here instead of warning.

Needs a local checkout of the sibling repository, so it skips with a message when there is none, the
way the external-anchors, gitleaks and checkov targets do. Set SIBLING_PLAYBOOK to override the
default path. `--fetch` reads the published contract over the network instead, for the scheduled job.

Run:  python3 tools/check_incoming_probes.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent

# Both names, for the same reason check_external_anchors.py holds both: the repository was renamed
# from fsxn-adoption-playbook, so a clone made before the rename carries the old name. Holding only
# one meant a checkout went unfound and the skip stood in for a pass.
CHECKOUT_NAMES = ("FSx-for-ONTAP-Adoption-Playbook", "fsxn-adoption-playbook")
CONTRACT = Path("docs/agent/cross-repo-probe-contract.txt")
RAW_CONTRACT = (
    "https://raw.githubusercontent.com/Yoshiki0705/"
    "FSx-for-ONTAP-Adoption-Playbook/main/" + CONTRACT.as_posix()
)

# The name the sibling's registration uses for this repository, in the first field.
THIS_REPO = "S3-Burst-on-ONTAP-Files"

FAIL_ROLE = "retraction"
WARN_ROLE = "reread"
ROLES = (FAIL_ROLE, WARN_ROLE)

# The sibling states its vocabulary is these two and that its own gate rejects a third. A value this
# does not recognise is therefore either a format change nobody announced or a typo, and both are
# reasons to stop rather than to skip the row. Guessing which is how a probe stops being checked
# while the output still says everything passed.
UNKNOWN_ROLE_FAILS = True

# **Flip this to True when the sibling publishes the contract**, which it had not when this was
# written (agreed on S3-Burst-on-ONTAP-Files#121; the sibling's change is its #172).
#
# It decides what a 404 from --fetch means, and the two meanings are opposite. Not published yet: a
# skip is correct. Published and then removed or renamed: the registration this repository depends on
# is gone, and a skip would report that as a clean run forever. There is no way to tell those apart
# from the response, and deriving it from a local checkout does not work either -- CI has no
# checkout, so every 404 would read as "not published yet" on exactly the runner where this is the
# only thing that runs. So it is an explicit switch, and the flip is a deliberate act.
CONTRACT_PUBLISHED = False

# Zero rows for this repository, from a contract that parsed, is not "nothing to check" -- it means
# the repository name or the field order moved. Thirty-two rows were registered when this was
# written. A scan that finds nothing has to say so rather than report a clean run.
EXPECT_AT_LEAST_ONE_ROW = True


class Probe(NamedTuple):
    path: str
    role: str
    text: str


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


def parse_contract(body: str) -> tuple[list[Probe], list[str]]:
    """Four TAB-separated fields: repo, path, role, string. The string is last and is taken whole.

    Last on purpose: a probe can contain any character except a tab, so anything after the third tab
    is the string, including further tabs if one ever appears. Splitting with a maxsplit rather than
    a plain split is what makes that true.

    `#` starts a comment only at the beginning of a line. A probe string can contain one, and a
    lookalike test anywhere in the line would silently drop those rows.
    """
    probes: list[Probe] = []
    problems: list[str] = []
    for number, raw in enumerate(body.splitlines(), start=1):
        if not raw.strip() or raw.startswith("#"):
            continue
        fields = raw.split("\t", 3)
        if len(fields) != 4:
            problems.append(
                f"line {number}: expected 4 tab-separated fields (repo, path, role, string), "
                f"got {len(fields)}. The string field is last and is taken whole."
            )
            continue
        repo, path, role, text = fields
        if repo.strip() != THIS_REPO:
            continue
        if not text:
            problems.append(f"line {number}: empty probe string for {path}")
            continue
        if role.strip() not in ROLES and UNKNOWN_ROLE_FAILS:
            problems.append(
                f"line {number}: unknown role '{role.strip()}' for {path}. "
                f"Expected one of {', '.join(ROLES)}. Either the vocabulary grew without notice "
                "or this is a typo; both need reading before the row is skipped."
            )
            continue
        # No .strip() on the text: leading or trailing whitespace could be part of the substring the
        # sibling chose, and trimming it here would change what is being looked for.
        probes.append(Probe(path=path.strip(), role=role.strip(), text=text))
    return probes, problems


def contract_from(base: Path) -> tuple[list[Probe], list[str]]:
    return parse_contract((base / CONTRACT).read_text(encoding="utf-8"))


def fetch_contract() -> tuple[list[Probe] | None, list[str]]:
    """Read the contract as published, not as it happens to sit on this disk.

    A local checkout can be behind, so a probe can be satisfied here against a registration the
    sibling has already changed. Needs the network, so it belongs with the other network job rather
    than in `make all`.

    Returns `(None, [])` for the one case that is not an error: a 404 while CONTRACT_PUBLISHED is
    False, meaning the contract does not exist yet.
    """
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(RAW_CONTRACT, timeout=30) as response:  # noqa: S310
            if response.status != 200:
                raise SystemExit(
                    f"incoming-probes: {RAW_CONTRACT} returned {response.status}"
                )
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404 and not CONTRACT_PUBLISHED:
            return None, []
        raise SystemExit(
            f"incoming-probes: {RAW_CONTRACT} returned {error.code}. "
            + (
                "The contract was published, so this is a removal or a rename rather than an "
                "absence -- the registration this repository is checked against is gone."
                if CONTRACT_PUBLISHED
                else "Not a 404, so this is not the expected 'not published yet'."
            )
        ) from error
    return parse_contract(body)


def check(probes: list[Probe]) -> tuple[list[str], list[str]]:
    """Substring test per probe. Failures for retraction, warnings for reread."""
    failures: list[str] = []
    warnings: list[str] = []
    cache: dict[str, str | None] = {}

    for probe in probes:
        if probe.path not in cache:
            target = ROOT / probe.path
            cache[probe.path] = (
                target.read_text(encoding="utf-8") if target.is_file() else None
            )
        body = cache[probe.path]

        if body is None:
            # The path is part of the registration, so a moved or deleted file breaks every probe
            # against it. Reported once per probe rather than once per file, because the sibling
            # needs to know which claims lost their target.
            failures.append(
                f"{probe.path}: file not found, so the {probe.role} probe {probe.text!r} "
                "cannot resolve. Moving or renaming a cited file breaks the citation over there "
                "even when the text survives."
            )
            continue

        if probe.text in body:
            continue

        if probe.role == FAIL_ROLE:
            failures.append(
                f"{probe.path}: {probe.text!r} is gone. The Playbook cites this claim and its "
                "gate will report it. If the claim was withdrawn, say so there; if this was a "
                "rewording, restore the string or agree a replacement first."
            )
        else:
            warnings.append(
                f"{probe.path}: {probe.text!r} is gone. This probe pins the minimum and maximum "
                "of a measurement set, so a new measurement is expected to move it. **Not a "
                "retraction** -- tell the Playbook the range changed and why."
            )
    return failures, warnings


def main() -> int:
    if "--fetch" in sys.argv:
        fetched, problems = fetch_contract()
        if fetched is None:
            print(
                "incoming-probes: SKIPPED, the sibling has not published "
                f"{CONTRACT.as_posix()} yet (404). Flip CONTRACT_PUBLISHED in this file when it "
                "lands, so that a later 404 reads as a removal rather than as this."
            )
            return 0
        probes, source = fetched, "the published contract"
    else:
        base = checkout()
        if base is None:
            # A contributor without the sibling clone is not blocked by a check about someone
            # else's citations. But the skip has to read as a skip, and it names both reasons it
            # can happen -- the contract is newer than this checker, so "not published yet" and
            # "no checkout" are different situations with the same symptom today.
            print(
                "incoming-probes: SKIPPED, no sibling probe contract found "
                f"(looked for {CONTRACT.as_posix()} beside this repository under "
                f"{' or '.join(CHECKOUT_NAMES)}, or set SIBLING_PLAYBOOK). "
                "Either the checkout is absent or the sibling has not published the contract yet; "
                "until it exists, a reworded claim here is caught by the Playbook's CI instead of "
                "by this gate."
            )
            return 0
        probes, problems = contract_from(base)
        source = base.name

    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"incoming-probes: {len(problems)} unreadable row(s) in the contract "
            f"({source}). Not treated as a pass: an unparsed row is an unchecked claim.",
            file=sys.stderr,
        )
        return 1

    if not probes and EXPECT_AT_LEAST_ONE_ROW:
        print(
            f"incoming-probes: the contract ({source}) parsed but holds no row for "
            f"{THIS_REPO}. Thirty-two were registered when this check was written, so this is a "
            "changed repository name or field order rather than an empty registration.",
            file=sys.stderr,
        )
        return 1

    failures, warnings = check(probes)

    for warning in warnings:
        print(f"  reread: {warning}")
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)

    if failures:
        print(
            f"incoming-probes: {len(failures)} cited claim(s) no longer resolve "
            f"({source})",
            file=sys.stderr,
        )
        return 1

    counts = {role: sum(1 for p in probes if p.role == role) for role in ROLES}
    summary = ", ".join(f"{counts[role]} {role}" for role in ROLES)
    tail = f", {len(warnings)} reread probe(s) moved" if warnings else ""
    print(
        f"incoming-probes: {len(probes)} probe(s) resolve ({summary}) ({source}){tail}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
