"""The security group rule description gate has to fail on what EC2 actually rejects.

This gate exists because cfn-lint does not check either constraint EC2 applies to a rule
description, and both of them blocked a stack creation in this repository before the gate was
written. A gate that passes everything would have looked identical on the clean tree, so the tests
that matter here are the ones that feed it input it must reject.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

TOOL = (
    Path(__file__).resolve().parent.parent / "tools" / "check_sg_rule_descriptions.py"
)


def run(*paths: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *(str(path) for path in paths)],
        capture_output=True,
        text=True,
        check=False,
    )


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "template.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def test_em_dash_in_a_rule_description_is_rejected(tmp_path: Path) -> None:
    """The exact character that failed the create, in the exact place it failed."""
    path = write(
        tmp_path,
        "Resources:\n"
        "  Group:\n"
        "    Type: AWS::EC2::SecurityGroup\n"
        "    Properties:\n"
        "      GroupDescription: test\n"
        "      SecurityGroupEgress:\n"
        "        - IpProtocol: -1\n"
        "          CidrIp: 0.0.0.0/0\n"
        "          Description: >-\n"
        "            Outbound for SSM. No inbound rule exists at all \u2014 the host uses SSM.\n",
    )
    result = run(path)
    assert result.returncode == 1
    assert "U+2014" in result.stdout


def test_apostrophe_and_quote_are_rejected(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Resources:\n"
        "  Rule:\n"
        "    Type: AWS::EC2::SecurityGroupIngress\n"
        "    Properties:\n"
        '      Description: An apostrophe\'s rule, and a "quoted" word.\n',
    )
    result = run(path)
    assert result.returncode == 1
    assert "U+0027" in result.stdout
    assert "U+0022" in result.stdout


def test_over_255_characters_is_rejected(tmp_path: Path) -> None:
    """The second limit. Prose explaining why a rule exists runs past it easily."""
    path = write(
        tmp_path,
        "Resources:\n"
        "  Rule:\n"
        "    Type: AWS::EC2::SecurityGroupIngress\n"
        "    Properties:\n"
        f"      Description: {'a' * 300}\n",
    )
    result = run(path)
    assert result.returncode == 1
    assert "255" in result.stdout


def test_a_parameter_typed_as_a_security_group_id_is_not_a_rule(tmp_path: Path) -> None:
    """AWS::EC2::SecurityGroup::Id is a parameter type, and its description is unrestricted.

    A matcher keyed on the substring "AWS::EC2::SecurityGroup" reports this file and is wrong. The
    first version of the check did, which is the reason this test is here.
    """
    path = write(
        tmp_path,
        "Parameters:\n"
        "  HostSecurityGroupId:\n"
        "    Type: AWS::EC2::SecurityGroup::Id\n"
        "    Description: >-\n"
        "      The host's security group \u2014 used as the source of the mount target's rule.\n",
    )
    result = run(path)
    assert result.returncode == 0, result.stdout


def test_an_acceptable_rule_description_passes(tmp_path: Path) -> None:
    path = write(
        tmp_path,
        "Resources:\n"
        "  Rule:\n"
        "    Type: AWS::EC2::SecurityGroupIngress\n"
        "    Properties:\n"
        "      Description: NFS data (port 2049), from the verification host only.\n",
    )
    result = run(path)
    assert result.returncode == 0, result.stdout


def test_no_files_reports_a_failure_rather_than_a_pass(tmp_path: Path) -> None:
    """A scan that could not run must not report a clean result."""
    result = run(tmp_path / "does-not-exist.yaml")
    assert result.returncode == 1
    assert "refusing to report a pass" in result.stdout


def test_the_repository_is_clean() -> None:
    result = run()
    assert result.returncode == 0, result.stdout
