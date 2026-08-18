<!-- Title: <type>(<optional-scope>): <what changed>, under 70 characters.
     Types: feat fix docs chore refactor test ci perf style bench
     .github/workflows/pr-title-check.yml enforces this. -->

## Summary

<!-- One or two sentences. What this adds or changes, not what was wrong before. -->

## Changes

-

## Evidence

<!-- Only if this touches a claim. Delete the rest.
     Stages: verified / documented / unverified / unconfirmed — see docs/ja/verification-status.md -->

- Stage of any new or changed claim:
- Source URL, or the environment it was observed in:
- For any number: date, Region, ONTAP version, configuration, object size, concurrency, and what was
  measured. A number without these cannot be reproduced, so it cannot be published.

## Testing

- [ ] `make all` green, run **after the last edit**
- [ ] `cfn-lint` clean, if a template changed
- [ ] Structure of the root `README.md` and `docs/en/README.md` still match, if either changed
- [ ] Switcher regenerated with `make switcher-write`, if a translation was added
- [ ] `docs/ja/verification-status.md` updated in this PR, if a claim's stage moved either way. It
      is the single source of stage; a document that restates one links to it
- [ ] Pattern README status still true, if a template was deployed or measured. `make pattern-status`
      checks the word is defined, not that it is accurate -- only you know that

## Deliberately left undone

<!-- What you decided not to do, and which constraints you accepted. This is the part a reviewer
     cannot infer from the diff. -->

-
