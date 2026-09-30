#!/usr/bin/env python3
"""Fail when a diagram makes the reader work out which way to read it.

Seven rules, all of them things that are only visible in the rendered image and therefore easy to
break while every generator function still looks correct.

**Direction.** Every edge must advance rightwards or downwards, never leftwards and never upwards.
The failure this prevents is not ugliness. A figure whose arrows change heading part-way through has
no reading order, so a reader traces each line with a finger to find out which one carries the thing
they came for -- which is usually the one claim the figure exists to make. A single backwards edge is
enough to cost that, because once one line runs the other way the reader can no longer assume any of
the others.

The verdict is reached on the polyline the edge actually follows: the exit anchor, then any explicit
waypoints the file carries, then the entry anchor. When there are no waypoints this is just the two
endpoints, and draw.io's own orthogonal router fills in the right-angle path between them -- which is
why a plain edge is still judged on its endpoints. When the generator gives waypoints (a tree fork:
one trunk down, a right-angle branch, then a vertical drop into a child's centre), each segment is
judged in turn.

A purely horizontal segment is allowed: it is the branch of a fork, not a reversal of reading order.
What is rejected is any segment that goes **upwards**, and -- on the endpoint pair of an edge with no
waypoints -- any leg that runs leftwards, since without waypoints a leftward endpoint pair is a
backwards edge rather than a branch. A tree fork therefore passes (its only non-vertical segments are
horizontal branches), while a diagonal leg off an icon corner that lands left-and-below still fails,
because its single segment carries both directions at once.

Reading the anchors matters wherever an edge lands on something large. A restore edge dropping onto
the top-right of a 520px boundary frame advances rightwards for the reader while the frame's *centre*
sits well to the left of where the edge left, so a centres-only rule reports a backwards edge that
renders forwards. The anchors are in the file, so there is no reason to guess.

**Icon labels.** A vertex drawn as an image must carry `verticalLabelPosition=bottom`. The official
AWS asset guidance puts a service's name under its icon, and every reader of these diagrams has
learned that convention from every other AWS diagram they have seen. A label beside an icon reads as
belonging to whatever else is on that row.

**Service names.** A vertex drawn with an official AWS *service* icon must carry that service's full
official name in its label -- "Amazon FSx for NetApp ONTAP", not the abbreviation "FSx for ONTAP",
and not a role word alone such as "file server", "controller A" or "SMB SVM". The AWS icon guidance
is explicit that service icons are labelled with the product's full name; a reader who sees the FSx
for ONTAP mark under the words "SMB SVM" cannot tell which service it is. The check reads the service
out of the icon itself -- every AWS SVG embeds its name in a `<title>` -- so it does not depend on
any project's label keys and travels between repositories unchanged. Put the role in a qualifier
line: "Amazon FSx for NetApp ONTAP\n(Controller A)". Resource icons (an S3 bucket, an access point,
the generic client/users marks) name a resource or a role rather than a top-level service and are
left alone.

**Boundary labels.** A group frame's title must not be pushed sideways with `spacingLeft` past the
standard offset. Raising it is how a boundary's name ends up sitting next to an icon that is merely
inside the boundary, which then looks exactly like that icon's own label while the icon's real label
sits underneath -- two names, one of them wrong.

**AWS Cloud mislabelling.** When a diagram contains exactly **one** group drawn with the
`group_aws_cloud` pictogram (the cloud-outline icon in its corner badge), that group must carry the
literal title "AWS Cloud", optionally with a parenthetical qualifier such as "AWS Cloud (Origin
Region)". A lone occurrence of the pictogram has only one plausible meaning in a figure that
otherwise draws no boundary at all: the account/partition edge every AWS reference diagram uses it
for. This is what shipped in `s3burst-two-ceilings` before it was caught by eye -- the cloud
pictogram, alone in the figure, captioned "FSx for ONTAP file server".

The check is deliberately silent when the pictogram appears more than once in the same diagram.
Several figures in this repository use it as a repeated per-panel card border ("A. ...", "B. ...")
or as an outer boundary with distinctly-captioned cards nested inside it -- both established,
intentional patterns unrelated to the account-edge meaning, and neither is what broke. Requiring
every occurrence to say "AWS Cloud" would make the rule fire on those instead of on the one shape
it exists to catch.

**Label spilling out of its own boundary.** An icon's label is not stored as a box in the file -- it
is text drawn below the icon at render time -- so a group or frame sized to the icon alone has no
room for what actually appears underneath it once the label wraps to two lines. This check
estimates the label's rendered height from its line count and font size and rejects any group or
frame whose rectangle fully contains the icon but ends before that estimated label does. This is
what shipped in `s3burst-block-c-layout`: the per-deployment group closed 30px above the second
line of the FSx caption, so the caption's own text sat on the group's border.

**Boundary title crossing a pass-through edge.** A centred frame or group title occupies the
horizontal middle of the boundary's top edge. An edge that runs straight through that same
horizontal band -- entering the boundary from above and continuing to a node below it, rather than
stopping at the boundary -- is drawn on top of the title whenever draw.io's router keeps to a
straight vertical run, which it does whenever the edge's exit and entry `x` already agree. This is
what shipped in `s3burst-block-b-multipath`: two vertical lines from the EC2 client to the two FSx
for ONTAP controllers passed straight through the centre of the "FSx for ONTAP HA pair" frame title.
Left-aligning the title (`title_align_left=True` on `Frame`, tracked in `build_diagrams.py`) moves it
to the corner nothing else crosses.

**Diagonal line into an icon corner.** An edge that anchors on an icon's *corner* -- x in {0,1} and
y in {0,1} at the same time -- with no waypoints to route it renders as a slanted line stabbing into
that corner rather than a clean orthogonal connection to the icon's centre. This is the defect
reported on the block figures: a fork's legs, anchored (0,1)/(1,0), drew diagonal lines into the FSx
and controller icons instead of dropping into their centres. The fix is the orthogonal tree
connector -- anchor on the centre (0.5) and give the edge waypoints so it goes down, turns at a
branch row, and drops vertically into the child's centre. An edge-*midpoint* anchor such as (1,0.5),
used elsewhere to leave an icon's side and route around its label, is not a corner and is left alone;
a waypointed edge routes itself and is exempt.

Crossing edges are otherwise not checked. Whether two arbitrary lines cross depends on the routing,
which is not in the file, and approximating it with straight centre-to-centre segments reports
crossings that do not render and misses ones that do. The boundary-title rule above is narrower than
that: it only fires on the one geometry a title box is guaranteed to occupy (a fixed band at a fixed
place), not on the router's path.

Nothing here is specific to one repository: paths are discovered rather than configured, so this file
is copied between repositories as-is. Two things then differ, both of them known. The suppression on
the parse call in `_parse()`: a repository whose ruff selects `S` needs `# noqa: S314` there, and one
that selects `RUF100` without `S` rejects the same comment as unused, so the divergence is isolated to
that one function rather than left to spread. And the line wrapping, because each repository's ruff
carries its own line length and reformats the copy on arrival -- so the copies are the same logic and
not the same bytes, and a diff between two of them is expected to show re-wrapped statements.

There is no debt file. This gate was wired only after every figure in the repository passed it, so
there is nothing to carry, and a gate with no exemption list cannot grow one quietly.

Run:  python3 tools/check_diagram_flow.py
      python3 tools/check_diagram_flow.py --selftest
"""

