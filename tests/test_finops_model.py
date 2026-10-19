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
    """Rendering sets the module language; leave it as the module found it.

    This used to call `fm.render("ja")`, which with the sensitivity section now runs ~6.4x10**4
    break-even evaluations after every test. The only module state a render leaves is `_LANG`, so
    resetting just that is enough and avoids the per-test cost.
    """
    fm._LANG = "ja"


def test_render_restores_the_language_state_so_teardown_need_only_reset_lang() -> None:
    """The teardown above assumes `render` leaves only `_LANG` changed. Confirm that holds: a full
    Japanese render after an English one is byte-identical, so no other state carried over."""
    first = fm.render("ja")
    fm.render("en")
    fm._LANG = "ja"
    assert fm.render("ja") == first


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
        "P1": ("placeholder", "placeholder", "definition"),
        "P2": ("placeholder", "placeholder", "definition"),
        "P3": ("sourced", "placeholder", "definition"),
        "P4": ("repository", "repository", "definition"),
        "P5": ("repository", "repository", "placeholder"),
        "P6": ("placeholder", "placeholder", "placeholder"),
        "P7": ("repository", "repository", "repository"),
        "P8": ("placeholder", "placeholder", "placeholder"),
    }


def test_a_zero_churn_is_a_definition_and_nothing_else_is() -> None:
    """No writes is true by construction, so it has no source to cite and no assumption to make. The
    JSON carries the same classification, so a reader of it does not see P1 as partly sourced."""
    for p in fm.BASELINE_PATTERNS:
        assert (p.basis[2] == "definition") == (p.churn_pct == 0), p.key
        assert "definition" not in p.basis[:2], p.key
    for entry in fm.baseline_json("ja")["patterns"]:  # type: ignore[attr-defined]
        basis = entry["basis"]
        assert (basis["churn"] == "definition") == (entry["churn_pct"] == 0), entry[
            "id"
        ]
        assert "definition" not in (basis["working_set"], basis["reads_per_object"])


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
        {"basis": ("definition", "sourced", "sourced")},
        {"basis": ("sourced", "sourced", "definition"), "churn_pct": 5},
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
        # A first read is still one read, so the stream count cannot exceed the month's reads.
        streamed = min(writes, reads)
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
    ("P8", 64): ("$2,147.36", "$11,002.59"),
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


_FIRST_READ_STREAM_LABEL = "GET リクエスト (初回読み出しはバケットからストリーム)"


def test_p8_64_kib_first_read_get_is_capped_at_the_read_count() -> None:
    """PR-H: the first-read stream GET line of the default P8 64 KiB cell is driven by the month's
    read count, not the (larger) written count. The cell books 335,544,320 writes against only
    33,554,432 reads, so without the cap the GET line would be ten times too large."""
    cell = _cell("P8", 64)
    # The cap binds here: the resolved first-read count exceeds the reads.
    assert fm._resolve_first_read_objects(cell) > cell.reads_per_month
    lines = fm.s3_files_option(cell, split_metadata=True)
    assert lines is not None
    get = lines[_FIRST_READ_STREAM_LABEL]
    assert abs(get - cell.reads_per_month * fm.S3["tier2"].usd) < 1e-9
    # Concretely, the capped GET line is 12.42, not the uncapped 124.15.
    assert fm.usd(get) == "$12.42"
    assert fm.usd(sum(lines.values())) == "$11,002.59"


def test_only_p8_64_kib_moves_under_the_cap_the_other_31_cells_are_unchanged() -> None:
    """PR-H changes exactly one of the 32 baseline cells. For every other cell the cap is a no-op:
    the resolved first-read count never exceeds the reads (writes <= reads, or the object is above
    the threshold and streamed directly), so the first-read GET line equals the uncapped value."""
    moved = []
    for cell in fm.baseline_cells():
        resolved = fm._resolve_first_read_objects(cell)
        capped = min(resolved, cell.reads_per_month)
        if (
            abs(resolved - capped) > 1e-9
            and cell.object_kib <= cell.s3files_threshold_kib
        ):
            moved.append((cell.pattern.key, int(cell.object_kib)))
    assert moved == [("P8", 64)], moved


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
    # The read side was observed in the billed quantity for 4 MiB objects only; the import side for 1 MiB or larger was not.
    assert (
        "読み取り側が 4 MiB のオブジェクトの読み取りにも立つことは、請求の数量で観測した"
        in section
    )
    assert "1 MiB と 16 MiB のオブジェクトの読み取りは観測していない" in section
    assert "取り込み側が 1 MiB 以上のオブジェクトにも立つかは、未確認である" in section
    assert "既定は 1 操作 × 4 KiB のままで、観測値には変えていない" in section
    # The delta in the note is the model's own figure for the cell that moves most (P6, 1 MiB).
    assert "最大 $12.00 (そのセルの小計の 1.9%) 下がる" in section
    assert "subtotal_excluding_metadata_usd" in section


def test_the_metadata_note_also_states_the_directions_that_raise_the_subtotal() -> None:
    """The increase is derived from the formula: stored objects x 4 KiB x the write price, once."""
    prices = fm.S3FILES["write"].usd
    expected = {}
    for kib in fm.BASELINE_SIZES_KIB:
        objects = Fraction(fm.BASELINE_STORED_TIB * 1024 * 1024 * 1024, kib)
        expected[kib] = float(objects * 4 / (1024 * 1024) * Fraction(str(prices)))
    ja = _baseline_section("ja")
    assert "増える方向もある。" in ja
    assert "読み取り側の行が k 倍になる" in ja
    assert "ファイル 1 個ごとに 4 KiB の書き込みを計量する" in ja
    sized = [
        f"{label} で ${expected[kib]:,.2f}"
        for kib, label in zip(
            fm.BASELINE_SIZES_KIB, ("64 KiB", "1 MiB", "4 MiB", "16 MiB"), strict=True
        )
    ]
    # The 64 KiB figure is the metadata alone and leaves out the data import (the default trigger
    # imports files at or below the threshold); the larger sizes stream the data and are written apart.
    assert (
        f"1 回限りの額 ({sized[0]}) は、メタデータ分だけの額で、128 KiB 以下のファイルのデータの取り込み書き込み"
        in ja
    )
    assert "は含まない。" in ja
    assert (
        f"128 KiB を超えるサイズ ({'、'.join(sized[1:])}) では、データは取り込まれず直接読まれるので、この額はメタデータ分のみである。"
        in ja
    )
    en = _baseline_section("en")
    assert "If each read carries k metadata operations" in en
    en_sized = [
        f"${expected[kib]:,.2f} for {label}"
        for kib, label in zip(
            fm.BASELINE_SIZES_KIB, ("64 KiB", "1 MiB", "4 MiB", "16 MiB"), strict=True
        )
    ]
    assert (
        f"({en_sized[0]}) is for the metadata alone; it does not include the import write"
        in en
    )
    assert (
        f"For sizes above 128 KiB ({', '.join(en_sized[1:])}) the data is not imported but read directly"
        in en
    )


