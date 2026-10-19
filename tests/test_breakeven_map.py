"""The committed break-even map carries the positions and values the model produces.

`tools/build_breakeven_map.py` writes four drawio files (JA/EN x light/dark). A map is a picture of
numbers, so nothing else in the repository notices when the model's output moves and the picture does
not. This test reads the files with an XML parser only (no draw.io CLI, no network) and checks them
against `finops_model.sensitivity_json()` and `baseline_json()`. It guards two things:

* **Numbers.** Every mark's position, every value label and every `$` amount is recomputed here from
  the model, with a position map and number formats written separately from the generator's, so a
  mistake in the generator's map is not checked by the generator.
* **The encoding of evidence kinds.** The map tells a sourced range from a mechanical range from a
  reused point by shape and fill, never by colour. `STYLE_TABLE` below states that encoding on its
  own and every shape cell is checked against it, so a refactor that fills the outline-only bar, or
  gives the thin reused-point mark the sourced bar's size, fails here even though the geometry and
  the values are untouched.

The last group of tests corrupts copies on purpose to show each check can fail; a check that cannot
fail would report a stale map as fine.
"""

from __future__ import annotations

import copy
import html
import math
import re
import shutil
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import build_breakeven_map as bbm
import build_cost_figures as bcf
import check_links
import finops_model as fm
import pytest

LANGS = ("ja", "en")
THEMES = ("light", "dark")
ROOT = Path(__file__).resolve().parent.parent
DOCS = {
    "ja": ROOT / "docs/ja/reference/comparison/finops-s3-vs-s3ap.md",
    "en": ROOT / "docs/en/reference/comparison/finops-s3-vs-s3ap.md",
}
SIZES = (64, 4096)
TOL = 0.02  # Canvas._add writes coordinates with 2 decimals: two roundings of at most 0.005
AMOUNT = re.compile(r"\$\d{1,3}(?:,\d{3})*(?:\.\d+)?|\$\d+(?:\.\d+)?")
CJK = re.compile(r"[\u3000-\u9fff\uff00-\uffef]")

# ---------------------------------------------------------------------------------------------
# The model, once per run (about three seconds)
# ---------------------------------------------------------------------------------------------

_CACHE: dict[str, dict] = {}


def sens() -> dict:
    if "sens" not in _CACHE:
        _CACHE["sens"], _CACHE["base"] = bbm.load()
    return _CACHE["sens"]


def base() -> dict:
    sens()
    return _CACHE["base"]


# ---------------------------------------------------------------------------------------------
# Reading a drawio file
# ---------------------------------------------------------------------------------------------


def parse_style(style: str) -> tuple[dict[str, str], set[str]]:
    """`a=b;c;` -> ({'a': 'b'}, {'c'}). Bare tokens (`ellipse`, `rhombus`) have no `=`."""
    kv: dict[str, str] = {}
    tokens: set[str] = set()
    for part in style.split(";"):
        if not part:
            continue
        if "=" in part:
            k, v = part.split("=", 1)
            kv[k] = v
        else:
            tokens.add(part)
    return kv, tokens


class Cell:
    def __init__(self, el: ET.Element):
        self.id = el.get("id")
        self.style = el.get("style") or ""
        self.kv, self.tokens = parse_style(self.style)
        g = el.find("mxGeometry")
        self.x, self.y, self.w, self.h = (
            (float(g.get(k)) for k in ("x", "y", "width", "height"))
            if g is not None
            else (0.0, 0.0, 0.0, 0.0)
        )
        raw = (el.get("value") or "").replace("<br>", "\n")
        self.text = html.unescape(re.sub(r"<[^>]+>", "", raw)).replace("\xa0", " ")
        self.is_text = self.style.startswith("text;")

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


def read(path: Path) -> tuple[dict[str, Cell], ET.Element]:
    root = ET.parse(path).getroot()
    cells = {}
    for el in root.iter("mxCell"):
        if el.get("id") in ("0", "1"):
            continue
        cells[el.get("id")] = Cell(el)
    return cells, root


def stem(lang: str, theme: str) -> str:
    return (
        bbm.BASE_NAME
        + ("-en" if lang == "en" else "")
        + ("-dark" if theme == "dark" else "")
    )


def committed(lang: str, theme: str) -> Path:
    return bbm.DIAGRAM_DIR / f"{stem(lang, theme)}.drawio"


# ---------------------------------------------------------------------------------------------
# The encoding of evidence kinds, stated here and nowhere else
# ---------------------------------------------------------------------------------------------

# kind -> (shape tokens required, fill, stroke colour, stroke width, width, height). `None` means
# the dimension is free (a range's length). Fill and stroke name a theme colour or "none".
STYLE_TABLE = {
    "dot": ({"ellipse"}, "ink", "bg", "2", 14, 14),
    "src": (set(), "ink", "none", None, None, 12),
    "pt": (set(), "ink", "none", None, 3, 20),
    "dom": (set(), "none", "ink", "2", None, 12),
    "flip": ({"rhombus"}, "ink", "bg", "2", 18, 18),
}
SHAPE_TOKENS = {"ellipse", "rhombus"}


def kind_problems(cell: Cell, kind: str, theme: str) -> list[str]:
    tokens, fill, stroke, sw, w, h = STYLE_TABLE[kind]
    th = bcf.THEMES[theme]
    colour = {"ink": th["ink"], "bg": th["bg"], "none": "none"}
    out = []
    if tokens != cell.tokens & SHAPE_TOKENS:
        out.append(f"{cell.id}: shape tokens {sorted(cell.tokens)} != {sorted(tokens)}")
    if cell.kv.get("fillColor") != colour[fill]:
        out.append(
            f"{cell.id}: fillColor {cell.kv.get('fillColor')!r} != {colour[fill]!r}"
        )
    if cell.kv.get("strokeColor") != colour[stroke]:
        out.append(
            f"{cell.id}: strokeColor {cell.kv.get('strokeColor')!r} != {colour[stroke]!r}"
        )
    if sw is not None and cell.kv.get("strokeWidth") != sw:
        out.append(f"{cell.id}: strokeWidth {cell.kv.get('strokeWidth')!r} != {sw}")
    if w is not None and abs(cell.w - w) > TOL:
        out.append(f"{cell.id}: width {cell.w} != {w}")
    if h is not None and abs(cell.h - h) > TOL:
        out.append(f"{cell.id}: height {cell.h} != {h}")
    return out


