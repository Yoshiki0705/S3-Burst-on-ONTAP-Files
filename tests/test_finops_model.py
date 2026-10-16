"""Tests for the cost model's language handling and the common baseline grid.

For the use-case sections the arithmetic is not tested here: `make finops` already compares every
total against the committed document, which is a stronger check than any assertion about a single
figure would be. What is tested for them is the part that has no such backstop: that adding a
language cannot quietly change the Japanese output, and that a partially translated model cannot
produce a half-Japanese English document.

The baseline grid is tested for its arithmetic as well. It is generated from the same model as the
document it is compared with, so a misreading of a formula would be copied into both and `make
finops` would pass. The baseline tests therefore recompute from the stated formulas, with exact
fractions for the quantities and a second implementation for the amounts, and fix the cells a
figure reads as literals.
"""

from __future__ import annotations

import ast
import json
import math
import pathlib
import re
import sys
from decimal import Decimal
from fractions import Fraction

import finops_model as fm
import pytest


def teardown_function() -> None:
    """Rendering sets module state; leave it as the module found it."""
    fm.render("ja")


# --- the Japanese output is not affected by the language mechanism -------------------------------


def test_rendering_japanese_twice_gives_the_same_block() -> None:
    assert fm.render("ja") == fm.render("ja")


def test_rendering_english_in_between_does_not_change_japanese() -> None:
    """The language is module state, so a stale value would surface here rather than in a diff."""
    first = fm.render("ja")
    fm.translation_gaps()
    assert fm.render("ja") == first


def test_an_unknown_language_is_refused() -> None:
    with pytest.raises(SystemExit, match="unknown language"):
        fm.render("fr")


# --- the gap report is what decides whether English gets written --------------------------------


def test_the_gap_report_counts_japanese_left_in_the_english_render() -> None:
    """Counting only the missing `t()` entries reported zero before a single call site was
    converted, and called the model ready. Residue is the measure that cannot be fooled that way."""
    missing, residue = fm.translation_gaps()
    assert isinstance(missing, list)
    assert isinstance(residue, list)
    for line in residue:
        assert fm.CJK.search(line), line


def test_the_gap_report_leaves_no_stand_ins_behind() -> None:
    """It inserts each missing key as its own translation to reach the next one. Left in place, those
    stand-ins would make the next call report a clean model that emits Japanese."""
    before = dict(fm.TRANSLATIONS)
    fm.translation_gaps()
    assert fm.TRANSLATIONS == before


def test_a_missing_entry_raises_rather_than_falling_back() -> None:
    """Falling back to Japanese is what produces a document that renders and reads wrong."""
    fm._LANG = "en"
    try:
        with pytest.raises(fm.MissingTranslation):
            fm.t("この文字列には英語の項目がない")
    finally:
        fm._LANG = "ja"


def test_translation_is_applied_before_interpolation() -> None:
    """Interpolating first would make every distinct number a distinct key."""
    fm.TRANSLATIONS["合計 {amount}"] = "Total {amount}"
    fm._LANG = "en"
    try:
        assert fm.t("合計 {amount}", amount="$1.00") == "Total $1.00"
    finally:
        fm._LANG = "ja"
        fm.TRANSLATIONS.pop("合計 {amount}")


def test_japanese_passes_through_untranslated() -> None:
    fm._LANG = "ja"
    assert fm.t("単価表") == "単価表"
    assert fm.t("合計 {amount}", amount="$1.00") == "合計 $1.00"


def test_a_source_string_with_no_japanese_needs_no_entry() -> None:
    """Otherwise a hundred entries mapping `GB-Mo` and `S3 Standard-IA GET` to themselves would sit
    in the table for a reviewer to read past."""
    fm._LANG = "en"
    try:
        assert fm.t("S3 Standard-IA GET / 1,000") == "S3 Standard-IA GET / 1,000"
        assert fm.t("GB-Mo") == "GB-Mo"
        assert fm.t("{mbps} MBps", mbps=384) == "384 MBps"
    finally:
        fm._LANG = "ja"