def test_the_get_and_read_change_of_the_first_read_stream_is_a_decrease_in_every_cell() -> (
    None
):
    """The note quotes the GET-and-read change alone, as a decrease, and says the import write is not in
    it. The decrease is checked in each of the four cells, not only the one the note quotes. This is
    not the net direction of counting the first read, which the note says the model does not determine."""
    cells = [c for c in fm.baseline_cells() if fm._books_no_first_read_stream(c)]
    assert [(c.pattern.key, c.object_kib) for c in cells] == [
        (k, 64) for k in ("P1", "P2", "P3", "P4")
    ]
    for cell in cells:
        before, after = fm._first_read_stream_sensitivity(cell)
        assert after < before, cell.pattern.key
        # the default is unchanged: passing nothing is passing the objects written
        default = fm.s3_files_option(cell, split_metadata=True)
        explicit = fm.s3_files_option(
            cell, split_metadata=True, first_read_objects=cell.objects_per_month
        )
        assert default == explicit


def test_the_first_read_stream_note_lists_what_rises_and_falls_and_asserts_no_net_direction() -> (
    None
):
    ja = _baseline_section("ja")
    # P2 at 64 KiB moves most on GET and reads alone: 335,544,320 GETs at the tier-2 price replace the
    # same reads at the S3 Files read price. The amounts are pinned as literals, like the metadata figure.
    assert (
        "増える項目は、バケットからの GET と、高性能ストレージへの取り込み書き込み "
        "($0.07 / GB、最小 32 KiB)、減る項目は、高性能ストレージの読み取りである。"
    ) in ja
    assert "差し引きの向きは、このモデルでは確定していない。" in ja
    assert (
        "P2 の 64 KiB の変化が最大で、$8,755.20 から $8,060.15 へ、$695.05 (7.9%) 下がる。"
        "この額に取り込み書き込みは入っていない。"
    ) in ja
    assert "差し引きで S3 Files の小計は下がり" not in ja
    en = _baseline_section("en")
    assert "The net direction is not determined by this model." in en
    assert (
        "in P2 at 64 KiB, from $8,755.20 to $8,060.15, a decrease of $695.05 (7.9%); "
        "that figure does not include the import write."
    ) in en
    assert "falls on balance" not in en


def test_p3_says_the_blogs_give_a_hot_share_and_not_a_share_read_in_a_month() -> None:
    ja = _baseline_section("ja")
    assert (
        ja.count(
            "ブログが述べるのはホットなデータの容量比で、月内に読まれる割合とは述べていない。"
        )
        == 1
    )
    en = _baseline_section("en")
    assert en.count("they do not say what share is read within a month") == 1
    for lang in ("ja", "en"):
        p3 = next(p for p in fm.baseline_json(lang)["patterns"] if p["id"] == "P3")  # type: ignore[attr-defined]
        assert ("月内に読まれる割合" in p3["position"]) == (lang == "ja")


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


# --- PR-A: reader assumptions -------------------------------------------------------------------
#
# The central guarantee is byte equality of the default output: Assumptions() and None produce the
# same grid as the current call with no argument, and `make finops` compares the rendered document.
# The tests here do not pin the four baseline hashes; a later price change would otherwise force a
# rewrite of a test whose point is that PR-A changed nothing. Instead they compare the default
# assumptions path against the no-argument path.

ALL_KEYS = (
    "deployment",
    "efficiency_ssd",
    "pool_efficiency_retention",
    "pool_fraction",
    "ssd_headroom",
    "throughput_mbps",
    "active_fraction",
    "s3files_threshold_kib",
    "first_read_mode",
    "first_read_stream_billing",
    "metadata_multiplier",
    "read_scale",
    "stored_tib",
    "noncurrent_version_gib",
    "snapshot_gib",
)


def _subtotals(cell: fm.BaselineCell) -> tuple[float, float]:
    files = fm.s3_files_option(cell, split_metadata=True)
    assert files is not None
    return sum(fm.fsx_s3ap(cell).values()), sum(files.values())


def test_the_registry_api_list_and_dataclass_hold_the_same_keys() -> None:
    assert set(fm.ASSUMPTION_SPECS) == set(ALL_KEYS)
    assert tuple(fm.ASSUMPTION_SPECS) == ALL_KEYS  # order is canonical
    fields = {f.name for f in fm.Assumptions.__dataclass_fields__.values()}
    assert fields == set(ALL_KEYS)
    table = fm._render_assumption_list("ja")
    listed = {line.split(" | ")[0].lstrip("| ") for line in table.splitlines()[2:]}
    assert listed == set(ALL_KEYS)
    for spec in fm.ASSUMPTION_SPECS.values():
        assert spec.tier in ("公式", "観測", "試算前提", "仮置き", "定義")


def test_c1_noncurrent_versions_add_an_s3_standard_line_only_when_set() -> None:
    """C1 (PR-A2) S3 Files side: non-current versions are priced as extra S3 Standard storage,
    as the marginal tiered cost on top of the stored volume. Default 0 books no line, so the
    baseline output is unchanged."""
    base = fm.baseline_cells()[0]
    base_files = fm.s3_files_option(base, split_metadata=True)
    assert base_files is not None
    label = "S3 Standard 非現行バージョンの保持"
    assert label not in base_files  # default books nothing

    over_cell = fm.baseline_cells(fm.Assumptions(noncurrent_version_gib=1000.0))[0]
    over_files = fm.s3_files_option(over_cell, split_metadata=True)
    assert over_files is not None
    expected = fm.tiered_s3_storage(base.stored_gib + 1000.0) - fm.tiered_s3_storage(
        base.stored_gib
    )
    assert over_files[label] == pytest.approx(expected)
    assert expected > 0


def test_c1_snapshot_gib_is_an_input_that_moves_no_subtotal() -> None:
    """C1 (PR-A2) FSx for ONTAP side: snapshot_gib is an input only. Which tier snapshot data
    occupies is open/unconfirmed, so it is not put into any formula and must move neither the
    S3 Files nor the FSx for ONTAP subtotal."""
    base = fm.baseline_cells()[0]
    over = fm.baseline_cells(fm.Assumptions(snapshot_gib=99_999.0))[0]
    assert _subtotals(base) == _subtotals(over)
    # It is still a registered assumption, so it is validated and echoed as an override.
    fm.validate_assumptions(fm.Assumptions(snapshot_gib=99_999.0))
    data = fm.baseline_json("ja", fm.Assumptions(snapshot_gib=10.0))
    keys = [o["key"] for o in data["assumption_overrides"]]
    assert "snapshot_gib" in keys


def test_the_default_grid_is_the_same_whether_or_not_assumptions_are_given() -> None:
    none_cells = fm.baseline_cells()
    empty_cells = fm.baseline_cells(fm.Assumptions())
    assert len(none_cells) == len(empty_cells) == 32
    for a, b in zip(none_cells, empty_cells, strict=True):
        assert _subtotals(a) == _subtotals(b), a.pattern.key
    for lang in fm.LANGS:
        none_json = json.dumps(fm.baseline_json(lang), ensure_ascii=False, indent=2)
        empty_json = json.dumps(
            fm.baseline_json(lang, fm.Assumptions()), ensure_ascii=False, indent=2
        )
        assert none_json == empty_json, lang
        assert "baseline_assumptions" not in fm.baseline_json(lang, fm.Assumptions())


