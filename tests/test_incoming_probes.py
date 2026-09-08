"""The probe contract parser, tested without the sibling repository.

The contract does not exist yet, so the checker skips everywhere and its parser would otherwise ship
unexercised. These tests are what makes the skeleton mean something before the sibling publishes:
they pin the format decisions taken in S3-Burst-on-ONTAP-Files#121, so that a later change to the
format shows up here rather than as a false break reported to the other repository.

The two most likely bugs in the whole arrangement are a parser that normalises and a generator that
escapes. This file covers the first.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location(
        "check_incoming_probes", ROOT / "tools" / "check_incoming_probes.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load()
ME = mod.THIS_REPO


def row(path: str, role: str, text: str, repo: str = ME) -> str:
    return f"{repo}\t{path}\t{role}\t{text}"


# --- format decisions -------------------------------------------------------------------------


def test_four_fields_in_order() -> None:
    probes, problems = mod.parse_contract(row("docs/a.md", "retraction", "45% 違った"))
    assert not problems
    assert probes == [mod.Probe(path="docs/a.md", role="retraction", text="45% 違った")]


def test_rows_for_other_repositories_are_ignored() -> None:
    body = "\n".join(
        [
            row("docs/a.md", "retraction", "mine"),
            row("docs/b.md", "retraction", "theirs", repo="Some-Other-Repo"),
        ]
    )
    probes, problems = mod.parse_contract(body)
    assert not problems
    assert [p.text for p in probes] == ["mine"]


def test_the_probe_string_is_last_so_it_may_contain_a_tab() -> None:
    """maxsplit=3, not a plain split. A probe can hold anything but a field separator."""
    probes, problems = mod.parse_contract(row("docs/a.md", "reread", "left\tright"))
    assert not problems
    assert probes[0].text == "left\tright"


def test_a_hash_inside_a_probe_is_not_a_comment() -> None:
    probes, problems = mod.parse_contract(
        row("docs/a.md", "retraction", "c$ は # 管理共有")
    )
    assert not problems
    assert probes[0].text == "c$ は # 管理共有"


def test_a_hash_at_the_start_of_a_line_is_a_comment() -> None:
    body = "# role: retraction fails, reread warns\n" + row(
        "docs/a.md", "retraction", "x"
    )
    probes, problems = mod.parse_contract(body)
    assert not problems
    assert len(probes) == 1


def test_whitespace_in_the_probe_is_not_trimmed() -> None:
    """Leading or trailing space could be part of the substring the sibling chose."""
    probes, _ = mod.parse_contract(row("docs/a.md", "retraction", " 倍率 2.97 は "))
    assert probes[0].text == " 倍率 2.97 は "


def test_emphasis_and_backticks_survive_verbatim() -> None:
    """No normalisation. Stripping `**` would match text that no longer holds the claim."""
    literal = "倍率 2.97 は **1,500 ÷ 500 = 3.0** に一致しており"
    probes, _ = mod.parse_contract(row("docs/a.md", "retraction", literal))
    assert probes[0].text == literal

    backticked = "EFS は `nconnect` にも非対応"
    probes, _ = mod.parse_contract(row("docs/b.md", "retraction", backticked))
    assert probes[0].text == backticked


# --- rows that must not be skipped quietly ----------------------------------------------------


def test_the_wrong_field_count_is_a_problem_not_a_skip() -> None:
    probes, problems = mod.parse_contract(f"{ME}\tdocs/a.md\tretraction")
    assert not probes
    assert len(problems) == 1


def test_an_unknown_role_is_a_problem_not_a_skip() -> None:
    """The sibling's gate rejects a third value, so one arriving here is a change or a typo."""
    probes, problems = mod.parse_contract(row("docs/a.md", "advisory", "x"))
    assert not probes
    assert len(problems) == 1
    assert "advisory" in problems[0]


def test_an_empty_probe_string_is_a_problem() -> None:
    probes, problems = mod.parse_contract(row("docs/a.md", "retraction", ""))
    assert not probes
    assert len(problems) == 1


# --- the two roles behave differently ---------------------------------------------------------


def target(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, body: str) -> str:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    (tmp_path / "docs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "docs" / "a.md").write_text(body, encoding="utf-8")
    return "docs/a.md"


def test_a_present_probe_neither_fails_nor_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = target(tmp_path, monkeypatch, "前後に文があって 45% 違った という主張")
    failures, warnings = mod.check(
        [mod.Probe(path=path, role="retraction", text="45% 違った")]
    )
    assert not failures and not warnings


def test_a_missing_retraction_probe_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = target(tmp_path, monkeypatch, "reworded beyond recognition")
    failures, warnings = mod.check(
        [mod.Probe(path=path, role="retraction", text="45% 違った")]
    )
    assert len(failures) == 1 and not warnings


def test_a_missing_reread_probe_only_warns(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A range probe moves when a measurement is added. That is not a retraction."""
    path = target(tmp_path, monkeypatch, "単一接続の 4 行は 500〜618 MB/s に収まる")
    failures, warnings = mod.check(
        [mod.Probe(path=path, role="reread", text="500〜592 MB/s に収まる")]
    )
    assert not failures and len(warnings) == 1
    assert "retraction" in warnings[0]


def test_a_moved_file_fails_even_when_the_text_survives(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The path is part of the registration, so a rename breaks the citation over there."""
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    failures, _ = mod.check(
        [mod.Probe(path="docs/renamed.md", role="retraction", text="45% 違った")]
    )
    assert len(failures) == 1
    assert "not found" in failures[0]


# --- the switch that stops a skip standing in for a pass --------------------------------------


def test_a_404_means_removal_now_that_the_contract_is_published(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The switch changes what a 404 means, so it is asserted in whichever position it is in.

    While CONTRACT_PUBLISHED was False a 404 read as "not published yet" and skipped. Now that the
    sibling publishes on its default branch, the same response means the registration this repository
    is checked against was removed or renamed -- and a skip would report that as a clean run forever.
    """
    import urllib.error

    def refuse(*_args, **_kwargs):
        raise urllib.error.HTTPError(mod.RAW_CONTRACT, 404, "Not Found", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", refuse)

    if mod.CONTRACT_PUBLISHED:
        with pytest.raises(SystemExit) as raised:
            mod.fetch_contract()
        assert "removal or a rename" in str(raised.value)
    else:
        probes, problems = mod.fetch_contract()
        assert probes is None and not problems


def test_a_non_404_failure_is_never_read_as_absence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 500 or a 403 is not "not published yet" in either position of the switch."""
    import urllib.error

    def refuse(*_args, **_kwargs):
        raise urllib.error.HTTPError(mod.RAW_CONTRACT, 500, "Server Error", {}, None)

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    with pytest.raises(SystemExit):
        mod.fetch_contract()


def test_zero_rows_for_this_repository_is_not_a_pass() -> None:
    """A parsed contract with nothing for us means a changed repo name, not an empty registration."""
    assert mod.EXPECT_AT_LEAST_ONE_ROW is True
    probes, problems = mod.parse_contract(
        row("docs/a.md", "retraction", "x", repo="Some-Other-Repo")
    )
    assert not probes and not problems
