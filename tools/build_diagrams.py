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

# Icons that are not AWS assets, resolved under docs/_assets/icons/. That directory is gitignored on
# purpose: the same reasoning that keeps the AWS Architecture Icons package outside the repository
# applies to any vendor mark, so what gets committed is the finished diagram with the icon embedded,
# never the icon as a file of its own. Obtain the ONTAP 9 product badge from NetApp and place it at
# the path below before running --write.
LOCAL_ICON_DIR = ROOT / "docs" / "_assets" / "icons"
LOCAL_ICONS = {
    "ontap_9": "ontap-9.png",
    "azure_netapp_files": "azure-netapp-files.svg",
    # Google publishes no product icon for Google Cloud NetApp Volumes. Its own product icon guide
    # lists the service under Storage without the marker it uses for products that carry a unique
    # icon, so the category icon plus the product name as a label is what Google's system prescribes
    # -- the same treatment Filestore gets. The label is what distinguishes them.
    "gcnv_storage_category": "google-cloud-storage-category.svg",
}

# Printed when a badge is missing, so the message says where to get it rather than only that it is
# absent. Each vendor permits use in architecture diagrams and documentation; none of them is
# committed here, which is the same stance the AWS package gets.
LOCAL_ICON_SOURCES = {
    "ontap_9": "the ONTAP 9 product badge from NetApp",
    "azure_netapp_files": (
        "Azure_Public_Service_Icons/Icons/storage/10096-icon-service-Azure-NetApp-Files.svg "
        "in the Azure architecture icons package, https://learn.microsoft.com/azure/architecture/icons/"
    ),
    "gcnv_storage_category": (
        "'Category Icons/Storage/SVG/Storage-512-color.svg' in the Google Cloud product category "
        "icons package, https://cloud.google.com/icons"
    ),
}

# A data URI needs the type that matches the bytes. The badge set is no longer PNG-only, and getting
# this wrong exports a broken-image placeholder while still reporting success.
MIME_BY_SUFFIX = {".png": "image/png", ".svg": "image/svg+xml"}