def test_the_style_table_gives_every_kind_a_different_look() -> None:
    looks = {
        (tuple(sorted(t)), f, s, w, h) for t, f, s, _sw, w, h in STYLE_TABLE.values()
    }
    assert len(looks) == len(STYLE_TABLE), (
        "two kinds share shape, fill, stroke and size"
    )


# ---------------------------------------------------------------------------------------------
# Independent number formats and position map
# ---------------------------------------------------------------------------------------------


def t_value(x: float) -> str:
    if x == 0:
        return "0"
    r = float(f"{x:.3g}")
    if abs(r) >= 1e4 or abs(r) < 1e-3:
        mant, exp = f"{r:.2e}".split("e")
        return f"{mant.rstrip('0').rstrip('.')}e{int(exp)}"
    if abs(r) >= 1e3:
        return f"{r:,.0f}"
    s = repr(r)
    return s.removesuffix(".0")


def t_edge(m: float) -> str:
    if m == 0:
        return "0"
    if (m >= 1e4 or m < 1e-3) and float(math.log2(m)).is_integer():
        return f"2^{int(math.log2(m))}"
    for n in range(3, 7):
        s = f"{m:.{n}g}"
        if float(s) == m:
            break
    else:
        s = f"{m:.6g}"
    if "e" in s:
        mant, exp = s.split("e")
        return f"{mant}e{int(exp)}"
    f = float(s)
    return f"{int(f):,}" if 1000 <= f < 10000 and f == int(f) else s


def t_px(sens_: dict, key: str, v: float, hi: float) -> float:
    a = sens_["assumption_axes"][key]
    x0 = bbm.TRACK_X0 + (28 if a["zero_probe"] else 0)
    cw = 836 - x0
    lo = a["lo"]
    if a["scale"] == "log":
        f = (math.log2(v) - math.log2(lo)) / (math.log2(hi) - math.log2(lo))
    else:
        f = (v - lo) / (hi - lo)
    return x0 + f * cw


def p4(cells: dict) -> dict:
    return cells["P4"]


def j0(sens_: dict, kib: int) -> dict:
    return p4(next(r for r in sens_["scenarios"][str(kib)] if r["id"] == "J0")["cells"])


def rows(sens_: dict, kib: int, key: str) -> list[dict]:
    return [r for r in sens_["one_at_a_time"][str(kib)] if r["key"] == key]


def axis_keys(sens_: dict, kib: int) -> list[str]:
    return [
        k
        for k, entries in sens_["break_even"].items()
        if any(e["pattern"] == "P4" and e["size_kib"] == kib for e in entries)
    ]


def be_entry(sens_: dict, kib: int, key: str) -> dict:
    return next(
        e
        for e in sens_["break_even"][key]
        if e["pattern"] == "P4" and e["size_kib"] == kib
    )


# ---------------------------------------------------------------------------------------------
# Checks on one drawio file (each returns a list of problems)
# ---------------------------------------------------------------------------------------------


