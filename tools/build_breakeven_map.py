#!/usr/bin/env python3
"""Generate the break-even map (pattern P4, 64 KiB and 4 MiB; JA/EN x light/dark) from the model.

Every number on the map comes from `finops_model.sensitivity_json()` (positions, values, the sides
that move, the flip points) or from `finops_model.baseline_json()` (region, price date, the P4
definition); nothing is typed here. Run: `python3 tools/build_breakeven_map.py [--export]`.
`--export` needs the draw.io CLI for PNG @2x and stops with an error when it is absent.
`tests/test_breakeven_map.py` compares the committed drawio files with the model, so regenerate
whenever the model's output changes. Never edit the `.drawio` files by hand.

Encoding: filled dot = baseline value; filled bar = sourced value (a range when two or more
sourced points exist, a short bar for one); thin short bar = reused or observed value (a point);
outline-only bar = mechanical search range; diamond = the value at which the lower subtotal changes
sides. Colour never carries the kind: the five kinds differ in shape, fill and size.

Layout is decided once from both languages' texts (`Shared`), so the marks and the labels inside the
panels sit at the same coordinates in all four variants. Only the notes and the footnote, which come
after the panels, may differ in height between languages.
"""

from __future__ import annotations

import argparse
import math
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

import build_cost_figures as bcf
import finops_model
from build_cost_figures import FONT, FONT_H, LINE_H, THEMES, W, esc, money, wrap

ROOT = bcf.ROOT
DIAGRAM_DIR = bcf.DIAGRAM_DIR
IMAGE_DIR = bcf.IMAGE_DIR
BASE_NAME = "s3burst-s3files-breakeven-map"

PATTERN = "P4"
SIZES = (64, 4096)
LANGS = ("ja", "en")

TRACK_X0 = 262  # left end of the track; the label column ends at LABEL_COL_W
TRACK_X1 = 836
TRACK_W = TRACK_X1 - TRACK_X0
LABEL_COL_W = 246
ZERO_W = 28  # room at the left of a zero-bearing axis for the "0" probe tick
GAP = 4  # minimum space between two labels in one lane
LANE_H = 22
TRACK_H = 20
ROW_PAD = 12
MAX_HEIGHT = (
    3200  # fail rather than grow past this; shorten the notes before raising it
)
SRC_POINT_W = 8  # one sourced point is drawn as a short bar, not a range
SPREAD_RATIO = (
    2.0  # max/min of the flip values across patterns at which "differ" is written
)
SIDES = ("fsx", "s3_files", "both", "none")
BASIS_ORDER = ("sourced", "observed", "reused", "mechanical")

# Kind -> shape and style. A kind is told apart by shape, fill and size, never by colour alone.
# `fill`/`stroke` name a theme colour ("ink" / "bg") or None; `sw` is the stroke width.
KINDS: dict[str, dict] = {
    "dot": {
        "shape": "ellipse",
        "fill": "ink",
        "stroke": "bg",
        "sw": 2,
        "w": 14,
        "h": 14,
    },
    "src": {"shape": None, "fill": "ink", "stroke": None, "sw": 0, "w": None, "h": 12},
    "pt": {"shape": None, "fill": "ink", "stroke": None, "sw": 0, "w": 3, "h": 20},
    "dom": {"shape": None, "fill": None, "stroke": "ink", "sw": 2, "w": None, "h": 12},
    "flip": {
        "shape": "rhombus",
        "fill": "ink",
        "stroke": "bg",
        "sw": 2,
        "w": 18,
        "h": 18,
    },
}

# ---------------------------------------------------------------------------------------------
# Text. Digits outside `{...}` are limited to TEXT_NUMBER_ALLOWLIST; every number on the map is
# substituted from the model.
# ---------------------------------------------------------------------------------------------

TEXT_NUMBER_ALLOWLIST = {
    "1": "'one assumption at a time' in the subtitle",
    "2": "'two subtotals' and 'two or more sourced points'",
}

