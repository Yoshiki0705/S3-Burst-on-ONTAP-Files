"""`llms.txt` restates the stage vocabulary and the central claim. This checks it still matches.

`llms.txt` exists for crawlers that will not follow a link, so the four stages and the scope of the
central claim are written out there rather than referenced. That makes it a second copy of something
`docs/*/verification-status.md` owns, and a second copy drifts: lowering a stage or re-measuring
touches the verification status document, and nothing today would notice that `llms.txt` still holds
the old figure while presenting itself as the authoritative summary for a machine reader.

These assertions are deliberately about identity, not phrasing. `llms.txt` may explain a stage in its
own words; it may not name a stage the repository does not define, and it may not state an
environment value that the verification status document does not.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LLMS = ROOT / "llms.txt"
STATUS_JA = ROOT / "docs" / "ja" / "verification-status.md"
STATUS_EN = ROOT / "docs" / "en" / "verification-status.md"
# Version strings are owned by two documents, not one: a measured environment belongs to the
# verification status, a minimum requirement to the support matrix. Checking against only the first
# would fail on `9.17.1 or later`, which is a support statement and not a measurement.
VERSION_OWNERS = (
    STATUS_JA,
    STATUS_EN,
    ROOT / "docs" / "ja" / "support-matrix.md",
    ROOT / "docs" / "en" / "support-matrix.md",
)

# The stage names, as the English verification status document defines them in its table.
STAGES = ("verified", "documented", "unverified", "unconfirmed")


def test_llms_txt_exists() -> None:
    # A missing file would make every assertion below vacuously true.
    assert LLMS.is_file(), "llms.txt is the machine-readable entry point and must exist"


def test_the_stage_list_matches_the_definition() -> None:
    """The bulleted stages in llms.txt are exactly the stages the status document defines."""
    listed = re.findall(r"^- \*\*([a-z]+)\*\* —", llms_text(), re.MULTILINE)
    assert tuple(listed) == STAGES, (
        f"llms.txt lists {listed}, but the verification status document defines {list(STAGES)}. "
        "Change both or neither."
    )
    status = STATUS_EN.read_text(encoding="utf-8")
    for stage in STAGES:
        assert re.search(rf"^\| {stage} \|", status, re.MULTILINE), (
            f"'{stage}' is listed in llms.txt but not defined in {STATUS_EN.name}"
        )


def test_restated_environment_values_come_from_the_status_document() -> None:
    """Every measurement value llms.txt restates appears in the document that owns it.

    Catches the case that matters: a re-measurement updates the status document and llms.txt keeps
    quoting the superseded figure to a machine reader that will not check.
    """
    text = llms_text()
    both = STATUS_JA.read_text(encoding="utf-8") + STATUS_EN.read_text(encoding="utf-8")
    owners = "".join(path.read_text(encoding="utf-8") for path in VERSION_OWNERS)

    dates = set(re.findall(r"\b20\d{2}-\d{2}-\d{2}\b", text))
    versions = set(re.findall(r"\b9\.\d+\.\d+[A-Z0-9]*\b", text))
    regions = set(re.findall(r"\b[a-z]{2}-[a-z]+-\d\b", text))
    samples = set(re.findall(r"\bn=\d+\b", text))

    for label, values, corpus, owner in (
        ("date", dates, both, "verification status document"),
        ("ONTAP version", versions, owners, "verification status or support matrix"),
        ("Region", regions, both, "verification status document"),
        ("sample size", samples, both, "verification status document"),
    ):
        for value in sorted(values):
            assert value in corpus, (
                f"llms.txt states {label} {value!r}, which appears in no {owner}. "
                "Restate it from there or drop it."
            )


def test_the_status_document_is_named_as_the_source() -> None:
    """A machine reader is told where the authoritative version is, not just given the summary."""
    assert "verification-status.md" in llms_text(), (
        "llms.txt restates stages and scope, so it must point at the document that owns them"
    )


def llms_text() -> str:
    return LLMS.read_text(encoding="utf-8")