def mark_problems(cells: dict[str, Cell], theme: str, sens_: dict) -> list[str]:
    out: list[str] = []
    for kib in SIZES:
        for key in axis_keys(sens_, kib):
            tag = f"{kib}-{key}"
            a = sens_["assumption_axes"][key]
            be = be_entry(sens_, kib, key)
            hi = be["hi"]

            def px(v: float, _key=key, _hi=hi) -> float:
                return t_px(sens_, _key, v, _hi)

            # baseline dot
            dot = cells.get(f"dot-{tag}")
            if dot is None:
                out.append(f"missing dot-{tag}")
            else:
                out += kind_problems(dot, "dot", theme)
                if abs(dot.cx - px(a["baseline"])) > TOL:
                    out.append(f"dot-{tag}: x {dot.cx:.2f} != {px(a['baseline']):.2f}")
                label = cells.get(f"val-{tag}-base")
                if label is None or label.text != t_value(a["baseline"]):
                    out.append(
                        f"val-{tag}-base: {label and label.text!r} != {t_value(a['baseline'])!r}"
                    )
            # the search range
            dom = cells.get(f"dom-{tag}")
            x0 = bbm.TRACK_X0 + (28 if a["zero_probe"] else 0)
            if dom is None:
                out.append(f"missing dom-{tag}")
            else:
                out += kind_problems(dom, "dom", theme)
                if abs(dom.x - x0) > TOL or abs(dom.x + dom.w - px(hi)) > TOL:
                    out.append(
                        f"dom-{tag}: spans {dom.x:.2f}..{dom.x + dom.w:.2f}, want {x0}..{px(hi):.2f}"
                    )
            if (f"dom-{tag}-zero" in cells) != a["zero_probe"]:
                out.append(
                    f"dom-{tag}-zero present={f'dom-{tag}-zero' in cells}, zero_probe={a['zero_probe']}"
                )
            if f"dom-{tag}-zero" in cells:
                out += kind_problems(cells[f"dom-{tag}-zero"], "dom", theme)
            if (lo := cells.get(f"lbl-{tag}-lo")) is None or lo.text != t_edge(a["lo"]):
                out.append(f"lbl-{tag}-lo: {lo and lo.text!r} != {t_edge(a['lo'])!r}")
            hi_cell = cells.get(f"lbl-{tag}-hi")
            if hi_cell is None or not hi_cell.text.startswith(t_edge(hi)):
                out.append(
                    f"lbl-{tag}-hi: {hi_cell and hi_cell.text!r} !~ {t_edge(hi)!r}"
                )
            # sourced values
            src_vals = sorted(
                {
                    float(r["value"])
                    for r in rows(sens_, kib, key)
                    if r["basis"] == "sourced"
                }
            )
            src = cells.get(f"src-{tag}")
            if not src_vals:
                if src is not None:
                    out.append(f"src-{tag} drawn without a sourced value")
            elif src is None:
                out.append(f"missing src-{tag}")
            else:
                out += kind_problems(src, "src", theme)
                if len(src_vals) >= 2:
                    if (
                        abs(src.x - px(src_vals[0])) > TOL
                        or abs(src.x + src.w - px(src_vals[-1])) > TOL
                    ):
                        out.append(f"src-{tag}: wrong extent")
                    if set(fm.sourced_points(key)) == set(src_vals):
                        want = fm.sourced_range(key)
                        if tuple(src_vals[:1] + src_vals[-1:]) != want:
                            out.append(f"src-{tag} differs from sourced_ranges")
                elif abs(src.cx - px(src_vals[0])) > TOL or abs(src.w - 8) > TOL:
                    out.append(
                        f"src-{tag}: a single sourced point must be a short bar centred on it"
                    )
            # reused / observed points, both directions
            pts = sorted(
                {
                    float(r["value"])
                    for r in rows(sens_, kib, key)
                    if r["basis"] in ("reused", "observed")
                }
            )
            drawn = sorted(
                c.cx
                for i, c in cells.items()
                if re.fullmatch(rf"pt-{re.escape(tag)}-\d+", i)
            )
            want_pts = sorted(px(v) for v in pts)
            if len(drawn) != len(want_pts) or any(
                abs(d - w) > TOL for d, w in zip(drawn, want_pts)
            ):
                out.append(f"pt-{tag}: {drawn} != {want_pts}")
            for i, c in cells.items():
                if re.fullmatch(rf"pt-{re.escape(tag)}-\d+", i):
                    out += kind_problems(c, "pt", theme)
            for v in (
                pts
            ):  # no mechanical point is drawn; a reused/observed one has a value label
                if not any(
                    c.text == t_value(v)
                    for i, c in cells.items()
                    if i.startswith(f"val-{tag}-pt")
                ):
                    out.append(f"val-{tag}: no label for {v}")
            # flips, both directions
            flips = sorted(be["break_evens"], key=lambda b: b["x_star"])
            drawn_f = sorted(
                c.cx
                for i, c in cells.items()
                if re.fullmatch(rf"flip-{re.escape(tag)}-\d+", i)
            )
            want_f = [px(b["x_star"]) for b in flips]
            if len(drawn_f) != len(want_f) or any(
                abs(d - w) > TOL for d, w in zip(drawn_f, want_f)
            ):
                out.append(f"flip-{tag}: {drawn_f} != {want_f}")
            for i, c in cells.items():
                if re.fullmatch(rf"flip-{re.escape(tag)}-\d+", i):
                    out += kind_problems(c, "flip", theme)
            for i, b in enumerate(flips):
                text = (cells.get(f"lbl-{tag}-flip{i}") or Cell(ET.Element("x"))).text
                if (
                    not text.startswith(f"◆ {t_value(b['x_star'])}:")
                    or b["low_below"] not in text
                    or b["low_above"] not in text
                ):
                    out.append(f"lbl-{tag}-flip{i}: {text!r}")
                # sourced_relation against the drawn bar
                if set(fm.sourced_points(key)) == set(src_vals) and src is not None:
                    fx = px(b["x_star"])
                    rel = b["sourced_relation"]
                    ok = {
                        "inside": src.x - TOL <= fx <= src.x + src.w + TOL,
                        "outside": fx < src.x or fx > src.x + src.w,
                        "point_below": fx < src.cx,
                        "point_above": fx > src.cx,
                        "none": False,
                    }[rel]
                    if not ok:
                        out.append(
                            f"flip-{tag}-{i}: sourced_relation {rel} disagrees with the drawing"
                        )
            if not flips and f"lbl-{tag}-noflip" not in cells:
                out.append(f"lbl-{tag}: no 'does not change sides' sentence")
            if flips and f"lbl-{tag}-noflip" in cells:
                out.append(
                    f"lbl-{tag}: a flip and a 'does not change' sentence together"
                )
            # the right end is labelled only when it was cut to the applicable range
            cut = hi < a["domain_hi"]
            marked = (
                bool(CJK.search(hi_cell.text) or "limit" in hi_cell.text)
                if hi_cell
                else False
            )
            if cut != marked:
                out.append(f"lbl-{tag}-hi: cut={cut} but marked={marked}")
        # the skipped axis of this size carries a reason, not an empty slot
        for key, a in sens_["assumption_axes"].items():
            if a["moves_p4"][str(kib)] is None and a["scale"] in ("linear", "log"):
                if any(
                    i.startswith(("dot-", "dom-", "src-")) and f"{kib}-{key}" in i
                    for i in cells
                ):
                    out.append(f"{kib} KiB {key}: drawn although it was not tried")
                reason = cells.get(f"reason-{kib}")
                thr = (
                    f"{sens_['assumption_axes']['s3files_threshold_kib']['baseline']:g}"
                )
                if reason is None or key not in reason.text or thr not in reason.text:
                    out.append(f"{kib} KiB {key}: no reason line with the threshold")
    return out


