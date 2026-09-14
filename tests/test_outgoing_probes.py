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


# --- which side of the sibling gets read -------------------------------------------------------


def _published(tmp_path: Path, path: str, published: str, working: str) -> Path:
    """A throwaway sibling whose published file and working tree disagree."""
    import subprocess

    bare = tmp_path / "origin.git"
    work = tmp_path / "sibling"
    subprocess.run(["git", "init", "-q", "--bare", str(bare)], check=True)
    subprocess.run(["git", "clone", "-q", str(bare), str(work)], check=True)
    for key, value in (("user.email", "fixture@example.com"), ("user.name", "t")):
        subprocess.run(["git", "-C", str(work), "config", key, value], check=True)
    target = work / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(published, encoding="utf-8")
    subprocess.run(["git", "-C", str(work), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(work), "commit", "-q", "-m", "publish"], check=True
    )
    subprocess.run(
        ["git", "-C", str(work), "push", "-q", "origin", "HEAD:main"], check=True
    )
    subprocess.run(["git", "-C", str(work), "fetch", "-q", "origin"], check=True)
    target.write_text(working, encoding="utf-8")
    return work


def test_a_sentence_only_in_the_checkout_does_not_satisfy_a_citation(
    tmp_path: Path,
) -> None:
    """The harmful direction for this check is an unpushed *addition*.

    A citation is a promise that a reader who follows it finds the claim. If the gate reads a working
    tree, a sentence someone has written but not pushed satisfies it, and the published document a
    reader lands on does not carry the claim. So the published side is what gets read, and a body
    that exists only in the checkout must not count.
    """
    doc = "docs/ja/example.md"
    base = _published(
        tmp_path, doc, published="nothing here\n", working="cited sentence\n"
    )
    body, from_git = mod.committed(base, doc)
    assert from_git, (
        "origin/main resolves, so this checkout can answer for the published side"
    )
    assert body == "nothing here\n"
    assert "cited sentence" not in (body or "")


def test_a_checkout_without_origin_main_is_reported_as_a_fallback(
    tmp_path: Path,
) -> None:
    """No origin/main means this checkout cannot answer for the published side.

    That is a different outcome from "the file is absent there", and the two are distinguished by
    asking git for the ref rather than by matching the wording of a failure -- a message that is free
    to change between git versions.
    """
    base = tmp_path / "plain"
    (base / "docs").mkdir(parents=True)
    (base / "docs" / "a.md").write_text("x\n", encoding="utf-8")
    body, from_git = mod.committed(base, "docs/a.md")
    assert not from_git
    assert body is None


# --- a citation that protects less than it looks like it does --------------------------------------


def test_a_string_occurring_twice_in_the_cited_file_is_reported_as_weak(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Two occurrences let the sibling reword one and leave this green while the citation goes stale.

    Unlike the incoming direction, the string was chosen here, so the fix is this repository's. The
    first run of this check found one: a probe registered against a phrase that sits in two table rows
    of the cited errata, which had been passing for as long as it had existed.
    """
    sibling(tmp_path, monkeypatch, "一度目は 発火しない、二度目も 発火しない")
    assert run(monkeypatch, row("docs/errata.md", "retraction", "発火しない")) == 0
    out = capsys.readouterr().out
    assert "weak probe" in out
    assert "occurs 2 times" in out


def test_a_weak_citation_still_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The string resolves, so this is not a retraction and the exit status stays 0.

    Failing would conflate "the claim was withdrawn" with "the anchor is fragile". The first needs a
    conversation with the sibling; the second needs a longer string on this side.
    """
    sibling(tmp_path, monkeypatch, "発火しない と 発火しない")
    assert run(monkeypatch, row("docs/errata.md", "retraction", "発火しない")) == 0
    assert "no longer resolve" not in capsys.readouterr().out
