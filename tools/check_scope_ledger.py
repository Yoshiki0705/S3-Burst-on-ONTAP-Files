#!/usr/bin/env python3
"""スコープ台帳（docs/ja/reference/tr-integration/scope-ledger.md）の網羅性を検査する。

`check_tr_inventory.py` が入力 PDF の集合（総数と重複）を見るのに対し、こちらは判定を書いた
台帳の側を見る。入力 TR は repo 外にあるので、台帳が 18 行を持ち、各行に判定が 1 つずつ付いて
いることは台帳だけから確かめるしかない。

検査すること:

- 「## スコープ判定」節の表が、期待した 5 列の見出しを持つこと
- 行数が `EXPECTED_TR_COUNT` と一致し、ファイル名が重複しないこと（要件 1.1 / 1.5）
- スコープ判定が「スコープ内」「スコープ外」のどちらか一方であること。空欄や他の値は未判定として
  扱う（要件 1.1）
- 優先・後続区分は、スコープ内の行なら「優先スコープ」「後続スコープ」のどちらか一方、
  スコープ外の行なら台帳の凡例どおり `—` であること（要件 1.3）

検査しないこと: 委任判定列の値。委任判定はスコープ判定と直交する別の軸で（要件 9.3）、
「スコープ外かつ Hub 委任」のような組み合わせもありうる。列が存在することだけを見て、
スコープ判定との組み合わせには制約を置かない。

`check_text()` は台帳の文字列を受け取るので、テストは合成した台帳で 17 本・19 本・重複などの
不合格例を作れる。問題があっても例外は投げず、所見のリストを返す（空なら合格）。

Run:  python3 tools/check_scope_ledger.py [--ledger PATH]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# 入力 TR の合意済みの総数（18）。出典は spec 要件 1.1 / 1.5。入力の PDF は repo 外
# （check_tr_inventory.DEFAULT_TR_DIR）にあって CI からは数えられないため定数として持つが、
# 同じ値を二重に書かないよう、入力側ゲートの定数をそのまま使う。
from check_tr_inventory import EXPECTED_TR_COUNT

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_LEDGER = (
    ROOT / "docs" / "ja" / "reference" / "tr-integration" / "scope-ledger.md"
)

SECTION_HEADING = "## スコープ判定"
EXPECTED_HEADER = (
    "ファイル名",
    "スコープ判定",
    "優先・後続区分",
    "関連根拠",
    "委任判定",
)

IN_SCOPE = "スコープ内"
OUT_OF_SCOPE = "スコープ外"
SCOPE_VALUES = (IN_SCOPE, OUT_OF_SCOPE)
TIER_VALUES = ("優先スコープ", "後続スコープ")
# スコープ外の行の区分表記。台帳の列凡例が「スコープ外は `—`」と定めている。
NO_TIER = "—"


def _cells(line: str) -> list[str]:
    """Markdown 表の 1 行をセルに分ける。先頭と末尾の `|` を落とす。"""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def parse_rows(text: str) -> tuple[list[str], list[list[str]]]:
    """「## スコープ判定」節の最初の表から (見出し行, データ行) を返す。

    節または表が見つからないときは ([], []) を返す。呼び出し側はそれを読み取りの故障として扱う。
    """
    lines = text.splitlines()
    try:
        start = next(
            i for i, line in enumerate(lines) if line.strip() == SECTION_HEADING
        )
    except StopIteration:
        return [], []

    table: list[str] = []
    for line in lines[start + 1 :]:
        if line.startswith("## "):
            break
        if line.lstrip().startswith("|"):
            table.append(line)
        elif table:
            break  # 表の直後の空行や散文で終わり

    if len(table) < 2:
        return [], []
    header = _cells(table[0])
    rows = [_cells(line) for line in table[2:]]  # table[1] は区切り行
    return header, rows


def check_text(text: str, source: str = "scope-ledger") -> list[str]:
    """台帳の文字列を検査し、所見のリストを返す。空なら合格。"""
    header, rows = parse_rows(text)
    if not header:
        return [
            f"{source}: 「{SECTION_HEADING}」節の表が見つからない。台帳の構成が変わったか、"
            f"読み取りが壊れている"
        ]
    if tuple(header) != EXPECTED_HEADER:
        return [
            f"{source}: 表の見出しが {header} で、期待した {list(EXPECTED_HEADER)} と違う"
        ]

    findings: list[str] = []
    if len(rows) != EXPECTED_TR_COUNT:
        findings.append(
            f"{source}: 台帳の行数が {len(rows)} で、期待した {EXPECTED_TR_COUNT} と違う"
        )

    seen: dict[str, int] = {}
    for row in rows:
        if len(row) != len(EXPECTED_HEADER):
            findings.append(f"{source}: 列数が {len(row)} の行がある: {row}")
            continue
        name, scope, tier = row[0], row[1], row[2]
        seen[name] = seen.get(name, 0) + 1
        if not name:
            findings.append(f"{source}: ファイル名が空の行がある: {row}")
        if scope not in SCOPE_VALUES:
            findings.append(
                f"{source}: {name!r} のスコープ判定が {scope!r}。"
                f"{' / '.join(SCOPE_VALUES)} のどちらか一方でなければ未判定として扱う"
            )
        elif scope == IN_SCOPE and tier not in TIER_VALUES:
            findings.append(
                f"{source}: スコープ内の {name!r} の区分が {tier!r}。"
                f"{' / '.join(TIER_VALUES)} のどちらか一方が要る"
            )
        elif scope == OUT_OF_SCOPE and tier != NO_TIER:
            findings.append(
                f"{source}: スコープ外の {name!r} の区分が {tier!r}。スコープ外は {NO_TIER!r}"
            )
        # 委任判定（row[4]）は意図的に検査しない。スコープ判定と直交する軸（要件 9.3）。

    for name, count in seen.items():
        if name and count > 1:
            findings.append(f"{source}: ファイル名 {name!r} が {count} 回現れる")
    return findings


def check(ledger: Path = DEFAULT_LEDGER) -> list[str]:
    if not ledger.is_file():
        return [f"{ledger}: 台帳ファイルが無い"]
    source = ledger.relative_to(ROOT) if ledger.is_relative_to(ROOT) else ledger
    return check_text(ledger.read_text(encoding="utf-8"), str(source))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER)
    args = parser.parse_args()
    findings = check(args.ledger.resolve())
    if findings:
        print(f"scope ledger: {len(findings)} finding(s):", file=sys.stderr)
        for finding in findings:
            print(f"  {finding}", file=sys.stderr)
        return 1
    print(
        f"scope ledger: {EXPECTED_TR_COUNT} rows, each with exactly one scope judgement"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
