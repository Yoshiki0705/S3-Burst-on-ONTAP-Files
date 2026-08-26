"""Invariants of this pattern's templates that cfn-lint has no opinion about.

Four of them, each because getting it wrong produces a stack that deploys and then behaves
differently from what the template appears to say.

* The ONTAP identity takes a user NAME. Numeric UID / GID belong to the FSx for OpenZFS shape of
  `AWS::FSx::S3AccessPointAttachment` and have no field in the ONTAP one, so a `UnixUid` parameter
  would be a value a reader can set and nothing can consume. The registry schema is the authority
  here, and it is asserted rather than trusted to memory.

* No wildcard principal, and no `s3:*` in an Allow. An access point policy with `Principal: "*"`
  deploys successfully; the mistake surfaces as working access from somewhere unintended.

* Object-level statements carry the `/object/` ARN segment and bucket-level ones do not. A
  bucket-style ARN returns AccessDenied against FSx for ONTAP on a stack that reported CREATE_COMPLETE
  -- the symptom is indistinguishable from a file-permission problem.

* `ListBucket` is confined by an `s3:prefix` condition wherever the object statement is confined by a
  prefix. Enforcing the prefix on objects while leaving the listing open makes every key name in the
  volume readable, which for most of the data this architecture collects is the disclosure that
  matters.

The examples are checked alongside the deployable template, because an example is what gets copied.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

PATTERN = Path(__file__).resolve().parent.parent
TEMPLATE = PATTERN / "template.yaml"
EXAMPLES = sorted((PATTERN / "examples").glob("*.yaml"))
ALL_TEMPLATES = [TEMPLATE, *EXAMPLES]


def test_the_examples_are_actually_present():
    """A glob that matches nothing would make every parametrised test below vacuous."""
    assert EXAMPLES, "no examples found; the tests over them prove nothing"
    names = {path.name for path in EXAMPLES}
    assert {"unix-user.yaml", "windows-user.yaml", "multi-access-points.yaml"} <= names


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


class _Loader(yaml.SafeLoader):
    """CloudFormation short forms are YAML tags SafeLoader rejects.

    Resolved to a plain marker rather than reconstructed faithfully: these tests read structure and
    string content, and an `!If` that becomes the string "<!If>" still lets the surrounding shape be
    walked. Reconstructing the intrinsic functions would mean reimplementing them.
    """


def _tag(loader, suffix, node):  # noqa: ANN001, ANN202 - yaml constructor signature
    if isinstance(node, yaml.ScalarNode):
        return {f"Fn::{suffix}": loader.construct_scalar(node)}
    if isinstance(node, yaml.SequenceNode):
        return {f"Fn::{suffix}": loader.construct_sequence(node, deep=True)}
    return {f"Fn::{suffix}": loader.construct_mapping(node, deep=True)}


_Loader.add_multi_constructor("!", _tag)


def parsed(path: Path) -> dict:
    return yaml.load(text(path), Loader=_Loader)


def walk(node):
    """Every mapping in the document, depth first."""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from walk(value)
    elif isinstance(node, list):
        for value in node:
            yield from walk(value)


def attachments(path: Path) -> list[dict]:
    resources = parsed(path).get("Resources", {})
    found = [
        body.get("Properties", {})
        for body in resources.values()
        if body.get("Type") == "AWS::FSx::S3AccessPointAttachment"
    ]
    assert found, f"{path.name} declares no attachment; its assertions would pass on nothing"
    return found


# --- the identity shape -------------------------------------------------------------------------


@pytest.mark.parametrize("path", ALL_TEMPLATES, ids=lambda p: p.name)
def test_ontap_identity_is_name_based(path: Path):
    """ONTAP identity carries a user name. A numeric UID/GID here would be unusable."""
    for properties in attachments(path):
        identity = properties["OntapConfiguration"]["FileSystemIdentity"]
        users = [key for key in ("UnixUser", "WindowsUser") if key in identity]
        assert users, f"{path.name}: identity declares neither UnixUser nor WindowsUser"
        for key in users:
            user = identity[key]
            if isinstance(user, dict) and "Fn::If" in user:
                continue  # conditional branch; the resource-level conditions cover it
            assert set(user) == {"Name"}, f"{path.name}: {key} takes only Name, got {sorted(user)}"


@pytest.mark.parametrize("path", ALL_TEMPLATES, ids=lambda p: p.name)
def test_no_uid_or_gid_parameters(path: Path):
    """A parameter a reader can set and the resource cannot consume is worse than its absence."""
    for name in parsed(path).get("Parameters", {}):
        assert not re.search(r"(?:Uid|Gid)$", name), (
            f"{path.name}: parameter {name} looks numeric-identity shaped. ONTAP takes a user name; "
            "Uid / Gid / SecondaryGids exist only in the FSx for OpenZFS configuration"
        )


def test_the_registry_schema_still_agrees():
    """The claim above is about a live resource type, so pin what it rests on.

    Not a network call: the assertion is that this pattern's own statement of the schema, in the
    README, names the same fields the template uses. If AWS adds a numeric identity to the ONTAP
    configuration later, this test does not fail -- but the README sentence it guards is the thing a
    reader trusts, and it cannot drift away from the template silently.
    """
    readme = text(PATTERN / "README.md")
    assert "UnixUser" in readme and "WindowsUser" in readme
    assert "PosixUser" in readme, (
        "the README should name the OpenZFS field that does take Uid/Gid, so a reader who arrived "
        "looking for it learns where it lives instead of concluding it was forgotten"
    )


# --- the policy ---------------------------------------------------------------------------------


def policy_blocks(path: Path) -> list[list[dict]]:
    """Each access point's own policy, as a list of statements.

    Grouped per policy rather than flattened per file, because the properties below are properties
    of one access point. The first version flattened them and reported the multi-tenant example's
    deliberate cross-prefix listing as a fault in the prefix-bound access point beside it.
    """
    blocks: list[list[dict]] = []
    for properties in attachments(path):
        block = (properties.get("S3AccessPoint") or {}).get("Policy")
        if not isinstance(block, dict):
            continue
        candidates = [block]
        if "Fn::If" in block:
            candidates = [item for item in block["Fn::If"] if isinstance(item, dict)]
        for candidate in candidates:
            statements = [s for s in (candidate.get("Statement") or []) if isinstance(s, dict)]
            if statements:
                blocks.append(statements)
    return blocks


WITH_POLICY = [path for path in ALL_TEMPLATES if policy_blocks(path)]


def test_at_least_one_template_carries_a_policy():
    """Discovered rather than listed: an empty list would make the policy tests vacuous.

    `examples/windows-user.yaml` and `examples/unix-user.yaml` deliberately carry no policy -- they
    are minimal references to the resource shape -- so the set is discovered from the files instead
    of maintained by hand, which is what made the first version of these tests fail on them.
    """
    assert WITH_POLICY, "no template declares an access point policy; the policy tests prove nothing"
    assert TEMPLATE in WITH_POLICY, "the deployable template must carry a policy"


@pytest.mark.parametrize("path", WITH_POLICY, ids=lambda p: p.name)
def test_no_wildcard_principal_on_an_allow(path: Path):
    """`Principal: "*"` is acceptable on a Deny and never on an Allow."""
    for statements in policy_blocks(path):
        for statement in statements:
            if statement.get("Effect") != "Allow":
                continue
            principal = statement.get("Principal")
            assert principal not in ("*", {"AWS": "*"}), (
                f"{path.name}: statement {statement.get('Sid')} allows a wildcard principal"
            )
            if isinstance(principal, dict):
                aws = principal.get("AWS")
                values = aws if isinstance(aws, list) else [aws]
                assert "*" not in values, (
                    f"{path.name}: statement {statement.get('Sid')} allows AWS: *"
                )


@pytest.mark.parametrize("path", WITH_POLICY, ids=lambda p: p.name)
def test_no_blanket_s3_action_on_an_allow(path: Path):
    for statements in policy_blocks(path):
        for statement in statements:
            if statement.get("Effect") != "Allow":
                continue
            actions = statement.get("Action")
            actions = actions if isinstance(actions, list) else [actions]
            assert "s3:*" not in actions, (
                f"{path.name}: statement {statement.get('Sid')} allows s3:*"
            )


OBJECT_ACTIONS = {"s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:GetObjectTagging"}
BUCKET_ACTIONS = {"s3:ListBucket"}


def arn_strings(value) -> list[str]:
    """Every literal ARN-ish string in a Resource value, through Sub and If."""
    out: list[str] = []
    if isinstance(value, str):
        out.append(value)
    elif isinstance(value, list):
        for item in value:
            out.extend(arn_strings(item))
    elif isinstance(value, dict):
        for item in value.values():
            out.extend(arn_strings(item))
    return [item for item in out if isinstance(item, str) and ":accesspoint/" in item]


@pytest.mark.parametrize("path", WITH_POLICY, ids=lambda p: p.name)
def test_object_actions_use_the_object_arn_segment(path: Path):
    """Object-level actions need `/object/`; bucket-level ones must not have it."""
    for statements in policy_blocks(path):
        for statement in statements:
            actions = statement.get("Action")
            actions = set(actions if isinstance(actions, list) else [actions])
            arns = arn_strings(statement.get("Resource"))
            assert arns, f"{path.name}: statement {statement.get('Sid')} has no access point ARN"
            if actions & OBJECT_ACTIONS and not actions & BUCKET_ACTIONS:
                assert all("/object/" in arn for arn in arns), (
                    f"{path.name}: statement {statement.get('Sid')} is object-level but an ARN has "
                    "no /object/ segment; this returns AccessDenied on a stack that deployed"
                )
            if actions & BUCKET_ACTIONS and not actions & OBJECT_ACTIONS:
                assert all("/object/" not in arn for arn in arns), (
                    f"{path.name}: statement {statement.get('Sid')} is bucket-level but an ARN "
                    "carries /object/"
                )


def prefix_bound(statement: dict) -> bool:
    """Whether an object statement is confined to something narrower than the whole volume."""
    for arn in arn_strings(statement.get("Resource")):
        if "/object/" not in arn:
            continue
        tail = arn.split("/object/", 1)[1]
        if tail not in ("*", ""):
            return True
    return False


@pytest.mark.parametrize("path", WITH_POLICY, ids=lambda p: p.name)
def test_a_prefix_bound_policy_also_bounds_the_listing(path: Path):
    """Within one access point, prefix-bound objects require a prefix-bound listing.

    Scoped to a single policy. An access point that deliberately lists across prefixes -- the
    read-only analytics one in the multi-tenant example -- has no prefix-bound object statement, so
    it is not caught here, which is the intended reading rather than an exemption.
    """
    for statements in policy_blocks(path):
        allows = [s for s in statements if s.get("Effect") == "Allow"]
        if not any(prefix_bound(s) for s in allows):
            continue
        listings = [
            s
            for s in allows
            if "s3:ListBucket" in (s.get("Action") or [])
            or s.get("Action") == "s3:ListBucket"
        ]
        assert listings, (
            f"{path.name}: object access is prefix-bound but nothing lists; if listing is not "
            "granted, say so, because a consumer that cannot list usually cannot work"
        )
        for statement in listings:
            condition = json.dumps(statement.get("Condition") or {})
            assert "s3:prefix" in condition, (
                f"{path.name}: statement {statement.get('Sid')} lists without an s3:prefix "
                "condition while object access is prefix-bound; the listing is then the disclosure"
            )


# --- the create-only reality --------------------------------------------------------------------


def test_template_states_that_changes_replace():
    """The resource has no update handler, and the README has to say so where it is read.

    Asserted against the template's own comments rather than the README alone: the comment is what a
    reader editing the policy sees, and that is the edit that triggers the replacement.
    """
    body = text(TEMPLATE)
    assert "create-only" in body, "the template does not mention that properties are create-only"
    assert "delete_then_create" in body or "delete then create" in body.lower()


@pytest.mark.parametrize("path", ALL_TEMPLATES, ids=lambda p: p.name)
def test_no_tags_on_the_attachment(path: Path):
    """`tagging.taggable` is false on this resource type; Tags would be rejected."""
    for properties in attachments(path):
        assert "Tags" not in properties, (
            f"{path.name}: the attachment is not taggable, so Tags cannot be set on it"
        )