def amount_problems(cells: dict[str, Cell], sens_: dict, base_: dict) -> list[str]:
    found = set()
    for c in cells.values():
        toks = AMOUNT.findall(c.text)
        if c.text.count("$") != len(toks):
            return [f"a '$' that is not a well-formed amount in {c.id}: {c.text!r}"]
        found.update(toks)
    want = set()
    pat = next(p for p in base_["patterns"] if p["id"] == "P4")
    for kib in SIZES:
        cell = next(c for c in pat["cells"] if c["size_kib"] == kib)
        for m in ("fsx_s3ap", "s3_files"):
            want.add(cell["methods"][m]["subtotal_display"])
        if (
            abs(
                j0(sens_, kib)["fsx_s3ap_usd"]
                - cell["methods"]["fsx_s3ap"]["subtotal_usd"]
            )
            > 1e-6
        ):
            return [f"{kib} KiB: J0 differs from the baseline grid"]
    return [f"amounts {sorted(found)} != {sorted(want)}"] if found != want else []


def readability_problems(
    path: Path, cells: dict[str, Cell], root: ET.Element
) -> list[str]:
    out = []
    styles = [c.style for c in cells.values()]
    sizes = [
        float(s) for st in styles for s in re.findall(r"fontSize=(\d+(?:\.\d+)?)", st)
    ]
    if not sizes or min(sizes) < 16:
        out.append(f"fontSize floor {min(sizes) if sizes else None}")
    for c in cells.values():
        if c.is_text and "fontSize=" not in c.style:
            out.append(f"{c.id}: text cell without fontSize")
        if c.x < -0.01 or c.x + c.w > bbm.W + 0.01:
            out.append(f"{c.id}: outside the canvas")
    page_h = int(root.find(".//mxGraphModel").get("pageHeight"))
    if page_h > bbm.MAX_HEIGHT:
        out.append(f"pageHeight {page_h} > {bbm.MAX_HEIGHT}")
    # labels in the panels never overlap each other
    labels = [
        c for i, c in cells.items() if i.startswith(("val-", "lbl-", "name-", "key-"))
    ]
    for n, a in enumerate(labels):
        for b in labels[n + 1 :]:
            if (
                a.x < b.x + b.w
                and b.x < a.x + a.w
                and a.y < b.y + b.h
                and b.y < a.y + a.h
            ):
                out.append(f"{a.id} overlaps {b.id}")
    # lanes: value labels sit above the track, edge values and sentences below it
    for c in cells.values():
        if c.id.startswith(("val-", "lbl-")):
            dot = cells["dot-" + "-".join(c.id.split("-")[1:3])]
            if c.id.startswith("val-") and c.y + c.h > dot.y + 0.01:
                out.append(f"{c.id} is not above its track")
            if c.id.startswith("lbl-") and c.y < dot.y + dot.h - 0.01:
                out.append(f"{c.id} is not below its track")
    return out


def style_scan_problems(cells: dict[str, Cell], theme: str) -> list[str]:
    """Every shape cell belongs to a kind in STYLE_TABLE; there is no unclassified shape."""
    out = []
    for cid, c in cells.items():
        if c.is_text:
            continue
        kind = cid.split("-", 1)[0]
        if kind == "leg":
            kind = cid.split("-")[1]
        if kind not in STYLE_TABLE:
            out.append(f"{cid}: a shape that belongs to no kind")
            continue
        out += kind_problems(c, kind, theme)
    return out


def baseline_text_problems(
    cells: dict[str, Cell], lang: str, base_: dict, sens_: dict
) -> list[str]:
    out = []
    foot = cells["foot"].text.replace("\n", " ")
    for needle in (base_["region"], base_["price_snapshot"]):
        if needle not in foot:
            out.append(f"footnote lacks {needle!r}")
    note2 = " ".join(
        c.text for i, c in cells.items() if i.startswith("note-2-")
    ).replace("\n", "")
    p4d = next(p for p in base_["patterns"] if p["id"] == "P4")
    for num in (
        f"{base_['stored_gib']:,}",
        str(p4d["working_set_pct"]),
        str(p4d["reads_per_object"]),
    ):
        if not re.search(rf"(?<![\d,.]){re.escape(num)}(?![\d,])", note2):
            out.append(f"note 2 lacks {num}")
    # the widest spread across the five patterns, found here separately
    best, best_key = 0.0, None
    for key, entries in sens_["break_even"].items():
        for kib in SIZES:
            xs = [
                b["x_star"]
                for e in entries
                if e["size_kib"] == kib
                for b in e["break_evens"]
            ]
            if len(xs) >= 2 and min(xs) > 0 and max(xs) / min(xs) > best:
                best, best_key = max(xs) / min(xs), (kib, key, min(xs), max(xs))
    if best_key and best >= 2:
        kib, key, lo, hi = best_key
        lo_s, hi_s = t_value(lo), t_value(hi)
        if key not in note2 or lo_s not in note2 or hi_s not in note2:
            out.append(f"note 2 lacks the widest spread {key} {lo_s}-{hi_s}")
    return out


def check_file(path: Path, lang: str, theme: str) -> list[str]:
    cells, root = read(path)
    s, b = sens(), base()
    return (
        mark_problems(cells, theme, s)
        + amount_problems(cells, s, b)
        + readability_problems(path, cells, root)
        + style_scan_problems(cells, theme)
        + baseline_text_problems(cells, lang, b, s)
    )


# ---------------------------------------------------------------------------------------------
# The committed files
# ---------------------------------------------------------------------------------------------


