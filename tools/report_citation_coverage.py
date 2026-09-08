#!/usr/bin/env python3
"""Which evidence documents here the Adoption Playbook has never cited.

The division of labour agreed in S3-Burst-on-ONTAP-Files#88 is that this repository holds the
measurements and the Playbook turns them into design guidance. Both sides can see what *was*
transferred: the Playbook registers a probe string per citation, and `check_incoming_probes.py` fails
when one goes missing. **Neither side can see what was not.** A finding measured here and never picked
up is invisible -- no artefact anywhere says so by its absence.

This prints that difference. It is a report, not a gate: an uncited finding is not a defect. A claim
at stage 未検証 has nothing to build guidance on yet, and some documents are deliberately out of the
Playbook's scope. The line worth reading is a document holding **verified** claims that no probe
touches, because that is knowledge this repository paid to obtain and nothing downstream uses.

**The unit is the document, not the claim, and that is a limit rather than a simplification.** A probe
is registered against a substring of an evidence document; a row in `verification-status.md`
paraphrases that document rather than quoting it. So "does a probe string appear in this claim row"
answers nothing -- it is false for almost every row even when the finding is heavily cited. Matching
per claim would need the Playbook to register which claim each probe supports, which is more
bookkeeping than the question is worth. What this can say honestly:

  - a document with no probe at all  ->  **nothing in it was transferred.** Confident.
  - a document with probes           ->  something was. Which claims, this cannot tell.

Not in `make all`, for the reason `sources-export` is not: it asserts nothing about this tree, so in
the aggregate it would be output nobody reads. Run it when deciding what to hand over next.

Reads the same contract `check_incoming_probes.py` uses, so the two never disagree about what is
registered. Skips with a message when the sibling checkout is absent.

Run:  python3 tools/report_citation_coverage.py [--all]
"""

from __future__ import annotations

import importlib.util
import re
import sys
from pathlib import Path
from typing import NamedTuple

ROOT = Path(__file__).resolve().parent.parent
STATUS = Path("docs/ja/verification-status.md")

# The claim table, and only that one. This document also holds a table of remaining measurements and
# one about how figures are written; both are prose about the process rather than claims with
# evidence, and counting them would report a gap against rows that never had an evidence link.
CLAIM_SECTION = "## 現在の状態"

# Relative links in the evidence column, resolved against the status document's own directory. The
# character class stops at the closing paren and at an anchor: a probe is registered against a file,
# so a fragment is not part of the comparison.
LOCAL_LINK = re.compile(r"\]\((?!https?:)([^)#\s]+\.md)")

# Stage is free prose with parentheticals -- "検証済み（対照付き）", "documented（ブロックプロトコルでの
# 実測は未測定）" -- so it is classified by substring rather than matched exactly. Order matters: the
# documented example above also contains 未測定, and reading it as unverified would hide a claim that
# does have a published basis.
RETRACTED = ("誤り",)
VERIFIED = ("検証済み",)
DOCUMENTED = ("documented", "ドキュメント記載")
UNVERIFIED = ("未検証", "未測定", "未計測", "未確認", "未確定", "揃っていない")

TRANSFERABLE = {"verified", "documented"}


def stage_class(stage: str) -> str:
    for word in RETRACTED:
        if word in stage:
            return "retracted"
    for word in VERIFIED:
        if word in stage:
            return "verified"
    for word in DOCUMENTED:
        if word in stage:
            return "documented"
    for word in UNVERIFIED:
        if word in stage:
            return "unverified"
    return "other"


class Claim(NamedTuple):
    line: int
    text: str
    stage: str
    documents: tuple[str, ...]


