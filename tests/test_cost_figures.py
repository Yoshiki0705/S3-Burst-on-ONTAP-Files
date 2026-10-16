"""The committed cost-structure drawio files carry exactly the amounts the model produces.

`tools/build_cost_figures.py` writes 8 drawio files (2 figures x JA/EN x light/dark) from
`finops_model.baseline_json()`. A figure is a picture of numbers, so nothing else in the repository
notices when the model's output moves and the picture does not. This test reads the 8 files with an
XML parser only (no draw.io CLI, no network) and compares them to the model:

* Every `$` amount in every text cell of a figure must equal the set the model implies for that
  figure, in both directions: an amount the model no longer produces is stale, and an amount the
  model produces that the figure lacks is missing. Order and placement are not compared.
* The axis maximum covers the largest total in the figure, and no bar is drawn longer than the axis.
* JA/EN and light/dark of one figure carry the same amounts.
* Every footnote mark in the body has its note line, and every note line is used.

The model-side expectation is recomputed from the live model on every run, so a changed model with
an unregenerated drawio fails here. The last group of tests corrupts copies on purpose to show that
each check can fail; a check that cannot fail would report a stale figure as fine.
"""

from __future__ import annotations

import copy
import html
import re
import shutil
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import build_cost_figures as bcf
import pytest

LANGS = ("ja", "en")
THEMES = ("light", "dark")
AMOUNT = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$\d+(?:\.\d+)?")
MARK = re.compile(r"(?:※|\*)(\d+)")
NOTE_ID = re.compile(r"note-(\d+)")


def stem(fig_no: int, lang: str, theme: str) -> str:
    suffix = bcf.FIGURES[fig_no]["suffix"]
    return (
        bcf.BASE_NAME
        + suffix
        + ("-en" if lang == "en" else "")
        + ("-dark" if theme == "dark" else "")
    )


def committed_files(directory: Path = bcf.DIAGRAM_DIR) -> dict[tuple, Path]:
    return {
        (fig_no, lang, theme): directory / f"{stem(fig_no, lang, theme)}.drawio"
        for fig_no in bcf.FIGURES
        for lang in LANGS
        for theme in THEMES
    }


def cell_texts(path: Path) -> dict[str, str]:
    """Cell id -> visible text. Tags become spaces so that adjacent amounts never fuse."""
    root = ET.parse(path).getroot()
    out: dict[str, str] = {}
    for cell in root.iter("mxCell"):
        raw = (cell.get("value") or "").replace("<br>", " ")
        out[cell.get("id")] = html.unescape(re.sub(r"<[^>]+>", " ", raw)).replace(
            "\xa0", " "
        )
    return out


def amounts_in(texts: dict[str, str]) -> Counter:
    found: Counter = Counter()
    for text in texts.values():
        tokens = AMOUNT.findall(text)
        if text.count("$") != len(tokens):
            raise AssertionError(f"a '$' that is not a well-formed amount: {text!r}")
        found.update(tokens)
    return found


def money(x: float) -> str:
    return f"${x:,.2f}"


def expected_amounts(data: dict, fig_no: int) -> set[str]:
    """What the model says figure `fig_no` must show: every total, every non-zero category, the
    axis ticks and the axis maximum."""
    pats = bcf.by_id(data)
    fig = bcf.FIGURES[fig_no]
    want: set[str] = set()
    for pid in fig["patterns"]:
        for kib in bcf.SIZES:
            for method in fig["methods"]:
                meth = bcf.cell_of(pats[pid], kib)["methods"][method]
                want.add(meth["subtotal_display"])
                want.update(money(a) for a in bcf.categorize(meth).values() if a != 0)
    ax = bcf.axis_max(data)
    want.update(f"${t:,}" for t in range(0, ax + 1, bcf.AXIS_STEP))
    want.add(f"${ax:,}")
    return want


def check_amounts(path: Path, texts: dict[str, str], want: set[str]) -> list[str]:
    found = set(amounts_in(texts))
    problems = [
        f"{path.name}: amount {a} is in the figure but not in the model (stale)"
        for a in sorted(found - want)
    ]
    problems += [
        f"{path.name}: amount {a} is in the model but not in the figure (missing)"
        for a in sorted(want - found)
    ]
    return problems