def png_size(path: Path) -> tuple[int, int]:
    return struct.unpack(">II", path.read_bytes()[16:24])


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("theme", THEMES)
def test_the_committed_map_matches_the_model(lang: str, theme: str) -> None:
    path = committed(lang, theme)
    assert path.is_file(), (
        f"{path.name} missing; run tools/build_breakeven_map.py --export"
    )
    problems = check_file(path, lang, theme)
    assert not problems, "\n".join(problems[:20])


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("theme", THEMES)
def test_the_png_exists_and_has_the_drawio_height(lang: str, theme: str) -> None:
    png = bbm.IMAGE_DIR / f"{stem(lang, theme)}@2x.png"
    assert png.is_file(), (
        f"{png.name} missing; run tools/build_breakeven_map.py --export"
    )
    w, h = png_size(png)
    assert 2 * (836 + 16) <= w <= 2 * (860 + 16) + 16, w
    _, root = read(committed(lang, theme))
    page_h = int(root.find(".//mxGraphModel").get("pageHeight"))
    assert abs(h - 2 * (page_h + 16)) <= 32, (h, page_h)


def cell_signature(c: Cell) -> tuple:
    return (c.style, round(c.x, 2), round(c.y, 2), round(c.w, 2), round(c.h, 2), c.text)


@pytest.mark.parametrize("lang", LANGS)
@pytest.mark.parametrize("theme", THEMES)
def test_regenerating_from_the_live_model_gives_the_committed_cells(
    lang: str, theme: str
) -> None:
    fresh = bbm.generate(sens(), base())[(lang, theme)][0]
    tmp = Path(_CACHE.setdefault("tmp", str(ROOT / ".pytest_cache"))) / "breakeven"
    tmp.mkdir(parents=True, exist_ok=True)
    path = tmp / f"{stem(lang, theme)}.drawio"
    fresh.write(path, encoding="utf-8", xml_declaration=True)
    a, _ = read(path)
    b, _ = read(committed(lang, theme))
    assert set(a) == set(b), sorted(set(a) ^ set(b))[:10]
    stale = [i for i in a if cell_signature(a[i]) != cell_signature(b[i])]
    assert not stale, f"stale cells (regenerate): {stale[:10]}"


def correspondence_problems(ja: dict[str, Cell], en: dict[str, Cell]) -> list[str]:
    """JA and EN share the layout: every cell in the panels has the same id and box. Only the notes
    and the footnote, which come after the panels, may differ in y and height."""
    out = []
    if set(ja) != set(en):
        return [f"cell ids differ: {sorted(set(ja) ^ set(en))[:6]}"]
    tail = ("note-", "foot")
    for i, a in ja.items():
        b = en[i]
        if i.startswith(tail):
            if abs(a.x - b.x) > TOL or abs(a.w - b.w) > TOL:
                out.append(f"{i}: x/width differ")
            continue
        if (round(a.x, 2), round(a.y, 2), round(a.w, 2), round(a.h, 2)) != (
            round(b.x, 2),
            round(b.y, 2),
            round(b.w, 2),
            round(b.h, 2),
        ):
            out.append(f"{i}: box differs between JA and EN")
    return out


@pytest.mark.parametrize("theme", THEMES)
def test_ja_and_en_share_the_layout_and_the_numbers(theme: str) -> None:
    ja, _ = read(committed("ja", theme))
    en, _ = read(committed("en", theme))
    problems = correspondence_problems(ja, en)
    assert not problems, "\n".join(problems[:10])
    visible_en = " ".join(c.text for c in en.values())
    assert not CJK.search(visible_en.replace("◆", "").replace("–", "")), CJK.search(
        visible_en
    )
    # Value labels and axis starts are numbers only, so they are the same text in both languages.
    for i in ja:
        if i.startswith("val-") or i.endswith("-lo") or i.endswith("-zero"):
            assert ja[i].text == en[i].text, i


def test_light_and_dark_differ_only_in_colour() -> None:
    for lang in LANGS:
        light, _ = read(committed(lang, "light"))
        dark, _ = read(committed(lang, "dark"))
        assert set(light) == set(dark)
        for i in light:
            a, b = light[i], dark[i]
            assert (a.x, a.y, a.w, a.h, a.text) == (b.x, b.y, b.w, b.h, b.text), i


# ---------------------------------------------------------------------------------------------
# Text table: no number is typed into the wording
# ---------------------------------------------------------------------------------------------


def test_the_text_table_holds_no_hand_typed_numbers() -> None:
    bbm._check_text_numbers()


def test_a_hand_typed_number_in_the_text_table_stops_the_build(monkeypatch) -> None:
    patched = copy.deepcopy(bbm.TEXT)
    patched["ja"]["n1"] += " 3 倍です。"
    monkeypatch.setattr(bbm, "TEXT", patched)
    with pytest.raises(SystemExit):
        bbm._check_text_numbers()


# ---------------------------------------------------------------------------------------------
# Branches the generator derives from the data (the tests pass modified copies of the data)
# ---------------------------------------------------------------------------------------------


def gen(
    s: dict | None = None, b: dict | None = None
) -> dict[tuple[str, str], dict[str, Cell]]:
    out = {}
    tmp = Path(ROOT / ".pytest_cache") / "breakeven-gen"
    tmp.mkdir(parents=True, exist_ok=True)
    for (lang, theme), (tree, _h) in bbm.generate(s or sens(), b or base()).items():
        path = tmp / f"{stem(lang, theme)}.drawio"
        tree.write(path, encoding="utf-8", xml_declaration=True)
        out[(lang, theme)] = read(path)[0]
    return out


def texts(cells: dict[str, Cell], prefix: str) -> str:
    return "\n".join(c.text for i, c in cells.items() if i.startswith(prefix))


def test_the_panel_heading_names_the_lower_side_of_the_baseline_cell() -> None:
    cells = read(committed("ja", "light"))[0]
    for kib in SIZES:
        c = j0(sens(), kib)
        low = "S3 Files" if c["s3_files_usd"] < c["fsx_s3ap_usd"] else "FSx for ONTAP"
        assert f"{low} の小計が低い" in cells[f"phead-{kib}"].text