TEXT: dict[str, dict[str, str]] = {
    "ja": {
        "title": "損益分岐の地図: P4 の小計の高低が入れ替わる前提の位置",
        "subtitle": "他の前提は基準に固定し、1 つだけ動かして、FSx for ONTAP と S3 Files の主要費目小計を比べます。",
        "leg_dot": "基準の値（モデルが置いた値）",
        "leg_src": "出典のある値（公式ページ・公表表）。出典の点が 2 つ以上なら最小〜最大の範囲、1 点なら範囲でなく点（短い太線）",
        "leg_pt": "再利用または観測の値（別の節が置いた値、このリポジトリの 1 回の観測）。範囲ではなく点",
        "leg_dom": "機械的な探索範囲（値の根拠はなく、モデルが探索した下限〜上限）",
        "leg_flip": "小計の低い側が入れ替わる値",
        "panel_head": "{size}: 基準の前提では {low} の小計が低い",
        "panel_sub": "基準の小計（主要費目小計、月額）: FSx for ONTAP {fsx} / S3 Files {files}",
        "group_fsx": "FSx for ONTAP の小計を動かす前提",
        "group_s3_files": "S3 Files の小計を動かす前提",
        "group_both": "両側の小計を動かす前提",
        "group_none": "P4 の小計を動かさない前提",
        "log": "（対数）",
        "no_flip": "探索範囲では入れ替わらない",
        "flip": "◆ {x}: 低い側は、未満で {below}、以上で {above}",
        "hi_limit": "{v}（適用範囲の上限）",
        "enum_head": "値を列挙して試した前提（軸は引かない）",
        "enum_row": "{label} {key}（{side}。基準 {base}。{kinds}を試した）: {result}",
        "side_fsx": "FSx for ONTAP 側",
        "side_s3_files": "S3 Files 側",
        "side_both": "両側",
        "side_none": "小計は動かない",
        "res_flip": "{vals} で入れ替わる",
        "res_same": "試した値では入れ替わらない",
        "res_none": "P4 の小計が動かない",
        "base_auto": "自動選択（必要なスループットからモデルが段を選ぶ）",
        "kind_sourced": "出典の {n} 値",
        "kind_observed": "観測の {n} 値",
        "kind_reused": "再利用の {n} 値",
        "kind_mechanical": "機械的な {n} 値",
        "kind_join": "、",
        "not_tried": "この大きさでは次の前提を試していません。探索の対象に入っていないだけで、小計に効かないという意味ではありません: {keys}",
        "reason_active": "active_fraction: {size} は S3 Files の取り込みしきい値（{thr} KiB）を超え、小計の計算にアクティブ割合が入らないため、探索していません",
        "key_join": "、",
        "notes_head": "注",
        "n1_lead": "線の長さ:",
        "n1": " 線の長さは不確かさの大きさを表しません。線は、値に付いた根拠の種類と、モデルが探索した範囲を示します。",
        "n1_zero": " 左端に小さな輪郭とゼロの目盛が付いた軸（{axes}）は、値ゼロも試したことを示します。機械的な範囲の帯ではありません。",
        "n1_limit": " 右端に「適用範囲の上限」と付いた軸（{axes}）は、モデルが成り立つ範囲の上限までを探索しており、その先の向きは示していません。",
        "n2_lead": "P4 を例に選んだ理由:",
        "n2": " 書き込みがなく、仮置きと明記されていないパターンのうち、感度の対象にあるのは P4 だけです。",
        "n2_opposite": " 基準の向きは {a} と {b} で逆です。",
        "n2_def": " P4 は保存 {stored} GiB のうち作業セットの {ws}% を、各オブジェクト月あたり {reads} 回読む前提で、いずれも本リポジトリの試算前提です。",
        "n2_diff": " 入れ替わる前提の集合と値はパターンで異なります（例: {size} の {key} は、{n} パターンで {lo}〜{hi}）。",
        "n2_diff_plain": " 入れ替わる前提の集合と値はパターンで異なります。",
        "n2_same": " 感度の対象の {n} パターンで、入れ替わる前提の集合と値は近い範囲にあります。",
        "n2_tail": " 他のパターンは本文の表にあります。",
        "n3_lead": "基準の向きと件数:",
        "n3_dir": " 基準の前提では、{items}。この向きは前提によって入れ替わりえます。",
        "n3_dir_item": "{size} は {low} の小計が低い",
        "n3_dir_join": "、",
        "n3_route": "比べているのは 2 つの小計です。FSx for ONTAP の小計は読み取りをファイルシステムから行い、S3 Access Points の読み取り課金は算入していません。S3 API 直読みは含みません。",
        "n3_denom": "件数は「出典のある点を持つ前提の数 / 分母」です。分母は、この大きさで試し、P4 の小計を動かした前提の数で、その側の前提の総数ではありません。",
        "n3_count": "{size}: FSx for ONTAP {f}、S3 Files {s}、両側 {b}",
        "n3_less": "。S3 Files 側は出典のある点を持つ前提の割合が低い",
        "n3_excl": "{size}: 出典のある点を持つが、この大きさで P4 の小計を動かさないため数えていない前提: {keys}",
        "n3_notried": "試していない前提がある大きさ（{sizes}）では、パネルの末尾に挙げています。",
        "n3_meaning": "件数は出典のある点があるかどうかを数えたもので、前提の確からしさや値の不確かさを表しません。提供形態や段のような選択も、出典のある点があれば数えます。",
        "foot": "各軸の値はモデルの計算で、実測ではありません。小計は主要費目小計で月額総額ではありません。{region}、単価は {snap} に取得しました。",
        "val_join": "、",
    },
    "en": {
        "title": "Break-even map: where the lower subtotal changes sides for P4",
        "subtitle": "Each other assumption is held at its baseline while one assumption moves; the comparison is between the FSx for ONTAP and S3 Files major-line-item subtotals.",
        "leg_dot": "Baseline value (the value the model uses)",
        "leg_src": "Sourced value (official pages and published tables): a min-to-max range for two or more sourced points, a short bar for one point",
        "leg_pt": "Reused or observed value (set in another section, or one observation in this repository): a point, not a range",
        "leg_dom": "Mechanical search range (no source for the values; the lower to upper bound the model searched)",
        "leg_flip": "Value at which the lower subtotal changes sides",
        "panel_head": "{size}: under the baseline assumptions, the {low} subtotal is lower",
        "panel_sub": "Baseline subtotals (major line items, per month): FSx for ONTAP {fsx} / S3 Files {files}",
        "group_fsx": "Assumptions that move the FSx for ONTAP subtotal",
        "group_s3_files": "Assumptions that move the S3 Files subtotal",
        "group_both": "Assumptions that move both subtotals",
        "group_none": "Assumptions that move neither P4 subtotal",
        "log": " (log)",
        "no_flip": "Does not change sides within the search range",
        "flip": "◆ {x}: lower side: {below} below, {above} at or above",
        "hi_limit": "{v} (upper limit of the applicable range)",
        "enum_head": "Assumptions tried at listed values (no axis)",
        "enum_row": "{label} {key} ({side}; baseline {base}; {kinds} tried): {result}",
        "side_fsx": "FSx for ONTAP side",
        "side_s3_files": "S3 Files side",
        "side_both": "both sides",
        "side_none": "subtotals do not move",
        "res_flip": "changes sides at {vals}",
        "res_same": "does not change sides at the values tried",
        "res_none": "the P4 subtotals do not move",
        "base_auto": "automatic (the model picks the tier from the required throughput)",
        "kind_sourced": "{n} sourced",
        "kind_observed": "{n} observed",
        "kind_reused": "{n} reused",
        "kind_mechanical": "{n} mechanical",
        "kind_join": ", ",
        "not_tried": "Not tried at this size. These assumptions are outside the search at this size; that does not mean they have no effect on the subtotals: {keys}",
        "reason_active": "active_fraction: {size} is above the S3 Files import threshold ({thr} KiB), so the active share does not enter the subtotal and was not searched",
        "key_join": ", ",
        "notes_head": "Notes",
        "n1_lead": "Line length:",
        "n1": " It does not represent uncertainty. A line shows the kind of evidence behind a value and the range the model searched.",
        "n1_zero": " An axis with a small outline and a zero tick at its left end ({axes}) was also tried at zero; it is not a mechanical-range band.",
        "n1_limit": " An axis whose right end reads 'upper limit of the applicable range' ({axes}) was searched up to the limit of the range where the model holds, and the figure shows nothing beyond it.",
        "n2_lead": "Why P4 is the example:",
        "n2": " Among the patterns with no writes that are not labeled placeholders, P4 is the only one in the sensitivity set.",
        "n2_opposite": " The baseline direction is opposite at {a} and {b}.",
        "n2_def": " P4 reads a {ws}% working set of the {stored} GiB stored, {reads} times per object per month; both are repository assumptions.",
        "n2_diff": " The set of assumptions that flip the result, and their values, differ by pattern (for example {key} at {size}: {lo} to {hi} across {n} patterns).",
        "n2_diff_plain": " The set of assumptions that flip the result, and their values, differ by pattern.",
        "n2_same": " Across the {n} patterns in the sensitivity set, the same assumptions flip the result at close values.",
        "n2_tail": " The other patterns are in the tables in the body.",
        "n3_lead": "Baseline direction and counts:",
        "n3_dir": " Under the baseline assumptions, {items}. This direction can reverse when the assumptions change.",
        "n3_dir_item": "the {low} subtotal is lower at {size}",
        "n3_dir_join": "; ",
        "n3_route": "The comparison is between two subtotals. The FSx for ONTAP subtotal reads from the file system and includes no S3 Access Points read charge. Reading directly through the S3 API is not included.",
        "n3_denom": "Each count reads 'assumptions with sourced points / denominator'. The denominator is the number of assumptions tried at this size that moved a P4 subtotal; it is not the total number of assumptions on that side.",
        "n3_count": "{size}: FSx for ONTAP side {f}, S3 Files side {s}, both {b}",
        "n3_less": ". The S3 Files side has a lower share of assumptions with sourced points",
        "n3_excl": "{size}: assumptions with sourced points that are not counted because they do not move a P4 subtotal at this size: {keys}",
        "n3_notried": "Sizes with assumptions not tried ({sizes}) list them at the end of the panel.",
        "n3_meaning": "The counts record whether sourced points exist. They do not express how reliable an assumption or its value is. Choices such as the deployment type or a tier are counted too when they have sourced points.",
        "foot": "Axis values are model calculations, not measurements. Subtotals are major-line-item subtotals, not monthly totals. {region}; unit prices retrieved {snap}.",
        "val_join": ", ",
    },
}