def test_no_key_is_defined_twice_in_the_translation_source() -> None:
    """The table is a dict literal plus an `update()` call, so ruff's duplicate-key rule only sees
    within each. A key defined in both is silently resolved to whichever ran last, and a later edit
    to the other one has no effect — which is not visible in a diff or in the rendered output."""
    source = (pathlib.Path(fm.__file__).parent / "finops_translations.py").read_text(
        encoding="utf-8"
    )
    keys = [
        node.value
        for dictionary in ast.walk(ast.parse(source))
        if isinstance(dictionary, ast.Dict)
        for node in dictionary.keys
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]
    duplicates = sorted({key for key in keys if keys.count(key) > 1})
    assert duplicates == [], duplicates


def test_every_scenario_title_keeps_the_separator_the_short_name_needs() -> None:
    """The tables index workloads by `title.split(" — ")[0]`. Translate a title without the em dash
    and the whole title lands in a narrow column instead — no error, just a wrecked table."""
    for scenario in fm.SCENARIOS:
        assert " — " in scenario.title, scenario.key
        assert " — " in fm.TRANSLATIONS[scenario.title], scenario.key


# --- the common 20 TiB baseline grid ------------------------------------------------------------
#
# The patterns are held as working-set ratio w, reads per working-set object n and churn rate c.
# The tests below fix three things: the patterns are exactly the agreed eight, every derived
# quantity follows from (w, n, c, size) by the stated formulas, and the amounts match a second
# implementation written here from the formulas rather than from the model.

BASELINE_EXPECTED = {
    # key: (w %, n, c %)
    "P1": (5, 1, 0),
    "P2": (100, 1, 0),
    "P3": (20, 5, 0),
    "P4": (10, 10, 0),
    "P5": (10, 10, 5),
    "P6": (50, 4, 100),
    "P7": (100, 2, 100),
    "P8": (10, 1, 100),
}
STORED_GIB = 20480


def _baseline_section(lang: str = "ja") -> str:
    head = "### 共通ベースライン" if lang == "ja" else "### A common baseline"
    block = fm.render(lang)
    fm.render("ja")  # restore module state
    return block.split(head)[1].split("\n### ")[0]


def _cell_sections(section: str, lang: str = "ja") -> dict[tuple[str, str], str]:
    marker = (
        r"^#### パターン (P\d+) — オブジェクト (.+)$"
        if lang == "ja"
        else r"^#### Pattern (P\d+) — (.+) objects$"
    )
    matches = list(re.finditer(marker, section, flags=re.MULTILINE))
    cells = {}
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(section)
        key = (m.group(1), m.group(2))
        assert key not in cells, key
        cells[key] = section[m.start() : end]
    return cells


def test_the_patterns_are_exactly_the_agreed_eight() -> None:
    got = {
        p.key: (p.working_set_pct, p.reads_per_object, p.churn_pct)
        for p in fm.BASELINE_PATTERNS
    }
    assert got == BASELINE_EXPECTED
    assert [p.key for p in fm.BASELINE_PATTERNS] == list(BASELINE_EXPECTED)


def test_only_p1_p6_and_p8_are_placeholders() -> None:
    assert {p.key for p in fm.BASELINE_PATTERNS if p.placeholder} == {"P1", "P6", "P8"}


def test_the_basis_of_every_value_is_recorded() -> None:
    basis = {p.key: p.basis for p in fm.BASELINE_PATTERNS}
    assert basis == {
        "P1": ("placeholder", "placeholder", "sourced"),
        "P2": ("placeholder", "placeholder", "sourced"),
        "P3": ("sourced", "placeholder", "sourced"),
        "P4": ("repository", "repository", "sourced"),
        "P5": ("repository", "repository", "placeholder"),
        "P6": ("placeholder", "placeholder", "placeholder"),
        "P7": ("repository", "repository", "repository"),
        "P8": ("placeholder", "placeholder", "placeholder"),
    }


def test_the_baseline_grid_is_eight_patterns_by_four_sizes() -> None:
    cells = fm.baseline_cells()
    assert len(cells) == 32
    assert fm.BASELINE_SIZES_KIB == (64, 1024, 4096, 16384)
    assert {c.pattern.key for c in cells} == set(BASELINE_EXPECTED)
    for pattern in fm.BASELINE_PATTERNS:
        sizes = [c.object_kib for c in cells if c.pattern is pattern]
        assert sizes == [64, 1024, 4096, 16384], pattern.key