from __future__ import annotations

import argparse
import base64
import binascii
import itertools
import re
import sys
import urllib.parse
import xml.etree.ElementTree as ET  # nosec B405  reads this repository's own committed files
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Directories that hold copies of other people's files, or build output. Scanning them reports
# findings nobody in this repository can act on.
SKIP = {".git", ".venv", "node_modules", "__pycache__", ".private", "site-packages"}

# Displacement below this is treated as no movement. It is not a rounding allowance: these figures
# are laid out on a 10px grid, and a box anchored at 0.5 of its own width lands a few pixels off the
# icon above it, which renders as a straight vertical line and was being reported as a leftward edge.
# A step a reader can perceive as a direction is a column or a row -- a hundred pixels and up -- so
# nothing real hides under this, and a backwards nudge small enough to pass is one nobody can see.
EPSILON = 8.0

# The offset the AWS group shape uses to clear its own corner badge. A title at this value sits at
# the top-left of the frame, which is where a boundary name belongs; past it, the title travels
# along the top edge and lands beside whatever the frame contains.
GROUP_SPACING_LEFT = 30

# The pictogram that promises "this boundary is the AWS account / partition edge". A group carrying
# it must be captioned to match; see the module docstring.
AWS_CLOUD_ICON = re.compile(r"\bgrIcon=mxgraph\.aws4\.group_aws_cloud\b")
AWS_CLOUD_TITLE = re.compile(r"^AWS Cloud(\s*\([^)]+\))?$")

# A frame or group's title band: how tall a reader's eye treats it as occupying regardless of the
# frame's own height, and how wide, centred, before an edge crossing that band is judged to cross
# the title rather than pass beside it. `spacingTop=6` in FRAME_STYLE and the group shape's own
# title row both sit within this.
TITLE_BAND_HEIGHT = 40
TITLE_BAND_WIDTH_FRACTION = 0.5

IMAGE_SHAPE = re.compile(r"\bshape=image\b")
GROUP_SHAPE = re.compile(r"\bshape=mxgraph\.aws4\.group\b")
SPACING_LEFT = re.compile(r"\bspacingLeft=(\d+(?:\.\d+)?)")
LEFT_ALIGNED = re.compile(r"\balign=left\b")
FONT_SIZE = re.compile(r"\bfontSize=(\d+(?:\.\d+)?)")
EXIT_X = re.compile(r"\bexitX=(-?\d+(?:\.\d+)?)")
EXIT_Y = re.compile(r"\bexitY=(-?\d+(?:\.\d+)?)")
ENTRY_X = re.compile(r"\bentryX=(-?\d+(?:\.\d+)?)")
ENTRY_Y = re.compile(r"\bentryY=(-?\d+(?:\.\d+)?)")

# A rough per-character width in px at fontSize=16, used only to estimate how many lines a label
# wraps to inside a fixed-width box -- not to render text. Deliberately generous (real glyphs at
# this weight run narrower) so the estimate over-wraps rather than under-wraps: missing a real
# overflow is the failure mode that ships a broken diagram, and a false positive here just adds a
# comment explaining why a genuinely tight fit is fine.
CHAR_WIDTH_AT_16PX = 10.0

# An icon embedded as a data URI carries the official AWS SVG, and that SVG names the service in its
# own <title>: `Icon-Architecture/64/Arch_Amazon-FSx-for-NetApp-ONTAP_64` for a top-level service,
# `Icon-Resource/...` for a resource icon. The AWS icon guidance says a *service* icon must be
# labelled with the service's full official name, not an abbreviation or a role word alone -- so a
# cell drawn with an `Arch_*` service icon must carry that service's name in its label. Resource
# icons (`Icon-Resource/...`, e.g. an S3 bucket or the generic client/users marks) name a resource
# or a role, not a top-level service, and are not held to this.
IMAGE_DATA_URI = re.compile(r"image=(data:image/svg\+xml[;,][^;\"]+)")
SVG_TITLE = re.compile(r"<title>\s*([^<]+?)\s*</title>")
ARCH_TITLE = re.compile(r"(?:^|/)Arch_(.+?)_\d+$")