LABELS: dict[str, dict[str, str]] = {
    "ja": {
        "pool_fraction": "キャパシティプールへ落とす割合",
        "efficiency_ssd": "SSD 層のストレージ効率",
        "pool_efficiency_retention": "プール層に残る効率の割合",
        "ssd_headroom": "SSD のプロビジョニング余裕",
        "active_fraction": "高性能層のアクティブ割合",
        "metadata_multiplier": "メタデータ操作数の倍率",
        "read_scale": "月間読み取り量の倍率",
        "stored_tib": "保存量（TiB）",
        "deployment": "デプロイ形態",
        "throughput_mbps": "スループットキャパシティ",
        "s3files_threshold_kib": "S3 Files の取り込みしきい値（KiB）",
        "first_read_mode": "初回ストリームの個数",
        "first_read_stream_billing": "初回ストリームの読み取り課金",
    },
    "en": {
        "pool_fraction": "Share moved to capacity pool",
        "efficiency_ssd": "SSD-tier storage efficiency",
        "pool_efficiency_retention": "Efficiency kept in pool tier",
        "ssd_headroom": "SSD provisioning headroom",
        "active_fraction": "High-perf. tier active share",
        "metadata_multiplier": "Metadata ops multiplier",
        "read_scale": "Monthly read multiplier",
        "stored_tib": "Stored volume (TiB)",
        "deployment": "Deployment type",
        "throughput_mbps": "Throughput capacity",
        "s3files_threshold_kib": "S3 Files import threshold (KiB)",
        "first_read_mode": "First-stream object count",
        "first_read_stream_billing": "First-stream read billing",
    },
}


def _check_text_numbers() -> None:
    """Digits outside `{...}` and outside the product words (S3, P4) must be on the allowlist."""
    for lang, table in TEXT.items():
        for name, value in table.items():
            bare = re.sub(r"\{[^}]*\}", "", value)
            bare = re.sub(r"\b(?:S3|P4)\b", "", bare)
            for digits in re.findall(r"\d+", bare):
                if digits not in TEXT_NUMBER_ALLOWLIST:
                    raise SystemExit(
                        f"TEXT[{lang}][{name}]: hand-typed number {digits!r}"
                    )


# ---------------------------------------------------------------------------------------------
# Number formats (the test implements these separately)
# ---------------------------------------------------------------------------------------------


def _compact_exp(s: str) -> str:
    """'1.5e+06' -> '1.5e6', '9.77e-04' -> '9.77e-4'."""
    mant, exp = s.split("e")
    return f"{mant}e{int(exp)}"


def fmt_value(x: float) -> str:
    """A value on the map: 3 significant digits; whole numbers as integers; 1,000-9,999 with a
    thousands separator; 10,000 and above, and below 0.001, as `3.17e4`."""
    if x == 0:
        return "0"
    r = float(f"{x:.3g}")
    a = abs(r)
    if a >= 10000 or a < 0.001:
        mant, exp = f"{r:.2e}".split("e")
        mant = mant.rstrip("0").rstrip(".")
        return f"{mant}e{int(exp)}"
    if a >= 1000:
        return f"{round(r):,}"
    return f"{r:.10g}"


def fmt_edge(m: float) -> str:
    """An axis end: `2^k` for a power of two that would need `e` notation; otherwise the fewest of
    3-6 significant digits that return the value; a value that needs more is rounded to 6."""
    if m == 0:
        return "0"
    if m >= 10000 or m < 0.001:
        mant, exp = math.frexp(m)
        if mant == 0.5:
            return f"2^{exp - 1}"
    for n in (3, 4, 5, 6):
        s = f"{m:.{n}g}"
        if float(s) == m:
            break
    else:
        s = f"{m:.6g}"
    if "e" in s:
        return _compact_exp(s)
    x = float(s)
    if 1000 <= abs(x) < 10000 and x == int(x):
        return f"{int(x):,}"
    return s


def fmt_plain(x: object) -> str:
    """A baseline or tried value outside an axis: whole floats as integers, strings as they are."""
    if isinstance(x, float):
        return fmt_value(x)
    return str(x)


# ---------------------------------------------------------------------------------------------
# Model-derived facts (no layout here)
# ---------------------------------------------------------------------------------------------


def sigma(d: float) -> int:
    """-1 when S3 Files is lower, +1 otherwise; d == 0 falls to +1, as in the model."""
    return -1 if d < 0 else 1


def _p4(cells: dict) -> dict:
    return cells[PATTERN]


