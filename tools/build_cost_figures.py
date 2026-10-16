#!/usr/bin/env python3
"""Generate the S3 Files cost-structure figures (2 figures x JA/EN x light/dark) from the model.
The only numeric input is `finops_model.baseline_json()`, the same data `finops_model.py
--baseline-json` prints; no amount is typed here. Run: `python3 tools/build_cost_figures.py
--recheck-date YYYY-MM-DD [--theme light|dark] [--export]`. `--export` needs the draw.io CLI for PNG
@2x and stops with an error when it is absent. `tests/test_cost_figures.py` compares the committed
drawio amounts with the model, so regenerate whenever the model's output changes.
"""

from __future__ import annotations

import argparse
import html
import json
import math
import re
import struct
import subprocess
import sys
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

import finops_model
from build_diagrams import DRAWIO_CLI

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = ROOT / "docs" / "_assets" / "diagrams"
IMAGE_DIR = ROOT / "docs" / "_assets" / "images"

BASE_NAME = "s3burst-s3files-cost-structure"
W = 860  # canvas width in px
FONT = 16
FONT_H = 18
LINE_H = 22
LABEL_W = 160
BAR_X = 170
BAR_PX_MAX = 560  # px for the full axis
BAR_H = 26
BAR_ROW_H = 58  # bar 26 + gap 2 + breakdown 22 + pad 8
AXIS_STEP = 2500
INSIDE_MIN_PX = 100
EXPORT_BORDER = 8

CATS = ["storage", "tput", "hps", "req"]  # stacking and legend order

# JA label prefix -> category. Exactly one prefix must match each line; otherwise the build fails.
RULES = [
    ("SSD ストレージ", "storage"),
    ("キャパシティプールストレージ", "storage"),
    ("ストレージ (S3 Standard", "storage"),
    ("スループットキャパシティ", "tput"),
    ("S3 Files 高性能ストレージ", "hps"),
    ("キャパシティプール読み取りリクエスト", "req"),
    ("PUT リクエスト", "req"),
    ("GET リクエスト", "req"),
    ("S3 Files 書き込み", "req"),
    ("S3 Files 読み取り", "req"),
    ("S3 Files メタデータ", "req"),
]

THEMES = {
    "light": {
        "bg": "#FFFFFF",
        "ink": "#232F3E",
        "inbar": "#FFFFFF",
        "grid": "#D5DBDB",
        "seg_stroke": "#FFFFFF",
        "cats": {
            "storage": "#1D6FA3",
            "tput": "#4C7A0F",
            "hps": "#B34A0A",
            "req": "#6B3FB5",
        },
    },
    "dark": {
        "bg": "#232F3E",
        "ink": "#FFFFFF",
        "inbar": "#101820",
        "grid": "#4A5568",
        "seg_stroke": "#232F3E",
        "cats": {
            "storage": "#5FB3E6",
            "tput": "#8FCB4A",
            "hps": "#F2975A",
            "req": "#B89BF2",
        },
    },
}

# Figure definitions: which patterns, which methods, file suffix, same-cost group for note *1.
FIGURES = {
    1: {
        "patterns": ["P1", "P4"],
        "methods": ["s3_direct", "s3_files", "fsx_s3ap"],
        "suffix": "",
        "same": ("P4", ["P2", "P3"]),
    },
    2: {
        "patterns": ["P5", "P6", "P8"],
        "methods": ["s3_files", "fsx_s3ap"],
        "suffix": "-writes",
        "same": ("P6", ["P7"]),
    },
}
SIZES = [64, 4096]

DEPLOYMENT = {"SINGLE_AZ_1": {"ja": "Single-AZ 第一世代", "en": "Single-AZ, 1st gen"}}

# ---------------------------------------------------------------------------------------------
# Text
# ---------------------------------------------------------------------------------------------

