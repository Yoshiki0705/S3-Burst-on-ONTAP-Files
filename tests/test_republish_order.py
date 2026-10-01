"""The republish order and its two stop conditions, verified with mocks.

Updating a published post is irreversible, so the design fixes the order fetch -> diff -> decide ->
apply -> verify and two conditions that stop it before the apply (requirement 4.7): the fetch
failed, or the live body is newer than the local draft. These tests drive that sequence through a
mock seam and assert on the recorded order and the decision, with the stop cases first -- the worst
way for this to break is to apply when it should have stopped, overwriting a published post's newer
body with an older local draft.

No live platform is touched. The "fetch", "apply", and "verify" side effects are mocks that record
their call; the decision under test is pure. That is the whole point of keeping decide_apply,
insert_paragraphs, and verify_applied free of I/O: the order and the stop conditions are testable
offline.
"""

from __future__ import annotations

import check_republish_order as rp
import pytest

# A live body that already carries two publish-time edits the local draft does not: a pinned commit
# SHA and a resolved cross-article URL. These are the markers that prove the published copy has run
# ahead of the local draft.
LIVE_AHEAD = (
    "# Article\n"
    "See [the guide](https://github.com/owner/repo/blob/b39f5d8a/docs/x.md).\n"
    "Related: https://dev.to/owner/the-other-article-35pi\n"
    "## What hasn't been measured yet\n"
    "- an existing item\n"
    "## Closing\n"
)

# The local draft: same article, but the links are still on `main` and a placeholder, i.e. the
# draft is BEHIND the published copy on those two markers.
LOCAL_BEHIND = (
    "# Article\n"
    "See [the guide](https://github.com/owner/repo/blob/main/docs/x.md).\n"
    "Related: TODO-LINK-OTHER\n"
    "## What hasn't been measured yet\n"
    "- an existing item\n"
    "- a new high-file-count item the local draft adds\n"
    "## Closing\n"
)

# The publish-time markers the caller expects the live body to already carry.
EXPECTED_LIVE_MARKERS = (
    "/blob/b39f5d8a/",
    "https://dev.to/owner/the-other-article-35pi",
)


# --- the two stop conditions (requirement 4.7), first -----------------------------------------


def test_a_failed_fetch_stops_the_apply_and_records_a_reason() -> None:
    """Could-not-read is not an empty article; nothing is applied and the reason is kept."""
    fetch = rp.FetchResult(ok=False, reason="editor did not yield its body")
    decision = rp.decide_apply(fetch, LOCAL_BEHIND, EXPECTED_LIVE_MARKERS)
    assert decision.apply is False
    assert "fetch failed" in decision.reason
    assert "editor did not yield its body" in decision.reason


def test_a_live_body_newer_than_local_stops_the_apply() -> None:
    """The published copy carries publish-time edits the local draft lacks; do not overwrite it."""
    fetch = rp.FetchResult(ok=True, body=LIVE_AHEAD)
    decision = rp.decide_apply(fetch, LOCAL_BEHIND, EXPECTED_LIVE_MARKERS)
    assert decision.apply is False
    assert "newer than the local draft" in decision.reason
    # Both leading markers are named, so the reconciliation knows what to pull back.
    assert set(decision.live_leads_on) == set(EXPECTED_LIVE_MARKERS)


def test_the_apply_proceeds_when_the_draft_is_reconciled() -> None:
    """Once the local draft carries the same publish-time markers, the live body no longer leads."""
    reconciled_local = LIVE_AHEAD.replace(
        "- an existing item\n",
        "- an existing item\n- a new high-file-count item the local draft adds\n",
    )
    fetch = rp.FetchResult(ok=True, body=LIVE_AHEAD)
    decision = rp.decide_apply(fetch, reconciled_local, EXPECTED_LIVE_MARKERS)
    assert decision.apply is True
    assert decision.live_leads_on == []


def test_no_expected_markers_means_the_apply_proceeds() -> None:
    """With nothing claimed to lead, a successful fetch allows the apply."""
    fetch = rp.FetchResult(ok=True, body=LIVE_AHEAD)
    decision = rp.decide_apply(fetch, LOCAL_BEHIND, expected_live_markers=())
    assert decision.apply is True


