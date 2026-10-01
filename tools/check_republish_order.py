#!/usr/bin/env python3
"""The order a published post is updated in, and the two conditions that stop it.

Updating an already-published article is irreversible: once the new body is saved, the old body is
gone from the platform, and a success response is not evidence that the save was correct. The design
(§未計測事項の反映パイプライン, §不可逆操作のガード) fixes a fixed order to make the operation safe:

    1. fetch   -- read the live body from the platform (both languages, each on its own)
    2. diff    -- compare the live body against the local draft and record the difference
    3. decide  -- stop if the fetch failed, or if the live body is newer than the local draft
    4. apply   -- insert the minimal new paragraphs (new paragraphs only; no edit or deletion)
    5. verify  -- re-fetch the live body and confirm the new paragraphs are present

This module is the decision at step 3 and the shape of the whole sequence, as pure functions. It
does NOT fetch, save, or re-fetch -- those are side effects the caller performs (here, through the
browser). Keeping the decision pure is what lets the order and the two stop conditions be tested
with mocks, without touching a live platform. The caller drives the five steps and consults
``decide_apply`` before step 4; the recorded order of its calls is what the tests assert on.

The two stop conditions are the ones the design's error table lists for requirement 4.7:

  * the fetch failed -- there is no live body to compare against, so nothing is applied, and the
    reason is recorded. A missing fetch is not the same as an empty article: the first is "could
    not read", the second is "read, and it was empty", and only the first stops the apply here.
  * the live body is newer than the local draft -- the platform copy carries information the local
    draft does not (this repository's drafts are JA-source-of-truth with the EN mirror following,
    and the published copy has run ahead of the local file before: SHA-pinned links, resolved
    cross-article URLs). Overwriting from the local draft would replace that newer information with
    an older copy. So when the live body leads, the apply stops and the direction is reported --
    the local draft must be reconciled first.

"Newer" is not a timestamp here. The caller supplies the set of markers it expects the live body to
already carry (the publish-time edits: pinned SHAs, resolved links). If the live body carries a
marker the local draft lacks, the live body leads for that marker, and the apply stops. This keeps
the check offline and deterministic -- it reasons about content, not about clocks that two systems
would disagree on.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

# The ordered step names, so the caller and the tests name the sequence the same way and cannot
# drift apart.
STEPS = ("fetch", "diff", "decide", "apply", "verify")


@dataclass
class FetchResult:
    """What a step-1 fetch returns: either a body, or a failure with a reason.

    ``ok`` false means the platform could not be read at all -- a load error, an auth failure, an
    editor that did not yield its body. ``body`` is only meaningful when ``ok`` is true. An empty
    string with ``ok`` true is a real (if empty) article, which is a different answer from a failed
    fetch and does not by itself stop the apply.
    """

    ok: bool
    body: str = ""
    reason: str = ""


@dataclass
class Decision:
    """The step-3 verdict: whether to apply, and if not, why not."""

    apply: bool
    reason: str = ""
    # Markers the live body already carries that the local draft lacks -- the evidence that the live
    # body leads. Empty when the apply proceeds.
    live_leads_on: list[str] = field(default_factory=list)


def decide_apply(
    fetch: FetchResult,
    local_body: str,
    expected_live_markers: Sequence[str] = (),
) -> Decision:
    """Decide whether step 4 (apply) may proceed, per requirement 4.7.

    Stops when the fetch failed, or when the live body carries any ``expected_live_markers`` that the
    local draft does not -- that is the live body leading, and applying from the local draft would
    overwrite newer information. Otherwise the apply proceeds.
    """
    if not fetch.ok:
        return Decision(
            apply=False,
            reason=(
                "fetch failed; there is no live body to compare against, so nothing is applied "
                f"({fetch.reason or 'no reason given'})"
            ),
        )

    # A marker the live body has and the local draft lacks means the published copy is ahead: it
    # carries a publish-time edit (a pinned SHA, a resolved cross-article URL) not yet mirrored
    # back into the local draft. Applying from the local draft would undo it.
    live_leads_on = [
        marker
        for marker in expected_live_markers
        if marker in fetch.body and marker not in local_body
    ]
    if live_leads_on:
        return Decision(
            apply=False,
            reason=(
                "live body is newer than the local draft: it carries "
                f"{len(live_leads_on)} marker(s) the local draft lacks, so the apply is stopped "
                "and the local draft must be reconciled first (requirement 4.7)"
            ),
            live_leads_on=live_leads_on,
        )

    return Decision(apply=True)


def insert_paragraphs(live_body: str, anchor: str, new_paragraphs: str) -> str:
    """Insert ``new_paragraphs`` immediately before ``anchor`` in ``live_body``; add nothing else.

    This is the step-4 apply as a pure string transform: new paragraphs only, no existing line
    touched (requirement 4.4). ``anchor`` is a line that already exists in the live body (the
    heading the new paragraphs go above). Raises if the anchor is absent or appears more than once,
    because inserting against an anchor that is not uniquely located would place the paragraphs
    somewhere other than intended -- and this operation is not reversible.
    """
    count = live_body.count(anchor)
    if count == 0:
        raise ValueError(
            f"anchor not found in live body: {anchor!r}; refusing to insert at an unknown position"
        )
    if count > 1:
        raise ValueError(
            f"anchor appears {count} times in live body: {anchor!r}; refusing to insert against a "
            f"non-unique anchor"
        )
    body = new_paragraphs if new_paragraphs.endswith("\n") else new_paragraphs + "\n"
    return live_body.replace(anchor, body + anchor, 1)


def verify_applied(refetched_body: str, new_paragraphs: Sequence[str]) -> list[str]:
    """Step 5: return the paragraphs still missing from the re-fetched body; empty means verified.

    A save on these platforms can report success and silently not take effect, so the apply is
    confirmed by reading the live body again, not by trusting the save's response. Each expected
    paragraph (or a distinctive substring of it) must be present in the re-fetched body.
    """
    return [
        paragraph for paragraph in new_paragraphs if paragraph not in refetched_body
    ]


class RepublishRecorder:
    """Records the sequence of steps a caller performs, so the order can be asserted in a test.

    Not used in production -- the production caller drives the browser directly. This exists so a
    mock-based test can drive the same five step names through a seam and assert they happened in
    the fixed order, with ``apply`` reached only when ``decide`` allowed it.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def record(self, step: str) -> None:
        if step not in STEPS:
            raise ValueError(f"unknown step {step!r}; expected one of {STEPS}")
        self.calls.append(step)

    def order_is_valid(self) -> bool:
        """True when the recorded calls are a prefix-respecting subsequence of STEPS.

        Each step may appear (once per language), and no step may precede an earlier one. ``apply``
        and ``verify`` are optional -- the sequence stops early when ``decide`` returns no-apply.
        """
        last = -1
        for call in self.calls:
            index = STEPS.index(call)
            if index < last:
                return False
            last = index
        return True
