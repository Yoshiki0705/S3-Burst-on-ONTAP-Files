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
    "ec2": "Architecture-Service-Icons_{d}/Arch_Compute/64/Arch_Amazon-EC2_64.svg",
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
    "ec2": 80,
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


# --- labels --------------------------------------------------------------------------------------

# Node labels stay English in both languages: they are product names and protocol names, which the
# repository's translation rules exclude. Panel titles and footnotes are prose and are localized.
LABELS: dict[str, dict[str, str]] = {
    # --- two ceilings -----------------------------------------------------------------------
    # This figure answers "why did the same file system return two numbers", so every label names a
    # location rather than a value. The measured figures stay in the prose table beside it: kept in
    # the image they would be maintained by hand in two places, and the image is not searchable,
    # translatable or reachable by a screen reader.
    "tc_fsx_service": {
        # The AWS icon guidance requires a service icon to carry the service's full official name,
        # not an abbreviation or a role word alone. So the first line is "Amazon FSx for NetApp
        # ONTAP" and the role ("file server") drops to a second line as a qualifier.
        "ja": "Amazon FSx for NetApp ONTAP\n(ファイルサーバー)",
        "en": "Amazon FSx for NetApp ONTAP\n(file server)",
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
    # The SVM runs on an FSx for ONTAP file system, and the icon is the FSx for ONTAP service
    # icon, so its label carries the full service name with the SMB-SVM role as a qualifier --
    # "SMB SVM" alone named a role and no service, which the AWS icon guidance does not allow.
    "hc_svm": {
        "ja": "Amazon FSx for NetApp ONTAP\n(SMB SVM)",
        "en": "Amazon FSx for NetApp ONTAP\n(SMB SVM)",
    },
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
        "ja": "ONTAP 9（オンプレミス）\n[未検証]",
        "en": "ONTAP 9 (on-premises)\n[unverified]",
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
    # Carries the stage, and is therefore separate from cache_vol_fsx_stacked above even though the
    # product name is the same. That label is also used by the protocol test matrix, where the same
    # icon stands for the storage under test rather than for one of two cache platforms -- a stage
    # marker there would be answering a question that figure does not ask.
    #
    # The stage is inside the image on purpose. A caption saying which of the two cache platforms
    # has been exercised is lost the moment the figure is screenshotted or lifted into a slide, and
    # what survives is a picture in which both options look equally settled. Only one has been
    # measured, so only one may look like the reference.
    "cache_vol_fsx_staged": {
        "ja": "Amazon FSx for\nNetApp ONTAP\n[検証済み]",
        "en": "Amazon FSx for\nNetApp ONTAP\n[verified]",
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
    # --- s3files internals figure ---
    "sfi_host_1": {"ja": "Linux Client 1", "en": "Linux Client 1"},
    "sfi_host_n": {"ja": "Linux Client N", "en": "Linux Client N"},
    "sfi_proxy_1": {
        "ja": "efs-proxy (TLS)\nホストごと・1 コアが上限",
        "en": "efs-proxy (TLS)\nper host, capped at one core",
    },
    "sfi_proxy_n": {
        "ja": "efs-proxy (TLS)\nホストごと・1 コアが上限",
        "en": "efs-proxy (TLS)\nper host, capped at one core",
    },
    "sfi_files": {
        "ja": "Amazon S3 Files\n(built on Amazon EFS)",
        "en": "Amazon S3 Files\n(built on Amazon EFS)",
    },
    "sfi_hps": {
        "ja": "高性能ストレージ\n(作業セット、しきい値未満)",
        "en": "High-performance storage\n(working set, below threshold)",
    },
    "sfi_bucket": {
        "ja": "Amazon S3 Bucket\n(正本。1 MiB 以上は直読)",
        "en": "Amazon S3 Bucket\n(source of truth; 1 MiB+ read direct)",
    },
    "sfi_nfs": {"ja": "NFS v4.1 / 4.2", "en": "NFS v4.1 / 4.2"},
    "sfi_scale": {
        "ja": "台数を増やすと合計は線形\n(8 台で 8.01x)",
        "en": "aggregate scales linearly with hosts\n(8.01x at 8 hosts)",
    },
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
    "sync_both_ways": {
        "ja": "取り込み / 書き戻し",
        "en": "import / write-back",
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
    # Inside the managed frame rather than on an edge from Azure. Azure sits to the right of both
    # ways in, so an edge from it to this frame can only run backwards -- 485px back across the
    # figure, crossing OCI's riser on the way. The fact it carried is kept here, where it is read
    # with the frame it belongs to.
    "managed_azure_preview": {
        "ja": "Azure は Preview（2026-08 時点）。GCP と OCI は GA",
        "en": "Azure is at Preview (as of 2026-08); GCP and OCI are GA",
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
    # --- block protocol articles (A / B / C) -----------------------------------------------------
    # Shared across the three: what is being measured is the connection count between one EC2
    # client and one FSx for ONTAP file system, not multiple clients pooled together. Naming the
    # generation and AZ layout matters here because the divisor in the AWS procedure this article
    # tests is stated per client, not per file system.
    "ba_ec2": {
        "ja": "Amazon EC2\n(c5n.9xlarge クライアント)",
        "en": "Amazon EC2\n(c5n.9xlarge client)",
    },
    "ba_fsx": {
        "ja": "Amazon FSx for NetApp ONTAP\n(第二世代 SINGLE_AZ_2)",
        "en": "Amazon FSx for NetApp ONTAP\n(second-generation SINGLE_AZ_2)",
    },
    "ba_iscsi": {
        "ja": "iSCSI\n(複数セッション)",
        "en": "iSCSI\n(multiple sessions)",
    },
    "ba_nvme": {
        "ja": "NVMe/TCP\n(複数キュー)",
        "en": "NVMe/TCP\n(multiple queues)",
    },
    "ba_or": {"ja": "または", "en": "or"},
    "ba_vpc": {
        "ja": "単一 VPC・単一 AZ（ネットワーク的な遠回りが無い状態）",
        "en": "Single VPC, single AZ (no network detour)",
    },
    "aws_cloud_plain": {
        "ja": "AWS Cloud",
        "en": "AWS Cloud",
    },
    # Block B: the HA pair behind one namespace, and the two paths ANA (multipathing) resolves into
    # one optimized route plus one standby. Drawn as two named paths rather than one link, because
    # the article's entire point is that without ANA in the kernel these look like two independent
    # devices rather than one path plus its standby.
    "bb_ec2": {
        "ja": "Amazon EC2\n(Amazon Linux 2023 クライアント)",
        "en": "Amazon EC2\n(Amazon Linux 2023 client)",
    },
    "bb_ha_pair": {
        "ja": "FSx for ONTAP HA ペア\n(第二世代 SINGLE_AZ_2)",
        "en": "FSx for ONTAP HA pair\n(second-generation SINGLE_AZ_2)",
    },
    # Each controller is one node of an FSx for ONTAP HA pair, drawn with the FSx for ONTAP
    # service icon, so the label carries the full service name and the controller identity drops
    # to a qualifier line -- the abbreviation "FSx for ONTAP" alone is not allowed on a service
    # icon by the AWS icon guidance.
    "bb_ctrl_a": {
        "ja": "Amazon FSx for NetApp ONTAP\n(コントローラ A)",
        "en": "Amazon FSx for NetApp ONTAP\n(Controller A)",
    },
    "bb_ctrl_b": {
        "ja": "Amazon FSx for NetApp ONTAP\n(コントローラ B)",
        "en": "Amazon FSx for NetApp ONTAP\n(Controller B)",
    },
    "bb_optimized": {
        "ja": "経路 1: optimized（最短経路）",
        "en": "Path 1: optimized (shortest route)",
    },
    "bb_non_optimized": {
        "ja": "経路 2: non-optimized（ANA 無効時は通常経路に見える）",
        "en": "Path 2: non-optimized (looks like a normal route without ANA)",
    },
    "bb_namespace": {"ja": "1 つの namespace", "en": "One namespace"},
    # Block C: two deployments built from the same template and the same specified values. The one
    # difference the figure exists to name is the thing no parameter list shows -- layout on disk --
    # so every other row in that list is drawn identical on purpose.
    "bc_deploy1": {
        "ja": "デプロイ 1",
        "en": "Deployment 1",
    },
    "bc_deploy2": {
        "ja": "デプロイ 2",
        "en": "Deployment 2",
    },
    "bc_ec2": {
        "ja": "Amazon EC2\n(同じ接続・同じワークロードのクライアント)",
        "en": "Amazon EC2\n(client, same connection and workload)",
    },
    "bc_fsx_same": {
        "ja": "Amazon FSx for NetApp ONTAP\n(同じテンプレート・同じ指定値)",
        "en": "Amazon FSx for NetApp ONTAP\n(same template, same specified values)",
    },
    "bc_same_conditions": {
        "ja": "揃えられる: 経路・接続の作り方・キュー数・<br>ディストリビューション・iopolicy",
        "en": "Held identical: path, connection setup, queue count,<br>distribution, iopolicy",
    },
    "bc_hidden_diff": {
        "ja": "揃えられない: ディスク上の配置\n(指定値の一覧には出てこない)",
        "en": "Cannot be held identical: layout on disk\n(does not appear in any specified value)",
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
    # Moves the label off the midpoint, in pixels. Needed where two edges leave one icon a few
    # tens of pixels apart: draw.io puts both labels at the midpoint of their own run, and at that
    # separation the two texts land on top of each other -- the fork in _two_ceilings rendered as
    # "キャッキャッシュに無い". Written as `<mxPoint as="offset">`, which the waypoint count in
    # `check()` does not match, so the two stay independent.
    label_offset: tuple[int, int] = (0, 0)

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
    # Left-aligned title, for a frame two edges pass straight through on their way to a node
    # inside it. A centred title sits directly over that centre line -- "FSx for ONTAP HA ペア"
    # over two lines converging on x=440 read as "FSx for ONTAP HÁ ペア" with a line through the
    # second word. Left alignment moves the words to the frame's own left margin, which nothing
    # here needs to cross.
    title_align_left: bool = False


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
        height=1080,
        font_size=16,
        groups=(
            Group("aws_cloud", "aws_cloud", 40, 60, 560, 250),
            Group(
                "edge_group",
                "cache_site",
                340,
                580,
                540,
                440,
                gr_icon="group_corporate_data_center",
                stroke="#147EBA",
            ),
        ),
        frames=(
            Frame("cache_platform", "cache_platform", 365, 620, 250, 360),
            # Directly under the origin volume, and the cache site directly under that: three bands
            # in one column. Placed to the *left* of the origin, as it was, the FlexCache edge had
            # to leave rightwards, drop, and then travel 465px back the other way before turning
            # down again -- right, down, left, down, in the one figure that has to show which
            # direction the data moves.
            Frame("link_layer", "connect_layer", 355, 350, 270, 190),
        ),
        nodes=(
            Node("s3client", "users", "s3_client_stacked", 90, 150),
            Node("s3ap", "s3_access_point", "s3_ap_stacked", 250, 150),
            Node("origin_vol", "fsx_ontap", "origin_vol_two_line", 450, 134),
            Node(
                "cache_fsx",
                "fsx_ontap",
                "cache_vol_fsx_staged",
                *centred("fsx_ontap", 490, 700),
            ),
            Node(
                "cache_ontap",
                "ontap_9",
                "cache_volume_ontap",
                *centred("ontap_9", 490, 885),
            ),
            Node(
                "nfs_client",
                "client",
                "file_client_stacked",
                *centred("client", 770, 800),
            ),
        ),
        texts=(
            # Sits between the two platform labels, not against the upper one. The FSx label gained
            # a third line for its stage, and at the original y this word landed hard under it and
            # read as part of that label rather than as the choice between the two.
            TextBox("cache_or", "either_of", 455, 822, 70, 20),
            TextBox("link_1", "link_same_region", 370, 390, 240, 20),
            TextBox("link_2", "link_cross_region", 370, 425, 240, 40),
            TextBox("link_3", "link_onprem", 370, 480, 240, 40),
        ),
        edges=(
            Edge("e1", "s3client", "s3ap", "put_object"),
            Edge("e2", "s3ap", "origin_vol"),
            # Straight down, both of them. The FlexCache label stays on the first leg, because
            # FlexCache is what crosses the link -- the frame says what the link is made of, not
            # what runs over it.
            Edge(
                "e3",
                "origin_vol",
                "link_layer",
                "flexcache_pull",
                (0.5, 1.0),
                (0.5, 0.0),
            ),
            Edge(
                "e3b",
                "link_layer",
                "cache_platform",
                "",
                (0.5, 1.0),
                (0.5, 0.0),
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
            # One leg with an arrowhead at each end, not two legs. Both directions are real, and
            # drawn as a pair the write-back was the only edge in the figure pointing back the way
            # the figure came -- which is what a reader has to disentangle before they can tell
            # which arrow carries what. The same choice as panels B and C of _bottlenecks.
            Edge("b2", "b_bucket", "b_files", "sync_both_ways", both_ways=True),
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
            # The access point on the left, the file system it fronts on the right -- the order the
            # other figures use, and the order that lets the edge between them advance.
            Node(
                "s3ap_n",
                "s3_access_point",
                "s3ap_here",
                *centred("s3_access_point", 260, 930),
            ),
            Node(
                "fsx_n",
                "fsx_ontap",
                "fsx_here",
                *centred("fsx_ontap", 620, 930),
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
            TextBox("managed_note", "managed_azure_preview", 55, 690, 400, 46),
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
            # Down the overlap between the two frames, not out and back along y=410. The managed
            # frame ends at 470 and OCI starts at 350, so an exit inside that band drops vertically.
            Edge(
                "x5",
                "oci",
                "managed",
                "private_path",
                (0.35, 1),
                (0.95, 0),
            ),
            Edge("x6", "azure", "partner", "private_path", (0.5, 1), (0.66, 0)),
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
            # Under the origin it pulls from, not back at the left margin. On the left, the
            # FlexCache edge had to run out to a riser at x=840 and then 640px back the other way
            # before turning down -- and the direction data moves is the one thing this panel is
            # for.
            Node(
                "a_cache",
                "fsx_ontap",
                "cache_vol_short",
                *centred("fsx_ontap", 665, row_a2),
            ),
            Node(
                "a_file", "client", "nfs_client_short", *centred("client", 830, row_a2)
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
            # One way on purpose: the cache pulls from the origin. Straight down now that the
            # cache sits underneath it.
            Edge(
                "q3",
                "a_origin",
                "a_cache",
                "flexcache_edge",
                (0.5, 1.0),
                (0.5, 0.0),
                # Beside the run rather than on it: centred, it landed immediately under the
                # origin's two-line label and read as a third line of it.
                label_offset=(70, 30),
            ),
            # "nfs_smb", not "nfs_smb_read". The panel title already says the direction and the
            # arrowhead says it again, and at this pitch the longer text ran onto the cache icon.
            Edge("q4", "a_cache", "a_file", "nfs_smb"),
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
        height=1040,
        font_size=16,
        groups=(
            Group("panel_a2", "panel_read_paths", 40, 60, 880, 270),
            Group("panel_d", "panel_efs", 40, 350, 880, 220),
            Group("panel_e", "panel_ontap_protocols", 40, 590, 880, 350),
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
            # Below both clients rather than between them. Between them, the lower client's leg
            # had to run upwards to reach it, so panel E was the one place in the figure where two
            # arrows on the same fan pointed opposite ways.
            Node(
                "e_ontap",
                "fsx_ontap",
                "cache_vol_fsx_stacked",
                *centred("fsx_ontap", 400, 830),
            ),
        ),
        texts=(
            # Inside the panel, not on its border. Two captions rather than three: the write and
            # the A-1 read are the same leg travelled twice, so splitting them across two x
            # positions would say they are different links.
            TextBox("t_write_a1", "write_then_a1", 60, 268, 400, 46),
            TextBox("t_a2", "read_a2", 500, 280, 400, 24),
            TextBox("t_efs_p", "efs_protocols", 510, 395, 390, 120),
            TextBox("t_ontap_p", "ontap_protocols", 540, 760, 360, 90),
            # Below panel E rather than inside it: it is about D and E together, and a caption about
            # two panels sitting inside one of them reads as belonging to that one.
            TextBox("t_comparable", "comparable_only", 60, 955, 560, 46),
        ),
        edges=(
            Edge("m1", "m_s3c", "m_ap", "s3_api_rw", both_ways=True),
            Edge("m2", "m_ap", "m_origin", both_ways=True),
            # A-2 leaves the same volume the S3 API wrote to. One way: this leg is the read, which
            # caption 3 under it also says -- so the label is the protocol only. Spelled out, it
            # was wider than the gap and ran onto the file system icon.
            Edge("m3", "m_origin", "m_file", "nfs_smb"),
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

    The outer group is "AWS Cloud" -- the account/partition boundary AWS's own reference diagrams
    use for a group -- not the file server relabelled to carry that job. The file server itself
    gets its own FSx for ONTAP service icon inside the boundary, between the client and the fork,
    so the read arrives at a named service before the figure asks which path inside it serves it.
    """
    centre = 440
    return Diagram(
        name="s3burst-two-ceilings",
        diagram_id="s3burst-two-ceilings",
        width=880,
        height=720,
        font_size=16,
        groups=(Group("tc_aws_cloud", "aws_cloud_plain", 20, 180, 840, 490),),
        frames=(
            # Sized to the two-line label. A frame taller than its text reads as an empty container
            # waiting to be filled, which is a claim about the architecture rather than about layout.
            # The inner edge of each box sits under the FSx icon's own edge, so both arms of
            # the fork drop almost vertically onto a corner instead of running out sideways. A
            # fork is not an inconsistent direction, but an arm that travels 200px to the left
            # before turning down reads as one.
            Frame("tc_cache", "tc_cache_layer", 90, 460, 330, 64, label_only=True),
            # x=480: cache frame at 90 (centre 255) and disk frame at 480 (centre 645) sit either
            # side of the FSx icon's centre column (440), so the fork's two branches are the same
            # length. The edges enter each frame on its own centre now, not on a corner.
            Frame("tc_disk", "tc_ssd", 480, 460, 330, 64, label_only=True),
            Frame(
                "tc_cap_cache", "tc_ceiling_cache", 90, 590, 330, 64, label_only=True
            ),
            Frame("tc_cap_disk", "tc_ceiling_disk", 480, 590, 330, 64, label_only=True),
        ),
        nodes=(
            # The client stays outside the AWS Cloud boundary, matching the app/pipeline actor in
            # every other figure in this set.
            Node("tc_users", "client", "tc_client", *centred("client", centre, 90)),
            # cy=270, not 280: the icon's own two-line label (ends ~40px below the icon's own
            # bottom edge) has to clear the hit/miss labels sitting at the fork's midpoint before
            # the fork frames start at y=440, and moving the icon up by 10px was the difference
            # between the two label bands touching and a full clear row between them.
            Node(
                "tc_fsx",
                "fsx_ontap",
                "tc_fsx_service",
                *centred("fsx_ontap", centre, 270),
            ),
        ),
        # A tree fork from the file server down to the two ceilings. Each arm leaves the FSx
        # icon's centre going straight down, turns once at the branch row (y=410, the clear band
        # between the icon's two-line label ~352 and the frames at 460), runs to the target
        # frame's centre column, then drops vertically into the top of the frame. This is the
        # orthogonal tree-connector shape (one trunk, right-angle branches, vertical entry to each
        # child's centre) rather than two diagonal legs off the icon's corners -- the read arrives
        # at one fork, and the "in cache" / "not in cache" labels sit on the horizontal branch
        # each names.
        #
        # Cache frame: x=90, w=330, centre 255. Disk frame: x=480, w=330, centre 645. The FSx icon
        # is centred on 440. Each label is pulled onto its own branch's horizontal run and away
        # from the trunk with label_offset, so neither sits under the FSx service name.
        edges=(
            Edge("tc_e_in", "tc_users", "tc_fsx"),
            Edge(
                "tc_e_hit",
                "tc_fsx",
                "tc_cache",
                "tc_hit",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((440, 410), (255, 410)),
                label_offset=(-60, -18),
            ),
            Edge(
                "tc_e_miss",
                "tc_fsx",
                "tc_disk",
                "tc_miss",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((440, 410), (645, 410)),
                label_offset=(60, -18),
            ),
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
            # Centred on the quarter points of the frame above, so each arm of the fork leaves at
            # the quarter point it lands on and drops straight down rather than travelling
            # sideways first.
            Frame("hc_var_shared", "hc_shared", 50, 240, 380, 64, label_only=True),
            Frame("hc_var_disjoint", "hc_disjoint", 450, 240, 380, 64, label_only=True),
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
            Edge(
                "hc_e_shared",
                "hc_group",
                "hc_var_shared",
                exit_at=(0.25, 1.0),
                entry_at=(0.5, 0.0),
            ),
            Edge(
                "hc_e_disjoint",
                "hc_group",
                "hc_var_disjoint",
                exit_at=(0.75, 1.0),
                entry_at=(0.5, 0.0),
            ),
            # Both variants converge on the one share, and the right-hand one reaches it by
            # leaving its own left edge and entering the share's right -- which advances
            # rightwards, where a centre-to-centre run would have gone 200px back the other way.
            Edge(
                "hc_e_shared_share",
                "hc_var_shared",
                "hc_cifs",
                exit_at=(0.5, 1.0),
                entry_at=(0.0, 0.0),
            ),
            Edge(
                "hc_e_disjoint_share",
                "hc_var_disjoint",
                "hc_cifs",
                exit_at=(0.0, 1.0),
                entry_at=(1.0, 0.0),
            ),
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


def _block_a_sessions() -> Diagram:
    """What Article A's session/queue-count measurement connects.

    One EC2 client, one FSx for ONTAP file system, and a choice of protocol: iSCSI with multiple
    sessions, or NVMe/TCP with multiple queues. The article's point is that "single client
    bandwidth ceiling / 625" does not size either count correctly, and that claim is about this
    one-to-one connection -- not about pooling multiple clients, which the figure does not draw.

    Vertical, 880px canvas, so font_size=16 clears the readability floor at full width.
    """
    centre = 440
    return Diagram(
        name="s3burst-block-a-sessions",
        diagram_id="s3burst-block-a-sessions",
        width=880,
        height=760,
        font_size=16,
        # Two bands, matching the official AWS reference layout: an outer "AWS Cloud" group (the
        # cloud-icon group AWS's own decks use for the account/partition boundary) holding an inner
        # "single VPC, single AZ" frame, rather than one frame relabelled to both jobs at once.
        groups=(Group("ba_aws_cloud", "aws_cloud_plain", 20, 20, 840, 640),),
        frames=(
            Frame("ba_vpc_group", "ba_vpc", 40, 70, 800, 570, label_only=True),
            Frame("ba_p1", "ba_iscsi", 100, 320, 300, 70, label_only=True),
            Frame("ba_p2", "ba_nvme", 480, 320, 300, 70, label_only=True),
        ),
        nodes=(
            Node("ba_client", "ec2", "ba_ec2", *centred("ec2", centre, 190)),
            # cy=510: the merge row where the two protocol branches rejoin sits at y=430, and the
            # FSx icon's top must clear it -- at the old cy=450 (top 410) the merge line ran
            # straight through the icon's own body. 510 puts the top at 470, a clear 40px below
            # the merge, so the single trunk drops into the top edge instead of crossing the icon.
            Node(
                "ba_target", "fsx_ontap", "ba_fsx", *centred("fsx_ontap", centre, 510)
            ),
        ),
        texts=(TextBox("ba_or_text", "ba_or", 410, 345, 60, 20),),
        # A tree fork, not four diagonal legs. Each arm leaves the icon's own centre going
        # straight down, turns once at the branch row (y=300, the clear row above the protocol
        # frames), runs horizontally to the frame's centre column, then drops vertically into the
        # top of the frame. The return legs mirror it: each leaves a frame's centre, drops to the
        # merge row (y=430, a clear band below the frames' bottom at 390 and above the FSx icon's
        # top at 470), runs to the trunk column, then drops as one line into the top of the FSx
        # icon's centre. This is the orthogonal tree-connector shape (one trunk, right-angle
        # branches, vertical entry to each child's centre) the connector-routing guidance
        # converges on, read as a single fork and a single merge rather than four diagonal legs.
        #
        # The frame centres are 250 (iSCSI: x=100, w=300) and 630 (NVMe: x=480, w=300); the EC2
        # and FSx icons are centred on 440.
        edges=(
            Edge(
                "ba_e1",
                "ba_client",
                "ba_p1",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((440, 300), (250, 300)),
            ),
            Edge(
                "ba_e2",
                "ba_client",
                "ba_p2",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((440, 300), (630, 300)),
            ),
            Edge(
                "ba_e3",
                "ba_p1",
                "ba_target",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((250, 430), (440, 430)),
            ),
            Edge(
                "ba_e4",
                "ba_p2",
                "ba_target",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((630, 430), (440, 430)),
            ),
        ),
    )


def _block_b_multipath() -> Diagram:
    """The two paths behind one namespace, and what ANA (multipathing) does with them.

    An HA pair always presents two paths to one namespace: one to whichever controller is closest
    (optimized) and one to the other (non-optimized, for failover). ANA is what tells the host
    which is which. Without it in the kernel, the article's whole finding is that these two paths
    show up as two independent devices pointing at the same data rather than as a primary route
    plus its standby -- so the figure draws both paths reaching the same namespace explicitly,
    rather than one link from the client to the file system.

    Vertical, 880px canvas, font_size=16.
    """
    centre = 440
    # Every edge now enters and leaves on an icon's own centre (x fraction 0.5) and turns at a
    # branch row, so the flow-direction gate sees each arm as a straight vertical drop with a
    # single horizontal branch in a clear band -- no anchor carries sideways motion. The two
    # The controllers sit either side of the client's centre; the namespace frame is centred under
    # the client so the merge is symmetric. They are spread wide (230 / 650, centre 440) because
    # each now carries the full "Amazon FSx for NetApp ONTAP" service name -- at the old 160px
    # centre spacing the two names collided in the middle. ns is centred on 440 between them.
    ctrl_a_cx, ctrl_b_cx = 230, 650
    branch_y, merge_y = 340, 680
    ns_w = 120
    ns_x = centre - ns_w // 2
    # Vertical bands, top to bottom, with a full clear row between each so a label's own text
    # never enters the row above or below it: AWS Cloud title (20-70) / EC2 client icon + its
    # two-line label (110-290) / path names in the clear row that follows (300-345) / HA-pair
    # frame title (365-410) / controller icons + their two-line labels (480-670) / namespace
    # frame (720-790).
    ec2_cy = 150
    ctrl_cy = 520
    return Diagram(
        name="s3burst-block-b-multipath",
        diagram_id="s3burst-block-b-multipath",
        width=1000,
        height=860,
        font_size=16,
        groups=(Group("bb_aws_cloud", "aws_cloud_plain", 20, 20, 960, 820),),
        frames=(
            Frame(
                "bb_pair_group",
                "bb_ha_pair",
                40,
                350,
                920,
                450,
                label_only=True,
                title_align_left=True,
            ),
            Frame("bb_ns", "bb_namespace", ns_x, 720, ns_w, 70, label_only=True),
        ),
        nodes=(
            Node("bb_client", "ec2", "bb_ec2", *centred("ec2", centre, ec2_cy)),
            Node(
                "bb_a",
                "fsx_ontap",
                "bb_ctrl_a",
                *centred("fsx_ontap", ctrl_a_cx, ctrl_cy),
            ),
            Node(
                "bb_b",
                "fsx_ontap",
                "bb_ctrl_b",
                *centred("fsx_ontap", ctrl_b_cx, ctrl_cy),
            ),
        ),
        # One full clear row below the client's own two-line label, and directly above the
        # HA-pair frame's title -- never sharing a row with either. Each spans its half of the
        # 1000px canvas so the path name sits over the controller column it describes.
        texts=(
            TextBox("bb_t1", "bb_optimized", 20, 300, 460, 40),
            TextBox("bb_t2", "bb_non_optimized", 520, 300, 460, 40),
        ),
        # A tree fork from the client down to the two controllers, then a mirror-image merge from
        # the two controllers down into the one namespace. Every arm leaves and enters an icon on
        # its centre (x fraction 0.5), going straight down; the single horizontal run happens at a
        # branch row in a clear band, never at an anchor. This is the orthogonal tree-connector
        # shape the connector-routing guidance settles on: one trunk, right-angle branches,
        # vertical entry to each child's centre -- read as one fork and one merge, not four
        # independent diagonal legs.
        #
        # Branch row (branch_y=340) sits between the client's label band (ends ~290) and the
        # HA-pair frame title (350). Merge row (merge_y=680) sits below the controllers' labels
        # (~670) and above the namespace frame (720). The controllers are centred on ctrl_a_cx /
        # ctrl_b_cx; the client and the namespace frame are both centred on `centre`. Waypoints
        # are derived from those so the fork stays symmetric when the spacing changes.
        edges=(
            Edge(
                "bb_e1",
                "bb_client",
                "bb_a",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((centre, branch_y), (ctrl_a_cx, branch_y)),
            ),
            Edge(
                "bb_e2",
                "bb_client",
                "bb_b",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((centre, branch_y), (ctrl_b_cx, branch_y)),
            ),
            Edge(
                "bb_e3",
                "bb_a",
                "bb_ns",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((ctrl_a_cx, merge_y), (centre, merge_y)),
            ),
            Edge(
                "bb_e4",
                "bb_b",
                "bb_ns",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
                points=((ctrl_b_cx, merge_y), (centre, merge_y)),
            ),
        ),
    )


def _block_c_layout() -> Diagram:
    """Two deployments, identical on paper, one hidden difference.

    Same CloudFormation template, same specified values, same path/connection/queue-count/
    distribution/iopolicy -- and still a 2.64x swing in sequential-read throughput between them.
    The figure's entire job is to make one thing visible that no parameter list shows: the layout
    data lands in on disk, which differs between deployments and is not a configuration knob at
    all. Drawing the two deployments side by side, both labelled "same template, same values", is
    what makes that gap legible -- a single deployment box would have nothing to contrast against.

    Vertical, 880px canvas, font_size=16.
    """
    return Diagram(
        name="s3burst-block-c-layout",
        diagram_id="s3burst-block-c-layout",
        width=880,
        height=820,
        font_size=16,
        # An outer "AWS Cloud" group (the account/partition boundary AWS's own reference
        # diagrams use) contains the two per-deployment groups side by side, matching the
        # official two-band layout instead of relabelling one band to do both jobs.
        #
        # Each per-deployment group is 480 tall, not 320: the FSx icon's own two-line label
        # ("Amazon FSx for NetApp ONTAP" / "(same template, same specified values)") runs to
        # about 50px below the icon's bottom edge, and at 320 the group closed 30px above
        # that -- the label's second line sat on the group's own border. 480 clears both the
        # EC2 icon's label and the FSx icon's label with room to spare.
        groups=(
            Group("bc_aws_cloud", "aws_cloud_plain", 20, 20, 840, 550),
            Group("bc_g1", "bc_deploy1", 60, 70, 380, 480),
            Group("bc_g2", "bc_deploy2", 480, 70, 380, 480),
        ),
        nodes=(
            Node("bc_c1", "ec2", "bc_ec2", *centred("ec2", 250, 180)),
            Node("bc_f1", "fsx_ontap", "bc_fsx_same", *centred("fsx_ontap", 250, 430)),
            Node("bc_c2", "ec2", "bc_ec2", *centred("ec2", 670, 180)),
            Node("bc_f2", "fsx_ontap", "bc_fsx_same", *centred("fsx_ontap", 670, 430)),
        ),
        frames=(
            Frame("bc_same", "bc_same_conditions", 40, 620, 800, 70, label_only=True),
            Frame("bc_diff", "bc_hidden_diff", 40, 710, 800, 70, label_only=True),
        ),
        edges=(
            Edge("bc_e1", "bc_c1", "bc_f1"),
            Edge("bc_e2", "bc_c2", "bc_f2"),
        ),
    )


def _s3files_internals() -> Diagram:
    """What S3 Files looks like from the inside, and the two things the measurements settled.

    The talk and the blog built on these measurements make one claim about shape: a single mount is
    capped by one efs-proxy core, and the aggregate scales with host count because each host has its
    own proxy. No existing figure shows that -- the single-site figure draws S3 Files as one box,
    and the bottlenecks figure compares three paths without opening S3 Files up. This one opens it:
    two client hosts, each with its own efs-proxy drawn as a named waypoint (there is no proxy icon,
    and inventing one would misattribute the component), both reaching the file system, which routes
    to high-performance storage for the working set and to the bucket direct for large reads.

    No measured number on the canvas: a figure has no room for the environment a number needs. The
    two findings sit as short labels (per-host proxy cap, linear aggregate); the numbers are in the
    prose beside the figure and in docs/ja/verification/s3files-throughput-measured.md.

    Vertical, 880px canvas, font_size=16.
    """
    return Diagram(
        name="s3burst-s3files-internals",
        diagram_id="s3burst-s3files-internals",
        width=880,
        height=760,
        font_size=16,
        groups=(
            # The AWS Cloud boundary: everything here is inside one account/VPC.
            Group("sfi_cloud", "aws_cloud", 30, 30, 820, 700),
        ),
        frames=(
            # Per-host efs-proxy, drawn as named waypoints under each client. The per-host cap is
            # the first finding, so it is on the proxy label itself.
            # x set so each frame's horizontal centre is exactly the column it sits in (230 / 630),
            # so the vertical edges enter and leave dead-centre and the flow check reads them as
            # straight-down rather than drifting 10px sideways.
            Frame("sfi_px1", "sfi_proxy_1", 80, 250, 300, 64, label_only=True),
            Frame("sfi_px2", "sfi_proxy_n", 480, 250, 300, 64, label_only=True),
            # The two routing targets below the file system.
            Frame("sfi_hp", "sfi_hps", 65, 600, 330, 72, label_only=True),
            Frame("sfi_bk", "sfi_bucket", 465, 600, 330, 72, label_only=True),
        ),
        nodes=(
            Node("sfi_c1", "client", "sfi_host_1", *centred("client", 230, 110)),
            Node("sfi_c2", "client", "sfi_host_n", *centred("client", 630, 110)),
            # Two file-system nodes, one under each client column, so every edge runs straight down
            # its own column and nothing crosses sideways. They are the same service -- the shared
            # S3 Files, made clear by the single AWS Cloud boundary and the identical label; a
            # single centred hub forced the converging/diverging legs to run leftwards, which is
            # the direction the flow check (rightly) rejects.
            Node("sfi_fs1", "efs", "sfi_files", *centred("efs", 230, 440)),
            Node("sfi_fs2", "efs", "sfi_files", *centred("efs", 630, 440)),
        ),
        texts=(
            # The second finding, placed between the two clients where the eye reads it before
            # following either path down.
            TextBox("sfi_scale_note", "sfi_scale", 330, 150, 220, 70),
        ),
        edges=(
            Edge(
                "sfi_e1",
                "sfi_c1",
                "sfi_px1",
                "sfi_nfs",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
            ),
            Edge(
                "sfi_e2",
                "sfi_c2",
                "sfi_px2",
                "sfi_nfs",
                exit_at=(0.5, 1.0),
                entry_at=(0.5, 0.0),
            ),
            Edge(
                "sfi_e3", "sfi_px1", "sfi_fs1", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)
            ),
            Edge(
                "sfi_e4", "sfi_px2", "sfi_fs2", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)
            ),
            Edge(
                "sfi_e5", "sfi_fs1", "sfi_hp", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)
            ),
            Edge(
                "sfi_e6", "sfi_fs2", "sfi_bk", exit_at=(0.5, 1.0), entry_at=(0.5, 0.0)
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
    _s3files_internals(),
    _block_a_sessions(),
    _block_b_multipath(),
    _block_c_layout(),
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
        frame_style = resized(FRAME_STYLE, diagram.font_size)
        if frame.title_align_left:
            frame_style = frame_style.replace(
                "align=center;spacingTop=6;", "align=left;spacingTop=6;spacingLeft=16;"
            )
        vertex(
            frame.cid,
            label(frame.label, lang),
            frame_style,
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
        if edge.points or edge.label_offset != (0, 0):
            lines.append('          <mxGeometry relative="1" as="geometry">')
            if edge.points:
                lines.append('            <Array as="points">')
                lines += [
                    f'              <mxPoint x="{x}" y="{y}" />' for x, y in edge.points
                ]
                lines.append("            </Array>")
            if edge.label_offset != (0, 0):
                dx, dy = edge.label_offset
                lines.append(f'            <mxPoint as="offset" x="{dx}" y="{dy}" />')
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