class Panel:
    """Everything one panel (one size) draws, derived from the two JSON documents."""

    def __init__(self, sens: dict, base: dict, kib: int):
        self.kib = kib
        axes = sens["assumption_axes"]
        j0 = next(r for r in sens["scenarios"][str(kib)] if r["id"] == "J0")
        c0 = _p4(j0["cells"])
        if c0["out_of_model_range"]:
            raise SystemExit(
                f"{kib} KiB: the J0 cell is outside the model's applicable range"
            )
        self.fsx = c0["fsx_s3ap_usd"]
        self.files = c0["s3_files_usd"]
        self.j0_sigma = sigma(self.files - self.fsx)
        self.low = "S3 Files" if self.j0_sigma < 0 else "FSx for ONTAP"
        rows = [r for r in sens["one_at_a_time"][str(kib)]]
        self.rows: dict[str, list[dict]] = {}
        for r in rows:
            if _p4(r["cells"])["out_of_model_range"]:
                raise SystemExit(
                    f"{kib} KiB: {r['key']}={r['value']} is outside the applicable range"
                )
            self.rows.setdefault(r["key"], []).append(r)
        self.moves = {k: a["moves_p4"][str(kib)] for k, a in axes.items()}
        tried = {k for k, m in self.moves.items() if m is not None}
        if tried != set(self.rows):
            raise SystemExit(
                f"{kib} KiB: moves_p4 and one_at_a_time disagree on the tried keys"
            )
        self.not_tried = [k for k in axes if self.moves[k] is None]
        # Continuous axes: the break-even entries of P4, in the model's order.
        self.axis_keys: list[str] = []
        self.be: dict[str, dict] = {}
        for key, entries in sens["break_even"].items():
            hit = [
                e for e in entries if e["pattern"] == PATTERN and e["size_kib"] == kib
            ]
            if hit:
                self.be[key] = hit[0]
                self.axis_keys.append(key)
        for key in self.axis_keys:
            if self.moves[key] is None:
                raise SystemExit(
                    f"{kib} KiB: {key} has a break-even entry but was not tried"
                )
        for key in axes:
            continuous = axes[key]["scale"] in ("linear", "log")
            if continuous and self.moves[key] is not None and key not in self.be:
                raise SystemExit(
                    f"{kib} KiB: {key} was tried but has no break-even entry"
                )
        self.enum_keys = [
            k
            for k, a in axes.items()
            if a["scale"] in ("enum", "discrete") and self.moves[k] is not None
        ]
        for key in self.axis_keys:
            for be in self.be[key]["break_evens"]:
                if be["step_change"]:
                    raise SystemExit(
                        f"{kib} KiB: {key} has a step change; no mark describes it"
                    )
        # A tried row on the other side of J0 needs a break-even to explain it.
        for key in self.axis_keys:
            flips = any(
                sigma(_p4(r["cells"])["s3_files_usd"] - _p4(r["cells"])["fsx_s3ap_usd"])
                != self.j0_sigma
                for r in self.rows[key]
            )
            if flips and not self.be[key]["break_evens"]:
                raise SystemExit(
                    f"{kib} KiB: {key} has a flipped row but no break-even"
                )
        self.groups: list[tuple[str, list[str]]] = []
        for side in SIDES:
            keys = [k for k in self.axis_keys if self.moves[k] == side]
            if keys:
                self.groups.append((side, keys))
        # Counts: denominator = tried keys that move a side; numerator = those with a sourced row.
        self.count: dict[str, tuple[int, int]] = {}
        for side in ("fsx", "s3_files", "both"):
            keys = [k for k in self.rows if self.moves[k] == side]
            self.count[side] = (sum(1 for k in keys if self.sourced(k)), len(keys))
        self.excluded = [
            k for k in self.rows if self.moves[k] == "none" and self.sourced(k)
        ]
        (nf, df), (ns, ds) = self.count["fsx"], self.count["s3_files"]
        self.less = df >= 1 and ds >= 1 and ns * df < nf * ds

    def sourced(self, key: str) -> list[float | str]:
        return sorted(
            {r["value"] for r in self.rows.get(key, []) if r["basis"] == "sourced"},
            key=str,
        )

    def src_values(self, key: str) -> list[float]:
        return sorted(
            {float(r["value"]) for r in self.rows[key] if r["basis"] == "sourced"}
        )

    def pt_values(self, key: str) -> list[float]:
        return sorted(
            {
                float(r["value"])
                for r in self.rows[key]
                if r["basis"] in ("reused", "observed")
            }
        )

    def truncated(self, key: str, sens: dict) -> bool:
        return self.be[key]["hi"] < sens["assumption_axes"][key]["domain_hi"]


def spread_example(sens: dict) -> tuple[bool, tuple | None]:
    """Whether the flip set or values differ by pattern, and the (kib, key, n, lo, hi) of the widest."""
    differ = False
    best: tuple | None = None
    best_ratio = 0.0
    for key, entries in sens["break_even"].items():
        for kib in SIZES:
            cells = [e for e in entries if e["size_kib"] == kib]
            have = [bool(e["break_evens"]) for e in cells]
            if any(have) and not all(have):
                differ = True
            xs = [be["x_star"] for e in cells for be in e["break_evens"]]
            if len(xs) >= 2 and min(xs) > 0:
                ratio = max(xs) / min(xs)
                if ratio >= SPREAD_RATIO:
                    differ = True
                if ratio > best_ratio:
                    best_ratio = ratio
                    best = (kib, key, len(xs), min(xs), max(xs))
    return differ, best


def verify_claims(sens: dict, base: dict) -> None:
    """Statements the map makes in prose must hold in the data, or the build fails."""
    if sens.get("schema_version") != 1:
        raise SystemExit(
            f"sensitivity_json schema_version {sens.get('schema_version')!r}, expected 1"
        )
    if "assumption_axes" not in sens:
        raise SystemExit("sensitivity_json has no assumption_axes; the map needs it")
    if sens["sizes_kib"] != list(SIZES):
        raise SystemExit(f"sizes_kib {sens['sizes_kib']} != {list(SIZES)}")
    if PATTERN not in sens["patterns"]:
        raise SystemExit(f"{PATTERN} is not in the sensitivity patterns")
    for key in ("region", "price_snapshot", "stored_gib", "patterns", "assumptions"):
        if key not in base:
            raise SystemExit(f"baseline_json has no {key!r}")
    pats = {p["id"]: p for p in base["patterns"]}
    # Selection: the read-only, non-placeholder pattern among the sensitivity patterns is one.
    picked = [
        pid
        for pid in sens["patterns"]
        if pats[pid]["churn_pct"] == 0 and not pats[pid]["placeholder"]
    ]
    if picked != [PATTERN]:
        raise SystemExit(f"selection criterion picks {picked}, expected [{PATTERN!r}]")
    p4 = pats[PATTERN]
    for k in ("working_set", "reads_per_object"):
        if p4["basis"][k] != "repository":
            raise SystemExit(
                f"{PATTERN} {k} basis is {p4['basis'][k]!r}; the note says repository"
            )
    for kib in SIZES:
        cells = [c for c in p4["cells"] if c["size_kib"] == kib]
        if len(cells) != 1:
            raise SystemExit(f"{PATTERN}: expected exactly one {kib} KiB cell")
        cell = cells[0]
        # The route note: the FSx for ONTAP subtotal carries no S3 Access Points GET line.
        if any(
            l["label"].startswith("GET") for l in cell["methods"]["fsx_s3ap"]["lines"]
        ):
            raise SystemExit(
                "the route note says S3 Access Points reads are excluded; a GET line exists"
            )
        j0 = next(r for r in sens["scenarios"][str(kib)] if r["id"] == "J0")
        c0 = _p4(j0["cells"])
        if (
            abs(c0["fsx_s3ap_usd"] - cell["methods"]["fsx_s3ap"]["subtotal_usd"]) > 1e-6
            or abs(c0["s3_files_usd"] - cell["methods"]["s3_files"]["subtotal_usd"])
            > 1e-6
        ):
            raise SystemExit(f"{kib} KiB: J0 differs from the baseline grid cell")
    thr = sens["assumption_axes"]["s3files_threshold_kib"]["baseline"]
    if thr != base["assumptions"]["s3files_threshold_kib"]:
        raise SystemExit(
            "s3files_threshold_kib baseline differs between the two documents"
        )


