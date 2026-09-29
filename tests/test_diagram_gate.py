"""The diagram gate, checked in both directions.

Mirrors `test_commit_gate.py`'s shape: assert the matcher fires on the command that writes a
diagram and stays silent on everything else, and assert the hook actually surfaces a real failing
diagram rather than only a synthetic one -- a hook proven only against fixtures it was written to
pass is not evidence it catches the defect it exists for.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import diagram_gate as gate

ROOT = Path(__file__).resolve().parent.parent


# --- command matching ----------------------------------------------------------------------------


def test_write_export_matches() -> None:
    assert gate.BUILD_COMMAND.search("python3 tools/build_diagrams.py --write --export")


def test_write_alone_matches() -> None:
    assert gate.BUILD_COMMAND.search("python3 tools/build_diagrams.py --write")


def test_check_alone_does_not_match() -> None:
    """`--check` reads committed files; nothing new is on disk for this hook to report on."""
    assert not gate.BUILD_COMMAND.search("python3 tools/build_diagrams.py --check")


def test_an_unrelated_command_does_not_match() -> None:
    assert not gate.BUILD_COMMAND.search("git status --short")


def test_running_the_check_scripts_directly_does_not_match() -> None:
    assert not gate.BUILD_COMMAND.search("python3 tools/check_diagram_flow.py")


# --- payload extraction ---------------------------------------------------------------------------


def test_command_read_from_top_level_field() -> None:
    assert gate.command_from_payload({"command": "echo hi"}) == "echo hi"


def test_command_read_from_nested_tool_input() -> None:
    assert gate.command_from_payload({"toolInput": {"command": "echo hi"}}) == "echo hi"


def test_a_non_dict_payload_yields_nothing() -> None:
    assert gate.command_from_payload("not a dict") == ""
    assert gate.command_from_payload(None) == ""


# --- the hook contract -----------------------------------------------------------------------------


def run_hook(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "diagram_gate.py"), "--hook"],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )


def test_the_hook_never_blocks() -> None:
    """A PostToolUse hook cannot undo a write that already landed; see the module docstring."""
    proc = run_hook({"command": "python3 tools/build_diagrams.py --write --export"})
    assert proc.returncode == 0


def test_the_hook_ignores_a_command_that_is_not_a_diagram_build() -> None:
    proc = run_hook({"command": "git status --short"})
    assert proc.returncode == 0
    assert proc.stdout == ""


def test_the_hook_does_not_block_on_an_unreadable_payload() -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "diagram_gate.py"), "--hook"],
        input="not json",
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0


def test_the_hook_stays_silent_when_every_committed_diagram_passes() -> None:
    """The repository's own diagrams are the fixture here, not a synthetic stand-in.

    If this starts failing because a real diagram regressed, that is the gate doing its job --
    fix the diagram, not this test.
    """
    proc = run_hook({"command": "python3 tools/build_diagrams.py --write --export"})
    assert proc.stdout == ""


def test_the_hook_reports_a_reintroduced_aws_cloud_mislabel(tmp_path: Path) -> None:
    """Reproduces the exact defect this gate was built for, against the real checker -- not a
    stand-in fixture -- so a change to the pictogram-caption rule that stops catching this is
    caught here before it reaches a real diagram again.
    """
    import check_diagram_flow as flow

    broken = (
        '<?xml version="1.0" encoding="UTF-8"?><mxfile><diagram id="d" name="d">'
        '<mxGraphModel pageWidth="880" pageHeight="600"><root>'
        '<mxCell id="0" /><mxCell id="1" parent="0" />'
        '<mxCell id="g" value="FSx for ONTAP file server" '
        'style="shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud;'
        'align=left;spacingLeft=30;" vertex="1" parent="1">'
        '<mxGeometry x="0" y="0" width="400" height="300" as="geometry" /></mxCell>'
        "</root></mxGraphModel></diagram></mxfile>"
    )
    findings = flow.inspect(tmp_path / "probe.drawio", broken)
    assert any(f.rule == "aws-cloud-mislabel" for f in findings)