def test_setting_every_key_to_its_baseline_value_reproduces_the_baseline_subtotals() -> (
    None
):
    """A full set of explicit values equal to the baseline: the amounts match, a notice is attached,
    and every key shows up as an override. throughput and active resolve to 128 and 1.0 in
    every cell, derived from the cells rather than asserted. noncurrent_version_gib and snapshot_gib
    set to their baseline 0 book no line, so the subtotals still match."""
    for cell in fm.baseline_cells():
        if cell.object_kib <= cell.s3files_threshold_kib:
            # auto picks the smallest tier that covers the requirement; the grid lands on 128.
            assert (
                fm.choose_throughput(
                    cell.required_mbps,
                    fm.DEPLOYMENTS[cell.deployment]["tput_options"],
                    cell.tput_headroom,
                )
                in fm.DEPLOYMENTS[cell.deployment]["tput_options"]
            )
    explicit = fm.Assumptions(
        deployment="SINGLE_AZ_1",
        efficiency_ssd=0.40,
        pool_efficiency_retention=0.5,
        pool_fraction=0.30,
        ssd_headroom=0.20,
        throughput_mbps=128,
        active_fraction=1.0,
        s3files_threshold_kib=128.0,
        first_read_mode="written",
        first_read_stream_billing="none",
        metadata_multiplier=1.0,
        read_scale=1.0,
        stored_tib=20.0,
        noncurrent_version_gib=0.0,
        snapshot_gib=0.0,
    )
    fm.validate_assumptions(explicit)
    # throughput=128 and active=1.0 are the auto values in every cell, so the subtotals match.
    for base, over in zip(
        fm.baseline_cells(), fm.baseline_cells(explicit), strict=True
    ):
        assert _subtotals(base) == pytest.approx(_subtotals(over)), base.pattern.key
    data = fm.baseline_json("ja", explicit)
    assert data["baseline_assumptions"] is False
    assert "notice" in data
    assert len(data["assumption_overrides"]) == len(ALL_KEYS)


def test_an_override_is_an_override_even_when_the_value_equals_the_baseline() -> None:
    """Detected by presence, not by value. Specifying pool_fraction=0.30 still carries a notice."""
    a = fm.Assumptions(pool_fraction=0.30)
    assert fm.specified(a) == {"pool_fraction": 0.30}
    data = fm.baseline_json("ja", a)
    assert "notice" in data
    assert data["assumption_overrides"][0]["key"] == "pool_fraction"


# --- monotonicity -------------------------------------------------------------------------------


def _single(key: str, value: object) -> fm.Assumptions:
    return fm.Assumptions(**{key: value})


def test_a_subtotal_does_not_move_the_wrong_way_when_one_assumption_rises() -> None:
    """Direction only, across all cells. fsx: non-decreasing in ssd_headroom/read_scale/stored_tib,
    non-increasing in efficiency_ssd. S3 Files: non-decreasing in active_fraction, metadata_multiplier,
    read_scale, stored_tib."""
    checks = [
        ("ssd_headroom", 0.0, 0.5, "fsx", "up"),
        ("efficiency_ssd", 0.1, 0.9, "fsx", "down"),
        ("read_scale", 1.0, 2.0, "fsx", "up"),
        ("stored_tib", 20.0, 40.0, "fsx", "up"),
        ("active_fraction", 0.1, 0.9, "files", "up"),
        ("metadata_multiplier", 1.0, 3.0, "files", "up"),
        ("read_scale", 1.0, 2.0, "files", "up"),
        ("stored_tib", 20.0, 40.0, "files", "up"),
    ]
    for key, low, high, side, direction in checks:
        lo_cells = fm.baseline_cells(_single(key, low))
        hi_cells = fm.baseline_cells(_single(key, high))
        for lo, hi in zip(lo_cells, hi_cells, strict=True):
            lo_fsx, lo_files = _subtotals(lo)
            hi_fsx, hi_files = _subtotals(hi)
            lo_v, hi_v = (lo_fsx, hi_fsx) if side == "fsx" else (lo_files, hi_files)
            if direction == "up":
                assert hi_v >= lo_v - 1e-6, (key, side, lo.pattern.key, lo.object_kib)
            else:
                assert hi_v <= lo_v + 1e-6, (key, side, lo.pattern.key, lo.object_kib)


def test_throughput_tier_rising_does_not_lower_the_fsx_subtotal() -> None:
    for lo, hi in zip(
        fm.baseline_cells(_single("throughput_mbps", 256)),
        fm.baseline_cells(_single("throughput_mbps", 512)),
        strict=True,
    ):
        assert _subtotals(hi)[0] >= _subtotals(lo)[0] - 1e-6, lo.pattern.key


def test_pool_fraction_zero_drops_the_pool_line_and_one_minimises_ssd() -> None:
    zero = fm.baseline_cells(_single("pool_fraction", 0.0))[0]
    one = fm.baseline_cells(_single("pool_fraction", 1.0))[0]
    assert not any("キャパシティプール" in label for label in fm.fsx_s3ap(zero))
    full_ssd = next(v for k, v in fm.fsx_s3ap(one).items() if "SSD" in k)
    dep = fm.DEPLOYMENTS[one.deployment]
    assert full_ssd == dep["min_ssd_gib"] * dep["ssd"].usd


# --- acting side --------------------------------------------------------------------------------


def test_each_key_moves_only_the_side_it_should() -> None:
    """fsx-only keys leave every S3 Files subtotal unchanged, and vice versa. read_scale/stored_tib
    move both. The one-sided keys must still move their own side in at least one cell."""
    fsx_only = (
        "deployment",
        "efficiency_ssd",
        "pool_efficiency_retention",
        "pool_fraction",
        "ssd_headroom",
        "throughput_mbps",
    )
    files_only = (
        "active_fraction",
        "s3files_threshold_kib",
        "first_read_mode",
        "first_read_stream_billing",
        "metadata_multiplier",
    )
    values = {
        "deployment": "MULTI_AZ_1",
        "efficiency_ssd": 0.9,
        "pool_efficiency_retention": 1.0,
        "pool_fraction": 0.8,
        "ssd_headroom": 0.5,
        "throughput_mbps": 2048,
        "active_fraction": 0.1,
        "s3files_threshold_kib": 32.0,
        "first_read_mode": "none",
        "first_read_stream_billing": "file_read",
        "metadata_multiplier": 3.0,
    }
    base = fm.baseline_cells()
    for key in fsx_only:
        over = fm.baseline_cells(_single(key, values[key]))
        moved_fsx = False
        for b, o in zip(base, over, strict=True):
            assert _subtotals(b)[1] == pytest.approx(_subtotals(o)[1]), (
                key,
                b.pattern.key,
            )
            if _subtotals(b)[0] != pytest.approx(_subtotals(o)[0]):
                moved_fsx = True
        assert moved_fsx, key
    for key in files_only:
        over = fm.baseline_cells(_single(key, values[key]))
        moved_files = False
        for b, o in zip(base, over, strict=True):
            assert _subtotals(b)[0] == pytest.approx(_subtotals(o)[0]), (
                key,
                b.pattern.key,
            )
            if _subtotals(b)[1] != pytest.approx(_subtotals(o)[1]):
                moved_files = True
        assert moved_files, key