T = {
    "ja": {
        "cats": {
            "storage": "保管",
            "tput": "固定の帯域",
            "hps": "S3 Files の高性能ストレージ",
            "req": "リクエストと S3 Files の読み書き課金",
        },
        "short": {
            "storage": "保管",
            "tput": "帯域",
            "hps": "高性能ストレージ",
            "req": "リクエスト等",
        },
        "methods": {
            "s3_direct": ["S3 API で", "直接読む"],
            "s3_files": ["S3 Files 経由"],
            "fsx_s3ap": ["FSx for ONTAP"],
        },
        "route": {
            1: "FSx for ONTAP の棒は、読み取りをファイルシステムから行います。\nS3 Access Points の読み取り課金は算入しません。",
            2: "FSx for ONTAP の棒は、読み取りをファイルシステムから行います。\n書き込みは S3 Access Points 経由の PUT 課金を算入します。",
        },
        "direct_note": "書き込みがあるパターンでは S3 API 直読みを比較対象にしないため、この図に S3 API 直読みの棒はありません。",
        "axis_note": "月額（ドル）。横軸は 0〜{max} で、図 1・図 2 と全パターンに共通です",
        "placeholder": "（仮置き{m}）",
        "prem1": "保存 20 TiB のうち作業セット {pct}%（{ws} TiB）を、各オブジェクト月 {n} 回読みます",
        "prem2": "月間の読み取り {r} TiB（保存量の {rm} 倍）、{w}",
        "w_none": "書き込みなし",
        "w_some": "書き込み{m3} {w} TiB（保存量の {wp}%）",
        "size_head": "{s}: 保存 {so} 個 / 読み取り {rr} 回 / {w}",
        "size_w_none": "書き込みなし",
        "size_w_some": "書き込み {wo} 個",
        "notes_head": "補足",
        "notes": {
            1: [
                (
                    "※1 同額のパターン:",
                    " P4 は P2・P3 と同額です。価格は作業セット比に連動しません。",
                ),
                ("※2 仮置きの値:", " P1 の作業セット比と回数は出典のない仮置きです。"),
                (
                    "※3 S3 API 直読みの棒:",
                    " 書き込みのない P1・P4 にだけ置いています。",
                ),
                (
                    "※4 S3 Files のメタデータ課金:",
                    " 4 KiB × 操作を紫に算入しています。1 MiB 以上で立つかは未確認です。",
                ),
            ],
            2: [
                (
                    "※1 同額のパターン:",
                    " P6 は P7 と同額です。価格は作業セット比に連動しません。",
                ),
                (
                    "※2 仮置きの値:",
                    " P5 の書き込み量、P6・P8 の作業セット比、回数、書き込み量は出典のない仮置きです。",
                ),
                (
                    "※3 書き込みは置き換え:",
                    " 書き込みは既存データの置き換えで、保存量は 20 TiB のまま一定です。",
                ),
                ("※4 S3 Files のメタデータ課金:", " 図 1 の※4 と同じです。"),
            ],
        },
        "marks": {
            1: {"same": "※1", "ph": "※2", "direct": "※3", "meta": "※4"},
            2: {"same": "※1", "ph": "※2", "write": "※3", "meta": "※4"},
        },
        "def_head": "{pid} {name}: ",
        "def_read": "作業セット {pct}% を各 {n} 回読み、",
        "def_w_none": "書き込みはありません。",
        "def_w_some": "書き込みは保存量の {pct}% です。",
        "def_basis": "{items}です。",
        "def_item": "{labels}は{word}",
        "def_join": "、",
        "def_and": "・",
        "labels": {
            "working_set": "作業セット比",
            "reads_per_object": "回数",
            "churn": "書き込み量",
        },
        "basis_word": {
            "placeholder": "出典のない仮置き",
            "repository": "リポジトリの試算前提",
            "sourced": "公開ブログの比",
        },
        "warn_head": "前提についての注意",
        "warn": (
            "この金額は固定の前提による試算です。主な前提は、capacity pool の割合（{pool}%）、"
            "SSD 層の効率（{eff}%）、S3 Files の高性能ストレージのアクティブ割合（100%）、"
            "取り込みしきい値（{thr} KiB）、デプロイ形態（{dep}）です。"
            "前提を変えると金額と順序が大きく動きます。"
            "S3 Files 経由と FSx for ONTAP を比べると、64 KiB は FSx for ONTAP が安く、"
            "4 MiB は S3 Files 経由が安いという向きですが、これは基準の前提での結果で、"
            "前提で入れ替わりえます。"
            "自分の環境の値に置き換えて選定してください。"
            "前提の一覧と感度は、別の節・別の PR で整理する予定です。"
        ),
        "foot1": (
            "各棒は主要費目小計で、月額総額ではありません。capacity pool の読み取りリクエスト数が未確認で、"
            "S3 のバージョニング非現行版・バックアップ・通信費を算入していません。"
        ),
        "foot2": (
            "リスト価格 × 数量の計算で、請求額ではありません。{region}、"
            "単価は {snap} に取得し {recheck} に読み直しました。"
        ),
        "required": ["前提", "入れ替わり", "別の PR", "主要費目小計", None],
    },
    "en": {
        "cats": {
            "storage": "Storage",
            "tput": "Provisioned throughput",
            "hps": "S3 Files high-performance storage",
            "req": "Requests and S3 Files read/write charges",
        },
        "short": {
            "storage": "Storage",
            "tput": "Throughput",
            "hps": "High-performance",
            "req": "Requests etc.",
        },
        "methods": {
            "s3_direct": ["Read via", "S3 API"],
            "s3_files": ["Via S3 Files"],
            "fsx_s3ap": ["FSx for ONTAP"],
        },
        "route": {
            1: "FSx for ONTAP bars: reads come from the file system;\nS3 Access Points read charges are not included.",
            2: "FSx for ONTAP bars: reads come from the file system;\nwrites include the S3 Access Points PUT charge.",
        },
        "direct_note": "There are no S3 API bars in this figure: patterns with writes are not compared against reading directly through the S3 API.",
        "axis_note": "Monthly cost (USD). Axis is 0 to {max}, shared by Figures 1 and 2 and all patterns.",
        "placeholder": " (placeholder{m})",
        "prem1": "Of the 20 TiB stored, a {pct}% working set ({ws} TiB) is read {n} {times} per object per month",
        "prem2": "Monthly reads {r} TiB ({rm}x stored), {w}",
        "w_none": "writes none",
        "w_some": "writes{m3} {w} TiB ({wp}% of stored)",
        "size_head": "{s}: {so} objects stored / {rr} reads / {w}",
        "size_w_none": "no writes",
        "size_w_some": "{wo} writes",
        "notes_head": "Notes",
        "notes": {
            1: [
                (
                    "*1 Same-cost patterns:",
                    " P4 costs the same as P2 and P3. Price does not follow the working-set share.",
                ),
                (
                    "*2 Placeholder values:",
                    " P1's working-set share and read count have no source.",
                ),
                ("*3 S3 API bars:", " placed only on P1 and P4, which have no writes."),
                (
                    "*4 S3 Files metadata charge:",
                    " 4 KiB x operations is included in the purple segment. Whether it applies at 1 MiB and above is unconfirmed.",
                ),
            ],
            2: [
                (
                    "*1 Same-cost patterns:",
                    " P6 costs the same as P7. Price does not follow the working-set share.",
                ),
                (
                    "*2 Placeholder values:",
                    " P5's write volume and P6's and P8's working-set share, read count and write volume have no source.",
                ),
                (
                    "*3 Writes replace existing data:",
                    " the stored volume stays at 20 TiB.",
                ),
                ("*4 S3 Files metadata charge:", " same as Figure 1, *4."),
            ],
        },
        "marks": {
            1: {"same": "*1", "ph": "*2", "direct": "*3", "meta": "*4"},
            2: {"same": "*1", "ph": "*2", "write": "*3", "meta": "*4"},
        },
        "def_head": "{pid} {name}: ",
        "def_read": "reads a {pct}% working set {n} {times} per object, ",
        "def_w_none": "with no writes. ",
        "def_w_some": "with writes of {pct}% of the stored volume. ",
        "def_basis": "{items}.",
        "def_item": "{labels} {verb} {word}",
        "def_join": "; ",
        "def_and": " and ",
        "labels": {
            "working_set": "working-set share",
            "reads_per_object": "read count",
            "churn": "write volume",
        },
        "basis_word": {
            "placeholder": ("a placeholder", "placeholders"),
            "repository": ("a repository assumption", "repository assumptions"),
            "sourced": ("taken from public blogs", "taken from public blogs"),
        },
        "warn_head": "Read these figures with their assumptions",
        "warn": (
            "These amounts are an estimate under fixed assumptions: capacity pool share ({pool}%), "
            "SSD-tier efficiency ({eff}%), S3 Files high-performance storage fully active (100%), "
            "import threshold ({thr} KiB), deployment type ({dep}). "
            "Change them and both the amounts and the order can move a lot. "
            "Comparing access through S3 Files with FSx for ONTAP, 64 KiB favors FSx for ONTAP and 4 MiB favors S3 Files; "
            "that holds under these assumptions only and can reverse when they change. "
            "Replace them with your own values when choosing. "
            "The full assumption list and sensitivity will follow in a separate section and PR."
        ),
        "foot1": (
            "Each bar is a major-line-item subtotal, not a monthly total. The capacity pool read-request "
            "count is unconfirmed, and non-current S3 versions, backups and data transfer are excluded."
        ),
        "foot2": (
            "List price x quantity, not an invoice. {region}; unit prices retrieved {snap} and re-read {recheck}."
        ),
        "required": [
            "assumptions",
            "order can move",
            "separate section and PR",
            "major-line-item subtotal",
            None,
        ],
    },
}


