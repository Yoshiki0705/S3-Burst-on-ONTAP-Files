# AGENTS.md

<!-- audit-file-allow: naming,neutrality,conflation,pii -->
<!-- This document defines the naming, neutrality, conflation and public-output rules, so it
     necessarily quotes the shapes it forbids. The file-level allowance above exempts it from the
     audit that enforces those rules everywhere else. Do not copy this declaration into a content
     file: it is the one place where quoting a forbidden pattern is the point. -->

> Project instructions for AI coding agents. This file is committed and travels with the repository.
> Kiro steering under `.kiro/` is local-only and gitignored, so anything an agent must know to work
> correctly belongs **here** or under `docs/`.

This file is loaded on every turn and cannot be made conditional. It holds only what is needed
*before* the task is known; everything else is one index line away. `make budget` fails past
20,000 B — move content to `docs/` rather than trimming prose to fit.

## What this repository is

One architecture, implemented three ways round. Data is collected over the S3 API into an
Amazon FSx for NetApp ONTAP origin volume, and served to consumers over NFS / SMB from FlexCache
volumes at the places that read it. No copy job between the two.

`burst` in the repository name means fanning collected data out to the file-protocol side. It does
not refer to FSx for ONTAP throughput burst credits.

Three extension axes, each independent — one can grow without the others:

| Directory | Holds |
|---|---|
| `patterns/collect/` | Ingest over the S3 Access Point |
| `patterns/serve/` | Fan-out to NFS / SMB over FlexCache |
| `patterns/pipelines/` | Collect and serve combined, per workload |

`environments/` holds the verification environment, split by where it runs: `aws-origin/` is
CloudFormation because the collect side is entirely AWS, and `onprem-cache/` is Terraform against
ONTAP because the cache side can be anywhere. Neither creates cluster or SVM peering — that is
network topology owned outside this repository, and its absence is the most common reason a FlexCache
creation fails.

`docs/ja/` is canonical. `docs/en/` carries the hub and the deployment guides; the guides are
translated because a reader follows them while creating billable resources and needs the teardown
order in their own language. A document's language is its directory; the exception is the Japanese
hub, which is the root `README.md`, so `docs/ja/README.md` does not exist.

## The fixed architecture — do not deviate

| Layer | Mechanism | Protocol |
|---|---|---|
| Collect (write) | FSx for ONTAP S3 Access Point, **on the origin volume only** | S3 API |
| Source of truth | FSx for ONTAP origin volume | — |
| Distribute | FlexCache | cluster / SVM peering |
| Consume (read) | Cache volume at the consuming site | **NFS / SMB only** |

- **No S3 on the cache side.** Writes always go through the AWS-side S3 Access Point on the origin.
- ONTAP FlexCache duality and attaching an FSx for ONTAP S3 Access Point to a volume are
  **separate mechanisms**. Never use the support status of one as evidence for the other. This
  architecture uses neither. `make audit` enforces this: a line naming both must say they differ.
- AWS documents exactly **three** FlexCache configurations. With FSx for ONTAP as origin, the cache
  is on-premises ONTAP or FSx for ONTAP. Cloud Volumes ONTAP, ONTAP Select, Azure NetApp Files and
  Google Cloud NetApp Volumes are **unverified** — write "unverified", never "works because it is
  ONTAP-based", and never "unsupported" either.

## Commands

```bash
pip install -r requirements-dev.txt      # ruff, pytest, cfn-lint — exact-pinned
npm install -g markdownlint-cli2         # not pip-installable
brew install gitleaks                    # not pip-installable

make help    # every target
make all     # the commit gate: lint i18n switcher audit secrets links budget en-lang counts test
```

`make all` is the gate. Run it **after the last edit**, not before. Editing one more file after a
green run — a CHANGELOG line is the usual candidate — is how a red pull request happens.

`make python` warns when the installed `ruff` differs from `requirements-dev.txt`. That warning
means a local pass does not predict CI, because rule sets widen between releases. Install the
pinned version instead of working past it.