# Relative to the icon package root, with `{d}` standing for the package's release date. That date
# appears in every top-level directory name inside the package (`Resource-Icons_07312026/`), and it
# changes every quarter -- so it is read off the package directory rather than written here. Writing
# it out would pin the tool to one release and give the same fact two homes, and the failure it
# produces on the next package is a path that does not resolve, which reads as a missing icon.
#
# The `_Light` suffix on the general-purpose resource icons is easy to miss: `Res_Client_48.svg`
# does not exist, `Res_Client_48_Light.svg` does.
ICONS = {
    "users": "Resource-Icons_{d}/Res_General-Icons/Res_48_Light/Res_Users_48_Light.svg",
    "client": "Resource-Icons_{d}/Res_General-Icons/Res_48_Light/Res_Client_48_Light.svg",
    "s3_access_point": (
        "Resource-Icons_{d}/Res_Storage/"
        "Res_Amazon-Simple-Storage-Service_General-Access-Points_48.svg"
    ),
    "s3_bucket": (
        "Resource-Icons_{d}/Res_Storage/Res_Amazon-Simple-Storage-Service_Bucket_48.svg"
    ),
    "s3": (
        "Architecture-Service-Icons_{d}/Arch_Storage/64/"
        "Arch_Amazon-Simple-Storage-Service_64.svg"
    ),
    "fsx_ontap": (
        "Architecture-Service-Icons_{d}/Arch_Storage/64/"
        "Arch_Amazon-FSx-for-NetApp-ONTAP_64.svg"
    ),
    # Added in the 07312026 package; absent from 01302026, which predates the service's GA.
    "aws_interconnect": (
        "Architecture-Service-Icons_{d}/Arch_Networking-Content-Delivery/64/"
        "Arch_AWS-Interconnect_64.svg"
    ),
    "efs": ("Architecture-Service-Icons_{d}/Arch_Storage/64/Arch_Amazon-EFS_64.svg"),
    "direct_connect": (
        "Architecture-Service-Icons_{d}/Arch_Networking-Content-Delivery/64/"
        "Arch_AWS-Direct-Connect_64.svg"
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
    "aws_interconnect": 80,
    "direct_connect": 80,
    "efs": 80,
    # Non-AWS service icons, held at 80 so they read as peers of the AWS service icons beside them
    # rather than as something less important. Each vendor's own rules are met at this size:
    #
    # Microsoft asks that the icon appear as it does within Azure, that the product name sit close to
    # it, and that it is not cropped, flipped, rotated or reshaped. The source is an 18 px square SVG
    # and is scaled uniformly, so nothing is distorted; the product name is the cell label directly
    # underneath. https://learn.microsoft.com/azure/architecture/icons/
    "azure_netapp_files": 80,
    # Google's product icon system gives unique icons to core products only and a shared category
    # icon to everything else, with the product name distinguishing them. Google Cloud NetApp Volumes
    # is listed under Storage without the core-product marker, so the Storage category icon is what
    # the system prescribes -- the same icon Filestore uses. https://cloud.google.com/icons
    "gcnv_storage_category": 80,
    # Placed at 80 to match the AWS service icons it sits beside. The source badge is 96 px square,
    # so this is the one icon that is scaled; an AWS asset would not be, but holding a third-party
    # badge at its own size next to an 80 px service icon reads as a difference in importance.
    "ontap_9": 80,
}

# --- styles --------------------------------------------------------------------------------------

GROUP_POINTS = (
    "points=[[0,0],[0.25,0],[0.5,0],[0.75,0],[1,0],[1,0.25],[1,0.5],[1,0.75],"
    "[1,1],[0.75,1],[0.5,1],[0.25,1],[0,1],[0,0.75],[0,0.5],[0,0.25]]"
)


BODY_FONT_SIZE = 11
# The group title is one point larger than body text and bold, so it reads as a boundary label.
# Derived rather than configured, so a diagram sets one number.
GROUP_FONT_OFFSET = 1


def resized(style: str, size: int) -> str:
    """Restate a style at a different font size.

    Every style here carries exactly one `fontSize`, so a substitution is total. At the default the
    result is the constant unchanged, which is what keeps the ten diagrams that predate this
    byte-identical -- `make diagrams-check` compares the generated bytes, so a formatting change
    here is indistinguishable from a content change there.
    """
    if size == BODY_FONT_SIZE:
        return style
    return re.sub(r"fontSize=\d+", f"fontSize={size}", style)


def group_style(gr_icon: str, stroke: str, size: int = BODY_FONT_SIZE) -> str:
    return (
        f"{GROUP_POINTS};outlineConnect=0;gradientColor=none;html=1;whiteSpace=wrap;"
        f"fontSize={size + GROUP_FONT_OFFSET};"
        f"fontStyle=1;fontColor=#232F3E;shape=mxgraph.aws4.group;grIcon=mxgraph.aws4.{gr_icon};"
        f"strokeColor={stroke};fillColor=none;verticalAlign=top;align=left;spacingLeft=30;"
        "spacingTop=4;dashed=0;"
    )


def icon_style(data_uri: str, size: int = BODY_FONT_SIZE) -> str:
    return (
        "sketch=0;html=1;shape=image;verticalLabelPosition=bottom;verticalAlign=top;"
        f"labelPosition=center;align=center;imageAspect=1;aspect=fixed;fontSize={size};"
        f"fontColor=#232F3E;image={data_uri};"
    )


EDGE_STYLE = (
    "edgeStyle=orthogonalEdgeStyle;rounded=0;html=1;endArrow=open;endFill=0;"
    "strokeColor=#232F3E;strokeWidth=1;fontSize=11;fontColor=#232F3E;"
)

# A plain dashed container, used where landing an edge on one icon would misstate the architecture.
# The cache platform is one of two products, so the FlexCache edge has to arrive at the choice rather
# than at whichever option happens to be drawn first. Dashed and unfilled so it reads as a grouping
# rather than as another boundary like the AWS Cloud and site groups.
FRAME_STYLE = (
    "rounded=1;whiteSpace=wrap;html=1;dashed=1;dashPattern=8 4;strokeColor=#666666;"
    "fillColor=none;fontColor=#232F3E;fontSize=11;verticalAlign=top;align=center;spacingTop=6;"
)

# Free-standing text with no box, for the "or" between two alternatives.
TEXT_STYLE = (
    "text;html=1;strokeColor=none;fillColor=none;align=center;verticalAlign=middle;"
    "fontSize=11;fontStyle=1;fontColor=#232F3E;"
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
    # --- two ceilings -----------------------------------------------------------------------
    # This figure answers "why did the same file system return two numbers", so every label names a
    # location rather than a value. The measured figures stay in the prose table beside it: kept in
    # the image they would be maintained by hand in two places, and the image is not searchable,
    # translatable or reachable by a screen reader.
    "tc_file_server": {
        "ja": "FSx for ONTAP ファイルサーバー",
        "en": "FSx for ONTAP file server",
    },
    "tc_client": {
        "ja": "NFS / SMB クライアント",
        "en": "NFS / SMB clients",
    },
    "tc_cache_layer": {
        "ja": "インメモリ + NVMe\nリードキャッシュ",
        "en": "In-memory + NVMe\nread cache",
    },
    "tc_ssd": {
        "ja": "SSD ストレージ\n(プロビジョンド IOPS)",
        "en": "SSD storage\n(provisioned IOPS)",
    },
    "tc_hit": {"ja": "キャッシュにある", "en": "in cache"},
    "tc_miss": {"ja": "キャッシュに無い", "en": "not in cache"},
    "tc_read": {"ja": "読み取り", "en": "read"},
    # Naming what sets each ceiling, not what it measured. "Overlap" is the workload property the
    # reader controls; it is the only handle on which path serves the read.
    "tc_ceiling_cache": {
        "ja": "上限: ネットワーク経路\n(領域が重なるほど近づく)",
        "en": "Ceiling: network path\n(approached as regions overlap)",
    },
    "tc_ceiling_disk": {
        "ja": "上限: ディスク経路\n(領域が重ならないほど近づく)",
        "en": "Ceiling: disk path\n(approached as regions diverge)",
    },
    # The host-count run. No figure carries a measured number: a number needs the date, the
    # version, the object size and the concurrency beside it to mean anything, and a label has room
    # for none of that. The tables in the verification record hold the figures.
    "hc_clients": {
        "ja": "SMB クライアント 8 台\n(1 台あたり 64 スレッド固定)",
        "en": "8 SMB clients\n(64 threads each, held constant)",
    },
    "hc_host_first": {"ja": "1 台目", "en": "host 1"},
    "hc_host_second": {"ja": "2 台目", "en": "host 2"},
    "hc_host_last": {"ja": "8 台目", "en": "host 8"},
    "hc_more": {"ja": "…", "en": "…"},
    # The two variants are the whole point of the figure: everything below them is identical, so a
    # difference in the total is a difference in which regions were read and nothing else.
    "hc_shared": {
        "ja": "同一ファイル\n全台が同じ範囲を読む",
        "en": "Same file\nevery host reads the same range",
    },
    "hc_disjoint": {
        "ja": "重ならない領域\n各台が 1/N の範囲を読む",
        "en": "Disjoint ranges\neach host reads 1/N of the file",
    },
    "hc_share": {
        "ja": "CIFS 共有 1 本 (SMB 3.1.1)\nMultichannel 4 チャネル",
        "en": "One CIFS share (SMB 3.1.1)\nMultichannel, 4 channels",
    },
    "hc_svm": {"ja": "SMB SVM", "en": "SMB SVM"},
    "hc_port": {
        "ja": "1 ノードの物理ポート 1 本\n(クライアント合計と突き合わせる)",
        "en": "One physical port on one node\n(corroborates the client sum)",
    },
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
    # Kept to one rendered line. At 220 px the two-line version pushed down onto the icon below it,
    # which the geometry checks cannot see — a label is laid out by the renderer, not by the spec.
    # The mechanism is already named on the incoming edge, so the frame does not repeat it.
    "cache_platform": {
        "ja": "Cache ボリューム（いずれか）",
        "en": "Cache volume (either one)",
    },
    "cache_volume_fsx": {
        "ja": "Amazon FSx for NetApp ONTAP",
        "en": "Amazon FSx for NetApp ONTAP",
    },
    # Non-AWS products are exempt from the Amazon / AWS prefix rule. "on-premises" is the qualifier
    # AWS's own documentation uses for this configuration, and it is load-bearing: the other ONTAP
    # platforms are unverified here, so the icon must not stand for "any ONTAP".
    "cache_volume_ontap": {
        "ja": "ONTAP 9（オンプレミス）",
        "en": "ONTAP 9 (on-premises)",
    },
    "either_of": {"ja": "または", "en": "or"},
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
    # The FlexCache edge used to cross the gap with nothing on it, and a reader asked where AWS
    # Interconnect was. The honest answer is that it depends on what the cache side is, and that the
    # cloud-to-cloud service is not this link at all. So the link carries a frame naming the three
    # cases rather than a single product icon: one icon here would read as a requirement, and a
    # Direct Connect icon in particular would imply a circuit for the same-Region case that needs
    # none.
    "connect_layer": {
        "ja": "接続層（いずれか）",
        "en": "Connectivity layer (one of)",
    },
    "link_same_region": {
        "ja": "同一リージョン: VPC ピアリング",
        "en": "Same Region: VPC peering",
    },
    "link_cross_region": {
        "ja": "別リージョン: VPC ピアリング /<br>Transit Gateway / Cloud WAN",
        "en": "Cross-Region: VPC peering /<br>Transit Gateway / Cloud WAN",
    },
    "link_onprem": {
        "ja": "オンプレミス: Direct Connect /<br>Site-to-Site VPN",
        "en": "On-premises: Direct Connect /<br>Site-to-Site VPN",
    },
    "overview_note": {
        "ja": note_body(
            "補足",
            (
                (
                    "※1",
                    "S3 PutObject から FlexCache の NFS で読めるまでの実測",
                    "p50 14 ms（aws CLI + cat、n=30）。boto3 の持続セッションでは p50 8 ms。"
                    "差は測定方法による。Cache 側も FSx for ONTAP、同一リージョン、"
                    "VPC ピアリング、ap-northeast-1、ONTAP 9.18.1P3D1",
                ),
                (
                    "※2",
                    "FlexCache の加算分",
                    "p50 +5 ms（Origin を直接読む場合との差）",
                ),
                ("※3", "SMB と NFS は同等", "持続接続でどちらも p50 7 ms（n=30）"),
                (
                    "※4",
                    "Cache 側は FSx for ONTAP かオンプレミスの ONTAP 9",
                    "AWS が文書化している FlexCache 構成はこの 2 つ。Cloud Volumes ONTAP、"
                    "ONTAP Select、Azure NetApp Files、Google Cloud NetApp Volumes は未検証で、"
                    "「ONTAP ベースだから動く」とは書かない",
                ),
                (
                    "※5",
                    "この図の主経路（オンプレミスの Cache）は未検証",
                    "上の数値はすべて Cache 側も FSx for ONTAP の条件で測ったもの。"
                    "オンプレミス ONTAP を Cache とする経路は AWS の対応構成にあるが実機で追っていない。"
                    "遠隔拠点の遅延も未測定",
                ),
                (
                    "※6",
                    "接続層は Cache 側のケースで変わる",
                    "FlexCache はクラスタ / SVM ピアリングを要求し、その下を通る経路が図中央の 3 つ。"
                    "AWS Interconnect – multicloud はこの線ではない。AWS と他 CSP を結ぶもので、"
                    "この図に他クラウドは出てこない（他クラウドとの接続は別の図にまとめてある）。"
                    "オンプレミスの回線を調達する手段としては "
                    "AWS Interconnect – last mile もあり、こちらは同じユーザーガイドの別サービス",
                ),
            ),
        ),
        "en": note_body(
            "Notes",
            (
                (
                    "*1",
                    "Measured S3 PutObject to FlexCache NFS read",
                    "p50 14 ms (aws CLI + cat, n=30); p50 8 ms with a persistent boto3 session. "
                    "The gap is the measurement method. Cache also on FSx for ONTAP, same Region, "
                    "VPC peering, ap-northeast-1, ONTAP 9.18.1P3D1",
                ),
                ("*2", "FlexCache overhead", "p50 +5 ms against a direct origin read"),
                (
                    "*3",
                    "SMB and NFS are equivalent",
                    "p50 7 ms each over persistent mounts (n=30)",
                ),
                (
                    "*4",
                    "The cache is FSx for ONTAP or on-premises ONTAP 9",
                    "Those are the two FlexCache configurations AWS documents. Cloud Volumes ONTAP, "
                    "ONTAP Select, Azure NetApp Files and Google Cloud NetApp Volumes are "
                    "unverified, which is not the same as unsupported",
                ),
                (
                    "*5",
                    "This diagram's main path, an on-premises cache, is unverified",
                    "Every figure above was measured with FSx for ONTAP on the cache side too. A "
                    "cache on on-premises ONTAP is in AWS's supported configurations but has not "
                    "been followed on hardware, and a remote site's latency is unmeasured",
                ),
                (
                    "*6",
                    "The connectivity layer depends on what the cache side is",
                    "FlexCache requires cluster and SVM peering, and the path underneath it is one "
                    "of the three in the middle of the figure. AWS Interconnect - multicloud is not this "
                    "link: it joins AWS to another CSP, and no other cloud appears in "
                    "this figure (cross-cloud connectivity has a figure of its own). For obtaining "
                    "the on-premises circuit there is also AWS Interconnect - last mile, a separate "
                    "service in the same user guide",
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
    # 以下 2 つは _single_site 専用。同じ文字列を 2 行に折ったもの。共有キーのほうを折らないのは、
    # 共有キーを使う図が公開済みブログ記事から main ブランチの URL で参照されており、折ると
    # 公開記事の図が差し替わるため。幅を詰めていない図で見た目を変える利益はない。
    # _overview と _protocol_matrix 専用の折返し。共有キーを折ると、幅を詰めていない図の
    # 見た目まで変わる。
    "s3_ap_stacked": {
        "ja": "Amazon S3\nAccess Point",
        "en": "Amazon S3\nAccess Point",
    },
    "origin_vol_two_line": {
        "ja": "Amazon FSx for\nNetApp ONTAP (Origin)",
        "en": "Amazon FSx for\nNetApp ONTAP (Origin)",
    },
    "file_client_stacked": {
        "ja": "NFS / SMB Client\n(HiL, EDA, VFX)",
        "en": "NFS / SMB Client\n(HiL, EDA, VFX)",
    },
    "cache_vol_fsx_stacked": {
        "ja": "Amazon FSx for\nNetApp ONTAP",
        "en": "Amazon FSx for\nNetApp ONTAP",
    },
    "s3_client_stacked": {
        "ja": "S3 Client\n(App / Pipeline)",
        "en": "S3 Client\n(App / Pipeline)",
    },
    "s3_bucket_stacked": {
        "ja": "Amazon S3 Bucket\n(source of truth)",
        "en": "Amazon S3 Bucket\n(source of truth)",
    },
    "s3_files": {"ja": "Amazon S3 Files", "en": "Amazon S3 Files"},
    "fsx_ontap_volume": {
        "ja": "Amazon FSx for NetApp ONTAP\n(source of truth)",
        "en": "Amazon FSx for NetApp ONTAP\n(source of truth)",
    },
    "file_client_any": {
        "ja": "NFS v3 / v4.x,\nSMB Client",
        "en": "NFS v3 / v4.x,\nSMB Client",
    },
    # The compute list that belongs here — Amazon EC2, AWS Lambda, Amazon EKS, Amazon ECS — cannot
    # be abbreviated in a diagram label and does not fit in two lines unabbreviated, so it lives in
    # the table beside the figure instead.
    "file_client_nfs41": {
        "ja": "NFS v4.1 / v4.2\nClient",
        "en": "NFS v4.1 / v4.2\nClient",
    },
    # The edge carries the protocol only; the client node label carries the rest.
    "nfs41_protocol": {
        "ja": "NFS v4.1 / v4.2",
        "en": "NFS v4.1 / v4.2",
    },
    # Both directions are drawn because only one of them is fast. A single "auto-sync" arrow reads as
    # if the whole thing settles in seconds, which is true of the import and not of the export.
    "sync_import": {
        "ja": "取り込み",
        "en": "import",
    },
    "sync_export": {
        "ja": "書き戻し",
        "en": "write-back",
    },
    "nfs_smb_rw": {
        "ja": "NFS / SMB（読み書き）",
        "en": "NFS / SMB (read / write)",
    },
    # --- throughput bottlenecks (Part 2) ---------------------------------------------------------
    # --- protocol test matrix -------------------------------------------------------------------
    "panel_read_paths": {
        "ja": "A. 同じデータを 2 つの経路で読む（S3 API で 1 回だけ書く）",
        "en": "A. Reading the same data over two paths (written once over the S3 API)",
    },
    "panel_efs": {"ja": "D. Amazon EFS", "en": "D. Amazon EFS"},
    "panel_ontap_protocols": {
        "ja": "E. Amazon FSx for NetApp ONTAP",
        "en": "E. Amazon FSx for NetApp ONTAP",
    },
    "efs_node": {"ja": "Amazon EFS", "en": "Amazon EFS"},
    "linux_client": {"ja": "Linux Client", "en": "Linux Client"},
    "windows_client": {"ja": "Windows Client", "en": "Windows Client"},
    # Folded at the arrow. Unfolded, the English line is about 595px and it was one of the three
    # captions that fixed this figure's width at 1180.
    "write_then_a1": {
        "ja": "① S3 API で 1 回だけ書く\u3000→<br>② A-1: 同じ経路で読む",
        "en": "1. Write once over the S3 API  -><br>2. A-1: read back over the same path",
    },
    "read_a2": {
        "ja": "③ A-2: 同じデータを NFS / SMB で読む",
        "en": "3. A-2: read the same data over NFS / SMB",
    },
    "efs_protocols": {
        "ja": "対応: NFSv4.0 / NFSv4.1<br><b>非対応: SMB・NFSv3・NFSv4.2・nconnect</b>"
        "<br>Windows を実行する EC2 からの<br>マウントも<b>非対応</b>",
        "en": "Supported: NFSv4.0 / NFSv4.1<br><b>Not supported: SMB, NFSv3, NFSv4.2, nconnect</b>"
        "<br>Mounting from an EC2 instance running Windows<br>is <b>not supported</b> either",
    },
    "ontap_protocols": {
        "ja": "対応: SMB (2.0 / 3.0 / 3.1.1)<br>NFSv3 / v4.0 / v4.1 / v4.2"
        "<br>nconnect は最大 16 接続",
        "en": "Supported: SMB (2.0 / 3.0 / 3.1.1)<br>NFSv3 / v4.0 / v4.1 / v4.2"
        "<br>nconnect up to 16 connections",
    },
    "comparable_only": {
        "ja": "D と E を同じ列に並べられるのは<br>NFSv4.0 と NFSv4.1 だけ",
        "en": "Only NFSv4.0 and NFSv4.1 can be put<br>in the same column for D and E",
    },
    "matrix_note": {
        "ja": note_body(
            "補足 — 可否はドキュメント記載、性能値は未測定",
            (
                (
                    "※1",
                    "A-1 と A-2 は同じデータに対して行う",
                    "書き込みは S3 API で 1 回だけ実施し、そのあと読み取りの経路を変える。"
                    "書き直すと、比較対象にデータ配置の差が混ざる",
                ),
                (
                    "※2",
                    "既存の測定では A-1 と A-2 の比較が成立していない",
                    "S3 API 読み取りの既存値は圧縮可能なテストデータで測っており、"
                    "オブジェクトの大きさと並列の作り方も NFS 側と揃っていない",
                ),
                (
                    "※3",
                    "D で SMB・NFSv3・NFSv4.2 が空欄なのは、遅いのではなく非対応",
                    "Amazon EFS は NFSv4.0 と NFSv4.1 のみ対応し、Windows を実行する "
                    "EC2 インスタンスからのマウントにも対応しない。nconnect も非対応",
                ),
                (
                    "※4",
                    "ファイルプロトコルは auto_vdbench、S3 API は別のスクリプトで測る",
                    "auto_vdbench は VDBENCH をマウントパスに対して駆動するツールで、"
                    "S3 API のワークロードは生成しない。2 つの値を並べるときは測定器が違うと添える",
                ),
                (
                    "※5",
                    "この図に性能値は入っていない",
                    "測定手順・必要な環境・未測定の一覧は docs/ja/verification/"
                    "throughput-protocol-matrix-plan.md にある",
                ),
            ),
        ),
        "en": note_body(
            "Notes — support status is documented; the performance figures are unmeasured",
            (
                (
                    "*1",
                    "A-1 and A-2 run against the same data",
                    "The write happens once over the S3 API, and only the read path changes after "
                    "that. Rewriting would mix a difference in data placement into the comparison",
                ),
                (
                    "*2",
                    "The existing measurements do not make an A-1 to A-2 comparison",
                    "The existing S3 API read figure was taken with compressible test data, and "
                    "neither the object size nor the shape of the concurrency matches the NFS side",
                ),
                (
                    "*3",
                    "SMB, NFSv3 and NFSv4.2 are blank under D because they are unsupported, not slow",
                    "Amazon EFS supports NFSv4.0 and NFSv4.1 only, and does not support mounting "
                    "from an EC2 instance running Windows. It does not support nconnect either",
                ),
                (
                    "*4",
                    "File protocols are measured with auto_vdbench, the S3 API with a separate script",
                    "auto_vdbench drives VDBENCH against a mounted path and does not generate S3 API "
                    "workloads. Where both appear together, say that the instruments differ",
                ),
                (
                    "*5",
                    "There are no performance figures in this diagram",
                    "The procedure, the environment it needs and the list of what is unmeasured are "
                    "in docs/ja/verification/throughput-protocol-matrix-plan.md",
                ),
            ),
        ),
    },
    "panel_this_arch": {
        "ja": "A. 本構成（FSx for ONTAP S3 Access Point → FlexCache → NFS / SMB）",
        "en": "A. This architecture (FSx for ONTAP S3 Access Point -> FlexCache -> NFS / SMB)",
    },
    "panel_amazon_s3": {
        "ja": "B. Amazon S3（S3 API のみ）",
        "en": "B. Amazon S3 (S3 API only)",
    },
    "panel_s3_files_path": {
        "ja": "C. Amazon S3 Files（バケットを NFS でマウント）",
        "en": "C. Amazon S3 Files (mount a bucket over NFS)",
    },
    "client_host": {"ja": "クライアントホスト", "en": "Client host"},
    "s3_client_n": {"ja": "S3 Client × N", "en": "S3 Client × N"},
    "origin_vol_short": {
        "ja": "Amazon FSx for NetApp ONTAP (Origin)",
        "en": "Amazon FSx for NetApp ONTAP (Origin)",
    },
    # _bottlenecks 専用。origin_vol_short を折ったもの。共有キーのほうを折らないのは、
    # protocol-matrix 図が同じキーを使っており、幅を詰めていない図の見た目を変える利益がないため。
    "origin_vol_stacked": {
        "ja": "Amazon FSx for NetApp ONTAP\n(Origin)",
        "en": "Amazon FSx for NetApp ONTAP\n(Origin)",
    },
    "cache_vol_short": {
        "ja": "Amazon FSx for NetApp ONTAP\n(Cache)",
        "en": "Amazon FSx for NetApp ONTAP\n(Cache)",
    },
    "efs_proxy_box": {"ja": "efs-proxy", "en": "efs-proxy"},
    "nfs_client_short": {"ja": "NFS / SMB Client", "en": "NFS / SMB Client"},
    "nfs_client_rw": {
        "ja": "NFS Client\n(App / Pipeline)",
        "en": "NFS Client\n(App / Pipeline)",
    },
    "s3_client_rw": {
        "ja": "S3 Client (App / Pipeline)",
        "en": "S3 Client (App / Pipeline)",
    },
    "amazon_s3_node": {"ja": "Amazon S3", "en": "Amazon S3"},
    "bn_this_arch": {
        "ja": "ボトルネック: 指定したスループットキャパシティ（全クライアントで共有）",
        "en": "Bottleneck: the throughput capacity you specify (shared by every client)",
    },
    "bn_amazon_s3": {
        "ja": "ボトルネック: クライアント側のネットワーク帯域（台数を増やすと合計が伸びる）",
        "en": "Bottleneck: client-side network bandwidth (the total grows as hosts are added)",
    },
    "bn_s3_files": {
        "ja": "ボトルネック: efs-proxy の CPU（クライアント上）",
        "en": "Bottleneck: efs-proxy CPU, on the client",
    },
    # One line on purpose. Folded to two, the second line landed under the enclosing frame's own
    # title and the two read as one block. `rw` is dropped rather than wrapped: the mount options
    # are in the verification note, and this figure is about where the path plateaus.
    "loopback_mount": {
        "ja": "NFS mount (127.0.0.1)",
        "en": "NFS mount (127.0.0.1)",
    },
    "s3_api": {"ja": "S3 API", "en": "S3 API"},
    "flexcache_edge": {"ja": "FlexCache", "en": "FlexCache"},
    "nfs_smb_read": {"ja": "NFS / SMB（読み取り）", "en": "NFS / SMB (read)"},
    "s3_api_rw": {"ja": "S3 API（読み書き）", "en": "S3 API (read / write)"},
    # --- cross-cloud connectivity diagram --------------------------------------------------------
    # This figure stops at the network. The FlexCache direction it does not draw as available is the
    # whole reason the figure exists: a reader who sees three clouds converging on FSx for ONTAP will
    # assume the storage integration follows, and it does not.
    "gcp_cloud": {"ja": "Google Cloud", "en": "Google Cloud"},
    "azure_cloud": {"ja": "Microsoft Azure", "en": "Microsoft Azure"},
    "oci_cloud": {
        "ja": "Oracle Cloud Infrastructure",
        "en": "Oracle Cloud Infrastructure",
    },
    "gcnv": {
        "ja": "Google Cloud NetApp Volumes",
        "en": "Google Cloud NetApp Volumes",
    },
    "anf": {"ja": "Azure NetApp Files", "en": "Azure NetApp Files"},
    # Oracle publishes no icon set this repository can draw from, so the service is named in a box.
    # A stand-in from another vendor's set would be worse than a label: it would attribute Oracle's
    # service to whoever's mark was borrowed.
    "oci_file_storage": {"ja": "OCI File Storage", "en": "OCI File Storage"},
    "gcp_vpc": {"ja": "Google Cloud VPC", "en": "Google Cloud VPC"},
    "azure_vnet": {"ja": "Azure VNet", "en": "Azure VNet"},
    "oci_vcn": {"ja": "OCI VCN", "en": "OCI VCN"},
    "managed_way": {
        "ja": "1 管理サービス — 対応リージョンのペアで決まる",
        "en": "1 Managed service - decided by the Region pairs",
    },
    # Azure reaches the managed frame too, but at Preview. The lifecycle rides on the edge label
    # rather than on the frame, because the frame holds three CSPs at two different lifecycles and a
    # frame-level label would flatten them into one.
    "private_path_preview": {
        "ja": "private 接続（Preview）",
        "en": "private connectivity (Preview)",
    },
    "partner_way": {
        "ja": "2 パートナー経由 — ロケーションの重なりで決まる",
        "en": "2 Partner route - decided by overlapping locations",
    },
    "aws_interconnect_mc": {
        "ja": "AWS Interconnect – multicloud",
        "en": "AWS Interconnect – multicloud",
    },
    "direct_connect": {"ja": "AWS Direct Connect", "en": "AWS Direct Connect"},
    "provider_fabric": {
        "ja": "相互接続プロバイダの<br>ファブリック",
        "en": "Interconnection provider's<br>fabric",
    },
    "aws_cloud_consuming": {
        "ja": "AWS Cloud",
        "en": "AWS Cloud",
    },
    "aws_vpc": {"ja": "Amazon VPC", "en": "Amazon VPC"},
    "fsx_here": {
        "ja": "Amazon FSx for NetApp ONTAP",
        "en": "Amazon FSx for NetApp ONTAP",
    },
    "s3ap_here": {"ja": "Amazon S3 Access Point", "en": "Amazon S3 Access Point"},
    "private_path": {"ja": "private 接続", "en": "private connectivity"},
    # Drawn as a barrier on the boundary rather than as a dashed arrow. A dashed arrow from each of
    # the three origins would cross the connectivity frames, and one arrow standing for all three
    # would attach a single verdict to platforms that have two different ones. A barrier says where
    # the evidence stops without implying a route that has been tried.
    # Wrapped explicitly. A TextBox does not wrap on export, so the longest line here is the
    # figure's width, and in English this one line is about 1530px -- which is what held the
    # canvas at 1400 and every label at 7.2px in a reader's column.
    "unconfirmed_boundary": {
        "ja": (
            "この図が示すのはネットワーク層だけ。<br>"
            "他クラウドのファイルストレージを Origin とし、FSx for ONTAP を Cache にする構成<br>"
            "（FlexCache）は未確認、または機構として対象外"
        ),
        "en": (
            "This figure covers the network layer only.<br>"
            "Another cloud's file storage as the origin with FSx for ONTAP as the cache<br>"
            "(FlexCache) is unconfirmed, or out of scope as a mechanism"
        ),
    },
    "cross_cloud_note": {
        "ja": note_body(
            "補足",
            (
                (
                    "※1",
                    "この図が示すのはネットワーク層だけである",
                    "他クラウドのファイルストレージを Origin として FSx for ONTAP を Cache にする"
                    "構成は、AWS の FlexCache 対応構成表に含まれていない。図の最上部の帯が"
                    "その境界を示す。矢印は AWS の VPC までで止めてある",
                ),
                (
                    "※2",
                    "帯が指す判定は 2 種類あり、同じ語で書かない",
                    "Google Cloud NetApp Volumes と Azure NetApp Files は未確認。"
                    "OCI File Storage は ONTAP ではないため機構として対象外で、"
                    "FlexCache が要求するクラスタ / SVM ピアリングが成立しない",
                ),
                (
                    "※3",
                    "分類 1 と分類 2 は可否の決まり方が違う",
                    "分類 1 はサービス提供側が公開している対応リージョンのペア、"
                    "分類 2 は Direct Connect ロケーション・相手クラウドの接続ロケーション・"
                    "プロバイダ拠点の重なりで決まる。分類 2 を選んでも分類 1 の対応ペアは増えない。"
                    "図の矢印は各クラウドで現在取れる分類を示すもので、"
                    "Google Cloud と OCI も分類 2 で作ることはできる",
                ),
                (
                    "※4",
                    "対応状況（2026-09-02 時点）",
                    "AWS Interconnect – multicloud は Google Cloud（8 ペア）と "
                    "OCI（us-east-1 ↔ us-ashburn-1 の 1 ペア）で GA、"
                    "Azure は 2026-08 から Preview で 4 ペア。"
                    "東京・大阪はどの CSP のペアにも含まれない。"
                    "Preview のペアと機能は変更されうるので GA と同じ根拠にしない",
                ),
                (
                    "※5",
                    "暗号化は層が違う",
                    "物理リンクの MACsec と、FlexCache のトラフィックを覆う "
                    "cluster peering encryption（ONTAP 9.6 以降、TLS 1.2 AES-256 GCM）は別物で、"
                    "前者があっても後者は要る",
                ),
                (
                    "※6",
                    "アイコンの出所",
                    "Azure NetApp Files は Microsoft の Azure architecture icons。"
                    "Google Cloud NetApp Volumes は固有アイコンがないため Google の規則どおり"
                    "Storage カテゴリアイコンと製品名で示す。OCI はアイコンを用意できず名前のみ",
                ),
            ),
        ),
        "en": note_body(
            "Notes",
            (
                (
                    "*1",
                    "This figure covers the network layer only",
                    "Another cloud's file storage as the origin with FSx for ONTAP as the cache is "
                    "not in AWS's supported FlexCache configuration table. The banner along the top "
                    "marks that boundary, and the arrows stop at the AWS VPC",
                ),
                (
                    "*2",
                    "The banner covers two different verdicts, not one",
                    "Google Cloud NetApp Volumes and Azure NetApp Files are unconfirmed. OCI File "
                    "Storage is out of scope as a mechanism because it is not ONTAP, so the cluster "
                    "and SVM peering FlexCache requires cannot exist",
                ),
                (
                    "*3",
                    "Ways 1 and 2 are decided by different things",
                    "Way 1 by the Region pairs the provider publishes; way 2 by whether Direct "
                    "Connect locations, the other cloud's connection locations and the provider's "
                    "footprint overlap. Taking way 2 does not add Regions to way 1. The arrows show "
                    "which way each cloud can use today; Google Cloud and OCI can also be built "
                    "with way 2",
                ),
                (
                    "*4",
                    "Status as at 2026-09-02",
                    "AWS Interconnect - multicloud is GA for Google Cloud (eight pairs) and OCI "
                    "(one pair, us-east-1 to us-ashburn-1), and at Preview for Azure since 2026-08 "
                    "with four pairs. No Japanese Region appears in any CSP's pairs. A Preview's "
                    "pairs and features can change, so it is not GA-strength evidence",
                ),
                (
                    "*5",
                    "Encryption sits at two layers",
                    "MACsec on the physical link and cluster peering encryption over FlexCache "
                    "traffic (ONTAP 9.6 or later, TLS 1.2 AES-256 GCM) are different things; the "
                    "first does not remove the need for the second",
                ),
                (
                    "*6",
                    "Where the icons come from",
                    "Azure NetApp Files from Microsoft's Azure architecture icons. Google Cloud "
                    "NetApp Volumes has no unique icon, so Google's own rule applies: the Storage "
                    "category icon with the product name. OCI is named in a box, with no icon",
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
    # Fixed connection points, as (x, y) fractions of the shape. Needed when two edges join the same
    # pair in opposite directions: left to itself, draw.io routes both along the same centre line and
    # the second one disappears under the first, taking its label with it.
    exit_at: tuple[float, float] | None = None
    entry_at: tuple[float, float] | None = None
    # An arrowhead at both ends, for a leg where the same client moves data in both directions over
    # the same protocol. Reaching for a second icon instead would say the read arrives from
    # somewhere else, which is true of this architecture's NFS / SMB side and of nothing else here.
    both_ways: bool = False
    # Explicit waypoints, for a leg that has to leave the row it starts on. Left to itself an
    # orthogonal edge takes the shortest path, and between two rows the shortest path runs through
    # the label under an icon -- the one place nothing else may go. Given here rather than nudged
    # afterwards, because then the clearances can be stated in a comment and checked against it.
    points: tuple[tuple[int, int], ...] = ()

    def style(self, size: int = BODY_FONT_SIZE) -> str:
        style = resized(EDGE_STYLE, size)
        if self.both_ways:
            style += "startArrow=open;startFill=0;"
        if self.exit_at:
            style += (
                f"exitX={self.exit_at[0]};exitY={self.exit_at[1]};exitDx=0;exitDy=0;"
            )
        if self.entry_at:
            style += f"entryX={self.entry_at[0]};entryY={self.entry_at[1]};entryDx=0;entryDy=0;"
        return style


@dataclass(frozen=True)
class Frame:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int
    # A frame normally draws a boundary around something, and an empty one is a boundary around
    # nothing -- the tests reject it. This says the box *is* the element: an internal layer that no
    # vendor publishes an icon for, where borrowing a mark would attribute the layer to whatever the
    # mark stands for. Set it deliberately; it switches off a real guard.
    label_only: bool = False


@dataclass(frozen=True)
class TextBox:
    cid: str
    label: str
    x: int
    y: int
    width: int
    height: int


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
    frames: tuple[Frame, ...] = ()
    nodes: tuple[Node, ...] = ()
    texts: tuple[TextBox, ...] = ()
    edges: tuple[Edge, ...] = ()
    notes: tuple[Note, ...] = ()
    # One number per diagram. The readability floor is on the size a reader receives after the
    # image is scaled into an 880px column, so a wider canvas needs a larger source size --
    # see docs/agent/diagrams.md. Defaults to the size the pre-gate diagrams were authored at.
    font_size: int = BODY_FONT_SIZE

    def filename(self, lang: str) -> str:
        # Japanese keeps the bare name: the published blog posts link the exported PNG by these
        # exact paths, so renaming either file breaks a live image.
        suffix = "" if lang == "ja" else f"-{lang}"
        return f"{self.name}{suffix}.drawio"


def centred(icon: str, cx: int, cy: int) -> tuple[int, int]:
    half = ICON_SIZE[icon] // 2
    return cx - half, cy - half


def _overview() -> Diagram:
    """The architecture as published: collect over S3, fan out with FlexCache.

    The cache side is drawn as two products inside one frame rather than as a single icon. AWS
    documents the cache as either FSx for ONTAP or on-premises ONTAP, and a lone FSx for ONTAP icon
    reads as a requirement -- which would send a reader with an existing on-premises cluster looking
    for a second file system they do not need. The FlexCache edge lands on the frame so it arrives at
    the choice rather than at whichever option is drawn first.

    **Two bands, not one row.** The chain is six elements wide and two of them are frames rather
    than icons, which at this label size needs about 1550px in a row -- and a 1550px canvas is
    scaled to 0.57 in a reader's column, so the labels arrive at 6.5px. The origin region keeps the
    top band and everything past the link moves to the second, which spends height that nothing here
    competes for. The riser leaves to the right of every label on the top band before it turns,
    because the space below an icon belongs to that icon's label.

    The notes box is gone. Its six items were checked off one at a time: the reflection latency and
    the FlexCache increment are in the article body and in
    `docs/ja/verification/cross-protocol-directions.md`; the supported cache platforms and the
    unverified on-premises path are in `docs/ja/verification-status.md`, which is the single source
    for how far each claim has been taken; and the connectivity cases are the three lines the frame
    in this figure already carries. Kept in the image, the longest of those lines was what fixed the
    canvas at 1450px wide.
    """
    return Diagram(
        name="s3burst-architecture-overview",
        diagram_id="s3burst-overview",
        width=900,
        height=840,
        font_size=16,
        groups=(
            Group("aws_cloud", "aws_cloud", 40, 60, 560, 250),
            Group(
                "edge_group",
                "cache_site",
                350,
                350,
                530,
                440,
                gr_icon="group_corporate_data_center",
                stroke="#147EBA",
            ),
        ),
        frames=(
            Frame("cache_platform", "cache_platform", 380, 390, 250, 360),
            # The link is its own band now, so the frame no longer has to squeeze into a gap between
            # two group boundaries. It keeps naming all three cases: a single icon on this link
            # would read as a requirement.
            Frame("link_layer", "connect_layer", 40, 350, 270, 190),
        ),
        nodes=(
            Node("s3client", "users", "s3_client_stacked", 90, 150),
            Node("s3ap", "s3_access_point", "s3_ap_stacked", 250, 150),
            Node("origin_vol", "fsx_ontap", "origin_vol_two_line", 450, 134),
            Node(
                "cache_fsx",
                "fsx_ontap",
                "cache_vol_fsx_stacked",
                *centred("fsx_ontap", 505, 470),
            ),
            Node(
                "cache_ontap",
                "ontap_9",
                "cache_volume_ontap",
                *centred("ontap_9", 505, 655),
            ),
            Node(
                "nfs_client",
                "client",
                "file_client_stacked",
                *centred("client", 760, 570),
            ),
        ),
        texts=(
            TextBox("cache_or", "either_of", 470, 575, 70, 20),
            TextBox("link_1", "link_same_region", 55, 390, 240, 20),
            TextBox("link_2", "link_cross_region", 55, 425, 240, 40),
            TextBox("link_3", "link_onprem", 55, 480, 240, 40),
        ),
        edges=(
            Edge("e1", "s3client", "s3ap", "put_object"),
            Edge("e2", "s3ap", "origin_vol"),
            # Out to a riser at x=640, clear of every label on the top band, then along y=332 --
            # below the origin group, which ends at 310, and above the link frame, which starts at
            # 350, so the label centred on it straddles neither border. Split in two so the
            # connectivity frame sits on the path instead of alongside it. The FlexCache label stays
            # on the first leg, because FlexCache is what crosses the link -- the frame says what the
            # link is made of, not what runs over it.
            Edge(
                "e3",
                "origin_vol",
                "link_layer",
                "flexcache_pull",
                (1, 0.5),
                (0.5, 0),
                points=((640, 174), (640, 332), (175, 332)),
            ),
            Edge(
                "e3b",
                "link_layer",
                "cache_platform",
                "",
                (1, 0.5),
                (0, 0.2),
                points=((345, 445), (345, 462)),
            ),
            Edge("e4", "cache_platform", "nfs_client", "nfs_smb"),
        ),
    )


def _single_site() -> Diagram:
    """The two ways to read S3-collected data as files inside one site.

    Deliberately not drawn as a variant of this architecture. The decision tree already answers the
    same-site case with "the S3 Access Point alone is enough; no fan-out" — it is an exit from the
    architecture, not a configuration of it, and the panels are laid out so a reader compares the
    two single-site options rather than reading either as a reduced form of the main diagram.

    **The two panels stay in one figure for that reason.** Splitting them would remove the
    comparison the figure exists to make, so the readability floor is met by narrowing instead: the
    canvas came down from 1180 to 960 and the four long labels are folded to two lines, which is
    what freed the width the larger font needs. A label on one line at this size is roughly twice
    as wide as the same label on two.

    The notes box is gone. Its seventeen items are in the table beside the figure in `README.md`
    and `docs/en/README.md`, where they can be searched, selected and translated; inside the image
    they were the first thing to become illegible and had to be kept in step with the prose by hand.
    """
    row_a, row_b = 175, 445
    return Diagram(
        name="s3burst-single-site-options",
        diagram_id="s3burst-single-site",
        # 960, not 1180. Every 100px of canvas is a further reduction applied to every label once
        # the image is fitted to a reader's column, so the width is set by the widest row and
        # nothing else.
        width=960,
        height=600,
        font_size=16,
        groups=(
            Group("panel_a", "panel_s3ap", 40, 60, 880, 230),
            Group("panel_b", "panel_s3files", 40, 330, 880, 230),
        ),
        nodes=(
            Node(
                "a_client", "users", "s3_client_stacked", *centred("users", 165, row_a)
            ),
            Node(
                "a_ap",
                "s3_access_point",
                "s3_access_point",
                *centred("s3_access_point", 345, row_a),
            ),
            Node(
                "a_vol",
                "fsx_ontap",
                "fsx_ontap_volume",
                *centred("fsx_ontap", 560, row_a),
            ),
            # Furthest right so the gap before it holds the read-path label, which is the widest
            # edge label in the figure and is wider still in English.
            Node("a_file", "client", "file_client_any", *centred("client", 845, row_a)),
            Node(
                "b_client", "users", "s3_client_stacked", *centred("users", 165, row_b)
            ),
            Node(
                "b_bucket",
                "s3_bucket",
                "s3_bucket_stacked",
                *centred("s3_bucket", 345, row_b),
            ),
            Node("b_files", "s3", "s3_files", *centred("s3", 560, row_b)),
            Node(
                "b_file", "client", "file_client_nfs41", *centred("client", 845, row_b)
            ),
        ),
        edges=(
            Edge("a1", "a_client", "a_ap", "put_object"),
            Edge("a2", "a_ap", "a_vol"),
            Edge("a3", "a_vol", "a_file", "nfs_smb_rw"),
            Edge("b1", "b_client", "b_bucket", "put_object"),
            Edge("b2", "b_bucket", "b_files", "sync_import", (1, 0.25), (0, 0.25)),
            Edge("b4", "b_files", "b_bucket", "sync_export", (0, 0.75), (1, 0.75)),
            Edge("b3", "b_files", "b_file", "nfs41_protocol"),
        ),
    )


def _cross_cloud() -> Diagram:
    """Private connectivity from three other clouds to AWS, stopping where the evidence stops.

    **Three bands, not four columns.** The figure used to read left to right -- source cloud, its
    network, the way in, the AWS boundary -- which needs about 1400px, and a 1400px canvas is scaled
    to 0.63 in a reader's column, so every label arrived at 7.2px. Height is the cheap axis, so the
    three source clouds share the top band, the two ways in share the second, and AWS is the third.
    The network name moved inside each cloud's own frame: it was a column of its own with one short
    label per row, which is 200px of width to say something containment already says.

    The two ways of building the connection are still separate frames rather than alternatives on
    one line, because what decides whether each is available is a different thing -- Region pairs for
    the managed service, overlapping locations for the partner route -- and putting them on one line
    invites reading the second as an extension of the first's coverage.

    Azure keeps two edges. A managed service at Preview since 2026-08, and the partner route it had
    before that. Dropping the partner route would say a Preview is a substitute for a GA path, and
    dropping the Preview edge would keep saying Azure is outside way 1, which it no longer is. The
    lifecycle rides on the edge rather than on the frame, because the frame holds three CSPs at two
    different lifecycles and a frame-level label would flatten them into one.

    The notes box is gone. What it carried -- which pairs are GA, which are Preview, and what is not
    a FlexCache path -- is in `docs/ja/reference/comparison/` and in the article body, and the
    boundary claim is the banner this figure still opens with. In the image, the longest of its lines
    fixed the canvas at 1300px wide.
    """
    return Diagram(
        name="s3burst-cross-cloud-connectivity",
        diagram_id="s3burst-cross-cloud",
        width=970,
        height=1120,
        font_size=16,
        groups=(Group("aws_cloud_r", "aws_cloud_consuming", 40, 820, 890, 260),),
        frames=(
            # Left to right by connectivity status, not alphabetically: the two clouds with a
            # managed service at GA sit together, so their edges reach the upper frame without
            # crossing Azure's edge to the lower one.
            Frame("gcp", "gcp_cloud", 40, 120, 270, 240),
            Frame("oci", "oci_cloud", 350, 120, 270, 240),
            Frame("azure", "azure_cloud", 660, 120, 270, 240),
            Frame("managed", "managed_way", 40, 500, 430, 250),
            Frame("partner", "partner_way", 510, 500, 430, 250),
            Frame("aws_vpc_f", "aws_vpc", 70, 870, 830, 170),
        ),
        nodes=(
            Node(
                "gcnv_n",
                "gcnv_storage_category",
                "gcnv",
                *centred("gcnv_storage_category", 175, 205),
            ),
            Node(
                "anf_n",
                "azure_netapp_files",
                "anf",
                *centred("azure_netapp_files", 795, 205),
            ),
            Node(
                "ic_n",
                "aws_interconnect",
                "aws_interconnect_mc",
                *centred("aws_interconnect", 255, 610),
            ),
            Node(
                "dx_n",
                "direct_connect",
                "direct_connect",
                *centred("direct_connect", 725, 585),
            ),
            Node(
                "fsx_n",
                "fsx_ontap",
                "fsx_here",
                *centred("fsx_ontap", 260, 930),
            ),
            Node(
                "s3ap_n",
                "s3_access_point",
                "s3ap_here",
                *centred("s3_access_point", 620, 930),
            ),
        ),
        texts=(
            # Oracle publishes no icon set this repository can draw from, so the service is named in
            # a box. A stand-in from another vendor's set would attribute Oracle's service to
            # whoever's mark was borrowed.
            TextBox("oci_fs", "oci_file_storage", 380, 190, 210, 30),
            # Each cloud's network, inside that cloud's frame. As a column of its own it cost 200px
            # of width to state what the frame already scopes.
            TextBox("gcp_net", "gcp_vpc", 55, 295, 240, 20),
            TextBox("oci_net", "oci_vcn", 365, 295, 240, 20),
            TextBox("azure_net", "azure_vnet", 675, 295, 240, 20),
            TextBox("fabric", "provider_fabric", 555, 670, 340, 50),
            # A banner across the top rather than a label wedged between the connectivity column and
            # the AWS boundary. Placed there it overlapped the two edges entering the VPC: a TextBox
            # does not clip, so its text overflowed its box and crossed the arrowheads. It is also
            # the first thing read, which is where a limit belongs.
            TextBox("boundary", "unconfirmed_boundary", 40, 8, 890, 90),
        ),
        edges=(
            # Which way each cloud can use today. Google Cloud and OCI have a managed service at GA.
            Edge("x4", "gcp", "managed", "private_path", (0.5, 1), (0.31, 0)),
            Edge(
                "x5",
                "oci",
                "managed",
                "private_path",
                (0.5, 1),
                (0.674, 0),
                points=((485, 410), (330, 410)),
            ),
            Edge("x6", "azure", "partner", "private_path", (0.5, 1), (0.66, 0)),
            # Down its own lane at y=440 and in from above. Routed left to itself it would run
            # straight up the middle of the old column: through the partner frame, over the Direct
            # Connect icon, and with its label on top of the fabric caption. The picture then said
            # Azure's managed path runs through the partner route, which is the one thing this
            # figure is careful not to say. It crosses OCI's riser once, at (330, 470).
            Edge(
                "x6b",
                "azure",
                "managed",
                "private_path_preview",
                (0.2, 1),
                (0.44, 0),
                points=((714, 470), (230, 470)),
            ),
            Edge("x7", "managed", "aws_vpc_f", None, (0.5, 1), (0.22, 0)),
            Edge("x8", "partner", "aws_vpc_f", None, (0.5, 1), (0.79, 0)),
            Edge("x9", "s3ap_n", "fsx_n"),
        ),
    )


def _bottlenecks() -> Diagram:
    """Where each of the three measured paths plateaus.

    Three panels, one per path, because the point of the figure is that the same "MB/s" comes from a
    different place in each. The bottleneck is called out under the element that carries it rather
    than in a legend, so a reader cannot take the number without the location.

    Panel C wraps the client and the proxy in one frame. That the NFS client connects to a process on
    its own host is the structural fact the panel exists to show — drawn as two separate columns it
    reads as a network hop, which is what makes `nconnect` look like the answer.

    efs-proxy gets a plain box, not an icon. There is no AWS asset for it, and borrowing another
    mark would attribute it to whoever's mark was borrowed.

    **Panel A is two rows.** Five columns of these labels need about 1290px at this size, and a
    canvas that wide brings every label back under the floor. Splitting the origin and the cache
    across rows spends height instead, which nothing here competes for, and it puts the FlexCache
    pull on its own segment rather than in a row of four arrows. The riser runs out to the right of
    every label before it turns, because the space below an icon belongs to that icon's label.

    The notes box is gone. Its numbers were checked off one at a time against
    `docs/ja/verification/throughput-iops-concurrency.md`, which is where the conditions and the
    later corrections live; all of them were already there except that the measurements are NFS
    only, which is now a bullet in that record's "読み取れないこと". Keeping a second copy inside the
    image meant keeping two copies in step by hand, and the copy in the image had already drifted:
    it stated an ONTAP version that the record says `DescribeFileSystems` returned as null for this
    purpose-built file system.

    That record has no English translation, so an English reader of this figure gets the panels and
    the bottleneck under each one, and no numbers. That is the intended reading either way -- the
    figure says where each path plateaus, not how fast it is.
    """
    row_a1, row_a2, row_b, row_c = 155, 310, 545, 760
    return Diagram(
        name="s3burst-throughput-bottlenecks",
        diagram_id="s3burst-bottlenecks",
        # 960 rather than 1180: the width is set by the widest row and nothing else, and every
        # extra 100px is a further reduction applied to every label in the figure.
        width=960,
        height=960,
        font_size=16,
        groups=(
            # 各パネルの高さは、最下段のアイコンではなく **その下のラベル 2 行** と、さらに下に
            # 置くボトルネックのキャプションで決まる。アイコン基準で切ると両方に重なる。
            Group("panel_a", "panel_this_arch", 40, 60, 880, 390),
            Group("panel_b", "panel_amazon_s3", 40, 480, 880, 160),
            Group("panel_c", "panel_s3_files_path", 40, 670, 880, 250),
        ),
        frames=(
            # The client and the proxy sit on one host. Drawn as a container so the loopback mount
            # inside it is unmistakable.
            # Height hugs the client's two label lines. Cut wider than the content, the dashed
            # bottom edge runs close enough to the bottleneck caption to read as its underline.
            Frame("c_host", "client_host", 70, 710, 440, 140),
        ),
        nodes=(
            Node(
                "a_client", "users", "s3_client_stacked", *centred("users", 150, row_a1)
            ),
            Node(
                "a_ap",
                "s3_access_point",
                "s3_access_point",
                *centred("s3_access_point", 385, row_a1),
            ),
            Node(
                "a_origin",
                "fsx_ontap",
                "origin_vol_stacked",
                *centred("fsx_ontap", 665, row_a1),
            ),
            Node(
                "a_cache",
                "fsx_ontap",
                "cache_vol_short",
                *centred("fsx_ontap", 200, row_a2),
            ),
            Node(
                "a_file", "client", "nfs_client_short", *centred("client", 520, row_a2)
            ),
            Node("b_client", "users", "s3_client_n", *centred("users", 150, row_b)),
            Node("b_s3", "s3", "amazon_s3_node", *centred("s3", 460, row_b)),
            Node("c_client", "users", "nfs_client_rw", *centred("users", 145, row_c)),
            Node("c_files", "s3", "s3_files", *centred("s3", 610, row_c)),
            Node(
                "c_bucket",
                "s3_bucket",
                "s3_bucket_stacked",
                *centred("s3_bucket", 830, row_c),
            ),
        ),
        texts=(
            TextBox("a_bn", "bn_this_arch", 150, 410, 620, 20),
            TextBox("b_bn", "bn_amazon_s3", 110, 610, 700, 20),
            TextBox("c_bn", "bn_s3_files", 110, 880, 480, 20),
            # A plain box, since no AWS asset exists for this process.
            TextBox("c_proxy", "efs_proxy_box", 395, 740, 110, 40),
        ),
        edges=(
            # A's two client legs are not symmetric, and that asymmetry is the architecture. The
            # S3 API side carries both directions (writes and reads were both measured over it), so
            # it is drawn both ways. The NFS / SMB side is the read fan-out, so it is one way.
            Edge("q1", "a_client", "a_ap", "s3_api_rw", both_ways=True),
            Edge("q2", "a_ap", "a_origin", both_ways=True),
            # One way on purpose: the cache pulls from the origin. Out to a riser clear of every
            # label on the row above, then back along y=252 -- below the origin label, which ends at
            # 239, and above the cache icon, which starts at 262.
            Edge(
                "q3",
                "a_origin",
                "a_cache",
                "flexcache_edge",
                (1, 0.5),
                (0.5, 0),
                points=((840, row_a1), (840, 252), (200, 252)),
            ),
            Edge("q4", "a_cache", "a_file", "nfs_smb_read"),
            # B and C move data both ways over one protocol from one client, so both ends carry an
            # arrowhead rather than a second client icon standing in for the read.
            Edge("q5", "b_client", "b_s3", "s3_api_rw", both_ways=True),
            Edge("q6", "c_client", "c_proxy", "loopback_mount", both_ways=True),
            # Deliberately unlabelled: what efs-proxy speaks to the service was not verified,
            # and it is not NFS. NFS is only between the client and the proxy.
            Edge("q7", "c_proxy", "c_files", both_ways=True),
            Edge("q8", "c_files", "c_bucket", both_ways=True),
        ),
    )


def _protocol_matrix() -> Diagram:
    """The test patterns that are not yet measured: two read paths on one dataset, and D against E.

    Panel A exists because the comparison it names does not exist yet. The write happens once and
    only the read path changes, which is the one arrangement the existing measurements do not have.

    Panels D and E carry their protocol lists as text rather than as separate rows, because what
    matters is which entries are absent on the D side. Absent is not slow: EFS supports NFSv4.0 and
    NFSv4.1 and nothing else here, so the Windows client is drawn only under E and D carries the
    reason it has none.

    No number appears anywhere in this figure. Nothing in it has been measured.

    880px panels rather than 1100. The width was set by three captions and the notes box, none of
    which is a node, and at 1180 the whole figure arrived in a reader's column at 8.5px. The
    captions are folded and the notes box is gone: every item it carried -- that A-1 and A-2 must
    run against the same written data, that the existing S3 figures are not comparable to the NFS
    ones, that D's blanks are unsupported rather than slow, and which tool measures which side -- is
    in `docs/ja/verification/throughput-protocol-matrix-plan.md`, which the note already pointed at
    for the procedure.
    """
    row_a, row_d = 185, 455
    return Diagram(
        name="s3burst-protocol-test-matrix",
        diagram_id="s3burst-protocol-matrix",
        width=940,
        height=990,
        font_size=16,
        groups=(
            Group("panel_a2", "panel_read_paths", 40, 60, 880, 270),
            Group("panel_d", "panel_efs", 40, 350, 880, 220),
            Group("panel_e", "panel_ontap_protocols", 40, 590, 880, 300),
        ),
        nodes=(
            Node("m_s3c", "users", "s3_client_stacked", *centred("users", 140, row_a)),
            Node(
                "m_ap",
                "s3_access_point",
                "s3_ap_stacked",
                *centred("s3_access_point", 380, row_a),
            ),
            Node(
                "m_origin",
                "fsx_ontap",
                "origin_vol_two_line",
                *centred("fsx_ontap", 600, row_a),
            ),
            Node(
                "m_file", "client", "nfs_client_short", *centred("client", 840, row_a)
            ),
            Node("d_linux", "client", "linux_client", *centred("client", 140, row_d)),
            Node("d_efs", "efs", "efs_node", *centred("efs", 400, row_d)),
            Node("e_linux", "client", "linux_client", *centred("client", 140, 660)),
            Node("e_win", "client", "windows_client", *centred("client", 140, 790)),
            Node(
                "e_ontap",
                "fsx_ontap",
                "cache_vol_fsx_stacked",
                *centred("fsx_ontap", 400, 720),
            ),
        ),
        texts=(
            # Inside the panel, not on its border. Two captions rather than three: the write and
            # the A-1 read are the same leg travelled twice, so splitting them across two x
            # positions would say they are different links.
            TextBox("t_write_a1", "write_then_a1", 60, 268, 400, 46),
            TextBox("t_a2", "read_a2", 500, 280, 400, 24),
            TextBox("t_efs_p", "efs_protocols", 510, 395, 390, 120),
            TextBox("t_ontap_p", "ontap_protocols", 540, 650, 360, 90),
            # Below panel E rather than inside it: it is about D and E together, and a caption about
            # two panels sitting inside one of them reads as belonging to that one.
            TextBox("t_comparable", "comparable_only", 60, 905, 560, 46),
        ),
        edges=(
            Edge("m1", "m_s3c", "m_ap", "s3_api_rw", both_ways=True),
            Edge("m2", "m_ap", "m_origin", both_ways=True),
            # A-2 leaves the same volume the S3 API wrote to. One way: this leg is the read.
            Edge("m3", "m_origin", "m_file", "nfs_smb_read"),
            Edge("d1", "d_linux", "d_efs", both_ways=True),
            # Fixed entry points. Left to itself draw.io lands both of these on the same point and
            # routes the second one back around, which reads as a link between the two clients.
            Edge(
                "e1",
                "e_linux",
                "e_ontap",
                both_ways=True,
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.25),
            ),
            Edge(
                "e2",
                "e_win",
                "e_ontap",
                both_ways=True,
                exit_at=(1.0, 0.5),
                entry_at=(0.0, 0.75),
            ),
        ),
    )


def _two_ceilings() -> Diagram:
    """The two ceilings a read can meet, and what decides which one applies.

    Exists because the same file system, the same workload shape and the same connection count
    returned figures 5.5x apart, and the difference was which regions of the data the threads
    touched. Read as one ceiling, that pair looks like an unexplained variance; read as two, it is
    the design decision the measurement plan turns on.

    Vertical, on an 880px canvas, so the source font can be 16 and still clear the readability
    floor at full width -- the pre-gate figures are 1180 to 1550px wide and arrive at roughly 7 to
    9px. No notes box, for the same reason: its longest line would set the canvas width.

    The cache layer and the SSD get boxes, not icons. Neither is a service, and borrowing a mark
    would attribute an internal layer to whatever the mark stands for.
    """
    centre = 440
    return Diagram(
        name="s3burst-two-ceilings",
        diagram_id="s3burst-two-ceilings",
        width=880,
        height=560,
        font_size=16,
        groups=(Group("tc_fs", "tc_file_server", 40, 200, 800, 300),),
        frames=(
            # Sized to the two-line label. A frame taller than its text reads as an empty container
            # waiting to be filled, which is a claim about the architecture rather than about layout.
            Frame("tc_cache", "tc_cache_layer", 80, 270, 320, 64, label_only=True),
            Frame("tc_disk", "tc_ssd", 480, 270, 320, 64, label_only=True),
            Frame(
                "tc_cap_cache", "tc_ceiling_cache", 80, 400, 320, 64, label_only=True
            ),
            Frame("tc_cap_disk", "tc_ceiling_disk", 480, 400, 320, 64, label_only=True),
        ),
        nodes=(
            Node("tc_users", "client", "tc_client", *centred("client", centre, 90)),
        ),
        edges=(
            Edge("tc_e_hit", "tc_users", "tc_cache", "tc_hit"),
            Edge("tc_e_miss", "tc_users", "tc_disk", "tc_miss"),
            Edge("tc_e_cache_cap", "tc_cache", "tc_cap_cache"),
            Edge("tc_e_disk_cap", "tc_disk", "tc_cap_disk"),
        ),
    )


def _host_count() -> Diagram:
    """What the SMB host-count run holds constant, and the one thing it varies.

    The run returned two totals that differ by 2.5x at eight hosts, and the reason is not visible
    in either number: everything from the share downwards is the same, and only the range each host
    reads changes. Drawn as one path with the two variants side by side above it, so the shared
    portion is what the eye follows and the divergence is the only fork.

    The physical port is on the figure because the client sum is not evidence on its own -- one read
    on the server can satisfy several clients, so a sum can count bytes that never left. Naming the
    port here is what makes the corroboration part of the method rather than a footnote.

    Vertical on an 880px canvas at font_size=16, and no measured number anywhere: a figure has no
    room for the environment a number needs to mean anything.
    """
    centre = 440
    return Diagram(
        name="s3burst-host-count",
        diagram_id="s3burst-host-count",
        width=880,
        height=700,
        font_size=16,
        frames=(
            Frame("hc_group", "hc_clients", 40, 40, 800, 150),
            # 64 for a two-line label, matching the frames in _two_ceilings. At 84 the bottom of
            # each box was empty, which reads as a container waiting for contents.
            Frame("hc_var_shared", "hc_shared", 40, 240, 380, 64, label_only=True),
            Frame("hc_var_disjoint", "hc_disjoint", 460, 240, 380, 64, label_only=True),
            Frame("hc_cifs", "hc_share", 280, 370, 320, 64, label_only=True),
            Frame("hc_eth", "hc_port", 280, 600, 320, 64, label_only=True),
        ),
        nodes=(
            Node("hc_h1", "client", "hc_host_first", *centred("client", 160, 110)),
            Node("hc_h2", "client", "hc_host_second", *centred("client", 320, 110)),
            Node("hc_h8", "client", "hc_host_last", *centred("client", 720, 110)),
            Node("hc_fsx", "fsx_ontap", "hc_svm", *centred("fsx_ontap", centre, 500)),
        ),
        texts=(TextBox("hc_gap", "hc_more", 480, 92, 120, 36),),
        edges=(
            Edge("hc_e_shared", "hc_group", "hc_var_shared"),
            Edge("hc_e_disjoint", "hc_group", "hc_var_disjoint"),
            Edge("hc_e_shared_share", "hc_var_shared", "hc_cifs"),
            Edge("hc_e_disjoint_share", "hc_var_disjoint", "hc_cifs"),
            Edge("hc_e_share_svm", "hc_cifs", "hc_fsx"),
            # Around the icon's label rather than through it. An icon carries its label underneath,
            # so an edge leaving the bottom edge crosses the text -- which is what the first export
            # did, with the arrow running through "SMB SVM". Leaving to the right and dropping into
            # the frame off-centre keeps both readable.
            Edge(
                "hc_e_svm_port",
                "hc_fsx",
                "hc_eth",
                exit_at=(1.0, 0.5),
                entry_at=(0.8, 0.0),
            ),
        ),
    )


DIAGRAMS = (
    _overview(),
    _single_site(),
    _cross_cloud(),
    _bottlenecks(),
    _protocol_matrix(),
    _two_ceilings(),
    _host_count(),
)


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


def package_date(package: Path) -> str:
    """The release date embedded in the package directory name, e.g. Icon-package_07312026.<hash>.

    Read rather than configured, so a new quarterly package needs no edit here. If the name does not
    carry a date the package is not the one this tool expects, and saying so beats reporting eight
    missing icons.
    """
    match = re.search(r"Icon-package_(\d{8})", package.name)
    if not match:
        raise SystemExit(
            f"build_diagrams: cannot read a release date from {package.name!r}.\n"
            "  Expected a directory named like Icon-package_07312026.<hash> from "
            "https://aws.amazon.com/architecture/icons/"
        )
    return match.group(1)


def data_uris(package: Path) -> dict[str, str]:
    """Read each icon and build its draw.io data URI.

    The comma-only form is required, and it is required for PNG as well as for SVG. Writing the URI
    the way the MIME specification would suggest — `data:image/png;base64,` — exports a broken-image
    placeholder rather than failing, so the export "succeeds" and only looking at the picture shows
    it. Established by exporting the same icon twice, once in each form.
    """
    uris = {}
    date = package_date(package)
    for key, relative in ICONS.items():
        resolved = relative.format(d=date)
        path = package / resolved
        if not path.is_file():
            raise SystemExit(f"build_diagrams: {resolved} missing from {package}")
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        uris[key] = f"data:image/svg+xml,{encoded}"

    for key, name in LOCAL_ICONS.items():
        path = LOCAL_ICON_DIR / name
        if not path.is_file():
            raise SystemExit(
                f"build_diagrams: {name} not found at {path.relative_to(ROOT)}.\n"
                "  This is a third-party product badge and is deliberately not committed, so it has\n"
                "  to be placed there once before the diagrams can be regenerated. It is embedded\n"
                "  into the generated .drawio, which is what gets committed.\n"
                f"  Where to obtain it: {LOCAL_ICON_SOURCES.get(key, 'see docs/agent/diagrams.md')}"
            )
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        uris[key] = f"data:{MIME_BY_SUFFIX[path.suffix.lower()]},{encoded}"
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
            group_style(group.gr_icon, group.stroke, diagram.font_size),
            group.x,
            group.y,
            group.width,
            group.height,
        )
    # Frames before nodes so the icons draw on top of the container they sit in.
    for frame in diagram.frames:
        vertex(
            frame.cid,
            label(frame.label, lang),
            resized(FRAME_STYLE, diagram.font_size),
            frame.x,
            frame.y,
            frame.width,
            frame.height,
        )
    for text in diagram.texts:
        vertex(
            text.cid,
            label(text.label, lang),
            resized(TEXT_STYLE, diagram.font_size),
            text.x,
            text.y,
            text.width,
            text.height,
        )
    for node in diagram.nodes:
        size = ICON_SIZE[node.icon]
        vertex(
            node.cid,
            label(node.label, lang),
            icon_style(uris[node.icon], diagram.font_size),
            node.x,
            node.y,
            size,
            size,
        )
    for edge in diagram.edges:
        value = label(edge.label, lang) if edge.label else ""
        lines.append(
            f"        <mxCell id={quoteattr(edge.cid)} value={quoteattr(value)} "
            f'style={quoteattr(edge.style(diagram.font_size))} edge="1" source={quoteattr(edge.source)} '
            f'target={quoteattr(edge.target)} parent="1">'
        )
        if edge.points:
            lines.append('          <mxGeometry relative="1" as="geometry">')
            lines.append('            <Array as="points">')
            lines += [
                f'              <mxPoint x="{x}" y="{y}" />' for x, y in edge.points
            ]
            lines.append("            </Array>")
            lines.append("          </mxGeometry>")
        else:
            lines.append('          <mxGeometry relative="1" as="geometry" />')
        lines.append("        </mxCell>")
    for note in diagram.notes:
        vertex(
            note.cid,
            label(note.label, lang),
            resized(NOTE_STYLE, diagram.font_size),
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


# draw.io stamps a fresh random element id into every SVG export, and uses it twice: once as the root
# `id` and once as the CSS selector for the adaptive-background rule. Left alone, re-exporting an
# unchanged diagram still produces a one-line diff in every SVG, which is the same failure the fixed
# MODIFIED timestamp exists to prevent -- the files that did not change bury the one that did. Since
# the id only has to be unique within the document, deriving it from the file name is enough.
SVG_RANDOM_ID = re.compile(r"ge-svg-[A-Za-z0-9_-]+")


def stabilize_svg(target: Path) -> None:
    """Replace the per-run random SVG id with one derived from the file name."""
    text = target.read_text(encoding="utf-8")
    stabilized = SVG_RANDOM_ID.sub(f"ge-svg-{target.stem}", text)
    if stabilized != text:
        target.write_text(stabilized, encoding="utf-8")


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
        if target.suffix == ".svg":
            stabilize_svg(target)
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
            xml = render(diagram, lang, uris)
            # Assert the waypoints reached the file, not that the spec listed them. In a sibling
            # repository this field existed on the dataclass and was never emitted, so every
            # waypoint in every figure was discarded while draw.io routed each edge itself -- right
            # wherever its own choice happened to match, and straight through the middle of a
            # transparent box where it did not. `--check` cannot catch that: it compares the written
            # file against the same renderer that dropped them.
            wanted = sum(len(edge.points) for edge in diagram.edges)
            got = xml.count("<mxPoint x=")
            if wanted != got:
                raise SystemExit(
                    f"build_diagrams: {path.name} carries {got} waypoint(s), spec has {wanted}"
                )
            path.write_text(xml, encoding="utf-8")
            print(f"  wrote     {path.relative_to(ROOT)}")
            if args.export:
                export(diagram, lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