def test_a_baseline_cell_that_disagrees_with_the_grid_stops_the_build() -> None:
    s = copy.deepcopy(sens())
    j = j0(s, 4096)
    j["fsx_s3ap_usd"], j["s3_files_usd"] = 1.0, 2.0
    with pytest.raises(SystemExit):
        bbm.generate(s, base())


def test_selection_by_read_only_and_not_placeholder_is_enforced() -> None:
    b = copy.deepcopy(base())
    next(p for p in b["patterns"] if p["id"] == "P4")["placeholder"] = True
    with pytest.raises(SystemExit):
        bbm.generate(sens(), b)


def test_an_active_fraction_row_at_4mib_or_a_step_change_stops_the_build() -> None:
    s = copy.deepcopy(sens())
    s["break_even"]["active_fraction"].append(
        {"pattern": "P4", "size_kib": 4096, "hi": 1.0, "break_evens": []}
    )
    with pytest.raises(SystemExit):
        bbm.generate(s, base())
    s = copy.deepcopy(sens())
    be_entry(s, 4096, "efficiency_ssd")["break_evens"][0]["step_change"] = True
    with pytest.raises(SystemExit):
        bbm.generate(s, base())


def test_the_route_note_is_checked_against_the_fsx_for_ontap_lines() -> None:
    b = copy.deepcopy(base())
    p = next(p for p in b["patterns"] if p["id"] == "P4")
    p["cells"][0]["methods"]["fsx_s3ap"]["lines"].append(
        {"label": "GET リクエスト", "usd": 1.0}
    )
    with pytest.raises(SystemExit):
        bbm.generate(sens(), b)


def test_the_upper_limit_label_follows_the_cut_of_each_cell() -> None:
    s = copy.deepcopy(sens())
    for e in s["break_even"]["read_scale"]:
        e["hi"] = s["assumption_axes"]["read_scale"]["domain_hi"]
    for e in s["break_even"]["stored_tib"]:
        if e["pattern"] == "P4":
            e["hi"] = 675.0
    cells = gen(s)[("ja", "light")]
    assert "適用範囲の上限" not in cells["lbl-64-read_scale-hi"].text
    assert "適用範囲の上限" in cells["lbl-64-stored_tib-hi"].text
    note1 = texts(cells, "note-1-")
    assert "stored_tib" in note1 and "read_scale" not in note1


def test_an_endless_decimal_at_the_axis_end_is_rounded_to_six_digits() -> None:
    s = copy.deepcopy(sens())
    for e in s["break_even"]["read_scale"]:
        if e["pattern"] == "P4":
            e["hi"] = 96.42857142857143
    cells = gen(s)[("en", "light")]
    assert cells["lbl-64-read_scale-hi"].text.startswith("96.4286 ")
    assert t_edge(96.42857142857143) == "96.4286"


def test_axis_end_and_value_formats_on_the_current_data() -> None:
    cells = read(committed("ja", "light"))[0]
    assert cells["lbl-64-metadata_multiplier-lo"].text == "2^-10"
    assert cells["lbl-64-metadata_multiplier-hi"].text == "2^24"
    assert cells["lbl-64-stored_tib-hi"].text == "1,024"
    assert cells["lbl-64-stored_tib-lo"].text == "0.125"
    assert cells["lbl-64-read_scale-hi"].text.startswith("101.25")
    assert "1,580" in cells["lbl-4096-metadata_multiplier-flip0"].text
    assert "e+" not in " ".join(c.text for c in cells.values())


def test_the_share_rule_needs_both_denominators_and_a_strictly_lower_share() -> None:
    s = copy.deepcopy(sens())
    # Give every S3 Files-side key at 64 KiB a sourced point: its share is no longer lower.
    for key, a in s["assumption_axes"].items():
        if a["moves_p4"]["64"] == "s3_files":
            last = [r for r in s["one_at_a_time"]["64"] if r["key"] == key][-1]
            last["basis"] = "sourced"
    notes = texts(gen(s)[("ja", "light")], "note-3-")
    line64 = next(
        l for l in notes.split("\n") if l.startswith("64 KiB: FSx for ONTAP ")
    )
    line4m = next(l for l in notes.split("\n") if l.startswith("4 MiB: FSx for ONTAP "))
    assert "割合が低い" not in line64
    assert "割合が低い" in line4m
    assert line64 != line4m


def test_the_denominator_sentence_comes_right_before_the_counts() -> None:
    for lang, denom in (
        ("ja", "分母は、この大きさで試し"),
        ("en", "The denominator is the number of assumptions tried"),
    ):
        cells = read(committed(lang, "light"))[0]
        notes = [
            c.text.replace("\n", "" if lang == "ja" else " ")
            for i, c in cells.items()
            if i.startswith("note-3-")
        ]
        idx = next(n for n, t in enumerate(notes) if denom in t)
        assert notes[idx + 1].startswith("64 KiB: FSx for ONTAP")
        assert notes[idx + 2].startswith("4 MiB: FSx for ONTAP")


def test_assumptions_not_tried_at_a_size_are_listed_whatever_their_evidence() -> None:
    cells = read(committed("ja", "light"))[0]
    tried = {r["key"] for r in sens()["one_at_a_time"]["4096"]}
    missing = [k for k in sens()["assumption_axes"] if k not in tried]
    assert missing and all(k in cells["nottried-4096"].text for k in missing)
    assert "nottried-64" not in cells
    s = copy.deepcopy(sens())
    s["one_at_a_time"]["64"] = [
        r for r in s["one_at_a_time"]["64"] if r["key"] != "first_read_mode"
    ]
    s["assumption_axes"]["first_read_mode"]["moves_p4"]["64"] = None
    cells = gen(s)[("ja", "light")]
    assert "first_read_mode" in cells["nottried-64"].text