# ---------------------------------------------------------------------------------------------
# Text measurement and wrapping (explicit line breaks; nothing is left to the renderer)
# ---------------------------------------------------------------------------------------------


def char_w(ch: str, size: float = FONT) -> float:
    if ch in "■※":
        return size
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return size
    if ch == "\u00a0" or ch == " ":
        return 0.30 * size
    if ch.isdigit():
        return 0.56 * size
    if ch.isupper():
        return 0.70 * size
    if ch.isalpha():
        return 0.55 * size
    if ch in ".,:;'|!iIl":
        return 0.32 * size
    return 0.60 * size


def text_w(s: str, size: float = FONT, bold: bool = False) -> float:
    return sum(char_w(c, size) for c in s) * (1.08 if bold else 1.0)


NO_LINE_START = set("、。，．）」』】）,.:;!?%※")


def tokens(s: str) -> list[str]:
    """Split into wrap units: whole ASCII words (with trailing spaces) and single CJK characters."""
    out: list[str] = []
    i = 0
    while i < len(s):
        c = s[i]
        if unicodedata.east_asian_width(c) in ("W", "F") or c in "■※":
            out.append(c)
            i += 1
            continue
        j = i
        while j < len(s) and not (
            unicodedata.east_asian_width(s[j]) in ("W", "F") or s[j] in "■※"
        ):
            if s[j] == " ":
                j += 1
                while j < len(s) and s[j] == " ":
                    j += 1
                break
            j += 1
        out.append(s[i:j])
        i = j
    return out


GLUE = [
    "S3 Files",
    "FSx for ONTAP",
    "capacity pool",
    "S3 Access Points",
    "Single-AZ",
    "S3 API",
    "S3 Standard",
    "KiB",
    "MiB",
    "TiB",
]
SOFT_BREAK = "、。"


def glue(s: str) -> str:
    for g in GLUE:
        s = s.replace(g, g.replace(" ", "\u00a0"))
    # keep a number with its unit
    return re.sub(r"(\d) (KiB|MiB|TiB)", "\\1\u00a0\\2", s)


def wrap(s: str, max_w: float, size: float = FONT, bold: bool = False) -> list[str]:
    lines: list[str] = []
    cur = ""
    for tk in tokens(glue(s)):
        trial = cur + tk
        if (
            cur
            and text_w(trial.rstrip(), size, bold) > max_w
            and tk.strip()
            and tk[0] not in NO_LINE_START
        ):
            cut = max((cur.rfind(c) for c in SOFT_BREAK), default=-1)
            if cut >= 0 and text_w(cur[cut + 1 :], size, bold) <= 190:
                lines.append(cur[: cut + 1].rstrip())
                cur = cur[cut + 1 :] + tk
            else:
                lines.append(cur.rstrip())
                cur = tk.lstrip()
        else:
            cur = trial
    if cur.strip():
        lines.append(cur.rstrip())
    return [l.replace("\u00a0", " ") for l in lines]


