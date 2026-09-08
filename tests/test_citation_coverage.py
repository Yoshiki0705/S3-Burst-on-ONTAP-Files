"""The citation-coverage reader, which has two ways to be quietly wrong.

It reports what the Hub has *not* taken from this repository, so both of its failure modes overstate
the gap. Reading the wrong table would count rows that never had an evidence link. Misreading a stage
would put an unverified claim on the handover list, where it does not belong -- and the stage column
is free prose, including one value that contains both `documented` and `未測定`.

The report itself is not asserted here. Its output changes whenever a claim or a citation is added,
which is the point of running it.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def load():
    spec = importlib.util.spec_from_file_location(
        "report_citation_coverage", ROOT / "tools" / "report_citation_coverage.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mod = load()


# --- the stage column is prose, not an enum -----------------------------------------------------


@pytest.mark.parametrize(
    ("stage", "expected"),
    [
        ("検証済み", "verified"),
        ("検証済み（失敗することを確認）", "verified"),
        ("**検証済み（減衰なし）**", "verified"),
        ("ドキュメント記載 / 実機未検証", "documented"),
        ("未検証", "unverified"),
        ("**未測定**", "unverified"),
        ("未確認（観測不能）", "unverified"),
        ("**誤り（否定済み）**", "retracted"),
        ("機構として対象外", "other"),
    ],
)
def test_stage_is_classified_by_substring(stage: str, expected: str) -> None:
    assert mod.stage_class(stage) == expected


def test_a_documented_stage_that_also_says_unmeasured_stays_documented() -> None:
    """The real value from the status page. Reading it as unverified would hide a published basis."""
    stage = "**documented（ブロックプロトコルでの実測は未測定）**"
    assert mod.stage_class(stage) == "documented"


def test_a_retracted_claim_is_not_offered_for_handover() -> None:
    """A withdrawn claim is not knowledge to transfer, and #94 is why it must not read as one."""
    assert mod.stage_class("**誤り（否定済み）**") not in mod.TRANSFERABLE


# --- reading the right table --------------------------------------------------------------------


def test_only_the_claim_section_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The status page holds other tables. Counting them would report a gap against rows that
    never had an evidence link."""
    document = tmp_path / mod.STATUS
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(
        f"""# 検証状況
## 中核の検証範囲
| 項目 | 段階 | 根拠 |
|---|---|---|
| これは別の表 | 検証済み | [記録](verification/other.md) |
{mod.CLAIM_SECTION}
| 項目 | 段階 | 根拠 |
|---|---|---|
| 本物の主張 | 検証済み | [記録](verification/real.md) |
## 残っている測定（優先順）
| 項目 | 段階 | 根拠 |
|---|---|---|
| これも別の表 | 未測定 | [計画](verification/plan.md) |
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    rows = mod.claims()
    assert [row.text for row in rows] == ["本物の主張"]
    assert rows[0].documents == ("docs/ja/verification/real.md",)


def test_a_fenced_table_is_not_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An example table inside a code fence is documentation, not a claim."""
    document = tmp_path / mod.STATUS
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(
        f"""{mod.CLAIM_SECTION}
| 項目 | 段階 | 根拠 |
|---|---|---|
| 本物 | 検証済み | [記録](verification/real.md) |
```text
| 例示 | 検証済み | [記録](verification/example.md) |
```
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert [row.text for row in mod.claims()] == ["本物"]


def test_an_external_only_evidence_row_has_no_local_document(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Coverage is not ours to measure when the evidence belongs to a vendor or a sibling."""
    document = tmp_path / mod.STATUS
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(
        f"""{mod.CLAIM_SECTION}
| 項目 | 段階 | 根拠 |
|---|---|---|
| 他社文書だけが根拠 | ドキュメント記載 | [AWS](https://docs.aws.amazon.com/x.html) |
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.claims()[0].documents == ()


def test_an_anchor_is_not_part_of_the_document_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A probe is registered against a file, so a fragment would never match."""
    document = tmp_path / mod.STATUS
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text(
        f"""{mod.CLAIM_SECTION}
| 項目 | 段階 | 根拠 |
|---|---|---|
| 節を指す根拠 | 検証済み | [記録](verification/real.md#ある節) |
""",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    assert mod.claims()[0].documents == ("docs/ja/verification/real.md",)


def test_no_claim_row_is_reported_as_a_broken_reader(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Zero claims means the section was renamed, not that the status page is empty."""
    document = tmp_path / mod.STATUS
    document.parent.mkdir(parents=True, exist_ok=True)
    document.write_text("# 検証状況\n## 別の見出し\n", encoding="utf-8")
    monkeypatch.setattr(mod, "ROOT", tmp_path)
    monkeypatch.setattr(mod.sys, "argv", ["report_citation_coverage.py"])

    fake = type(
        "FakeProbes",
        (),
        {
            "checkout": staticmethod(lambda: tmp_path),
            "contract_from": staticmethod(lambda _base: ([], [])),
            "CONTRACT": Path("docs/agent/cross-repo-probe-contract.txt"),
            "CHECKOUT_NAMES": ("sibling",),
        },
    )
    monkeypatch.setattr(mod, "probes_module", lambda: fake)

    assert mod.main() == 1
    assert "broken reader" in capsys.readouterr().err
