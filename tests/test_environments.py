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
S3FILES = ROOT / "environments" / "s3files-compare"


def aws_template() -> str:
    return (AWS / "template.yaml").read_text(encoding="utf-8")


def s3files_template() -> str:
    return (S3FILES / "template.yaml").read_text(encoding="utf-8")


def onprem_files() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in ONPREM.glob("*.tf")}


def pinned_provider_version() -> str:
    """The provider's pinned version, read from inside required_providers.

    Scoped to the provider block on purpose: a bare search for `version = "..."` finds
    `required_version` first, which is a Terraform CLI constraint and legitimately a range.
    """
    versions = onprem_files()["versions.tf"]
    block = re.search(r"required_providers\s*\{(.*?)\n  \}", versions, re.DOTALL)
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
        "environments/s3files-compare/template.yaml",
        "environments/s3files-compare/params.example.json",
        "environments/s3files-compare/mount-s3files.sh",
        "environments/s3files-compare/teardown.sh",
        "docs/ja/deployment/aws-cloudformation.md",
        "docs/ja/deployment/onprem-terraform.md",
        "docs/ja/deployment/aws-s3files-compare.md",
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


@pytest.mark.parametrize("token", IMMUTABILITY)
def test_the_comparison_template_enables_no_immutability_feature(token: str) -> None:
    """The comparison environment holds an S3 bucket, so Object Lock is reachable from here.

    The guard above covered only the two original directories. A bucket whose objects are locked
    cannot be emptied, and a bucket that cannot be emptied cannot be deleted by CloudFormation, so
    the same class of mistake lands on the same outcome by a different route.
    """
    assert token not in s3files_template(), token


def test_the_comparison_bucket_is_versioned_and_encrypted() -> None:
    """Both are prerequisites of S3 Files, not preferences: without them the file system is refused.

    Versioning is asserted here rather than left to the deploy attempt because its absence fails at
    file system creation, long after the bucket exists.
    """
    template = s3files_template()
    assert "VersioningConfiguration" in template
    assert "Status: Enabled" in template
    assert "SSEAlgorithm: AES256" in template


def test_the_comparison_environment_reuses_rather_than_rebuilds_the_host() -> None:
    """A second host would compare two clocks, which is the one thing the measurement cannot do."""
    template = s3files_template()
    assert "AWS::EC2::Instance" not in template
    assert "MeasurementHostSecurityGroupId" in template


def test_a_verification_environment_can_be_deleted() -> None:
    """DeletionPolicy: Retain on a file system would leave the bill running after a delete-stack."""
    assert "DeletionPolicy: Retain" not in aws_template()
    assert "DeletionPolicy: Retain" not in s3files_template()
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
    block = re.search(r'variable "allowed_clients" \{(.*?)\n\}', variables, re.DOTALL)
    assert block, "allowed_clients variable not found"
    # Match an assignment, not the word: the description explains *why* there is no default.
    assert not re.search(r"^\s*default\s*=", block.group(1), re.MULTILINE), (
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
        re.DOTALL,
    )
    assert match, "OriginVolumeSecurityStyle AllowedValues not found"
    assert "MIXED" not in match.group(1)


# --- example files carry placeholders, not real values --------------------------------------------


def test_the_parameter_example_uses_placeholders() -> None:
    params = json.loads((AWS / "params.example.json").read_text(encoding="utf-8"))
    values = {p["ParameterKey"]: p["ParameterValue"] for p in params}
    assert values["VpcId"] == "vpc-0123456789abcdef0"
    assert values["SubnetId"] == "subnet-0123456789abcdef0"


def test_the_comparison_parameter_example_uses_placeholders() -> None:
    params = json.loads((S3FILES / "params.example.json").read_text(encoding="utf-8"))
    values = {p["ParameterKey"]: p["ParameterValue"] for p in params}
    assert values["VpcId"] == "vpc-0123456789abcdef0"
    assert values["SubnetId"] == "subnet-0123456789abcdef0"
    # Bytes, not KiB. 128 here instead of 131072 would import almost nothing while reading as the
    # documented default, and the resulting figures would look like a slow file system.
    assert values["SmallFileImportThresholdBytes"] == "131072"


def test_the_tfvars_example_holds_no_password() -> None:
    """Terraform writes variable values into state in clear text, sensitive or not."""
    text = (ONPREM / "terraform.tfvars.example").read_text(encoding="utf-8")
    assert not re.search(r"^\s*cache_cluster_password\s*=", text, re.MULTILINE)
    assert "TF_VAR_cache_cluster_password" in text, (
        "point the reader at the environment instead"
    )


