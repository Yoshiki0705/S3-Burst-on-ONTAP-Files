# Deferred restructuring decisions

Moved out of `AGENTS.md` for the same reason `diagrams.md` was: needed only when picking this work
back up, so it costs nothing to look up and nothing to carry every turn.

A decision to defer a restructuring is not the same as a decision that it is unnecessary. Recording
only "see git log" loses the *condition* under which the deferral should end, and a deferral with no
recorded condition tends to become permanent. Each entry below states what was deferred, why, and
what would trigger picking it up — not a deadline, since none of this repository's restructuring
work is scheduled against a date.

## README.md — 12-section restructuring

Raised in a review of `S3 Access Points修正プロンプト.md` (2026-09, not tracked in this repository;
see `.private/` for the source if it still exists locally). The prompt asked for the root
`README.md` to be reordered into a fixed 12-section sequence (what this repository proposes / target
readers / 30-second data flow / key constraints / verification status / when this fits / when it
does not / quickstart / doc map / local verification / security / disclaimer).

**Deferred, not declined.** The current structure covers the same information at a different
heading granularity, and `docs/en/README.md` mirrors it exactly — `make i18n-check` compares heading
structure, not text, so a reorder of the Japanese hub has to land in the same commit as the English
one or the check goes red. That coupling is what made this a "defer and batch" decision rather than
a same-session edit.

**Condition to pick this up**: the next time `README.md`'s section order is touched for an unrelated
reason (a new guide added to the "Start here" table, a new implementation pattern axis, or another
persona-review pass), reconsider the 12-section order in the same change rather than layering one
more addition onto the current structure. Do not open a dedicated restructuring task for this alone;
the cost of touching both language files at once is best amortized against a change that was
happening anyway.

## `docs/ja/verification/` — environment.yaml migration for existing records

Same source review. The full request was to make every measurement record's environment machine-
readable via `docs/ja/verification/<name>/environment.yaml`, replacing the inline prose that
currently carries Region, ONTAP version, throughput configuration, and so on.

**Scoped down, not declined.** `docs/ja/verification-status.md` alone carries well over a hundred
individual measurement entries, and the sibling files under `docs/ja/verification/` carry the
detailed records those entries point to. Migrating all of them in one pass is a rewrite of the
verification record, not an edit to it, and the risk of losing a caveat in translation between prose
and YAML is highest exactly where the prose is doing the most work (a superseded number, a retracted
attribution, a measurement taken twice with different results).

**Adopted policy, effective now**: a *new* verification record added from 2026-09 onward uses
[`docs/ja/verification/onprem-cache-poc-environment.example.yaml`](../ja/verification/onprem-cache-poc-environment.example.yaml)
as its template. `docs/agent/policy-in-code.md` names this file as what to read before adding one.

**Condition to migrate an existing record**: when a record under `docs/ja/verification/` is next
edited for its own sake — a correction, a re-measurement, a superseding claim — write its
`environment.yaml` sibling as part of that same edit rather than as a separate pass. This turns the
migration into something that happens incrementally as records are already being touched, rather
than a backlog that grows monotonically until someone schedules a dedicated migration.
