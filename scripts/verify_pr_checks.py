#!/usr/bin/env python3
"""Confirm that CI passed for the commit a pull request currently points at.

`gh pr checks` answers "what is the latest result", not "what is the result for the current head".
Push after reading it and the same output comes back, describing the previous commit, until the new
run starts. The sibling playbook merged on that output; the giveaway was that the run ID had not
changed. Nothing about the command shows which commit it is describing.

So this resolves the pull request's head SHA and asks for the runs keyed on that SHA. A workflow that
has not started for it does not exist in the answer, which is the case that reads as success when the
question is asked the other way round.

The repository already requires `make all` to run after the last edit. This is the same rule applied
to CI: read the result of the last push, not the last result.

Run:  python3 scripts/verify_pr_checks.py <pr-number>
      make pr-verify PR=<pr-number>
"""

from __future__ import annotations

import json
import subprocess
import sys

# The repository is not named here. `gh` resolves it from the working directory and templates
# `{owner}/{repo}` in an API path, so a constant would restate what git already knows -- and would be
# wrong in a fork, silently reporting the upstream's runs as this branch's.
#
# Workflows that run for every pull request. `zizmor` is path-filtered to `.github/` and the pinned
# manifest, so its absence is normal and is reported rather than treated as missing.
ALWAYS = {"ci", "gitleaks", "pr-title-check"}


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise SystemExit(f"gh {' '.join(args)} failed: {result.stderr.strip()}")
    return result.stdout


def main() -> int:
    if len(sys.argv) != 2:
        raise SystemExit("usage: verify_pr_checks.py <pr-number>")
    number = sys.argv[1]

    view = json.loads(gh("pr", "view", number, "--json", "headRefOid,state,title"))
    head = view["headRefOid"]
    runs = json.loads(
        gh("api", f"repos/{{owner}}/{{repo}}/actions/runs?head_sha={head}&per_page=100")
    )["workflow_runs"]

    # Latest run per workflow, in case one was re-run.
    latest: dict[str, dict] = {}
    for run in sorted(runs, key=lambda r: r["run_started_at"]):
        latest[run["name"]] = run

    print(f"PR #{number} ({view['state']}) head {head[:12]}")
    problems = []
    for name, run in sorted(latest.items()):
        status = run["status"]
        conclusion = run["conclusion"]
        print(f"  {name}: {status}/{conclusion}")
        if status != "completed":
            problems.append(f"{name} has not finished for {head[:12]}")
        elif conclusion != "success":
            problems.append(f"{name} concluded {conclusion} for {head[:12]}")

    missing = sorted(ALWAYS - set(latest))
    for name in missing:
        problems.append(
            f"{name} has no run for {head[:12]} - it has probably not started yet, which is the case "
            "that `gh pr checks` reports as the previous commit's success"
        )

    if problems:
        print()
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print(f"pr-verify: not safe to merge #{number}", file=sys.stderr)
        return 1
    extra = sorted(set(latest) - ALWAYS)
    note = f"; also ran: {', '.join(extra)}" if extra else "; zizmor path-filtered out"
    print(f"pr-verify: every workflow succeeded for this exact commit{note}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
