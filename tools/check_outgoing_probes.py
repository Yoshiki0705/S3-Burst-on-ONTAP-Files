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
import sys
from pathlib import Path
from typing import NamedTuple

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


def main() -> int:
    probes, problems = parse_contract((ROOT / CONTRACT).read_text(encoding="utf-8"))
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
                target = checkout(probe.repo) / probe.path  # type: ignore[operator]
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
        if probe.text in body:
            continue
        message = (
            f"{probe.repo}: {probe.text!r} is gone from {probe.path}. This repository restates "
            "the claim that string carries."
        )
        (failures if probe.role == FAIL_ROLE else warnings).append(message)

    for warning in warnings:
        print(f"  reread: {warning}")
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
    if checked:
        print(f"outgoing-probes: {checked} probe(s) resolve against {source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
