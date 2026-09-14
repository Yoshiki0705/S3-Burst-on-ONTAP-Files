#!/usr/bin/env python3
"""Verify the probe strings this repository registers against sibling repositories.

The mirror of `check_incoming_probes.py`, one repository over. That one reads a contract someone else
publishes and fails when a string **we own** disappears. This one reads the contract **we** publish
(`docs/agent/cross-repo-probe-contract.txt`) and fails when a string we *cite* disappears.

Both failures are useful and they ask for different things:

    incoming  a claim of ours that something depends on was reworded -> restore it or agree a change
    outgoing  evidence we rest on moved -> re-point the citation, or lower the claim's stage

So the same reword fires on both sides, and the two sides are not redundant: the owner learns that
someone depends on the wording, and the citer learns that a claim here has lost its basis. Neither can
be inferred from the other.

**This is also the self-validating step this repository asked the Playbook for and should hold itself
to.** Publishing a contract whose strings were never checked against the cited repository would put a
wrong probe in front of another project's gate, where it reads as a break they caused.

Needs a local checkout of each cited repository, so it skips per repository with a message when one is
absent -- the way the external-anchors and incoming-probes targets do. `--fetch` reads the cited files
over the network instead, for the scheduled job, which is what makes this run at all on a CI runner.

Run:  python3 tools/check_outgoing_probes.py [--fetch]
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path
from typing import NamedTuple

import probe_strength

ROOT = Path(__file__).resolve().parent.parent
CONTRACT = Path("docs/agent/cross-repo-probe-contract.txt")

OWNER = "Yoshiki0705"
RAW = f"https://raw.githubusercontent.com/{OWNER}/{{repo}}/main/{{path}}"

# A working directory is named by whoever cloned it, and several of these diverge from the repository
# name -- which is the same hazard `check_links.py` keeps its allowlist for. Each cited repository
# therefore lists the directory names it is known by locally, most canonical first. An environment
# variable of the form SIBLING_<REPO_WITH_UNDERSCORES> overrides one.
LOCAL_NAMES = {
    "FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns": (
        "FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns",
        "fsxn-s3ap-serverless-patterns",
        "s3ap-patterns",
    ),
    "FSx-for-ONTAP-Adoption-Playbook": (
        "FSx-for-ONTAP-Adoption-Playbook",
        "fsxn-adoption-playbook",
    ),
    "VMware-Migration-EC2-ONTAP": (
        "VMware-Migration-EC2-ONTAP",
        "vmware-migration-ec2-ontap",
    ),
}

FAIL_ROLE = "retraction"
WARN_ROLE = "reread"
ROLES = (FAIL_ROLE, WARN_ROLE)


class Probe(NamedTuple):
    repo: str
    path: str
    role: str
    text: str


def parse_contract(body: str) -> tuple[list[Probe], list[str]]:
    """Four TAB-separated fields: repo, path, role, string. The string is last and is taken whole.

    Identical to the reader on the incoming side, because the format is the same one -- the Playbook's.
    Kept as its own function rather than imported so that the published contract can be validated
    without the sibling checkout that the incoming reader needs in order to exist.
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
                f"got {len(fields)}"
            )
            continue
        repo, path, role, text = fields
        if not text:
            problems.append(f"line {number}: empty probe string for {path}")
            continue
        if role.strip() not in ROLES:
            problems.append(
                f"line {number}: unknown role {role.strip()!r}. Expected one of "
                f"{', '.join(ROLES)}"
            )
            continue
        if repo.strip() not in LOCAL_NAMES:
            problems.append(
                f"line {number}: {repo.strip()!r} has no local directory names recorded, so this "
                "row can never be checked. Add it to LOCAL_NAMES."
            )
            continue
        probes.append(
            Probe(repo=repo.strip(), path=path.strip(), role=role.strip(), text=text)
        )
    return probes, problems


def checkout(repo: str) -> Path | None:
    override = os.environ.get("SIBLING_" + repo.upper().replace("-", "_"))
    candidates = (
        [Path(override).expanduser()]
        if override
        else [ROOT.parent / name for name in LOCAL_NAMES[repo]]
    )
    for path in candidates:
        if path.is_dir():
            return path
    return None