def test_every_cell_stores_the_common_20_tib_whatever_the_pattern_writes() -> None:
    """One fixed footing. A pattern that writes 20 TiB a month replaces what is stored; it does not
    enlarge it, so the stored volume is the same in the cell that writes nothing and the one that
    writes as much as is stored."""
    for cell in fm.baseline_cells():
        assert cell.stored_gib == STORED_GIB == fm.BASELINE_STORED_TIB * fm.GIB_PER_TIB
        assert cell.retention_months == 1.0
        assert cell.file_protocol_required is False


def test_derived_quantities_follow_the_stated_formulas_in_every_cell() -> None:
    """Computed with exact fractions from (w, n, c, size), not from the model's own arithmetic."""
    for cell in fm.baseline_cells():
        w, n, c = BASELINE_EXPECTED[cell.pattern.key]
        kib = Fraction(cell.object_kib)
        stored = Fraction(STORED_GIB)
        working_set = stored * w / 100
        read = working_set * n
        write = stored * c / 100
        per_gib = Fraction(1024 * 1024) / kib  # objects per GiB at this size
        where = (cell.pattern.key, cell.object_kib)

        assert Fraction(cell.working_set_gib) == working_set, where
        assert Fraction(cell.read_gib_per_month) == read == stored * w * n / 100, where
        assert Fraction(cell.write_gib_per_month) == write, where
        assert Fraction(cell.unread_gib) == stored - working_set, where
        assert Fraction(cell.objects_stored) == stored * per_gib, where
        assert Fraction(cell.working_set_objects) == working_set * per_gib, where
        assert Fraction(cell.reads_per_month) == read * per_gib, where
        assert Fraction(cell.objects_per_month) == write * per_gib, where
        assert cell.pattern.read_multiple == pytest.approx(float(read / stored)), where
        # size x count returns the bytes, so no count is quietly a volume
        assert Fraction(cell.reads_per_month) * kib / (1024 * 1024) == read, where
        assert Fraction(cell.objects_per_month) * kib / (1024 * 1024) == write, where
        assert Fraction(cell.objects_stored) * kib / (1024 * 1024) == stored, where
        assert cell.working_set_objects <= cell.objects_stored, where
        assert cell.read_gib_per_month + cell.write_gib_per_month > 0, where


def test_the_byte_ratio_is_a_share_of_bytes_moved() -> None:
    expected = {
        "P1": (100.0, 0.0),
        "P2": (100.0, 0.0),
        "P5": (95.2, 4.8),
        "P6": (66.7, 33.3),
        "P8": (9.1, 90.9),
    }
    for cell in fm.baseline_cells():
        if cell.pattern.key in expected:
            read, write = expected[cell.pattern.key]
            assert round(cell.read_share_pct, 1) == read, cell.pattern.key
            assert round(cell.write_share_pct, 1) == write, cell.pattern.key


@pytest.mark.parametrize(
    "overrides",
    [
        {"churn_pct": 101},
        {"churn_pct": -1},
        {"working_set_pct": 0},
        {"working_set_pct": 101},
        {"reads_per_object": 0},
        {"basis": ("sourced", "sourced")},
        {"basis": ("sourced", "sourced", "guess")},
        {"key": "Q1"},
        {"key": "P"},
    ],
)
def test_a_pattern_that_cannot_be_read_as_a_replacement_is_refused(
    overrides: dict[str, object],
) -> None:
    fields: dict[str, object] = {
        "key": "P9",
        "name": "x",
        "working_set_pct": 10,
        "reads_per_object": 1,
        "churn_pct": 0,
        "placeholder": False,
        "basis": ("sourced", "sourced", "sourced"),
        "position": "x",
    }
    fields.update(overrides)
    with pytest.raises(ValueError):
        fm.BaselinePattern(**fields)  # type: ignore[arg-type]


def test_a_pattern_touches_the_whole_volume_when_w_plus_c_reaches_100() -> None:
    touching = {p.key for p in fm.BASELINE_PATTERNS if p.touches_whole_volume}
    assert touching == {"P2", "P6", "P7", "P8"}
    for p in fm.BASELINE_PATTERNS:
        assert p.touches_whole_volume == (p.working_set_pct + p.churn_pct >= 100)