# ---------------------------------------------------------------------------------------------
# Drawing
# ---------------------------------------------------------------------------------------------


class MapCanvas(bcf.Canvas):
    """Adds the three shapes the cost figures do not need: ellipse, rhombus, outline-only bar."""

    def mark(self, cid: str, kind: str, x: float, y: float, w: float, h: float) -> None:
        spec = KINDS[kind]
        theme = self.t
        parts = [spec["shape"]] if spec["shape"] else ["rounded=0"]
        parts += ["whiteSpace=nowrap", "html=0"]
        parts.append(
            f"fillColor={'none' if spec['fill'] is None else theme[spec['fill']]}"
        )
        if spec["stroke"] is None:
            parts.append("strokeColor=none")
        else:
            parts += [
                f"strokeColor={theme[spec['stroke']]}",
                f"strokeWidth={spec['sw']}",
            ]
        parts.append(f"fontSize={FONT}")
        self._add(self.cells, cid, "", x, y, w, h, ";".join(parts) + ";")


class Shared:
    """Widths and line counts both languages need, taken as the larger of the two."""

    def __init__(self, widths: dict[str, float], lines: dict[str, int]):
        self.widths = widths
        self.lines = lines

    @classmethod
    def merge(cls, parts: list[tuple[dict, dict]]) -> Shared:
        widths: dict[str, float] = {}
        lines: dict[str, int] = {}
        for w, n in parts:
            for k, v in w.items():
                widths[k] = max(widths.get(k, 0.0), v)
            for k, v in n.items():
                lines[k] = max(lines.get(k, 0), v)
        return cls(widths, lines)


class Lane:
    def __init__(self) -> None:
        self.spans: list[tuple[float, float]] = []

    def fits(self, x0: float, x1: float) -> bool:
        return all(x1 + GAP <= a or x0 >= b + GAP for a, b in self.spans)

    def add(self, x0: float, x1: float) -> None:
        self.spans.append((x0, x1))