def test_the_access_point_example_explains_the_immutable_setting() -> None:
    """NetworkOrigin cannot be changed later, so the example has to say so where it is chosen."""
    text = (AWS / "access-point.example.json").read_text(encoding="utf-8")
    assert "NetworkOrigin" in text
    assert "Immutable" in text or "immutable" in text


def _declared_parameters(template: str) -> set[str]:
    """Parameter names from a template's Parameters block, stopping at the next top-level key."""
    body = template.split("Parameters:", 1)[1]
    for terminator in ("\nConditions:", "\nResources:", "\nMappings:"):
        body = body.split(terminator, 1)[0]
    return set(re.findall(r"^  ([A-Za-z0-9]+):$", body, re.MULTILINE))


def _example_parameters(name: str) -> dict[str, str]:
    entries = json.loads((AWS / name).read_text(encoding="utf-8"))
    return {
        e["ParameterKey"]: e["ParameterValue"] for e in entries if "ParameterKey" in e
    }


EXAMPLES = ["params.example.json", "params.throughput.example.json"]


@pytest.mark.parametrize("example", EXAMPLES)
def test_every_template_parameter_appears_in_the_example(example: str) -> None:
    """An example that omits a parameter hides it, and a hidden parameter keeps its default.

    This is not hypothetical. Three parameters were added to the template for the throughput
    measurement (AssociatePublicIp, HostS3DataAccess, HostS3ResourceArns) and the example was not
    updated in the same change, so a reader copying it would have deployed a host with no route to
    Session Manager and no way to see why.
    """
    missing = _declared_parameters(aws_template()) - set(_example_parameters(example))
    assert not missing, f"{example} omits {sorted(missing)}"


@pytest.mark.parametrize("example", EXAMPLES)
def test_the_example_invents_no_parameter(example: str) -> None:
    """A parameter the template does not declare fails the create with an unhelpful message."""
    unknown = set(_example_parameters(example)) - _declared_parameters(aws_template())
    assert not unknown, (
        f"{example} names {sorted(unknown)}, which the template does not declare"
    )


def test_the_throughput_example_names_the_instance_that_makes_it_valid() -> None:
    """c5n.9xlarge is not a preference here; it is what lets the client be ruled out as the limit.

    Every smaller c5n is quoted as "Up to 25 Gbps", a burst ceiling. If the example drifted to one
    of those, a reader would reproduce the procedure and measure their own network credits instead.
    """
    entries = _example_parameters("params.throughput.example.json")
    assert entries["HostInstanceType"] == "c5n.9xlarge"
    # A 30-second write point at the 2048 MBps step lands about 61 GB, so the volume must hold one.
    assert int(entries["OriginVolumeSizeMB"]) >= 102400


def test_the_ontap_password_excludes_all_punctuation() -> None:
    """A generated password with punctuation did not become the file system's actual password.

    The failure was silent in every place that would normally catch it: the stack reached
    CREATE_COMPLETE, the file system reached AVAILABLE, and the secret held a 32-character password.
    Only the ONTAP REST API disagreed, with HTTP 401 and `"User is not authorized."` -- a message
    about permissions, for what was actually an authentication mismatch.

    It matters more here than it would elsewhere because FlexCache, cluster peering and SVM peering
    have no AWS API at all. A file system whose fsxadmin credential does not work is one on which
    the serve side of this architecture cannot be built, and no AWS-side status reflects that.
    """
    template = aws_template()
    secret = template.split("OntapAdminSecret:", 1)[1].split("\n  FileSystem:", 1)[0]
    assert "ExcludePunctuation: true" in secret, (
        "ExcludePunctuation must stay true. A partial ExcludeCharacters list let ! # < > ] ^ | } "
        "through and produced a file system whose fsxadmin password did not match its secret."
    )
    assert "RequireEachIncludedType: true" in secret, (
        "Without RequireEachIncludedType, excluding punctuation can yield a password that fails "
        "ONTAP's complexity requirement."
    )
    # A shorter password would be the wrong way to compensate for dropping the symbol set.
    length = int(re.search(r"PasswordLength:\s*(\d+)", secret).group(1))
    assert length >= 32, (
        f"PasswordLength is {length}; alphanumeric-only needs the length kept up"
    )
