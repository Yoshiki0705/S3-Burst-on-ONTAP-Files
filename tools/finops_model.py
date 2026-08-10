#!/usr/bin/env python3
"""Generate the cost tables in `docs/ja/reference/comparison/finops-s3-vs-s3ap.md`.

Why this is a script and not arithmetic typed into the document.

The comparison needs roughly six scenarios with eight line items each, and every line item is a
product of a list price and an assumed usage figure. Typed into Markdown, that arithmetic is
unverifiable: a reader cannot tell a transcription slip from a modelling choice, and when a list
price changes there is no way to find which of the fifty-odd totals moved. Here the prices live in
one dated table with a source, the scenarios are declarations, and the totals are derived. When a
price changes, one line changes and `--check` reports every total that no longer matches the
document.

What this script is not. It is not a measurement. Every total is a model built on stated
assumptions about object size, retention, read multiplier, storage efficiency and provisioned
throughput. The list prices are real and sourced; the usage figures are illustrative. The document
labels them as 試算 for that reason, and the distinction is the point rather than a caveat.

Storage efficiency deserves particular care. AWS publishes "typical savings" of 65% for
general-purpose file sharing workloads, and that figure is used only where the workload plausibly
resembles that description. Pre-compressed media gets 0%, because deduplicating an already
compressed render output does not save anything and assuming otherwise would flatter the
architecture this repository proposes. Each scenario carries its own assumed rate so the choice is
visible rather than buried in a constant.

Prices are ap-northeast-1 list prices, on demand, excluding tax and any private pricing. They were
read from the AWS Price List API on the date in `PRICE_SNAPSHOT`. Re-read them with:

    python3 tools/finops_model.py --show-prices

Run:
    python3 tools/finops_model.py --write    # regenerate the block in the document
    python3 tools/finops_model.py --check    # fail if the document is stale
    python3 tools/finops_model.py            # print the block to stdout
"""

from __future__ import annotations

import argparse
import math
import re
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOC = ROOT / "docs" / "ja" / "reference" / "comparison" / "finops-s3-vs-s3ap.md"
BEGIN = "<!-- finops-model:begin -->"
END = "<!-- finops-model:end -->"

REGION = "ap-northeast-1"
REGION_LABEL = "アジアパシフィック (東京)"
PRICE_SNAPSHOT = "2026-08-09"

SOURCE_S3 = "https://aws.amazon.com/s3/pricing/"
SOURCE_FSX = "https://aws.amazon.com/fsx/netapp-ontap/pricing/"
SOURCE_DATASYNC = "https://aws.amazon.com/datasync/pricing/"
SOURCE_FLEXCACHE_FEATURES = "https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html"
SOURCE_FLEXCACHE_SIZING = (
    "https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html"
)
SOURCE_S3FILES_QUOTAS = (
    "https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html"
)

GIB_PER_TIB = 1024

# S3 Files metering minimums, from the metering reference.
# https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html
S3FILES_METADATA_KIB = 4.0  # metadata read/write minimum
S3FILES_MIN_IO_KIB = 32.0  # file read/write minimum per operation
S3FILES_MIN_FILE_KIB = 10.0  # minimum billable file size on high-performance storage
S3FILES_DEFAULT_THRESHOLD_KIB = (
    128.0  # files at or below this are held on high-perf storage
)
S3FILES_DEFAULT_EXPIRY_DAYS = 30.0  # unread data expires from high-perf storage
SECONDS_PER_MONTH = 30 * 24 * 3600


# --------------------------------------------------------------------------- prices


@dataclass(frozen=True)
class Rate:
    """One billable unit price, carried with the effective date AWS returned for it."""

    usd: float
    unit: str
    label: str
    effective: str
    source: str


# S3, effective 2026-08-01 (AmazonS3 offer publication 2026-08-07).
S3_STANDARD_TIERS: tuple[tuple[float, float], ...] = (
    (51_200.0, 0.025),  # first 50 TiB
    (512_000.0, 0.024),  # next 450 TB
    (math.inf, 0.023),  # beyond 500 TB
)

S3 = {
    "standard": Rate(
        0.025,
        "GB-Mo",
        "S3 Standard ストレージ (最初の 50 TiB)",
        "2026-08-01",
        SOURCE_S3,
    ),
    "standard_ia": Rate(
        0.0138, "GB-Mo", "S3 Standard-IA ストレージ", "2026-08-01", SOURCE_S3
    ),
    "onezone_ia": Rate(
        0.011, "GB-Mo", "S3 One Zone-IA ストレージ", "2026-08-01", SOURCE_S3
    ),
    "gir": Rate(
        0.005,
        "GB-Mo",
        "S3 Glacier Instant Retrieval ストレージ",
        "2026-08-01",
        SOURCE_S3,
    ),
    "int_fa": Rate(
        0.025, "GB-Mo", "S3 Intelligent-Tiering 頻繁アクセス層", "2026-08-01", SOURCE_S3
    ),
    "int_ia": Rate(
        0.0138,
        "GB-Mo",
        "S3 Intelligent-Tiering 低頻度アクセス層",
        "2026-08-01",
        SOURCE_S3,
    ),
    "int_aia": Rate(
        0.005,
        "GB-Mo",
        "S3 Intelligent-Tiering アーカイブインスタントアクセス層",
        "2026-08-01",
        SOURCE_S3,
    ),
    "tier1": Rate(
        0.0047 / 1000,
        "リクエスト",
        "S3 標準 PUT / COPY / POST / LIST",
        "2026-08-01",
        SOURCE_S3,
    ),
    "tier2": Rate(
        0.00037 / 1000,
        "リクエスト",
        "S3 標準 GET およびその他",
        "2026-08-01",
        SOURCE_S3,
    ),
    "ia_tier1": Rate(
        0.01 / 1000,
        "リクエスト",
        "S3 Standard-IA PUT / COPY / POST / LIST",
        "2026-08-01",
        SOURCE_S3,
    ),
    "ia_tier2": Rate(
        0.001 / 1000,
        "リクエスト",
        "S3 Standard-IA GET およびその他",
        "2026-08-01",
        SOURCE_S3,
    ),
    "ia_retrieval": Rate(
        0.01, "GB", "S3 Standard-IA 取り出し", "2026-08-01", SOURCE_S3
    ),
    "gir_retrieval": Rate(
        0.03, "GB", "S3 Glacier Instant Retrieval 取り出し", "2026-08-01", SOURCE_S3
    ),
    # Requests reaching an FSx for ONTAP volume through an S3 Access Point.
    "ap_tier1": Rate(
        0.00108 / 1000,
        "リクエスト",
        "S3 AP 経由 PUT / COPY / POST / LIST (FSx for ONTAP 宛)",
        "2026-08-01",
        SOURCE_S3,
    ),
    "ap_tier2": Rate(
        0.000029 / 1000,
        "リクエスト",
        "S3 AP 経由 GET およびその他 (FSx for ONTAP 宛)",
        "2026-08-01",
        SOURCE_S3,
    ),
}