def definition(p: dict, lang: str) -> str:
    """One reader-facing line that defines a pattern, derived from the model's own fields.

    The working-set share, the read count, the writes and the origin of each value (`basis`) are read
    from the pattern; nothing about P2, P3 or P7 is typed here. A basis the table does not name stops
    the build rather than being guessed at.
    """
    tx = T[lang]
    pid = p["id"]
    params = ["working_set", "reads_per_object"] + (["churn"] if p["churn_pct"] else [])
    groups: dict[str, list[str]] = {}
    for key in params:
        basis = p["basis"][key]
        if basis not in tx["basis_word"] or (
            basis == "sourced" and key != "working_set"
        ):
            raise SystemExit(f"{pid}: no wording for basis {basis!r} of {key}")
        groups.setdefault(basis, []).append(tx["labels"][key])
    clauses = []
    for basis, labels in groups.items():
        if lang == "ja":
            joined, word = tx["def_and"].join(labels), tx["basis_word"][basis]
            verb = ""
        else:
            joined = (
                labels[0]
                if len(labels) == 1
                else ", ".join(labels[:-1]) + tx["def_and"] + labels[-1]
            )
            word = tx["basis_word"][basis][len(labels) > 1]
            verb = "are" if len(labels) > 1 else "is"
        clauses.append(tx["def_item"].format(labels=joined, word=word, verb=verb))
    basis_text = tx["def_basis"].format(items=tx["def_join"].join(clauses))
    if lang == "en":
        basis_text = basis_text[0].upper() + basis_text[1:]
    reads = tx["def_read"].format(
        pct=p["working_set_pct"],
        n=p["reads_per_object"],
        times="time" if p["reads_per_object"] == 1 else "times",
    )
    writes = (
        tx["def_w_some"].format(pct=num(p["churn_pct"]))
        if p["churn_pct"]
        else tx["def_w_none"]
    )
    head = tx["def_head"].format(
        pid=pid, name=p["name_ja" if lang == "ja" else "name_en"]
    )
    return head + reads + writes + basis_text


def money(x: float) -> str:
    return f"${x:,.2f}"


def size_name(kib: int) -> str:
    return f"{kib} KiB" if kib < 1024 else f"{kib // 1024} MiB"


def num(x: float) -> str:
    """Integer when whole, otherwise a plain decimal (TiB amounts)."""
    return (
        f"{x:,.0f}" if abs(x - round(x)) < 1e-9 else f"{x:,.2f}".rstrip("0").rstrip(".")
    )


def mult(x: float) -> str:
    s = f"{x:.2f}"
    return s.removesuffix("0")


# ---------------------------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------------------------


def load() -> dict:
    """The model's baseline grid. Labels are Japanese in both languages: only `classify` reads them."""
    return json.loads(json.dumps(finops_model.baseline_json("ja")))


def classify(label: str) -> str:
    hits = [cat for prefix, cat in RULES if label.startswith(prefix)]
    if len(hits) != 1:
        raise SystemExit(f"unclassified or ambiguous line label: {label!r} -> {hits}")
    return hits[0]


def categorize(method: dict) -> dict[str, float]:
    out = {c: 0.0 for c in CATS}
    for line in method["lines"]:
        out[classify(line["label"])] += line["usd"]
    if abs(sum(out.values()) - method["subtotal_usd"]) > 1e-6:
        raise SystemExit(
            f"category sum {sum(out.values())} != subtotal {method['subtotal_usd']}"
        )
    shown = sum(round(v, 2) for v in out.values())
    if abs(shown - round(method["subtotal_usd"], 2)) > 0.02:
        raise SystemExit(
            f"rounded categories {shown} differ from {method['subtotal_display']}"
        )
    if money(method["subtotal_usd"]) != method["subtotal_display"]:
        raise SystemExit(
            f"subtotal_display {method['subtotal_display']} != {money(method['subtotal_usd'])}"
        )
    return out


def by_id(data: dict) -> dict[str, dict]:
    return {p["id"]: p for p in data["patterns"]}


def cell_of(p: dict, kib: int) -> dict:
    hits = [c for c in p["cells"] if c["size_kib"] == kib]
    if len(hits) != 1:
        raise SystemExit(f"{p['id']}: expected one cell of {kib} KiB")
    return hits[0]


def axis_max(data: dict) -> int:
    pats = by_id(data)
    top = 0.0
    for fig in FIGURES.values():
        for pid in fig["patterns"]:
            for kib in SIZES:
                for m in fig["methods"]:
                    top = max(
                        top, cell_of(pats[pid], kib)["methods"][m]["subtotal_usd"]
                    )
    return int(math.ceil(top / AXIS_STEP) * AXIS_STEP)


def verify_claims(data: dict) -> None:
    """Statements the figures make in prose must hold in the data, or the build fails."""
    pats = by_id(data)

    def totals(pid: str) -> list:
        return [
            (c["size_kib"], m, v["subtotal_usd"])
            for c in pats[pid]["cells"]
            for m, v in c["methods"].items()
            if v
        ]

    for fig in FIGURES.values():
        head, others = fig["same"]
        for o in others:
            if totals(head) != totals(o):
                raise SystemExit(f"note: {head} is not the same price as {o}")
    for pid in [pid for f in FIGURES.values() for pid in f["patterns"]]:
        p = pats[pid]
        small, big = cell_of(p, 64)["methods"], cell_of(p, 4096)["methods"]
        if not small["fsx_s3ap"]["subtotal_usd"] < small["s3_files"]["subtotal_usd"]:
            raise SystemExit(
                f"{pid}: 64 KiB does not favor FSx for ONTAP; the warning sentence is false"
            )
        if not big["s3_files"]["subtotal_usd"] < big["fsx_s3ap"]["subtotal_usd"]:
            raise SystemExit(
                f"{pid}: 4 MiB does not favor S3 Files; the warning sentence is false"
            )
    # route notes
    for pid in FIGURES[1]["patterns"]:
        for c in pats[pid]["cells"]:
            if any(
                l["label"].startswith("GET") for l in c["methods"]["fsx_s3ap"]["lines"]
            ):
                raise SystemExit(
                    "figure 1 route note says S3 Access Points reads are excluded; a GET line exists"
                )
    for pid in FIGURES[2]["patterns"]:
        for kib in SIZES:
            c = cell_of(pats[pid], kib)
            if c["methods"].get("s3_direct"):
                raise SystemExit(
                    f"{pid}: s3_direct exists, but figure 2 says it is not applicable"
                )
            put = [
                l["usd"]
                for l in c["methods"]["fsx_s3ap"]["lines"]
                if l["label"].startswith("PUT リクエスト (S3 AP")
            ]
            if not put or put[0] <= 0:
                raise SystemExit(
                    f"{pid}: figure 2 route note says an S3 AP PUT charge is included; none found"
                )
    for pid in FIGURES[1]["patterns"]:
        for kib in SIZES:
            c = cell_of(pats[pid], kib)
            if not all(c["methods"].get(m) for m in FIGURES[1]["methods"]):
                raise SystemExit(f"{pid}: figure 1 needs all three methods")
            if c["write_objects"] != 0:
                raise SystemExit(f"{pid}: figure 1 holds read-only patterns")
    for pid in FIGURES[2]["patterns"]:
        if cell_of(pats[pid], 64)["write_objects"] == 0:
            raise SystemExit(f"{pid}: figure 2 holds patterns with writes")