## Naming (applies to every file, diagram, comment and commit)

- First mention: **Amazon FSx for NetApp ONTAP**. Thereafter: **FSx for ONTAP**. These are the only
  accepted forms.
- Always wrong, always corrected to "FSx for ONTAP": `FSxN`, bare `FSx`, `FSx ONTAP`, `FSx NetApp`.
  Note that "FSx as origin" is a bare `FSx` — write "FSx for ONTAP as origin".
- Sibling AWS services are legitimate: `FSx for Windows File Server`, `FSx for Lustre`,
  `FSx for OpenZFS`.
- **Never propose these**: NetApp Workload Factory, NetApp Console, BlueXP. Reframe to the native
  mechanism — Amazon CloudWatch, ONTAP REST API, FabricPool, AWS DataSync, Snapshot / FlexClone /
  SnapMirror.
- A citation URL or verbatim source title that contains one of those names is evidence, not a
  proposal. Mark that line `<!-- allow:vendor-ref -->` with the reason.

## How comparisons are written

State each option's exclusion conditions at the same granularity, this architecture's own included.
Then a reader can choose. Do not announce that the comparison is even-handed: `make audit` rejects
the words for it, because a sentence declaring even-handedness reads as a defence and invites the
framing it is trying to avoid.

Forbidden: `beats X`, `X is inferior`, `competing tools`, `競合ツール`, `より優れて`, `優位性`,
`game-changer`, `best-in-class`, and any vendor-versus positioning. Every comparison carries a
"how to choose" path — see `docs/ja/reference/decision-trees/choosing-this-architecture.md`.

## Evidence discipline

Four stages, defined in [docs/ja/verification-status.md](docs/ja/verification-status.md):
**verified** / **documented** / **unverified** / **unconfirmed**.

- "The documentation says so" and "it works" are different claims. Do not cite the first as the
  second.
- **unconfirmed** means "no public statement found", not "cannot be done".
- Numbers are meaningless without the environment. A performance or cost figure needs the date,
  Region, ONTAP version, file system generation and throughput configuration, object size and
  concurrency, and what was measured. **If it was not measured, it is not written.**
- Separate "sample run" from "production estimate", and "design consideration" from
  "legal / compliance judgement".
- Lowering a stage needs no justification. Raising one needs the evidence attached.

## Public-output safety

This repository is public. Git history is permanent and search-indexed.

**Never commit**: personal names (colleagues, reviewers, customers — in any language), email
addresses, phone numbers, addresses, identity-linked handles, employee IDs, AWS account IDs,
internal IPs or hostnames, support case numbers, vendor-internal ticket or product IDs, customer or
organisation names, unmasked screenshots.

| Do not use | Use instead |
|---|---|
| A named reviewer | A role-based reference ("storage operations perspective") |
| `name@company.example` | "(internal reviewer)" |
| Internal ticket `XX-I-12345` | "an internal product request (tracked)" |
| Support case `#123456` | "filed with the vendor (tracked)" |
| A real account ID | `123456789012` |
| A real IP | `10.0.x.x` or `<management-ip>` |
| A real file system ID | `fs-0123456789abcdef0` |
| `/Users/<name>/…` | A relative path or `${PROJECT_DIR}` |

Names are fine in `.private/` and `.kiro/`, both gitignored. Never in a tracked file.

**Do not label an inline callout with a job title or persona** (`> **AppSec lens**:`,
`> **… の視点**:`). Such a label implies an interview or expert review took place. Use a
topic-based label instead — `> **Security note**:`, `> **セキュリティに関する補足**:`. The finding
is unchanged; only the label differs.

**No process metadata in published documents**: no review rounds, dates, lens counts or `R1/F2`
tags. That belongs in `.private/`.

Branch names and commit messages are public output too. Name what the change *adds*, never what was
wrong before. Conventional commits, subject under 72 characters; PR titles under 70.

## Irreversible operations

