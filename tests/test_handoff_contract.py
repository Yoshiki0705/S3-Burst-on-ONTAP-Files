"""The handoff-contract gate, verified against the ways it is meant not to fail.

A handoff contract is the file that carries one unit of delegation from this Spoke to the Hub (or
back): which Technical Report, what deliverable is expected, what the Spoke needs to reference, and
the standing assertion that the public-output rules apply on the far side too. The design fixes six
required fields and the behaviour on a missing one -- the gate does not raise, it reports the
missing field names and treats the contract as incomplete, so a caller keeps the record it built
rather than losing it to an exception. These tests assert on the returned findings, not on an
exception.

Separately, a reference that points into another GitHub repository has to be an absolute URL
(requirement 2.4): a relative link resolves against the wrong repository root once it is read from
the other side. The gate checks the *form* of such a reference offline; whether the target actually
resolves (HTTP 404) is left to the network gate, as the body of the checker records.

Contract values here are placeholders. Repository names are real where that reads naturally, but no
case number, person, or internal identifier appears -- the contract never carries those, and a test
that wrote one would be putting into a tracked file exactly what the audit removes everywhere else.
"""

from __future__ import annotations

import check_handoff_contract as handoff


def sound_contract() -> dict:
    """A contract with all six required fields filled -- the shape that must pass."""
    return {
        "delegator_repo": "s3-burst-on-ontap-files",
        "delegatee_repo": "fsxn-adoption-playbook",
        "target_tr": "High_file_count_NAS_workloads.pdf",
        "expected_deliverable": "高ファイル数ワークロードの横断的な採用判断材料を Hub に集約する",
        "reference_requirements": [
            "この Spoke から Hub の該当ページへ絶対 URL で参照できること",
        ],
        "public_output_rules_apply": True,
    }


# --- the required-field gate -------------------------------------------------------------------


def test_a_complete_contract_passes() -> None:
    assert handoff.check(sound_contract()) == []


def test_each_missing_field_is_reported_by_name() -> None:
    """Dropping any one required field is reported, and the finding names that field."""
    for field in handoff.REQUIRED_FIELDS:
        contract = sound_contract()
        del contract[field]
        findings = handoff.check(contract)
        assert findings, f"removing {field} should produce a finding"
        assert any(field in finding for finding in findings), (
            f"the finding should name the missing field {field!r}"
        )


def test_all_six_required_fields_are_checked() -> None:
    """The gate guards exactly the six fields the design fixes -- no more, no fewer."""
    assert set(handoff.REQUIRED_FIELDS) == {
        "delegator_repo",
        "delegatee_repo",
        "target_tr",
        "expected_deliverable",
        "reference_requirements",
        "public_output_rules_apply",
    }


def test_an_empty_string_counts_as_missing() -> None:
    """A field present but blank is as absent as one that is not there at all."""
    contract = sound_contract()
    contract["expected_deliverable"] = ""
    findings = handoff.check(contract)
    assert any("expected_deliverable" in finding for finding in findings)


def test_an_empty_reference_list_counts_as_missing() -> None:
    """reference_requirements present but empty carries no reference, so it is incomplete."""
    contract = sound_contract()
    contract["reference_requirements"] = []
    findings = handoff.check(contract)
    assert any("reference_requirements" in finding for finding in findings)


def test_a_none_value_counts_as_missing() -> None:
    contract = sound_contract()
    contract["delegatee_repo"] = None
    findings = handoff.check(contract)
    assert any("delegatee_repo" in finding for finding in findings)


def test_public_output_rules_apply_must_be_true() -> None:
    """The field asserts the rules apply on the far side; false is not an acknowledgement of them."""
    contract = sound_contract()
    contract["public_output_rules_apply"] = False
    findings = handoff.check(contract)
    assert any("public_output_rules_apply" in finding for finding in findings)


# --- the reference-form gate (requirement 2.4) -------------------------------------------------


def test_an_absolute_cross_repo_url_passes() -> None:
    contract = sound_contract()
    contract["reference_requirements"] = [
        "https://github.com/example-owner/fsxn-adoption-playbook/blob/main/docs/ja/x.md",
    ]
    assert handoff.check(contract) == []


def test_a_relative_cross_repo_reference_is_reported() -> None:
    """A relative link cannot address another repository; it resolves against the wrong root."""
    contract = sound_contract()
    contract["reference_requirements"] = [
        "../fsxn-adoption-playbook/docs/ja/x.md",
    ]
    findings = handoff.check(contract)
    assert findings
    assert any(
        "absolute" in finding.lower() or "絶対" in finding for finding in findings
    )


def test_a_bare_path_reference_is_reported() -> None:
    contract = sound_contract()
    contract["reference_requirements"] = ["docs/ja/x.md"]
    findings = handoff.check(contract)
    assert findings


def test_a_non_url_prose_reference_without_a_path_passes() -> None:
    """A reference requirement may be prose, not a link; only path-like references must be URLs."""
    contract = sound_contract()
    contract["reference_requirements"] = [
        "この Spoke から Hub の該当ページへ絶対 URL で参照できること",
    ]
    assert handoff.check(contract) == []


# --- the non-raising contract ------------------------------------------------------------------


def test_check_does_not_raise_on_a_wholly_empty_contract() -> None:
    """Every required field missing at once is still reported, not raised."""
    findings = handoff.check({})
    assert isinstance(findings, list)
    assert len(findings) >= len(handoff.REQUIRED_FIELDS)


def test_check_does_not_raise_on_a_non_mapping() -> None:
    """A contract that is not even an object is reported, not raised."""
    findings = handoff.check([])
    assert isinstance(findings, list)
    assert findings