# ---------------------------------------------------------------------------------------------
# drawio writer
# ---------------------------------------------------------------------------------------------


class Canvas:
    def __init__(self, theme: dict):
        self.t = theme
        self.cells: list[ET.Element] = []
        self.back: list[ET.Element] = []
        self.n = 2

    def _add(self, target: list, cid: str, value: str, x, y, w, h, style: str) -> None:
        c = ET.Element(
            "mxCell", id=cid, value=value, style=style, vertex="1", parent="1"
        )
        ET.SubElement(
            c,
            "mxGeometry",
            {
                "x": f"{x:.2f}",
                "y": f"{y:.2f}",
                "width": f"{w:.2f}",
                "height": f"{h:.2f}",
                "as": "geometry",
            },
        )
        target.append(c)

    def uid(self, prefix: str) -> str:
        self.n += 1
        return f"{prefix}-{self.n}"

    def text(
        self,
        cid,
        value_html,
        x,
        y,
        w,
        h,
        *,
        size=FONT,
        bold=False,
        align="left",
        fill=False,
        color=None,
    ):
        style = (
            f"text;html=1;whiteSpace=nowrap;overflow=visible;align={align};verticalAlign=middle;"
            f"spacing=0;spacingLeft=0;spacingRight=0;spacingTop=0;spacingBottom=0;"
            f"fontSize={size};fontColor={color or self.t['ink']};fontStyle={1 if bold else 0};"
        )
        if fill:
            style += f"fillColor={self.t['bg']};strokeColor=none;"
        self._add(self.cells, cid, value_html, x, y, w, h, style)

    def rect(
        self,
        cid,
        fill,
        x,
        y,
        w,
        h,
        *,
        label="",
        stroke=None,
        label_color=None,
        back=False,
    ):
        stroke_style = (
            f"strokeColor={stroke};strokeWidth=1;" if stroke else "strokeColor=none;"
        )
        style = (
            f"rounded=0;whiteSpace=nowrap;html=0;fillColor={fill};{stroke_style}"
            f"fontSize={FONT};fontColor={label_color or self.t['inbar']};fontStyle=1;align=center;verticalAlign=middle;"
        )
        self._add(self.back if back else self.cells, cid, label, x, y, w, h, style)


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def build_figure(
    data: dict, fig_no: int, lang: str, theme_name: str, recheck: str, ax_max: int
) -> tuple[ET.ElementTree, int]:
    th = THEMES[theme_name]
    tx = T[lang]
    fig = FIGURES[fig_no]
    pats = by_id(data)
    marks = tx["marks"][fig_no]
    cv = Canvas(th)
    scale = BAR_PX_MAX / ax_max
    y = 0.0
    name_key = "name_ja" if lang == "ja" else "name_en"

    # 1. legend (2 x 2, row-major)
    for i, cat in enumerate(CATS):
        col, row = i % 2, i // 2
        lx, ly = col * (W / 2), y + row * 28
        cv.rect(f"legend-sw-{cat}", th["cats"][cat], lx, ly + 4, 20, 20)
        label = tx["cats"][cat] + (marks["meta"] if cat == "req" else "")
        cv.text(f"legend-{cat}", esc(label), lx + 28, ly, W / 2 - 32, 28)
    y += 2 * 28 + 10

    # 2. route note
    lines = [l for part in tx["route"][fig_no].split("\n") for l in wrap(part, W - 20)]
    cv.text(
        "route-note", "<br>".join(esc(l) for l in lines), 0, y, W, LINE_H * len(lines)
    )
    y += LINE_H * len(lines)
    if (
        fig_no == 2
    ):  # a line of its own, so no footnote mark hangs on the PUT-charge sentence above
        dl = wrap(tx["direct_note"], W - 20)
        cv.text(
            "direct-note", "<br>".join(esc(l) for l in dl), 0, y, W, LINE_H * len(dl)
        )
        y += LINE_H * len(dl)
    y += 8

    # 3. axis note and ticks (top)
    cv.text(
        "axis-note",
        esc(tx["axis_note"].format(max=money(ax_max).replace(".00", ""))),
        0,
        y,
        W,
        LINE_H,
    )
    y += LINE_H

    def tick_row(prefix: str, y0: float) -> None:
        for t in range(0, ax_max + 1, AXIS_STEP):
            cx = BAR_X + t * scale
            label = f"${t:,}"
            cv.text(
                f"{prefix}-{t}", esc(label), cx - 40, y0, 80, LINE_H, align="center"
            )

    tick_row("tick-top", y)
    y += LINE_H + 6

    # 4. pattern blocks
    groups: list[tuple[float, float]] = []
    a = data["assumptions"]
    for pid in fig["patterns"]:
        p = pats[pid]
        c0 = cell_of(p, 64)
        stored_gib = data["stored_gib"]
        basis = p["basis"]
        ph_ws = "placeholder" in (basis["working_set"], basis["reads_per_object"])
        ph_ch = basis["churn"] == "placeholder"

        head = f"{pid} {p[name_key]}"
        if pid == fig["same"][0]:
            head += marks["same"]
        cv.text(f"head-{pid}", f"<b>{esc(head)}</b>", 0, y, W, 28, size=FONT_H)
        y += 28

        ws_gib = stored_gib * p["working_set_pct"] / 100
        if abs(ws_gib - c0["working_set_gib"]) > 1e-9:
            raise SystemExit(f"{pid}: working_set_pct disagrees with working_set_gib")
        ph = tx["placeholder"].format(m=marks["ph"]) if ph_ws else ""
        p1 = (
            tx["prem1"].format(
                pct=p["working_set_pct"],
                ws=num(ws_gib / 1024),
                n=p["reads_per_object"],
                times="time" if p["reads_per_object"] == 1 else "times",
            )
            + ph
        )
        read_tib = c0["read_gib"] / 1024
        rm = c0["read_gib"] / stored_gib
        if abs(rm - p["read_multiple"]) > 1e-9:
            raise SystemExit(f"{pid}: read_multiple disagrees with read_gib")
        if c0["write_gib"] == 0:
            w = tx["w_none"]
        else:
            wp = c0["write_gib"] / stored_gib * 100
            if abs(wp - p["churn_pct"]) > 1e-9:
                raise SystemExit(f"{pid}: churn_pct disagrees with write_gib")
            w = tx["w_some"].format(
                m3=marks.get("write", ""), w=num(c0["write_gib"] / 1024), wp=num(wp)
            )
            if ph_ch:
                w += tx["placeholder"].format(m=marks["ph"])
        p2 = tx["prem2"].format(r=num(read_tib), rm=mult(rm), w=w)
        pl = wrap(p1, W) + wrap(p2, W)
        cv.text(
            f"prem-{pid}", "<br>".join(esc(l) for l in pl), 0, y, W, LINE_H * len(pl)
        )
        y += LINE_H * len(pl) + 6

        for kib in SIZES:
            c = cell_of(p, kib)
            w_txt = (
                tx["size_w_none"]
                if c["write_objects"] == 0
                else tx["size_w_some"].format(wo=f"{c['write_objects']:,}")
            )
            sh = tx["size_head"].format(
                s=size_name(kib),
                so=f"{c['stored_objects']:,}",
                rr=f"{c['read_requests']:,}",
                w=w_txt,
            )
            for l in wrap(sh, W):
                cv.text(f"size-{pid}-{kib}", esc(l), 0, y, W, LINE_H)
                y += LINE_H
            y += 2
            g_top = y
            for m in fig["methods"]:
                meth = c["methods"][m]
                cats = categorize(meth)
                bid = f"{pid}-{kib}-{m}"
                ml = list(tx["methods"][m])
                if m == "s3_direct" and fig_no == 1:
                    ml[-1] += marks["direct"]
                if max(text_w(l) for l in ml) > LABEL_W - 4:
                    raise SystemExit(f"method label too wide: {ml}")
                cv.text(
                    f"name-{bid}",
                    "<br>".join(esc(l) for l in ml),
                    0,
                    y,
                    LABEL_W,
                    BAR_H + 2 + 22,
                )
                x = float(BAR_X)
                for cat in CATS:
                    amt = cats[cat]
                    if amt == 0:
                        continue
                    wpx = amt * scale
                    inside = money(amt) if wpx >= INSIDE_MIN_PX else ""
                    cv.rect(
                        f"bar-{bid}-{cat}",
                        th["cats"][cat],
                        x,
                        y,
                        wpx,
                        BAR_H,
                        label=inside,
                        stroke=th["seg_stroke"] if wpx >= 2 else None,
                    )
                    x += wpx
                cv.text(
                    f"total-{bid}",
                    f"<b>{esc(meth['subtotal_display'])}</b>",
                    x + 8,
                    y,
                    112,
                    BAR_H,
                    bold=True,
                )
                parts = []
                plain = []
                for cat in CATS:
                    amt = cats[cat]
                    if amt == 0:
                        continue
                    lab = f"{tx['short'][cat]} {money(amt)}"
                    parts.append(f"<font color='{th['cats'][cat]}'>■</font>{esc(lab)}")
                    plain.append("■" + lab)
                bw = text_w("  ".join(plain)) + 8
                if BAR_X + bw > W:
                    raise SystemExit(f"breakdown line too wide: {bid} {bw:.0f}px")
                cv.text(
                    f"brk-{bid}",
                    "&nbsp;&nbsp;".join(parts),
                    BAR_X,
                    y + BAR_H + 2,
                    bw,
                    22,
                    fill=True,
                )
                y += BAR_ROW_H
            groups.append((g_top, y - 8))
            y += 4
        y += 8

    # 5. bottom axis
    tick_row("tick-bot", y)
    y += LINE_H + 12

    # grid lines behind everything, one run per size group
    for gi, (g0, g1) in enumerate(groups):
        for t in range(0, ax_max + 1, AXIS_STEP):
            cx = BAR_X + t * scale
            cv.rect(f"grid-{gi}-{t}", th["grid"], cx - 0.5, g0, 1, g1 - g0, back=True)

    # 6. notes
    cv.text("notes-head", f"<b>{esc(tx['notes_head'])}</b>", 0, y, W, LINE_H)
    y += LINE_H
    for i, (hd, body) in enumerate(tx["notes"][fig_no], 1):
        ls = wrap(hd + body, W)
        if not ls[0].startswith(hd):
            raise SystemExit(f"note heading wrapped: {hd}")
        out = [f"<b>{esc(hd)}</b>{esc(ls[0][len(hd) :])}"] + [esc(l) for l in ls[1:]]
        if hd.startswith(
            marks["same"]
        ):  # names patterns the figure does not draw; define them here
            for other in fig["same"][1]:
                out += [esc(l) for l in wrap(definition(pats[other], lang), W)]
        cv.text(f"note-{i}", "<br>".join(out), 0, y, W, LINE_H * len(out))
        y += LINE_H * len(out)
    y += 10

    # 7. assumption warning
    dep = a["deployment"]
    if dep not in DEPLOYMENT:
        raise SystemExit(f"unknown deployment {dep!r}")
    warn = tx["warn"].format(
        pool=round(a["pool_fraction"] * 100),
        eff=round(a["efficiency_ssd"] * 100),
        thr=num(a["s3files_threshold_kib"]),
        dep=DEPLOYMENT[dep][lang],
    )
    cv.text("warn-head", f"<b>{esc(tx['warn_head'])}</b>", 0, y, W, LINE_H)
    y += LINE_H
    wl = wrap(warn, W)
    cv.text("warn", "<br>".join(esc(l) for l in wl), 0, y, W, LINE_H * len(wl))
    y += LINE_H * len(wl) + 10

    # 8. footnotes
    f1 = wrap(tx["foot1"], W)
    f2 = wrap(
        tx["foot2"].format(
            region=data["region"], snap=data["price_snapshot"], recheck=recheck
        ),
        W,
    )
    fl = f1 + f2
    cv.text("foot", "<br>".join(esc(l) for l in fl), 0, y, W, LINE_H * len(fl))
    y += LINE_H * len(fl)

    height = math.ceil(y)
    gm = ET.Element(
        "mxGraphModel",
        dx="0",
        dy="0",
        grid="0",
        gridSize="10",
        guides="1",
        tooltips="1",
        connect="1",
        arrows="1",
        fold="1",
        page="1",
        pageScale="1",
        pageWidth=str(W),
        pageHeight=str(height),
        math="0",
        shadow="0",
        background=th["bg"],
    )
    root = ET.SubElement(gm, "root")
    ET.SubElement(root, "mxCell", id="0")
    ET.SubElement(root, "mxCell", id="1", parent="0")
    for c in cv.back + cv.cells:
        root.append(c)
    mx = ET.Element("mxfile", host="app.diagrams.net")
    d = ET.SubElement(mx, "diagram", id="cost", name=f"s3files-cost-structure-{fig_no}")
    d.append(gm)
    ET.indent(mx)
    return ET.ElementTree(mx), height