# --- the apply is new-paragraphs-only (requirement 4.4) ---------------------------------------


def test_insert_adds_before_the_anchor_and_touches_nothing_else() -> None:
    new = "- a new high-file-count item\n"
    out = rp.insert_paragraphs(LIVE_AHEAD, "## Closing\n", new)
    # The new paragraph is present, immediately before the anchor.
    assert new + "## Closing\n" in out
    # Every original line survives: the apply deletes and rewrites nothing.
    for line in LIVE_AHEAD.splitlines():
        assert line in out
    # Exactly the new content was added.
    assert len(out) == len(LIVE_AHEAD) + len(new)


def test_insert_refuses_an_absent_anchor() -> None:
    with pytest.raises(ValueError, match="anchor not found"):
        rp.insert_paragraphs(LIVE_AHEAD, "## A heading that is not there\n", "- x\n")


def test_insert_refuses_a_non_unique_anchor() -> None:
    doubled = LIVE_AHEAD + "## Closing\n"
    with pytest.raises(ValueError, match="non-unique anchor"):
        rp.insert_paragraphs(doubled, "## Closing\n", "- x\n")


# --- step 5 verifies by re-fetching, not by trusting the save ---------------------------------


def test_verify_reports_a_paragraph_that_did_not_take() -> None:
    """A save can report success and not take effect; the re-fetch is what confirms it."""
    refetched = LIVE_AHEAD  # the new paragraph did not actually land
    missing = rp.verify_applied(refetched, ["- a new high-file-count item"])
    assert missing == ["- a new high-file-count item"]


def test_verify_passes_when_the_paragraph_is_present_on_refetch() -> None:
    applied = rp.insert_paragraphs(
        LIVE_AHEAD, "## Closing\n", "- a new high-file-count item\n"
    )
    missing = rp.verify_applied(applied, ["- a new high-file-count item"])
    assert missing == []


# --- the full order, driven through a recording seam ------------------------------------------


def _run_sequence(fetch: rp.FetchResult, local: str, markers) -> rp.RepublishRecorder:
    """Drive the five steps the way the production caller would, recording each.

    fetch -> diff -> decide are always performed; apply and verify only when decide allows. This is
    the sequence the browser-driving caller follows, with the side effects replaced by recording.
    """
    rec = rp.RepublishRecorder()
    rec.record("fetch")
    rec.record("diff")
    rec.record("decide")
    decision = rp.decide_apply(fetch, local, markers)
    if decision.apply:
        rec.record("apply")
        rec.record("verify")
    return rec


def test_the_sequence_runs_in_order_when_the_apply_proceeds() -> None:
    reconciled_local = LIVE_AHEAD.replace(
        "- an existing item\n",
        "- an existing item\n- a new item\n",
    )
    rec = _run_sequence(
        rp.FetchResult(ok=True, body=LIVE_AHEAD),
        reconciled_local,
        EXPECTED_LIVE_MARKERS,
    )
    assert rec.calls == ["fetch", "diff", "decide", "apply", "verify"]
    assert rec.order_is_valid()


def test_the_sequence_stops_at_decide_when_the_fetch_failed() -> None:
    rec = _run_sequence(
        rp.FetchResult(ok=False, reason="load error"),
        LOCAL_BEHIND,
        EXPECTED_LIVE_MARKERS,
    )
    # apply and verify are never reached; the recorded order is still valid (a prefix of STEPS).
    assert rec.calls == ["fetch", "diff", "decide"]
    assert rec.order_is_valid()


def test_the_sequence_stops_at_decide_when_the_live_body_leads() -> None:
    rec = _run_sequence(
        rp.FetchResult(ok=True, body=LIVE_AHEAD), LOCAL_BEHIND, EXPECTED_LIVE_MARKERS
    )
    assert rec.calls == ["fetch", "diff", "decide"]
    assert rec.order_is_valid()


def test_apply_before_fetch_is_an_invalid_order() -> None:
    """A guard on the recorder itself: applying before fetching is rejected as out of order."""
    rec = rp.RepublishRecorder()
    rec.record("apply")
    rec.record("fetch")
    assert rec.order_is_valid() is False