def test_the_baseline_has_no_industry_field() -> None:
    """A dedicated dataclass was chosen over reusing Scenario precisely so the grid carries no
    industry; this guards that choice against a later field creeping back in."""
    assert not hasattr(fm.baseline_cells()[0], "industry")


# --- amounts: a second implementation, then literals ---------------------------------------------


def _dec(value: float) -> Decimal:
    return Decimal(str(value))


def _independent_subtotals(
    w: int, n: int, c: int, size_kib: int
) -> tuple[Decimal, Decimal, Decimal | None]:
    """FSx for ONTAP, S3 Files and (if there are no writes) S3-alone subtotals.

    Written from the pricing description and the unit prices, with Decimal. It shares the unit
    prices with the model and nothing else: not the helpers, not the cell class, not the rounding.
    """
    stored = Decimal(STORED_GIB)
    read = stored * w * n / 100
    write = stored * c / 100
    kib = Decimal(size_kib)
    gib_per_kib = Decimal(1) / Decimal(1024 * 1024)
    reads = read / (kib * gib_per_kib)
    writes = write / (kib * gib_per_kib)
    s3_storage = stored * _dec(
        0.025
    )  # 20,480 GiB sits inside the first S3 Standard tier
    put = writes * _dec(fm.S3["tier1"].usd)
    get = reads * _dec(fm.S3["tier2"].usd)

    # FSx for ONTAP, Single-AZ gen 1, 30 % capacity pool, 40 % SSD / 20 % pool efficiency
    ssd_gib = max(
        1024,
        math.ceil(float(stored * Decimal("0.7") * Decimal("0.6") * Decimal("1.2"))),
    )
    pool_gib = stored * Decimal("0.3") * Decimal("0.8")
    mbps = (read + write) * 1024 / 2_592_000
    target = mbps * 5
    tput = next((o for o in (128, 256, 512, 1024, 2048, 4096) if o >= target), 4096)
    fsx = (
        ssd_gib * _dec(fm.FSX["ssd_saz"].usd)
        + tput * _dec(fm.FSX["tput_saz1"].usd)
        + pool_gib * _dec(fm.FSX["pool_saz"].usd)
        + reads * Decimal("0.3") * _dec(fm.FSX["pool_read"].usd)
        + writes * _dec(fm.S3["ap_tier1"].usd)
    )

    meta_gib = Decimal(4) * gib_per_kib
    meta_in = writes * meta_gib * _dec(fm.S3FILES["write"].usd)
    meta_rd = reads * meta_gib * _dec(fm.S3FILES["read"].usd)
    if size_kib <= 128:
        floor_factor = max(Decimal(1), Decimal(10) / kib)
        hps = stored * floor_factor * _dec(fm.S3FILES["storage"].usd)
        io_kib = max(kib, Decimal(32))
        streamed = writes
        files_get = streamed * _dec(fm.S3["tier2"].usd)
        imp = writes * io_kib * gib_per_kib * _dec(fm.S3FILES["write"].usd)
        hps_reads = max(Decimal(0), reads - streamed)
        rd = hps_reads * io_kib * gib_per_kib * _dec(fm.S3FILES["read"].usd)
        files = s3_storage + put + hps + files_get + imp + rd + meta_in + meta_rd
    else:
        files = s3_storage + put + get + meta_in + meta_rd

    direct = s3_storage + put + get if c == 0 else None
    return fsx, files, direct


def test_every_subtotal_matches_an_independent_calculation() -> None:
    for cell in fm.baseline_cells():
        w, n, c = BASELINE_EXPECTED[cell.pattern.key]
        fsx, files, direct = _independent_subtotals(w, n, c, int(cell.object_kib))
        files_lines = fm.s3_files_option(cell, split_metadata=True)
        assert files_lines is not None
        where = (cell.pattern.key, cell.object_kib)
        assert abs(_dec(sum(fm.fsx_s3ap(cell).values())) - fsx) < Decimal("0.01"), where
        assert abs(_dec(sum(files_lines.values())) - files) < Decimal("0.01"), where
        solo = fm.s3_only(cell)
        if direct is None:
            assert solo is None or c > 0, where
        else:
            assert solo is not None
            assert abs(_dec(sum(solo.values())) - direct) < Decimal("0.01"), where


