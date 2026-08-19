"""The translation-drift checker, and the false positives that made an earlier version unusable.

The first version of this checker reported seven findings on a clean tree and every one was wrong:
five came from matching an English stage word as a substring (a row saying "held as a measurement"
does not contain "measured"), and two came from Japanese writing 3 億 where English writes
"300 million". A checker with that ratio gets switched off, which is worse than the gap it was built
to close, so the stage rule was removed and numbers are compared by value.

The cases below are the ones that argument rests on. `test_a_myriad_and_a_million_are_one_value` and
`test_a_bare_group_of_a_thousands_number_is_not_a_separate_value` are the two false positives,
asserted so that a future change to the pattern cannot bring them back.
"""

from __future__ import annotations

import check_translation_drift as drift
import pytest


# --- number normalisation ----------------------------------------------------------------------


def values(text: str) -> set[str]:
    """The compared half of numbers_in(); the other half is the spelling used in reports."""
    return set(drift.numbers_in(text))


def test_a_myriad_and_a_million_are_one_value() -> None:
    """3 億 and 300 million are the same number written in two numeral systems."""
    assert values("3 億オブジェクト") == values("300 million objects")
    assert values("10 万ファイル") == values("100,000 files")


def test_a_bare_group_of_a_thousands_number_is_not_a_separate_value() -> None:
    """`300,000,000` must not also yield `300`: a comma is a word boundary, and \\b\\d{3,}\\b matched it."""
    assert values("300,000,000") == values("300 million")


def test_a_changed_measurement_is_a_different_value() -> None:
    assert values("24,861 B") != values("24,681 B")


def test_small_numbers_are_ignored() -> None:
    """Below the floor a number is an ordinal far more often than a measurement."""
    assert values("1. first step, 2 of 3, n=30") == set()


def test_the_floor_is_documented_as_a_hole() -> None:
    """An object size of 64 is a real measurement this checker does not cover; assert it knowingly."""
    assert values("64 B") == set()
    assert drift.NUMBER_FLOOR == 100


def test_a_decimal_and_a_version_are_distinguished() -> None:
    assert "9.18.1P3D1" in drift.literals_in("ONTAP 9.18.1P3D1")
    assert values("p50 8 ms") == set()


# --- identifiers -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text,expected",
    [
        ("`aws:SourceVpce` only", "aws:SourceVpce"),
        ("grant `s3:PutObject`", "s3:PutObject"),
        ("in ap-northeast-1", "ap-northeast-1"),
    ],
)
def test_identifiers_are_extracted(text: str, expected: str) -> None:
    assert expected in drift.literals_in(text)


def test_a_mistyped_condition_key_is_a_different_identifier() -> None:
    assert drift.literals_in("`aws:VpcSourceIp`") != drift.literals_in(
        "`aws:VpcSourceIP`"
    )


# --- table extraction --------------------------------------------------------------------------


def test_only_table_rows_are_read(tmp_path) -> None:
    document = tmp_path / "d.md"
    document.write_text(
        "# Title\n\nProse with 12,345 in it.\n\n| a | b |\n|---|---|\n| x | 24,861 |\n",
        encoding="utf-8",
    )
    rows = [row for table in drift.tables(document) for row in table]
    assert len(rows) == 2, rows  # header and one body row; the separator is dropped
    assert not any("Prose" in row for row in rows)


def test_a_fenced_block_is_not_a_table(tmp_path) -> None:
    """A pipe inside a code fence is shell syntax, not a table cell."""
    document = tmp_path / "d.md"
    document.write_text("# T\n\n```bash\ncat x | grep 24,861\n```\n", encoding="utf-8")
    assert drift.tables(document) == []


# --- reporting ---------------------------------------------------------------------------------


def test_a_finding_names_the_spelling_that_is_in_the_file() -> None:
    """Reporting the normalised value makes a correct finding unusable.

    A reader told a table cell holds `24681` cannot find it in a file that says `24,861`. The
    comparison is by value; the report has to be by spelling.
    """
    assert drift.numbers_in("24,681 B")["24681"] == "24,681"
    assert drift.numbers_in("3 億")["300000000"] == "3 億"
    assert drift.numbers_in("300 million")["300000000"] == "300 million"


# --- copyability -------------------------------------------------------------------------------


def test_the_numeric_block_is_self_contained() -> None:
    """The block offered to the sibling repository must actually run with only `re` available.

    Asserted by executing it in an empty namespace rather than by reading it: the promise is that it
    can be lifted out, and a later edit that reaches for ROOT or another helper would break that
    silently while every other test still passed.
    """
    import re as re_module
    from pathlib import Path

    source = Path(drift.__file__).read_text(encoding="utf-8")
    start = source.index("# --- copyable block")
    end = source.index("# --- end of copyable block")
    namespace: dict[str, object] = {"re": re_module}
    exec(compile(source[start:end], "<copyable block>", "exec"), namespace)  # noqa: S102
    lifted = namespace["numbers_in"]
    assert set(lifted("3 億")) == set(lifted("300 million"))  # type: ignore[operator]
    assert lifted("24,861 B")["24861"] == "24,861"  # type: ignore[index]