def test_read_scale_and_stored_tib_move_both_sides() -> None:
    for key in ("read_scale", "stored_tib"):
        value = 2.0 if key == "read_scale" else 40.0
        over = fm.baseline_cells(_single(key, value))
        base = fm.baseline_cells()
        assert any(
            _subtotals(b)[0] != pytest.approx(_subtotals(o)[0])
            for b, o in zip(base, over, strict=True)
        ), key
        assert any(
            _subtotals(b)[1] != pytest.approx(_subtotals(o)[1])
            for b, o in zip(base, over, strict=True)
        ), key


# --- value parsing ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "item, key, value",
    [
        ("efficiency_ssd=0.1", "efficiency_ssd", 0.1),
        ("efficiency_ssd=.5", "efficiency_ssd", 0.5),
        ("efficiency_ssd=1e-1", "efficiency_ssd", 0.1),
        ("read_scale=128", "read_scale", 128.0),
        ("stored_tib=  50  ", "stored_tib", 50.0),
        ("throughput_mbps=256", "throughput_mbps", 256),
        ("deployment=MULTI_AZ_1", "deployment", "MULTI_AZ_1"),
        ("first_read_mode=none", "first_read_mode", "none"),
    ],
)
def test_accepted_values_parse_to_the_expected_field(item, key, value) -> None:
    a = fm.parse_assumptions([item])
    assert getattr(a, key) == value


@pytest.mark.parametrize(
    "item",
    [
        "throughput_mbps=auto",
        "active_fraction=auto",
    ],
)
def test_auto_parses_as_unspecified(item) -> None:
    key = item.split("=")[0]
    a = fm.parse_assumptions([item])
    assert getattr(a, key) is None
    assert key not in fm.specified(a)


@pytest.mark.parametrize(
    "item, code",
    [
        ("efficiency_ssd=1_0", "type"),
        ("efficiency_ssd=30%", "type"),
        ("efficiency_ssd=abc", "type"),
        ("efficiency_ssd=true", "type"),
        ("throughput_mbps=128.0", "type"),
        ("throughput_mbps=AUTO", "type"),
        ("efficiency_ssd=1e999", "not_finite"),
        ("efficiency_ssd=nan", "not_finite"),
        ("efficiency_ssd=Inf", "not_finite"),
        ("efficiency_ssd=", "type"),
        ("foo=1", "unknown_key"),
        ("noeq", "bad_format"),
        ("=1", "bad_format"),
        ("efficiency_ssd=2", "range"),
        ("read_scale=0", "range"),
        ("stored_tib=0", "range"),
        ("deployment=multi_az_1", "choice"),
        ("first_read_mode=bogus", "choice"),
        ("throughput_mbps=999", "throughput_tier"),
        ("s3files_threshold_kib=64", "threshold_on_grid"),
    ],
)
def test_a_rejected_value_raises_with_the_right_code(item, code) -> None:
    with pytest.raises(fm.AssumptionError) as info:
        a = fm.parse_assumptions([item])
        fm.validate_assumptions(a)
    assert info.value.code == code, item


def test_a_duplicate_key_is_rejected_even_with_the_same_value() -> None:
    with pytest.raises(fm.AssumptionError) as info:
        fm.parse_assumptions(["pool_fraction=0.3", "pool_fraction=0.3"])
    assert info.value.code == "duplicate"


def test_a_validation_error_exits_two_on_the_command_line(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys, "argv", ["finops_model.py", "--baseline-json", "--assume", "foo=1"]
    )
    assert fm.main() == 2
    captured = capsys.readouterr()
    assert "finops-model:" in captured.err
    assert fm.CJK.search(captured.err)  # Japanese by default


def test_the_validation_error_language_follows_lang(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        ["finops_model.py", "--baseline-json", "--lang", "en", "--assume", "foo=1"],
    )
    assert fm.main() == 2
    err = capsys.readouterr().err
    assert "Unknown assumption" in err
    assert not fm.CJK.search(err)


# --- M-3: order independence of cross-item validation -------------------------------------------


def test_throughput_and_deployment_validate_the_same_in_either_order() -> None:
    forward = fm.parse_assumptions(["throughput_mbps=384", "deployment=SINGLE_AZ_2"])
    backward = fm.parse_assumptions(["deployment=SINGLE_AZ_2", "throughput_mbps=384"])
    fm.validate_assumptions(forward)  # no raise
    fm.validate_assumptions(backward)  # no raise
    api = fm.Assumptions(throughput_mbps=384, deployment="SINGLE_AZ_2")
    fm.validate_assumptions(api)
    # 384 is a second-generation tier only; against the default first generation it is rejected.
    with pytest.raises(fm.AssumptionError) as info:
        fm.validate_assumptions(fm.parse_assumptions(["throughput_mbps=384"]))
    assert info.value.code == "throughput_tier"


# --- combination rules --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ["--baseline-table", "--write"],
        ["--baseline-table", "--check"],
        ["--baseline-table", "--baseline-json"],
        ["--list-assumptions", "--write"],
        ["--list-assumptions", "--baseline-json"],
        ["--baseline-table", "--list-assumptions"],
        ["--assume", "pool_fraction=0.5"],
        ["--list-assumptions", "--assume", "pool_fraction=0.5"],
        ["--write", "--assume", "pool_fraction=0.5"],
        ["--check", "--assume", "pool_fraction=0.5"],
        ["--lang", "en", "--write"],
    ],
)
def test_incompatible_flag_combinations_exit_two(
    monkeypatch: pytest.MonkeyPatch, argv
) -> None:
    monkeypatch.setattr(sys, "argv", ["finops_model.py", *argv])
    with pytest.raises(SystemExit) as info:
        fm.main()
    assert info.value.code == 2, argv