# Literals from the independent calculation, fixed so that the second implementation and the model
# cannot share a misreading unnoticed. They are the cells the cost figure reads (P1, P3, P4, P6, P8
# at 64 KiB and 4 MiB); P3 and P4 price the same as P2.
FIGURE_SUBTOTALS = {
    # (pattern, size KiB): (FSx for ONTAP, S3 Files)
    ("P1", 64): ("$1,783.11", "$7,928.32"),
    ("P1", 4096): ("$1,781.28", "$512.14"),
    ("P3", 64): ("$1,818.50", "$8,755.20"),
    ("P3", 4096): ("$1,781.83", "$514.74"),
    ("P4", 64): ("$1,818.50", "$8,755.20"),
    ("P4", 4096): ("$1,781.83", "$514.74"),
    ("P6", 64): ("$2,218.13", "$12,030.81"),
    ("P6", 4096): ("$1,788.08", "$543.52"),
    ("P8", 64): ("$2,147.36", "$11,114.33"),
    ("P8", 4096): ("$1,786.97", "$538.32"),
}
DIRECT_SUBTOTALS = {
    ("P1", 64): "$518.21",
    ("P1", 4096): "$512.10",
    ("P3", 64): "$636.15",
    ("P3", 4096): "$513.94",
    ("P4", 64): "$636.15",
    ("P4", 4096): "$513.94",
}
METADATA_USD = {
    # (pattern, size KiB): (import side, read side)
    ("P4", 4096): ("$0.00", "$0.80"),
    ("P5", 4096): ("$0.07", "$0.80"),
    ("P7", 64): ("$89.60", "$102.40"),
    ("P8", 64): ("$89.60", "$5.12"),
}


def _cell(key: str, kib: int) -> fm.BaselineCell:
    return next(
        c for c in fm.baseline_cells() if c.pattern.key == key and c.object_kib == kib
    )


def test_the_figure_cells_have_the_recorded_subtotals() -> None:
    for (key, kib), (fsx, files) in FIGURE_SUBTOTALS.items():
        cell = _cell(key, kib)
        files_lines = fm.s3_files_option(cell, split_metadata=True)
        assert files_lines is not None
        assert fm.usd(sum(fm.fsx_s3ap(cell).values())) == fsx, (key, kib)
        assert fm.usd(sum(files_lines.values())) == files, (key, kib)
    for (key, kib), expected in DIRECT_SUBTOTALS.items():
        solo = fm.s3_only(_cell(key, kib))
        assert solo is not None
        assert fm.usd(sum(solo.values())) == expected, (key, kib)


def test_the_metadata_charges_are_their_own_lines_with_the_recorded_amounts() -> None:
    for (key, kib), (ingest, read) in METADATA_USD.items():
        cell = _cell(key, kib)
        ingest_usd, read_usd = fm.s3_files_metadata_usd(cell)
        assert (fm.usd(ingest_usd), fm.usd(read_usd)) == (ingest, read), (key, kib)
        lines = fm.s3_files_option(cell, split_metadata=True)
        assert lines is not None
        shown = {
            label: value
            for label, value in lines.items()
            if label.startswith("S3 Files メタデータ")
        }
        assert sorted(shown.values()) == sorted([ingest_usd, read_usd]), (key, kib)


# --- the amounts do not follow the working-set ratio ---------------------------------------------


def test_patterns_with_the_same_read_and_write_volumes_price_the_same() -> None:
    """P2, P3 and P4 read 20 TiB and write nothing; P6 and P7 read 40 and write 20. Their working
    sets differ, their amounts do not. If this starts failing, the price has begun to follow the
    working-set ratio, which the document says it does not."""
    groups = sorted(sorted(p.key for p in g) for g in fm.baseline_same_price_groups())
    assert groups == [["P2", "P3", "P4"], ["P6", "P7"]]
    singles = {p.key for p in fm.BASELINE_PATTERNS} - {k for g in groups for k in g}
    assert singles == {"P1", "P5", "P8"}


