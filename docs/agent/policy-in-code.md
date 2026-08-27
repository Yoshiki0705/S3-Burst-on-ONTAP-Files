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
