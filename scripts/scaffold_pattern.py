#!/usr/bin/env python3
"""Copy `patterns/_template/skeleton/` into an axis and fill in the pattern's identity.

The extra `skeleton/` level exists so that the source and the destination sit at the same depth —
`patterns/_template/skeleton/` and `patterns/<axis>/<slug>/` are both three levels from the root.
That means every relative link in the template is already correct in the copy, and the link check
covers the template itself rather than only the generated pattern. Flattening it would force the
links to be wrong in one of the two places.

Why a script rather than "copy the directory and edit it": the template carries a handful of tokens
that have to agree with each other across five files, and the axis has to be one of three. Both are
easy to get almost right, and a pattern whose `PATTERN_AXIS` says `collect` while it sits under
`serve/` is the sort of thing nobody notices until a count or a tag looks wrong.

What it deliberately does not do: it does not touch anything outside the new directory. No index to
update, no count to increment, no list to append to. Pattern totals are derived from
`patterns/*/*/template.yaml` by `make counts`, so a new pattern is counted the moment its template
exists. A scaffolder that edits a shared file is a scaffolder that produces merge conflicts.

Run:  python3 scripts/scaffold_pattern.py --axis collect --slug s3ap-ingest
      make new-pattern AXIS=collect SLUG=s3ap-ingest
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "patterns" / "_template" / "skeleton"
AXES = ("collect", "serve", "pipelines")

SLUG = re.compile(r"^[a-z][a-z0-9-]{1,38}[a-z0-9]$")

# Files whose bytes are rewritten. Anything else is copied verbatim.
TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".json", ".py", ".toml", ".txt", ".example"}

# Names that would be copied but must not be: caches, and the placeholder files whose only job was
# to keep an empty directory in git.
SKIP_NAMES = {"__pycache__", ".pytest_cache", ".DS_Store"}


def title_from(slug: str) -> str:
    """`s3ap-ingest` becomes `S3ap Ingest`, which is a starting point, not an answer.

    The README asks the author to write a real title. Deriving something readable is still better
    than leaving the raw token, because a token left in a heading survives review more easily than
    an obviously provisional title does.
    """
    return " ".join(word.capitalize() for word in slug.split("-"))


def substitutions(axis: str, slug: str) -> dict[str, str]:
    return {
        "__PATTERN_AXIS__": axis,
        "__PATTERN_SLUG__": slug,
        "__PATTERN_TITLE__": title_from(slug),
    }


def scaffold(axis: str, slug: str, *, root: Path = ROOT) -> Path:
    """Create the pattern directory and return its path."""
    if axis not in AXES:
        raise SystemExit(f"--axis must be one of {', '.join(AXES)} (got {axis!r})")
    if not SLUG.match(slug):
        raise SystemExit(
            f"--slug must be lowercase letters, digits and hyphens, 3-40 characters (got {slug!r})"
        )

    template = root / "patterns" / "_template" / "skeleton"
    if not template.is_dir():
        raise SystemExit(f"template not found: {template}")

    destination = root / "patterns" / axis / slug
    if destination.exists():
        raise SystemExit(f"already exists: {destination.relative_to(root)}")

    tokens = substitutions(axis, slug)
    created: list[Path] = []

    for source in sorted(template.rglob("*")):
        if any(part in SKIP_NAMES for part in source.relative_to(template).parts):
            continue
        target = destination / source.relative_to(template)
        if source.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        # .gitkeep exists to keep an empty directory in git. Once the directory holds real files it
        # is noise, and once it holds none it should not have been copied at all.
        if source.name == ".gitkeep":
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.suffix in TEXT_SUFFIXES:
            text = source.read_text(encoding="utf-8")
            for token, value in tokens.items():
                text = text.replace(token, value)
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(source, target)
        created.append(target)

    # A directory the template kept only with .gitkeep would otherwise vanish. Recreate the marker
    # so the empty directory survives a clone, which is what check_links.py checks for.
    for directory in sorted(p for p in destination.rglob("*") if p.is_dir()):
        if not any(child.is_file() for child in directory.rglob("*")):
            (directory / ".gitkeep").touch()
            created.append(directory / ".gitkeep")

    print(f"created {destination.relative_to(root)} ({len(created)} file(s))")
    for path in created:
        print(f"  {path.relative_to(root)}")
    print(
        "\nnext:\n"
        "  1. replace the placeholder Deny policy in template.yaml with least privilege\n"
        "  2. implement functions/handler.py and keep the contract tests\n"
        "  3. fill in README.md and delete its 'still from the template' section\n"
        "  4. make all"
    )
    return destination


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--axis", required=True, help=f"one of {', '.join(AXES)}")
    parser.add_argument("--slug", required=True, help="pattern directory name")
    args = parser.parse_args()
    scaffold(args.axis, args.slug)
    return 0


if __name__ == "__main__":
    sys.exit(main())