def test_the_json_states_that_price_does_not_depend_on_the_working_set() -> None:
    data = fm.baseline_json("ja")
    assert data["pricing_depends_on_working_set"] is False
    assert data["price_inputs"] == ["object_size", "read_bytes", "write_bytes"]


# --- the metadata lines and the first-read stream ------------------------------------------------


def test_the_default_lines_of_s3_files_are_unchanged() -> None:
    """The use-case sections call it without the flag; their labels and amounts must not move."""
    by_branch = {
        "small": next(
            s for s in fm.SCENARIOS if s.s3files_viable and s.object_mib * 1024 <= 128
        ),
        "large": next(
            s for s in fm.SCENARIOS if s.s3files_viable and s.object_mib * 1024 > 128
        ),
    }
    small = fm.s3_files_option(by_branch["small"])
    large = fm.s3_files_option(by_branch["large"])
    assert small is not None and large is not None
    assert "S3 Files 読み取り (取り込み後の読み出しとメタデータ)" in small
    assert "GET リクエスト (初回読み出しはバケットからストリーム)" in small
    assert "S3 Files 読み取り (メタデータ)" in large
    assert "S3 Files 書き込み (メタデータの取り込み)" in large


def test_splitting_the_metadata_does_not_change_any_subtotal() -> None:
    """Every baseline cell and every scenario: the same sum, split into different lines."""
    for item in [*fm.baseline_cells(), *fm.SCENARIOS]:
        plain = fm.s3_files_option(item)
        split = fm.s3_files_option(item, split_metadata=True)
        assert (plain is None) == (split is None)
        if plain is not None and split is not None:
            assert abs(sum(plain.values()) - sum(split.values())) < 1e-9


def test_both_metadata_lines_exist_in_both_branches_of_a_baseline_cell() -> None:
    for kib in (64, 4096):
        lines = fm.s3_files_option(_cell("P5", kib), split_metadata=True)
        assert lines is not None
        labels = list(lines)
        assert (
            sum(label.startswith("S3 Files メタデータ取り込み") for label in labels)
            == 1
        )
        assert (
            sum(label.startswith("S3 Files メタデータ読み取り") for label in labels)
            == 1
        )


def test_a_cell_with_no_writes_books_no_first_read_stream_line() -> None:
    stream = "GET リクエスト (初回読み出しはバケットからストリーム)"
    for pattern in fm.BASELINE_PATTERNS:
        lines = fm.s3_files_option(_cell(pattern.key, 64), split_metadata=True)
        assert lines is not None
        assert (stream in lines) == (pattern.churn_pct > 0), pattern.key
        # dropping a zero-valued line leaves the total where the default call puts it
        plain = fm.s3_files_option(_cell(pattern.key, 64))
        assert plain is not None
        assert abs(sum(lines.values()) - sum(plain.values())) < 1e-9, pattern.key


# --- the generated section -------------------------------------------------------------------


def test_the_section_has_one_heading_per_cell_and_no_repeats() -> None:
    cells = _cell_sections(_baseline_section("ja"))
    assert len(cells) == 32
    assert {k for k, _ in cells} == set(BASELINE_EXPECTED)
    assert {s for _, s in cells} == {"64 KiB", "1 MiB", "4 MiB", "16 MiB"}


def test_every_cell_shows_all_eight_items_and_says_writes_replace() -> None:
    section = _baseline_section("ja")
    cells = _cell_sections(section)
    labels = [
        "| 1. 保存量 (論理) と保存オブジェクト数 |",
        "| 2. オブジェクトサイズ |",
        "| 3. 作業セット (月内に読まれる部分) |",
        "| 4. 作業セット内の読み取り回数 |",
        "| 5. 月間読み取り (バイト / 回数 / 保存量に対する倍数 R) |",
        "| 6. 月間書き込み (バイト / 個数 / 保存量に対する比 = チャーン率) |",
        "| 7. 読み : 書き (バイト比。操作数の比ではない) |",
        "| 8. リテンション |",
    ]
    for key, body in cells.items():
        for label in labels:
            assert body.count(label) == 1, (key, label)
        retention = next(
            line for line in body.split("\n") if line.startswith("| 8. リテンション")
        )
        assert "置き換え" in retention, key


