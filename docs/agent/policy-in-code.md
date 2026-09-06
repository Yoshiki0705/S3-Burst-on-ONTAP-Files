# What to read before changing a URL, a name, or a count

Moved out of `.kiro/steering/`, which is not published and is budgeted to hold only a load condition
and a pointer. This is needed only when a convention itself changes, so it costs nothing to look up.

The reading order for `docs/` content — architecture, protocols, support status, claim stages — is in
the steering file that points here. This page covers the other kind: **conventions that exist only as
code.** There is no prose page stating them, so the enforcing tool is the primary source, and reading
the prose instead produces a confident answer that the tool then contradicts.

| What you are changing | Read |
|---|---|
| A GitHub URL, the repository name, an external link | `tools/check_links.py` — `PUBLISHED_REPOS` and the comment above it |
| A diagram or an icon | `docs/agent/diagrams.md`, then `tools/build_diagrams.py` |
| Anything about the two languages or the switcher | `docs/i18n-terms.md`, `tools/check_i18n_parity.py` |
| A number stated in prose | `tools/check_derived_counts.py` — `COUNT_GLOBS` |
| A published article and its draft | `tools/check_blog_draft_sync.py` |
| The Interconnect Region pairs or a CSP's lifecycle | `tools/check_interconnect_regions.py` — `DOCUMENTS` and `CSP_HEADINGS` |

## A grep hit count is not a list of things to change

Read what surrounds each hit before reporting a scale or proposing a policy. Counting is not reading,
and a count presented as a work estimate invites approval for work that should not happen.

Worked example. This repository was renamed, and the old name appeared in fifteen places. None of
them needed changing:

- **Three were deployment values** in `environments/` — resource names and tags. Editing those
  renames live resources, which is a different operation from fixing a link, with a different blast
  radius.
- **Two were the link checker's own design.** `check_links.py` compares case-insensitively on
  purpose, so the lowercase entries are correct, not stale.
- **The rest were URLs that already resolve.** The rename changed capitalisation only, and GitHub
  resolves a case-difference permanently rather than by redirect.

That last fact — the one that made the whole task unnecessary — was written in `check_links.py`
before the question was asked. The failure was not missing knowledge; it was forming a conclusion
from an external observation ("this repository moved") and a hit count, without reading the code that
already had the answer.

## Do not take a decision from an external fact alone

When an external observation and this repository disagree, the repository is describing its own
choices and the observation is not. Read the local record first, then decide whether the observation
changes it. The reverse order produces work that has to be withdrawn.

## An empty result and an unreadable source are different answers

A check that reads someone else's page has two ways of coming back with nothing, and they call for
opposite responses. No difference found means the documents are correct. Nothing parsed means the page
changed shape and the check has stopped looking, which is worse than a difference because it is
silent and stays silent.

`tools/check_interconnect_regions.py` is the one check here that reads an external page, and it exits
non-zero on every empty path: the request failing, the page parsing to zero pairs, and a document
whose table cannot be found. `make counts` applies the same rule to the filesystem — a count of zero
is reported as a broken reader, not as "none yet".

The rule for any check added later: **decide what the absence of findings means before writing the
success message.** If a scan that could not run and a scan that found nothing print the same line,
the check will eventually report success forever.

## Some rules cannot live in a checker, and the measurement says which

Every rule above is enforced by code because it can be. The obligation to cite a source cannot be,
and the reason is worth recording so it is not attempted a second time.

The rule wanted: a claim about what a product cannot do, or a numeric ceiling, must have a source
next to it. It exists because three claims in this repository were written as findings and turned out
to be documented behaviour, and one negative about a vendor capability was written after a search that
never opened the product's own feature table. Every one of them passed every other check here.

Three detectors were written and measured against the tracked tree:

| Detector | Findings | Why it does not work |
|---|---|---|
| Capability negatives and ceilings, source required within 3 lines | 167 | Matches the authoring rules that *describe* the wording, and the cells of support matrices, where the claim is the content |
| Any figure carrying a throughput, IOPS or capacity unit | 868 | Measurement records are dense with figures, and their provenance sits in a table caption or a "conditions" section, not on the line |
| "No source found" with no record of what was checked | 23, of which ~15 were noise | Matches glossary rows defining `unconfirmed`, and runtime errors — a missing Java binary is not a missing citation |

None is usable. Widening the window until the tree passes would leave a check that cannot fail;
annotating 868 lines produces markers nobody maintains. The third could be narrowed further, but at
that point the detector is being shaped to fit the result it is wanted to produce, which is the
failure mode this page exists to warn about.

So the control is a process one, in
[CONTRIBUTING.md](../../CONTRIBUTING.md#できないと書く前に開くページ): a table naming the index page
to open for each kind of claim, because in the case that prompted this, the answer was one row of a
table on a page that was never opened. **A checker can see whether a citation is present. It cannot
see whether anyone read it, and presence was never the thing that failed.**

The general rule: **before adding a check, run it and read the findings.** A detector that fires
hundreds of times on a tree the maintainers consider clean is not measuring the rule it was written
for, and merging it teaches everyone to pass it rather than to follow the rule.

## When a step fails, four reads before the next attempt

An error message names a symptom. It does not name a cause, and on this stack it routinely points
somewhere else: a domain account that does not exist reports `The specified network password is not
correct.`, and a CIFS share that does not exist reports `The network name cannot be found.` One
session lost three attempts to that pair, and all three were the same mistake — a name inferred from
adjacent data instead of read from the API that owns it.

So on any failure, in this order, before changing the command:

1. **List the causes that produce this exact message.** More than one usually does. If only one comes
   to mind, that is the assumption, not the diagnosis.
2. **Read this repository's record for the step.** The runbook, the environment README, the parameter
   file. The mount command that failed had been documented for a month.
3. **Read the authoritative source for every identifier in the command.** A name is read, never
   derived from a sibling: in one environment the SVMs are hyphenated and the volumes use
   underscores, so deriving either from the other fails. Having an id is not knowing a name.
4. **Check the vendor documentation for the mechanism**, not for the error string. That is where "SMB
   addresses a share, and only hidden administrative shares exist by default" was, and it made two of
   the three failures obvious at once.

Then act. **Never retry the same command to see whether it fails the same way** — it will, and the
second failure is not evidence.

**Read the whole section, not the lines that matched.** `grep | head` hid an existing parameter file
in the same session, and a narrow pattern hid the documented mount command. A truncated scan produces
a confident answer about what is not there. Where a check does the scanning, its scope is part of its
result: `make ja-headings` listed only tracked files, so a new document passed locally and failed in
CI on the commit that added it.

Worked example, with sources and the error-to-cause table:
[SMB でマウントできる名前と、識別子を読む場所](../ja/reference/limits/smb-share-and-identifier-reading.md).
