# Long-running task discipline for this repository

Moved here for the same reason `diagrams.md` and `policy-in-code.md` were: needed only when a
multi-step task is under way, so it costs nothing to look up and nothing to carry every turn.

The base rules live in global steering (`ai-agent-workflow` — the Parallel-by-default and Auditor
Sub-Agent sections — and `benchmark-and-evidence-standards`), which apply to every Kiro session. This
page does not restate them. It records only the connections specific to this repository: where the
decision log goes, which evidence-tier words to use, and the repeating task types with their
checklists.

## Where the decision log goes

A multi-step task (new pattern, verification run, IaC change) keeps a decision log with these three
sections, separate from the implementation write-up:

```markdown
## Decisions
- <what was decided>: <why. basis is 測定 / 文献 / 推測>

## Rejected alternatives
- <alternative rejected>: <why. could it come back if conditions change>

## Assumptions
- <assumed without verifying>: <what breaks if it is wrong>
```

Placement follows this repository's existing habit, not the Hub's:

- The decision log is **process metadata** (rejected options, unverified assumptions, evidence
  basis), so it goes to a gitignored area. This repository already uses `.agents/tasks/<task>/` for
  task records (`impl-note.md`, `report.md`, `plan.md`) and it is gitignored — use it.
- Do not split the three sections into separate files. Keep them in that task's one record.
- If a task already has a record file (`impl-note.md` / `report.md` / `plan.md`), add the three
  sections to it rather than inventing a new name. Match the existing name; `impl-note.md` is not
  mandatory.
- This template itself (the reusable part) is the only tracked piece, and it lives under
  `docs/agent/`. The per-task decision logs stay gitignored.

## Evidence-tier vocabulary

For verification work, map each `Decisions` basis to this repository's tiers. **Do not introduce a
fifth word.** The tiers are defined in [`docs/ja/verification-status.md`](../ja/verification-status.md)
and enforced through the ledger (`tools/check_scope_ledger.py`).

| Basis in the log | This repository's tier (JA / EN) |
|---|---|
| 測定（自分で実行・再現した。環境を併記） | 検証済み / verified |
| 文献（公式ドキュメントに記載。出典 URL と開いた日付） | ドキュメント記載 / documented |
| 推測（確かめていない。断定形にしない） | 未検証 / unverified、または 未確認 / unconfirmed |

`未確認` means "no public statement found", not "cannot be done" — the distinction
`verification-status.md` makes. A one-time observation that has not converged is written as the
measurement record already does it: labelled 「1 回測定・ばらつき未収束」, not promoted to 検証済み.

## When to call the auditor

On any of these signals, call the auditor before continuing. Do not build an automatic hook (a
read-only call tripping a hook costs more than the automation saves). Notice the signal and call by
hand.

- the same approach has failed twice
- the same file has been re-edited three or more times
- a multi-step task keeps hitting the same error message

Where to send it, and the direction:

- review the judgement / surface missed angles → `semantic_reviewer`, with the three log sections
  and the diff
- check an assumption against the implementation → `context-gatherer`, asking "does this assumption
  match the code"

Point the instruction at doubt, not reinforcement: which decisions rest on 推測 rather than
measurement, which rejected alternative should come back now, which unverified assumption would waste
the work if it is wrong.

This repository has no separate auditor mechanism (no evidence-ledger / ADR beyond the scope and
verification ledgers), so the auditor rides on the two sub-agents above. The pre-commit review of
public output is the persona review board's job — keep it separate from the auditor (not in the
signal list).

## Measure the spread before claiming an effect

Before attributing a throughput / latency / cost change to something you changed, measure the
run-to-run spread of the **unchanged** configuration first. If the change's delta is inside that
spread, it is noise — say so, or add iterations until it clears. A one-off "A is faster than B",
each measured once, is the same case.

This repository already practises this. Follow its existing labels rather than inventing new ones:

- 「1 回測定・ばらつき未収束」 for a single, non-converged measurement
  (`docs/ja/verification/s3ap-multipart-internet-origin.md`)