def committed(base: Path, path: str) -> tuple[str | None, bool]:
    """One file from the sibling as published, read from git rather than from the checkout.

    Returns `(body, read_from_git)`. `read_from_git` false means the caller should fall back and say
    so; a None body with it true means the file is genuinely absent at `origin/main`.

    The harmful direction here is the opposite of the incoming check's. There, an unpushed removal
    stops a published registration from being enforced. Here, an **unpushed addition** lets this
    repository cite a sentence no reader can see: the gate goes green against a working tree while
    the published document does not carry the claim. Reading `origin/main` is local -- no fetch -- and
    it is the side a reader following the citation lands on.
    """
    import subprocess

    def git(*args: str) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(
                ["git", "-C", str(base), *args],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return None

    # Asked separately, and not inferred from the wording of a failure. "This checkout cannot answer
    # for origin/main" and "origin/main does not carry this file" need opposite handling -- fall back
    # versus report the file as gone -- and telling them apart by matching git's stderr would rest the
    # distinction on a message that is free to change between versions.
    ref = git("rev-parse", "--verify", "--quiet", "origin/main")
    if ref is None or ref.returncode != 0:
        return None, False

    shown = git("show", f"origin/main:{path}")
    if shown is None:
        return None, False
    return (shown.stdout, True) if shown.returncode == 0 else (None, True)


def fetch(repo: str, path: str) -> str | None:
    import urllib.error
    import urllib.request

    url = RAW.format(repo=repo, path=path)
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            if response.status != 200:
                raise SystemExit(f"outgoing-probes: {url} returned {response.status}")
            return response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None  # the cited file itself is gone; reported by the caller
        raise SystemExit(f"outgoing-probes: {url} returned {error.code}") from error


def out_of_order(text: str) -> list[str]:
    """Rows that break the sort the header declares.

    Checked here rather than in the shared parser, because the sort is this repository's convention.
    A sibling's contract goes through the same parser and must not fail for keeping its own order.

    The rule existed only in the header until a sibling read the file and noticed: a re-anchored row
    had been written back into the position of the row it replaced, and nothing looked. A convention
    stated in prose and enforced nowhere is a convention that holds until the first edit made in a
    hurry -- and the reason for this one is practical, not tidiness: two people appending rows to a
    sorted file conflict in one predictable place instead of wherever each happened to type.
    """
    rows = [line for line in text.split("\n") if line and not line.startswith("#")]
    if rows == sorted(rows):
        return []
    for position, (actual, expected) in enumerate(zip(rows, sorted(rows)), start=1):
        if actual != expected:
            return [
                f"{CONTRACT.as_posix()}: row {position} of the data rows breaks the sort the "
                f"header declares. Found {actual.split(chr(9))[-1]!r} where "
                f"{expected.split(chr(9))[-1]!r} belongs. Sort the data rows whole, as they are "
                "tab-separated with the probe last."
            ]
    return []  # pragma: no cover - unreachable while the lists differ


SHAPE = re.compile(
    r"SHAPE:\s*(\d+) rows across (\d+) files, (\d+) in the largest", re.MULTILINE
)


def shape_drift(text: str) -> list[str]:
    """The header states the contract's shape, and that shape is the premise of a decision.

    Not blocking on this check in CI is justified by the rows being concentrated: one rewrite of the
    file that holds most of them fails several at once, so an other-caused red would block every
    unrelated change. That argument stops holding as rows spread out -- and a hand-written count goes
    stale silently, which would leave the decision standing on a premise that is no longer true.

    So the numbers are recomputed and compared, the same way pattern counts are. Absent header: also a
    failure. A premise that can be deleted to make the check pass is not a premise.
    """
    rows = [line for line in text.split("\n") if line and not line.startswith("#")]
    per_file: dict[tuple[str, str], int] = {}
    for line in rows:
        fields = line.split("\t")
        if len(fields) >= 2:
            per_file[(fields[0], fields[1])] = (
                per_file.get((fields[0], fields[1]), 0) + 1
            )
    actual = (len(rows), len(per_file), max(per_file.values(), default=0))

    match = SHAPE.search(text)
    if match is None:
        return [
            f"{CONTRACT.as_posix()}: the header no longer states a SHAPE line. It carries the "
            "premise for not blocking on this check in CI, so removing it removes the reason "
            f"rather than the requirement. Expected: SHAPE: {actual[0]} rows across {actual[1]} "
            f"files, {actual[2]} in the largest."
        ]
    stated = tuple(int(group) for group in match.groups())
    if stated != actual:
        return [
            f"{CONTRACT.as_posix()}: the header states {stated[0]} rows across {stated[1]} files "
            f"with {stated[2]} in the largest; the rows are {actual[0]} across {actual[1]} with "
            f"{actual[2]} in the largest. Update the SHAPE line -- and if the rows have spread out, "
            "the reason this check does not block on a pull request may no longer hold."
        ]
    return []


def main() -> int:
    contract_text = (ROOT / CONTRACT).read_text(encoding="utf-8")
    problems = out_of_order(contract_text) + shape_drift(contract_text)
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"outgoing-probes: {CONTRACT.as_posix()} is not in the order its header declares.",
            file=sys.stderr,
        )
        return 1
    probes, problems = parse_contract(contract_text)
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(
            f"outgoing-probes: {len(problems)} unreadable row(s) in {CONTRACT.as_posix()}. "
            "Not a pass: a row that cannot be parsed is a probe another repository's gate may be "
            "reading while this one is not.",
            file=sys.stderr,
        )
        return 1
    if not probes:
        print(
            f"outgoing-probes: {CONTRACT.as_posix()} holds no probe. If nothing here cites a "
            "sibling's claim that is correct; if something does, the citation is unregistered.",
            file=sys.stderr,
        )
        return 1

    online = "--fetch" in sys.argv
    failures: list[str] = []
    warnings: list[str] = []
    skipped: set[str] = set()
    # Repositories whose published side could not be read, so the checkout answered instead. Named in
    # the summary: a run that fell back proves less than one that read origin/main, and the output is
    # the only place a reader can tell which happened.
    fell_back: set[str] = set()
    weak: list[str] = []
    bodies: dict[tuple[str, str], str | None] = {}
    checked = 0

    for probe in probes:
        if not online and checkout(probe.repo) is None:
            skipped.add(probe.repo)
            continue
        key = (probe.repo, probe.path)
        if key not in bodies:
            if online:
                bodies[key] = fetch(probe.repo, probe.path)
            else:
                base = checkout(probe.repo)
                assert base is not None
                body, from_git = committed(base, probe.path)
                if from_git:
                    bodies[key] = body
                else:
                    fell_back.add(probe.repo)
                    target = base / probe.path
                    bodies[key] = (
                        target.read_text(encoding="utf-8") if target.is_file() else None
                    )
        body = bodies[key]
        checked += 1

        if body is None:
            failures.append(
                f"{probe.repo}: {probe.path} not found, so the {probe.role} probe "
                f"{probe.text!r} cannot resolve. A claim here cites that file; re-point it or "
                "lower the claim's stage."
            )
            continue
        # A string that occurs more than once in the cited document protects less than it appears to:
        # the sibling can reword one occurrence and this stays green, so the citation here goes stale
        # without anyone being told. Chosen on this side, so unlike the incoming direction the fix is
        # this repository's -- pick a longer string, from a sentence that appears once.
        count = probe_strength.occurrences(body, probe.text)
        if count > 1:
            weak.append(
                f"{probe.repo}: {probe.text!r} occurs {count} times in {probe.path}, so "
                "rewording one occurrence leaves this green while the citation here goes stale. "
                "Re-anchor on a string that appears once."
            )
        if probe_strength.heading_only(body, probe.text):
            weak.append(
                f"{probe.repo}: {probe.text!r} only ever appears as a section heading in "
                f"{probe.path}. The heading survives its section being replaced with the opposite "
                "conclusion, so this never fires. Re-anchor on the claim, usually the line below."
            )
        if count:
            continue
        message = (
            f"{probe.repo}: {probe.text!r} is gone from {probe.path}. This repository restates "
            "the claim that string carries."
        )
        (failures if probe.role == FAIL_ROLE else warnings).append(message)

    for warning in warnings:
        print(f"  reread: {warning}")
    for note in weak:
        print(f"  weak probe: {note}")
    for failure in failures:
        print(f"  {failure}", file=sys.stderr)

    if failures:
        print(
            f"outgoing-probes: {len(failures)} cited claim(s) no longer resolve",
            file=sys.stderr,
        )
        return 1

    source = "published" if online else "local checkout(s)"
    if skipped:
        # Named, and not folded into the pass line. A skip that reads like a pass is how a contract
        # gets published with a string that was never checked against the repository it names.
        print(
            "outgoing-probes: SKIPPED for "
            + ", ".join(sorted(skipped))
            + " (no local checkout beside this repository; the scheduled job runs --fetch)"
        )
    if fell_back:
        print(
            "outgoing-probes: read the working tree for "
            + ", ".join(sorted(fell_back))
            + " because origin/main was unreadable there. An unpushed edit in that checkout can "
            "make this pass while the published document does not carry the claim."
        )
    if checked:
        print(f"outgoing-probes: {checked} probe(s) resolve against {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