def test_placeholders_are_marked_in_the_pattern_table_and_nowhere_else() -> None:
    section = _baseline_section("ja")
    phrase = "出典のある値ではなく、算術を通すための仮置き"
    rows = [line for line in section.split("\n") if phrase in line]
    assert sorted(line.split(" | ")[0].lstrip("| ") for line in rows) == [
        "P1",
        "P6",
        "P8",
    ]
    en = _baseline_section("en")
    en_rows = [
        line
        for line in en.split("\n")
        if "Not a sourced value; placed to make the arithmetic work" in line
    ]
    assert sorted(line.split(" | ")[0].lstrip("| ") for line in en_rows) == [
        "P1",
        "P6",
        "P8",
    ]


def test_every_subtotal_is_a_major_line_item_subtotal() -> None:
    """Each total has an uncounted line item (the UNCONFIRMED capacity-pool read requests), so it
    must be labelled a 主要費目小計, never a 月額総額. FSx for ONTAP and S3 Files in all 32 cells,
    plus S3 alone in the 16 cells that have no writes."""
    section = _baseline_section("ja")
    assert section.count("**主要費目小計 / major-line-item subtotal**") == 32 * 2 + 16
    assert "| **月額総額" not in section


def test_s3_alone_appears_only_where_there_are_no_writes() -> None:
    cells = _cell_sections(_baseline_section("ja"))
    for (key, _), body in cells.items():
        has_direct = "**S3 単独 (利用側も S3 API)**" in body
        assert has_direct == (BASELINE_EXPECTED[key][2] == 0), key


def test_the_first_read_stream_note_is_in_exactly_the_four_cells_it_applies_to() -> (
    None
):
    section = _baseline_section("ja")
    cells = _cell_sections(section)
    stream = "GET リクエスト (初回読み出しはバケットからストリーム)"
    note = "は、初回読み出しのストリームを計上しない。"
    for (key, size), body in cells.items():
        no_writes_small = BASELINE_EXPECTED[key][2] == 0 and size == "64 KiB"
        assert (note in body) == no_writes_small, (key, size)
        if size == "64 KiB":
            assert (stream in body) == (not no_writes_small), (key, size)
        else:
            assert stream not in body, (key, size)


def test_the_fixed_premises_are_stated_once_with_the_groups_derived() -> None:
    section = _baseline_section("ja")
    assert section.count("この表の 3 つの前提は作業セット比と切り離している。") == 1
    assert "P1・P3・P4・P5 は、作業セット比とチャーン率の和が 100% 未満" in section
    assert "P2・P6・P7・P8 は和が 100% 以上" in section
    assert "(P2・P3・P4) と (P6・P7) は" in section


def test_the_baseline_leaves_capacity_pool_requests_unconfirmed() -> None:
    """The count per GET is not measured; the grid must say so rather than guess a number."""
    assert "未確認" in _baseline_section("ja")
    en_section = _baseline_section("en")
    assert "UNCONFIRMED" in en_section or "unconfirmed" in en_section


def test_the_metadata_lines_are_counted_in_the_subtotal_and_the_doubt_is_stated() -> (
    None
):
    section = _baseline_section("ja")
    assert "1 MiB 以上の読み取りと取り込みにも立つかは、未確認である" in section
    # The delta in the note is the model's own figure for the cell that moves most (P6, 1 MiB).
    assert "最大 $12.00 (そのセルの小計の 1.9%) 下がる" in section
    assert "subtotal_excluding_metadata_usd" in section


def test_every_generated_string_now_has_english() -> None:
    """The document is promoted only once this holds, and it has to keep holding afterwards: a new
    gap makes the script skip English rather than fail, which would freeze the English tables."""
    missing, residue = fm.translation_gaps()
    assert missing == []
    assert residue == []


def test_the_english_section_has_the_same_cells_as_the_japanese() -> None:
    ja = _cell_sections(_baseline_section("ja"))
    en = _cell_sections(_baseline_section("en"), "en")
    assert [k for k in ja] == [k for k in en]


# --- machine-readable output ---------------------------------------------------------------------


