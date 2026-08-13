"""Tests for the cost model's language handling.

The arithmetic is not tested here — `make finops` already compares every total against the committed
document, which is a stronger check than any assertion about a single figure would be. What is tested
is the part that has no such backstop: that adding a language cannot quietly change the Japanese
output, and that a partially translated model cannot produce a half-Japanese English document.
"""

from __future__ import annotations

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


# --- documents ----------------------------------------------------------------------------------


def test_each_language_resolves_to_its_own_document() -> None:
    assert fm.doc_for("ja") != fm.doc_for("en")
    for lang in fm.LANGS:
        assert fm.doc_for(lang).parts[-4:-3] == (lang,)


def test_the_japanese_document_exists() -> None:
    """The English one is created by the promotion; this script only splices into it."""
    assert fm.doc_for("ja").is_file()