class Builder:
    def __init__(
        self, sens: dict, base: dict, lang: str, theme: str, shared: Shared | None
    ):
        self.sens, self.base = sens, base
        self.lang, self.theme_name = lang, theme
        self.tx = TEXT[lang]
        self.shared = shared
        self.rec_w: dict[str, float] = {}
        self.rec_n: dict[str, int] = {}
        self.panels = [Panel(sens, base, kib) for kib in SIZES]
        self.axes = sens["assumption_axes"]
        self.cv = MapCanvas(THEMES[theme])

    # -- measurement shared between languages ------------------------------------------------

    def width(self, cid: str, text: str, size: int = FONT, bold: bool = False) -> float:
        m = bcf.text_w(text, size, bold)
        self.rec_w[cid] = m
        if self.shared is None:
            return m
        w = self.shared.widths[cid]
        if m > w + 1e-6:
            raise SystemExit(f"{cid}: text wider than the shared width")
        return w

    def count(self, cid: str, n: int) -> int:
        self.rec_n[cid] = n
        if self.shared is None:
            return n
        if n > self.shared.lines[cid]:
            raise SystemExit(f"{cid}: more lines than the shared count")
        return self.shared.lines[cid]

    def block(
        self,
        cid: str,
        text: str,
        y: float,
        *,
        size: int = FONT,
        bold: bool = False,
        x: float = 0,
        w: float = W,
        shared: bool = True,
        width: float | None = None,
    ) -> float:
        lh = 28 if size > FONT else LINE_H
        lines = wrap(text, (width or w) - 4, size, bold)
        n = self.count(cid, len(lines)) if shared else len(lines)
        html = "<br>".join(esc(l) for l in lines)
        if bold:
            html = f"<b>{html}</b>"
        self.cv.text(cid, html, x, y, w, n * lh, size=size, bold=bold)
        # A language with fewer lines than the shared count must not centre its text in the taller box.
        self.cv.cells[-1].set(
            "style",
            self.cv.cells[-1]
            .get("style")
            .replace("verticalAlign=middle", "verticalAlign=top"),
        )
        return y + n * lh

    # -- positions ---------------------------------------------------------------------------

    def px(self, key: str, v: float) -> float:
        a = self.axes[key]
        x0 = TRACK_X0 + (ZERO_W if a["zero_probe"] else 0)
        cw = TRACK_X1 - x0
        lo = a["lo"]
        return x0 + self.frac(a["scale"], lo, self.cur_hi, v) * cw

    @staticmethod
    def frac(scale: str, lo: float, hi: float, v: float) -> float:
        if scale == "log":
            return (math.log2(v) - math.log2(lo)) / (math.log2(hi) - math.log2(lo))
        return (v - lo) / (hi - lo)

    def inside(self, key: str, v: float, what: str, kib: int) -> None:
        a = self.axes[key]
        if v < a["lo"] * (1 - 1e-9) - 1e-12 or v > self.cur_hi * (1 + 1e-9) + 1e-12:
            raise SystemExit(
                f"{kib} KiB {key}: {what} {v} is outside [{a['lo']}, {self.cur_hi}]"
            )

    # -- one axis row ------------------------------------------------------------------------

    def plan_row(self, p: Panel, key: str) -> dict:
        a = self.axes[key]
        be = p.be[key]
        self.cur_hi = be["hi"]
        kib = p.kib
        zero = a["zero_probe"]
        x_cont0 = TRACK_X0 + (ZERO_W if zero else 0)
        tag = f"{kib}-{key}"
        # marks (centre x)
        base_v = a["baseline"]
        self.inside(key, base_v, "baseline", kib)
        src = p.src_values(key)
        for v in src:
            self.inside(key, v, "sourced value", kib)
        pts = p.pt_values(key)
        for v in pts:
            self.inside(key, v, "reused/observed value", kib)
        flips = sorted(be["break_evens"], key=lambda b: b["x_star"])
        for b in flips:
            self.inside(key, b["x_star"], "flip", kib)
        # upper lane (value labels), fixed order: baseline, sourced, reused/observed left to right
        items: list[tuple[str, str, float]] = [
            (f"val-{tag}-base", fmt_value(base_v), self.px(key, base_v))
        ]
        if len(src) >= 2:
            lo_x, hi_x = self.px(key, src[0]), self.px(key, src[-1])
            items.append(
                (
                    f"val-{tag}-src",
                    f"{fmt_value(src[0])}–{fmt_value(src[-1])}",
                    (lo_x + hi_x) / 2,
                )
            )
        elif len(src) == 1:
            items.append((f"val-{tag}-src", fmt_value(src[0]), self.px(key, src[0])))
        for i, v in enumerate(pts):
            items.append((f"val-{tag}-pt{i}", fmt_value(v), self.px(key, v)))
        up, xup = Lane(), Lane()
        upper, extra_upper = [], []
        for cid, text, cx in items:
            w = self.width(cid, text)
            x0 = cx - w / 2
            if x0 < 0 or x0 + w > W:
                raise SystemExit(f"{cid}: label leaves the canvas")
            if up.fits(x0, x0 + w):
                up.add(x0, x0 + w)
                upper.append((cid, text, x0, w, "center"))
            elif xup.fits(x0, x0 + w):
                xup.add(x0, x0 + w)
                extra_upper.append((cid, text, x0, w, "center"))
            else:
                raise SystemExit(
                    f"{cid}: no room for the label even in the extra upper lane"
                )
        # lower lane: edge values first, then the flip / no-flip sentence
        low = Lane()
        lower: list[tuple] = []
        extra_lower: list[tuple] = []

        def put(cid: str, text: str, x0: float, w: float, align: str) -> None:
            if not low.fits(x0, x0 + w):
                raise SystemExit(f"{cid}: overlaps another lower-lane label")
            low.add(x0, x0 + w)
            lower.append((cid, text, x0, w, align))

        if zero:
            w = self.width(f"lbl-{tag}-zero", "0")
            put(f"lbl-{tag}-zero", "0", TRACK_X0, w, "left")
        lo_text = fmt_edge(a["lo"])
        w_lo = self.width(f"lbl-{tag}-lo", lo_text)
        put(f"lbl-{tag}-lo", lo_text, x_cont0, w_lo, "left")
        hi_text = fmt_edge(be["hi"])
        if p.truncated(key, self.sens):
            hi_text = self.tx["hi_limit"].format(v=hi_text)
        w_hi = self.width(f"lbl-{tag}-hi", hi_text)
        put(f"lbl-{tag}-hi", hi_text, TRACK_X1 - w_hi, w_hi, "right")
        free_l = x_cont0 + w_lo + GAP
        free_r = TRACK_X1 - w_hi - GAP
        if not flips:
            text = self.tx["no_flip"]
            cid = f"lbl-{tag}-noflip"
            w = self.width(cid, text)
            if w <= free_r - free_l:
                put(cid, text, free_l + (free_r - free_l - w) / 2, w, "left")
            else:
                if w > TRACK_W:
                    raise SystemExit(f"{cid}: wider than the track")
                extra_lower.append((cid, text, float(TRACK_X0), w, "left"))
        for i, b in enumerate(flips):
            fx = self.px(key, b["x_star"])
            text = self.tx["flip"].format(
                x=fmt_value(b["x_star"]), below=b["low_below"], above=b["low_above"]
            )
            cid = f"lbl-{tag}-flip{i}"
            w = self.width(cid, text)
            if w > TRACK_W:
                raise SystemExit(f"{cid}: wider than the track")
            right_x0 = fx + 14
            if right_x0 + w <= free_r and low.fits(right_x0, right_x0 + w):
                put(cid, text, right_x0, w, "left")
            elif free_l + w <= fx - 14 and low.fits(free_l, free_l + w):
                put(cid, text, free_l, w, "left")
            else:
                extra_lower.append((cid, text, float(TRACK_X0), w, "left"))
        return {
            "key": key,
            "kib": kib,
            "src": src,
            "pts": pts,
            "flips": flips,
            "zero": zero,
            "upper": upper,
            "extra_upper": extra_upper,
            "lower": lower,
            "extra_lower": extra_lower,
            "hi": be["hi"],
        }

    def draw_row(self, plan: dict, y: float) -> float:
        cv, key, kib = self.cv, plan["key"], plan["kib"]
        a = self.axes[key]
        tag = f"{kib}-{key}"
        self.cur_hi = plan["hi"]
        top = y + (LANE_H if plan["extra_upper"] else 0)
        cy = top + LANE_H + TRACK_H / 2
        # label column
        label = LABELS[self.lang][key]
        keytxt = key + (self.tx["log"] if a["scale"] == "log" else "")
        for text, name in ((label, "name"), (keytxt, "key")):
            if bcf.text_w(text) > LABEL_COL_W:
                raise SystemExit(
                    f"{name} for {key} is wider than {LABEL_COL_W}px: {text}"
                )
        cv.text(f"name-{tag}", esc(label), 0, top + 11, LABEL_COL_W + 4, LINE_H)
        cv.text(f"key-{tag}", esc(keytxt), 0, top + 33, LABEL_COL_W + 4, LINE_H)
        # marks, bottom layer first
        x_cont0 = TRACK_X0 + (ZERO_W if plan["zero"] else 0)
        hi_x = self.px(key, plan["hi"])
        cv.mark(f"dom-{tag}", "dom", x_cont0, cy - 6, hi_x - x_cont0, KINDS["dom"]["h"])
        if plan["zero"]:
            cv.mark(f"dom-{tag}-zero", "dom", TRACK_X0, cy - 6, 6, KINDS["dom"]["h"])
        src = plan["src"]
        if len(src) >= 2:
            x0, x1 = self.px(key, src[0]), self.px(key, src[-1])
            cv.mark(f"src-{tag}", "src", x0, cy - 6, x1 - x0, KINDS["src"]["h"])
        elif len(src) == 1:
            cx = self.px(key, src[0])
            cv.mark(
                f"src-{tag}",
                "src",
                cx - SRC_POINT_W / 2,
                cy - 6,
                SRC_POINT_W,
                KINDS["src"]["h"],
            )
        for i, v in enumerate(plan["pts"]):
            cv.mark(f"pt-{tag}-{i}", "pt", self.px(key, v) - 1.5, cy - 10, 3, 20)
        cv.mark(f"dot-{tag}", "dot", self.px(key, a["baseline"]) - 7, cy - 7, 14, 14)
        for i, b in enumerate(plan["flips"]):
            cv.mark(
                f"flip-{tag}-{i}", "flip", self.px(key, b["x_star"]) - 9, cy - 9, 18, 18
            )
        # labels
        up_y, xup_y = top, top - LANE_H
        for lane, ly in (
            (plan["upper"], up_y),
            (plan["extra_upper"], xup_y if plan["extra_upper"] else up_y),
        ):
            for cid, text, x0, w, align in lane:
                cv.text(cid, esc(text), x0, ly, w, LANE_H, align=align)
        low_y = top + LANE_H + TRACK_H
        for cid, text, x0, w, align in plan["lower"]:
            cv.text(cid, esc(text), x0, low_y, w, LANE_H, align=align)
        for j, (cid, text, x0, w, align) in enumerate(plan["extra_lower"]):
            cv.text(
                cid, esc(text), x0, low_y + LANE_H * (j + 1), w, LANE_H, align=align
            )
        return low_y + LANE_H * (1 + len(plan["extra_lower"])) + ROW_PAD

    # -- enumerated rows ---------------------------------------------------------------------

    def enum_text(self, p: Panel, key: str) -> str:
        tx = self.tx
        a = self.axes[key]
        rows = p.rows[key]
        base_v = a["baseline"]
        base = tx["base_auto"] if base_v == "auto" else fmt_plain(base_v)
        counts = Counter(r["basis"] for r in rows)
        kinds = tx["kind_join"].join(
            tx[f"kind_{b}"].format(n=counts[b]) for b in BASIS_ORDER if counts[b]
        )
        flipped = [
            fmt_plain(r["value"])
            for r in rows
            if sigma(_p4(r["cells"])["s3_files_usd"] - _p4(r["cells"])["fsx_s3ap_usd"])
            != p.j0_sigma
        ]
        if flipped:
            result = tx["res_flip"].format(vals=tx["val_join"].join(flipped))
        elif p.moves[key] == "none":
            result = tx["res_none"]
        else:
            result = tx["res_same"]
        return tx["enum_row"].format(
            label=LABELS[self.lang][key],
            key=key,
            side=tx[f"side_{p.moves[key]}"],
            base=base,
            kinds=kinds,
            result=result,
        )

    # -- the whole figure --------------------------------------------------------------------

    def build(self) -> tuple[ET.ElementTree, int]:
        tx, cv = self.tx, self.cv
        y = 0.0
        y = self.block("title", tx["title"], y, size=FONT_H, bold=True)
        y = self.block("subtitle", tx["subtitle"], y)
        y += 8
        # legend
        for kind, name in (
            ("dot", "leg_dot"),
            ("src", "leg_src"),
            ("pt", "leg_pt"),
            ("dom", "leg_dom"),
            ("flip", "leg_flip"),
        ):
            spec = KINDS[kind]
            h = spec["h"]
            w = spec["w"] if spec["w"] else 40
            cv.mark(f"leg-{kind}", kind, 22 - w / 2, y + 11 - h / 2, w, h)
            y = self.block(f"legtxt-{kind}", tx[name], y, x=52, w=W - 52)
            y += 4
        y += 8
        for p in self.panels:
            y = self.draw_panel(p, y)
        y = self.draw_notes(y)
        height = math.ceil(y)
        if height > MAX_HEIGHT:
            raise SystemExit(
                f"figure height {height}px exceeds {MAX_HEIGHT}px; shorten the notes"
            )
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
            background=THEMES[self.theme_name]["bg"],
        )
        root = ET.SubElement(gm, "root")
        ET.SubElement(root, "mxCell", id="0")
        ET.SubElement(root, "mxCell", id="1", parent="0")
        for c in cv.cells:
            root.append(c)
        mx = ET.Element("mxfile", host="app.diagrams.net")
        d = ET.SubElement(mx, "diagram", id="breakeven", name="s3files-breakeven-map")
        d.append(gm)
        ET.indent(mx)
        return ET.ElementTree(mx), height

    def draw_panel(self, p: Panel, y: float) -> float:
        tx = self.tx
        size = bcf.size_name(p.kib)
        y = self.block(
            f"phead-{p.kib}",
            tx["panel_head"].format(size=size, low=p.low),
            y,
            size=FONT_H,
            bold=True,
        )
        y = self.block(
            f"psub-{p.kib}",
            tx["panel_sub"].format(fsx=money(p.fsx), files=money(p.files)),
            y,
        )
        y += 8
        for side, keys in p.groups:
            y = self.block(f"ghead-{p.kib}-{side}", tx[f"group_{side}"], y, bold=True)
            y += 4
            for key in keys:
                y = self.draw_row(self.plan_row(p, key), y)
        if p.enum_keys:
            y += 4
            y = self.block(f"ehead-{p.kib}", tx["enum_head"], y, bold=True)
            y += 4
            for key in p.enum_keys:
                y = self.block(f"enum-{p.kib}-{key}", self.enum_text(p, key), y)
                y += 6
        if p.not_tried:
            keys = tx["key_join"].join(p.not_tried)
            y = self.block(f"nottried-{p.kib}", tx["not_tried"].format(keys=keys), y)
            y += 4
            if "active_fraction" in p.not_tried:
                thr = self.axes["s3files_threshold_kib"]["baseline"]
                over = p.kib > thr
                missing = "active_fraction" not in p.be
                if over != missing:
                    raise SystemExit(
                        f"{size}: the reason for skipping active_fraction (threshold {thr}) does not match the model"
                    )
                y = self.block(
                    f"reason-{p.kib}",
                    tx["reason_active"].format(size=size, thr=fmt_plain(float(thr))),
                    y,
                )
        return y + 24

    def join(self, *pieces: str) -> str:
        """Sentences carry no leading space in the table; Japanese joins them bare, English with a space."""
        return ("" if self.lang == "ja" else " ").join(
            p.strip() for p in pieces if p.strip()
        )

    def notes(self) -> list[tuple[str, list[str]]]:
        """(lead, paragraphs) per note; the lead is bold and prefixes the first paragraph."""
        tx, sens, base = self.tx, self.sens, self.base
        panels = self.panels
        out = []
        truncated = []
        for p in panels:
            for key in p.axis_keys:
                if p.truncated(key, sens) and key not in truncated:
                    truncated.append(key)
        zero_keys = []
        for p in panels:
            for key in p.axis_keys:
                if self.axes[key]["zero_probe"] and key not in zero_keys:
                    zero_keys.append(key)
        n1 = self.join(
            tx["n1"],
            tx["n1_limit"].format(axes=tx["key_join"].join(truncated))
            if truncated
            else "",
            tx["n1_zero"].format(axes=tx["key_join"].join(zero_keys))
            if zero_keys
            else "",
        )
        out.append((tx["n1_lead"], [n1]))
        p4 = next(x for x in base["patterns"] if x["id"] == PATTERN)
        differ, best = spread_example(sens)
        parts = [tx["n2"]]
        if len({p.j0_sigma for p in panels}) == 2:
            parts.append(
                tx["n2_opposite"].format(
                    a=bcf.size_name(SIZES[0]), b=bcf.size_name(SIZES[1])
                )
            )
        parts.append(
            tx["n2_def"].format(
                stored=f"{base['stored_gib']:,}",
                ws=p4["working_set_pct"],
                reads=p4["reads_per_object"],
            )
        )
        if differ and best:
            kib, key, n, lo, hi = best
            parts.append(
                tx["n2_diff"].format(
                    size=bcf.size_name(kib),
                    key=key,
                    n=n,
                    lo=fmt_value(lo),
                    hi=fmt_value(hi),
                )
            )
        elif differ:
            parts.append(tx["n2_diff_plain"])
        else:
            parts.append(tx["n2_same"].format(n=len(sens["patterns"])))
        parts.append(tx["n2_tail"])
        out.append((tx["n2_lead"], [self.join(*parts)]))
        dirs = tx["n3_dir_join"].join(
            tx["n3_dir_item"].format(size=bcf.size_name(p.kib), low=p.low)
            for p in panels
        )
        paras = [
            tx["n3_dir"].format(items=dirs).strip(),
            tx["n3_route"],
            tx["n3_denom"],
        ]
        for p in panels:
            f, s, b = (
                f"{p.count[k][0]}/{p.count[k][1]}" for k in ("fsx", "s3_files", "both")
            )
            line = tx["n3_count"].format(size=bcf.size_name(p.kib), f=f, s=s, b=b)
            paras.append(
                line
                + (tx["n3_less"] if p.less else "")
                + ("。" if self.lang == "ja" else ".")
            )
        for p in panels:
            if p.excluded:
                paras.append(
                    tx["n3_excl"].format(
                        size=bcf.size_name(p.kib), keys=tx["key_join"].join(p.excluded)
                    )
                )
        sizes = tx["key_join"].join(bcf.size_name(p.kib) for p in panels if p.not_tried)
        if sizes:
            paras.append(tx["n3_notried"].format(sizes=sizes))
        paras.append(tx["n3_meaning"])
        out.append((tx["n3_lead"], paras))
        return out

    def draw_notes(self, y: float) -> float:
        tx, cv = self.tx, self.cv
        cv.text("notes-head", f"<b>{esc(tx['notes_head'])}</b>", 0, y, W, LINE_H)
        y += LINE_H
        for i, (lead, paras) in enumerate(self.notes(), 1):
            for j, para in enumerate(paras):
                text = f"{lead} {para}" if j == 0 else para
                ls = wrap(text, W - 4)
                html_lines = [esc(l) for l in ls]
                if j == 0:
                    if not ls[0].startswith(lead):
                        raise SystemExit(f"note {i}: the lead wrapped")
                    html_lines[0] = f"<b>{esc(lead)}</b>{esc(ls[0][len(lead) :])}"
                cv.text(
                    f"note-{i}-{j}",
                    "<br>".join(html_lines),
                    0,
                    y,
                    W,
                    LINE_H * len(html_lines),
                )
                y += LINE_H * len(html_lines) + 3
            y += 8
        y += 6
        foot = tx["foot"].format(
            region=self.base["region"], snap=self.base["price_snapshot"]
        )
        fl = wrap(foot, W - 4)
        cv.text("foot", "<br>".join(esc(l) for l in fl), 0, y, W, LINE_H * len(fl))
        return y + LINE_H * len(fl)


