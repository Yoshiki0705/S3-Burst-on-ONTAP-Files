"""The inward-facing counterpart to the probe contract.

A probe fires when a string disappears. The failure this file guards against is the opposite one: a
statement that a later measurement overturned, still standing. It happened twice, and both times a
sibling repository found it -- once as a scoped observation ("do not generalise this to AL2023") left
in place while a new section generalised to exactly that scope.

So the rejection tested first is "the string is present without its anchor", and the allowance second.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location(
        "check_superseded_claims", ROOT / "tools" / "check_superseded_claims.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load()


def row(path: str, text: str, anchor: str) -> str:
    return f"{path}\t{text}\t{anchor}"


# --- format -------------------------------------------------------------------------------------


def test_three_fields_in_order() -> None:
    rows, problems = mod.parse(row("docs/a.md", "一般化しない", "#section"))
    assert not problems
    assert rows == [mod.Row("docs/a.md", "一般化しない", "#section")]


def test_a_hash_at_the_start_of_a_line_is_a_comment() -> None:
    rows, problems = mod.parse("# a comment\n" + row("docs/a.md", "x", "#s"))
    assert not problems
    assert len(rows) == 1


def test_a_hash_inside_the_string_is_not_a_comment() -> None:
    rows, problems = mod.parse(row("docs/a.md", "見出し # の話", "#s"))
    assert not problems
    assert rows[0].text == "見出し # の話"


def test_the_wrong_field_count_is_a_problem_not_a_skip() -> None:
    rows, problems = mod.parse("docs/a.md\tonly two")
    assert not rows
    assert problems


def test_an_anchor_without_a_hash_is_a_problem() -> None:
    rows, problems = mod.parse(row("docs/a.md", "x", "section"))
    assert not rows
    assert problems


def test_an_empty_string_is_a_problem() -> None:
    rows, problems = mod.parse(row("docs/a.md", "   ", "#s"))
    assert not rows
    assert problems


# --- the check itself ---------------------------------------------------------------------------


def test_an_unannotated_statement_is_rejected(tmp_path: Path, monkeypatch) -> None:
    """注記が無いまま残っている旧記述が、この検査の存在理由。"""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "**「AL2023 では」と一般化しない** — 観測は 2 日間の AMI に限る\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    failures = mod.check([mod.Row("doc.md", "一般化しない", "#new-section")])
    assert len(failures) == 1
    assert "stands without naming what superseded it" in failures[0]


def test_the_anchor_within_the_window_clears_it(tmp_path: Path, monkeypatch) -> None:
    doc = tmp_path / "doc.md"
    doc.write_text(
        "**「AL2023 では」と一般化しない** — 観測は 2 日間の AMI に限る\n"
        "この限定は外れた（[確認](x.md#new-section)）\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.check([mod.Row("doc.md", "一般化しない", "#new-section")]) == []


def test_an_anchor_beyond_the_window_does_not_clear_it(
    tmp_path: Path, monkeypatch
) -> None:
    """遠くに置いた注記は、読者が旧主張を信じ終えたあとに届く。"""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "一般化しない\n" + "filler\n" * mod.WINDOW + "#new-section\n", encoding="utf-8"
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert len(mod.check([mod.Row("doc.md", "一般化しない", "#new-section")])) == 1


def test_a_string_that_is_gone_is_reported_so_the_row_can_be_removed(
    tmp_path: Path, monkeypatch
) -> None:
    """不在は成功ではない。登録簿が存在しない本文について主張し続けるのを防ぐ。"""
    doc = tmp_path / "doc.md"
    doc.write_text("この文は書き換えられた\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    failures = mod.check([mod.Row("doc.md", "一般化しない", "#new-section")])
    assert len(failures) == 1
    assert "is gone" in failures[0]


def test_a_missing_file_is_reported(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    failures = mod.check([mod.Row("absent.md", "x", "#s")])
    assert len(failures) == 1
    assert "file not found" in failures[0]


def test_every_occurrence_is_checked_not_just_the_first(
    tmp_path: Path, monkeypatch
) -> None:
    """1 か所を直して満足する形が、この族の元の失敗だった。"""
    doc = tmp_path / "doc.md"
    doc.write_text(
        "一般化しない\n[確認](x.md#s)\n\n一般化しない\n注記なし\n", encoding="utf-8"
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert len(mod.check([mod.Row("doc.md", "一般化しない", "#s")])) == 1


# --- the registry that ships --------------------------------------------------------------------


def test_the_published_registry_parses_and_holds_rows() -> None:
    rows, problems = mod.parse(mod.CONTRACT.read_text(encoding="utf-8"))
    assert not problems
    assert rows, "an empty registry is reported rather than passed"


def test_the_published_registry_is_sorted() -> None:
    rows, _ = mod.parse(mod.CONTRACT.read_text(encoding="utf-8"))
    assert rows == sorted(rows), (
        "sorted, so a diff shows what changed rather than where it moved"
    )
