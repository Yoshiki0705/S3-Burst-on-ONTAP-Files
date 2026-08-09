"""Invariants of the deployment templates that a linter cannot see.

`cfn-lint` proves the CloudFormation is well formed and `terraform validate` proves the HCL matches
the provider schema. Neither has an opinion about whether a template enables a feature that makes a
file system undeletable for six months, pins its provider, or ships a real network in an example
file. Those are the things that hurt, so they are asserted here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
AWS = ROOT / "environments" / "aws-origin"
ONPREM = ROOT / "environments" / "onprem-cache"


def aws_template() -> str:
    return (AWS / "template.yaml").read_text(encoding="utf-8")


def onprem_files() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in ONPREM.glob("*.tf")}


def pinned_provider_version() -> str:
    """The provider's pinned version, read from inside required_providers.

    Scoped to the provider block on purpose: a bare search for `version = "..."` finds
    `required_version` first, which is a Terraform CLI constraint and legitimately a range.
    """
    versions = onprem_files()["versions.tf"]
    block = re.search(r"required_providers\s*\{(.*?)\n  \}", versions, re.S)
    assert block, "required_providers block not found in versions.tf"
    match = re.search(r'version\s*=\s*"([^"]+)"', block.group(1))
    assert match, "no provider version found inside required_providers"
    return match.group(1)


# --- the templates exist and are wired to the guides ---------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "environments/README.md",
        "environments/aws-origin/template.yaml",
        "environments/aws-origin/params.example.json",
        "environments/aws-origin/access-point.example.json",
        "environments/onprem-cache/main.tf",
        "environments/onprem-cache/variables.tf",
        "environments/onprem-cache/versions.tf",
        "environments/onprem-cache/outputs.tf",
        "environments/onprem-cache/terraform.tfvars.example",
        "docs/ja/deployment/aws-cloudformation.md",
        "docs/ja/deployment/onprem-terraform.md",
        "docs/en/deployment/aws-cloudformation.md",
        "docs/en/deployment/onprem-terraform.md",
    ],
)
def test_the_expected_files_exist(path: str) -> None:
    assert (ROOT / path).is_file(), path


def test_both_deployment_guides_are_tier_one() -> None:
    """A guide a reader follows while creating billable resources belongs in their language."""
    manifest = (ROOT / "docs" / "i18n-manifest.txt").read_text(encoding="utf-8")
    for entry in ("deployment/aws-cloudformation.md", "deployment/onprem-terraform.md"):
        assert entry in manifest, entry


def test_the_guides_are_reachable_from_both_hubs() -> None:
    ja = (ROOT / "README.md").read_text(encoding="utf-8")
    en = (ROOT / "docs" / "en" / "README.md").read_text(encoding="utf-8")
    assert "docs/ja/deployment/aws-cloudformation.md" in ja
    assert "docs/ja/deployment/onprem-terraform.md" in ja
    assert "deployment/aws-cloudformation.md" in en
    assert "deployment/onprem-terraform.md" in en


# --- irreversibility: the invariant that cost a sibling repository six months ---------------------


IMMUTABILITY = (
    "SnaplockConfiguration",
    "SnaplockType",
    "snaplock_type",
    "AuditLogVolume",
    "PrivilegedDelete",
    "snapshot_locking_enabled",
    "SnapshotLockingEnabled",
    "VolumeAppendModeEnabled",
    "ObjectLock",
    "put-object-retention",
    "PERMANENTLY_DISABLED",
    "COMPLIANCE",
)


@pytest.mark.parametrize("token", IMMUTABILITY)
def test_the_cloudformation_template_enables_no_immutability_feature(
    token: str,
) -> None:
    """A 128 MiB SnapLock audit log volume once made a whole file system undeletable for six months.

    A feature whose purpose is to remove the ability to delete data must never appear in a template
    that somebody deploys to try something out.
    """
    assert token not in aws_template(), token


@pytest.mark.parametrize("token", IMMUTABILITY)
def test_the_terraform_configuration_enables_no_immutability_feature(
    token: str,
) -> None:
    combined = "\n".join(onprem_files().values())
    assert token not in combined, token


def test_a_verification_environment_can_be_deleted() -> None:
    """DeletionPolicy: Retain on a file system would leave the bill running after a delete-stack."""
    assert "DeletionPolicy: Retain" not in aws_template()
    assert "prevent_destroy = true" not in "\n".join(onprem_files().values())


# --- supply chain ---------------------------------------------------------------------------------


def test_the_terraform_provider_is_pinned_to_an_exact_version() -> None:
    """A range lets a provider release change behaviour between two applies of unchanged config."""
    pinned = pinned_provider_version()
    for operator in ("~>", ">=", "<=", ">", "<", "!="):
        assert operator not in pinned, (
            f"provider version {pinned!r} is a range, not a pin"
        )
    assert re.fullmatch(r"\d+\.\d+\.\d+", pinned), pinned


def test_the_lock_file_is_committed_and_agrees_with_versions_tf() -> None:
    """The lock file records provider hashes; it is the Terraform equivalent of an exact pin."""
    lock = ONPREM / ".terraform.lock.hcl"
    assert lock.is_file(), "run terraform init and commit .terraform.lock.hcl"
    text = lock.read_text(encoding="utf-8")
    pinned = pinned_provider_version()
    assert re.search(rf'version\s*=\s*"{re.escape(pinned)}"', text), (
        f"the lock file does not record {pinned}; run terraform init after changing versions.tf"
    )
    assert "hashes = [" in text, "the lock file records no hashes"


def test_the_ami_is_resolved_rather_than_hardcoded() -> None:
    """A hardcoded AMI ID is Region- and date-specific, and is why templates stop deploying."""
    template = aws_template()
    assert "resolve:ssm:/aws/service/ami-amazon-linux-latest" in template
    assert not re.search(r'ImageId:\s*["\']?ami-[0-9a-f]{8,}', template)


# --- access control decisions must not have convenient defaults ----------------------------------


def test_the_export_client_list_has_no_default() -> None:
    """An export rule is an access control decision; a default would be wrong for everyone."""
    variables = onprem_files()["variables.tf"]
    block = re.search(r'variable "allowed_clients" \{(.*?)\n\}', variables, re.S)
    assert block, "allowed_clients variable not found"
    # Match an assignment, not the word: the description explains *why* there is no default.
    assert not re.search(r"^\s*default\s*=", block.group(1), re.M), (
        "allowed_clients must not have a default"
    )


def test_exporting_to_the_world_is_rejected_not_merely_discouraged() -> None:
    variables = onprem_files()["variables.tf"]
    assert '"0.0.0.0/0"' in variables
    assert "validation" in variables


def test_the_cache_export_is_read_only() -> None:
    """Writes belong on the origin's access point; a writable cache invites the avoided topology."""
    main = onprem_files()["main.tf"]
    assert 'rw_rule   = ["none"]' in main or 'rw_rule = ["none"]' in main
    assert 'superuser = ["none"]' in main


