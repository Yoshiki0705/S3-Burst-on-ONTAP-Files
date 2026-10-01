"""The TR inventory gate, verified against the ways it is meant not to fail.

This is the first gate of the TR reading procedure: before any scope judgement is written, the input
set of 18 reports is confirmed to be exactly that many and free of duplicate filenames. The design
puts this behaviour under Error Handling, where a mismatch or a duplicate must *not* raise -- the
enumeration already built is held and the problem is reported -- so these tests assert on the
returned findings rather than on an exception.

Every case uses a throwaway directory of empty `.pdf` files. The gate reads filenames and counts,
never the body of a report, so the files need no content; that keeps this test from standing in for
task 2.2, which is where the reports are actually read.
"""

from __future__ import annotations

import check_tr_inventory as inventory
import pytest


def make_pdfs(directory, names: list[str]) -> None:
    """Create one empty `.pdf` per name under `directory`."""
    for name in names:
        (directory / name).write_bytes(b"")


def eighteen_names() -> list[str]:
    """Eighteen distinct filenames -- the shape of a sound input set."""
    return [f"TR_{index:02d}.pdf" for index in range(inventory.EXPECTED_TR_COUNT)]


# --- the count gate ----------------------------------------------------------------------------


def test_exactly_eighteen_reports_pass(tmp_path) -> None:
    make_pdfs(tmp_path, eighteen_names())
    assert inventory.check(tmp_path) == []


def test_seventeen_reports_are_a_mismatch(tmp_path) -> None:
    make_pdfs(tmp_path, [f"TR_{i:02d}.pdf" for i in range(1, 18)])  # 17 files
    findings = inventory.check(tmp_path)
    assert len(findings) == 1
    assert "enumerated 17" in findings[0]
    assert f"expected {inventory.EXPECTED_TR_COUNT}" in findings[0]


def test_nineteen_reports_are_a_mismatch(tmp_path) -> None:
    make_pdfs(tmp_path, [f"TR_{i:02d}.pdf" for i in range(1, 20)])  # 19 files
    findings = inventory.check(tmp_path)
    assert len(findings) == 1
    assert "enumerated 19" in findings[0]
    assert f"expected {inventory.EXPECTED_TR_COUNT}" in findings[0]


def test_an_empty_directory_is_a_broken_reader_not_an_empty_set(tmp_path) -> None:
    """Zero reports means the enumeration stopped matching, which must read louder than a mismatch.

    A directory that moved produces exactly this, and reading it as "no reports yet" is how a moved
    input would go unnoticed.
    """
    findings = inventory.check(tmp_path)
    assert len(findings) == 1
    assert "no .pdf found" in findings[0]
    assert "stopped matching" in findings[0]


def test_an_absent_directory_is_reported_not_raised(tmp_path) -> None:
    """A missing directory holds the same meaning as an empty one, and still does not raise."""
    findings = inventory.check(tmp_path / "does-not-exist")
    assert len(findings) == 1
    assert "no .pdf found" in findings[0]


# --- the duplicate gate ------------------------------------------------------------------------


def test_a_duplicate_filename_is_reported(tmp_path) -> None:
    """Two sources listed together can collide on `name`; the gate reports the repeated filename.

    Built by hand rather than through the filesystem, because a single directory cannot hold two
    files of the same name. The identity the scope ledger records is the filename, so that is what
    the duplicate check reads.
    """
    pdfs = [tmp_path / "NFS.pdf", tmp_path / "sub" / "NFS.pdf", tmp_path / "SMB.pdf"]
    names = inventory.duplicate_names(pdfs)
    assert names == ["NFS.pdf"]


def test_no_duplicates_among_eighteen_distinct_names(tmp_path) -> None:
    make_pdfs(tmp_path, eighteen_names())
    assert inventory.duplicate_names(inventory.enumerate_pdfs(tmp_path)) == []


# --- the non-raising, state-holding contract ---------------------------------------------------


def test_a_mismatch_still_returns_the_enumeration_it_built(tmp_path) -> None:
    """The design holds the recorded result rather than discarding it to an exception.

    So even on a mismatch, the enumeration a caller would record is intact and complete.
    """
    make_pdfs(tmp_path, [f"TR_{i:02d}.pdf" for i in range(1, 20)])  # 19 files
    pdfs = inventory.enumerate_pdfs(tmp_path)
    assert len(pdfs) == 19
    # check() reports the mismatch without raising; the enumeration above is still available.
    assert inventory.check(tmp_path)


def test_a_duplicate_among_eighteen_is_reported_without_a_count_mismatch(
    tmp_path,
) -> None:
    """A duplicate is found even when the total is right, so neither check masks the other."""
    pdfs = [tmp_path / f"TR_{i:02d}.pdf" for i in range(inventory.EXPECTED_TR_COUNT)]
    pdfs.append(
        tmp_path / "nested" / "TR_00.pdf"
    )  # repeats TR_00.pdf under a subdirectory
    assert inventory.duplicate_names(pdfs) == ["TR_00.pdf"]


# --- enumeration -------------------------------------------------------------------------------


def test_enumeration_is_sorted_and_non_recursive(tmp_path) -> None:
    make_pdfs(tmp_path, ["b.pdf", "a.pdf"])
    (tmp_path / "nested").mkdir()
    (tmp_path / "nested" / "deep.pdf").write_bytes(b"")
    names = [path.name for path in inventory.enumerate_pdfs(tmp_path)]
    assert names == ["a.pdf", "b.pdf"]  # sorted, and the nested file is not included


def test_only_pdfs_are_enumerated(tmp_path) -> None:
    make_pdfs(tmp_path, ["report.pdf"])
    (tmp_path / "notes.txt").write_text("x", encoding="utf-8")
    (tmp_path / "readme.md").write_text("x", encoding="utf-8")
    names = [path.name for path in inventory.enumerate_pdfs(tmp_path)]
    assert names == ["report.pdf"]


@pytest.mark.parametrize("count", [0, 17, 18, 19])
def test_check_never_raises_regardless_of_count(tmp_path, count: int) -> None:
    make_pdfs(tmp_path, [f"TR_{i:02d}.pdf" for i in range(count)])
    # The contract is that a problem is reported, not raised; this must hold for every count.
    result = inventory.check(tmp_path)
    assert isinstance(result, list)
