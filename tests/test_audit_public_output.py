"""The public-output audit, checked in both directions.

A gate is only trustworthy once it has been shown to fail on input it must reject. These tests
therefore assert the rejection first and the allowance second, for every category.

The `vendor-ref` case is the reason this file exists. The portability table in this repository
cites a vendor page whose URL path contains a product name that must never be *proposed*:

    https://docs.netapp.com/us-en/bluexp-cloud-volumes-ontap/concept-client-protocols.html

The sibling repository's audit script matched that product name case-sensitively, so a lower-case
occurrence inside a URL slipped through — and a rule that misses the lower-case spelling also
misses it in prose. Making the match case-insensitive closes that, and immediately turns every
legitimate citation into a finding. Hence `allow:vendor-ref`, and hence a test pinning the exact
URL: the marker and the rule have to stay in agreement, and the next person to touch either one
should find out from a red test rather than from a reader.
"""

from __future__ import annotations

import audit_public_output as audit
from conftest import (
    REAL_LOOKING_ACCOUNT,
    REAL_LOOKING_FSX_ID,
    REAL_LOOKING_FSX_ID_CONSOLE,
)

CVO_CITATION = (
    "| Cloud Volumes ONTAP | ONTAP S3 | "
    "[Client protocols](https://docs.netapp.com/us-en/bluexp-cloud-volumes-ontap/"
    "concept-client-protocols.html) |"
)


def categories(line: str, **kwargs) -> set[str]:
    return {category for category, _ in audit.audit_line(line, **kwargs)}


# --- vendor-ref ---------------------------------------------------------------------------------


def test_a_citation_url_is_flagged_without_the_marker() -> None:
    assert "vendor-ref" in categories(CVO_CITATION)


def test_the_marker_clears_the_citation_url() -> None:
    marked = CVO_CITATION + " <!-- allow:vendor-ref source URL path, not a proposal -->"
    assert categories(marked) == set()


def test_the_product_name_is_matched_regardless_of_case() -> None:
    """The lower-case spelling is the one that reached production undetected."""
    for spelling in ("BlueXP", "bluexp", "BLUEXP"):
        assert "vendor-ref" in categories(f"Use {spelling} to manage the cluster.")


def test_proposing_a_forbidden_product_is_still_flagged_in_prose() -> None:
    for line in (
        "NetApp Workload Factory can provision the volume.",
        "Open NetApp Console and create the bucket.",
    ):
        assert "vendor-ref" in categories(line)


def test_vendor_ref_does_not_excuse_a_naming_violation_on_the_same_line() -> None:
    """The marker is scoped to one rule. A citation line may not also misname the service."""
    line = "FSxN and BlueXP <!-- allow:vendor-ref -->"
    found = categories(line)
    assert "naming" in found
    assert "vendor-ref" not in found


# --- naming ------------------------------------------------------------------------------------


def test_forbidden_service_spellings_are_flagged() -> None:
    for line in ("FSxN volumes", "FSx ONTAP volumes", "FSx NetApp volumes"):
        assert "naming" in categories(line)


def test_bare_fsx_is_flagged_but_the_accepted_forms_are_not() -> None:
    assert "naming" in categories("The FSx file system is Multi-AZ.")
    assert "naming" not in categories("Amazon FSx for NetApp ONTAP is the origin.")
    assert "naming" not in categories("The FSx for ONTAP origin volume.")


def test_sibling_aws_services_are_not_misread_as_the_bare_form() -> None:
    for line in (
        "FSx for Windows File Server",
        "FSx for Lustre",
        "FSx for OpenZFS",
    ):
        assert "naming" not in categories(line)


# --- neutrality --------------------------------------------------------------------------------


def test_vendor_versus_framing_is_flagged() -> None:
    for line in (
        "競合ツールと比較する",
        "This approach beats DataSync",
        "FlexCache is better than a copy job",
        "a game-changer for HiL testing",
    ):
        assert "neutrality" in categories(line)


