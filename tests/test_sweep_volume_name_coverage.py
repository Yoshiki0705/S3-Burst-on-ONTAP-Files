"""Every ONTAP volume this repository creates must be attributable to the project.

`sweep_after_teardown.py` refuses to delete a resource it cannot tie to this project by name, and
an FSx backup carries only its volume's name. So a template that names a volume in a way
`PROJECT_VOLUME_NAMES` does not match produces a backup the sweep reports but will not remove --
which is how a 10 GiB `smb_vol` backup outlived its file system.

This asserts the coverage rather than the list, so adding a template with a new volume name fails
here instead of at the next teardown.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))

from sweep_after_teardown import (
    PROJECT_VOLUME_NAMES,
    attributable,
)

# `Name:` on the line, or within the few lines above `VolumeType: ONTAP`. Reading the templates as
# YAML would need a loader that understands `!Sub` and `!Ref`, so this stays textual.
VOLUME_BLOCK = re.compile(
    r"Name:\s*(?P<name>[^\n]+)\n(?:[^\n]*\n){0,6}?\s*VolumeType:\s*ONTAP",
)
SUB_LITERAL = re.compile(r'!Sub\s*"\$\{\w+\}(?P<suffix>[\w-]+)"')
REF_PARAM = re.compile(r"!Ref\s+(?P<param>\w+)")


def _parameter_default(template: str, parameter: str) -> str | None:
    """The `Default:` of a named parameter, or None when it has none."""
    block = re.search(
        rf"^  {parameter}:\n(?P<body>(?:    [^\n]*\n|\n)+)",
        template,
        re.MULTILINE,
    )
    if not block:
        return None
    default = re.search(
        r"^    Default:\s*(?P<value>[^\n]+)$", block.group("body"), re.MULTILINE
    )
    return default.group("value").strip().strip("\"'") if default else None


def _volume_names() -> list[tuple[Path, str]]:
    """Every ONTAP volume name this repository's templates can produce."""
    found: list[tuple[Path, str]] = []
    for template in sorted(REPO.glob("**/*.yaml")):
        if any(part in {".git", "node_modules"} for part in template.parts):
            continue
        text = template.read_text(encoding="utf-8")
        for match in VOLUME_BLOCK.finditer(text):
            raw = match.group("name").strip()
            if literal := SUB_LITERAL.search(raw):
                found.append((template, literal.group("suffix")))
            elif ref := REF_PARAM.search(raw):
                default = _parameter_default(text, ref.group("param"))
                if default:
                    found.append((template, default))
            elif not raw.startswith("!"):
                found.append((template, raw.strip("\"'")))
    return found


def test_the_scan_finds_volumes():
    """A scan that finds nothing is a broken reader, not a repository without volumes."""
    assert _volume_names(), "found no ONTAP volume names -- the template scan is broken"


@pytest.mark.parametrize(("template", "name"), _volume_names(), ids=lambda v: str(v))
def test_volume_name_is_attributable(template: Path, name: str):
    assert attributable(name, PROJECT_VOLUME_NAMES), (
        f"{template.relative_to(REPO)} creates a volume named {name!r}, which "
        f"PROJECT_VOLUME_NAMES does not match. A backup of it would be reported but never "
        f"deleted. Add a matching fragment to scripts/sweep_after_teardown.py."
    )