def test_the_cache_does_not_set_a_security_style() -> None:
    """It is inherited from the origin at cache creation time, not chosen by the cache."""
    assert "security_style" not in onprem_files()["main.tf"]


def test_mixed_security_style_is_not_offered_on_the_origin() -> None:
    """Reported unsupported for cache volumes, so offering it would produce an unbuildable pair."""
    match = re.search(
        r"OriginVolumeSecurityStyle:.*?AllowedValues:\s*(\[[^\]]*\])",
        aws_template(),
        re.S,
    )
    assert match, "OriginVolumeSecurityStyle AllowedValues not found"
    assert "MIXED" not in match.group(1)


# --- example files carry placeholders, not real values --------------------------------------------


def test_the_parameter_example_uses_placeholders() -> None:
    params = json.loads((AWS / "params.example.json").read_text(encoding="utf-8"))
    values = {p["ParameterKey"]: p["ParameterValue"] for p in params}
    assert values["VpcId"] == "vpc-0123456789abcdef0"
    assert values["SubnetId"] == "subnet-0123456789abcdef0"


def test_the_tfvars_example_holds_no_password() -> None:
    """Terraform writes variable values into state in clear text, sensitive or not."""
    text = (ONPREM / "terraform.tfvars.example").read_text(encoding="utf-8")
    assert not re.search(r"^\s*cache_cluster_password\s*=", text, re.M)
    assert "TF_VAR_cache_cluster_password" in text, (
        "point the reader at the environment instead"
    )


def test_the_access_point_example_explains_the_immutable_setting() -> None:
    """NetworkOrigin cannot be changed later, so the example has to say so where it is chosen."""
    text = (AWS / "access-point.example.json").read_text(encoding="utf-8")
    assert "NetworkOrigin" in text
    assert "Immutable" in text or "immutable" in text
