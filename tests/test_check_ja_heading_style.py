"""The heading check has to fail on the shapes it exists for, and pass on the ones it does not.

A check trusted without seeing it reject something is a check that may never have run. Each
exemption below is a heading that was reported by an earlier version of this detector and was
already correct.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

import check_ja_heading_style as ch


def flagged(line: str) -> bool:
    return bool(ch.violations([line]))


def test_predicate_endings_are_rejected() -> None:
    for heading in (
        "## 上限が 2 つに分かれる",  # verb terminal form
        "## 別のファイルシステムです",  # copula
        "## 仮説を 1 つ外しました",  # plain past -- missed by the rule's own written regex
        "## 8 台まで折れません",  # negative polite
        "## どう見るか",  # interrogative
        "### 続けて書くと、容量が増えていきます",
        "#### リクエストレートは SSD IOPS より先に頭打ちになる",
    ):
        assert flagged(heading), heading


def test_noun_phrases_and_exemptions_pass() -> None:
    for heading in (
        "## 上限の分かれ方",
        "## 15 分の持続書き込みでの減衰の不在",
        "## The two ceilings a read can meet",  # no kana: out of scope
        "## 外れた仮説 1 つ",  # counter, not the verb 立つ
        "## キャッシュされる `nconnect`",  # ends in an identifier
        "## まだ測っていないこと",  # already a noun
        "## 記録に必ず添える項目",
    ):
        assert not flagged(heading), heading


def test_h1_is_out_of_scope() -> None:
    assert not flagged("# 上限が 2 つに分かれる")


def test_fenced_blocks_are_skipped() -> None:
    # A `#` inside a fence is a shell comment. Reporting it leads to editing code.
    assert not ch.violations(["```sh", "# 上限を上げる", "```"])
    assert ch.violations(["```sh", "```", "## 上限を上げる"])


def test_code_spans_are_replaced_not_removed() -> None:
    # Removing the span leaves "...ソースにしても返る", which ends in a verb and is a false report.
    assert not flagged("### 結果: 同一 Access Point 内をソースにしても返る `NoSuchKey`")


def test_the_repository_is_clean() -> None:
    root = Path(__file__).resolve().parent.parent
    files = ch.tracked_markdown(root)
    assert files, "no tracked Markdown found; the reader is broken, not the tree"
    offenders = {
        str(path.relative_to(root)): ch.violations(
            path.read_text(encoding="utf-8").split("\n")
        )
        for path in files
    }
    assert not {k: v for k, v in offenders.items() if v}
