#!/usr/bin/env python3
"""Compare the AWS Interconnect - multicloud Region pairs in the docs against AWS's own page.

The Region pairs and the per-CSP lifecycle are the two facts in this repository that change without
anyone touching a file. They went stale exactly that way: Azure moved from "coming later in 2026" to
Preview with four pairs, and four separate statements -- the overview table, the "planned" table, the
selection steps and the state of the Japanese Regions -- kept asserting it was neither GA nor
Preview. Nothing in the commit gate looks at another party's page, so nothing could have caught it.

What this enforces: the pairs table is derived from
https://docs.aws.amazon.com/interconnect/latest/userguide/region-availability.html, not maintained by
hand. A row that AWS has withdrawn, a pair AWS has added, and a CSP whose lifecycle has moved are all
reported, in both languages.

**A page that could not be read is not a page with no differences.** Every way of coming back empty
-- the request failing, the page returning something that parses to zero pairs, a document whose
table cannot be found -- exits non-zero with its own message. That distinction is the point: this
check runs on a schedule, against a document AWS reorganises, and the failure mode that matters is
the one where it silently reports success forever after the page's markup changes.

Not covered: counts spelled out in prose. Japanese writes "8 ペア" and English writes "eight pairs",
and matching a number word next to a CSP name produced false positives on the rows of the table
itself. A checker that invents findings gets switched off, so the prose counts are left to the
reader. When this check reports a pair difference, search both documents for the count as well.

Run:  python3 tools/check_interconnect_regions.py [--list] [--from-file page.html]
"""

from __future__ import annotations

import argparse
import html
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent

SOURCE_URL = (
    "https://docs.aws.amazon.com/interconnect/latest/userguide/region-availability.html"
)
USER_AGENT = "s3-burst-on-ontap-files-interconnect-check"
TIMEOUT = 20.0

# The documents holding the table, and the header cell that identifies it. The header is matched
# rather than the surrounding heading so that renaming the section does not silently stop the check.
DOCUMENTS = {
    "docs/ja/multi-cloud-connectivity.md": "ライフサイクル",
    "docs/en/multi-cloud-connectivity.md": "Lifecycle",
}

# AWS's own headings, mapped to the shorter names the documents use in the table. The lifecycle rides
# on the heading -- "Microsoft Azure (Preview)" -- so it is read from there rather than guessed.
CSP_HEADINGS = {
    "google cloud": "Google Cloud",
    "microsoft azure": "Azure",
    "oracle cloud infrastructure": "OCI",
}
CSP_NAMES = tuple(CSP_HEADINGS.values())

AWS_REGION = re.compile(r"\b[a-z]{2}-[a-z]+-\d\b")
H3 = re.compile(r"<h3[^>]*>(.*?)</h3>", re.DOTALL)
LIST_ITEM = re.compile(r'<li class="listitem">\s*<p>\s*(.*?)</p>', re.DOTALL)
TAG = re.compile(r"<[^>]+>")
# An en dash separates the AWS side from the CSP side. A hyphen is accepted too, in case the page is
# ever rewritten with one.
PAIR_SEPARATOR = re.compile(r"\s[\u2013\u2014-]\s")


class Pair(NamedTuple):
    aws_region: str
    csp: str
    csp_region: str
    lifecycle: str

    def describe(self) -> str:
        return f"{self.aws_region} - {self.csp} {self.csp_region} [{self.lifecycle}]"


def _text(fragment: str) -> str:
    return " ".join(html.unescape(TAG.sub(" ", fragment)).split())