- 「非統制（uncontrolled）」 when comparing across environments, naming every axis that differs
- the `perf-matrix` records' own convergence notes (e.g. "run 内は再現、環境間は再現しない")

Keep the mandatory metadata from `benchmark-and-evidence-standards` in the record:
`benchmark_run_id`, `test_environment`, `object_size`, `concurrency`, `iteration_count`,
`warm_up_runs`, `timestamp`, `limitations`. From 2026-09 onward a new record copies
`docs/ja/verification/onprem-cache-poc-environment.example.yaml` to keep the environment
machine-readable (`policy-in-code.md`).

---

## Repeating task-type checklists

Grow these one item at a time. A second failure of the same type is the signal that an item is
missing, not a one-off. A failure that a hook or gate could stop belongs in learned-constraints
instead; only judgement and review angles that no mechanism can enforce stay here.

### New pattern (collect / serve / pipelines)

- [ ] scaffolded with `make new-pattern AXIS=<axis> SLUG=<slug>` — never hand-copy
      `patterns/_template/skeleton/` (the relative-link depth breaks)
- [ ] did not flatten the template level (`patterns/<axis>/<slug>/` sits at the skeleton's depth)
- [ ] did not deviate from the fixed architecture (writes always via the origin-side S3 Access
      Point; the cache side is NFS / SMB only; no S3 on the cache side)
- [ ] `cfn-lint` clean; tests under `patterns/<axis>/<slug>/tests/`
- [ ] `make counts` passes (counts are recomputed from `patterns/*/*/template.yaml`; do not hand-write a number)
- [ ] `make all` green, run **after the last edit**

### Verification run (environments/)

`environments/` is aws-origin (CloudFormation) / onprem-cache (Terraform) / perf-matrix /
s3files-compare. These are billable.

- [ ] did not enable an irreversible feature on my own judgement (SnapLock, Object Lock, snapshot
      lock, `PERMANENTLY_DISABLED`, `COMPLIANCE`) — the retention value must be named by the user
- [ ] read the teardown page before the create page (reversibility is documented separately)
- [ ] FlexCache teardown order: do not delete the origin while a cache exists — release the cache,
      then the SVM peer, then the cluster peer
- [ ] exported any artifact that teardown destroys (objects in a bucket about to be deleted, files
      on a throwaway volume) **before** teardown; if it was not exported, lower the tier, do not
      write 検証済み
- [ ] did not treat a success response as evidence of success — judged by state a few tens of
      seconds later (`Lifecycle` etc.)
- [ ] AWS SSO session alive (on `Token has expired`, ask the user to run `aws sso login`; do not
      switch to long-term keys)
- [ ] identifiers for destructive calls taken from a saved file or a list output, not typed by hand
- [ ] recorded what was and was not confirmed

### Benchmark (before claiming a number)

- [ ] measured the unchanged configuration's run-to-run spread first
- [ ] the change's delta clears that spread (if not, wrote "noise" or added iterations)
- [ ] mandatory metadata in the record (run_id / environment / object_size / concurrency /
      iteration_count / warm_up / timestamp / limitations)
- [ ] reported mean / p50 / p90 / p95 / p99 / max / stddev
- [ ] labelled cross-environment comparisons 「非統制（uncontrolled）」 and listed the differing axes
- [ ] separated "sample run" from "production estimate"
- [ ] did not write "A is faster than B" from one measurement each
- [ ] a number without its environment is written 未測定, not filled with a plausible default

### Common (before committing)

- [ ] `make all` green, after the last edit; read the exit code from a file (never through a pipe)
- [ ] public-output sweep (no personal names, AWS account IDs, internal IPs, support case numbers,
      client or organisation names, vendor-internal ticket IDs in tracked files)
- [ ] naming (FSx for ONTAP only; no FSxN / bare FSx / FSx ONTAP) <!-- allow:naming the item quotes the forbidden forms it bans -->
- [ ] JA/EN parity (touch both in the same commit when a translated file changes)