# The official product name for each architecture-service icon stem (the part between `Arch_` and
# the trailing size). The stem comes straight from the AWS asset's own title, so a new service is
# added here once, by name. The check requires the label to *contain* this string, so a qualifier
# such as "Amazon FSx for NetApp ONTAP (Controller A)" passes while "FSx for ONTAP" alone does not.
# `Amazon-Simple-Storage-Service` maps to "Amazon S3" because that is the name AWS now uses for it,
# and "Amazon S3 Files" / "Amazon S3 Access Point" both contain it.
AWS_SERVICE_NAMES = {
    "Amazon-EC2": "Amazon EC2",
    "Amazon-EFS": "Amazon EFS",
    "Amazon-FSx-for-NetApp-ONTAP": "Amazon FSx for NetApp ONTAP",
    "Amazon-Simple-Storage-Service": "Amazon S3",
    "AWS-Direct-Connect": "AWS Direct Connect",
    "AWS-Interconnect": "AWS Interconnect",
}


def _decode_data_uri(uri: str) -> str | None:
    """The SVG text inside an `image=data:image/svg+xml,...` value, or None if it is not decodable.

    The payload appears in three forms across draw.io files: `data:image/svg+xml,<base64>` (this
    repository's generator writes base64 *without* the `;base64` marker, which the AGENTS.md notes
    are the only form draw.io renders), `data:image/svg+xml;base64,<base64>`, and a URL-encoded
    form. The marker is therefore not a reliable signal, so this tries base64 first -- an SVG
    always begins with `<`, and valid base64 that decodes to something starting with `<?xml` or
    `<svg` is unambiguous -- and falls back to URL-decoding.
    """
    if "," not in uri:
        return None
    _header, payload = uri.split(",", 1)
    try:
        decoded = base64.b64decode(payload, validate=True).decode("utf-8", "replace")
        if decoded.lstrip().startswith("<"):
            return decoded
    except (binascii.Error, ValueError):
        pass
    return urllib.parse.unquote(payload)


def _service_name(style: str) -> str | None:
    """The official AWS service name an icon's embedded SVG declares, or None.

    Returns a value only for a top-level architecture-service icon (`Arch_*`); resource icons and
    non-AWS badges return None and are left unchecked.
    """
    match = IMAGE_DATA_URI.search(style)
    if match is None:
        return None
    svg = _decode_data_uri(match.group(1))
    if svg is None:
        return None
    title = SVG_TITLE.search(svg)
    if title is None:
        return None
    arch = ARCH_TITLE.search(title.group(1))
    if arch is None:
        return None
    return AWS_SERVICE_NAMES.get(arch.group(1))


@dataclass(frozen=True)
class Finding:
    path: Path
    rule: str
    detail: str


def _skipped(path: Path) -> bool:
    return bool(SKIP.intersection(path.relative_to(ROOT).parts))


def walk(pattern: str) -> list[Path]:
    return sorted(p for p in ROOT.rglob(pattern) if not _skipped(p))


def _parse(text: str) -> ET.Element:
    """Parse a committed .drawio from this repository -- never user-supplied data.

    The whole function exists to hold one line; see the module docstring for why the suppression
    cannot move.
    """
    return ET.fromstring(text)  # nosec B314


def _rect(cell: ET.Element) -> tuple[float, float, float, float] | None:
    """A vertex's rectangle in page coordinates, or None when it has no geometry of its own.

    A cell whose geometry is relative, or absent, is positioned by something else -- a label on an
    edge, or a child tracking its parent -- and has no place of its own to compare.
    """
    for geometry in cell:
        if geometry.tag != "mxGeometry":
            continue
        if geometry.get("relative") == "1":
            return None
        x, y = geometry.get("x"), geometry.get("y")
        if x is None or y is None:
            return None
        return (
            float(x),
            float(y),
            float(geometry.get("width") or 0),
            float(geometry.get("height") or 0),
        )
    return None


def _waypoints(cell: ET.Element) -> list[tuple[float, float]]:
    """The explicit routing points on an edge, in order, or [] when it has none.

    draw.io stores them as `<mxPoint x= y=>` children of an `<Array as="points">` inside the
    edge's `<mxGeometry>`. A bare `<mxPoint as="offset">` (a label nudge) is not a waypoint and is
    not inside that array, so scoping to the array keeps the two apart.
    """
    for geometry in cell:
        if geometry.tag != "mxGeometry":
            continue
        for child in geometry:
            if child.tag != "Array" or child.get("as") != "points":
                continue
            points: list[tuple[float, float]] = []
            for point in child:
                if point.tag != "mxPoint":
                    continue
                x, y = point.get("x"), point.get("y")
                if x is not None and y is not None:
                    points.append((float(x), float(y)))
            return points
    return []


def _anchor(
    rect: tuple[float, float, float, float],
    style: str,
    x_pattern: re.Pattern[str],
    y_pattern: re.Pattern[str],
) -> tuple[float, float]:
    """Where the edge meets this node: its fixed anchor if the style names one, else the centre."""
    x, y, w, h = rect
    fx = x_pattern.search(style)
    fy = y_pattern.search(style)
    return (
        x + (float(fx.group(1)) if fx else 0.5) * w,
        y + (float(fy.group(1)) if fy else 0.5) * h,
    )


def _heading(dx: float, dy: float) -> str | None:
    """Which forbidden way this edge runs, or None when it advances right and/or down."""
    parts = []
    if dx < -EPSILON:
        parts.append("leftwards")
    if dy < -EPSILON:
        parts.append("upwards")
    return " and ".join(parts) if parts else None


def _label_line_count(value: str) -> int:
    """How many lines this label's own text forces, ignoring width-driven wrapping.

    Every label in this repository's generator carries an explicit `\n` where it needs a line
    break rather than relying on the renderer to find one, so counting `\n` is exact for these
    files even though it would undercount a label that wraps on width alone.
    """
    return value.count("\n") + 1 if value else 0