def probes_module():
    """Reuse the checker's contract reader rather than parsing the contract a second way."""
    spec = importlib.util.spec_from_file_location(
        "check_incoming_probes", ROOT / "tools" / "check_incoming_probes.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def claims() -> list[Claim]:
    lines = (ROOT / STATUS).read_text(encoding="utf-8").splitlines()
    found: list[Claim] = []
    inside = False
    fenced = False
    for number, raw in enumerate(lines, start=1):
        if re.match(r"^\s*(```|~~~)", raw):
            fenced = not fenced
            continue
        if fenced:
            continue
        if raw.startswith("## "):
            inside = raw.strip() == CLAIM_SECTION
            continue
        if not inside or not raw.startswith("|"):
            continue
        cells = [cell.strip() for cell in raw.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        if cells[1] == "段階" or set(cells[0]) <= set("-: "):
            continue  # header and separator
        documents = tuple(
            dict.fromkeys(
                str((STATUS.parent / link).as_posix())
                for link in LOCAL_LINK.findall(raw)
            )
        )
        found.append(
            Claim(line=number, text=cells[0], stage=cells[1], documents=documents)
        )
    return found


def main() -> int:
    module = probes_module()
    base = module.checkout()
    if base is None:
        print(
            "citation-coverage: SKIPPED, no sibling probe contract found "
            f"(looked for {module.CONTRACT.as_posix()} beside this repository under "
            f"{' or '.join(module.CHECKOUT_NAMES)}, or set SIBLING_PLAYBOOK)."
        )
        return 0
    probes, problems = module.contract_from(base)
    if problems:
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        print("citation-coverage: contract unreadable", file=sys.stderr)
        return 1

    probes_per_document: dict[str, int] = {}
    for probe in probes:
        probes_per_document[probe.path] = probes_per_document.get(probe.path, 0) + 1

    rows = claims()
    if not rows:
        print(
            f"citation-coverage: no claim row found under '{CLAIM_SECTION}' in "
            f"{STATUS.as_posix()}. The table moved or was renamed; this is a broken reader, "
            "not an empty status page.",
            file=sys.stderr,
        )
        return 1

    # Claims per document, kept by stage so an uncited document of unverified claims does not read
    # like an uncited document of measurements.
    per_document: dict[str, list[Claim]] = {}
    external: list[Claim] = []
    for claim in rows:
        if not claim.documents:
            # Evidence is a sibling repository or a vendor page. The Playbook would register its
            # probe against whoever owns that document, not against us.
            external.append(claim)
            continue
        for document in claim.documents:
            per_document.setdefault(document, []).append(claim)

    uncited = {
        document: claims_
        for document, claims_ in per_document.items()
        if not probes_per_document.get(document)
    }
    handover = {
        document: [c for c in claims_ if stage_class(c.stage) in TRANSFERABLE]
        for document, claims_ in uncited.items()
    }
    handover = {d: c for d, c in handover.items() if c}

    print(
        f"citation-coverage: {len(rows)} claim(s) in {STATUS.as_posix()}, "
        f"{len(probes)} probe(s) registered by {base.name} across "
        f"{len(probes_per_document)} document(s)"
    )
    print(f"  {len(per_document):3d}  evidence document(s) referenced by a claim")
    print(f"  {len(per_document) - len(uncited):3d}  of them carry at least one probe")
    print(f"  {len(uncited):3d}  carry none")
    print(
        f"  {len(external):3d}  claim(s) whose evidence is outside this repository, "
        "so coverage is not ours to measure"
    )

    print(
        f"\n--- never cited, and holding verified or documented claims ({len(handover)} document(s)) "
        + "-" * 6
    )
    if not handover:
        print("  none")
    for document in sorted(handover, key=lambda d: -len(handover[d])):
        transferable = handover[document]
        total = len(per_document[document])
        print(
            f"\n  {document}  ({len(transferable)} of {total} claim(s) transferable, 0 probes)"
        )
        for claim in sorted(transferable, key=lambda c: c.line):
            print(f"      :{claim.line}  [{stage_class(claim.stage)}] {claim.text}")

    print("\n--- coverage per document " + "-" * 46)
    print(f"  {'probes':>6}  {'claims':>6}  document")
    for document in sorted(
        per_document, key=lambda d: (-probes_per_document.get(d, 0), d)
    ):
        print(
            f"  {probes_per_document.get(document, 0):>6}  "
            f"{len(per_document[document]):>6}  {document}"
        )

    if "--all" in sys.argv:
        print(
            f"\n--- uncited, and not expected to be yet ({len(uncited) - len(handover)} document(s)) "
            + "-" * 12
        )
        for document in sorted(set(uncited) - set(handover)):
            print(f"\n  {document}")
            for claim in sorted(uncited[document], key=lambda c: c.line):
                print(f"      :{claim.line}  [{stage_class(claim.stage)}] {claim.text}")

    # Documents the Playbook cites that no claim row points at. Not a defect either -- a probe can sit
    # in supporting prose. But a reader of the status page cannot see that something depends on it.
    orphans = sorted(set(probes_per_document) - set(per_document))
    print(f"\n--- cited, but no claim row points at them ({len(orphans)}) " + "-" * 21)
    for document in orphans:
        print(f"  {probes_per_document[document]:>3} probe(s)  {document}")
    if orphans:
        print(
            "\n  The Playbook builds on these, and the status page does not name them as evidence for\n"
            "  anything. Either a claim is missing a link, or the finding lives only in the document."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
