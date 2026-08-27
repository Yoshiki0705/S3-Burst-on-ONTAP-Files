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
    # Both directions are drawn because only one of them is fast. A single "auto-sync" arrow reads as
    # if the whole thing settles in seconds, which is true of the import and not of the export.
    "sync_import": {
        "ja": "取り込み ※3",
        "en": "import *3",
    },
    "sync_export": {
        "ja": "書き戻し ※4",
        "en": "write-back *4",
    },
    "nfs_smb_rw": {
        "ja": "NFS / SMB（読み書き）※2",
        "en": "NFS / SMB (read / write) *2",
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
                    "A は両方向ミリ秒（この構成での実測）",
                    "S3 → NFS は p50 9 ms、NFS → S3 AP は p50 44 ms。同一ボリューム、64 B、"
                    "actimeo=0、n=30。既定マウントではクライアント側キャッシュが支配的",
                ),
                (
                    "※3",
                    "B の取り込みは通常数秒（AWS ドキュメント記載。以下 ※4 も同じ）",
                    "対象は高性能ストレージに現在データがあるファイルのみ。"
                    "期限切れで追い出されたファイルは次のアクセスまで更新されない",
                ),
                (
                    "※4",
                    "B の書き戻しは「書き込みが約 60 秒止まってから」",
                    "待ち時間ではなく無活動時間。30 秒ごとに 5 分追記する例ではエクスポート開始は "
                    "6 分目で、追記が続く間はバケットに出ない",
                ),
                (
                    "※5",
                    "正本の置き場所の違い",
                    "A は FSx for ONTAP のボリューム。B は S3 バケットのままで、"
                    "両側が同じファイルを変更するとバケットが優先し、ファイル側は lost and found へ",
                ),
                (
                    "※6",
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
                    "A settles in milliseconds both ways (measured on this architecture)",
                    "S3 to NFS p50 9 ms; NFS to S3 Access Point p50 44 ms. Same volume, 64 B, "
                    "actimeo=0, n=30. On a default mount the client cache dominates",
                ),
                (
                    "*3",
                    "B imports in seconds, typically (AWS documentation, as is *4)",
                    "Only for files whose data is currently in the performance tier. A file evicted "
                    "on expiry is not updated until it is next accessed",
                ),
                (
                    "*4",
                    "B writes back only after roughly 60 seconds of write inactivity",
                    "Not a delay but an idle period. For an application appending every 30 seconds "
                    "for five minutes, the export starts in the sixth minute; nothing reaches the "
                    "bucket while the appending continues",
                ),
                (
                    "*5",
                    "The source of truth sits in different places",
                    "A: the FSx for ONTAP volume. B: the S3 bucket, unchanged — and if both sides "
                    "change one file the bucket wins, with the file-system copy moved to lost and "
                    "found",
                ),
                (
                    "*6",
                    "B requires consumers on AWS compute",
                    "Amazon EC2, AWS Lambda, Amazon EKS, Amazon ECS, with a mount helper",
                ),
            ),
        ),
    },
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
        "ja": "相互接続プロバイダのファブリック",
        "en": "Interconnection provider's fabric",
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
    "unconfirmed_boundary": {
        "ja": "この図が示すのはネットワーク層だけ — "
        "他クラウドのファイルストレージを Origin として FSx for ONTAP を Cache にする構成"
        "（FlexCache）は未確認、または機構として対象外",
        "en": "This figure covers the network layer only - another cloud's file storage as the "
        "origin with FSx for ONTAP as the cache (FlexCache) is unconfirmed, or out of scope as a "
        "mechanism",
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
                    "対応状況（2026-08-27 時点）",
                    "AWS Interconnect – multicloud は GA。Google Cloud は 8 ペア、"
                    "OCI は us-east-1 ↔ us-ashburn-1 の 1 ペアで、東京・大阪はいずれも対象外。"
                    "Azure は「予定」であり GA でも Preview でもない",
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
                    "Status as at 2026-08-27",
                    "AWS Interconnect - multicloud is GA: eight pairs for Google Cloud, one pair "
                    "for OCI (us-east-1 to us-ashburn-1), and no Japanese Region in either. Azure "
                    "is stated as planned, which is neither GA nor Preview",
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

    def style(self) -> str:
        style = EDGE_STYLE
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
    reads as a requirement — which would send a reader with an existing on-premises cluster looking
    for a second file system they do not need. The FlexCache edge lands on the frame so it arrives at
    the choice rather than at whichever option is drawn first.
    """
    return Diagram(
        name="s3burst-architecture-overview",
        diagram_id="s3burst-overview",
        width=1350,
        height=665,
        groups=(
            Group("aws_cloud", "aws_cloud", 50, 50, 560, 350),
            Group(
                "edge_group",
                "cache_site",
                720,
                50,
                560,
                350,
                gr_icon="group_corporate_data_center",
                stroke="#147EBA",
            ),
        ),
        frames=(Frame("cache_platform", "cache_platform", 760, 85, 220, 270),),
        nodes=(
            Node("s3client", "users", "s3_client", 100, 180),
            Node("s3ap", "s3_access_point", "s3_access_point", 270, 180),
            Node("origin_vol", "fsx_ontap", "origin_volume", 420, 164),
            Node(
                "cache_fsx",
                "fsx_ontap",
                "cache_volume_fsx",
                *centred("fsx_ontap", 870, 155),
            ),
            Node(
                "cache_ontap",
                "ontap_9",
                "cache_volume_ontap",
                *centred("ontap_9", 870, 285),
            ),
            Node("nfs_client", "client", "file_client", *centred("client", 1160, 205)),
        ),
        texts=(TextBox("cache_or", "either_of", 820, 215, 100, 20),),
        edges=(
            Edge("e1", "s3client", "s3ap", "put_object"),
            Edge("e2", "s3ap", "origin_vol"),
            Edge("e3", "origin_vol", "cache_platform", "flexcache_pull"),
            Edge("e4", "cache_platform", "nfs_client", "nfs_smb"),
        ),
        notes=(Note("note", "overview_note", 50, 440, 1250, 200),),
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
        height=825,
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
            Edge("a3", "a_vol", "a_file", "nfs_smb_rw"),
            Edge("b1", "b_client", "b_bucket", "put_object"),
            Edge("b2", "b_bucket", "b_files", "sync_import", (1, 0.25), (0, 0.25)),
            Edge("b4", "b_files", "b_bucket", "sync_export", (0, 0.75), (1, 0.75)),
            Edge("b3", "b_files", "b_file", "nfs41_protocol"),
        ),
        notes=(Note("note", "single_site_note", 40, 590, 1100, 205),),
    )


def _cross_cloud() -> Diagram:
    """Private connectivity from three other clouds to AWS, stopping where the evidence stops.

    The layout carries the argument. Left to right is the network path, and it ends at Amazon VPC.
    FSx for ONTAP sits inside the AWS boundary but the edge reaching it is dashed and labelled,
    because the FlexCache direction from another cloud's file storage is not in AWS's supported
    configurations. Drawing it solid would turn a network diagram into an architecture proposal.

    The two ways of building the connection are stacked as separate frames rather than as
    alternatives on one line, because what decides whether each is available is a different thing --
    Region pairs for the managed service, overlapping locations for the partner route -- and putting
    them on one line invites reading the second as an extension of the first's coverage.
    """
    return Diagram(
        name="s3burst-cross-cloud-connectivity",
        diagram_id="s3burst-cross-cloud",
        width=1400,
        height=900,
        groups=(Group("aws_cloud_r", "aws_cloud_consuming", 1060, 50, 290, 520),),
        frames=(
            # Ordered so that the two clouds with a managed service at GA sit next to each other and
            # their edges reach the upper frame without crossing Azure's edge to the lower one. The
            # order is a consequence of the connectivity status, not alphabetical.
            Frame("gcp", "gcp_cloud", 50, 50, 250, 150),
            Frame("oci", "oci_cloud", 50, 235, 250, 150),
            Frame("azure", "azure_cloud", 50, 420, 250, 150),
            Frame("managed", "managed_way", 620, 50, 330, 230),
            Frame("partner", "partner_way", 620, 320, 330, 250),
            Frame("aws_vpc_f", "aws_vpc", 1085, 100, 240, 440),
        ),
        nodes=(
            Node(
                "gcnv_n",
                "gcnv_storage_category",
                "gcnv",
                *centred("gcnv_storage_category", 175, 110),
            ),
            Node(
                "anf_n",
                "azure_netapp_files",
                "anf",
                *centred("azure_netapp_files", 175, 480),
            ),
            Node(
                "ic_n",
                "aws_interconnect",
                "aws_interconnect_mc",
                *centred("aws_interconnect", 785, 145),
            ),
            Node(
                "dx_n",
                "direct_connect",
                "direct_connect",
                *centred("direct_connect", 785, 400),
            ),
            Node(
                "fsx_n",
                "fsx_ontap",
                "fsx_here",
                *centred("fsx_ontap", 1205, 200),
            ),
            Node(
                "s3ap_n",
                "s3_access_point",
                "s3ap_here",
                *centred("s3_access_point", 1205, 420),
            ),
        ),
        texts=(
            TextBox("oci_fs", "oci_file_storage", 90, 295, 170, 30),
            TextBox("gcp_net", "gcp_vpc", 340, 110, 200, 20),
            TextBox("oci_net", "oci_vcn", 340, 295, 200, 20),
            TextBox("azure_net", "azure_vnet", 340, 480, 200, 20),
            TextBox("fabric", "provider_fabric", 645, 480, 280, 40),
            # A banner across the top rather than a label wedged between the connectivity column and
            # the AWS boundary. Placed there it overlapped the two edges entering the VPC: a TextBox
            # does not clip, so its text overflowed the 95 px box and crossed the arrowheads. It is
            # also the first thing read, which is where a limit belongs.
            TextBox("boundary", "unconfirmed_boundary", 50, 8, 1300, 30),
        ),
        edges=(
            Edge("x1", "gcnv_n", "gcp_net"),
            Edge("x2", "anf_n", "azure_net"),
            Edge("x3", "oci_fs", "oci_net"),
            # Which way each cloud can use today. Google Cloud and OCI have a managed service at GA;
            # Azure has only the partner route, because it is not yet a supported CSP. Sending OCI to
            # the partner frame would have said the opposite of what its GA status says.
            Edge("x4", "gcp_net", "managed", "private_path"),
            Edge("x5", "oci_net", "managed", "private_path"),
            Edge("x6", "azure_net", "partner", "private_path"),
            Edge("x7", "managed", "aws_vpc_f"),
            Edge("x8", "partner", "aws_vpc_f"),
            Edge("x9", "s3ap_n", "fsx_n"),
        ),
        notes=(Note("note", "cross_cloud_note", 50, 620, 1300, 260),),
    )


DIAGRAMS = (_overview(), _single_site(), _cross_cloud())


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
            group_style(group.gr_icon, group.stroke),
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
            FRAME_STYLE,
            frame.x,
            frame.y,
            frame.width,
            frame.height,
        )
    for text in diagram.texts:
        vertex(
            text.cid,
            label(text.label, lang),
            TEXT_STYLE,
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
            f'style={quoteattr(edge.style())} edge="1" source={quoteattr(edge.source)} '
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
            path.write_text(render(diagram, lang, uris), encoding="utf-8")
            print(f"  wrote     {path.relative_to(ROOT)}")
            if args.export:
                export(diagram, lang)
    return 0


if __name__ == "__main__":
    sys.exit(main())
