"""Tests for the diagram generator that do not need the AWS icon package.

The generator reads icons from a quarterly package that is deliberately not committed, so the parts
that touch it — rendering, `--check`, export — are exercised locally by `make diagrams`. What is
tested here is everything upstream of the icons, because that is where a change breaks silently: a
spec naming a label that does not exist, or a new label added in Japanese only. Both produce a file
that opens and exports without complaint.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from xml.sax.saxutils import quoteattr

import build_diagrams as bd
import pytest

# --- the spec and the label table agree ----------------------------------------------------------


def test_every_label_a_spec_refers_to_exists_in_every_language() -> None:
    """A missing entry would otherwise surface as an empty label in the exported picture."""
    for diagram in bd.DIAGRAMS:
        keys = (
            [group.label for group in diagram.groups]
            + [node.label for node in diagram.nodes]
            + [edge.label for edge in diagram.edges if edge.label]
            + [note.label for note in diagram.notes]
        )
        for key in keys:
            for lang in bd.LANGS:
                assert bd.label(key, lang), f"{diagram.name}: {key} has no {lang} label"


def test_every_icon_a_spec_refers_to_has_a_path_and_a_size() -> None:
    for diagram in bd.DIAGRAMS:
        for node in diagram.nodes:
            assert node.icon in bd.ICONS, (
                f"{diagram.name}: no path for icon {node.icon}"
            )
            assert node.icon in bd.ICON_SIZE, (
                f"{diagram.name}: no size for icon {node.icon}"
            )


def test_only_the_two_official_icon_sizes_are_used() -> None:
    """The icon guidelines say place at the native canvas and do not resize."""
    assert set(bd.ICON_SIZE.values()) == {48, 80}


def test_edges_reference_declared_nodes() -> None:
    for diagram in bd.DIAGRAMS:
        declared = {node.cid for node in diagram.nodes}
        for edge in diagram.edges:
            assert edge.source in declared, (
                f"{diagram.name}: {edge.cid} source {edge.source}"
            )
            assert edge.target in declared, (
                f"{diagram.name}: {edge.cid} target {edge.target}"
            )


def test_cell_ids_are_unique_within_a_diagram() -> None:
    for diagram in bd.DIAGRAMS:
        ids = [
            c.cid
            for c in (*diagram.groups, *diagram.nodes, *diagram.edges, *diagram.notes)
        ]
        assert len(ids) == len(set(ids)), f"{diagram.name}: duplicate cell id"


def test_nodes_and_notes_stay_inside_the_page() -> None:
    """draw.io exports past the page edge without complaining; the crop is what gives it away."""
    for diagram in bd.DIAGRAMS:
        for node in diagram.nodes:
            size = bd.ICON_SIZE[node.icon]
            assert node.x + size <= diagram.width, (
                f"{diagram.name}: {node.cid} past the right edge"
            )
            assert node.y + size <= diagram.height, (
                f"{diagram.name}: {node.cid} past the bottom"
            )
        for box in (*diagram.groups, *diagram.notes):
            assert box.x + box.width <= diagram.width, (
                f"{diagram.name}: {box.cid} too wide"
            )
            assert box.y + box.height <= diagram.height, (
                f"{diagram.name}: {box.cid} too tall"
            )


# --- the language gate ---------------------------------------------------------------------------


def test_no_english_label_contains_japanese() -> None:
    for key, translations in bd.LABELS.items():
        assert not bd.CJK.search(translations["en"]), (
            f"{key}: English label carries Japanese"
        )


def test_a_japanese_string_left_in_the_english_column_is_refused(monkeypatch) -> None:
    monkeypatch.setitem(bd.LABELS, "probe", {"ja": "配布層", "en": "配布層"})
    assert bd.label("probe", "ja") == "配布層"
    with pytest.raises(SystemExit, match="still contains Japanese"):
        bd.label("probe", "en")


def test_a_missing_label_is_refused(monkeypatch) -> None:
    monkeypatch.setitem(bd.LABELS, "probe", {"ja": "図"})
    with pytest.raises(SystemExit, match="no en label"):
        bd.label("probe", "en")


# --- figure annotations --------------------------------------------------------------------------


def test_notes_are_items_with_headlines_rather_than_prose() -> None:
    """A figure annotation is scanned, not read, so every note carries markers and headlines."""
    for diagram in bd.DIAGRAMS:
        for note in diagram.notes:
            for lang, marker in (("ja", "※1"), ("en", "*1")):
                body = bd.label(note.label, lang)
                assert body.startswith("<b>"), f"{note.label} ({lang}) has no heading"
                assert marker in body, f"{note.label} ({lang}) is not itemized"
                assert "<b>" in body.split(marker, 1)[1], (
                    f"{note.label} ({lang}) item lacks a headline"
                )


def test_the_japanese_note_marker_is_the_japanese_one() -> None:
    """`※` is the Japanese footnote marker; `*` is the English one. They do not swap."""
    for diagram in bd.DIAGRAMS:
        for note in diagram.notes:
            assert "補足" in bd.label(note.label, "ja")
            assert "Notes" in bd.label(note.label, "en")


@pytest.mark.parametrize(
    "headline",
    [
        "plain",
        'a "quoted" headline',
        "an 'apostrophed' headline",
        """both "kinds" of 'quote'""",
        "an & ampersand",
        "a <tag> and a > bracket",
    ],
)
def test_note_markup_round_trips_through_an_xml_attribute(headline: str) -> None:
    """A value that breaks out of its attribute is the worst failure available here: draw.io drops
    that cell and every cell after it, and still reports a successful export. So the assertion is
    that the value comes back out intact, not that any particular character was escaped — the
    quoting mechanism differs by input (`quoteattr` switches delimiters rather than escaping when it
    can), and pinning the mechanism would test the standard library instead of the risk."""
    body = bd.note_body("Notes", (("*1", headline, "detail"),))
    document = f"<mxCell value={quoteattr(body)} />"
    assert ET.fromstring(document).get("value") == body
    assert headline in body


# --- file naming ---------------------------------------------------------------------------------


def test_japanese_keeps_the_bare_filename() -> None:
    """The published blog posts link the exported PNG by these paths; a rename breaks a live image."""
    overview = next(d for d in bd.DIAGRAMS if d.name == "s3burst-architecture-overview")
    assert overview.filename("ja") == "s3burst-architecture-overview.drawio"
    assert overview.filename("en") == "s3burst-architecture-overview-en.drawio"