def test_declaring_neutrality_is_itself_flagged() -> None:
    """Showing it is the requirement; announcing it is what this repository does not do."""
    for line in (
        "中立性の核はここにある",
        "ベンダー中立の立場をとる",
        "This comparison is vendor-neutral.",
    ):
        assert "neutrality" in categories(line)


def test_symmetric_trade_off_wording_passes() -> None:
    line = (
        "S3 単独は新規アプリに向き、既存の NFS / SMB を変更できない場合には向かない。"
    )
    assert categories(line) == set()


# --- conflation --------------------------------------------------------------------------------


def test_naming_both_mechanisms_without_distinguishing_them_is_flagged() -> None:
    line = "FlexCache duality により Cache ボリュームへ S3 AP を接続できる。"
    assert "conflation" in categories(line)


def test_stating_that_they_differ_satisfies_the_rule_without_a_marker() -> None:
    line = "ONTAP の FlexCache duality と、S3 Access Point を接続することは別の機構である。"
    assert "conflation" not in categories(line)


def test_the_english_wording_also_satisfies_the_rule() -> None:
    line = "FlexCache duality and attaching an S3 Access Point are separate mechanisms."
    assert "conflation" not in categories(line)


def test_either_mechanism_alone_is_not_flagged() -> None:
    assert "conflation" not in categories("FlexCache duality is an ONTAP feature.")
    assert "conflation" not in categories(
        "The S3 Access Point is on the origin volume."
    )


# --- pii ---------------------------------------------------------------------------------------


def test_identifiers_that_must_never_ship_are_flagged() -> None:
    for line in (
        "See case 123456 for details.",
        "Tracked as DB-I-15824.",
        "Open /Users/someone/Projects/thing.md",
        "Contact someone@somecompany.example",
        "The management LIF is 10.0.4.17",
        f"Account {REAL_LOOKING_ACCOUNT} owns the bucket.",
        f"| Origin cluster | {REAL_LOOKING_FSX_ID_CONSOLE} (`lab-cluster`), SINGLE_AZ_1 |",
        f"The file system is {REAL_LOOKING_FSX_ID}.",
    ):
        assert "pii" in categories(line), line


def test_sanctioned_placeholders_pass() -> None:
    for line in (
        "Account 123456789012 owns the bucket.",
        "The management LIF is 10.0.x.x",
        "Contact reviewer@example.com",
        "The file system is fs-0123456789abcdef0.",
    ):
        assert "pii" not in categories(line), line


# --- role-label --------------------------------------------------------------------------------


def test_a_role_labeled_callout_is_flagged() -> None:
    for line in (
        "> **AppSec lens**: rotate the secret.",
        "> **セキュリティ担当の視点**: rotate the secret.",
    ):
        assert "role-label" in categories(line)


def test_a_topic_labeled_callout_passes() -> None:
    for line in (
        "> **Security note**: rotate the secret.",
        "> **セキュリティに関する補足**: rotate the secret.",
    ):
        assert "role-label" not in categories(line)


# --- escape hatches ----------------------------------------------------------------------------


def test_allow_all_clears_a_line_entirely() -> None:
    assert categories("FSxN and BlueXP <!-- allow:all -->") == set()


def test_a_file_level_allowance_applies_to_every_line() -> None:
    assert categories("FSxN volumes", file_allowed=frozenset({"naming"})) == set()


def test_an_unknown_file_level_category_is_rejected_loudly() -> None:
    """A typo in the declaration must not silently disable nothing, or everything."""
    import pytest

    with pytest.raises(SystemExit):
        audit.file_allowances(["<!-- audit-file-allow: nameing -->"])


def test_every_allow_token_the_regex_accepts_is_a_real_category() -> None:
    """`allow:typo` must not read as a valid marker, and each category must be reachable."""
    for category in audit.CATEGORIES:
        match = audit.ALLOW.search(f"<!-- allow:{category} -->")
        assert match, (
            f"{category} is listed in CATEGORIES but the ALLOW regex rejects it"
        )
    assert audit.ALLOW.search("<!-- allow:nonsense -->") is None