# FSx for ONTAP, effective 2026-07-01 (AmazonFSx offer publication 2026-08-05).
FSX = {
    "ssd_saz": Rate(
        0.150,
        "GB-Mo",
        "SSD ストレージ Single-AZ (第一 / 第二世代)",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "ssd_maz": Rate(
        0.300,
        "GB-Mo",
        "SSD ストレージ Multi-AZ (第一 / 第二世代)",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "tput_saz1": Rate(
        0.906,
        "MBps-Mo",
        "スループットキャパシティ Single-AZ 第一世代",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "tput_saz2": Rate(
        2.013,
        "MBps-Mo",
        "スループットキャパシティ Single-AZ 第二世代",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "tput_maz1": Rate(
        1.511,
        "MBps-Mo",
        "スループットキャパシティ Multi-AZ 第一世代",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "tput_maz2": Rate(
        3.148,
        "MBps-Mo",
        "スループットキャパシティ Multi-AZ 第二世代",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "iops_saz": Rate(
        0.0204, "IOPS-Mo", "追加 SSD IOPS Single-AZ", "2026-07-01", SOURCE_FSX
    ),
    "iops_maz": Rate(
        0.0408, "IOPS-Mo", "追加 SSD IOPS Multi-AZ", "2026-07-01", SOURCE_FSX
    ),
    "pool_saz": Rate(
        0.0238,
        "GB-Mo",
        "キャパシティプールストレージ Single-AZ",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "pool_maz": Rate(
        0.0476,
        "GB-Mo",
        "キャパシティプールストレージ Multi-AZ",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "pool_read": Rate(
        0.00037 / 1000,
        "リクエスト",
        "キャパシティプール読み取りリクエスト",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "pool_write": Rate(
        0.0047 / 1000,
        "リクエスト",
        "キャパシティプール書き込みリクエスト",
        "2026-07-01",
        SOURCE_FSX,
    ),
    "backup": Rate(0.050, "GB-Mo", "バックアップストレージ", "2026-07-01", SOURCE_FSX),
}

# S3 Files, effective 2026-08-01. Three dimensions only; the Price List API returned no
# per-file-system or per-mount-target hourly charge for this Region.
S3FILES = {
    "storage": Rate(
        0.36,
        "GB-Mo",
        "S3 Files 高性能ストレージ (アクティブ分のみ)",
        "2026-08-01",
        SOURCE_S3,
    ),
    "read": Rate(0.04, "GB", "S3 Files データ読み取り", "2026-08-01", SOURCE_S3),
    "write": Rate(0.07, "GB", "S3 Files データ書き込み", "2026-08-01", SOURCE_S3),
}

DATASYNC = {
    "basic_gb": Rate(
        0.0125, "GB", "DataSync 転送 (Basic モード)", "2025-09-01", SOURCE_DATASYNC
    ),
    "enhanced_gb": Rate(
        0.015, "GB", "DataSync 転送 (Enhanced モード)", "2025-09-01", SOURCE_DATASYNC
    ),
    "enhanced_exec": Rate(
        0.55,
        "タスク実行",
        "DataSync タスク実行 (Enhanced モード)",
        "2025-09-01",
        SOURCE_DATASYNC,
    ),
}

# Deployment options, from the FSx for ONTAP user guide's generation comparison table.
# https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html
DEPLOYMENTS = {
    "saz1": {
        "label": "Single-AZ 第一世代",
        "api": "SINGLE_AZ_1",
        "ssd": FSX["ssd_saz"],
        "tput": FSX["tput_saz1"],
        "pool": FSX["pool_saz"],
        "tput_options": (128, 256, 512, 1024, 2048, 4096),
        "min_ssd_gib": 1024,
    },
    "maz1": {
        "label": "Multi-AZ 第一世代",
        "api": "MULTI_AZ_1",
        "ssd": FSX["ssd_maz"],
        "tput": FSX["tput_maz1"],
        "pool": FSX["pool_maz"],
        "tput_options": (128, 256, 512, 1024, 2048, 4096),
        "min_ssd_gib": 1024,
    },
    "saz2": {
        "label": "Single-AZ 第二世代",
        "api": "SINGLE_AZ_2",
        "ssd": FSX["ssd_saz"],
        "tput": FSX["tput_saz2"],
        "pool": FSX["pool_saz"],
        "tput_options": (384, 768, 1536, 3072, 6144),
        "min_ssd_gib": 1024,
    },
    "maz2": {
        "label": "Multi-AZ 第二世代",
        "api": "MULTI_AZ_2",
        "ssd": FSX["ssd_maz"],
        "tput": FSX["tput_maz2"],
        "pool": FSX["pool_maz"],
        "tput_options": (384, 768, 1536, 3072, 6144),
        "min_ssd_gib": 1024,
    },
}


# --------------------------------------------------------------------------- helpers


def usd(value: float) -> str:
    return f"${value:,.2f}"


def unit_usd(value: float) -> str:
    """Format a unit price without collapsing the small ones to $0.00."""
    if value == 0:
        return "$0"
    if value >= 0.01:
        return f"${value:,.4f}".rstrip("0").rstrip(".")
    return f"${value:.9f}".rstrip("0")


def per_1000(rate: Rate) -> str:
    return f"${rate.usd * 1000:,.6f}".rstrip("0").rstrip(".") + " / 1,000"


def gib(value: float) -> str:
    return f"{value:,.0f} GiB"


def tiered_s3_storage(gib_stored: float) -> float:
    """S3 Standard storage cost across its volume tiers."""
    remaining, total, floor = gib_stored, 0.0, 0.0
    for ceiling, price in S3_STANDARD_TIERS:
        band = min(remaining, ceiling - floor)
        if band <= 0:
            break
        total += band * price
        remaining -= band
        floor = ceiling
    return total


def choose_throughput(
    required_mbps: float, options: tuple[int, ...], headroom: float
) -> int:
    """Smallest offered tier that covers the sustained requirement plus burst headroom."""
    target = required_mbps * (1 + headroom)
    for option in options:
        if option >= target:
            return option
    return options[-1]


# --------------------------------------------------------------------------- scenarios


@dataclass
class Scenario:
    key: str
    title: str
    industry: str
    objects_per_month: int
    object_mib: float
    retention_months: float
    reads_per_object: float
    efficiency: float
    efficiency_note: str
    deployment: str
    pool_fraction: float
    file_protocol_required: bool
    notes: list[str] = field(default_factory=list)
    tput_headroom: float = 4.0
    ssd_headroom: float = 0.20
    # Months the S3 landing copy survives before a lifecycle rule expires it. 0.25 ≈ 7 days.
    landing_retention_months: float = 0.25
    # Cache size as a fraction of origin logical data. NetApp's documented best practice is at
    # least 10 percent, and 10 percent is also the create default, so 0.10 is the baseline here.
    cache_ratio: float = 0.10
    # A cache is rebuildable from the origin, which is why Single-AZ is defensible for it even
    # when the origin is Multi-AZ.
    cache_deployment: str = "saz1"
    # S3 Files needs the mount helper on Linux compute in AWS, so viability is a property of where
    # the consumer runs, not of the data. Stated per scenario rather than assumed.
    s3files_viable: bool = True
    s3files_reason: str = ""
    s3files_threshold_kib: float = S3FILES_DEFAULT_THRESHOLD_KIB
    s3files_expiration_days: float = S3FILES_DEFAULT_EXPIRY_DAYS

    @property
    def ingest_gib(self) -> float:
        return self.objects_per_month * self.object_mib / 1024

    @property
    def stored_gib(self) -> float:
        return self.ingest_gib * self.retention_months

    @property
    def reads_per_month(self) -> float:
        return self.objects_per_month * self.reads_per_object

    @property
    def cache_required_mbps(self) -> float:
        """Sustained read throughput the distribution site serves, in MB/s over the month."""
        return self.ingest_gib * 1024 * self.reads_per_object / SECONDS_PER_MONTH

    @property
    def required_mbps(self) -> float:
        """Sustained throughput implied by ingest plus reads, in MB/s averaged over the month."""
        moved_mib = self.ingest_gib * 1024 * (1 + self.reads_per_object)
        return moved_mib / SECONDS_PER_MONTH


def s3_only(sc: Scenario) -> dict[str, float] | None:
    """Everything in an S3 bucket, consumers speaking the S3 API."""
    if sc.file_protocol_required:
        return None
    return {
        "ストレージ (S3 Standard)": tiered_s3_storage(sc.stored_gib),
        "PUT リクエスト": sc.objects_per_month * S3["tier1"].usd,
        "GET リクエスト": sc.reads_per_month * S3["tier2"].usd,
    }


def fsx_component(sc: Scenario) -> dict[str, float]:
    """The file system the consumers read from.

    Identical in both file-protocol options. The tiering ratio, the storage efficiency and the
    provisioned throughput are properties of the workload and of how the volume is configured, not
    of how bytes arrived. Modelling the sync option without tiering would inflate it by the whole
    capacity pool discount and make this repository's architecture look better than it is.
    """
    dep = DEPLOYMENTS[sc.deployment]
    logical_ssd = sc.stored_gib * (1 - sc.pool_fraction)
    logical_pool = sc.stored_gib * sc.pool_fraction
    ssd = max(
        dep["min_ssd_gib"],
        math.ceil(logical_ssd * (1 - sc.efficiency) * (1 + sc.ssd_headroom)),
    )
    pool = logical_pool * (1 - sc.efficiency)
    tput = choose_throughput(sc.required_mbps, dep["tput_options"], sc.tput_headroom)

    lines = {
        f"SSD ストレージ ({gib(ssd)})": ssd * dep["ssd"].usd,
        f"スループットキャパシティ ({tput} MBps)": tput * dep["tput"].usd,
    }
    if sc.pool_fraction > 0:
        lines[f"キャパシティプールストレージ ({gib(pool)})"] = pool * dep["pool"].usd
        lines["キャパシティプール読み取りリクエスト"] = (
            sc.reads_per_month * sc.pool_fraction * FSX["pool_read"].usd
        )
    return lines


def s3_plus_sync(sc: Scenario) -> dict[str, float]:
    """The same file system, fed by an S3 landing bucket and a DataSync task.

    The landing bucket is assumed to hold each object only until the task has copied it and a
    lifecycle rule expires it, so its storage line is a fraction of a month rather than the full
    retention period. Organisations that keep the S3 copy as the archive of record pay the full
    retention instead, which widens the gap; the shorter assumption is used because it is the one
    less favourable to the architecture this repository proposes.
    """
    lines = dict(fsx_component(sc))
    landing_gib = sc.ingest_gib * sc.landing_retention_months
    list_calls = math.ceil(sc.objects_per_month / 1000)
    lines[f"ストレージ (S3 Standard、着信面 {gib(landing_gib)})"] = tiered_s3_storage(
        landing_gib
    )
    lines["PUT リクエスト (S3 バケット宛)"] = sc.objects_per_month * S3["tier1"].usd
    lines["GET / LIST リクエスト (同期の読み出し)"] = (
        sc.objects_per_month * S3["tier2"].usd + list_calls * S3["tier1"].usd
    )
    lines["DataSync 転送"] = sc.ingest_gib * DATASYNC["basic_gb"].usd
    return lines


def fsx_s3ap(sc: Scenario) -> dict[str, float]:
    """The same file system, written through an S3 Access Point. No second copy, no task."""
    lines = dict(fsx_component(sc))
    lines["PUT リクエスト (S3 AP 経由)"] = sc.objects_per_month * S3["ap_tier1"].usd
    return lines


def s3_files_option(sc: Scenario) -> dict[str, float] | None:
    """An S3 bucket read as a file system through S3 Files, with no FSx for ONTAP at all.

    The authoritative copy stays in the bucket, so S3 Standard is still paid in full. On top of
    that, S3 Files charges for the active fraction resident on its high-performance storage and for
    reads and writes against that storage.

    Object size decides almost everything. Files above the size threshold (default 128 KiB) are
    streamed straight from the bucket and incur no S3 Files storage charge at all, which makes large
    object workloads very cheap here. Files at or below it are imported onto high-performance
    storage at 0.36 USD per GB-month, which makes small object workloads expensive unless the
    expiration window is shortened. Both branches are modelled rather than assuming one.
    """
    if not sc.s3files_viable:
        return None

    object_kib = sc.object_mib * 1024
    metadata_gib = S3FILES_METADATA_KIB / (1024 * 1024)

    lines: dict[str, float] = {
        "ストレージ (S3 Standard、正典はバケットに残る)": tiered_s3_storage(
            sc.stored_gib
        ),
        "PUT リクエスト (S3 バケット宛)": sc.objects_per_month * S3["tier1"].usd,
    }

    if object_kib <= sc.s3files_threshold_kib:
        retention_days = sc.retention_months * 30.0
        active = min(1.0, sc.s3files_expiration_days / retention_days)
        # A file smaller than the minimum billable size is charged as that size.
        floor_factor = max(1.0, S3FILES_MIN_FILE_KIB / object_kib)
        hps_gib = sc.stored_gib * active * floor_factor
        io_kib = max(object_kib, S3FILES_MIN_IO_KIB)
        import_gib = sc.objects_per_month * io_kib / (1024 * 1024)
        # The first read of a file not yet on high-performance storage is streamed from the bucket
        # and carries an S3 GET plus a metadata read, with no file read charge. It is that read
        # which triggers the asynchronous import. Only the reads after it are served from
        # high-performance storage and metered as file reads.
        streamed_reads = float(sc.objects_per_month)
        hps_reads = max(0.0, sc.reads_per_month - streamed_reads)
        read_gib = hps_reads * io_kib / (1024 * 1024)

        lines[f"S3 Files 高性能ストレージ (アクティブ {active:.0%})"] = (
            hps_gib * S3FILES["storage"].usd
        )
        lines["GET リクエスト (初回読み出しはバケットからストリーム)"] = (
            streamed_reads * S3["tier2"].usd
        )
        lines["S3 Files 書き込み (高性能ストレージへの取り込み)"] = (
            import_gib + sc.objects_per_month * metadata_gib
        ) * S3FILES["write"].usd
        lines["S3 Files 読み取り (取り込み後の読み出しとメタデータ)"] = (
            read_gib + sc.reads_per_month * metadata_gib
        ) * S3FILES["read"].usd
    else:
        lines["GET リクエスト (バケットから直接ストリーム)"] = (
            sc.reads_per_month * S3["tier2"].usd
        )
        lines["S3 Files 書き込み (メタデータの取り込み)"] = (
            sc.objects_per_month * metadata_gib * S3FILES["write"].usd
        )
        lines["S3 Files 読み取り (メタデータ)"] = (
            sc.reads_per_month * metadata_gib * S3FILES["read"].usd
        )

    return lines


# ------------------------------------------------------------------ distribution site


def cache_component(sc: Scenario, ratio: float | None = None) -> dict[str, float]:
    """A FlexCache volume at the distribution site.

    Entirely on SSD. A cache volume cannot be tiered, so there is no capacity pool line here even
    when the origin has one. That constraint is what forces the cache to stay small, and staying
    small is what makes an all-SSD footprint affordable: the cache holds the working set, not the
    dataset. Sizing it like a copy and then discovering the SSD bill is the failure this models.
    """
    dep = DEPLOYMENTS[sc.cache_deployment]
    ratio = sc.cache_ratio if ratio is None else ratio
    logical = sc.stored_gib * ratio
    ssd = max(
        dep["min_ssd_gib"],
        math.ceil(logical * (1 - sc.efficiency) * (1 + sc.ssd_headroom)),
    )
    tput = choose_throughput(
        sc.cache_required_mbps, dep["tput_options"], sc.tput_headroom
    )
    return {
        f"SSD ストレージ ({gib(ssd)}、階層化不可)": ssd * dep["ssd"].usd,
        f"スループットキャパシティ ({tput} MBps)": tput * dep["tput"].usd,
    }


def full_copy_component(sc: Scenario) -> dict[str, float]:
    """A full second copy at the same site instead of a cache.

    This is a normal volume, so it can tier. Modelling it as all-SSD would overstate the gap;
    the honest comparison gives the copy its capacity pool discount and still asks what the
    remaining difference is.
    """
    dep = DEPLOYMENTS[sc.cache_deployment]
    logical_ssd = sc.stored_gib * (1 - sc.pool_fraction)
    logical_pool = sc.stored_gib * sc.pool_fraction
    ssd = max(
        dep["min_ssd_gib"],
        math.ceil(logical_ssd * (1 - sc.efficiency) * (1 + sc.ssd_headroom)),
    )
    pool = logical_pool * (1 - sc.efficiency)
    tput = choose_throughput(
        sc.cache_required_mbps, dep["tput_options"], sc.tput_headroom
    )
    lines = {
        f"SSD ストレージ ({gib(ssd)})": ssd * dep["ssd"].usd,
        f"スループットキャパシティ ({tput} MBps)": tput * dep["tput"].usd,
    }
    if sc.pool_fraction > 0:
        lines[f"キャパシティプールストレージ ({gib(pool)})"] = pool * dep["pool"].usd
    return lines


SCENARIOS: list[Scenario] = [
    Scenario(
        key="telemetry",
        title="車載 / IoT テレメトリ — 小オブジェクト高頻度",
        industry="自動車、製造、IoT",
        objects_per_month=300_000_000,
        object_mib=0.0625,  # 64 KiB
        retention_months=1.0,
        reads_per_object=2.0,
        efficiency=0.65,
        efficiency_note="テキスト / JSON 主体。AWS が汎用ファイル共有の典型として公表する 65% を当てる",
        deployment="saz1",
        pool_fraction=0.0,
        file_protocol_required=False,
        s3files_viable=True,
        s3files_reason="解析処理を AWS 側の Linux コンピュートで動かす前提。マウントヘルパーを入れられる",
        notes=[
            "3 億オブジェクト / 月 (1 日あたり 1,000 万) を 64 KiB で受ける",
            "利用側が S3 API を話せる場合を想定し、S3 単独も参考として並べる。"
            "NFS / SMB が要るなら S3 単独は選択肢から外れる",
        ],
    ),
    Scenario(
        key="hil",
        title="HiL テストベンチ — 走行ログを装置へ配る",
        industry="自動車 (AV / ADAS)",
        objects_per_month=20_000_000,
        object_mib=1.0,
        retention_months=2.0,
        reads_per_object=1.5,
        efficiency=0.50,
        efficiency_note="一部が既圧縮の混在データ。汎用ファイル共有の 65% より保守的に置く",
        deployment="saz1",
        pool_fraction=0.30,
        file_protocol_required=True,
        s3files_viable=False,
        s3files_reason="テストベンチは構成を変えられない物理機器で、AWS 外にある。マウントヘルパーを入れられない",
        notes=[
            "テストベンチは NFS / SMB マウントしか話さない。S3 単独は要件を満たさない",
            "3 割は再読み出し頻度が低くキャパシティプールへ落ちるものとして置く",
        ],
    ),
    Scenario(
        key="eda",
        title="EDA / CAE — バースト読み出し、メタデータ操作が多い",
        industry="半導体、製造",
        objects_per_month=60_000_000,
        object_mib=0.25,  # 256 KiB
        retention_months=3.0,
        reads_per_object=4.0,
        efficiency=0.65,
        efficiency_note="ソースとネットリストが主体で重複が多い。汎用ファイル共有の 65% を当てる",
        deployment="saz2",
        pool_fraction=0.40,
        file_protocol_required=True,
        s3files_viable=True,
        s3files_reason="ツールチェーンを AWS の EC2 Linux で動かす前提。オンプレミスのファームに残す場合は選べない",
        notes=[
            "ツールチェーンが POSIX セマンティクスを要求する。S3 単独は要件を満たさない",
            "第二世代を選ぶ理由は単価ではなく上限 (SSD 512 TiB、200,000 IOPS)",
        ],
    ),
    Scenario(
        key="media",
        title="メディア / レンダリング — 大オブジェクト、リクエストは少ない",
        industry="メディア、エンターテインメント",
        objects_per_month=50_000,
        object_mib=500.0,
        retention_months=3.0,
        reads_per_object=3.0,
        efficiency=0.0,
        efficiency_note="既に圧縮された素材。重複排除と圧縮の効果は見込まない",
        deployment="saz1",
        pool_fraction=0.80,
        file_protocol_required=True,
        s3files_viable=True,
        s3files_reason="レンダリングノードが AWS の EC2 Linux である前提。Windows ベースの工程や SMB が要る場合は選べない",
        notes=[
            "レンダリングノードは NFS マウント。S3 単独は要件を満たさない",
            "リクエスト単価の差はほぼ効かない。効くのはスループットとストレージ",
        ],
    ),
    Scenario(
        key="genomics",
        title="ゲノム解析 — シーケンサー出力を HPC へ",
        industry="ライフサイエンス、研究",
        objects_per_month=2_000_000,
        object_mib=8.0,
        retention_months=6.0,
        reads_per_object=2.0,
        efficiency=0.30,
        efficiency_note="FASTQ / BAM は部分的に圧縮済み。保守的に 30% を置く",
        deployment="saz1",
        pool_fraction=0.70,
        file_protocol_required=True,
        s3files_viable=True,
        s3files_reason="HPC クラスタを AWS の EC2 Linux で動かす前提",
        notes=[
            "HPC クラスタは NFS マウント。S3 単独は要件を満たさない",
            "長期保持が効くため、キャパシティプールへの階層化が最大のレバーになる",
        ],
    ),
]


# --------------------------------------------------------------------------- rendering


def table(headers: list[str], rows: list[list[str]]) -> list[str]:
    out = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join(["---"] * len(headers)) + "|",
    ]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


def render_prices() -> list[str]:
    out = [
        "### 単価表",
        "",
        f"{REGION_LABEL} (`{REGION}`)、オンデマンド、税別。"
        f"AWS Price List API から {PRICE_SNAPSHOT} に取得したもので、`effective` は API が返した適用開始日である。",
        "",
    ]
    rows = []
    for group, rates in (("S3", S3), ("FSx for ONTAP", FSX), ("DataSync", DATASYNC)):
        for rate in rates.values():
            shown = (
                per_1000(rate)
                if rate.unit == "リクエスト"
                else f"{unit_usd(rate.usd)} / {rate.unit}"
            )
            rows.append([group, rate.label, shown, rate.effective])
    out += table(["サービス", "課金項目", "単価", "effective"], rows)
    out += [
        "",
        "S3 Standard のストレージ単価は使用量で段階が変わる"
        f" (最初の 50 TiB {unit_usd(0.025)}、次の 450 TB {unit_usd(0.024)}、500 TB 超 {unit_usd(0.023)} / GB-Mo)。"
        "以下の試算はこの段階を反映している。",
        "",
    ]
    return out


def render_request_asymmetry() -> list[str]:
    put_ratio = S3["tier1"].usd / S3["ap_tier1"].usd
    get_ratio = S3["tier2"].usd / S3["ap_tier2"].usd
    ia_put_ratio = S3["ia_tier1"].usd / S3["ap_tier1"].usd
    rows = [
        [
            "PUT / COPY / POST / LIST",
            per_1000(S3["tier1"]),
            per_1000(S3["ap_tier1"]),
            f"{put_ratio:.2f} 倍",
        ],
        [
            "GET およびその他",
            per_1000(S3["tier2"]),
            per_1000(S3["ap_tier2"]),
            f"{get_ratio:.2f} 倍",
        ],
    ]
    return [
        "### リクエスト単価の非対称",
        "",
        "同じ API 操作でも、宛先が S3 バケットか FSx for ONTAP ボリュームかで単価が違う。",
        "",
        *table(
            [
                "操作",
                "S3 バケット宛",
                "S3 AP 経由 (FSx for ONTAP 宛)",
                "S3 バケット宛が何倍か",
            ],
            rows,
        ),
        "",
        f"低頻度アクセス層を選ぶと逆に開く。S3 Standard-IA の PUT は {per_1000(S3['ia_tier1'])} で、"
        f"S3 AP 経由の {ia_put_ratio:.1f} 倍にあたる。"
        "保存単価を下げる目的で階層を落とすと、書き込みが多いワークロードではリクエスト側で戻ってくる。",
        "",
    ]


def render_floor() -> list[str]:
    rows = []
    for dep in DEPLOYMENTS.values():
        min_tput = dep["tput_options"][0]
        ssd_cost = dep["min_ssd_gib"] * dep["ssd"].usd
        tput_cost = min_tput * dep["tput"].usd
        rows.append(
            [
                dep["label"],
                f"`{dep['api']}`",
                gib(dep["min_ssd_gib"]),
                f"{min_tput} MBps",
                usd(ssd_cost),
                usd(tput_cost),
                f"**{usd(ssd_cost + tput_cost)}**",
            ]
        )
    return [
        "### 固定費の下限",
        "",
        "S3 バケットに下限はない。1 バイトも置かなければ請求は発生しない。"
        "FSx for ONTAP は SSD 1 TiB とスループットキャパシティ 1 段が最小構成で、"
        "使用量に関わらずこの分が毎月かかる。",
        "",
        *table(
            [
                "デプロイ",
                "API 値",
                "最小 SSD",
                "最小スループット",
                "SSD 分",
                "スループット分",
                "月額下限",
            ],
            rows,
        ),
        "",
        "第二世代の最小スループットは 384 MBps で、第一世代の 128 MBps より 3 段上にあたる。"
        "第二世代を選ぶ理由は MBps あたりの単価ではなく、"
        "SSD 512 TiB、200,000 IOPS、Single-AZ で最大 12 HA ペアという上限の側にある"
        "([世代の比較](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html))。"
        "上限に用がないワークロードで第二世代を選ぶと、使わない余力に払うことになる。",
        "",
    ]


def render_object_size_sensitivity() -> list[str]:
    sizes_kib = (8, 32, 64, 128, 256, 1024, 8192)
    rows = []
    for kib in sizes_kib:
        objects_per_gib = 1024 * 1024 / kib
        s3_put = objects_per_gib * S3["tier1"].usd
        ap_put = objects_per_gib * S3["ap_tier1"].usd
        rows.append(
            [
                f"{kib:,} KiB",
                f"{objects_per_gib:,.0f}",
                unit_usd(s3_put),
                unit_usd(ap_put),
                f"{s3_put / S3['standard'].usd:.1f} 倍",
            ]
        )
    crossover_mib = S3["tier1"].usd * 1024 / S3["standard"].usd
    return [
        "### オブジェクトサイズが効く理由",
        "",
        "リクエスト課金は容量ではなく回数にかかる。"
        "同じ 1 GiB を書くとき、オブジェクトが小さいほど回数が増え、リクエスト課金が保存料金を追い越す。",
        "",
        *table(
            [
                "平均オブジェクトサイズ",
                "1 GiB あたりの PUT 回数",
                "S3 バケット宛の PUT / GiB",
                "S3 AP 経由の PUT / GiB",
                "S3 の PUT が S3 Standard 1 か月保存料の何倍か",
            ],
            rows,
        ),
        "",
        f"平均オブジェクトサイズが約 {crossover_mib * 1024:,.0f} KiB を下回ると、"
        "S3 バケットへの PUT 料金が S3 Standard の 1 か月分の保存料金を超える。"
        "小さいオブジェクトを高頻度で書く収集系では、保存単価ではなくリクエスト単価が支配項になる。",
        "",
    ]


def render_scenario(sc: Scenario) -> list[str]:
    dep = DEPLOYMENTS[sc.deployment]
    options: list[tuple[str, dict[str, float] | None]] = [
        ("S3 単独 (利用側も S3 API)", s3_only(sc)),
        ("S3 バケット + DataSync + FSx for ONTAP", s3_plus_sync(sc)),
        ("FSx for ONTAP S3 AP (この構成)", fsx_s3ap(sc)),
    ]

    out = [
        f"#### {sc.title}",
        "",
        f"想定業種: {sc.industry}",
        "",
        *table(
            ["前提", "値"],
            [
                ["月間オブジェクト数", f"{sc.objects_per_month:,}"],
                ["平均オブジェクトサイズ", f"{sc.object_mib * 1024:,.0f} KiB"],
                ["月間書き込み量", gib(sc.ingest_gib)],
                ["保持期間", f"{sc.retention_months:g} か月"],
                ["定常保存量 (論理)", gib(sc.stored_gib)],
                ["1 オブジェクトあたり読み出し回数", f"{sc.reads_per_object:g}"],
                ["ストレージ効率の仮定", f"{sc.efficiency:.0%} — {sc.efficiency_note}"],
                ["デプロイ", f"{dep['label']} (`{dep['api']}`)"],
                ["平均所要スループット", f"{sc.required_mbps:,.1f} MB/s"],
                ["キャパシティプールへ落とす割合", f"{sc.pool_fraction:.0%}"],
                [
                    "スループットの余裕",
                    f"平均所要の {sc.tput_headroom + 1:g} 倍を満たす最小の段を選ぶ",
                ],
                [
                    "SSD のプロビジョニング余裕",
                    f"効率適用後の {sc.ssd_headroom:.0%} 増し",
                ],
                [
                    "着信面 (S3) の保持期間",
                    f"{sc.landing_retention_months:g} か月 — 同期後にライフサイクルで失効させる想定",
                ],
                [
                    "利用側がファイルプロトコルを要求するか",
                    "はい" if sc.file_protocol_required else "いいえ",
                ],
            ],
        ),
        "",
    ]
    for note in sc.notes:
        out.append(f"- {note}")
    out.append("")

    totals: dict[str, float] = {}
    for label, lines in options:
        if lines is None:
            out += [f"**{label}**: 要件を満たさないため試算しない。", ""]
            continue
        total = sum(lines.values())
        totals[label] = total
        rows = [[item, usd(cost)] for item, cost in lines.items()]
        rows.append(["**合計 (月額)**", f"**{usd(total)}**"])
        rows.append(["論理 1 GiB あたり", unit_usd(total / sc.stored_gib)])
        out += [f"**{label}**", "", *table(["内訳", "月額"], rows), ""]

    ap_label = "FSx for ONTAP S3 AP (この構成)"
    sync_label = "S3 バケット + DataSync + FSx for ONTAP"
    if ap_label in totals and sync_label in totals:
        delta = totals[sync_label] - totals[ap_label]
        pct = delta / totals[sync_label] * 100
        direction = "下回る" if delta > 0 else "上回る"

        # Name the dominant term rather than reciting the same three causes every time. Which one
        # dominates changes with object size, and that change is the finding.
        shared = fsx_component(sc)
        contributions = {k: v for k, v in s3_plus_sync(sc).items() if k not in shared}
        contributions["PUT リクエスト (S3 AP 経由) の節約"] = -(
            sc.objects_per_month * S3["ap_tier1"].usd
        )
        top = max(contributions.items(), key=lambda kv: abs(kv[1]))
        top_share = abs(top[1]) / abs(delta) * 100 if delta else 0.0

        out += [
            f"同期ジョブを挟む構成と比べ、この構成は月額 {usd(abs(delta))} "
            f"({abs(pct):.0f}%) {direction}。"
            f"差の最大項は「{top[0]}」で、差の {top_share:.0f}% を占める。",
            "",
        ]
    return out


def render_cache_site() -> list[str]:
    """The distribution side, which the origin-only tables leave out entirely."""
    burst = [sc for sc in SCENARIOS if sc.file_protocol_required]

    rows = []
    for sc in burst:
        cache = sum(cache_component(sc).values())
        cache_20 = sum(cache_component(sc, 0.20).values())
        copy_total = sum(full_copy_component(sc).values())
        dep = DEPLOYMENTS[sc.cache_deployment]
        cache_ssd_gib = max(
            dep["min_ssd_gib"],
            math.ceil(
                sc.stored_gib
                * sc.cache_ratio
                * (1 - sc.efficiency)
                * (1 + sc.ssd_headroom)
            ),
        )
        floored = cache_ssd_gib == dep["min_ssd_gib"]
        rows.append(
            [
                sc.title.split(" — ")[0],
                gib(sc.stored_gib),
                gib(cache_ssd_gib) + ("(下限に張り付き)" if floored else ""),
                usd(cache),
                usd(cache_20),
                usd(copy_total),
                f"{copy_total / cache:.1f} 倍" if cache else "—",
            ]
        )

    out = [
        "### 配布側 — フル SSD の Cache ボリューム",
        "",
        "ここまでの試算は収集側 (Origin) だけを見ている。"
        "この構成は配布側に FlexCache の Cache ボリュームを置くので、その分が別に載る。",
        "",
        "Cache ボリュームには階層化ができない。"
        "ONTAP の仕様として、FabricPool の Origin を Cache することはできるが"
        "**Cache ボリューム自体は階層化されない** "
        f"([対応機能一覧]({SOURCE_FLEXCACHE_FEATURES}))。"
        "したがって Cache は全量が SSD に載る。",
        "",
        "それが成立するのは Cache が疎だからである。FlexCache は Origin の全データを複製せず、"
        "実際に読まれたブロックだけを保持する。"
        f"NetApp のサイジング指針は Origin の**最低 10%**を推奨し、作成時の既定値も 10% である"
        f" ([サイジング指針]({SOURCE_FLEXCACHE_SIZING}))。"
        "読み取り中心のワークロードでは 5〜15% に収める運用が一般的で、"
        "この帯であれば全量 SSD でも費用が成り立つ。",
        "",
        f"以下は Cache 比率を {burst[0].cache_ratio:.0%} に置いた場合の配布側の月額と、"
        "同じ場所に全量コピーを置いた場合の比較である。"
        "全量コピーは通常のボリュームなので階層化できるものとして計算している。"
        "全量 SSD として計算すれば差はさらに開くが、それは比較として不当なので採らない。",
        "",
        *table(
            [
                "ワークロード",
                "Origin 論理",
                "Cache SSD (効率適用後、10%)",
                "Cache 10% の月額",
                "Cache 20% の月額",
                "全量コピーの月額",
                "コピーが何倍か",
            ],
            rows,
        ),
        "",
        "差が小さく出るのは、Origin の階層化割合が大きいワークロードである。"
        "コピー側もキャパシティプールに落とせるため、SSD 単価の差が効きにくくなる。"
        "逆にホットなデータが多いワークロードでは、コピー側も SSD に置くことになり差が開く。",
        "",
    ]

    # How the cost moves with the ratio, on the workload where the ratio has the most room.
    pick = max(burst, key=lambda s: s.stored_gib)
    ratio_rows = []
    for ratio in (0.10, 0.15, 0.20, 0.25, 0.50, 1.00):
        dep = DEPLOYMENTS[pick.cache_deployment]
        ssd = max(
            dep["min_ssd_gib"],
            math.ceil(
                pick.stored_gib
                * ratio
                * (1 - pick.efficiency)
                * (1 + pick.ssd_headroom)
            ),
        )
        total = sum(cache_component(pick, ratio).values())
        note = "サイジング指針の下限、かつ作成時の既定値" if ratio == 0.10 else ""
        if ratio == 0.20:
            note = "作業セットが読みきれないときの比較用"
        if ratio == 1.00:
            note = "実質的にコピー。階層化できないぶんコピーより高い"
        ratio_rows.append([f"{ratio:.0%}", gib(ssd), usd(total), note])

    out += [
        f"Cache 比率を動かしたときの月額を、Origin 論理が最大の"
        f"「{pick.title.split(' — ')[0]}」({gib(pick.stored_gib)}) で示す。",
        "",
        *table(["Cache 比率", "Cache SSD", "Cache の月額", "備考"], ratio_rows),
        "",
        "比率 100% は成立しない選択である。階層化できない Cache に全量を置くと、"
        "階層化できる通常のボリュームに全量コピーを置くより高くつく。"
        "Cache を「コピーの代わり」として全量でサイジングすると、この領域に入る。",
        "",
    ]
    return out


def render_whole_system() -> list[str]:
    """The three delivery options at a single site, with no cache in any of them.

    An earlier version of this table added a FlexCache to the DataSync option as well, which was
    wrong. Copying from a bucket into an FSx for ONTAP file system produces a file system that
    already serves NFS and SMB; nothing is left for a cache to do. A cache earns its cost only when
    the consumers sit somewhere other than the file system, and in that case the DataSync
    alternative is a full copy at that site rather than a cache. The per-site comparison for that
    case is the cache table above; this table is the single-site case, where every option is one
    file system or none.
    """
    rows = []
    for sc in SCENARIOS:
        sync_total = sum(s3_plus_sync(sc).values())
        ap_total = sum(fsx_s3ap(sc).values())
        files = s3_files_option(sc)
        files_cell = usd(sum(files.values())) if files else "要件を満たさない"
        rows.append(
            [
                sc.title.split(" — ")[0],
                f"{sc.object_mib * 1024:,.0f} KiB",
                usd(sync_total),
                usd(ap_total),
                files_cell,
            ]
        )

    out = [
        "### 3 つの選択肢を並べる — 収集と利用が同じ場所の場合",
        "",
        "ここでは配布側を足さない。**バケットから DataSync で FSx for ONTAP にコピーすれば、"
        "その FSx for ONTAP 自体が NFS / SMB で読み書きできるので、Cache を置く理由がない。**"
        "Cache が費用に見合うのは、利用側がファイルシステムと別の場所にいる場合だけである。"
        "その場合の比較は Cache と全量コピーの対比（上の表）になる。"
        "この表は 3 案がいずれもファイルシステム 1 つ、または 0 つで済む単一サイトの比較である。",
        "",
        "この表は「利用側にファイルとして配る」ことを前提にした比較である。"
        "利用側が S3 API で足りるなら配布層そのものが不要で、"
        "各ワークロードの試算にある S3 単独の金額が下限になる。",
        "",
        "3 列目の S3 Files は、S3 バケットをファイルシステムとしてマウントする選択肢である。"
        "FSx for ONTAP を持たないため固定費の下限がなく、正典はバケットに残る。"
        "対応プロトコルは NFSv4.1 と NFSv4.2 で、**NFSv3 と SMB は対象外**である"
        f" ([非対応事項とクォータ]({SOURCE_S3FILES_QUOTAS}))。"
        "EC2 では S3 Files のマウントヘルパー (`amazon-efs-utils` に含まれる) が必要で、"
        "`s3files` というファイルシステムタイプでマウントする"
        " ([マウント手順](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html))。"
        "対応するコンピュートは EC2、Lambda、EKS、ECS である"
        " ([S3 Files の概要](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html))。"
        "費用だけでは決められない仕様上の制約が複数あるので、"
        "この表の金額は後述の[S3 Files を選ぶ場合の仕様](#s3-files-を選ぶ場合の仕様)と併せて読む。",
        "",
        *table(
            [
                "ワークロード",
                "平均オブジェクト",
                "S3 + DataSync + FSx for ONTAP",
                "FSx for ONTAP S3 AP (この構成)",
                "S3 + S3 Files",
            ],
            rows,
        ),
        "",
        "オブジェクトサイズで結果が反転する。"
        f"S3 Files は既定のしきい値 ({S3FILES_DEFAULT_THRESHOLD_KIB:,.0f} KiB) を超えるファイルを"
        "高性能ストレージに載せず、バケットから直接ストリームする。"
        "ストレージ課金が発生しないので、大きいオブジェクトを読むワークロードでは安い。"
        "しきい値以下のファイルは高性能ストレージに取り込まれ、"
        f"{unit_usd(S3FILES['storage'].usd)} / GB-Mo が効くので、小さいオブジェクトでは高くつく。",
        "",
        "大きいオブジェクトの行で S3 Files の金額がほぼ S3 Standard の保存料金に見えるのは、"
        "計上漏れではなく設計どおりである。1 MiB 以上の読み出しは高性能ストレージを経由せず"
        "バケットから直接ストリームされ、ファイルシステム側のデータ課金が発生しない。"
        "残るのは S3 の GET リクエストと 4 KiB のメタデータ読み取りだけで、"
        "オブジェクトが大きければ回数が少ないため金額に出ない。"
        "S3 の GET と PUT はどの行でも計上している。",
        "",
        "**配布サイトを増やしたときの増え方は 3 案で違う。**"
        "この構成は Origin 1 つに対してサイトごとに Cache を足すので、"
        "1 サイトあたり Origin 論理の 1 割程度で増える。"
        "DataSync 方式はサイトごとに全量コピーを置くので、1 サイトあたり全量で増える。"
        "S3 Files はファイルシステムあたり 1 VPC なのでサイトごとにファイルシステムを作るが、"
        "同じバケットに複数のファイルシステムを付けられ、"
        "課金されるのは各ファイルシステムが実際に使った分だけである。"
        "サイト数が増えるほど全量コピー方式が不利になる。",
        "",
        "S3 Files が安く出るワークロードで、それでもこの構成を選ぶ理由は費用ではない。"
        "利用側が構成を変えられない装置である、SMB が要る、AWS 外にいる、"
        "ONTAP のデータ管理機能を収集直後のデータに効かせたい、といった要件の側にある。"
        "費用だけで選ぶなら、その要件がない限り S3 Files のほうが合う場面がある。",
        "",
    ]

    # The two tunables that move the S3 Files figure most, on the workload where they bind.
    small = [
        sc for sc in SCENARIOS if sc.object_mib * 1024 <= S3FILES_DEFAULT_THRESHOLD_KIB
    ]
    if small:
        sc = small[0]
        sweep = []
        for days in (1, 3, 7, 30, 90):
            variant = replace(sc, s3files_expiration_days=float(days))
            total = sum(s3_files_option(variant).values())
            retention_days = sc.retention_months * 30.0
            active = min(1.0, days / retention_days)
            sweep.append(
                [
                    f"{days} 日",
                    f"{active:.0%}",
                    usd(total),
                    "既定値" if days == 30 else "",
                ]
            )
        out += [
            f"小さいオブジェクトの場合、高性能ストレージの有効期限が最大のレバーになる。"
            f"「{sc.title.split(' — ')[0]}」で期限を振ると次のようになる"
            "(既定は 30 日、設定可能な範囲は 1 日から 365 日)。",
            "",
            *table(
                ["有効期限", "アクティブ割合", "S3 + S3 Files の月額", "備考"], sweep
            ),
            "",
            "期限を詰めれば下がるが、期限外のファイルを読むとバケットからの取り込みが再度発生する。"
            "読み取りの時間的な偏りが小さいワークロードでは、期限を詰めても取り込みの往復で戻ってくる。",
            "",
            "しきい値のほうも同じ構造を持つ。"
            "しきい値を上げれば小さくないファイルも低レイテンシで読めるが、"
            "その分が高性能ストレージの課金対象になる。"
            "この列の安さは、しきい値を超えるファイルが S3 のレイテンシで読まれることと引き換えである。",
            "",
        ]
    return out


def render_marginal_cost() -> list[str]:
    """The case this repository actually addresses: the file system already exists."""
    sc = next(s for s in SCENARIOS if s.key == "telemetry")
    shared = fsx_component(sc)
    ap_incremental = sum(v for k, v in fsx_s3ap(sc).items() if k not in shared)
    alt_incremental = sum(v for k, v in s3_plus_sync(sc).items() if k not in shared)
    return [
        "### 既に FSx for ONTAP がある場合の増分",
        "",
        "この構成が対象とする状況では、利用側が NFS / SMB を要求するため FSx for ONTAP は既にある。"
        "そこに S3 の受け口を足すときの比較は、"
        "グリーンフィールドの「S3 か FSx for ONTAP か」ではなく「増分としてどちらが安いか」になる。",
        "",
        f"前提は上の「{SCENARIOS[0].title}」と同じ (3 億オブジェクト / 月、64 KiB)。"
        "SSD とスループットは既存ワークロードのために既に払っているものとして、増分だけを並べる。",
        "",
        *table(
            ["増分", "内訳", "月額"],
            [
                ["S3 AP を足す", "S3 AP 経由 PUT のみ", usd(ap_incremental)],
                [
                    "S3 バケットと同期ジョブを足す",
                    "S3 保存 + S3 PUT + 同期の読み出し GET + DataSync 転送",
                    usd(alt_incremental),
                ],
                ["差", "", f"**{usd(alt_incremental - ap_incremental)}**"],
            ],
        ),
        "",
        "S3 AP はアクセスポイント自体に時間課金がないため、増分はリクエスト課金に集約される。"
        "同期ジョブ側の増分には、同じバイト列を 2 系統で持つ保存料金が含まれる。"
        "この差は容量が増えても縮まらない。",
        "",
    ]


def render() -> str:
    out = [
        BEGIN,
        "",
        "<!-- 生成物。編集しない。tools/finops_model.py で再生成する -->",
        "",
        *render_prices(),
        *render_request_asymmetry(),
        *render_floor(),
        *render_object_size_sensitivity(),
        "### ユースケース別の試算",
        "",
        "いずれも**試算**であり実測ではない。単価は上の単価表、使用量は各表の前提に置いた仮定である。",
        "自分のワークロードで置き換えるべき値は、月間オブジェクト数、平均オブジェクトサイズ、"
        "保持期間、読み出し回数、ストレージ効率の 5 つ。",
        "",
    ]
    for sc in SCENARIOS:
        out += render_scenario(sc)
    out += render_cache_site()
    out += render_whole_system()
    out += render_marginal_cost()
    out += [END]
    return "\n".join(out).rstrip() + "\n"


# --------------------------------------------------------------------------- entry


def show_prices() -> None:
    print(f"# {REGION} list prices, snapshot {PRICE_SNAPSHOT}")
    for group, rates in (("S3", S3), ("FSX", FSX), ("DATASYNC", DATASYNC)):
        for key, rate in rates.items():
            print(
                f"{group:9} {key:16} {rate.usd:<14.10g} {rate.unit:12} effective {rate.effective}"
            )


def splice(text: str, block: str) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(f"{DOC}: markers {BEGIN} / {END} not found")
    return pattern.sub(block.rstrip("\n"), text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--write", action="store_true", help="regenerate the block in the document"
    )
    parser.add_argument(
        "--check", action="store_true", help="fail if the document is stale"
    )
    parser.add_argument(
        "--show-prices", action="store_true", help="print the price table"
    )
    args = parser.parse_args()

    if args.show_prices:
        show_prices()
        return 0

    block = render()

    if not (args.write or args.check):
        print(block, end="")
        return 0

    if not DOC.exists():
        raise SystemExit(f"{DOC}: not found")
    original = DOC.read_text(encoding="utf-8")
    updated = splice(original, block)

    if args.write:
        if updated != original:
            DOC.write_text(updated, encoding="utf-8")
            print(f"finops-model: rewrote {DOC.relative_to(ROOT)}")
        else:
            print("finops-model: already current")
        return 0

    if updated != original:
        print(
            "finops-model: generated cost tables are stale.\n"
            "  Run: python3 tools/finops_model.py --write",
            file=sys.stderr,
        )
        return 1
    print("finops-model: current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
