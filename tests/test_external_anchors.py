"""The citation pattern of the external-anchor check, in the forms citations actually take here.

The check compares each citation's path against the sibling's anchor contract, so a path read with
one stray character attached is reported as an untracked document. That happened with the first
citation held in a JSON string: the closing quote and comma were read as part of the path.
"""

from __future__ import annotations

import check_external_anchors as ea

URL = ea.REPO_URL + "docs/ja/domains/performance/notes/example-note.md"


def test_a_markdown_link_ends_at_the_closing_parenthesis() -> None:
    match = ea.CITATION.search(f"see [the note]({URL}#a-heading) for details")
    assert match
    assert match.group(1) == "docs/ja/domains/performance/notes/example-note.md"
    assert match.group(2) == "a-heading"


def test_a_url_in_a_json_string_ends_at_the_quote() -> None:
    match = ea.CITATION.search(f'  "reference_requirements": ["{URL}",\n')
    assert match
    assert match.group(1) == "docs/ja/domains/performance/notes/example-note.md"
    assert match.group(2) is None


def test_an_anchor_in_a_json_string_ends_at_the_quote() -> None:
    match = ea.CITATION.search(f'"{URL}#a-heading",')
    assert match
    assert match.group(2) == "a-heading"


def test_a_bare_url_in_prose_ends_at_whitespace() -> None:
    match = ea.CITATION.search(f"Read {URL} first.")
    assert match
    assert match.group(1) == "docs/ja/domains/performance/notes/example-note.md"