def fetch(from_file: Path | None) -> str:
    """Return the page source, or raise SystemExit naming why it could not be read."""
    if from_file is not None:
        try:
            return from_file.read_text(encoding="utf-8")
        except OSError as exc:
            raise SystemExit(
                f"interconnect-regions: cannot read {from_file}: {exc}"
            ) from exc
    request = urllib.request.Request(SOURCE_URL, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:  # noqa: S310
            return response.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SystemExit(
            f"interconnect-regions: could not retrieve {SOURCE_URL}: {exc}\n"
            "  This is a retrieval failure, not a clean result. Nothing is asserted about the "
            "documents."
        ) from exc


def parse_page(source: str) -> set[Pair]:
    """Read the pairs out of AWS's page, keyed by the CSP heading each list sits under.

    The two list shapes are both in use: Google Cloud and Azure put the CSP Region in trailing
    parentheses, OCI puts it after a colon. Anything that matches neither is left out and shows up as
    a missing pair rather than as a silently dropped row.
    """
    pairs: set[Pair] = set()
    # Walk the headings in document order and take each one's list items up to the next heading.
    marks = [(m.start(), _text(m.group(1))) for m in H3.finditer(source)]
    for index, (start, heading) in enumerate(marks):
        end = marks[index + 1][0] if index + 1 < len(marks) else len(source)
        key = heading.lower().split("(")[0].strip()
        csp = CSP_HEADINGS.get(key)
        if csp is None:
            continue
        lifecycle = "Preview" if "preview" in heading.lower() else "GA"
        for item in LIST_ITEM.finditer(source[start:end]):
            line = _text(item.group(1))
            halves = PAIR_SEPARATOR.split(line, maxsplit=1)
            if len(halves) != 2:
                continue
            aws_side, csp_side = halves
            aws_match = AWS_REGION.search(aws_side)
            if not aws_match:
                continue
            if csp_side.endswith(")"):
                csp_region = csp_side[csp_side.rfind("(") + 1 : -1].strip()
            elif ":" in csp_side:
                csp_region = csp_side.rsplit(":", 1)[1].strip()
            else:
                continue
            pairs.add(Pair(aws_match.group(0), csp, csp_region, lifecycle))
    return pairs


def parse_document(path: Path, header: str) -> set[Pair]:
    """Read the pairs out of one document's table, identified by its lifecycle column header."""
    pairs: set[Pair] = set()
    in_table = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            if in_table:
                break
            continue
        cells = [cell.strip() for cell in stripped.strip("|").split("|")]
        if not in_table:
            in_table = header in cells
            continue
        if set(stripped) <= set("|-: "):
            continue
        if len(cells) < 3:
            continue
        aws_match = AWS_REGION.search(cells[0])
        if not aws_match:
            continue
        target = cells[1]
        csp = next((name for name in CSP_NAMES if target.startswith(name)), None)
        if csp is None:
            continue
        # The Region code is the first token after the CSP name. Splitting on the opening bracket as
        # well covers Japanese, which writes the gloss as （...） with no preceding space.
        remainder = target[len(csp) :].strip()
        csp_region = re.split(r"[\s（(]", remainder, maxsplit=1)[0].strip()
        lifecycle = cells[2].replace("*", "").strip()
        pairs.add(Pair(aws_match.group(0), csp, csp_region, lifecycle))
    return pairs


def compare(published: set[Pair], stated: set[Pair], label: str) -> list[str]:
    findings: list[str] = []
    for pair in sorted(published - stated):
        # A pair whose lifecycle alone moved reads better as one finding than as a removal and an
        # addition, which is how a set difference would otherwise present it.
        moved = next(
            (
                other
                for other in stated
                if (other.aws_region, other.csp, other.csp_region)
                == (pair.aws_region, pair.csp, pair.csp_region)
            ),
            None,
        )
        if moved is not None:
            findings.append(
                f"{label}: {pair.aws_region} - {pair.csp} {pair.csp_region} states "
                f"{moved.lifecycle}, AWS now publishes {pair.lifecycle}"
            )
        else:
            findings.append(
                f"{label}: AWS publishes {pair.describe()}, the table omits it"
            )
    for pair in sorted(stated - published):
        if any(
            (other.aws_region, other.csp, other.csp_region)
            == (pair.aws_region, pair.csp, pair.csp_region)
            for other in published
        ):
            continue  # already reported as a lifecycle move
        findings.append(
            f"{label}: the table states {pair.describe()}, AWS no longer publishes it"
        )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--list", action="store_true", help="print the pairs AWS publishes and exit"
    )
    parser.add_argument(
        "--from-file",
        type=Path,
        help="read the page from a local file instead of the network",
    )
    args = parser.parse_args()

    published = parse_page(fetch(args.from_file))
    if not published:
        print(
            "interconnect-regions: the page was retrieved but no Region pair could be read from "
            "it.\n  Treat this as the markup having changed, not as an empty result. Check "
            f"{SOURCE_URL} by hand and fix the parser before trusting this check again.",
            file=sys.stderr,
        )
        return 1

    if args.list:
        for pair in sorted(published):
            print(pair.describe())
        return 0

    findings: list[str] = []
    for relative, header in DOCUMENTS.items():
        path = ROOT / relative
        if not path.is_file():
            findings.append(f"{relative}: not found")
            continue
        stated = parse_document(path, header)
        if not stated:
            findings.append(
                f"{relative}: no pairs table found (looked for a column headed {header!r}). "
                "Either the table moved or the header was renamed; this is a broken reader, not an "
                "empty table"
            )
            continue
        findings.extend(compare(published, stated, relative))

    if findings:
        print(
            f"Interconnect Region pairs are stale ({len(findings)} finding(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\n  AWS's page is the source. Correct both language versions in the same commit, and "
            "check the surrounding prose: the pair counts and the lifecycle are stated in the "
            "overview table, the comparison sections and the selection steps as well.",
            file=sys.stderr,
        )
        return 1

    print(
        f"interconnect-regions: {len(published)} pair(s) published, "
        f"{len(DOCUMENTS)} document(s) match"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