def test_the_auto_baseline_has_its_own_wording() -> None:
    cells = read(committed("ja", "light"))[0]
    row = cells["enum-64-throughput_mbps"].text
    assert "自動選択" in row and "auto" not in row
    assert "基準 128" in cells["enum-64-s3files_threshold_kib"].text.replace("\n", "")
    assert "128.0" not in " ".join(c.text for c in cells.values())
    en = read(committed("en", "light"))[0]["enum-64-throughput_mbps"].text
    assert "automatic" in en


def test_the_data_in_the_footnote_and_note_2_comes_from_the_documents() -> None:
    b = copy.deepcopy(base())
    b["region"], b["price_snapshot"] = "xx-test-9", "2031-01-02"
    b["stored_gib"] = 12345
    p = next(p for p in b["patterns"] if p["id"] == "P4")
    p["working_set_pct"], p["reads_per_object"] = 37, 53
    for lang in LANGS:
        cells = gen(b=b)[(lang, "light")]
        foot = cells["foot"].text.replace("\n", " ")
        assert "xx-test-9" in foot and "2031-01-02" in foot
        assert base()["region"] not in foot and base()["price_snapshot"] not in foot
        note2 = texts(cells, "note-2-").replace("\n", "")
        for num in ("12,345", "37", "53"):
            assert num in note2
        assert "20,480" not in note2


def test_layout_is_shared_when_only_one_language_needs_an_extra_lane(
    monkeypatch,
) -> None:
    long = "Does not change sides within the search range"
    while bcf.text_w(long + " no") <= 560:
        long += " no"
    assert 540 < bcf.text_w(long) <= bbm.TRACK_W
    patched = copy.deepcopy(bbm.TEXT)
    patched["en"]["no_flip"] = long
    monkeypatch.setattr(bbm, "TEXT", patched)
    monkeypatch.setattr(
        bbm, "MAX_HEIGHT", 6000
    )  # every no-flip row grows; only the layout is under test
    both = gen()
    problems = correspondence_problems(both[("ja", "light")], both[("en", "light")])
    assert not problems, problems[:5]
    plain = read(committed("ja", "light"))[0]
    # pool_fraction's row grew in both languages: the row after it moved down by one lane
    assert (
        both[("ja", "light")]["name-64-efficiency_ssd"].y
        > plain["name-64-efficiency_ssd"].y
    )


# ---------------------------------------------------------------------------------------------
# The document side
# ---------------------------------------------------------------------------------------------


def h3_section(lang: str) -> tuple[str, str]:
    text = DOCS[lang].read_text(encoding="utf-8")
    head = "### 損益分岐の地図" if lang == "ja" else "### Break-even map for pattern P4"
    assert text.count(head + "\n") == 1, f"{lang}: expected exactly one H3 {head!r}"
    start = text.index(head)
    end = text.index("\n## ", start)
    return text, text[start:end]


def link_shape(section: str) -> tuple:
    images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", section)
    body = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", section)
    links = re.findall(r"\[[^\]]*\]\(([^)]+)\)", body)
    frag = [l for l in links if l.startswith("#")]
    other = [l for l in links if not l.startswith("#")]
    return (
        [i.rsplit("/", 1)[0] for i in images],
        [o.rsplit("/", 1)[0] for o in other],
        len(frag),
        len(set(frag)),
    )


def test_both_h3_have_the_same_link_structure_and_real_targets() -> None:
    shapes = {}
    for lang in LANGS:
        text, section = h3_section(lang)
        shapes[lang] = link_shape(section)
        doc_dir = DOCS[lang].parent
        for target in re.findall(r"\]\(([^)#][^)]*)\)", section):
            assert (doc_dir / target).is_file(), f"{lang}: {target} does not exist"
        anchors = {
            check_links.slugify(m.group(1))
            for m in re.finditer(r"^#{1,6} (.+)$", text, re.MULTILINE)
        }
        for frag in re.findall(r"\]\(#([^)]+)\)", section):
            assert frag in anchors, f"{lang}: #{frag} is not a heading"
        # the guide sentence is the last sentence of the paragraph before the generated block
        before = text.split("<!-- finops-model:begin -->")[0].rstrip("\n")
        last_line = before.split("\n")[-1]
        head_slug = (
            "損益分岐の地図" if lang == "ja" else "break-even-map-for-pattern-p4"
        )
        assert f"(#{head_slug})" in last_line and last_line.count("](#") == 1
    assert shapes["ja"] == shapes["en"], shapes
    images, other, n_frag, n_distinct = shapes["ja"]
    assert len(images) == 1 and len(other) == 1
    assert n_frag == n_distinct == 5, (
        "five distinct sections of the generated block, each once"
    )


def direction_opposite(s: dict) -> bool:
    lower_is_s3 = [
        j0(s, kib)["s3_files_usd"] < j0(s, kib)["fsx_s3ap_usd"] for kib in SIZES
    ]
    return lower_is_s3[0] != lower_is_s3[1]


def derive_claims(s: dict, b: dict) -> dict[str, bool]:
    """The facts the hand-written H3 asserts, derived from the data."""
    differ, _ = bbm.spread_example(s)
    out = {
        "direction_opposite_by_size": direction_opposite(s),
        "patterns_differ": differ,
    }
    share = []
    for panel in (bbm.Panel(s, b, k) for k in SIZES):
        share.append(panel.less)
    out["s3_share_lower_in_both"] = all(share)
    ranged = {k for k, r in s["sourced_ranges"].items() if r is not None}
    sides = {
        k: {w for w in s["assumption_axes"][k]["moves_p4"].values() if w}
        for k in ranged
    }
    out["ranged_assumptions_are_fsx_only"] = bool(sides) and all(
        v <= {"fsx"} for v in sides.values()
    )
    return out