def _label_overflow(
    rect: tuple[float, float, float, float], style: str, value: str
) -> float:
    """How far this icon's rendered label is expected to extend below the icon's own bottom edge.

    Not a layout engine: a fixed per-line height at the cell's own `fontSize`, plus one gap between
    the icon and the first line. Good enough to catch a container sized to the icon alone with no
    room left for what actually prints underneath it -- see the module docstring.
    """
    lines = _label_line_count(value)
    if lines == 0:
        return 0.0
    match = FONT_SIZE.search(style)
    font_size = float(match.group(1)) if match else 16.0
    gap = 8.0
    line_height = font_size * 1.3
    return gap + lines * line_height


def _is_frame_container(style: str) -> bool:
    """Whether this style is the dashed frame box `Frame` renders, not a `Note` (filled) or icon.

    `Frame` and `Note` share `dashed=1;dashPattern=8 4`, and only `fillColor` tells them apart:
    `Frame` is `fillColor=none` (a boundary around something), `Note` is `fillColor=#F5F5F5` (a
    filled card of its own text). A `Note` has no children to contain and no title band a real
    edge is meant to stop at, so counting it as a container would check it against geometry it was
    never meant to satisfy.
    """
    return (
        "dashed=1" in style
        and "dashPattern=8 4" in style
        and "fillColor=none" in style
        and "shape=image" not in style
    )


@dataclass(frozen=True)
class _Container:
    cid: str
    rect: tuple[float, float, float, float]
    value: str
    is_group: bool
    title_left_aligned: bool


def _contains(
    outer: tuple[float, float, float, float], inner: tuple[float, float, float, float]
) -> bool:
    ox, oy, ow, oh = outer
    ix, iy, iw, ih = inner
    return ix >= ox and ix + iw <= ox + ow and iy >= oy and iy + ih <= oy + oh


