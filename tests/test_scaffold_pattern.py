"""What the scaffolder produces, and that it produces a repository that still passes.

The last two tests are the point of this file. A scaffolder is used once per pattern and never
looked at again, so the failure mode is that it quietly starts emitting something that does not
lint, does not import, or leaves a token in a heading — and the person who finds out is whoever runs
the gate afterwards, by which time the output looks like their own mistake.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import scaffold_pattern as scaffold

REPO = Path(__file__).resolve().parent.parent
TEMPLATE = REPO / "patterns" / "_template" / "skeleton"


@pytest.fixture
def fake_repo(tmp_path):
    """A repository root holding only the template, so nothing real is written to.

    Caches are excluded from the copy: running the template's own tests leaves a `__pycache__`
    behind in the working tree, and copying it in would mean the fixture's contents depend on
    whether those tests happened to run first.
    """
    shutil.copytree(
        TEMPLATE,
        tmp_path / "patterns" / "_template" / "skeleton",
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return tmp_path


# --- input validation ---------------------------------------------------------------------------


def test_an_unknown_axis_is_rejected(fake_repo) -> None:
    with pytest.raises(SystemExit) as excinfo:
        scaffold.scaffold("collectt", "example-pattern", root=fake_repo)
    assert "collect" in str(excinfo.value)


@pytest.mark.parametrize(
    "slug", ["Example", "ex", "example_pattern", "-example", "example-", "exämple"]
)
def test_a_malformed_slug_is_rejected(fake_repo, slug: str) -> None:
    with pytest.raises(SystemExit):
        scaffold.scaffold("collect", slug, root=fake_repo)


def test_an_existing_pattern_is_not_overwritten(fake_repo) -> None:
    scaffold.scaffold("collect", "example-pattern", root=fake_repo)
    with pytest.raises(SystemExit) as excinfo:
        scaffold.scaffold("collect", "example-pattern", root=fake_repo)
    assert "already exists" in str(excinfo.value)


# --- what it writes ----------------------------------------------------------------------------


def test_the_expected_files_are_created(fake_repo) -> None:
    created = scaffold.scaffold("serve", "flexcache-fanout", root=fake_repo)
    for relative in (
        "template.yaml",
        "README.md",
        "params.example.json",
        "samconfig.toml.example",
        "functions/handler.py",
        "tests/test_handler.py",
    ):
        assert (created / relative).is_file(), relative


def test_no_token_survives_anywhere(fake_repo) -> None:
    """A token left behind is the defect this script exists to prevent."""
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    for path in created.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for token in ("__PATTERN_AXIS__", "__PATTERN_SLUG__", "__PATTERN_TITLE__"):
            assert token not in text, f"{path.name} still contains {token}"


def test_the_axis_matches_the_directory_it_was_written_to(fake_repo) -> None:
    """`PATTERN_AXIS: collect` under `serve/` is the mismatch a manual copy produces."""
    created = scaffold.scaffold("serve", "flexcache-fanout", root=fake_repo)
    assert "PATTERN_AXIS: serve" in (created / "template.yaml").read_text(
        encoding="utf-8"
    )
    assert created.parent.name == "serve"


def test_the_slug_reaches_the_parameters_file(fake_repo) -> None:
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    assert '"s3ap-ingest"' in (created / "params.example.json").read_text(
        encoding="utf-8"
    )


def test_a_readable_title_is_derived(fake_repo) -> None:
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    assert (
        (created / "README.md").read_text(encoding="utf-8").startswith("# S3ap Ingest")
    )


def test_gitkeep_markers_are_not_copied_into_populated_directories(fake_repo) -> None:
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    for directory in ("functions", "tests"):
        assert not (created / directory / ".gitkeep").exists()


def test_an_empty_directory_keeps_its_marker(fake_repo) -> None:
    """`check_links.py` reports a directory that would not survive a clone, so the marker matters."""
    (fake_repo / "patterns" / "_template" / "skeleton" / "docs").mkdir(exist_ok=True)
    (fake_repo / "patterns" / "_template" / "skeleton" / "docs" / ".gitkeep").touch()
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    assert (created / "docs" / ".gitkeep").exists()


def test_caches_are_not_copied(fake_repo) -> None:
    """Running the template's tests leaves a `__pycache__`; it must not reach a new pattern."""
    cache = (
        fake_repo / "patterns" / "_template" / "skeleton" / "functions" / "__pycache__"
    )
    cache.mkdir(parents=True, exist_ok=True)
    (cache / "handler.cpython-313.pyc").write_bytes(b"\x00")
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    assert not (created / "functions" / "__pycache__").exists()


# --- the output has to actually pass -----------------------------------------------------------


def test_the_scaffolded_template_lints(fake_repo) -> None:
    if shutil.which("cfn-lint") is None:
        pytest.skip("cfn-lint not installed")
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    proc = subprocess.run(
        ["cfn-lint", "--non-zero-exit-code", "error", str(created / "template.yaml")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_scaffolded_tests_pass(fake_repo) -> None:
    """`make new-pattern` must not leave the repository red."""
    created = scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", str(created / "tests"), "-q"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr


def test_the_new_pattern_is_counted_without_editing_anything_else(fake_repo) -> None:
    """Counts are derived, so a new pattern needs no index update and no list to append to."""
    import check_derived_counts as counts

    scaffold.scaffold("collect", "s3ap-ingest", root=fake_repo)
    scaffold.scaffold("serve", "flexcache-fanout", root=fake_repo)

    original = counts.ROOT
    try:
        counts.ROOT = fake_repo
        assert counts._templates_under("patterns/collect") == 1
        assert counts._templates_under("patterns/serve") == 1
        assert counts._templates_under("patterns/pipelines") == 0

        # The total sums the three named axes, so the template's own template.yaml is never counted
        # as a pattern. Defining the claim over `patterns/` instead would pick up anything that
        # happened to sit beside the axes.
        total = next(c for c in counts.COUNT_CLAIMS if c["name"] == "patterns-total")
        assert total["count"]() == 2
    finally:
        counts.ROOT = original