**A feature whose purpose is to remove your ability to delete data must never be enabled on an
agent's own judgement.** When such a feature works correctly it is indistinguishable from an outage
you caused, there is no rollback, and the blast radius is routinely wider than the resource named in
the call.

In a sibling repository a 128 MiB SnapLock audit log volume made its volume, its SVM and **the
entire file system** undeletable for six months. Privileged delete had already been set to
`PERMANENTLY_DISABLED`, closing the last exit. It was verification work, and it produced no usable
finding.

Requires an explicit human instruction naming the retention value: SnapLock
(`SnaplockConfiguration`, `SnaplockType`, `AuditLogVolume`, `PrivilegedDelete`, `RetentionPeriod`),
snapshot locking / tamperproof snapshots (`-snapshot-locking-enabled`, `-snaplock-expiry-time`,
`snapmirror policy add-rule -retention-period`), S3 Object Lock, S3 Glacier vault lock, AWS Backup
Vault Lock, EBS `lock-snapshot`, and any value named `PERMANENTLY_DISABLED` or `COMPLIANCE`.

Before acting:

1. **Find the parameter that actually binds.** "Use the minimum" is not protection. In the incident
   above the volume `RetentionPeriod` was already `0 YEARS` while a *different* parameter did the
   locking — and the AWS API has no field for it, so a default applied silently. When your API
   cannot express a value, the fact that a default will apply is itself what needs approval.
2. **State the widest scope**: volume, SVM, file system, bucket, vault, account. Name the period and
   the cost of holding that scope for its whole duration.
3. **Read the teardown page before the create page.** Reversibility is a property of the exit and is
   documented separately from the entry.
4. **Verification is not an exemption.** A PoC is the worst place for an irreversible operation: an
   undeletable test resource becomes a long-lived bill and blocks everything beside it.
5. **A success response is not evidence of success.** Some deletions silently revert. Judge by state
   a few tens of seconds later, not by the response. If it did not take effect, do not add a flag
   and retry.

FlexCache has its own ordering constraint: do not delete the origin side while a cache still exists;
release the cache, then the SVM peer, then the cluster peer.

## Writing conventions

- Markdown, ATX headings, tables over bullet lists for anything with two or more attributes.
- **Every diagram states the same thing in prose or a table.** Mermaid does not render everywhere,
  is not reliably reachable by a screen reader, and is not extractable by a crawler. A decision that
  exists only inside a diagram is a decision some readers cannot access.
- Code blocks always carry a language tag. Internal links are relative.
- Japanese is the authoring language for documents; code, identifiers and commit messages are
  English.
- **Never hand-write a language switcher.** `make switcher-write` generates it. A new localized file
  needs the marker pair added once, after the H1 and at the end.
- **Do not write a number that can be derived.** `make counts` recomputes every pattern count from
  `patterns/*/*/template.yaml` and fails on drift. A count of zero is reported as a broken reader,
  not as "none yet".
- The conflation check reads one line at a time, so when a sentence names both mechanisms the words
  "separate mechanisms" / `別の機構` have to sit on the **same** line, not wrap onto the next. That is
  a constraint worth keeping: it stops the distinction drifting away from the claim during a later
  edit, which is exactly how the two came to be treated as one thing elsewhere.
- A pattern is scaffolded from `patterns/_template/skeleton/`, which sits at the same depth as
  `patterns/<axis>/<slug>/` on purpose. Relative links are therefore identical in the template and
  in the copy. Do not flatten that level.

## Verification checklist

1. `make all` green, after the last edit
2. New or changed claim → stage honest, environment stated for any number
3. Changed the root `README.md` structure → `docs/en/README.md` updated in the same commit
   (`make i18n-check` compares heading structure, not text)
4. Added a translation → `make switcher-write`, never a hand-edited switcher line
5. New pattern → `make new-pattern AXIS=<axis> SLUG=<slug>`, `cfn-lint` clean, tests under
   `patterns/<axis>/<slug>/tests/`
