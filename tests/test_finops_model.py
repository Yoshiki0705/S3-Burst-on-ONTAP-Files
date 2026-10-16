"""Tests for the cost model's language handling.

The arithmetic is not tested here — `make finops` already compares every total against the committed
document, which is a stronger check than any assertion about a single figure would be. What is tested
is the part that has no such backstop: that adding a language cannot quietly change the Japanese
output, and that a partially translated model cannot produce a half-Japanese English document.
"""

from __future__ import annotations

import ast
import pathlib

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


def test_the_baseline_grid_has_twelve_cells() -> None:
    """Four object sizes crossed with three read/write patterns."""
    cells = fm.baseline_cells()
    assert len(cells) == 12
    assert len(fm.BASELINE_SIZES_KIB) == 4
    assert len(fm.BASELINE_PATTERNS) == 3


def test_every_cell_stores_the_common_20_tib() -> None:
    """The whole point of the grid is one fixed footing; a cell that drifted off it would make the
    cross-size comparison meaningless."""
    expected = fm.BASELINE_STORED_TIB * fm.GIB_PER_TIB
    for cell in fm.baseline_cells():
        assert cell.stored_gib == expected, cell.pattern


def test_size_times_count_equals_total_bytes_for_each_cell() -> None:
    """The counts are derived as volume / size, so size x count must return the volume. This is the
    check that object count is not quietly conflated with a volume figure."""
    for cell in fm.baseline_cells():
        gib_per_object = cell.object_mib / 1024
        # Stored object count x size == stored volume.
        assert cell.objects_stored * gib_per_object == pytest.approx(cell.stored_gib)
        # Written object count x size == monthly write volume.
        assert cell.objects_per_month * gib_per_object == pytest.approx(
            cell.write_gib_per_month
        )
        # Read count x size == monthly read volume.
        assert cell.reads_per_month * gib_per_object == pytest.approx(
            cell.read_gib_per_month
        )


def test_pattern_read_and_write_volumes_equal_the_declared_inputs() -> None:
    """A (read 20, write 0), B (read 20, write 1), C (read 40, write 20), in TiB per month."""
    declared = {"A": (20.0, 0.0), "B": (20.0, 1.0), "C": (40.0, 20.0)}
    for cell in fm.baseline_cells():
        read_tib, write_tib = declared[cell.pattern]
        assert cell.read_gib_per_month == pytest.approx(read_tib * fm.GIB_PER_TIB)
        assert cell.write_gib_per_month == pytest.approx(write_tib * fm.GIB_PER_TIB)


def test_write_volume_is_not_equated_with_stored_volume() -> None:
    """Design section 3.3: writing 1 TiB/month into a 20 TiB resident set replaces part of it; the
    monthly write count must stay smaller than the resident object count, never equal to it."""
    for cell in fm.baseline_cells():
        if cell.write_gib_per_month < cell.stored_gib:
            assert cell.objects_per_month < cell.objects_stored, cell.pattern


def test_the_baseline_has_no_industry_field() -> None:
    """A dedicated dataclass was chosen over reusing Scenario precisely so the grid carries no
    industry; this guards that choice against a later field creeping back in."""
    assert not hasattr(fm.BaselineCell("A", 1.0, 1.0, 1.0, 1.0), "industry")


def test_every_baseline_subtotal_is_a_major_line_item_subtotal() -> None:
    """Each total has an uncounted line item (the UNCONFIRMED capacity-pool read requests), so it
    must be labelled a 主要費目小計, never a 月額総額."""
    block = fm.render("ja")
    section = block.split("### 共通ベースライン")[1].split("\n### ")[0]
    # Twelve cells, two methods each: twenty-four subtotal rows, every one a 主要費目小計.
    assert section.count("**主要費目小計 / major-line-item subtotal**") == 24
    # No subtotal row is labelled 月額総額. The phrase appears once in the intro prose explaining
    # the distinction ("a subtotal, not a 月額総額"), so guard the table-row label, not the word.
    assert "| **月額総額" not in section


def test_the_baseline_leaves_capacity_pool_requests_unconfirmed() -> None:
    """The count per GET is not measured; the grid must say so rather than guess a number."""
    block = fm.render("ja")
    section = block.split("### 共通ベースライン")[1].split("\n### ")[0]
    assert "未確認" in section
    en = fm.render("en")
    fm.render("ja")  # restore module state
    en_section = en.split("### A common baseline")[1].split("\n### ")[0]
    assert "UNCONFIRMED" in en_section or "unconfirmed" in en_section


def test_every_generated_string_now_has_english() -> None:
    """The document is promoted only once this holds, and it has to keep holding afterwards: a new
    gap makes the script skip English rather than fail, which would freeze the English tables."""
    missing, residue = fm.translation_gaps()
    assert missing == []
    assert residue == []


# --- documents ----------------------------------------------------------------------------------


def test_each_language_resolves_to_its_own_document() -> None:
    assert fm.doc_for("ja") != fm.doc_for("en")
    for lang in fm.LANGS:
        assert fm.doc_for(lang).parts[-4:-3] == (lang,)


def test_the_japanese_document_exists() -> None:
    """The English one is created by the promotion; this script only splices into it."""
    assert fm.doc_for("ja").is_file()
