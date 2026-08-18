#!/usr/bin/env python3
"""Check that Tier 1 documents have the same section structure in Japanese and English.

Adapted from the sibling repository `FSx-for-ONTAP-Adoption-Playbook` (`tools/check_i18n_parity.py`).
Divergence: that repository carries eight languages and a second tier of module READMEs
discovered from `docs/ja/{playbooks,domains}/`. This repository has two languages and no module
axis, so the language list is reduced and the Tier 2 discovery pass is removed rather than kept
as a loop that matches nothing. A check that silently examines zero files is worse than no check,
because its output is indistinguishable from success — so `main()` fails when it finds nothing to
compare.

Translations drift silently: a section gets added in Japanese and the English file keeps rendering
an older story. Comparing heading *structure* (level + order + count) rather than text catches that
without requiring the translations themselves to be machine-comparable.

Tier 1 = the language hubs, plus the files listed in `docs/i18n-manifest.txt`.

A document's language is its directory, not a filename suffix. The one exception is the Japanese
hub: it is the repository-root README.md, because that is what GitHub renders on the landing page,
so `docs/ja/README.md` deliberately does not exist.

The manifest exists so that a new guide can land in Japanese first and be promoted deliberately.
Without it, either every new document blocks the commit gate until a translation exists, or the
gate has to be switched off — and a gate that is switched off stops catching the drift it was
built for.

Run:  python3 tools/check_i18n_parity.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANIFEST = ROOT / "docs" / "i18n-manifest.txt"

TIER1_LANGS = ["ja", "en"]

ATX = re.compile(r"^(#{1,6})\s+\S")
SUMMARY = re.compile(r"<summary>", re.IGNORECASE)
FENCE = re.compile(r"^\s*(?:```|~~~)")


def structure(path: Path) -> list[str]:
    """Return a structural fingerprint: heading levels and <summary> markers, in order.

    Heading *text* is intentionally ignored — it is translated. Fenced code blocks are skipped so
    that comments starting with '#' inside a shell snippet are not mistaken for headings.
    """
    fingerprint: list[str] = []
    in_fence = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = ATX.match(line)
        if match:
            fingerprint.append(f"h{len(match.group(1))}")
        elif SUMMARY.search(line):
            fingerprint.append("details")
    return fingerprint


def read_manifest() -> list[tuple[str, list[str]]]:
    """Parse docs/i18n-manifest.txt into [(subpath, [langs])].

    Format, one entry per line:  <subpath>[: lang,lang,...]
    Omitting the language list means every Tier 1 language is required.
    """
    if not MANIFEST.exists():
        return []
    entries: list[tuple[str, list[str]]] = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        stripped = line.split("#", 1)[0].strip()
        if not stripped:
            continue
        name, sep, raw_langs = stripped.partition(":")
        name = name.strip()
        if sep and raw_langs.strip():
            langs = [lang.strip() for lang in raw_langs.split(",") if lang.strip()]
            unknown = sorted(set(langs) - set(TIER1_LANGS))
            if unknown:
                raise SystemExit(
                    f"i18n-manifest.txt: unknown language(s) {unknown} for {name}"
                )
        else:
            langs = list(TIER1_LANGS)
        entries.append((name, langs))
    return entries


def hub_for(lang: str) -> Path:
    """The top-level hub for a language. Japanese is the repository-root README."""
    if lang == "ja":
        return ROOT / "README.md"
    return ROOT / "docs" / lang / "README.md"


def compare(label: str, reference: Path, others: list[tuple[str, Path]]) -> list[str]:
    errors: list[str] = []
    expected = structure(reference)
    for lang, path in others:
        if not path.exists():
            errors.append(
                f"{label}: missing {lang} translation ({path.relative_to(ROOT)})"
            )
            continue
        actual = structure(path)
        if actual == expected:
            continue
        if len(actual) != len(expected):
            errors.append(
                f"{label}: {lang} has {len(actual)} section marker(s), "
                f"reference has {len(expected)} ({path.relative_to(ROOT)})"
            )
            continue
        for index, (want, got) in enumerate(zip(expected, actual)):
            if want != got:
                errors.append(
                    f"{label}: {lang} section #{index + 1} is '{got}', "
                    f"reference has '{want}' ({path.relative_to(ROOT)})"
                )
                break
    return errors


def tier2_count() -> int:
    """How many documents under docs/ja/ are deliberately not translated.

    Reported on success so that the summary line cannot be read as coverage. "3 document groups in
    parity" is true whether the repository has three Japanese documents or thirty, and the number
    that matters when judging whether the split is still the right one is the other one.
    """
    ja_root = ROOT / "docs" / "ja"
    if not ja_root.is_dir():
        return 0
    promoted = {name for name, _ in read_manifest()}
    return sum(
        1
        for path in ja_root.rglob("*.md")
        if str(path.relative_to(ja_root).as_posix()) not in promoted
    )


def main() -> int:
    errors: list[str] = []
    checked = 0

    ja_hub = hub_for("ja")
    if ja_hub.exists():
        checked += 1
        errors += compare(
            "hub README",
            ja_hub,
            [(lang, hub_for(lang)) for lang in TIER1_LANGS if lang != "ja"],
        )
    else:
        errors.append("root README.md not found; it is the Japanese hub")

    for name, langs in read_manifest():
        reference = ROOT / "docs" / "ja" / name
        if not reference.exists():
            errors.append(
                f"docs/*/{name}: listed in i18n-manifest.txt but docs/ja/{name} is missing"
            )
            continue
        checked += 1
        others = [(lang, ROOT / "docs" / lang / name) for lang in langs if lang != "ja"]
        errors += compare(f"docs/*/{name}", reference, others)

    if not checked:
        errors.append(
            "nothing was compared; the check would report success without examining anything"
        )

    if errors:
        print(f"i18n parity failed ({len(errors)} issue(s)):", file=sys.stderr)
        for error in errors:
            print(f"  {error}", file=sys.stderr)
        return 1

    tier2 = tier2_count()
    print(
        f"i18n: {checked} document group(s) in parity, "
        f"{tier2} document(s) Japanese-only by policy (Tier 2)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