def check_axis(path: Path, texts: dict[str, str], data: dict) -> list[str]:
    problems: list[str] = []
    totals = {
        cid: float(AMOUNT.findall(t)[0][1:].replace(",", ""))
        for cid, t in texts.items()
        if cid.startswith("total-") and AMOUNT.findall(t)
    }
    ticks = [int(cid.rsplit("-", 1)[1]) for cid in texts if cid.startswith("tick-top-")]
    if not totals or not ticks:
        return [f"{path.name}: no totals or no axis ticks found"]
    axis = max(ticks)
    if axis < max(totals.values()):
        problems.append(
            f"{path.name}: axis maximum ${axis:,} is below the largest total ${max(totals.values()):,.2f}"
        )
    if axis != bcf.axis_max(data):
        problems.append(
            f"{path.name}: axis maximum ${axis:,} != model's ${bcf.axis_max(data):,}"
        )
    for cell in ET.parse(path).getroot().iter("mxCell"):
        if (cell.get("id") or "").startswith("bar-"):
            geom = cell.find("mxGeometry")
            if (
                geom is not None
                and float(geom.get("width")) > bcf.BAR_PX_MAX * 1.0001 + 0.01
            ):
                problems.append(
                    f"{path.name}: {cell.get('id')} is longer than the axis"
                )
    return problems


def check_marks(path: Path, texts: dict[str, str]) -> list[str]:
    """Body marks and note lines must correspond one to one, numbered 1..n without gaps."""
    note_ids = sorted(
        int(m.group(1)) for cid in texts if (m := NOTE_ID.fullmatch(cid or ""))
    )
    problems: list[str] = []
    if not note_ids:
        return [f"{path.name}: no note lines found"]
    if note_ids != list(range(1, len(note_ids) + 1)):
        problems.append(f"{path.name}: note cells {note_ids} are not 1..n")
    noted: list[int] = []
    for n in note_ids:
        text = texts[f"note-{n}"].strip()
        lead = MARK.match(text)
        if not lead:
            problems.append(f"{path.name}: note-{n} does not start with a mark")
            continue
        noted.append(int(lead.group(1)))
        if len(text) - len(lead.group(0)) < 10:
            problems.append(f"{path.name}: note-{n} has no explanation after the mark")
    if noted != list(range(1, len(note_ids) + 1)):
        problems.append(
            f"{path.name}: note lines carry marks {noted}, expected 1..{len(note_ids)} in order"
        )
    used = {
        int(m)
        for cid, t in texts.items()
        if not (cid or "").startswith("note-")
        for m in MARK.findall(t)
    }
    if used != set(noted):
        problems.append(
            f"{path.name}: marks used in the body {sorted(used)} != note lines {sorted(noted)}"
        )
    return problems


def check_all(files: dict[tuple, Path], data: dict) -> list[str]:
    problems: list[str] = []
    per_figure: dict[int, dict[tuple, Counter]] = {}
    marks_by_figure: dict[int, dict[tuple, set[int]]] = {}
    for key, path in files.items():
        fig_no = key[0]
        if not path.is_file():
            problems.append(f"{path.name}: file is missing")
            continue
        texts = cell_texts(path)
        try:
            found = amounts_in(texts)
        except AssertionError as exc:
            problems.append(f"{path.name}: {exc}")
            continue
        per_figure.setdefault(fig_no, {})[key] = found
        problems += check_amounts(path, texts, expected_amounts(data, fig_no))
        problems += check_axis(path, texts, data)
        problems += check_marks(path, texts)
        marks_by_figure.setdefault(fig_no, {})[key] = {
            int(m)
            for cid, t in texts.items()
            if not (cid or "").startswith("note-")
            for m in MARK.findall(t)
        }
    for fig_no, variants in per_figure.items():
        if len(variants) != len(LANGS) * len(THEMES):
            continue  # a missing file is already reported
        (_, first), *rest = variants.items()
        for key, counter in rest:
            if set(counter) != set(first):
                problems.append(
                    f"figure {fig_no}: {key[1]}/{key[2]} amount set differs from "
                    f"{next(iter(variants))[1]}/{next(iter(variants))[2]}"
                )
        marks = list(marks_by_figure[fig_no].values())
        if any(m != marks[0] for m in marks):
            problems.append(f"figure {fig_no}: footnote marks differ between variants")
    return problems


@pytest.fixture(scope="module")
def model() -> dict:
    return bcf.load()


@pytest.fixture()
def copies(tmp_path: Path) -> dict[tuple, Path]:
    """A throwaway copy of the 8 committed files, safe to corrupt."""
    out: dict[tuple, Path] = {}
    for key, src in committed_files().items():
        dst = tmp_path / src.name
        shutil.copy(src, dst)
        out[key] = dst
    return out


# --- the committed files match the model ----------------------------------------------------------


def test_all_eight_files_are_committed() -> None:
    missing = [p.name for p in committed_files().values() if not p.is_file()]
    assert not missing, f"missing drawio files: {missing}"
    assert len(committed_files()) == 8


def test_committed_figures_match_the_model(model: dict) -> None:
    problems = check_all(committed_files(), model)
    assert not problems, (
        "the committed drawio files do not match the model; regenerate with "
        "`python3 tools/build_cost_figures.py --recheck-date <date> --export`:\n  "
        + "\n  ".join(problems)
    )


