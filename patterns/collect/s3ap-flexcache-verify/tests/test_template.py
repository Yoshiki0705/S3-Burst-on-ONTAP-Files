"""Invariants of the verification pattern's template that cfn-lint has no opinion about.

Two properties of this template decide how much damage a wrong parameter does, and neither is
visible to a linter:

* Every security group rule this stack creates takes its source CIDR from a parameter. A value of
  `0.0.0.0/0` opens NFS, SMB and the ONTAP intercluster ports to the internet, and the stack creates
  successfully -- the mistake surfaces as a working deployment. The on-premises Terraform already
  rejects that value for its export rule; this is the CloudFormation half of the same guard.
* The test host's role reaches S3 and Secrets Manager. Both are bounded by parameters, and the S3
  one defaults to `*` because the access point does not exist until after the stack. That default is
  a documented, temporary state, so what is asserted is that it is bounded once set -- not that it
  starts narrow.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATE = Path(__file__).resolve().parent.parent / "template.yaml"
CIDR_PARAMETERS = ("OriginVpcCidr", "CacheVpcCidr")


def template() -> str:
    return TEMPLATE.read_text(encoding="utf-8")


def parameter_block(name: str) -> str:
    """The YAML block for one parameter, up to the next parameter at the same indentation."""
    match = re.search(
        rf"^  {name}:\n(.*?)(?=^  [A-Za-z]|\Z)", template(), re.MULTILINE | re.DOTALL
    )
    assert match, f"parameter {name} not found; this test is checking nothing"
    return match.group(1)


def allowed_pattern(name: str) -> str:
    match = re.search(r'AllowedPattern:\s*"([^"]+)"', parameter_block(name))
    assert match, f"{name} has no AllowedPattern"
    # As written in YAML the backslashes are doubled; unescape to get the regex itself.
    return match.group(1).replace("\\\\", "\\")


@pytest.mark.parametrize("name", CIDR_PARAMETERS)
def test_a_cidr_parameter_is_constrained(name: str) -> None:
    assert "AllowedPattern" in parameter_block(name), (
        f"{name} becomes the source of every security group rule in this stack, "
        "so it needs an AllowedPattern"
    )


@pytest.mark.parametrize("name", CIDR_PARAMETERS)
@pytest.mark.parametrize(
    "value",
    [
        "0.0.0.0/0",
        "10.0.0.0/0",
        "1.2.3.4/16",
        "8.8.8.8/32",
        "10.0.0.0/33",
        "not-a-cidr",
    ],
)
def test_a_public_or_malformed_cidr_is_rejected(name: str, value: str) -> None:
    assert not re.match(allowed_pattern(name), value), (
        f"{name} accepts {value!r}, which would open the security group rules wider than the peer VPC"
    )


@pytest.mark.parametrize("name", CIDR_PARAMETERS)
@pytest.mark.parametrize("value", ["10.0.0.0/16", "172.31.0.0/16", "192.168.1.0/24"])
def test_a_private_cidr_is_accepted(name: str, value: str) -> None:
    """The constraint has to admit the values the deployment guide tells people to use."""
    assert re.match(allowed_pattern(name), value), f"{name} rejects {value!r}"


def test_the_secret_read_is_bounded_to_one_secret() -> None:
    body = template()
    assert "SmbCredentialSecretName" in body, (
        "the secret name must come from a parameter"
    )
    assert ":secret:*" not in body, (
        "secret:* matches every secret in the account; scope it to the one this measurement reads"
    )


def test_the_s3_statements_reference_the_access_point_parameter() -> None:
    """`Resource: "*"` may only appear via the documented default, never written into a statement."""
    body = template()
    assert "S3AccessPointArn" in body
    assert not re.search(r"^\s+Resource:\s*\"\*\"\s*$", body, re.MULTILINE), (
        'a literal Resource: "*" is in the policy; bound it to the access point ARN parameter'
    )


def test_head_bucket_is_not_granted_as_an_iam_action() -> None:
    """`s3:HeadBucket` does not exist as an IAM action: HeadBucket is authorised by s3:ListBucket.

    Matched as a list entry rather than as a substring, so that the comment in the template
    explaining this does not satisfy its own test.
    """
    granted = re.findall(r"^\s*-\s*(s3:[A-Za-z*]+)\s*$", template(), re.MULTILINE)
    assert "s3:HeadBucket" not in granted, f"granted S3 actions: {granted}"