def test_the_json_carries_every_pattern_and_size() -> None:
    data = fm.baseline_json("ja")
    assert data["stored_gib"] == STORED_GIB
    patterns = data["patterns"]
    assert [p["id"] for p in patterns] == list(BASELINE_EXPECTED)  # type: ignore[index]
    for p in patterns:  # type: ignore[attr-defined]
        assert [c["size_kib"] for c in p["cells"]] == [64, 1024, 4096, 16384]


def test_the_json_amounts_are_the_ones_printed_in_the_document() -> None:
    section = _baseline_section("ja")
    cells = _cell_sections(section)
    size_label = {64: "64 KiB", 1024: "1 MiB", 4096: "4 MiB", 16384: "16 MiB"}
    data = fm.baseline_json("ja")
    for p in data["patterns"]:  # type: ignore[attr-defined]
        for c in p["cells"]:
            body = cells[(p["id"], size_label[c["size_kib"]])]
            for method in ("fsx_s3ap", "s3_files", "s3_direct"):
                m = c["methods"][method]
                if m is None:
                    assert p["churn_pct"] > 0
                    continue
                assert f"**{m['subtotal_display']}**" in body, (p["id"], c["size_kib"])
                assert abs(m["subtotal_usd"] - sum(x["usd"] for x in m["lines"])) < 1e-9
            files = c["methods"]["s3_files"]
            md = files["metadata_usd"]
            assert files["subtotal_excluding_metadata_usd"] == pytest.approx(
                files["subtotal_usd"] - md["ingest"] - md["read"]
            )


def test_the_json_counts_are_integers_and_s3_alone_is_absent_with_writes() -> None:
    for p in fm.baseline_json("ja")["patterns"]:  # type: ignore[attr-defined]
        for c in p["cells"]:
            for key in (
                "stored_objects",
                "working_set_objects",
                "read_requests",
                "write_objects",
            ):
                assert isinstance(c[key], int), (p["id"], key)
            assert (c["methods"]["s3_direct"] is None) == (p["churn_pct"] > 0)


def test_the_json_is_the_same_bytes_every_time() -> None:
    first = json.dumps(fm.baseline_json("ja"), ensure_ascii=False, indent=2)
    assert first == json.dumps(fm.baseline_json("ja"), ensure_ascii=False, indent=2)


def test_the_english_json_has_no_japanese_in_labels_or_positions() -> None:
    data = fm.baseline_json("en")
    for p in data["patterns"]:  # type: ignore[attr-defined]
        assert not fm.CJK.search(p["position"]), p["id"]
        assert fm.CJK.search(p["name_ja"]) and not fm.CJK.search(p["name_en"])
        for c in p["cells"]:
            for m in c["methods"].values():
                for line in (m or {}).get("lines", []):
                    assert not fm.CJK.search(line["label"]), line["label"]
    assert fm._LANG == "ja"


def test_the_json_option_cannot_be_combined_with_the_document_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for other in ("--check", "--write", "--show-prices", "--translation-gaps"):
        monkeypatch.setattr(sys, "argv", ["finops_model.py", "--baseline-json", other])
        with pytest.raises(SystemExit) as exit_info:
            fm.main()
        assert exit_info.value.code == 2, other
    monkeypatch.setattr(sys, "argv", ["finops_model.py", "--lang", "en"])
    with pytest.raises(SystemExit) as exit_info:
        fm.main()
    assert exit_info.value.code == 2


def test_the_json_option_prints_json_and_leaves_the_documents_alone(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = {lang: fm.doc_for(lang).read_bytes() for lang in fm.LANGS}
    monkeypatch.setattr(
        sys, "argv", ["finops_model.py", "--baseline-json", "--lang", "en"]
    )
    assert fm.main() == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["schema_version"] == 1
    assert {lang: fm.doc_for(lang).read_bytes() for lang in fm.LANGS} == before


# --- documents ----------------------------------------------------------------------------------


def test_each_language_resolves_to_its_own_document() -> None:
    assert fm.doc_for("ja") != fm.doc_for("en")
    for lang in fm.LANGS:
        assert fm.doc_for(lang).parts[-4:-3] == (lang,)


def test_the_japanese_document_exists() -> None:
    """The English one is created by the promotion; this script only splices into it."""
    assert fm.doc_for("ja").is_file()
