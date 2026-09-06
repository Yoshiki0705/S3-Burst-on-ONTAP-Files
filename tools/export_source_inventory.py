#!/usr/bin/env python3
"""Export every external source this repository cites, for the Hub's resource index.

WHY THIS IS A SCRIPT AND NOT A DOCUMENT

FSx-for-ONTAP-Adoption-Playbook owns the curated primary-source index (its
`block-storage-resource-map.md` is the pattern, and a file-protocol counterpart is being added). This
repository owns the measurements. If the supply were a hand-written table here it would be a second
index, and the two would drift -- which is the failure their `cross-repo-index.md` names in its first
paragraph.

So the mechanical half is generated on demand and the judgement half stays prose. What this produces:
URL, which section of their taxonomy it belongs in, every place here that cites it, and the citing
sentence. What it cannot produce is why the citation was made or which of two conflicting pages was
believed; those are in the handoff note, because they are judgements rather than extractions.

Japanese documents are the source of truth here, so `docs/en/` is skipped: including it would list
every URL twice and inflate the index with translations of the same claim.

Run:  python3 tools/export_source_inventory.py            # TSV on stdout
      python3 tools/export_source_inventory.py --format md
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import OrderedDict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

URL = re.compile(r'https?://[^\s)>\]"\'`]+')
TRAILING = ".,、。:;"

# Their taxonomy, in the order their block-storage map uses. Order matters: aws.amazon.com/blogs has
# to be tested before the bare product-page rule, or every blog lands in the wrong section.
# Not sources. A badge, a calculator, an icon package or an unresolved placeholder would each be a
# row the receiving index has to delete by hand, and deleting by hand is where a supply becomes a
# maintenance burden.
EXCLUDE = (
    "img.shields.io",
    "calculator.aws",
    "aws.amazon.com/architecture/icons",
    "<",  # placeholders such as http://<data-lif>
)

SECTIONS: tuple[tuple[str, str], ...] = (
    ("docs.aws.amazon.com", "一次情報 (AWS ユーザーガイド)"),
    # `/blogs/` rather than `aws.amazon.com/blogs`: the regional paths (`aws.amazon.com/cn/blogs/`)
    # are the same publication and were landing in the product-page section.
    ("/blogs/", "AWS ブログ"),
    ("about-aws/whats-new", "提供状況の告知 (What's New)"),
    ("repost.aws", "re:Post"),
    ("docs.netapp.com", "NetApp ドキュメント"),
    ("kb.netapp.com", "NetApp KB"),
    ("github.com", "公開 IaC / リポジトリ"),
    ("aws.amazon.com", "AWS 製品ページ / 料金"),
)


def excluded(url: str) -> bool:
    return any(needle in url for needle in EXCLUDE)


def section_of(url: str) -> str:
    for needle, name in SECTIONS:
        if needle in url:
            return name
    return "その他"


def tracked_japanese_markdown() -> list[Path]:
    names = subprocess.run(
        ["git", "ls-files", "*.md"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    return [ROOT / n for n in names if not n.startswith("docs/en/")]


def collect() -> OrderedDict[str, list[tuple[str, int, str]]]:
    found: OrderedDict[str, list[tuple[str, int, str]]] = OrderedDict()
    for path in tracked_japanese_markdown():
        rel = str(path.relative_to(ROOT))
        for lineno, line in enumerate(path.read_text(encoding="utf-8").split("\n"), 1):
            for raw in URL.findall(line):
                url = raw.rstrip(TRAILING)
                if excluded(url):
                    continue
                found.setdefault(url, []).append((rel, lineno, line.strip()))
    return found


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("tsv", "md"), default="tsv")
    args = parser.parse_args()

    found = collect()
    # An empty result means the reader broke, not that the repository cites nothing.
    if not found:
        print(
            "export_source_inventory: no URLs found; the reader is broken, not the tree",
            file=sys.stderr,
        )
        return 1

    rows = sorted(found.items(), key=lambda kv: (section_of(kv[0]), kv[0]))
    if args.format == "md":
        print("| 節 | URL | 引用箇所 | 引用している文 |")
        print("|---|---|---|---|")
        for url, occ in rows:
            where = " / ".join(f"`{f}:{i}`" for f, i, _ in occ[:3])
            if len(occ) > 3:
                where += f" ほか {len(occ) - 3} 箇所"
            sentence = occ[0][2].replace("|", "\\|")[:150]
            print(f"| {section_of(url)} | {url} | {where} | {sentence} |")
    else:
        print("section\turl\tcited_in\tciting_line")
        for url, occ in rows:
            where = ";".join(f"{f}:{i}" for f, i, _ in occ)
            print(f"{section_of(url)}\t{url}\t{where}\t{occ[0][2][:200]}")

    counts: dict[str, int] = {}
    for url, _ in rows:
        counts[section_of(url)] = counts.get(section_of(url), 0) + 1
    print(
        f"\n# {len(rows)} URL(s): "
        + ", ".join(f"{k} {v}" for k, v in sorted(counts.items())),
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
