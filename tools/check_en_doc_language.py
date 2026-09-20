#!/usr/bin/env python3
"""Catch Japanese text left in English documentation.

Adapted from the sibling repository `FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns`
(`scripts/check_en_doc_language.py`). Divergences: that repository names translations
`<name>.en.md` alongside the Japanese file, so it selected them by filename; here a document's
language is its directory, so the selector is `docs/en/**/*.md`. It also discovered files through
`git ls-files`; this one globs the filesystem so that it works before the repository has been
initialised, which is exactly when the first English page gets written.

English documents here are produced by translating their Japanese counterparts, and a translation
pass that misses a line leaves no trace: the file renders, the links work, and only a reader who
does not read Japanese notices.

Some Japanese in an English document is correct, and the distinction is what makes this checkable
rather than a blanket ban:

* the language switcher is bilingual by design — it has to name the other language in that
  language;
* a link whose text says "Japanese version" is meant to leave English;
* a Japanese statute is a proper noun and is given with an English gloss, which is more useful to
  a reader than the gloss alone.

What remains after those is ALLOWED_ANCHORS: links into Japanese documents that have no English
counterpart to point at. They are debt, not exceptions. Listing them individually means a new one
fails this check, and closing an entry means writing the English target rather than extending the
list.

Run:  python3 tools/check_en_doc_language.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EN_ROOT = ROOT / "docs" / "en"

CJK = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff]")

# Bilingual by design: the switcher names the other language in that language.
SWITCHER = re.compile(r"🌐|\[日本語\]\(|\(日本語\)|\[English\]\(")

# A link that says it goes to the Japanese version is doing what it says.
DELIBERATE_JA_LINK = re.compile(
    r"\[Japanese version\]|\[README \(日本語\)\]|Japanese is authoritative"
)

# A Japanese statute paired with its English gloss, in either order.
LAW_WITH_GLOSS = re.compile(
    r"[\u4e00-\u9fff]+(法|規則|条例|基準)[^(（]{0,12}[(（]\s*[A-Za-z]"
    r"|[A-Za-z][A-Za-z ]{3,}[(（][^)）]{0,20}[\u4e00-\u9fff]+(法|規則|条例|基準)[^)）]{0,10}[)）]"
)

# Files where the Japanese is the subject of the passage, not a translation miss. Scoped to the
# lines that carry it, so the rest of each file is still checked.
BY_DESIGN_FILES: dict[str, re.Pattern[str]] = {}

# Links into Japanese documents that have no English counterpart. Each entry is a reader who
# leaves English by following a link whose own text is in English.
ALLOWED_ANCHORS: dict[str, tuple[str, ...]] = {
    # The throughput / IOPS / concurrency record is Japanese-only by the Tier 2 policy: it is a
    # measurement record, not a page a reader follows while creating billable resources. English
    # documents that cite a specific finding in it therefore have no English target to point at, and
    # the alternative would be restating measured figures in a second place, where the two copies
    # would drift.
    #
    # Closing these entries means translating docs/ja/verification/throughput-iops-concurrency.md,
    # not deleting the links.
    "docs/en/deployment/onprem-terraform.md": (
        "#flexcache-経由の読み取り",  # the FlexCache read measurement
        "#リージョンを跨いだ-flexcache読み手が遠い場合",  # the inter-Region FlexCache measurement
    ),
    "docs/en/reference/comparison/finops-s3-vs-s3ap.md": (
        "#小さいオブジェクトの-iops",  # why extra SSD IOPS does not raise the S3 request rate
    ),
    "docs/en/reference/limits/s3ap-design-guide.md": (
        "#複数クライアントでの集約",  # shared versus per-client ceilings, at two clients
        "#クライアント台数を-1-から-4-まで上げたとき",  # the same, extended to four
    ),
    "docs/en/verification-status.md": (
        # The round that measured the nine outstanding items and corrected five published figures.
        "#残していた-9-件を測ったこの記録の数値を-5-つ訂正します",
        # The re-measurement that read 2.15x the file server's in-memory cache in one pass, which is
        # what the 7.14x from SSD IOPS had been missing. It reproduces the low point and not the
        # high one, so the English row states a ratio that only this record's conditions explain.
        "#キャッシュを超える作業セットでの再測定2026-09-17",
        # The 1 MiB transfer-size re-measurement that closed the candidate the row above left open.
        # Both ends move and the ratio does not, which is the finding; the English row states the
        # ratio and this record holds the two points and the conditions that produced them.
        "#転送サイズ-1-mib-での再測定2026-09-18-倍率の不変",
        # The FlexCache pair measured with the origin at 2048 and the cache at 128, where the 2.31x
        # inverts. The row states the inversion; the record holds why each figure is conditional --
        # the resident read was bursting and the direct origin read came from memory.
        "#origin-を-2048-mbps-に上げたときの向きの逆転2026-09-18",
        # The two-client run that settled whether the unexplained ceiling was the client's or the
        # file system's. The English row states the answer and the two utilization figures that
        # carry it; the record holds the per-interval values and the conditions.
        "#2-台で測った結果--天井はクライアント側2026-09-19",
        # The thread sweep that narrowed the row above: the answer was not a client resource but two
        # client-side settings, and one host then reaches the same file-system ceiling two did. The
        # English row states that and the utilization figure; the record holds all four points, the
        # response times that double while throughput does not, and what is still unreconciled.
        "#スレッド数を振った結果--1195-を決めていたのは設定-2-つ2026-09-1920",
        # The re-read of retained CloudWatch that closed the gap between the one-client and
        # two-client totals without new resources: no burst-balance metric exists on this
        # configuration, the utilization denominator is the specified value, and both sessions pinned
        # the server side at the same ceiling. The English rows state each of those; the record holds
        # the per-minute figures and the counter disagreement it opened in exchange.
        "#保持された-cloudwatch-で閉じた-2-点2026-09-20",
        # The aligned-window comparison that closed the counter disagreement the entry above
        # opened. The English row states that the two counters agree to within 0.2% once the
        # window starts on a minute boundary and partial minutes are discarded; the record holds
        # both windows, the excluded partial minutes that produced the original 19%, and why the
        # server-side read cache could not be dropped between them.
        "#窓を分境界に合わせた-2-系統の比較2026-09-20",
        # The 900 s window that refuted the last remaining hypothesis for the SMB 300-vs-900
        # gap: the channel count held at 4 across all 31 samples. The English row states that
        # and the limitation that the magnitudes are not reproducible at 1,536 MBps; the record
        # holds the samples, the two prerequisites for measuring SMB without a directory, and
        # why no throughput figure is reported from that run.
        "#900-秒のあいだチャネル数が減らないこと2026-09-20",
        # The run that varied only the measurement duration and found no 16% effect. The English
        # row states the write means and that run-to-run variation at a fixed duration exceeds
        # them; the record holds both passes, the non-monotonic read outlier at 60 s, and the
        # untested layout hypothesis offered for it.
        "#測定時間だけを振った結果--16-の不在2026-09-20",
        # The run that located the 4 KiB front-end ceiling by changing only how the working set
        # was split. The English row states the three deltas and that the disk side reaches 96.6%
        # at two clients; the record holds all five shapes, the counter cross-check, and why it is
        # not a reproduction of F-10.
        "#4-kib-ランダム読みの天井の所在2026-09-20",
        # The re-measurement that failed to reproduce the SMB 12.4% window-length gap, in the
        # opposite direction. The English row states both figures and the two limitations; the
        # record holds the per-minute series and why the long window stopped early.
        "#smb-の窓長-124-の再現不成立2026-09-20",
    ),
    # The block measurements, cited from the shape that this architecture does not serve. Shape 5 sends
    # a reader who needs iSCSI or NVMe/TCP away, and the one thing worth handing them on the way out is
    # the measurement plus the three limits that stop it being read as a distribution figure. The
    # record is a measurement record and Japanese-only by the Tier 2 policy; restating the figures in
    # English would put them in a second place, where the two copies drift.
    "docs/en/reference/decision-trees/from-your-current-setup.md": (
        "#f-1-iscsi-の実測",
    ),
    # The English expectations page states, in a note under two measured rows, that above 100% on the
    # first generation is not burst: the denominator is the specified value and no burst-balance
    # metric exists on that configuration. That correction is only safe to state next to the
    # per-minute figures it came from, and those are in the Japanese measurement record. Restating
    # them here would put a metric's denominator in two places, which is how the "in burst" label
    # that this note removes got written in the first place.
    "docs/en/performance-expectations.md": (
        "#保持された-cloudwatch-で閉じた-2-点2026-09-20",
        # The row that closed the counter disagreement states the aligned figures; the record
        # holds the discarded partial minutes that explain where the original 19% came from.
        "#窓を分境界に合わせた-2-系統の比較2026-09-20",
    ),
    # The teardown traps from the security-style inheritance run. The English teardown step warns
    # that skipping the peer release strands the stack, and this anchor is the eight failures behind
    # that warning -- including the two that only appear when the order is already wrong. Restating
    # them in English would put the recovery procedure in two places, and the copy a reader reaches
    # while their stack is stuck is the one that must not be the stale one.
    "docs/en/deployment/aws-cloudformation.md": ("#この手順で踏んだ罠",),
}


def english_docs() -> list[Path]:
    if not EN_ROOT.is_dir():
        return []
    return sorted(EN_ROOT.rglob("*.md"))


def is_allowed(relative: str, line: str) -> bool:
    """Whether this line's Japanese is there on purpose."""
    if SWITCHER.search(line) or DELIBERATE_JA_LINK.search(line):
        return True
    if LAW_WITH_GLOSS.search(line):
        return True
    by_design = BY_DESIGN_FILES.get(relative)
    if by_design and by_design.search(line):
        return True
    return any(needle in line for needle in ALLOWED_ANCHORS.get(relative, ()))


def main() -> int:
    findings: list[str] = []
    scanned = 0
    for path in english_docs():
        scanned += 1
        relative = str(path.relative_to(ROOT))
        for number, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if not CJK.search(line) or is_allowed(relative, line):
                continue
            findings.append(f"{relative}:{number}: {line.strip()[:110]}")

    if findings:
        print(
            f"English documents carry untranslated Japanese ({len(findings)} line(s)):",
            file=sys.stderr,
        )
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        print(
            "\n  Japanese that is there on purpose (a statute name with its English gloss, the "
            "language switcher, an explicit link to the Japanese version) belongs in the allow "
            "lists in tools/check_en_doc_language.py, with the reason. Anchors into Japanese "
            "documents are listed individually in ALLOWED_ANCHORS; before adding one, consider "
            "writing the English target instead.",
            file=sys.stderr,
        )
        return 1

    print(f"EN docs OK: no untranslated Japanese in {scanned} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