# ---------------------------------------------------------------------------------------------
# Verification (re-reads the written file)
# ---------------------------------------------------------------------------------------------


def plain(v: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", v.replace("<br>", "\n"))).replace(
        "\xa0", " "
    )


def verify_file(
    path: Path,
    data: dict,
    fig_no: int,
    lang: str,
    theme_name: str,
    ax_max: int,
    recheck: str,
) -> dict:
    th = THEMES[theme_name]
    fig = FIGURES[fig_no]
    pats = by_id(data)
    root = ET.parse(path).getroot()
    cells = {c.get("id"): c for c in root.iter("mxCell")}
    scale = BAR_PX_MAX / ax_max
    texts = {cid: plain(c.get("value") or "") for cid, c in cells.items()}
    problems: list[str] = []
    n_totals = n_cats = 0
    money_set: set[str] = set()
    for pid in fig["patterns"]:
        for kib in SIZES:
            c = cell_of(pats[pid], kib)
            for m in fig["methods"]:
                meth = c["methods"][m]
                bid = f"{pid}-{kib}-{m}"
                if texts.get(f"total-{bid}") != meth["subtotal_display"]:
                    problems.append(
                        f"total {bid}: {texts.get(f'total-{bid}')!r} != {meth['subtotal_display']}"
                    )
                n_totals += 1
                money_set.add(meth["subtotal_display"])
                cats = categorize(meth)
                brk = texts.get(f"brk-{bid}", "")
                width_sum = 0.0
                for cat in CATS:
                    amt = cats[cat]
                    seg = cells.get(f"bar-{bid}-{cat}")
                    if amt == 0:
                        if seg is not None:
                            problems.append(f"zero category drawn: {bid}-{cat}")
                        continue
                    if money(amt) not in brk:
                        problems.append(f"{bid}: breakdown lacks {money(amt)}")
                    n_cats += 1
                    money_set.add(money(amt))
                    g = seg.find("mxGeometry")
                    wpx = float(g.get("width"))
                    width_sum += wpx
                    if abs(wpx - amt * scale) > 0.01:
                        problems.append(
                            f"{bid}-{cat}: width {wpx} != {amt * scale:.4f}"
                        )
                    if f"fillColor={th['cats'][cat]};" not in seg.get("style"):
                        problems.append(f"{bid}-{cat}: wrong colour")
                    inside = texts.get(f"bar-{bid}-{cat}", "")
                    if wpx >= INSIDE_MIN_PX and inside != money(amt):
                        problems.append(f"{bid}-{cat}: inside label {inside!r}")
                    if wpx < INSIDE_MIN_PX and inside:
                        problems.append(f"{bid}-{cat}: label on a narrow segment")
                if abs(width_sum - meth["subtotal_usd"] * scale) > 0.05:
                    problems.append(f"{bid}: bar width {width_sum} != total")
    # every footnote mark in the figure has a note, and every note is used
    mark_re = r"※\d|\*\d"
    used = {
        m
        for cid, t in texts.items()
        if not cid.startswith("note-")
        for m in re.findall(mark_re, t)
    }
    noted = [
        re.match(mark_re, texts[f"note-{i}"]).group(0)
        for i in range(1, len(T[lang]["notes"][fig_no]) + 1)
    ]
    if (
        noted != [m for m in T[lang]["marks"][fig_no].values() if m in noted]
        or set(noted) != used
    ):
        problems.append(f"footnote marks {sorted(used)} do not match the notes {noted}")
    # the patterns the same-cost note refers to are defined in the figure
    for other in fig["same"][1]:
        squeeze = {ord(c): None for c in " \n"}  # wrapping moves line breaks, not words
        if definition(pats[other], lang).translate(squeeze) not in texts.get(
            "note-1", ""
        ).translate(squeeze):
            problems.append(f"definition of {other} missing from note-1")
    if (fig_no == 2) != ("direct-note" in cells):
        problems.append("direct-note present on the wrong figure")
    # axis ticks
    ticks = sorted(
        int(cid.split("-")[-1]) for cid in cells if cid.startswith("tick-top-")
    )
    if ticks != list(range(0, ax_max + 1, AXIS_STEP)):
        problems.append(f"ticks {ticks}")
    # font sizes
    sizes = [
        float(s)
        for c in cells.values()
        for s in re.findall(r"fontSize=(\d+(?:\.\d+)?)", c.get("style") or "")
    ]
    if not sizes or min(sizes) < 16:
        problems.append(f"fontSize floor: {min(sizes) if sizes else None}")
    # required words
    blob = re.sub(r"\s+", " ", " ".join(texts.values()))
    for w in T[lang]["required"]:
        needle = w if w else recheck
        if needle not in blob:
            problems.append(f"missing required text {needle!r}")
    for banned in ("損益分岐", "break-even", "breakeven"):
        if banned in blob:
            problems.append(f"sensitivity figure present: {banned}")
    if data["price_snapshot"] not in blob:
        problems.append("price snapshot date missing")
    if problems:
        raise SystemExit(f"VERIFY FAILED {path.name}:\n  " + "\n  ".join(problems))
    return {
        "totals": n_totals,
        "categories": n_cats,
        "money": money_set,
        "min_font": min(sizes),
    }


