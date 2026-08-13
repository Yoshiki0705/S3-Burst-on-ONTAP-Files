#!/usr/bin/env python3
"""Generate the architecture diagrams, one spec per diagram, one file per language.

The two diagrams that were already committed here had no generator. Their labels were English in
both the Japanese and the English file, and the only localized string was the footnote — which
meant the pair could only be kept in step by editing two 24 KB XML files by hand. That is the same
failure mode as a hand-edited language switcher, and it is why `sync_lang_switcher.py` exists.
Diagram text now comes from one `LABELS` table, so a wording change lands in both languages or
neither.

Why the XML is written directly, rather than through the draw.io MCP tools or the built-in
`mxgraph.aws4.*` shapes — all three were tried in the sibling project and recorded in AGENTS.md:

* `insert_image_vertex` embeds icons in a form the draw.io CLI drops on export, so the picture is
  right on screen and empty in the exported file;
* `mxgraph.aws4.*` carries the 2019 icon generation, not the current asset package;
* the data URI must be `data:image/svg+xml,<base64>` — with `;base64` added, as the MIME spec would
  suggest, draw.io renders nothing.

Icons are read from the AWS Architecture Icons package rather than copied into the repository. The
package is a quarterly release from https://aws.amazon.com/architecture/icons/ and is not committed
here, so this is an authoring step and not a gate: the generated `.drawio` and the exported images
are the committed artefacts. `make all` therefore does not run it.

`--check` compares what the spec would produce against what is committed, cell by cell, and is how
a hand edit to a generated file gets caught. It needs the icon package, so it is a local check.

Run:
  python3 tools/build_diagrams.py --check     # committed files still match the spec
  python3 tools/build_diagrams.py --write     # regenerate .drawio for every language
  python3 tools/build_diagrams.py --write --export   # and run the draw.io CLI for SVG + PNG
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from xml.sax.saxutils import quoteattr

ROOT = Path(__file__).resolve().parent.parent
DIAGRAM_DIR = ROOT / "docs" / "_assets" / "diagrams"
IMAGE_DIR = ROOT / "docs" / "_assets" / "images"

LANGS = ("ja", "en")

# Fixed so that regeneration is byte-stable; a changing timestamp would put every diagram in every
# diff and hide the edit that mattered.
MODIFIED = "2026-08-10T00:00:00.000Z"
DRAWIO_CLI = Path("/Applications/draw.io.app/Contents/MacOS/draw.io")

# --- icons ---------------------------------------------------------------------------------------

# Relative to the icon package root. The `_Light` suffix on the general-purpose resource icons is
# easy to miss: `Res_Client_48.svg` does not exist, `Res_Client_48_Light.svg` does.
ICONS = {
    "users": "Resource-Icons_01302026/Res_General-Icons/Res_48_Light/Res_Users_48_Light.svg",
    "client": "Resource-Icons_01302026/Res_General-Icons/Res_48_Light/Res_Client_48_Light.svg",
    "s3_access_point": (
        "Resource-Icons_01302026/Res_Storage/"
        "Res_Amazon-Simple-Storage-Service_General-Access-Points_48.svg"
    ),
    "s3_bucket": (
        "Resource-Icons_01302026/Res_Storage/Res_Amazon-Simple-Storage-Service_Bucket_48.svg"
    ),
    "s3": (
        "Architecture-Service-Icons_01302026/Arch_Storage/64/"
        "Arch_Amazon-Simple-Storage-Service_64.svg"
    ),
    "fsx_ontap": (
        "Architecture-Service-Icons_01302026/Arch_Storage/64/"
        "Arch_Amazon-FSx-for-NetApp-ONTAP_64.svg"
    ),
}

# Native sizes. Rescaling an AWS icon is what the icon guidelines forbid, so the size follows the
# asset: 80 for an architecture (service) icon, 48 for a resource icon.
ICON_SIZE = {
    "users": 48,
    "client": 48,
    "s3_access_point": 48,
    "s3_bucket": 48,
    "s3": 80,
    "fsx_ontap": 80,
}

# --- styles --------------------------------------------------------------------------------------

GROUP_POINTS = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
    "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]]"
)


def group_style(gr_icon: str, stroke: str) -> str:
    return (
        f"{GROUP_POINTS};outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;fontSize=12;"
        f"fontStyle=1;fontColor=#232F3E;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};"
        f"strokeColor={stroke};fillColor=none;verticalAlign=top;align=left;spacingLeft=30;"
        "spacingTop=4;dashed=0;"
    )


def icon_style(data_uri: str) -> str:
    return (
        "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
        "labelPosition=center;align=center;imageAspect=1;aspect=fixed;fontSize=11;"
        f"fontColor=#232F3E;image={data_uri};"
    )


EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;"
    "strokeColor=#232F3E;strokeWidth=1;fontSize=11;fontColor=#232F3E;"
)

NOTE_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#666666;"
    "fillColor=#F5F5F5;fontColor=#333333;fontSize=11;align=left;verticalAlign=top;"
    "spacingLeft=10;spacingTop=6;"
)


# Figure annotations are read as items, not as a paragraph: a marker, a headline that stops at the
# noun, then the detail. `※` is the Japanese marker for a footnote and `*` the English one, so the
# two languages differ here even though the structure does not.
#
# The `<b>` and `<br>` reach draw.io because the cell style carries `html=1`. They are written as
# literal characters and escaped on the way into the attribute; `quoteattr` also escapes `"`, which
# plain `escape()` does not — an unescaped quote inside a value terminates the attribute, and
# draw.io responds by silently dropping that cell and every cell after it while still exporting
# successfully.
def note_body(heading: str, items: tuple[tuple[str, str, str], ...]) -> str:
    parts = [f"<b>{heading}</b>"]
    for marker, headline, detail in items:
        parts.append(f"{marker} <b>{headline}</b>")
        parts.append(detail)
    return "<br>".join(parts)


# --- labels --------------------------------------------------------------------------------------

# Node labels stay English in both languages: they are product names and protocol names, which the
# repository's translation rules exclude. Panel titles and footnotes are prose and are localized.
LABELS: dict[str, dict[str, str]] = {
    "aws_cloud": {
        "ja": "AWS Cloud (Origin Region)",
        "en": "AWS Cloud (Origin Region)",
    },
    "cache_site": {
        "ja": "Cache Site (On-premises / Remote Region)",
        "en": "Cache Site (On-premises / Remote Region)",
    },
    "s3_client": {
        "ja": "S3 Client (App / Pipeline)",
        "en": "S3 Client (App / Pipeline)",
    },
    "s3_access_point": {
        "ja": "Amazon S3 Access Point",
        "en": "Amazon S3 Access Point",
    },
    "origin_volume": {
        "ja": "Amazon FSx for NetApp ONTAP (Origin)",
        "en": "Amazon FSx for NetApp ONTAP (Origin)",
    },
    "cache_volume": {
        "ja": "Amazon FSx for NetApp ONTAP (FlexCache)",
        "en": "Amazon FSx for NetApp ONTAP (FlexCache)",
    },
    "file_client": {
        "ja": "NFS / SMB Client (HiL, EDA, VFX)",
        "en": "NFS / SMB Client (HiL, EDA, VFX)",
    },
    "put_object": {"ja": "PutObject", "en": "PutObject"},
    # Single line on purpose. A literal newline in an XML attribute is normalized to a space by any
    # conforming parser, and with `html=1` a `&#10;` collapses too, so a two-line edge label has to
    # be written as `<br>` or not at all. The committed diagram had the newline and rendered on one
    # line regardless; this states what actually shows.
    "flexcache_pull": {
        "ja": "FlexCache (pull on read)",
        "en": "FlexCache (pull on read)",
    },
    "nfs_smb": {"ja": "NFS / SMB", "en": "NFS / SMB"},
    "overview_note": {
        "ja": note_body(
            "補足",
            (
                (
                    "※1",
                    "S3 PutObject から FlexCache の NFS で読めるまでの実測",
                    "p50 14 ms（aws CLI + cat、n=30）。boto3 の持続セッションでは p50 8 ms。"
                    "差は測定方法による",
                ),
                (
                    "※2",
                    "FlexCache の加算分",
                    "p50 +5 ms（Origin を直接読む場合との差）",
                ),
                ("※3", "SMB と NFS は同等", "持続接続でどちらも p50 7 ms（n=30）"),
            ),
        ),
        "en": note_body(
            "Notes",
            (
                (
                    "*1",
                    "Measured S3 PutObject to FlexCache NFS read",
                    "p50 14 ms (aws CLI + cat, n=30); p50 8 ms with a persistent boto3 session. "
                    "The gap is the measurement method",
                ),
                ("*2", "FlexCache overhead", "p50 +5 ms against a direct origin read"),
                (
                    "*3",
                    "SMB and NFS are equivalent",
                    "p50 7 ms each over persistent mounts (n=30)",
                ),
            ),
        ),
    },
    # --- single-site diagram -------------------------------------------------------------------
    "panel_s3ap": {
        "ja": "A. FSx for ONTAP S3 Access Point のみ（ファンアウトなし）",
        "en": "A. FSx for ONTAP S3 Access Point only (no fan-out)",
    },
    "panel_s3files": {
        "ja": "B. S3 バケット + S3 Files",
        "en": "B. S3 bucket + S3 Files",
    },
    "s3_bucket": {
        "ja": "Amazon S3 Bucket (source of truth)",
        "en": "Amazon S3 Bucket (source of truth)",
    },
    "s3_files": {"ja": "Amazon S3 Files", "en": "Amazon S3 Files"},
    "fsx_ontap_volume": {
        "ja": "Amazon FSx for NetApp ONTAP (source of truth)",
        "en": "Amazon FSx for NetApp ONTAP (source of truth)",
    },
    "file_client_any": {
        "ja": "NFS v3 / v4.x, SMB Client",
        "en": "NFS v3 / v4.x, SMB Client",
    },
    # The compute list that belongs here — Amazon EC2, AWS Lambda, Amazon EKS, Amazon ECS — cannot
    # be abbreviated in a diagram label and does not fit in two lines unabbreviated, so it lives in
    # the table beside the figure instead.
    "file_client_nfs41": {
        "ja": "NFS v4.1 / v4.2 Client",
        "en": "NFS v4.1 / v4.2 Client",
    },
    # The edge carries the protocol only; the client node label carries the rest.
    "nfs41_protocol": {
        "ja": "NFS v4.1 / v4.2",
        "en": "NFS v4.1 / v4.2",
    },
    "auto_sync": {
        "ja": "自動同期（取り込みは数秒）",
        "en": "auto-sync (import in seconds)",
    },
    "single_site_note": {
        "ja": note_body(
            "補足",
            (
                (
                    "※1",
                    "どちらも 1 拠点で完結し、FlexCache によるファンアウトは不要",
                    "この構成が対象とするのは、利用側が別の場所にあって動かせない場合",
                ),
                (
                    "※2",
                    "選択を先に絞るのは費用ではなく対応プロトコル",
                    "A は NFS v3 / v4.x と SMB。B は NFS v4.1 と v4.2 のみで、SMB と NFSv3 は対象外",
                ),
                (
                    "※3",
                    "正典の置き場所の違い",
                    "A は FSx for ONTAP のボリューム。B は S3 バケットのまま",
                ),
                (
                    "※4",
                    "B の利用側は AWS 上のコンピュートに限られる",
                    "Amazon EC2、AWS Lambda、Amazon EKS、Amazon ECS。マウントヘルパーが必要",
                ),
            ),
        ),
        "en": note_body(
            "Notes",
            (
                (
                    "*1",
                    "Both complete within one site; no FlexCache fan-out",
                    "This architecture is for consumers that sit elsewhere and cannot be moved",
                ),
                (
                    "*2",
                    "Protocol coverage narrows the choice before cost does",
                    "A serves NFS v3 / v4.x and SMB. B serves NFS v4.1 and v4.2 only; NFSv3 and "
                    "SMB are out of scope",
                ),
                (
                    "*3",
                    "The source of truth sits in different places",
                    "A: the FSx for ONTAP volume. B: the S3 bucket, unchanged",
                ),
                (
                    "*4",
                    "B requires consumers on AWS compute",
                    "Amazon EC2, AWS Lambda, Amazon EKS, Amazon ECS, with a mount helper",
                ),
            ),
        ),
    },
}


CJK = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff]")


def label(key: str, lang: str) -> str:
    """Look up a label, refusing to emit Japanese into an English diagram.

    Two failures are caught here rather than by looking at the picture. A spec that names a label
    with no entry stops the build instead of drawing an empty string; and a new Japanese label
    copied into the English column stops it too. The second is the one that would otherwise ship:
    the file renders, the export succeeds, and only a reader who does not read Japanese finds out.
    """
    try:
        value = LABELS[key][lang]
    except KeyError as exc:
        raise SystemExit(f"build_diagrams: no {lang} label for {key!r}") from exc
    if lang != "ja" and CJK.search(value):
        raise SystemExit(
            f"build_diagrams: the {lang} label for {key!r} still contains Japanese: {value[:60]!r}"
        )
    return value


# --- spec ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Node:
    cid: str
    icon: str
    label: str
    x: int
    y: int


@dataclass(frozen=True)
class Group:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int
    gr_icon: str = "group_aws_cloud"
    stroke: str = "#232F3E"


@dataclass(frozen=True)
class Edge:
    cid: str
    source: str
    target: str
    label: str = ""


@dataclass(frozen=True)
class Note:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


@dataclass(frozen=True)
class Diagram:
    name: str
    diagram_id: str
    width: int
    height: int
    groups: tuple[Group, ...] = ()
    nodes: tuple[Node, ...] = ()
    edges: tuple[Edge, ...] = ()
    notes: tuple[Note, ...] = ()

    def filename(self, lang: str) -> str:
        # Japanese keeps the bare name: the published blog posts link the exported PNG by these
        # exact paths, so renaming either file breaks a live image.
        suffix = "" if lang == "ja" else f"-{lang}"
        return f"{self.name}{suffix}.drawio"


def centred(icon: str, cx: int, cy: int) -> tuple[int, int]:
    half = ICON_SIZE[icon] // 2
    return cx - half, cy - half


def _overview() -> Diagram:
    """The architecture as published: collect over S3, fan out with FlexCache."""
    return Diagram(
        name="s3burst-architecture-overview",
        diagram_id="s3burst-overview",
        width=1350,
        height=580,
        groups=(
            Group("aws_cloud", "aws_cloud", 50, 50, 560, 350),
            Group(
                "edge_group",
                "cache_site",
                720,
                50,
                500,
                350,
                gr_icon="group_corporate_data_center",
                stroke="#147EBA",
            ),
        ),
        nodes=(
            Node("s3client", "users", "s3_client", 100, 180),
            Node("s3ap", "s3_access_point", "s3_access_point", 270, 180),
            Node("origin_vol", "fsx_ontap", "origin_volume", 420, 164),
            Node("cache_vol", "fsx_ontap", "cache_volume", 850, 164),
            Node("nfs_client", "client", "file_client", 1060, 180),
        ),
        edges=(
            Edge("e1", "s3client", "s3ap", "put_object"),
            Edge("e2", "s3ap", "origin_vol"),
            Edge("e3", "origin_vol", "cache_vol", "flexcache_pull"),
            Edge("e4", "cache_vol", "nfs_client", "nfs_smb"),
        ),
        notes=(Note("note", "overview_note", 50, 425, 1250, 125),),
    )


def _single_site() -> Diagram:
    """The two ways to read S3-collected data as files inside one site.

    Deliberately not drawn as a variant of this architecture. The decision tree already answers the
    same-site case with "the S3 Access Point alone is enough; no fan-out" — it is an exit from the
    architecture, not a configuration of it, and the panels are laid out so a reader compares the
    two single-site options rather than reading either as a reduced form of the main diagram.
    """
    row_a, row_b = 175, 445
    return Diagram(
        name="s3burst-single-site-options",
        diagram_id="s3burst-single-site",
        width=1180,
        height=780,
        groups=(
            Group("panel_a", "panel_s3ap", 40, 60, 1100, 230),
            Group("panel_b", "panel_s3files", 40, 330, 1100, 230),
        ),
        nodes=(
            Node("a_client", "users", "s3_client", *centred("users", 160, row_a)),
            Node(
                "a_ap",
                "s3_access_point",
                "s3_access_point",
                *centred("s3_access_point", 400, row_a),
            ),
            Node(
                "a_vol",
                "fsx_ontap",
                "fsx_ontap_volume",
                *centred("fsx_ontap", 680, row_a),
            ),
            Node("a_file", "client", "file_client_any", *centred("client", 980, row_a)),
            Node("b_client", "users", "s3_client", *centred("users", 160, row_b)),
            Node(
                "b_bucket", "s3_bucket", "s3_bucket", *centred("s3_bucket", 400, row_b)
            ),
            Node("b_files", "s3", "s3_files", *centred("s3", 680, row_b)),
            Node(
                "b_file", "client", "file_client_nfs41", *centred("client", 980, row_b)
            ),
        ),
        edges=(
            Edge("a1", "a_client", "a_ap", "put_object"),
            Edge("a2", "a_ap", "a_vol"),
            Edge("a3", "a_vol", "a_file", "nfs_smb"),
            Edge("b1", "b_client", "b_bucket", "put_object"),
            Edge("b2", "b_bucket", "b_files", "auto_sync"),
            Edge("b3", "b_files", "b_file", "nfs41_protocol"),
        ),
        notes=(Note("note", "single_site_note", 40, 590, 1100, 155),),
    )


DIAGRAMS = (_overview(), _single_site())


# --- rendering -----------------------------------------------------------------------------------


def icon_package(explicit: str | None) -> Path:
    """Locate the AWS Architecture Icons package."""
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_dir():
            raise SystemExit(f"build_diagrams: --icons {path} is not a directory")
        return path
    env = os.environ.get("AWS_ICON_PACKAGE")
    if env:
        return icon_package(env)
    candidates = sorted(Path.home().glob("Downloads/Icon-package_*"), reverse=True)
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise SystemExit(
        "build_diagrams: the AWS Architecture Icons package was not found.\n"
        "  Download the current quarterly release from "
        "https://aws.amazon.com/architecture/icons/ and either leave it in ~/Downloads or pass\n"
        "  --icons <path> / set AWS_ICON_PACKAGE. The package is not committed here, which is why\n"
        "  the generated .drawio files are."
    )


def data_uris(package: Path) -> dict[str, str]:
    """Read each icon and build its draw.io data URI.

    The comma rather than `;base64,` is not a typo: draw.io renders nothing when the encoding is
    declared the way the MIME specification would suggest.
    """
    uris = {}
    for key, relative in ICONS.items():
        path = package / relative
        if not path.is_file():
            raise SystemExit(f"build_diagrams: {relative} missing from {package}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        uris[key] = f"data:image/svg+xml,{encoded}"
    return uris


def render(diagram: Diagram, lang: str, uris: dict[str, str]) -> str:
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<mxfile host="app.diagrams.net" modified="{MODIFIED}" agent="build_diagrams.py" '
        'version="24.0.0" type="device">',
    ]
    suffix = "" if lang == "ja" else f"-{lang}"
    name = f"{diagram.name}{suffix}"
    lines.append(f'  <diagram id="{diagram.diagram_id}{suffix}" name="{name}">')
    lines.append(
        f'    <mxGraphModel dx="1422" dy="762" grid="1" gridSize="10" guides="1" tooltips="1" '
        f'connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="{diagram.width}" '
        f'pageHeight="{diagram.height}" math="0" shadow="0">'
    )
    lines += [
        "      <root>",
        '        <mxCell id="0" />',
        '        <mxCell id="1" parent="0" />',
    ]

    def vertex(
        cid: str, value: str, style: str, x: int, y: int, w: int, h: int
    ) -> None:
        lines.append(
            f"        <mxCell id={quoteattr(cid)} value={quoteattr(value)} "
            f'style={quoteattr(style)} vertex="1" parent="1">'
        )
        lines.append(
            f'          <mxGeometry x="{x}" y="{y}" width="{w}" height="{h}" as="geometry" />'
        )
        lines.append("        </mxCell>")

    for group in diagram.groups:
        vertex(
            group.cid,
            label(group.label, lang),
            group_style(group.gr_icon, group.stroke),
            group.x,
            group.y,
            group.width,
            group.height,
        )
    for node in diagram.nodes:
        size = ICON_SIZE[node.icon]
        vertex(
            node.cid,
            label(node.label, lang),
            icon_style(uris[node.icon]),
            node.x,
            node.y,
            size,
            size,
        )
    for edge in diagram.edges:
        value = label(edge.label, lang) if edge.label else ""
        lines.append(
            f"        <mxCell id={quoteattr(edge.cid)} value={quoteattr(value)} "
            f'style={quoteattr(EDGE_STYLE)} edge="1" source={quoteattr(edge.source)} '
            f'target={quoteattr(edge.target)} parent="1">'
        )
        lines.append('          <mxGeometry relative="1" as="geometry" />')
        lines.append("        </mxCell>")
    for note in diagram.notes:
        vertex(
            note.cid,
            label(note.label, lang),
            NOTE_STYLE,
            note.x,
            note.y,
            note.width,
            note.height,
        )

    lines += ["      </root>", "    </mxGraphModel>", "  </diagram>", "</mxfile>", ""]
    return "\n".join(lines)


# --- checking ------------------------------------------------------------------------------------


def cells(xml: str) -> list[tuple[str, str, str, str]]:
    """Reduce a document to the parts a reader sees, so formatting is not compared."""
    out = []
    for cell in ET.fromstring(xml).find(".//root").iter("mxCell"):
        geometry = cell.find("mxGeometry")
        geo = (
            " ".join(f"{k}={v}" for k, v in sorted(geometry.attrib.items()))
            if geometry is not None
            else ""
        )
        style = re.sub(
            r"image=data:image/svg\+xml,([A-Za-z0-9+/=]{16})[A-Za-z0-9+/=]*",
            r"image=<\1...>",
            cell.get("style") or "",
        )
        out.append((cell.get("id") or "", cell.get("value") or "", style, geo))
    return out


def check(uris: dict[str, str]) -> int:
    problems = 0
    for diagram in DIAGRAMS:
        for lang in LANGS:
            path = DIAGRAM_DIR / diagram.filename(lang)
            if not path.is_file():
                print(f"  missing   {path.relative_to(ROOT)}", file=sys.stderr)
                problems += 1
                continue
            want = cells(render(diagram, lang, uris))
            got = cells(path.read_text(encoding="utf-8"))
            if want == got:
                continue
            problems += 1
            print(f"  differs   {path.relative_to(ROOT)}", file=sys.stderr)
            for a, b in zip(want, got):
                if a != b:
                    print(f"      spec: {a}", file=sys.stderr)
                    print(f"      file: {b}", file=sys.stderr)
            if len(want) != len(got):
                print(
                    f"      cell count spec={len(want)} file={len(got)}",
                    file=sys.stderr,
                )
    if problems:
        print(
            "\n  A generated diagram was edited by hand, or the spec moved without a regenerate.\n"
            "  Run: python3 tools/build_diagrams.py --write --export",
            file=sys.stderr,
        )
        return 1
    print(f"diagrams: {len(DIAGRAMS) * len(LANGS)} file(s) match the spec")
    return 0


# --- exporting -----------------------------------------------------------------------------------


def export(diagram: Diagram, lang: str) -> None:
    source = DIAGRAM_DIR / diagram.filename(lang)
    stem = source.stem
    if not DRAWIO_CLI.is_file():
        print(
            f"  draw.io CLI not found at {DRAWIO_CLI}; skipping export", file=sys.stderr
        )
        return
    runs = (
        # SVG for the repository: crawlers and screen readers can reach the text.
        (IMAGE_DIR / f"{stem}.svg", ["--format", "svg", "--embed-svg-images"]),
        # PNG at 2x for the blog posts, which do not render SVG reliably.
        (IMAGE_DIR / f"{stem}@2x.png", ["--format", "png", "--scale", "2"]),
    )
    for target, extra in runs:
        subprocess.run(
            [
                str(DRAWIO_CLI),
                "--export",
                "--border",
                "12",
                *extra,
                "--output",
                str(target),
                str(source),
            ],
            check=True,
            capture_output=True,
        )
        print(f"  exported  {target.relative_to(ROOT)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="regenerate the .drawio files"
    )
    parser.add_argument("--export", action="store_true", help="also export SVG and PNG")
    parser.add_argument(
        "--check", action="store_true", help="compare committed files to the spec"
    )
    parser.add_argument("--icons", help="path to the AWS Architecture Icons package")
    args = parser.parse_args()

    if not (args.write or args.check):
        parser.error("give --write or --check")

    uris = data_uris(icon_package(args.icons))

    if args.check:
        return check(uris)

    DIAGRAM_DIR.mkdir(parents=True, exist_ok=True)
    IMAGE_DIR.mkdir(parents=True, exist_ok=True)
    for diagram in DIAGRAMS:
        for lang in LANGS:
            path = DIAGRAM_DIR / diagram.filename(lang)
            path.write_text(render(diagram, lang, uris), encoding="utf-8")
            print(f"  wrote     {path.relative_to(ROOT)}")
            if args.export:
                export(diagram, lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