def inspect(path: Path, text: str) -> list[Finding]:
    findings: list[Finding] = []
    root = _parse(text)
    for model in root.iter("mxGraphModel"):
        rects: dict[str, tuple[float, float, float, float]] = {}
        edges: list[tuple[str, str, str, str, str, list[tuple[float, float]]]] = []
        icons: list[tuple[str, tuple[float, float, float, float], str, str]] = []
        containers: list[_Container] = []
        aws_cloud_groups: list[tuple[str, str]] = []
        for cell in model.iter("mxCell"):
            cid = cell.get("id") or "?"
            style = cell.get("style") or ""
            value = (cell.get("value") or "").strip()
            if cell.get("edge") == "1":
                source, target = cell.get("source"), cell.get("target")
                if source and target:
                    edges.append((cid, source, target, value, style, _waypoints(cell)))
                continue
            if cell.get("vertex") != "1":
                continue
            rect = _rect(cell)
            if rect is not None:
                rects[cid] = rect
            if (
                IMAGE_SHAPE.search(style)
                and "verticalLabelPosition=bottom" not in style
            ):
                findings.append(
                    Finding(
                        path,
                        "icon-label",
                        f"cell {cid} ({value or 'unlabelled'}): an icon's label belongs underneath "
                        "it -- set verticalLabelPosition=bottom",
                    )
                )
            if IMAGE_SHAPE.search(style):
                service = _service_name(style)
                if service is not None and service not in value.replace("\n", " "):
                    findings.append(
                        Finding(
                            path,
                            "service-name",
                            f"cell {cid} ({value.splitlines()[0] if value else 'unlabelled'}): its "
                            f"icon is the {service} service icon, but the label does not contain "
                            f'"{service}". The AWS icon guidance requires the full official service '
                            "name on a service icon, not an abbreviation or a role word alone -- "
                            "put the role in a qualifier line, e.g. "
                            f'"{service}\\n(Controller A)"',
                        )
                    )
            if IMAGE_SHAPE.search(style) and rect is not None:
                icons.append((cid, rect, style, value))
            is_group = bool(GROUP_SHAPE.search(style))
            if is_group and value:
                match = SPACING_LEFT.search(style)
                spacing = float(match.group(1)) if match else 0.0
                if spacing > GROUP_SPACING_LEFT:
                    findings.append(
                        Finding(
                            path,
                            "boundary-label",
                            f"cell {cid} ({value}): spacingLeft={spacing:g} pushes the boundary "
                            f"title past the frame corner (max {GROUP_SPACING_LEFT}), where it "
                            "reads as the label of an icon inside the frame",
                        )
                    )
            if is_group and AWS_CLOUD_ICON.search(style):
                aws_cloud_groups.append((cid, value))
            if (is_group or _is_frame_container(style)) and rect is not None:
                containers.append(
                    _Container(
                        cid,
                        rect,
                        value,
                        is_group,
                        LEFT_ALIGNED.search(style) is not None,
                    )
                )
        if len(aws_cloud_groups) == 1:
            lone_cid, lone_value = aws_cloud_groups[0]
            if lone_value and not AWS_CLOUD_TITLE.match(lone_value):
                findings.append(
                    Finding(
                        path,
                        "aws-cloud-mislabel",
                        f"cell {lone_cid}: the only group_aws_cloud pictogram in this diagram is "
                        f'captioned {lone_value!r} instead of "AWS Cloud" -- title it "AWS Cloud" '
                        '(optionally "AWS Cloud (qualifier)"), or drop the pictogram for a boundary '
                        "that is not the account/partition edge",
                    )
                )
        for icon_cid, icon_rect, icon_style, icon_value in icons:
            overflow = _label_overflow(icon_rect, icon_style, icon_value)
            if overflow <= 0:
                continue
            _, iy, _, ih = icon_rect
            label_bottom = iy + ih + overflow
            for container in containers:
                if container.cid == icon_cid:
                    continue
                if not _contains(container.rect, icon_rect):
                    continue
                cx, cy, cw, ch = container.rect
                if label_bottom > cy + ch:
                    findings.append(
                        Finding(
                            path,
                            "label-overflow",
                            f"cell {icon_cid} ({icon_value.splitlines()[0] if icon_value else 'unlabelled'}): "
                            f"its label runs to an estimated y={label_bottom:.0f}, past container "
                            f"{container.cid}'s bottom edge at y={cy + ch:.0f} -- give the container "
                            "more height (see _label_overflow) rather than trimming the label",
                        )
                    )
        for container in containers:
            if (
                container.is_group
                or container.title_left_aligned
                or not container.value
            ):
                continue
            cx, cy, cw, ch = container.rect
            band_width = cw * TITLE_BAND_WIDTH_FRACTION
            band_x0 = cx + (cw - band_width) / 2
            band_x1 = band_x0 + band_width
            band_y1 = cy + TITLE_BAND_HEIGHT
            for cid, source, target, label, style, waypoints in edges:
                if source not in rects or target not in rects:
                    continue
                if waypoints:
                    continue  # a waypointed edge routes explicitly; it does not free-run through
                sx, sy = _anchor(rects[source], style, EXIT_X, EXIT_Y)
                tx, ty = _anchor(rects[target], style, ENTRY_X, ENTRY_Y)
                if abs(sx - tx) > EPSILON:
                    continue  # not a straight vertical run; the router may dodge the title
                if sy >= cy or ty <= band_y1:
                    continue  # does not span from above the frame to below its title band
                mid_x = (sx + tx) / 2
                if band_x0 <= mid_x <= band_x1:
                    findings.append(
                        Finding(
                            path,
                            "boundary-title-crossing",
                            f"edge {cid} ({source} -> {target}) runs straight through container "
                            f"{container.cid}'s centred title {container.value!r} at x={mid_x:.0f} "
                            f"-- set title_align_left=True on the Frame so the title moves to the "
                            "corner nothing crosses",
                        )
                    )
        icon_cids = {cid for cid, _rect_, _style_, _value_ in icons}
        for cid, source, target, label, style, waypoints in edges:
            if source not in rects or target not in rects:
                continue
            sx, sy = _anchor(rects[source], style, EXIT_X, EXIT_Y)
            tx, ty = _anchor(rects[target], style, ENTRY_X, ENTRY_Y)
            named = f" '{label}'" if label else ""
            # An edge landing on or leaving an icon at one of the icon's four *corners*, with no
            # waypoints to route it, renders as a diagonal line stabbing into the corner rather
            # than a clean orthogonal connection to the icon's centre. That is the exact defect
            # reported on the block figures: fork legs anchored at (0,1)/(1,0) drew slanted lines
            # into the FSx and controller icons. A corner is x in {0,1} AND y in {0,1} together; an
            # edge-midpoint like (1,0.5), used on host-count to leave around a label, is not a
            # corner and is left alone, and a waypointed edge routes itself so it is exempt too.
            if not waypoints:
                for end, node_cid, xr, yr in (
                    ("exit", source, EXIT_X, EXIT_Y),
                    ("entry", target, ENTRY_X, ENTRY_Y),
                ):
                    if node_cid not in icon_cids:
                        continue
                    fx = xr.search(style)
                    fy = yr.search(style)
                    if fx is None or fy is None:
                        continue
                    fxv, fyv = float(fx.group(1)), float(fy.group(1))
                    if fxv in (0.0, 1.0) and fyv in (0.0, 1.0):
                        findings.append(
                            Finding(
                                path,
                                "icon-corner-anchor",
                                f"edge {cid}{named}: its {end} anchor sits on icon {node_cid}'s "
                                f"corner ({fxv:g},{fyv:g}), which draws a diagonal line into the "
                                "corner -- anchor on the centre (0.5) and add waypoints so it "
                                "connects as an orthogonal tree branch",
                            )
                        )
            if waypoints:
                # Trace the polyline the file actually draws. Each segment may go down or run
                # horizontally (a fork branch); a segment that goes up is a backwards read.
                polyline = [(sx, sy), *waypoints, (tx, ty)]
                bad = None
                for (ax, ay), (bx, by) in itertools.pairwise(polyline):
                    if by - ay < -EPSILON:
                        bad = (ax, ay, bx, by)
                        break
                if bad is None:
                    continue
                ax, ay, bx, by = bad
                findings.append(
                    Finding(
                        path,
                        "flow-direction",
                        f"edge {cid}{named}: {source} -> {target} has a segment running upwards "
                        f"({ax:.0f},{ay:.0f} -> {bx:.0f},{by:.0f})",
                    )
                )
                continue
            heading = _heading(tx - sx, ty - sy)
            if heading is None:
                continue
            findings.append(
                Finding(
                    path,
                    "flow-direction",
                    f"edge {cid}{named}: {source} -> {target} runs {heading} ({sx:.0f},{sy:.0f} -> {tx:.0f},{ty:.0f})",
                )
            )
    return findings


ADVICE = """
  flow-direction: rerouting the line is rarely the fix, because the direction follows from the
  placement. Move the target so it sits right of or below its source; where two nodes must share a
  column, point the edge the way the thing it carries actually travels rather than drawing a return
  leg; and where a chain runs downwards, start it from a box, since the space under an icon belongs
  to that icon's label.

  aws-cloud-mislabel: caption the group "AWS Cloud" (optionally with a parenthetical qualifier), or
  choose a group without the group_aws_cloud pictogram when the boundary is not the account edge.

  label-overflow: give the container the height its icon's own label needs, or shorten the label to
  fewer lines -- not both wrong at once.

  boundary-title-crossing: pass title_align_left=True to the Frame so the title sits in the corner
  instead of the centre of the top edge.

  icon-corner-anchor: anchor the edge on the icon's centre (exit_at/entry_at x=0.5) and add
  waypoints so it drops, turns at a branch row, and re-enters the next icon's centre -- the
  orthogonal tree connector, not a diagonal leg off a corner.

  service-name: put the service's full official name in the label (e.g. "Amazon FSx for NetApp
  ONTAP"), with any role as a qualifier line -- not an abbreviation and not a role word alone."""