# ---------------------------------------------------------------------------------------------
# Export
# ---------------------------------------------------------------------------------------------


def png_size(path: Path) -> tuple[int, int]:
    b = path.read_bytes()[:24]
    return struct.unpack(">II", b[16:24])


def export_png(src: Path, dst: Path) -> None:
    if not DRAWIO_CLI.is_file():
        raise SystemExit(
            f"draw.io CLI not found at {DRAWIO_CLI}; cannot export {dst.name}"
        )
    subprocess.run(
        [
            str(DRAWIO_CLI),
            "--export",
            "--format",
            "png",
            "--scale",
            "2",
            "--border",
            str(EXPORT_BORDER),
            "--output",
            str(dst),
            str(src),
        ],
        check=True,
        capture_output=True,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--recheck-date",
        required=True,
        help="date the unit prices were re-read (no default)",
    )
    ap.add_argument("--theme", choices=["light", "dark", "both"], default="both")
    ap.add_argument("--lang", choices=["ja", "en", "both"], default="both")
    ap.add_argument("--diagram-dir", type=Path, default=DIAGRAM_DIR)
    ap.add_argument("--image-dir", type=Path, default=IMAGE_DIR)
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()

    if args.export and not DRAWIO_CLI.is_file():
        raise SystemExit(f"--export needs the draw.io CLI, not found at {DRAWIO_CLI}")
    data = load()
    verify_claims(data)
    ax = axis_max(data)
    langs = ["ja", "en"] if args.lang == "both" else [args.lang]
    themes = ["light", "dark"] if args.theme == "both" else [args.theme]
    args.diagram_dir.mkdir(parents=True, exist_ok=True)
    args.image_dir.mkdir(parents=True, exist_ok=True)
    print(f"axis max {money(ax)} (one value for every figure)")
    for theme in themes:
        seen: dict[tuple[int, str], set[str]] = {}
        for fig_no, fig in FIGURES.items():
            for lang in langs:
                stem = (
                    BASE_NAME
                    + fig["suffix"]
                    + ("-en" if lang == "en" else "")
                    + ("-dark" if theme == "dark" else "")
                )
                path = args.diagram_dir / f"{stem}.drawio"
                tree, height = build_figure(
                    data, fig_no, lang, theme, args.recheck_date, ax
                )
                tree.write(path, encoding="utf-8", xml_declaration=True)
                res = verify_file(
                    path, data, fig_no, lang, theme, ax, args.recheck_date
                )
                seen[(fig_no, lang)] = res["money"]
                print(
                    f"wrote {path}  height={height}  totals={res['totals']}  categories={res['categories']}  minFont={res['min_font']:g}"
                )
                if args.export:
                    png = args.image_dir / f"{stem}@2x.png"
                    export_png(path, png)
                    w, h = png_size(png)
                    print(f"exported {png}  {w}x{h}")
        if len(langs) == 2:
            for fig_no in FIGURES:
                if seen[(fig_no, "ja")] != seen[(fig_no, "en")]:
                    raise SystemExit(f"figure {fig_no}: JA and EN number sets differ")
            print(f"{theme}: JA/EN number sets equal in both figures")
    return 0


if __name__ == "__main__":
    sys.exit(main())