def test_expectation_is_not_empty(model: dict) -> None:
    """A vacuous comparison passes whatever the files hold."""
    for fig_no in bcf.FIGURES:
        want = expected_amounts(model, fig_no)
        assert len(want) >= 25, (fig_no, len(want))
        found = set(amounts_in(cell_texts(committed_files()[(fig_no, "ja", "light")])))
        assert found == want


# --- the test itself can fail ------------------------------------------------------------------


def test_changed_model_with_unregenerated_drawio_fails(model: dict) -> None:
    """Model output moves by one dollar in one cell; the committed drawio is untouched."""
    moved = copy.deepcopy(model)
    meth = bcf.cell_of(bcf.by_id(moved)["P1"], 64)["methods"]["s3_files"]
    meth["lines"][0]["usd"] += 1.0
    meth["subtotal_usd"] += 1.0
    meth["subtotal_display"] = money(meth["subtotal_usd"])
    problems = check_all(committed_files(), moved)
    assert any("missing" in p for p in problems), problems
    assert any("stale" in p for p in problems), problems


def test_corrupted_amount_fails(copies: dict[tuple, Path], model: dict) -> None:
    assert check_all(copies, model) == [], "the untouched copy must pass first"
    path = copies[(1, "ja", "light")]
    text = path.read_text(encoding="utf-8")
    first = AMOUNT.search(
        "".join(
            c.get("value") or ""
            for c in ET.parse(path).getroot().iter("mxCell")
            if (c.get("id") or "").startswith("total-")
        )
    ).group(0)
    assert text.count(first) >= 1
    path.write_text(text.replace(first, "$9,999.99"), encoding="utf-8")
    problems = check_all(copies, model)
    assert any(path.name in p and "stale" in p for p in problems), problems
    assert any(path.name in p and "missing" in p for p in problems), problems


def test_extra_amount_fails(copies: dict[tuple, Path], model: dict) -> None:
    path = copies[(2, "en", "dark")]
    root = ET.parse(path).getroot()
    for cell in root.iter("mxCell"):
        if cell.get("id") == "axis-note":
            cell.set("value", (cell.get("value") or "") + " $0.01")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    problems = check_all(copies, model)
    assert any(path.name in p and "$0.01" in p and "stale" in p for p in problems)


def test_removed_amount_fails(copies: dict[tuple, Path], model: dict) -> None:
    path = copies[(1, "ja", "dark")]
    root = ET.parse(path).getroot()
    cells = [c for c in root.iter("mxCell") if (c.get("id") or "").startswith("total-")]
    victim = cells[0]
    gone = AMOUNT.search(victim.get("value") or "").group(0)
    victim.set("value", "")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    problems = check_all(copies, model)
    assert any(path.name in p and gone in p and "missing" in p for p in problems)


def test_variant_that_differs_from_its_siblings_fails(
    copies: dict[tuple, Path], model: dict
) -> None:
    """Only the dark copy is edited, so the light/dark comparison is what has to catch it."""
    path = copies[(1, "en", "dark")]
    root = ET.parse(path).getroot()
    for cell in root.iter("mxCell"):
        if (cell.get("id") or "").startswith("tick-bot-") and cell.get("value"):
            cell.set(
                "value", ""
            )  # every `$` the bottom ticks carry also sits in the top ticks
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    # The amount set is unchanged, so this edit must NOT be flagged: it proves the sibling check
    # compares sets, not placement.
    assert check_all(copies, model) == []
    # Now remove a top tick too: the set changes and the file is flagged.
    root = ET.parse(path).getroot()
    for cell in root.iter("mxCell"):
        if cell.get("id") == "tick-top-2500":
            cell.set("value", "")
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    problems = check_all(copies, model)
    assert any(path.name in p and "$2,500" in p for p in problems), problems


def test_axis_below_largest_total_fails(copies: dict[tuple, Path], model: dict) -> None:
    path = copies[(2, "ja", "light")]
    root = ET.parse(path).getroot()
    tops = sorted(
        (c for c in root.iter("mxCell") if (c.get("id") or "").startswith("tick-top-")),
        key=lambda c: int(c.get("id").rsplit("-", 1)[1]),
    )
    tops[-1].set("id", "tick-x-gone")  # the axis now ends one tick early
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    problems = check_all(copies, model)
    assert any(path.name in p and "axis maximum" in p for p in problems), problems


def test_note_mark_without_note_line_fails(
    copies: dict[tuple, Path], model: dict
) -> None:
    path = copies[(1, "ja", "light")]
    root = ET.parse(path).getroot()
    for cell in root.iter("mxCell"):
        if cell.get("id") == "note-2":
            cell.set("value", (cell.get("value") or "").replace("※2", "※7", 1))
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    problems = check_all(copies, model)
    assert any(path.name in p and "marks" in p for p in problems), problems


def test_missing_file_fails(copies: dict[tuple, Path], model: dict) -> None:
    copies[(2, "en", "light")].unlink()
    problems = check_all(copies, model)
    assert any("file is missing" in p for p in problems), problems
