"""How much a probe string actually protects, judged from the file it points at.

A probe is a string a sibling repository asks not to be reworded silently. Whether it protects the
claim depends on the string, not on the registration: two probes with the same role and the same
target can differ entirely in what they would notice.

Two weaknesses are decidable from the text, and both are reported rather than failed -- the claim
still resolves, and calling a fragile anchor a withdrawal would misinform the other side.

    multiplicity   The string occurs more than once. Rewording one occurrence leaves the other in
                   place, so the gate stays green and nobody is warned.
    heading-only   Every occurrence is a section heading. A heading survives its section being
                   replaced with the opposite conclusion, which is the failure probes exist to
                   catch. The replacement is usually the line below it.

The two are independent, and neither is a superset. Measured against this repository: the
multiplicity rule found 2 (both figures repeated inside one measurement page), the heading-only rule
found 3 (each occurring exactly once, so invisible to the first). The 3 came from a sibling running
a criterion this repository did not have -- which is why the predicates live in one module now,
imported by the incoming and outgoing checkers, instead of being written twice.

A third kind -- a string too generic to be about the claim at all, such as a product name or a
section label -- is not decidable here. Length does not decide it either: an eight-character
measured ratio protects a great deal, and a thirteen-character product name protects nothing. That
one stays a per-line judgement.
"""

from __future__ import annotations

import re

# ATX heading, with the up-to-three leading spaces CommonMark allows.
HEADING = re.compile(r"^\s{0,3}#{1,6}\s")


def occurrences(body: str, text: str) -> int:
    """How many times the probe string appears in the file."""
    return body.count(text)


def heading_only(body: str, text: str) -> bool:
    """True when the probe string appears, and only ever on heading lines.

    出現が 1 つでも本文・表・箇条書きにあれば False。見出しの題は中身が入れ替わっても
    残るので、見出しにしか当たらない probe は主張が反対になっても発火しない。
    """
    lines = [line for line in body.splitlines() if text in line]
    return bool(lines) and all(HEADING.match(line) for line in lines)
