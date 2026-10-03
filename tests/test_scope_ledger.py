"""スコープ台帳の網羅性ゲートを、実台帳と、通してはいけない合成台帳の両方で確かめる。

実台帳は読むだけで、合格することだけを見る。不合格の振る舞い（17 本・19 本・重複・未判定・
区分の誤り）は、テスト内で組み立てた台帳文字列で確かめる。実台帳がたまたま正しいだけでは、
ゲートが落ちるべき入力で落ちることの証拠にならないため。
"""

from __future__ import annotations

import check_scope_ledger as ledger
import pytest

HEADER = "| " + " | ".join(ledger.EXPECTED_HEADER) + " |"
SEPARATOR = "|" + "---|" * len(ledger.EXPECTED_HEADER)


def row(
    name: str,
    scope: str,
    tier: str,
    delegation: str = "[委任台帳](delegation-ledger.md)参照",
) -> str:
    return f"| {name} | {scope} | {tier} | 関連根拠の 1 文 | {delegation} |"


def sound_rows(count: int = ledger.EXPECTED_TR_COUNT) -> list[str]:
    """先頭の半分をスコープ内（優先・後続を交互）、残りをスコープ外にした健全な行。"""
    rows = []
    for index in range(count):
        name = f"TR_{index:02d}.pdf"
        if index < count // 2:
            tier = ledger.TIER_VALUES[index % 2]
            rows.append(row(name, ledger.IN_SCOPE, tier))
        else:
            rows.append(
                row(name, ledger.OUT_OF_SCOPE, ledger.NO_TIER, "—（スコープ外）")
            )
    return rows


def compose(rows: list[str]) -> str:
    """実台帳と同じ形（節見出し → 表 → 次の節）の台帳文字列を組み立てる。"""
    return "\n".join(
        [
            "# 台帳",
            "",
            ledger.SECTION_HEADING,
            "",
            HEADER,
            SEPARATOR,
            *rows,
            "",
            "## 次の節",
            "",
        ]
    )


# --- 実台帳 -------------------------------------------------------------------------------------


def test_the_tracked_ledger_passes() -> None:
    assert ledger.check() == []


def test_the_tracked_ledger_is_actually_read() -> None:
    """合格が「表を読めなかった」ことの裏返しでないことを、行数で確かめる。"""
    _, rows = ledger.parse_rows(ledger.DEFAULT_LEDGER.read_text(encoding="utf-8"))
    assert len(rows) == ledger.EXPECTED_TR_COUNT
    assert {r[1] for r in rows} <= set(ledger.SCOPE_VALUES)


# --- 総数と重複（要件 1.1 / 1.5） ---------------------------------------------------------------


def test_a_sound_synthetic_ledger_passes() -> None:
    assert ledger.check_text(compose(sound_rows())) == []


@pytest.mark.parametrize("count", [17, 19])
def test_a_count_other_than_eighteen_fails(count: int) -> None:
    findings = ledger.check_text(compose(sound_rows(count)))
    assert len(findings) == 1
    assert f"行数が {count}" in findings[0]


def test_a_duplicate_filename_fails() -> None:
    rows = sound_rows()
    rows[-1] = rows[0]  # 18 行のまま、1 本が重複し 1 本が欠ける
    findings = ledger.check_text(compose(rows))
    assert findings == ["scope-ledger: ファイル名 'TR_00.pdf' が 2 回現れる"]


def test_a_missing_section_is_a_broken_reader() -> None:
    text = compose(sound_rows()).replace(ledger.SECTION_HEADING, "## 別の節")
    findings = ledger.check_text(text)
    assert len(findings) == 1
    assert "表が見つからない" in findings[0]


# --- 未判定（要件 1.1） -------------------------------------------------------------------------


@pytest.mark.parametrize("scope", ["", "未判定", "保留", "スコープ内 / スコープ外"])
def test_a_row_without_exactly_one_scope_judgement_fails(scope: str) -> None:
    rows = sound_rows()
    rows[0] = row("TR_00.pdf", scope, ledger.TIER_VALUES[0])
    findings = ledger.check_text(compose(rows))
    assert len(findings) == 1
    assert "未判定" in findings[0]


# --- 優先・後続区分（要件 1.3） -----------------------------------------------------------------


@pytest.mark.parametrize("tier", ["", "—", "優先スコープ / 後続スコープ", "保留"])
def test_an_in_scope_row_needs_exactly_one_tier(tier: str) -> None:
    rows = sound_rows()
    rows[0] = row("TR_00.pdf", ledger.IN_SCOPE, tier)
    findings = ledger.check_text(compose(rows))
    assert len(findings) == 1
    assert "スコープ内の 'TR_00.pdf'" in findings[0]


@pytest.mark.parametrize("tier", ledger.TIER_VALUES)
def test_an_out_of_scope_row_carries_no_tier(tier: str) -> None:
    rows = sound_rows()
    rows[-1] = row("TR_17.pdf", ledger.OUT_OF_SCOPE, tier)
    findings = ledger.check_text(compose(rows))
    assert len(findings) == 1
    assert "スコープ外の 'TR_17.pdf'" in findings[0]


# --- スコープ判定と委任判定の直交（要件 9.3） ---------------------------------------------------


@pytest.mark.parametrize("delegation", ["Hub", "Spoke", "保留"])
@pytest.mark.parametrize(
    ("scope", "tier"),
    [(ledger.IN_SCOPE, ledger.TIER_VALUES[0]), (ledger.OUT_OF_SCOPE, ledger.NO_TIER)],
)
def test_every_scope_and_delegation_combination_is_accepted(
    scope: str, tier: str, delegation: str
) -> None:
    """「スコープ外かつ Hub 委任」を含め、委任判定の値でスコープ判定の行が弾かれないこと。"""
    rows = sound_rows()
    rows[0] = row("TR_00.pdf", scope, tier, delegation)
    assert ledger.check_text(compose(rows)) == []