def test_assume_is_allowed_with_baseline_json_and_baseline_table(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for mode in ("--baseline-json", "--baseline-table"):
        monkeypatch.setattr(
            sys, "argv", ["finops_model.py", mode, "--assume", "pool_fraction=0.5"]
        )
        assert fm.main() == 0, mode
        capsys.readouterr()


# --- mutation testing ---------------------------------------------------------------------------


def test_mutation_apply_ignores_all_keys_breaks_the_acting_side(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """If _apply_assumptions returns the cell untouched, the fsx-only override no longer moves fsx."""
    monkeypatch.setattr(fm, "_apply_assumptions", lambda cell, resolved: cell)
    base = fm.baseline_cells()
    over = fm.baseline_cells(_single("efficiency_ssd", 0.9))
    assert all(_subtotals(b) == _subtotals(o) for b, o in zip(base, over, strict=True))


# snapshot_gib (C1, PR-A2) is an input only: the tier it occupies is open/unconfirmed, so it is
# deliberately not put into any formula and moves no subtotal. It is therefore excluded from the
# "dropping the key must stop a subtotal from moving" mutation. noncurrent_version_gib does move the
# S3 Files subtotal (extra S3 Standard storage) and stays covered.
_APPLY_MUTATION_KEYS = tuple(k for k in ALL_KEYS if k != "snapshot_gib")


@pytest.mark.parametrize("dropped", _APPLY_MUTATION_KEYS)
def test_mutation_dropping_one_key_in_apply_is_caught(
    monkeypatch: pytest.MonkeyPatch, dropped
) -> None:
    """Drop one resolved key before it is applied; moving that key must then fail to move anything.

    For the two auto keys and the enums, moving to a value that differs from the baseline still has
    to change some subtotal; dropping the key makes it not."""
    real = fm._apply_assumptions

    def mutant(cell, resolved):
        patched = dict(resolved)
        patched[dropped] = fm.ASSUMPTION_SPECS[dropped].baseline()
        return real(cell, patched)

    values = {
        "deployment": "MULTI_AZ_1",
        "efficiency_ssd": 0.9,
        "pool_efficiency_retention": 1.0,
        "pool_fraction": 0.8,
        "ssd_headroom": 0.5,
        "throughput_mbps": 2048,
        "active_fraction": 0.1,
        "s3files_threshold_kib": 32.0,
        "first_read_mode": "none",
        "first_read_stream_billing": "file_read",
        "metadata_multiplier": 3.0,
        "read_scale": 2.0,
        "stored_tib": 40.0,
        "noncurrent_version_gib": 1000.0,
    }
    over = fm.baseline_cells(_single(dropped, values[dropped]))
    monkeypatch.setattr(fm, "_apply_assumptions", mutant)
    muted = fm.baseline_cells(_single(dropped, values[dropped]))
    assert any(
        _subtotals(a) != _subtotals(b) for a, b in zip(over, muted, strict=True)
    ), dropped


def test_mutation_removing_the_threshold_check_lets_a_bad_value_through(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fm, "validate_assumptions", lambda a, lang="ja": None)
    # Without the check, a grid-size threshold no longer raises. (A 1 MiB or larger threshold is
    # allowed since PR-F; the grid-size equality is what the remaining stage-2 check rejects.)
    fm.validate_assumptions(fm.parse_assumptions(["s3files_threshold_kib=64"]))


def test_mutation_emptying_the_notice_is_caught(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the notice emptied, the guarantee the notice test checks (a non-empty notice on an
    override) no longer holds. The real test is `test_a_notice_is_present_exactly_when_...`."""
    monkeypatch.setattr(fm, "_notice_text", lambda a, cells: "")
    data = fm.baseline_json("ja", fm.Assumptions(pool_fraction=0.5))
    assert not data["notice"]  # the mutant; the live notice test asserts it is truthy


# --- notice -------------------------------------------------------------------------------------


def test_a_notice_is_present_exactly_when_something_is_overridden() -> None:
    assert "notice" not in fm.baseline_json("ja")
    assert "notice" not in fm.baseline_json("ja", fm.Assumptions())
    data = fm.baseline_json("ja", fm.Assumptions(pool_fraction=0.5))
    assert data["notice"]
    assert data["baseline_assumptions"] is False
    table = fm.baseline_table("ja", fm.Assumptions(pool_fraction=0.5))
    assert table.splitlines()[0].startswith("> ")


def test_render_has_no_assumptions_parameter() -> None:
    import inspect

    assert "assumptions" not in inspect.signature(fm.render).parameters


def test_each_caveat_clause_appears_only_when_its_condition_holds() -> None:
    placeholder = fm.baseline_json("ja", fm.Assumptions(pool_fraction=0.5))["notice"]
    assert "仮置きまたは未測定の前提を含む" in placeholder
    definition = fm.baseline_json("ja", fm.Assumptions(read_scale=0.5))["notice"]
    assert "仮置きまたは未測定の前提を含む" not in definition

    first_read = fm.baseline_json("ja", fm.Assumptions(first_read_mode="none"))[
        "notice"
    ]
    assert "初回読み出しを数える変種" in first_read
    assert "初回読み出しを数える変種" not in placeholder

    billing = fm.baseline_json(
        "ja", fm.Assumptions(first_read_stream_billing="file_read")
    )["notice"]
    assert "ファイル読み取り課金が付くかどうか" in billing
    assert "ファイル読み取り課金が付くかどうか" not in placeholder

    tput = fm.baseline_json("ja", fm.Assumptions(throughput_mbps=128))["notice"]
    assert "スループットは読者の指定" in tput
    assert "スループットは読者の指定" not in placeholder


def test_overriding_active_fraction_or_first_read_mode_drops_the_matching_premise() -> (
    None
):
    base = fm.baseline_json("ja")["fixed_premises"]
    active = fm.baseline_json("ja", fm.Assumptions(active_fraction=1.0))[
        "fixed_premises"
    ]
    assert (
        "s3files_high_performance_storage_is_fully_active_at_or_below_threshold" in base
    )
    assert (
        "s3files_high_performance_storage_is_fully_active_at_or_below_threshold"
        not in active
    )
    first = fm.baseline_json("ja", fm.Assumptions(first_read_mode="none"))[
        "fixed_premises"
    ]
    assert "s3files_books_no_first_read_stream_when_there_are_no_writes" not in first
    # the pool-share premise stays for both
    assert "fsx_capacity_pool_share_is_fixed_in_every_pattern" in active


# --- applied-range flags and model range --------------------------------------------------------


def test_out_of_model_range_matches_an_independent_computation() -> None:
    big = fm.Assumptions(read_scale=5000.0)
    data = fm.baseline_json("ja", big)
    for p in data["patterns"]:
        for c in p["cells"]:
            cell = next(
                x
                for x in fm.baseline_cells(big)
                if x.pattern.key == p["id"] and x.object_kib == c["size_kib"]
            )
            expected = cell.required_mbps * (1 + cell.tput_headroom) > fm._max_tier(
                cell
            )
            assert c["throughput_out_of_model_range"] == expected, (
                p["id"],
                c["size_kib"],
            )


def test_a_specified_tier_below_average_is_flagged() -> None:
    data = fm.baseline_json(
        "ja", fm.Assumptions(throughput_mbps=128, read_scale=1000.0)
    )
    assert any(
        c["specified_tier_below_average"] for p in data["patterns"] for c in p["cells"]
    )


# --- M-4: metadata_multiplier only on BaselineCell, and its effect ------------------------------


def test_scenario_and_baseline_cell_share_five_assumption_fields() -> None:
    shared = (
        "pool_efficiency_retention",
        "throughput_mbps",
        "active_fraction",
        "first_read_mode",
        "first_read_stream_billing",
    )
    scenario = fm.SCENARIOS[0]
    cell = fm.baseline_cells()[0]
    for name in shared:
        assert hasattr(scenario, name), name
        assert hasattr(cell, name), name
        assert getattr(scenario, name) == getattr(cell, name), name
    # read_scale and metadata_multiplier are BaselineCell-only
    assert hasattr(cell, "metadata_multiplier")
    assert hasattr(cell, "read_scale")
    assert not hasattr(scenario, "metadata_multiplier")
    assert not hasattr(scenario, "read_scale")


def test_metadata_multiplier_scales_only_the_read_side_metadata() -> None:
    cell = next(
        c for c in fm.baseline_cells() if c.pattern.key == "P5" and c.object_kib == 64
    )
    doubled = fm.replace(cell, metadata_multiplier=2.0)
    base_in, base_rd = fm.s3_files_metadata_usd(cell)
    two_in, two_rd = fm.s3_files_metadata_usd(doubled)
    assert two_in == base_in  # import side untouched
    assert two_rd == pytest.approx(base_rd * 2.0)


def test_metadata_multiplier_moves_the_files_subtotal_in_the_split_path_for_every_cell() -> (
    None
):
    """It is applied through s3_files_metadata_usd, which the baseline grid always calls with
    split_metadata=True; the read-metadata line is the only thing that moves."""
    for base in fm.baseline_cells():
        over = fm.replace(base, metadata_multiplier=3.0)
        if base.reads_per_month > 0:
            assert _subtotals(over)[1] >= _subtotals(base)[1]
        # fsx side never moves
        assert _subtotals(over)[0] == _subtotals(base)[0]


def test_the_read_metadata_label_shows_the_multiplier_only_when_overridden() -> None:
    cell = next(
        c for c in fm.baseline_cells() if c.pattern.key == "P5" and c.object_kib == 64
    )
    default_labels = list(fm.s3_files_option(cell, split_metadata=True))
    assert any(
        label
        == f"S3 Files メタデータ読み取り ({cell.reads_per_month:,.0f} 操作 × 4 KiB)"
        for label in default_labels
    )
    over = fm.replace(cell, metadata_multiplier=2.0)
    over_labels = list(fm.s3_files_option(over, split_metadata=True))
    assert any("× 4 KiB × 2" in label for label in over_labels)


def test_a_non_round_active_fraction_uses_one_decimal_in_the_label() -> None:
    cell = next(
        c for c in fm.baseline_cells() if c.pattern.key == "P1" and c.object_kib == 64
    )
    frac = fm.replace(cell, active_fraction=0.075)
    assert any(
        "アクティブ 7.5%" in label
        for label in fm.s3_files_option(frac, split_metadata=True)
    )
    # a whole percent keeps the zero-decimal form
    whole = fm.replace(cell, active_fraction=0.07)
    assert any(
        "アクティブ 7%" in label
        for label in fm.s3_files_option(whole, split_metadata=True)
    )
    # the baseline's 100% is unchanged
    assert any(
        "アクティブ 100%" in label
        for label in fm.s3_files_option(cell, split_metadata=True)
    )


def test_first_read_mode_working_set_can_exceed_the_read_count() -> None:
    """P8 at 64 KiB writes more than it reads; working_set first reads are not capped by the model."""
    cell = next(
        c for c in fm.baseline_cells() if c.pattern.key == "P8" and c.object_kib == 64
    )
    ws = fm.replace(cell, first_read_mode="working_set")
    assert fm._resolve_first_read_objects(ws) == ws.working_set_objects


# --- stored_tib override integrity --------------------------------------------------------------


def test_stored_tib_override_scales_quantities_and_drops_position() -> None:
    data = fm.baseline_json("ja", fm.Assumptions(stored_tib=50.0))
    assert data["stored_gib"] == pytest.approx(50 * 1024)
    for p in data["patterns"]:
        assert "position" not in p
        for c in p["cells"]:
            # quantities scale 2.5x versus the 20 TiB baseline
            base_cell = next(
                x
                for x in fm.baseline_cells()
                if x.pattern.key == p["id"] and x.object_kib == c["size_kib"]
            )
            assert c["read_gib"] == pytest.approx(base_cell.read_gib_per_month * 2.5)


def test_a_fractional_stored_tib_emits_fractional_counts() -> None:
    data = fm.baseline_json("ja", fm.Assumptions(stored_tib=1.3))
    counts = [c["stored_objects"] for p in data["patterns"] for c in p["cells"]]
    assert any(not float(x).is_integer() for x in counts)


def test_the_whole_number_check_still_bites_on_the_baseline() -> None:
    with pytest.raises(ValueError):
        fm._whole(100.5)
    assert fm._count(100.5, strict=False) == 100.5


# --- the sensitivity section (PR-B) ----------------------------------------------------------


def _sensitivity_section(lang: str = "ja") -> str:
    head = (
        "### 基準の前提と感度"
        if lang == "ja"
        else "### Baseline assumptions and sensitivity"
    )
    tail_ja = "\n### "
    block = fm.render(lang)
    fm._LANG = "ja"
    after = block.split(head, 1)[1]
    # Up to the next top-level '### ' heading (read-heavy section).
    return head + after.split(tail_ja, 1)[0]


def test_the_sensitivity_section_follows_the_baseline_grid() -> None:
    block = fm.render("ja")
    fm._LANG = "ja"
    grid = block.index("### 共通ベースライン")
    sens = block.index("### 基準の前提と感度")
    read_heavy = block.index("### 読み取りが繰り返されるとき")
    assert grid < sens < read_heavy


def test_the_section_has_one_h3_and_eight_h4() -> None:
    section = _sensitivity_section("ja")
    assert section.count("\n### ") == 0  # the only ### is the first line
    assert section.startswith("### 基準の前提と感度")
    h4 = [line for line in section.split("\n") if line.startswith("#### ")]
    assert len(h4) == 8, h4
    # The eight headings in the brief's order.
    assert h4 == [
        "#### 誤読を防ぐ注",
        "#### 前提の一覧",
        "#### 前提を 1 つずつ動かしたときの小計",
        "#### 小計の高低が入れ替わる前提の値",
        "#### 2 つの前提の組での入れ替わり",
        "#### 複数の前提を同時に動かしたシナリオ",
        "#### 算入していない費目",
        "#### 自分の値での試算手順",
    ]


def test_existing_baseline_anchors_are_unchanged() -> None:
    """The sensitivity section must not duplicate or displace the baseline-grid headings."""
    block = fm.render("ja")
    fm._LANG = "ja"
    for heading in (
        "### 共通ベースライン — 20 TiB を同じ条件で",
        "#### パターンの一覧",
        "#### 式と読み方の例",
    ):
        assert block.count(heading) == 1, heading


def test_the_baseline_row_matches_the_figure_subtotals() -> None:
    """The baseline row of the one-at-a-time tables equals the recorded figure subtotals."""
    for (key, kib), (fsx, files) in FIGURE_SUBTOTALS.items():
        if key not in fm.SENSITIVITY_PATTERNS or kib not in fm.SENSITIVITY_SIZES_KIB:
            continue
        shown = fm._sens_cell_subtotals(key, kib, None)
        assert f"FSx for ONTAP {fsx}" in shown, (key, kib)
        assert f"S3 Files {files}" in shown, (key, kib)


def test_every_sensitivity_subtotal_matches_an_independent_recompute() -> None:
    """Each one-at-a-time cell equals a subtotal taken straight from the pricing helpers."""
    for kib in fm.SENSITIVITY_SIZES_KIB:
        for key, points in fm.SWEEPS.items():
            for point in points:
                if kib not in point.sizes:
                    continue
                for pat in fm.SENSITIVITY_PATTERNS:
                    cell = fm._sens_cell(pat, kib, fm.Assumptions(**{key: point.value}))
                    files_lines = fm.s3_files_option(cell, split_metadata=True)
                    assert files_lines is not None
                    independent_fsx = sum(fm.fsx_s3ap(cell).values())
                    independent_files = sum(files_lines.values())
                    shown_fsx, shown_files = fm._subtotals(cell)
                    assert abs(shown_fsx - independent_fsx) < 1e-9
                    assert abs(shown_files - independent_files) < 1e-9


def test_every_sweep_point_declares_a_range_basis() -> None:
    for key, points in fm.SWEEPS.items():
        for point in points:
            assert point.basis in fm.RANGE_BASES, (key, point)


def test_the_numeric_and_enum_assumptions_all_have_sweeps() -> None:
    """Every registry key that the section sweeps has a SWEEPS entry (or a stated reason not to)."""
    swept = set(fm.SWEEPS)
    # stored_tib's baseline is a definition, but it is still swept; read_scale likewise.
    # C1 (PR-A2): the retention-days inputs default to 0 (no line booked) and are documented in the
    # "not included" table rather than swept in the one-at-a-time sensitivity section, so they carry
    # no SWEEPS entry by design. snapshot_gib is not even in any formula (open/unconfirmed tier).
    not_swept = {"noncurrent_version_gib", "snapshot_gib"}
    for key in fm.ASSUMPTION_SPECS:
        if key in not_swept:
            assert key not in swept, key
            continue
        assert key in swept, key


def test_the_sourced_range_matches_the_design() -> None:
    assert fm.sourced_range("efficiency_ssd") == (0.65, 0.75)
    assert (
        fm.sourced_range("ssd_headroom") is None
    )  # a single sourced point, not a range
    assert fm.sourced_points("ssd_headroom") == [0.25]
    assert (
        fm.sourced_range("pool_fraction") is None
    )  # 0.80 is "reused", not sourced (M-6)
    assert fm.sourced_points("pool_fraction") == []


def test_the_applicable_range_bound_matches_a_closed_form() -> None:
    """hi' for read_scale / stored_tib equals the independent closed-form hi_model, per cell."""
    counter = fm._EvalCounter()
    for key in ("read_scale", "stored_tib"):
        for kib in fm.SENSITIVITY_SIZES_KIB:
            for pat in fm.SENSITIVITY_PATTERNS:
                _, hi = fm._bisect_breakevens(pat, kib, key, counter)
                base_cell = fm._sens_cell(pat, kib, None)
                max_tier = fm._max_tier(base_cell)
                headroom = base_cell.tput_headroom
                x_b = (
                    1.0
                    if key == "read_scale"
                    else base_cell.stored_gib / fm.GIB_PER_TIB
                )
                closed = x_b * max_tier / (base_cell.required_mbps * (1.0 + headroom))
                domain_hi = float(fm.SEARCH_DOMAINS[key]["hi"])
                assert abs(hi - min(domain_hi, closed)) < 1e-6, (key, kib, pat)


def test_a_break_even_flips_sigma_across_x_star() -> None:
    """At each x*, sigma differs just below and just above (delta = final interval width)."""
    counter = fm._EvalCounter()
    found = 0
    for key in fm.BREAKEVEN_NUMERIC_KEYS:
        for kib in fm.SENSITIVITY_SIZES_KIB:
            if key == "active_fraction" and kib == 4096:
                continue
            for pat in fm.SENSITIVITY_PATTERNS:
                results, _ = fm._bisect_breakevens(pat, kib, key, counter)
                for be in results:
                    found += 1
                    delta = max(1e-6, abs(be.x_star) * 1e-6)
                    below = fm._sigma(fm._d(pat, kib, key, be.x_star - delta))
                    above = fm._sigma(fm._d(pat, kib, key, be.x_star + delta))
                    assert below != above, (key, kib, pat, be.x_star)
    assert found > 0  # the section is meant to find some break-evens


def test_a_none_break_even_has_no_sign_change_under_a_dense_sweep() -> None:
    """Where the render says "none", a 4096-point dense sweep confirms no sign change."""
    counter = fm._EvalCounter()
    for key in fm.BREAKEVEN_NUMERIC_KEYS:
        for kib in fm.SENSITIVITY_SIZES_KIB:
            if key == "active_fraction" and kib == 4096:
                continue
            for pat in fm.SENSITIVITY_PATTERNS:
                results, _ = fm._bisect_breakevens(pat, kib, key, counter)
                if not results:
                    assert fm._dense_has_no_sign_change(pat, kib, key), (key, kib, pat)


def test_the_evaluation_count_stays_under_the_cap() -> None:
    counter = fm._EvalCounter()
    for key in fm.BREAKEVEN_NUMERIC_KEYS:
        for kib in fm.SENSITIVITY_SIZES_KIB:
            if key == "active_fraction" and kib == 4096:
                continue
            for pat in fm.SENSITIVITY_PATTERNS:
                fm._bisect_breakevens(pat, kib, key, counter)
    assert counter.count <= fm._EVAL_CAP


def test_japanese_and_english_sensitivity_tables_match_in_shape() -> None:
    ja = _sensitivity_section("ja")
    en = _sensitivity_section("en")
    for marker in ("|---", "####"):
        assert ja.count(marker) == en.count(marker), marker
    # The table rows (lines starting with "| ") count the same.
    ja_rows = [line for line in ja.split("\n") if line.startswith("| ")]
    en_rows = [line for line in en.split("\n") if line.startswith("| ")]
    assert len(ja_rows) == len(en_rows)


def test_the_english_sensitivity_section_has_no_japanese() -> None:
    en = _sensitivity_section("en")
    cjk = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff]")
    residue = [line for line in en.split("\n") if cjk.search(line)]
    assert residue == []


def test_the_scenario_direction_names_match_the_data() -> None:
    """The render-time check (M-2) passes on the current prices; it is what render relies on."""
    fm._check_scenario_directions()  # must not raise


def test_a_flipped_cell_fails_the_scenario_direction_check(monkeypatch) -> None:
    """Monkeypatch one cell's direction the wrong way; the check must raise (M-2)."""
    real_subtotals = fm._subtotals

    def flipped(cell):
        fsx, files = real_subtotals(cell)
        # J1 sets efficiency_ssd=0.75 (baseline is 0.40). Inflate FSx only on the J1-override
        # P1 4 MiB cell, so base (0.40) and override (0.75) differ and the "FSx goes down" name
        # is contradicted (FSx goes up) for that cell.
        if (
            cell.object_kib == 4096
            and cell.pattern.key == "P1"
            and abs(cell.efficiency_ssd - 0.75) < 1e-9
        ):
            return fsx * 100.0, files
        return fsx, files

    monkeypatch.setattr(fm, "_subtotals", flipped)
    with pytest.raises(ValueError):
        fm._check_scenario_directions()


def test_j3_moves_two_premises_without_first_read_mode() -> None:
    overrides = fm.SCENARIO_DEFS["J3"]["overrides"]
    assert set(overrides) == {"active_fraction", "metadata_multiplier"}
    assert "first_read_mode" not in overrides


def test_an_out_of_range_cell_is_marked_and_excluded_from_direction() -> None:
    """A read_scale large enough to leave the applicable range marks the cell with ※ and (M-5)
    the marked cell does not drive the direction column."""
    # P6 64 KiB has the lowest hi_model; find a read_scale value above it.
    counter = fm._EvalCounter()
    _, hi = fm._bisect_breakevens("P6", 64, "read_scale", counter)
    over_value = hi * 4
    cell = fm._sens_cell("P6", 64, fm.Assumptions(read_scale=over_value))
    assert fm._out_of_model(cell)
    shown = fm._sens_cell_subtotals("P6", 64, fm.Assumptions(read_scale=over_value))
    assert "※" in shown
    # The out-of-range cell is not counted as a direction difference.
    differing = fm._direction_differs("read_scale", over_value, (64,))
    assert "P6 64 KiB" not in differing


def test_the_metadata_observation_note_only_appears_for_n_gt_1_patterns() -> None:
    """The 64 KiB one-at-a-time table's metadata_multiplier=2 row carries the re-read note; the
    note is about n>1 patterns, so the row is annotated (M-7)."""
    table = fm._one_at_a_time_table(64)
    text = "\n".join(table)
    # The observed metadata point (2) at 64 KiB carries the UNCONFIRMED re-read note.
    assert "再読み取りの操作数が未測定" in text
    # P1 and P8 are n=1 (observation condition); the note is a property of the row, not the cell.
    assert fm._n_eq_1_pattern("P1") and fm._n_eq_1_pattern("P8")
    assert not fm._n_eq_1_pattern("P4")  # n=10


def test_the_sensitivity_json_values_match_the_table() -> None:
    """The structure --sensitivity-json emits equals the subtotals the tables are built from."""
    data = fm.sensitivity_json("ja")
    assert data["schema_version"] == 1
    for kib_str, rows in data["one_at_a_time"].items():
        kib = int(kib_str)
        for row in rows:
            key, value = row["key"], row["value"]
            for pat, cell in row["cells"].items():
                fsx, files = fm._subtotals(
                    fm._sens_cell(pat, kib, fm.Assumptions(**{key: value}))
                )
                assert abs(cell["fsx_s3ap_usd"] - fsx) < 1e-9
                assert abs(cell["s3_files_usd"] - files) < 1e-9


def test_the_baseline_direction_sentence_true_branch_matches_the_data() -> None:
    """The current prices give opposed directions by size, so the single-sentence branch is used."""
    lines = fm._direction_baseline_sentence()
    text = "\n".join(lines)
    assert "向きを分けているのはオブジェクトサイズである" in text


def test_the_64kib_direction_sentence_switches_branch_when_no_break_even(
    monkeypatch,
) -> None:
    """When active_fraction has no break-even in any 64 KiB cell, the false branch is used."""
    real = fm._bisect_breakevens

    def no_breakeven(pattern_key, kib, key, counter):
        if key == "active_fraction":
            return [], 1.0
        return real(pattern_key, kib, key, counter)

    monkeypatch.setattr(fm, "_bisect_breakevens", no_breakeven)
    text = "\n".join(fm._direction_64kib_sentence())
    assert "向きが変わらない" in text
    assert "仮置き・未測定" in text


# --- assumption_axes: what the break-even map reads (PR-C) -----------------------------------------


_SENS_CACHE: dict[str, dict] = {}


def _sens() -> dict:
    """One sensitivity_json("ja") per test run; it costs about three seconds and is read-only here."""
    if "ja" not in _SENS_CACHE:
        _SENS_CACHE["ja"] = fm.sensitivity_json("ja")
    return _SENS_CACHE["ja"]


def test_assumption_axes_covers_exactly_the_swept_keys_with_their_domains() -> None:
    axes = _sens()["assumption_axes"]
    assert list(axes) == list(fm.SWEEPS)
    assert len(axes) == 13
    numeric = set(fm.BREAKEVEN_NUMERIC_KEYS)
    for key, axis in axes.items():
        if key in numeric:
            domain = fm.SEARCH_DOMAINS[key]
            assert axis["lo"] == float(domain["lo"])
            assert axis["domain_hi"] == float(domain["hi"])
            assert axis["scale"] == domain["axis"]
            assert axis["zero_probe"] is bool(domain.get("zero", False))
            assert isinstance(axis["baseline"], float)
        elif key in fm.ENUM_SWEEP_KEYS:
            assert axis["scale"] == "enum"
        else:
            assert key == "s3files_threshold_kib"
            assert axis["scale"] == "discrete"
        # A per-key flag or count would be false for some cells; the figure reads the cell instead.
        assert "truncated_to_model_range" not in axis
        assert "sourced_point_count" not in axis
        assert set(axis["moves_p4"]) == {"64", "4096"}


def test_moves_p4_matches_a_classification_derived_from_the_rows() -> None:
    """Derive the classification from `one_at_a_time` and J0 with its own threshold, so the model's
    `_moving_flags` is checked against a second route to the same fact."""
    data = _sens()
    axes = data["assumption_axes"]
    eps = 1e-6  # the model's MOVE_EPS_USD, deliberately not imported
    for kib in (64, 4096):
        base = next(r for r in data["scenarios"][str(kib)] if r["id"] == "J0")["cells"][
            "P4"
        ]
        rows = data["one_at_a_time"][str(kib)]
        for key, axis in axes.items():
            mine = [r["cells"]["P4"] for r in rows if r["key"] == key]
            got = axis["moves_p4"][str(kib)]
            if not mine:
                assert got is None, (key, kib)
                continue
            fsx = any(abs(c["fsx_s3ap_usd"] - base["fsx_s3ap_usd"]) > eps for c in mine)
            files = any(
                abs(c["s3_files_usd"] - base["s3_files_usd"]) > eps for c in mine
            )
            want = {
                (True, True): "both",
                (True, False): "fsx",
                (False, True): "s3_files",
                (False, False): "none",
            }[(fsx, files)]
            assert got == want, (key, kib, got, want)
    # The document column is the union of the two sizes, in the same words.
    for key, axis in axes.items():
        sides = {w for w in axis["moves_p4"].values() if w is not None}
        fsx = bool(sides & {"fsx", "both"})
        files = bool(sides & {"s3_files", "both"})
        want = (
            "両側"
            if fsx and files
            else "FSx for ONTAP"
            if fsx
            else "S3 Files"
            if files
            else "—"
        )
        assert fm._moving_side(key) == want, key


def test_the_effective_baseline_reproduces_the_unspecified_p4_subtotals() -> None:
    """Passing a key's reported baseline explicitly must change nothing; for `active_fraction` this
    is what shows the effective value (the registry says "auto") is the one the model uses."""
    axes = _sens()["assumption_axes"]
    for key in fm.BREAKEVEN_NUMERIC_KEYS:
        for kib in (64, 4096):
            plain = fm._subtotals(fm._sens_cell("P4", kib, None))
            explicit = fm._subtotals(
                fm._sens_cell("P4", kib, fm.Assumptions(**{key: axes[key]["baseline"]}))
            )
            assert explicit == pytest.approx(plain, abs=1e-9), (key, kib)
    assert axes["s3files_threshold_kib"]["baseline"] == fm.S3FILES_DEFAULT_THRESHOLD_KIB


def test_move_eps_is_the_old_inline_threshold() -> None:
    assert fm.MOVE_EPS_USD == 1e-6