def check() -> int:
    files = walk("*.drawio")
    if not files:
        print("diagram-flow: no .drawio files found")
        return 0

    findings: list[Finding] = []
    for path in files:
        try:
            findings += inspect(path, path.read_text(encoding="utf-8"))
        except ET.ParseError as error:
            print(
                f"error: {path.relative_to(ROOT)} is not valid XML: {error}",
                file=sys.stderr,
            )
            return 1

    if findings:
        print("error: diagrams that do not read in one direction", file=sys.stderr)
        current = None
        for finding in findings:
            name = str(finding.path.relative_to(ROOT))
            if name != current:
                print(f"  {name}", file=sys.stderr)
                current = name
            print(f"    [{finding.rule}] {finding.detail}", file=sys.stderr)
        print(ADVICE, file=sys.stderr)
        return 1

    print(f"diagram-flow: {len(files)} file(s) read rightwards and downwards")
    return 0


# --- selftest ------------------------------------------------------------------------------------

# A gate is only trustworthy once it has been seen to fail, so every gate target runs this before the
# check itself. Without it, a refactor that makes `inspect` return nothing would look like a
# repository whose diagrams are all correct.


def _doc(cells: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8"?><mxfile><diagram id="d" name="d">'
        '<mxGraphModel pageWidth="880" pageHeight="600"><root>'
        '<mxCell id="0" /><mxCell id="1" parent="0" />'
        f"{cells}</root></mxGraphModel></diagram></mxfile>"
    )


def _node(
    cid: str, x: int, y: int, *, style: str = "rounded=1;", value: str = "n"
) -> str:
    return (
        f'<mxCell id="{cid}" value="{value}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="80" height="80" as="geometry" /></mxCell>'
    )


def _edge(
    cid: str,
    source: str,
    target: str,
    *,
    anchors: str = "",
    waypoints: tuple[tuple[int, int], ...] = (),
) -> str:
    if waypoints:
        pts = "".join(f'<mxPoint x="{x}" y="{y}" />' for x, y in waypoints)
        geometry = (
            '<mxGeometry relative="1" as="geometry">'
            f'<Array as="points">{pts}</Array></mxGeometry>'
        )
    else:
        geometry = '<mxGeometry relative="1" as="geometry" />'
    return (
        f'<mxCell id="{cid}" value="" style="endArrow=open;{anchors}" edge="1" '
        f'source="{source}" target="{target}" parent="1">{geometry}</mxCell>'
    )


def _frame(cid: str, x: int, y: int, w: int, h: int) -> str:
    return (
        f'<mxCell id="{cid}" value="" style="{GROUP}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>'
    )


ICON = "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;fontSize=16;"
ICON_SIDE = (
    "sketch=0;html=1;shape=image;verticalLabelPosition=middle;verticalAlign=middle;"
)
# A minimal SVG carrying only the <title> the service-name rule reads, base64-encoded into the
# data-URI form this repository's generator uses (comma, no `;base64` marker). Two titles: a
# top-level service icon (Arch_*) which the rule checks, and a resource icon (Res_*) which it does
# not. Real AWS assets carry far more, but the rule only reads the title, so this is enough.
_FSX_SVC_B64 = (
    "PD94bWwgdmVyc2lvbj0iMS4wIj8+PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmci"
    "Pjx0aXRsZT5JY29uLUFyY2hpdGVjdHVyZS82NC9BcmNoX0FtYXpvbi1GU3gtZm9yLU5ldEFwcC1PTlRB"
    "UF82NDwvdGl0bGU+PC9zdmc+"
)
_S3_RESOURCE_B64 = (
    "PD94bWwgdmVyc2lvbj0iMS4wIj8+PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmci"
    "Pjx0aXRsZT5JY29uLVJlc291cmNlL1N0b3JhZ2UvUmVzX0FtYXpvbi1TaW1wbGUtU3RvcmFnZS1TZXJ2"
    "aWNlX0J1Y2tldF80ODwvdGl0bGU+PC9zdmc+"
)
ICON_FSX = (
    "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
    f"fontSize=16;image=data:image/svg+xml,{_FSX_SVC_B64};"
)
ICON_S3_RESOURCE = (
    "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
    f"fontSize=16;image=data:image/svg+xml,{_S3_RESOURCE_B64};"
)
GROUP = "shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.group_aws_cloud;align=left;spacingLeft=30;"
GROUP_WIDE = GROUP.replace("spacingLeft=30", "spacingLeft=160")
GROUP_OTHER = GROUP.replace("group_aws_cloud", "group_corporate_data_center")
# The real `FRAME_STYLE` from build_diagrams.py, and its title-left-aligned variant -- copied
# rather than imported so this test does not depend on the other module's internals.
FRAME_CENTRED = (
    "rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#666666;"
    "fillColor=none;fontColor=#232F3E;fontSize=16;verticalAlign=top;align=center;spacingTop=6;"
)
FRAME_LEFT = FRAME_CENTRED.replace(
    "align=center;spacingTop=6;", "align=left;spacingTop=6;spacingLeft=16;"
)


def _frame_titled(
    cid: str, x: int, y: int, w: int, h: int, *, value: str, style: str = FRAME_CENTRED
) -> str:
    return (
        f'<mxCell id="{cid}" value="{value}" style="{style}" vertex="1" parent="1">'
        f'<mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" /></mxCell>'
    )


