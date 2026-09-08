"""The contract this repository publishes, and its reader.

This contract is consumed by another project's gate, so a wrong row here surfaces there as a break
they appear to have caused. That asymmetry is why the parser fails rows rather than skipping them, and
why the published file is asserted directly: no other repository can tell us it is malformed without
first failing because of it.

The two limits the owner of these strings measured are recorded in the contract's own header rather
than here, because they are properties of probing and not of this reader.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location(
        "check_outgoing_probes", ROOT / "tools" / "check_outgoing_probes.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load()
REPO = "FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns"


def row(path: str, role: str, text: str, repo: str = REPO) -> str:
    return f"{repo}\t{path}\t{role}\t{text}"


# --- the published contract itself ---------------------------------------------------------------


def test_the_published_contract_parses_without_a_problem() -> None:
    probes, problems = mod.parse_contract(
        (ROOT / mod.CONTRACT).read_text(encoding="utf-8")
    )
    assert not problems, problems
    assert probes, "the contract holds no probe"


def test_every_registered_repository_has_local_directory_names() -> None:
    """Without them a row can never be checked locally, and the skip would look like a pass."""
    probes, _ = mod.parse_contract((ROOT / mod.CONTRACT).read_text(encoding="utf-8"))
    for probe in probes:
        assert probe.repo in mod.LOCAL_NAMES


def test_the_contract_is_reachable_at_the_path_a_sibling_would_fetch() -> None:
    """The path is the interface. Moving it silently returns the other side to skipping."""
    assert (ROOT / mod.CONTRACT).is_file()
    assert mod.CONTRACT.as_posix() == "docs/agent/cross-repo-probe-contract.txt"


# --- rows that must not be skipped quietly -------------------------------------------------------


def test_the_wrong_field_count_is_a_problem_not_a_skip() -> None:
    probes, problems = mod.parse_contract(f"{REPO}\tdocs/a.md\tretraction")
    assert not probes and len(problems) == 1


def test_an_unknown_role_is_a_problem_not_a_skip() -> None:
    probes, problems = mod.parse_contract(row("docs/a.md", "advisory", "x"))
    assert not probes and len(problems) == 1
    assert "advisory" in problems[0]


def test_an_unrecorded_repository_is_a_problem_not_a_skip() -> None:
    """A row naming a repository with no local names could never be checked."""
    probes, problems = mod.parse_contract(
        row("docs/a.md", "retraction", "x", repo="Some-Unrecorded-Repo")
    )
    assert not probes and len(problems) == 1
    assert "LOCAL_NAMES" in problems[0]


def test_an_empty_probe_string_is_a_problem() -> None:
    probes, problems = mod.parse_contract(row("docs/a.md", "retraction", ""))
    assert not probes and len(problems) == 1


# --- the format decisions, same as the incoming side ---------------------------------------------


def test_the_probe_string_is_last_so_it_may_contain_a_tab() -> None:
    probes, problems = mod.parse_contract(row("docs/a.md", "retraction", "left\tright"))
    assert not problems
    assert probes[0].text == "left\tright"


def test_a_hash_inside_a_probe_is_not_a_comment() -> None:
    probes, problems = mod.parse_contract(row("docs/a.md", "retraction", "a # b"))
    assert not problems
    assert probes[0].text == "a # b"


def test_whitespace_in_the_probe_is_not_trimmed() -> None:
    probes, _ = mod.parse_contract(row("docs/a.md", "retraction", " padded "))
    assert probes[0].text == " padded "


# --- both failure modes, against a checkout on disk ---------------------------------------------


def sibling(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str | None) -> Path:
    """A stand-in checkout, reached the way a real one is: a sibling directory of the repository.

    The contract is written into the fake repository at its real path rather than injected by patching
    `Path.read_text`. Patching it globally was the first attempt and it made two tests pass wrongly:
    the sibling file read returned the contract too, and a contract row **contains** the probe string,
    so a probe resolved against the registration of itself. A harness that feeds the same bytes to both
    sides cannot tell the two reads apart.
    """
    root = tmp_path / "repo"
    (root / mod.CONTRACT.parent).mkdir(parents=True)
    checkout = tmp_path / mod.LOCAL_NAMES[REPO][0]
    checkout.mkdir()
    if body is not None:
        target = checkout / "docs" / "errata.md"
        target.parent.mkdir(parents=True)
        target.write_text(body, encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", root)
    return root


def run(
    monkeypatch: pytest.MonkeyPatch, contract: str, root: Path | None = None
) -> int:
    base = root if root is not None else mod.ROOT
    (base / mod.CONTRACT).write_text(contract + "\n", encoding="utf-8")
    monkeypatch.setattr(mod.sys, "argv", ["check_outgoing_probes.py"])
    return mod.main()


def test_a_present_string_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sibling(tmp_path, monkeypatch, "前後に文があって 発火しない という主張")
    assert run(monkeypatch, row("docs/errata.md", "retraction", "発火しない")) == 0
    assert "1 probe(s) resolve" in capsys.readouterr().out


def test_a_missing_string_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sibling(tmp_path, monkeypatch, "reworded beyond recognition")
    assert run(monkeypatch, row("docs/errata.md", "retraction", "発火しない")) == 1
    assert "no longer resolve" in capsys.readouterr().err


def test_a_missing_file_fails_and_says_what_to_do(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sibling(tmp_path, monkeypatch, None)
    assert run(monkeypatch, row("docs/errata.md", "retraction", "発火しない")) == 1
    assert "re-point it or lower the claim's stage" in capsys.readouterr().err


def test_a_reread_role_warns_instead_of_failing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sibling(tmp_path, monkeypatch, "the range moved")
    assert run(monkeypatch, row("docs/errata.md", "reread", "5〜9 GB")) == 0
    assert "reread:" in capsys.readouterr().out


def test_an_absent_checkout_is_named_rather_than_folded_into_the_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """A skip that reads like a pass is how a contract gets published unchecked."""
    root = tmp_path / "repo"
    (root / mod.CONTRACT.parent).mkdir(parents=True)
    monkeypatch.setattr(mod, "ROOT", root)
    assert (
        run(monkeypatch, row("docs/errata.md", "retraction", "発火しない"), root) == 0
    )
    out = capsys.readouterr().out
    assert "SKIPPED" in out and REPO in out
    assert "probe(s) resolve" not in out


def test_an_empty_contract_is_not_a_pass(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = sibling(tmp_path, monkeypatch, None)
    assert run(monkeypatch, "# only a comment", root) == 1
    assert "holds no probe" in capsys.readouterr().err