# ---------------------------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------------------------


def stem(lang: str, theme: str) -> str:
    return (
        BASE_NAME
        + ("-en" if lang == "en" else "")
        + ("-dark" if theme == "dark" else "")
    )


def generate(
    sens: dict, base: dict
) -> dict[tuple[str, str], tuple[ET.ElementTree, int]]:
    """All four variants from the two JSON documents. The layout is measured on both languages
    first and shared, so the marks and panel labels land on identical coordinates."""
    _check_text_numbers()
    verify_claims(sens, base)
    measured = []
    for lang in LANGS:
        b = Builder(sens, base, lang, "light", None)
        b.build()
        measured.append((b.rec_w, b.rec_n))
    shared = Shared.merge(measured)
    return {
        (lang, theme): Builder(sens, base, lang, theme, shared).build()
        for lang in LANGS
        for theme in ("light", "dark")
    }


def load() -> tuple[dict, dict]:
    """The model's two documents. Numbers do not depend on the language; JA is fetched."""
    import json

    sens = json.loads(json.dumps(finops_model.sensitivity_json("ja")))
    base = json.loads(json.dumps(finops_model.baseline_json("ja")))
    return sens, base


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--theme", choices=["light", "dark", "both"], default="both")
    ap.add_argument("--lang", choices=["ja", "en", "both"], default="both")
    ap.add_argument("--diagram-dir", type=Path, default=DIAGRAM_DIR)
    ap.add_argument("--image-dir", type=Path, default=IMAGE_DIR)
    ap.add_argument("--export", action="store_true")
    args = ap.parse_args()
    if args.export and not bcf.DRAWIO_CLI.is_file():
        raise SystemExit(
            f"--export needs the draw.io CLI, not found at {bcf.DRAWIO_CLI}"
        )
    sens, base = load()
    variants = generate(sens, base)
    args.diagram_dir.mkdir(parents=True, exist_ok=True)
    args.image_dir.mkdir(parents=True, exist_ok=True)
    for (lang, theme), (tree, height) in variants.items():
        if args.lang not in ("both", lang) or args.theme not in ("both", theme):
            continue
        path = args.diagram_dir / f"{stem(lang, theme)}.drawio"
        tree.write(path, encoding="utf-8", xml_declaration=True)
        print(f"wrote {path.name}  height={height}")
        if args.export:
            png = args.image_dir / f"{stem(lang, theme)}@2x.png"
            bcf.export_png(path, png)
            w, h = bcf.png_size(png)
            print(f"exported {png.name}  {w}x{h}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