def selftest() -> int:
    cases: list[tuple[str, str, bool]] = [
        # (name, document, expected to be rejected)
        (
            "rightwards is accepted",
            _doc(_node("a", 0, 0) + _node("b", 200, 0) + _edge("e", "a", "b")),
            False,
        ),
        (
            "downwards is accepted",
            _doc(_node("a", 0, 0) + _node("b", 0, 200) + _edge("e", "a", "b")),
            False,
        ),
        (
            "down and to the right is accepted",
            _doc(_node("a", 0, 0) + _node("b", 200, 200) + _edge("e", "a", "b")),
            False,
        ),
        (
            "leftwards on the same row is rejected",
            _doc(_node("a", 200, 0) + _node("b", 0, 0) + _edge("e", "a", "b")),
            True,
        ),
        (
            "down and to the left is rejected, symmetric fan or not",
            _doc(
                _node("a", 200, 0)
                + _node("b", 0, 200)
                + _node("c", 400, 200)
                + _edge("e1", "a", "b")
                + _edge("e2", "a", "c")
            ),
            True,
        ),
        (
            "upwards is rejected",
            _doc(_node("a", 0, 200) + _node("b", 0, 0) + _edge("e", "a", "b")),
            True,
        ),
        (
            "a few pixels off the grid is not a direction",
            _doc(_node("a", 0, 0) + _node("b", 200, -6) + _edge("e", "a", "b")),
            False,
        ),
        (
            "a whole row up still is",
            _doc(_node("a", 0, 200) + _node("b", 200, 40) + _edge("e", "a", "b")),
            True,
        ),
        (
            "an edge to a node with no geometry of its own is skipped, not guessed at",
            _doc(_node("a", 200, 0) + _edge("e", "a", "nowhere")),
            False,
        ),
        (
            "an icon labelled underneath is accepted",
            _doc(_node("a", 0, 0, style=ICON)),
            False,
        ),
        (
            "an icon labelled beside itself is rejected",
            _doc(_node("a", 0, 0, style=ICON_SIDE)),
            True,
        ),
        (
            "a boundary title at the standard offset is accepted",
            _doc(_node("g", 0, 0, style=GROUP, value="AWS Cloud")),
            False,
        ),
        (
            "a boundary title pushed along the top edge is rejected",
            _doc(_node("g", 0, 0, style=GROUP_WIDE, value="AWS Cloud")),
            True,
        ),
        (
            "an untitled boundary is not judged on its offset",
            _doc(_node("g", 0, 0, style=GROUP_WIDE, value="")),
            False,
        ),
        (
            "a drop onto the far side of a wide frame advances, though its centre is behind",
            _doc(
                _node("a", 400, 0)
                + _frame("f", 0, 200, 520, 200)
                + _edge("e", "a", "f", anchors="exitX=0.5;exitY=1;entryX=0.9;entryY=0;")
            ),
            False,
        ),
        (
            "and a drop onto the near side of the same frame does not",
            _doc(
                _node("a", 400, 0)
                + _frame("f", 0, 200, 520, 200)
                + _edge(
                    "e", "a", "f", anchors="exitX=0.5;exitY=1;entryX=0.25;entryY=0;"
                )
            ),
            True,
        ),
        (
            "one backwards edge among good ones is caught",
            _doc(
                _node("a", 0, 0)
                + _node("b", 200, 0)
                + _node("c", 400, 0)
                + _edge("e1", "a", "b")
                + _edge("e2", "c", "b")
            ),
            True,
        ),
        (
            "AWS Cloud pictogram captioned AWS Cloud is accepted",
            _doc(_node("g", 0, 0, style=GROUP, value="AWS Cloud")),
            False,
        ),
        (
            "AWS Cloud pictogram with a parenthetical qualifier is accepted",
            _doc(_node("g", 0, 0, style=GROUP, value="AWS Cloud (Origin Region)")),
            False,
        ),
        (
            "AWS Cloud pictogram captioned with something else is rejected",
            _doc(_node("g", 0, 0, style=GROUP, value="FSx for ONTAP file server")),
            True,
        ),
        (
            "a different pictogram is not held to the AWS Cloud caption",
            _doc(_node("g", 0, 0, style=GROUP_OTHER, value="Cache Site")),
            False,
        ),
        (
            "a tree fork -- down, horizontal branch, down into a child's centre -- is accepted",
            _doc(
                _node("a", 200, 0)
                + _node("b", 0, 400)
                + _edge(
                    "e",
                    "a",
                    "b",
                    anchors="exitX=0.5;exitY=1;entryX=0.5;entryY=0;",
                    waypoints=((240, 200), (40, 200)),
                )
            ),
            False,
        ),
        (
            "a waypointed edge whose branch then climbs back up is rejected",
            _doc(
                _node("a", 0, 200)
                + _node("b", 400, 400)
                + _edge(
                    "e",
                    "a",
                    "b",
                    anchors="exitX=0.5;exitY=1;entryX=0.5;entryY=0;",
                    waypoints=((40, 300), (440, 100)),
                )
            ),
            True,
        ),
        (
            "an edge entering an icon on its corner with no waypoints is rejected",
            _doc(
                _node("a", 0, 0)
                + _node("b", 0, 300, style=ICON)
                + _edge("e", "a", "b", anchors="exitX=0.5;exitY=1;entryX=1;entryY=0;")
            ),
            True,
        ),
        (
            "the same corner anchor with waypoints (a routed tree branch) is accepted",
            _doc(
                _node("a", 0, 0)
                + _node("b", 0, 300, style=ICON)
                + _edge(
                    "e",
                    "a",
                    "b",
                    anchors="exitX=0.5;exitY=1;entryX=1;entryY=0;",
                    waypoints=((40, 150), (40, 150)),
                )
            ),
            False,
        ),
        (
            "an edge leaving an icon's side midpoint to route around its label is accepted",
            _doc(
                _node("a", 0, 0, style=ICON)
                + _node("b", 200, 200)
                + _edge("e", "a", "b", anchors="exitX=1;exitY=0.5;entryX=0.5;entryY=0;")
            ),
            False,
        ),
        (
            "an edge entering a non-icon box on its corner is not judged for this",
            _doc(
                _node("a", 0, 0)
                + _node("b", 0, 300)
                + _edge("e", "a", "b", anchors="exitX=0.5;exitY=1;entryX=1;entryY=0;")
            ),
            False,
        ),
        (
            "a service icon labelled with the full official name is accepted",
            _doc(_node("a", 0, 0, style=ICON_FSX, value="Amazon FSx for NetApp ONTAP")),
            False,
        ),
        (
            "the full name with a role qualifier line is accepted",
            _doc(
                _node(
                    "a",
                    0,
                    0,
                    style=ICON_FSX,
                    value="Amazon FSx for NetApp ONTAP&#10;(Controller A)",
                )
            ),
            False,
        ),
        (
            "a service icon labelled only with the abbreviation is rejected",
            _doc(
                _node("a", 0, 0, style=ICON_FSX, value="FSx for ONTAP&#10;Controller A")
            ),
            True,
        ),
        (
            "a service icon labelled only with a role word is rejected",
            _doc(_node("a", 0, 0, style=ICON_FSX, value="SMB SVM")),
            True,
        ),
        (
            "a resource icon is not held to the service-name rule",
            _doc(_node("a", 0, 0, style=ICON_S3_RESOURCE, value="source of truth")),
            False,
        ),
        (
            "two AWS Cloud pictograms as per-panel cards are not judged, even mistitled",
            _doc(
                _node("g1", 0, 0, style=GROUP, value="A. Panel one")
                + _node("g2", 500, 0, style=GROUP, value="B. Panel two")
            ),
            False,
        ),
        (
            "an icon whose two-line label fits inside its container is accepted",
            _doc(
                _node(
                    "g",
                    0,
                    0,
                    style=GROUP,
                    value="AWS Cloud",
                )
                + _node(
                    "a",
                    20,
                    40,
                    style=ICON,
                    value="Amazon FSx for NetApp ONTAP\n(qualifier)",
                )
            ).replace(
                '<mxGeometry x="0" y="0" width="80" height="80" as="geometry" />',
                '<mxGeometry x="0" y="0" width="400" height="220" as="geometry" />',
                1,
            ),
            False,
        ),
        (
            "the same icon in a container too short for its own label is rejected",
            _doc(
                _node(
                    "g",
                    0,
                    0,
                    style=GROUP,
                    value="AWS Cloud",
                )
                + _node(
                    "a",
                    20,
                    40,
                    style=ICON,
                    value="Amazon FSx for NetApp ONTAP\n(qualifier)",
                )
            ).replace(
                '<mxGeometry x="0" y="0" width="80" height="80" as="geometry" />',
                '<mxGeometry x="0" y="0" width="400" height="130" as="geometry" />',
                1,
            ),
            True,
        ),
        (
            "a centred frame title with no edge through it is accepted",
            _doc(_frame_titled("f", 0, 0, 400, 200, value="HA pair")),
            False,
        ),
        (
            "a straight vertical edge through a centred frame title is rejected",
            _doc(
                _node("a", 160, -100, style="rounded=1;")
                + _frame_titled("f", 0, 0, 400, 200, value="HA pair")
                + _node("b", 160, 250, style="rounded=1;")
                + _edge(
                    "e",
                    "a",
                    "b",
                    anchors="exitX=0.5;exitY=1;entryX=0.5;entryY=0;",
                )
            ),
            True,
        ),
        (
            "the same crossing edge is accepted once the title is left-aligned",
            _doc(
                _node("a", 160, -100, style="rounded=1;")
                + _frame_titled("f", 0, 0, 400, 200, value="HA pair", style=FRAME_LEFT)
                + _node("b", 160, 250, style="rounded=1;")
                + _edge(
                    "e",
                    "a",
                    "b",
                    anchors="exitX=0.5;exitY=1;entryX=0.5;entryY=0;",
                )
            ),
            False,
        ),
        (
            "an edge that only clips the frame's side, not its title band, is accepted",
            _doc(
                _node("a", 360, -100, style="rounded=1;")
                + _frame_titled("f", 0, 0, 400, 200, value="HA pair")
                + _node("b", 360, 250, style="rounded=1;")
                + _edge(
                    "e",
                    "a",
                    "b",
                    anchors="exitX=0.5;exitY=1;entryX=0.5;entryY=0;",
                )
            ),
            False,
        ),
    ]
    probe = ROOT / "selftest.drawio"
    failures = 0
    for name, document, should_reject in cases:
        rejected = bool(inspect(probe, document))
        if rejected != should_reject:
            verdict = "rejected" if rejected else "accepted"
            wanted = "reject" if should_reject else "accept"
            print(
                f"  selftest FAILED: {name} -> {verdict}, expected to {wanted}",
                file=sys.stderr,
            )
            failures += 1

    fan_case = next(d for n, d, _ in cases if n.startswith("down and to the left"))
    rules = {f.rule for f in inspect(probe, fan_case)}
    if rules != {"flow-direction"}:
        print(
            f"  selftest FAILED: fan case reported {rules}, expected flow-direction",
            file=sys.stderr,
        )
        failures += 1

    if failures:
        print(f"selftest: {failures} case(s) failed", file=sys.stderr)
        return 1
    print(f"selftest: {len(cases) + 1} case(s) behave as documented")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="prove the check rejects backwards edges and misplaced labels, and accepts compliant ones",
    )
    args = parser.parse_args()
    return selftest() if args.selftest else check()


if __name__ == "__main__":
    sys.exit(main())
