#!/usr/bin/env python3
"""Verify the claim-bearing strings a sibling repository probes for in this repository.

Claims here are cited by sibling repositories, each of which registers an exact substring per
citation and fails its own gate when the substring is gone. That is the intended design: a
retraction here surfaces there rather than leaving a stale sentence behind. But it puts the
discovery in the wrong place -- the person who reworded the sentence learns about it from another
repository's CI, and until it is fixed that repository's guidance is published without the evidence
under it.

**Every citing repository is read, not one.** Naming a single sibling was a real gap rather than a
simplification: a second repository published its registration and this gate did not look at it, so
the discovery stayed in the wrong place for exactly the claims it was meant to protect.

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

CONTRACT = Path("docs/agent/cross-repo-probe-contract.txt")

# The name the sibling's registration uses for this repository, in the first field.
THIS_REPO = "S3-Burst-on-ONTAP-Files"


class Sibling(NamedTuple):
    """A repository that cites claims here and publishes what it cites.

    `checkout_names` holds every name a local clone can carry, for the same reason
    check_external_anchors.py does: a repository that was renamed leaves older clones under the old
    name, and holding only one meant a checkout went unfound while the skip stood in for a pass.

    `published` decides what a 404 from --fetch means, and the two meanings are opposite. Not
    published yet: a skip is correct. Published and then removed or renamed: the registration this
    repository is checked against is gone, and a skip would report that as a clean run forever. There
    is no way to tell those apart from the response, so it is an explicit switch per sibling.

    `rows_when_written` is for the message only. Asserting the count would fail the moment a sibling
    legitimately drops a citation; what has to fail is *zero* rows from a contract that parsed, which
    means the repository name or the field order moved.
    """

    label: str
    checkout_names: tuple[str, ...]
    env_override: str
    published: bool
    rows_when_written: int

    @property
    def raw_contract(self) -> str:
        return (
            "https://raw.githubusercontent.com/Yoshiki0705/"
            f"{self.label}/main/" + CONTRACT.as_posix()
        )


# **More than one repository cites this one, so more than one contract has to be read.** Naming a
# single sibling was a real gap: VMware-Migration-EC2-ONTAP published its registration and this gate
# did not look at it, so a rewording here would have been caught only by that repository's own CI --
# which is precisely the discovery-in-the-wrong-place problem this checker exists to fix. It built its
# own outgoing check rather than wait, which is the right call: its protection should not depend on a
# change landing here.
SIBLINGS: tuple[Sibling, ...] = (
    Sibling(
        label="FSx-for-ONTAP-Adoption-Playbook",
        checkout_names=("FSx-for-ONTAP-Adoption-Playbook", "fsxn-adoption-playbook"),
        env_override="SIBLING_PLAYBOOK",
        published=True,
        rows_when_written=32,
    ),
    Sibling(
        label="VMware-Migration-EC2-ONTAP",
        checkout_names=("VMware-Migration-EC2-ONTAP",),
        env_override="SIBLING_VMWARE",
        published=True,
        rows_when_written=5,
    ),
)

FAIL_ROLE = "retraction"
WARN_ROLE = "reread"
ROLES = (FAIL_ROLE, WARN_ROLE)

# The sibling states its vocabulary is these two and that its own gate rejects a third. A value this
# does not recognise is therefore either a format change nobody announced or a typo, and both are
# reasons to stop rather than to skip the row. Guessing which is how a probe stops being checked
# while the output still says everything passed.
UNKNOWN_ROLE_FAILS = True

# Zero rows for this repository, from a contract that parsed, is not "nothing to check" -- it means
# the repository name or the field order moved. A scan that finds nothing has to say so rather than
# report a clean run.
EXPECT_AT_LEAST_ONE_ROW = True


class Probe(NamedTuple):
    path: str
    role: str
    text: str


def checkout(sibling: Sibling) -> Path | None:
    explicit = os.environ.get(sibling.env_override)
    candidates = (
        [Path(explicit).expanduser()]
        if explicit
        else [ROOT.parent / name for name in sibling.checkout_names]
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


def fetch_contract(sibling: Sibling) -> tuple[list[Probe] | None, list[str]]:
    """Read one sibling's contract as published, not as it happens to sit on this disk.

    A local checkout can be behind, so a probe can be satisfied here against a registration the
    sibling has already changed. Needs the network, so it belongs with the other network job rather
    than in `make all`.

    Returns `(None, [])` for the one case that is not an error: a 404 while the sibling is marked as
    not having published, meaning the contract does not exist yet.
    """
    import urllib.error
    import urllib.request

    url = sibling.raw_contract
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise SystemExit(f"incoming-probes: {url} returned {response.status}")
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404 and not sibling.published:
            return None, []
        raise SystemExit(
            f"incoming-probes: {url} returned {error.code}. "
            + (
                "The contract was published, so this is a removal or a rename rather than an "
                "absence -- the registration this repository is checked against is gone."
                if sibling.published
                else "Not a 404, so this is not the expected 'not published yet'."
            )
        ) from error
    return parse_contract(body)


def check(
    probes: list[Probe], citing: str = "the sibling"
) -> tuple[list[str], list[str]]:
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
                f"{probe.path}: {probe.text!r} is gone. {citing} cites this claim and its "
                "gate will report it. If the claim was withdrawn, say so there; if this was a "
                "rewording, restore the string or agree a replacement first."
            )
        else:
            warnings.append(
                f"{probe.path}: {probe.text!r} is gone. This probe pins the minimum and maximum "
                "of a measurement set, so a new measurement is expected to move it. **Not a "
                f"retraction** -- tell {citing} the range changed and why."
            )
    return failures, warnings


def check_sibling(sibling: Sibling, fetch: bool) -> tuple[int, int, bool]:
    """Read and check one sibling's registration.

    Returns `(exit_code, probes_checked, skipped)`. A skip is reported per sibling rather than for the
    run: one sibling being absent locally says nothing about another, and collapsing them would let a
    present contract go unread because a different one was missing.
    """
    if fetch:
        fetched, problems = fetch_contract(sibling)
        if fetched is None:
            print(
                f"incoming-probes [{sibling.label}]: SKIPPED, not published yet (404). "
                "Flip `published` for this sibling when it lands, so that a later 404 reads as a "
                "removal rather than as this."
            )
            return 0, 0, True
        probes, source = fetched, f"{sibling.label}, as published"
    else:
        base = checkout(sibling)
        if base is None:
            # A contributor without the clone is not blocked by a check about someone else's
            # citations. But the skip has to read as a skip, and it names both reasons it can
            # happen: an absent checkout and an unpublished contract look the same from here.
            print(
                f"incoming-probes [{sibling.label}]: SKIPPED, no probe contract found "
                f"(looked for {CONTRACT.as_posix()} beside this repository under "
                f"{' or '.join(sibling.checkout_names)}, or set {sibling.env_override}). "
                "Until it is readable, a reworded claim here is caught by that repository's CI "
                "instead of by this gate."
            )
            return 0, 0, True
        probes, problems = contract_from(base)
        source = base.name

    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"incoming-probes [{sibling.label}]: {len(problems)} unreadable row(s) in the "
            f"contract ({source}). Not treated as a pass: an unparsed row is an unchecked claim.",
            file=sys.stderr,
        )
        return 1, 0, False

    if not probes and EXPECT_AT_LEAST_ONE_ROW:
        print(
            f"incoming-probes [{sibling.label}]: the contract ({source}) parsed but holds no row "
            f"for {THIS_REPO}. {sibling.rows_when_written} were registered when this sibling was "
            "added, so this is a changed repository name or field order rather than an empty "
            "registration.",
            file=sys.stderr,
        )
        return 1, 0, False

    failures, warnings = check(probes, citing=sibling.label)

    for warning in warnings:
        print(f"  reread [{sibling.label}]: {warning}")
    for failure in failures:
        print(f"  [{sibling.label}] {failure}", file=sys.stderr)

    if failures:
        print(
            f"incoming-probes [{sibling.label}]: {len(failures)} cited claim(s) no longer "
            f"resolve ({source})",
            file=sys.stderr,
        )
        return 1, len(probes), False

    counts = {role: sum(1 for p in probes if p.role == role) for role in ROLES}
    summary = ", ".join(f"{counts[role]} {role}" for role in ROLES)
    tail = f", {len(warnings)} reread probe(s) moved" if warnings else ""
    print(
        f"incoming-probes [{sibling.label}]: {len(probes)} probe(s) resolve "
        f"({summary}) ({source}){tail}"
    )
    return 0, len(probes), False


def main() -> int:
    fetch = "--fetch" in sys.argv
    status = 0
    total = 0
    skipped = 0
    # Every sibling is read even when an earlier one fails. Stopping at the first would hide how many
    # citations are affected, which is the number the repository that cites them needs.
    for sibling in SIBLINGS:
        code, count, was_skipped = check_sibling(sibling, fetch)
        status = status or code
        total += count
        skipped += 1 if was_skipped else 0

    if skipped == len(SIBLINGS):
        print(f"incoming-probes: SKIPPED, no contract readable ({skipped} sibling(s))")
        return status

    # The tail line carries the verdict. Printing only a count made a failing run end on a sentence
    # that reads like a pass, which is the shape of every gate that reported success while a check
    # was broken.
    verdict = (
        "all resolve" if status == 0 else "**at least one does not resolve, see above**"
    )
    print(
        f"incoming-probes: {total} probe(s) checked across "
        f"{len(SIBLINGS) - skipped} of {len(SIBLINGS)} sibling(s) -- {verdict}",
        file=sys.stderr if status else sys.stdout,
    )
    return status


if __name__ == "__main__":
    raise SystemExit(main())