6. Copied an asset from a sibling repository → provenance and divergence recorded at the top of the
   file

## Self-review (four axes)

Automated checks catch syntax. These catch design-level problems.

1. **Gaps** — anything in scope still missing? Doc added but not linked from the hub? Structure
   changed in Japanese only?
2. **Oddities** — leftover placeholder text, headings that no longer match the body, half-applied
   renames, a stated number nobody recomputed.
3. **Polish** — small in-scope improvements noticed and dismissed. Include them when they touch the
   same files with no behaviour risk.
4. **Regression** — did a link target move? Does another document cite something you just changed?

## Do not

- Move `solutions/flexcache/` out of the sibling repository `fsxn-s3ap-serverless-patterns`. Its
  README, its stale-claim tests and its `pattern-test-dirs.txt` all count that directory, and a move
  breaks `make drift` and `make test` there.
- Copy an asset without recording where it came from and how it diverged.
- Put the body of any knowledge in `.kiro/`. It is not published. Steering holds the load condition
  and a pointer; the body goes in `docs/`. `make budget` checks that every pointer resolves to a
  tracked file.
- Reimplement the global steering, skills and hooks under `~/.kiro/`. They already apply.
- Write a performance or cost number that was not measured.
- Present an S3-on-the-cache-side design as the main line.

## Where the details live

| Document | Answers |
|---|---|
| [docs/ja/architecture.md](docs/ja/architecture.md) | The two layers, what the architecture solves and does not solve, the HiL use case |
| [docs/ja/design-first-decisions.md](docs/ja/design-first-decisions.md) | What must be decided before the origin volume is created, and how far it is confirmed |
| [docs/ja/support-matrix.md](docs/ja/support-matrix.md) | Support status and minimum versions for both layers |
| [docs/ja/verification-status.md](docs/ja/verification-status.md) | The four stages and the current state of each claim |
| [docs/ja/portability.md](docs/ja/portability.md) | Replacing either layer per platform, and what stays unconfirmed |
| [docs/ja/poc-checklist.md](docs/ja/poc-checklist.md) | What to confirm, in the order that unblocks design |
| [docs/ja/verification/s3ap-nfs-visibility.md](docs/ja/verification/s3ap-nfs-visibility.md) | The one measurement taken so far, its conditions, and what it does **not** answer |
| [docs/ja/deployment/aws-cloudformation.md](docs/ja/deployment/aws-cloudformation.md) | Deploying the collect side, and the teardown order |
| [docs/ja/deployment/onprem-terraform.md](docs/ja/deployment/onprem-terraform.md) | Deploying the serve side, and why peering is not created for you |
| [docs/ja/reference/glossary/object-access-on-ontap.md](docs/ja/reference/glossary/object-access-on-ontap.md) | The mechanisms named "S3 over files", and which inferences do not hold |
| [docs/ja/reference/comparison/alternatives.md](docs/ja/reference/comparison/alternatives.md) | Every option's suited and unsuited conditions, this one included |
| [docs/ja/reference/decision-trees/choosing-this-architecture.md](docs/ja/reference/decision-trees/choosing-this-architecture.md) | Whether to adopt this architecture |
| [docs/ja/reference/limits/s3-access-point.md](docs/ja/reference/limits/s3-access-point.md) | Limits with source and stage |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Authoring conventions and the review gate |

## External dependencies

- Python 3.12 or later for `tools/` and `scripts/` (stdlib only). `ruff`, `pytest` and `cfn-lint`
  are exact-pinned in `requirements-dev.txt`; CI installs from that file so the verdict does not
  depend on the day it runs.
- No application runtime. Patterns are CloudFormation / SAM templates deployed by the reader.
- The S3 Access Point itself is created out of band: CloudFormation has no native resource for it,
  so `aws fsx create-and-attach-s3-access-point --cli-input-json file://…` is used. Positional
  `--ontap-configuration` parsing is fragile; always pass a JSON file.