def test_h3_claims_hold() -> None:
    claims = derive_claims(sens(), base())
    assert all(claims.values()), (
        f"{claims}: the hand-written H3 in both finops documents states these; "
        "revise it before changing this test"
    )


def test_h3_claims_notice_a_changed_model() -> None:
    s = copy.deepcopy(sens())
    j = j0(s, 4096)
    j["fsx_s3ap_usd"], j["s3_files_usd"] = 1.0, 2.0
    assert not direction_opposite(s)


# ---------------------------------------------------------------------------------------------
# Each check can fail: corrupted copies of a committed file
# ---------------------------------------------------------------------------------------------


def corrupt(tmp_path: Path, edit, lang: str = "ja", theme: str = "light") -> list[str]:
    path = tmp_path / committed(lang, theme).name
    shutil.copy(committed(lang, theme), path)
    tree = ET.parse(path)
    edit(tree.getroot())
    tree.write(path, encoding="utf-8", xml_declaration=True)
    return check_file(path, lang, theme)


def cell_el(root: ET.Element, cid: str) -> ET.Element:
    return next(c for c in root.iter("mxCell") if c.get("id") == cid)


def move(cid: str, dx: float = 0, dy: float = 0):
    def edit(root: ET.Element) -> None:
        g = cell_el(root, cid).find("mxGeometry")
        g.set("x", f"{float(g.get('x')) + dx:.2f}")
        g.set("y", f"{float(g.get('y')) + dy:.2f}")

    return edit


def restyle(cid: str, old: str, new: str):
    def edit(root: ET.Element) -> None:
        el = cell_el(root, cid)
        assert old in el.get("style"), (cid, old)
        el.set("style", el.get("style").replace(old, new))

    return edit


def resize(cid: str, w: float, h: float):
    def edit(root: ET.Element) -> None:
        g = cell_el(root, cid).find("mxGeometry")
        g.set("width", f"{w:.2f}")
        g.set("height", f"{h:.2f}")

    return edit


def remove(cid: str):
    def edit(root: ET.Element) -> None:
        parent = next(p for p in root.iter() if cell_el(root, cid) in list(p))
        parent.remove(cell_el(root, cid))

    return edit


def retext(cid: str, old: str, new: str):
    def edit(root: ET.Element) -> None:
        el = cell_el(root, cid)
        assert old in el.get("value"), (cid, old)
        el.set("value", el.get("value").replace(old, new))

    return edit


@pytest.mark.parametrize(
    ("name", "edit"),
    [
        ("a flip diamond moved", move("flip-4096-metadata_multiplier-0", dx=10)),
        ("a flip diamond removed", remove("flip-64-stored_tib-0")),
        ("a baseline dot moved", move("dot-64-pool_fraction", dx=10)),
        ("an amount rewritten", retext("psub-64", "$1,818.50", "$1,818.51")),
        ("a value label rewritten", retext("val-64-pool_fraction-base", "0.3", "0.4")),
        ("a sourced bar shortened", resize("src-64-efficiency_ssd", 20, 12)),
        (
            "an outline bar filled",
            restyle("dom-64-pool_fraction", "fillColor=none", "fillColor=#232F3E"),
        ),
        (
            "a sourced bar left unfilled",
            restyle("src-64-efficiency_ssd", "fillColor=#232F3E", "fillColor=none"),
        ),
        (
            "a reused point made as wide as a sourced point",
            resize("pt-64-pool_fraction-1", 8, 12),
        ),
        (
            "a diamond turned into an ellipse",
            restyle("flip-64-stored_tib-0", "rhombus", "ellipse"),
        ),
        ("the footnote date changed", retext("foot", "2026-08-09", "2026-08-10")),
        ("the 4 MiB reason line removed", remove("reason-4096")),
        ("an outline bar width changed", resize("dom-64-pool_fraction", 300, 12)),
    ],
)
def test_the_check_fails_on_a_corrupted_copy(tmp_path: Path, name: str, edit) -> None:
    assert corrupt(tmp_path, edit), f"nothing noticed: {name}"


def test_legend_and_rows_changing_together_still_fail(tmp_path: Path) -> None:
    """The legend and the rows are drawn by one function, so both can change at once. The table in
    this file is what catches that, not a comparison between the two."""

    def edit(root: ET.Element) -> None:
        for cid in ("leg-dom", "dom-64-pool_fraction", "dom-4096-pool_fraction"):
            restyle(cid, "fillColor=none", "fillColor=#232F3E")(root)

    problems = corrupt(tmp_path, edit)
    assert any("leg-dom" in p for p in problems)


def test_an_unclassified_shape_fails(tmp_path: Path) -> None:
    def edit(root: ET.Element) -> None:
        graph = root.find(".//root")
        extra = ET.SubElement(
            graph,
            "mxCell",
            id="sep-1",
            style="rounded=0;fillColor=#D5DBDB;strokeColor=none;fontSize=16;",
            vertex="1",
            parent="1",
        )
        ET.SubElement(
            extra,
            "mxGeometry",
            {"x": "0", "y": "0", "width": "10", "height": "10", "as": "geometry"},
        )

    assert any("sep-1" in p for p in corrupt(tmp_path, edit))


def test_a_language_only_shift_is_caught_by_the_correspondence_check(
    tmp_path: Path,
) -> None:
    shutil.copy(committed("en", "light"), tmp_path / "en.drawio")
    tree = ET.parse(tmp_path / "en.drawio")
    move("dot-64-pool_fraction", dy=10)(tree.getroot())
    tree.write(tmp_path / "en.drawio", encoding="utf-8", xml_declaration=True)
    ja = read(committed("ja", "light"))[0]
    en = read(tmp_path / "en.drawio")[0]
    assert correspondence_problems(ja, en)
