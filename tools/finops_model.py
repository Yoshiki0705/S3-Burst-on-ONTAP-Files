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
import json
import math
import re
import sys
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from pathlib import Path

from finops_translations import TRANSLATIONS as FINOPS_TRANSLATIONS

ROOT = Path(__file__).resolve().parent.parent
BEGIN = "<!-- finops-model:begin -->"
END = "<!-- finops-model:end -->"

LANGS = ("ja", "en")
SUBPATH = Path("reference") / "comparison" / "finops-s3-vs-s3ap.md"


def doc_for(lang: str) -> Path:
    return ROOT / "docs" / lang / SUBPATH


# --------------------------------------------------------------------------- language
#
# The generated block carries headings, so the English document cannot simply reuse the Japanese one:
# `make i18n-check` compares heading structure between a pair, which means the block has to be
# generated in each language. Hand-maintaining an English copy of it was the alternative and was
# rejected — 723 of the document's lines are generated, so the two copies would diverge the first
# time a unit price moved, which is the failure this script exists to prevent.
#
# The current language is module state rather than a parameter threaded through every function. There
# are twenty-odd render functions and rendering is sequential and single-threaded, so the parameter
# would be noise at every call site while buying nothing. `render()` sets it and is the only entry.

_LANG = "ja"

# Keyed by the Japanese source text. Inventing key names for six hundred strings would add a second
# thing to keep in step; the Japanese string is already unique and already at the call site. The cost
# is that rewording the Japanese orphans its translation — which `translation_gaps()` reports, so it
# fails loudly rather than silently emitting Japanese into the English document.
#
# The table itself lives in `finops_translations.py`. It is data, it is reviewed as a unit, and at
# several hundred entries it would sit between this file's language section and its price constants —
# the two things a reader auditing the arithmetic came here for.
TRANSLATIONS: dict[str, str] = FINOPS_TRANSLATIONS

CJK = re.compile(r"[\u3000-\u30ff\u4e00-\u9fff]")


def t(ja: str, **fmt: object) -> str:
    """Return `ja` in the current language, with `fmt` applied after translation.

    Interpolation happens after the lookup so that the placeholders, not the interpolated values,
    are what gets translated. Formatting a value into the string first would make every distinct
    number a distinct key.

    A string with no Japanese in it is returned as it is rather than looked up. The source language
    is Japanese, so a source string without a Japanese character — `S3 Standard-IA GET`, `128 MBps`,
    a unit like `GB-Mo` — is already the same in both languages, and demanding an entry mapping it to
    itself would put a hundred such pairs in the table for a reviewer to read past. This does not
    weaken the residue check, which looks for Japanese in the English output and so cannot be
    satisfied by a string that has none.
    """
    if _LANG == "ja" or not CJK.search(ja):
        text = ja
    else:
        text = TRANSLATIONS.get(ja)
        if text is None:
            raise MissingTranslation(ja)
    return text.format(**fmt) if fmt else text


class MissingTranslation(Exception):
    """Raised when a generated string has no entry for the current language."""

    def __init__(self, source: str) -> None:
        super().__init__(source)
        self.source = source


REGION = "ap-northeast-1"
REGION_LABEL = "アジアパシフィック (東京)"
PRICE_SNAPSHOT = "2026-08-09"

SOURCE_S3 = "https://aws.amazon.com/s3/pricing/"
SOURCE_FSX = "https://aws.amazon.com/fsx/netapp-ontap/pricing/"
SOURCE_DATASYNC = "https://aws.amazon.com/datasync/pricing/"
SOURCE_EGRESS = "https://aws.amazon.com/ec2/pricing/on-demand/#Data_Transfer"
SOURCE_DX = "https://aws.amazon.com/directconnect/pricing/"
SOURCE_FSX_GENERATIONS = (
    "https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html"
)
SOURCE_FLEXCACHE_FEATURES = "https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html"
SOURCE_FLEXCACHE_SIZING = (
    "https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html"
)
SOURCE_FSX_EFFICIENCY = (
    "https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html"
)
SOURCE_FSX_TIER_EFFICIENCY = (
    "https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/manage-vol-SE.html"
)
SOURCE_NETAPP_TIER_EFFICIENCY = "https://kb.netapp.com/Advice_and_Troubleshooting/Data_Storage_Software/ONTAP_OS/Does_ONTAP_apply_efficiencies_to_blocks_that_are_tiered-out_to_Fabricpool%3F"
SOURCE_S3FILES_QUOTAS = (
    "https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html"
)
SOURCE_S3FILES_MOUNTING = (
    "https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html"
)
SOURCE_S3FILES_OVERVIEW = (
    "https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html"
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

# Fraction of the SSD-tier saving that survives on blocks living in the capacity pool.
#
# Background storage efficiency does not run on data once it has been tiered; only savings already
# applied while the block was on SSD are preserved. A block tiered before efficiency ran keeps no
# saving at all. So the pool-tier rate cannot simply be the published SSD rate, and how close it
# gets depends on the tiering policy and cooling period, which no vendor figure covers. Half is an
# assumption, stated as one, and the document carries a sensitivity table across the whole range
# because the choice moves the totals more than most.
#   https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/manage-vol-SE.html
POOL_EFFICIENCY_RETENTION = 0.5
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

# Data transfer out of ap-northeast-1. Internet egress is tiered per month across the account;
# Direct Connect is flat per GB and carries separate port charges that depend on the facility.
EGRESS_INTERNET_TIERS: tuple[tuple[float, float], ...] = (
    (10_240.0, 0.114),  # first 10 TB
    (51_200.0, 0.089),  # next 40 TB
    (153_600.0, 0.086),  # next 100 TB
    (math.inf, 0.084),  # beyond 150 TB
)

EGRESS = {
    "internet": Rate(
        EGRESS_INTERNET_TIERS[0][1],
        "GB",
        "インターネット向けデータ転送 (最初の 10 TB)",
        "2026-06-01",
        SOURCE_EGRESS,
    ),
    "dx": Rate(
        0.041,
        "GB",
        "Direct Connect 経由のデータ転送 (東京、ポート料金は別)",
        "2026-07-01",
        SOURCE_DX,
    ),
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


def tiered_egress(gib_out: float) -> float:
    """Internet egress cost across its monthly volume tiers."""
    remaining, total, floor = gib_out, 0.0, 0.0
    for ceiling, price in EGRESS_INTERNET_TIERS:
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
    efficiency_ssd: float
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
    def efficiency_pool(self) -> float:
        """Saving assumed on blocks in the capacity pool. See POOL_EFFICIENCY_RETENTION."""
        return self.efficiency_ssd * POOL_EFFICIENCY_RETENTION

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
        t("ストレージ (S3 Standard)"): tiered_s3_storage(sc.stored_gib),
        t("PUT リクエスト"): sc.objects_per_month * S3["tier1"].usd,
        t("GET リクエスト"): sc.reads_per_month * S3["tier2"].usd,
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
        math.ceil(logical_ssd * (1 - sc.efficiency_ssd) * (1 + sc.ssd_headroom)),
    )
    pool = logical_pool * (1 - sc.efficiency_pool)
    tput = choose_throughput(sc.required_mbps, dep["tput_options"], sc.tput_headroom)

    lines = {
        t("SSD ストレージ ({size})", size=gib(ssd)): ssd * dep["ssd"].usd,
        t("スループットキャパシティ ({mbps} MBps)", mbps=tput): tput * dep["tput"].usd,
    }
    if sc.pool_fraction > 0:
        lines[t("キャパシティプールストレージ ({size})", size=gib(pool))] = (
            pool * dep["pool"].usd
        )
        lines[t("キャパシティプール読み取りリクエスト")] = (
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
    lines[t("ストレージ (S3 Standard、着信面 {size})", size=gib(landing_gib))] = (
        tiered_s3_storage(landing_gib)
    )
    lines[t("PUT リクエスト (S3 バケット宛)")] = sc.objects_per_month * S3["tier1"].usd
    lines[t("GET / LIST リクエスト (同期の読み出し)")] = (
        sc.objects_per_month * S3["tier2"].usd + list_calls * S3["tier1"].usd
    )
    lines[t("DataSync 転送")] = sc.ingest_gib * DATASYNC["basic_gb"].usd
    return lines


def fsx_s3ap(sc: Scenario) -> dict[str, float]:
    """The same file system, written through an S3 Access Point. No second copy, no task."""
    lines = dict(fsx_component(sc))
    lines[t("PUT リクエスト (S3 AP 経由)")] = sc.objects_per_month * S3["ap_tier1"].usd
    return lines


def s3_files_metadata_usd(sc: Scenario | BaselineCell) -> tuple[float, float]:
    """The two S3 Files metadata charges, in USD: (import side, read side).

    Four KiB per operation on each side, the same quantity `s3_files_option` books in both of its
    branches. Exposed so a caller can show the two amounts apart from the data lines without
    reading them back out of a label.
    """
    metadata_gib = S3FILES_METADATA_KIB / (1024 * 1024)
    return (
        sc.objects_per_month * metadata_gib * S3FILES["write"].usd,
        sc.reads_per_month * metadata_gib * S3FILES["read"].usd,
    )


def s3_files_option(
    sc: Scenario | BaselineCell, split_metadata: bool = False
) -> dict[str, float] | None:
    """An S3 bucket read as a file system through S3 Files, with no FSx for ONTAP at all.

    The authoritative copy stays in the bucket, so S3 Standard is still paid in full. On top of
    that, S3 Files charges for the active fraction resident on its high-performance storage and for
    reads and writes against that storage.

    Object size decides almost everything. Files above the size threshold (default 128 KiB) are
    streamed straight from the bucket and incur no S3 Files storage charge at all, which makes large
    object workloads very cheap here. Files at or below it are imported onto high-performance
    storage at 0.36 USD per GB-month, which makes small object workloads expensive unless the
    expiration window is shortened. Both branches are modelled rather than assuming one.

    `split_metadata` shows the two 4 KiB-per-operation metadata charges as lines of their own in
    both branches, instead of folding them into the data lines at or below the threshold. The
    subtotal is the same either way; only how it is split into lines changes. The default keeps
    every existing caller's lines exactly as they were. With it set, a branch that streams nothing
    on first read (no writes, so no first reads) does not emit the zero-valued stream line.
    """
    if not sc.s3files_viable:
        return None

    object_kib = sc.object_mib * 1024
    metadata_gib = S3FILES_METADATA_KIB / (1024 * 1024)

    lines: dict[str, float] = {
        t("ストレージ (S3 Standard、正本はバケットに残る)"): tiered_s3_storage(
            sc.stored_gib
        ),
        t("PUT リクエスト (S3 バケット宛)"): sc.objects_per_month * S3["tier1"].usd,
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

        lines[
            t("S3 Files 高性能ストレージ (アクティブ {share})", share=f"{active:.0%}")
        ] = hps_gib * S3FILES["storage"].usd
        if not split_metadata or streamed_reads > 0:
            lines[t("GET リクエスト (初回読み出しはバケットからストリーム)")] = (
                streamed_reads * S3["tier2"].usd
            )
        if split_metadata:
            lines[t("S3 Files 書き込み (高性能ストレージへの取り込み)")] = (
                import_gib * S3FILES["write"].usd
            )
            lines[t("S3 Files 読み取り (取り込み後の読み出し)")] = (
                read_gib * S3FILES["read"].usd
            )
        else:
            lines[t("S3 Files 書き込み (高性能ストレージへの取り込み)")] = (
                import_gib + sc.objects_per_month * metadata_gib
            ) * S3FILES["write"].usd
            lines[t("S3 Files 読み取り (取り込み後の読み出しとメタデータ)")] = (
                read_gib + sc.reads_per_month * metadata_gib
            ) * S3FILES["read"].usd
    else:
        lines[t("GET リクエスト (バケットから直接ストリーム)")] = (
            sc.reads_per_month * S3["tier2"].usd
        )
        if not split_metadata:
            lines[t("S3 Files 書き込み (メタデータの取り込み)")] = (
                sc.objects_per_month * metadata_gib * S3FILES["write"].usd
            )
            lines[t("S3 Files 読み取り (メタデータ)")] = (
                sc.reads_per_month * metadata_gib * S3FILES["read"].usd
            )

    if split_metadata:
        ingest_usd, read_usd = s3_files_metadata_usd(sc)
        lines[
            t(
                "S3 Files メタデータ取り込み ({ops} 操作 × 4 KiB)",
                ops=f"{sc.objects_per_month:,.0f}",
            )
        ] = ingest_usd
        lines[
            t(
                "S3 Files メタデータ読み取り ({ops} 操作 × 4 KiB)",
                ops=f"{sc.reads_per_month:,.0f}",
            )
        ] = read_usd

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
        math.ceil(logical * (1 - sc.efficiency_ssd) * (1 + sc.ssd_headroom)),
    )
    tput = choose_throughput(
        sc.cache_required_mbps, dep["tput_options"], sc.tput_headroom
    )
    return {
        t("SSD ストレージ ({size}、階層化不可)", size=gib(ssd)): ssd * dep["ssd"].usd,
        t("スループットキャパシティ ({mbps} MBps)", mbps=tput): tput * dep["tput"].usd,
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
        math.ceil(logical_ssd * (1 - sc.efficiency_ssd) * (1 + sc.ssd_headroom)),
    )
    pool = logical_pool * (1 - sc.efficiency_pool)
    tput = choose_throughput(
        sc.cache_required_mbps, dep["tput_options"], sc.tput_headroom
    )
    lines = {
        t("SSD ストレージ ({size})", size=gib(ssd)): ssd * dep["ssd"].usd,
        t("スループットキャパシティ ({mbps} MBps)", mbps=tput): tput * dep["tput"].usd,
    }
    if sc.pool_fraction > 0:
        lines[t("キャパシティプールストレージ ({size})", size=gib(pool))] = (
            pool * dep["pool"].usd
        )
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
        efficiency_ssd=0.50,
        efficiency_note="テキスト / JSON 主体だが同一内容の重複は少ない。AWS 公表値の汎用ファイル共有・圧縮のみ 50% を当てる",
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
        title="HiL テストベンチ — 走行ログの装置への配布",
        industry="自動車 (AV / ADAS)",
        objects_per_month=20_000_000,
        object_mib=1.0,
        retention_months=2.0,
        reads_per_object=1.5,
        efficiency_ssd=0.40,
        efficiency_note="センサー由来のバイナリが主体。AWS 公表値で最も近い地震探査データの 40% を当てる",
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
        efficiency_ssd=0.75,
        efficiency_note="AWS 公表値のエンジニアリングデータ 75% (圧縮 + 重複排除) を当てる",
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
        efficiency_ssd=0.0,
        efficiency_note="既に圧縮された素材。圧縮も重複排除も効果を見込まない",
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
        efficiency_ssd=0.40,
        efficiency_note="FASTQ / BAM は部分的に圧縮済み。AWS 公表値で最も近い地震探査データの 40% を当てる",
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
        t("### 単価表"),
        "",
        t(
            "{region_label} (`{region}`)、オンデマンド、税別。"
            "AWS Price List API から {snapshot} に取得したもので、`effective` は API が返した適用開始日である。",
            region_label=t(REGION_LABEL),
            region=REGION,
            snapshot=PRICE_SNAPSHOT,
        ),
        "",
        t(
            "**この表は取得時点の値である。** 現在の単価は"
            "[S3 料金]({source_s3})と[FSx for ONTAP 料金]({source_fsx})で確認し、"
            "更新するときは `make finops-write` で再生成する（`make finops` が食い違いを検出する）。",
            source_s3=SOURCE_S3,
            source_fsx=SOURCE_FSX,
        ),
        "",
    ]
    rows = []
    for group, rates in (
        ("S3", S3),
        ("FSx for ONTAP", FSX),
        ("S3 Files", S3FILES),
        ("データ転送", EGRESS),
        ("DataSync", DATASYNC),
    ):
        for rate in rates.values():
            shown = (
                per_1000(rate)
                if rate.unit == "リクエスト"
                else f"{unit_usd(rate.usd)} / {t(rate.unit)}"
            )
            rows.append([t(group), t(rate.label), shown, rate.effective])
    out += table(
        [t("サービス"), t("課金項目"), t("単価"), "effective"],
        rows,
    )
    out += [
        "",
        t(
            "S3 Standard のストレージ単価は使用量で段階が変わる"
            " (最初の 50 TiB {first}、次の 450 TB {next_450}、500 TB 超 {beyond} / GB-Mo)。"
            "以下の試算はこの段階を反映している。",
            first=unit_usd(0.025),
            next_450=unit_usd(0.024),
            beyond=unit_usd(0.023),
        ),
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
            t("{ratio} 倍", ratio=f"{put_ratio:.2f}"),
        ],
        [
            t("GET およびその他"),
            per_1000(S3["tier2"]),
            per_1000(S3["ap_tier2"]),
            t("{ratio} 倍", ratio=f"{get_ratio:.2f}"),
        ],
    ]
    return [
        t("### リクエスト単価の非対称"),
        "",
        t(
            "同じ API 操作でも、宛先が S3 バケットか FSx for ONTAP ボリュームかで単価が違う。"
        ),
        "",
        *table(
            [
                t("操作"),
                t("S3 バケット宛"),
                t("S3 AP 経由 (FSx for ONTAP 宛)"),
                t("S3 バケット宛が何倍か"),
            ],
            rows,
        ),
        "",
        t(
            "低頻度アクセス層を選ぶと逆に開く。S3 Standard-IA の PUT は {ia_put} で、"
            "S3 AP 経由の {ratio} 倍にあたる。"
            "保存単価を下げる目的で階層を落とすと、書き込みが多いワークロードではリクエスト側で戻ってくる。",
            ia_put=per_1000(S3["ia_tier1"]),
            ratio=f"{ia_put_ratio:.1f}",
        ),
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
                t(dep["label"]),
                f"`{dep['api']}`",
                gib(dep["min_ssd_gib"]),
                f"{min_tput} MBps",
                usd(ssd_cost),
                usd(tput_cost),
                f"**{usd(ssd_cost + tput_cost)}**",
            ]
        )
    return [
        t("### 固定費の下限"),
        "",
        t(
            "S3 バケットに下限はない。1 バイトも置かなければ請求は発生しない。"
            "FSx for ONTAP は SSD 1 TiB とスループットキャパシティ 1 つが最小構成で、"
            "使用量に関わらずこの分が毎月かかる。"
        ),
        "",
        *table(
            [
                t("デプロイ"),
                t("API 値"),
                t("最小 SSD"),
                t("最小スループット"),
                t("SSD 分"),
                t("スループット分"),
                t("月額下限"),
            ],
            rows,
        ),
        "",
        t(
            "第二世代の最小スループットは 384 MBps で、第一世代の 128 MBps より 3 つ上の指定値にあたる。"
            "第二世代を選ぶ理由は MBps あたりの単価ではなく、"
            "SSD 512 TiB、200,000 IOPS、Single-AZ で最大 12 HA ペアという上限の側にある"
            "([世代の比較]({url}))。"
            "上限に用がないワークロードで第二世代を選ぶと、使わない余力に払うことになる。",
            url=SOURCE_FSX_GENERATIONS,
        ),
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
                t("{ratio} 倍", ratio=f"{s3_put / S3['standard'].usd:.1f}"),
            ]
        )
    crossover_mib = S3["tier1"].usd * 1024 / S3["standard"].usd
    return [
        t("### オブジェクトサイズが効く理由"),
        "",
        t(
            "リクエスト課金は容量ではなく回数にかかる。"
            "同じ 1 GiB を書くとき、オブジェクトが小さいほど回数が増え、リクエスト課金が保存料金を追い越す。"
        ),
        "",
        *table(
            [
                t("平均オブジェクトサイズ"),
                t("1 GiB あたりの PUT 回数"),
                t("S3 バケット宛の PUT / GiB"),
                t("S3 AP 経由の PUT / GiB"),
                t("S3 の PUT が S3 Standard 1 か月保存料の何倍か"),
            ],
            rows,
        ),
        "",
        t(
            "平均オブジェクトサイズが約 {kib} KiB を下回ると、"
            "S3 バケットへの PUT 料金が S3 Standard の 1 か月分の保存料金を超える。"
            "小さいオブジェクトを高頻度で書く収集系では、保存単価ではなくリクエスト単価が支配項になる。",
            kib=f"{crossover_mib * 1024:,.0f}",
        ),
        "",
    ]


def render_scenario(sc: Scenario) -> list[str]:
    dep = DEPLOYMENTS[sc.deployment]
    # Each option carries a key as well as a label. The label is rendered and therefore translated;
    # the key is what the code compares against. Matching on the label worked while there was one
    # language and would have turned every comparison here into a second thing to translate
    # correctly — including `label.endswith("S3 Files")`, which decides which unavailability reason a
    # reader is given.
    options: list[tuple[str, str, dict[str, float] | None]] = [
        ("s3_only", t("S3 単独 (利用側も S3 API)"), s3_only(sc)),
        ("sync", t("S3 バケット + DataSync + FSx for ONTAP"), s3_plus_sync(sc)),
        ("s3ap", t("FSx for ONTAP S3 AP (この構成)"), fsx_s3ap(sc)),
        ("s3files", t("S3 バケット + S3 Files"), s3_files_option(sc)),
    ]

    out = [
        f"#### {t(sc.title)}",
        "",
        t("想定業種: {industry}", industry=t(sc.industry)),
        "",
        *table(
            [t("前提"), t("値")],
            [
                [t("月間オブジェクト数"), f"{sc.objects_per_month:,}"],
                [t("平均オブジェクトサイズ"), f"{sc.object_mib * 1024:,.0f} KiB"],
                [t("月間書き込み量"), gib(sc.ingest_gib)],
                [t("保持期間"), t("{months} か月", months=f"{sc.retention_months:g}")],
                [t("定常保存量 (論理)"), gib(sc.stored_gib)],
                [t("1 オブジェクトあたり読み出し回数"), f"{sc.reads_per_object:g}"],
                [
                    t("ストレージ効率の仮定 (SSD 層)"),
                    f"{sc.efficiency_ssd:.0%} — {t(sc.efficiency_note)}",
                ],
                [
                    t("ストレージ効率の仮定 (キャパシティプール層)"),
                    t(
                        "{share} — 階層化後は背景の効率化が動かないため、"
                        "SSD 層の {retained} と仮定",
                        share=f"{sc.efficiency_pool:.0%}",
                        retained=f"{POOL_EFFICIENCY_RETENTION:.0%}",
                    ),
                ],
                [t("デプロイ"), f"{t(dep['label'])} (`{dep['api']}`)"],
                [t("平均所要スループット"), f"{sc.required_mbps:,.1f} MB/s"],
                [t("キャパシティプールへ落とす割合"), f"{sc.pool_fraction:.0%}"],
                [
                    t("スループットの余裕"),
                    t(
                        "平均所要の {multiple} 倍を満たす最小の指定値を選ぶ",
                        multiple=f"{sc.tput_headroom + 1:g}",
                    ),
                ],
                [
                    t("SSD のプロビジョニング余裕"),
                    t("効率適用後の {share} 増し", share=f"{sc.ssd_headroom:.0%}"),
                ],
                [
                    t("着信面 (S3) の保持期間"),
                    t(
                        "{months} か月 — 同期後にライフサイクルで失効させる想定",
                        months=f"{sc.landing_retention_months:g}",
                    ),
                ],
                [
                    t("利用側がファイルプロトコルを要求するか"),
                    t("はい") if sc.file_protocol_required else t("いいえ"),
                ],
            ],
        ),
        "",
    ]
    for note in sc.notes:
        out.append(f"- {t(note)}")
    out.append("")

    totals: dict[str, float] = {}
    for key, label, lines in options:
        if lines is None:
            reason = (
                t(sc.s3files_reason)
                if key == "s3files" and sc.s3files_reason
                else t("利用側がファイルプロトコルを要求するため")
            )
            out += [
                t(
                    "**{option}**: 要件を満たさないため試算しない（{reason}）。",
                    option=label,
                    reason=reason,
                ),
                "",
            ]
            continue
        total = sum(lines.values())
        totals[key] = total
        rows = [[item, usd(cost)] for item, cost in lines.items()]
        rows.append([t("**合計 (月額)**"), f"**{usd(total)}**"])
        rows.append([t("論理 1 GiB あたり"), unit_usd(total / sc.stored_gib)])
        out += [f"**{label}**", "", *table([t("内訳"), t("月額")], rows), ""]

    if "s3ap" in totals and "sync" in totals:
        delta = totals["sync"] - totals["s3ap"]
        pct = delta / totals["sync"] * 100

        # Name the dominant term rather than reciting the same three causes every time. Which one
        # dominates changes with object size, and that change is the finding.
        shared = fsx_component(sc)
        contributions = {k: v for k, v in s3_plus_sync(sc).items() if k not in shared}
        contributions[t("PUT リクエスト (S3 AP 経由) の節約")] = -(
            sc.objects_per_month * S3["ap_tier1"].usd
        )
        top = max(contributions.items(), key=lambda kv: abs(kv[1]))
        top_share = abs(top[1]) / abs(delta) * 100 if delta else 0.0

        # Two phrasings rather than one with a substituted verb: English puts the direction in a
        # different place in the sentence than Japanese does, and a 「下回る」/「上回る」 slot would
        # force the English into the Japanese word order.
        template = (
            "同期ジョブを挟む構成と比べ、この構成は月額 {amount} ({pct}%) 下回る。"
            "差の最大項は「{term}」で、差の {share}% を占める。"
            if delta > 0
            else "同期ジョブを挟む構成と比べ、この構成は月額 {amount} ({pct}%) 上回る。"
            "差の最大項は「{term}」で、差の {share}% を占める。"
        )
        out += [
            t(
                template,
                amount=usd(abs(delta)),
                pct=f"{abs(pct):.0f}",
                term=top[0],
                share=f"{top_share:.0f}",
            ),
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
                * (1 - sc.efficiency_ssd)
                * (1 + sc.ssd_headroom)
            ),
        )
        floored = cache_ssd_gib == dep["min_ssd_gib"]
        rows.append(
            [
                t(sc.title).split(" — ")[0],
                gib(sc.stored_gib),
                gib(cache_ssd_gib) + (t("(下限に張り付き)") if floored else ""),
                usd(cache),
                usd(cache_20),
                usd(copy_total),
                t("{ratio} 倍", ratio=f"{copy_total / cache:.1f}") if cache else "—",
            ]
        )

    out = [
        t("### 配布側 — フル SSD の Cache ボリューム"),
        "",
        t(
            "ここまでの試算は収集側 (Origin) だけを見ている。"
            "この構成は配布側に FlexCache の Cache ボリュームを置くので、その分が別に載る。"
        ),
        "",
        t(
            "Cache ボリュームには階層化ができない。"
            "ONTAP の仕様として、FabricPool の Origin を Cache することはできるが"
            "**Cache ボリューム自体は階層化されない** "
            "([対応機能一覧]({url}))。"
            "したがって Cache は全量が SSD に載る。",
            url=SOURCE_FLEXCACHE_FEATURES,
        ),
        "",
        t(
            "それが成立するのは Cache が疎だからである。FlexCache は Origin の全データを複製せず、"
            "実際に読まれたブロックだけを保持する。"
            "NetApp のサイジング指針は Origin の**最低 10%** を推奨し、作成時の既定値も 10% である"
            " ([サイジング指針]({url}))。"
            "読み取り中心のワークロードでは 5〜15% に収める運用が一般的で、"
            "この帯であれば全量 SSD でも費用が成り立つ。",
            url=SOURCE_FLEXCACHE_SIZING,
        ),
        "",
        t(
            "以下は Cache 比率を {ratio} に置いた場合の配布側の月額と、"
            "同じ場所に全量コピーを置いた場合の比較である。"
            "全量コピーは通常のボリュームなので階層化できるものとして計算している。"
            "全量 SSD として計算すれば差はさらに開くが、それは比較として不当なので採らない。",
            ratio=f"{burst[0].cache_ratio:.0%}",
        ),
        "",
        *table(
            [
                t("ワークロード"),
                t("Origin 論理"),
                t("Cache SSD (効率適用後、10%)"),
                t("Cache 10% の月額"),
                t("Cache 20% の月額"),
                t("全量コピーの月額"),
                t("コピーが何倍か"),
            ],
            rows,
        ),
        "",
        t(
            "差が小さく出るのは、Origin の階層化割合が大きいワークロードである。"
            "コピー側もキャパシティプールに落とせるため、SSD 単価の差が効きにくくなる。"
            "逆にホットなデータが多いワークロードでは、コピー側も SSD に置くことになり差が開く。"
        ),
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
                * (1 - pick.efficiency_ssd)
                * (1 + pick.ssd_headroom)
            ),
        )
        total = sum(cache_component(pick, ratio).values())
        note = t("サイジング指針の下限、かつ作成時の既定値") if ratio == 0.10 else ""
        if ratio == 0.20:
            note = t("作業セットが読みきれないときの比較用")
        if ratio == 1.00:
            note = t("実質的にコピー。階層化できないぶんコピーより高い")
        ratio_rows.append([f"{ratio:.0%}", gib(ssd), usd(total), note])

    out += [
        t(
            "Cache 比率を動かしたときの月額を、Origin 論理が最大の"
            "「{workload}」({size}) で示す。",
            workload=t(pick.title).split(" — ")[0],
            size=gib(pick.stored_gib),
        ),
        "",
        *table(
            [t("Cache 比率"), t("Cache SSD"), t("Cache の月額"), t("備考")],
            ratio_rows,
        ),
        "",
        t(
            "比率 100% は成立しない選択である。階層化できない Cache に全量を置くと、"
            "階層化できる通常のボリュームに全量コピーを置くより高くつく。"
            "Cache を「コピーの代わり」として全量でサイジングすると、この領域に入る。"
        ),
        "",
    ]
    return out


@dataclass
class ReadHeavy:
    """A dataset in AWS, read repeatedly by consumers outside AWS.

    This is the shape the architecture was built for and the one the earlier revisions of this
    document never priced. Every scenario above assumed the reader sat in the same Region, where
    transfer is free, so the comparison turned on storage and request rates. Once the readers are
    on premises, egress enters and it is charged per byte moved — so it multiplies by the number of
    times the same bytes are read, which is exactly what a cache removes.
    """

    title: str
    dataset_gib: float
    working_set_gib: float
    reads_per_file: float
    object_mib: float
    note: str
    pool_fraction: float = 0.70
    efficiency_ssd: float = 0.40
    throughput_mbps: int = 128
    deployment: str = "saz1"
    ssd_headroom: float = 0.20
    # Blocks a cache re-fetches over the month because the origin changed or they were evicted, as
    # a fraction of the working set. Reviewed as plausible for read-heavy reference workloads, but
    # it remains an assumption rather than a measurement: nothing here was measured against a live
    # cache, and the hit rate that determines it drifts with the workload.
    refetch_fraction: float = 0.20

    @property
    def read_gib(self) -> float:
        return self.working_set_gib * self.reads_per_file

    @property
    def read_requests(self) -> float:
        per_file = self.object_mib / 1024
        return (
            self.working_set_gib / per_file * self.reads_per_file if per_file else 0.0
        )

    def origin_lines(self) -> dict[str, float]:
        dep = DEPLOYMENTS[self.deployment]
        ssd = max(
            dep["min_ssd_gib"],
            math.ceil(
                self.dataset_gib
                * (1 - self.pool_fraction)
                * (1 - self.efficiency_ssd)
                * (1 + self.ssd_headroom)
            ),
        )
        pool = (
            self.dataset_gib
            * self.pool_fraction
            * (1 - self.efficiency_ssd * POOL_EFFICIENCY_RETENTION)
        )
        return {
            t("SSD ストレージ ({size})", size=gib(ssd)): ssd * dep["ssd"].usd,
            t(
                "スループットキャパシティ ({mbps} MBps)", mbps=self.throughput_mbps
            ): self.throughput_mbps * dep["tput"].usd,
            t("キャパシティプールストレージ ({size})", size=gib(pool)): pool
            * dep["pool"].usd,
        }


# Working set at a tenth of the dataset and a 20 percent refetch rate. Both were reviewed as
# plausible for this class of workload; both are still assumptions, and the document says which
# way each one moves the result.
READ_HEAVY = ReadHeavy(
    title="同じデータを繰り返し読む — 利用側はオンプレミス",
    dataset_gib=20 * GIB_PER_TIB,
    working_set_gib=2 * GIB_PER_TIB,
    reads_per_file=30.0,
    object_mib=4.0,
    note="参照データセットを毎月 30 回読み直す。回帰試験、再生、突き合わせのように"
    "同じ入力を何度も読むワークロードを想定する",
)


# FabricPool bundles cold blocks into 4 MB objects, so a fetch from the capacity pool is metered in
# units of that size rather than per file.
# https://docs.netapp.com/us-en/ontap-whatsnew/ontap98fo_storage_efficiencies.html
FABRICPOOL_OBJECT_MIB = 4.0

# The read-side options, keyed by a stable identifier. The costs are looked up by three functions
# and rendered by two, so the label a reader sees and the key the code indexes by have to be
# separate things — indexing by the label would mean every lookup here had to be translated
# correctly as well, and a typo would read as a missing option rather than as an error.
READ_OPTIONS: dict[str, str] = {
    "direct": "S3 バケットを直接読む",
    "s3ap": "FSx for ONTAP S3 AP 経由で読む",
    "flexcache": "FSx for ONTAP + FlexCache を NFS / SMB で読む (この構成)",
    "copy": "S3 + DataSync で全量コピー",
}


def read_request_costs(rh: ReadHeavy) -> dict[str, dict[str, float]]:
    """Request charges only, per option. Storage and transfer are deliberately left out."""
    reads = rh.read_requests
    objects_in_dataset = rh.dataset_gib * 1024 / rh.object_mib

    # Cache fills pull the working set plus refetches; the share sitting in the capacity pool is
    # read in FabricPool-sized units.
    fill_gib = rh.working_set_gib * (1 + rh.refetch_fraction)
    pool_ops = fill_gib * rh.pool_fraction * 1024 / FABRICPOOL_OBJECT_MIB

    return {
        "direct": {
            t("S3 GET ({count} 回)", count=f"{reads:,.0f}"): reads * S3["tier2"].usd,
        },
        "s3ap": {
            t("S3 AP 経由 GET ({count} 回)", count=f"{reads:,.0f}"): reads
            * S3["ap_tier2"].usd,
            t(
                "キャパシティプール読み取り ({count} 操作)", count=f"{pool_ops:,.0f}"
            ): pool_ops * FSX["pool_read"].usd,
        },
        "flexcache": {
            t("S3 リクエスト"): 0.0,
            t(
                "キャパシティプール読み取り ({count} 操作、キャッシュ充填分のみ)",
                count=f"{pool_ops:,.0f}",
            ): pool_ops * FSX["pool_read"].usd,
        },
        "copy": {
            t(
                "S3 GET ({count} 回、全量を 1 回)", count=f"{objects_in_dataset:,.0f}"
            ): objects_in_dataset * S3["tier2"].usd,
            "S3 LIST": math.ceil(objects_in_dataset / 1000) * S3["tier1"].usd,
            t("利用側の読み出し (ローカル)"): 0.0,
        },
    }


def render_read_requests(rh: ReadHeavy) -> list[str]:
    """Request charges at a fixed read count, and how object size moves them."""
    costs = read_request_costs(rh)
    rows = []
    for key, lines in costs.items():
        detail = t("、").join(f"{k} {usd(v)}" for k, v in lines.items() if v > 0) or t(
            "なし"
        )
        rows.append([t(READ_OPTIONS[key]), detail, f"**{usd(sum(lines.values()))}**"])

    direct_egress = tiered_egress(rh.read_gib)
    direct_requests = sum(costs["direct"].values())

    out = [
        t(
            "#### 読み取り {reads} 回時点のリクエスト課金",
            reads=f"{rh.reads_per_file:g}",
        ),
        "",
        t(
            "前提は上と同じで、読み取り回数だけ {reads} 回に固定する。"
            "作業セット {working_set} を {object_mib} MiB のオブジェクトで持つと"
            "ユニークなオブジェクト数は {objects} 個、"
            "読み出し回数は {requests} 回になる。",
            reads=f"{rh.reads_per_file:g}",
            working_set=gib(rh.working_set_gib),
            object_mib=f"{rh.object_mib:g}",
            objects=f"{rh.working_set_gib * 1024 / rh.object_mib:,.0f}",
            requests=f"{rh.read_requests:,.0f}",
        ),
        "",
        *table(
            [t("方式"), t("内訳"), t("リクエスト課金の合計")],
            rows,
        ),
        "",
        t(
            "**この規模ではリクエスト課金は支配項ではない。** 同じ条件での転送料金は {egress} で、"
            "直接読む構成のリクエスト課金 {requests} の "
            "{ratio} 倍にあたる。"
            "この構成が読み取り側で効くのは、リクエスト単価ではなく転送量を減らすからである。",
            egress=usd(direct_egress),
            requests=usd(direct_requests),
            ratio=f"{direct_egress / direct_requests:,.0f}",
        ),
        "",
        t(
            "FlexCache 経由の読み出しに S3 リクエストは発生しない。"
            "利用側は NFS / SMB で読むためである。"
            "残るのはキャッシュ充填時に Origin 側のキャパシティプールから読む分だけで、"
            "FabricPool が {object_mib} MB 単位で扱うためこの操作数で計上している。",
            object_mib=f"{FABRICPOOL_OBJECT_MIB:g}",
        ),
        "",
    ]

    out += [
        t(
            "S3 Files はこの表に入れていない。**この構成が対象とする利用側では使えない**。"
            "対応プロトコルが NFSv4.1 と NFSv4.2 だけで、"
            "NFSv3 と SMB が対象外である ([非対応事項とクォータ]({url}))。"
            "NFSv3 で固定された装置や Windows の工程はこれで外れる。"
            "ドキュメントが挙げる対応コンピュートも EC2、Lambda、EKS、ECS で、"
            "オンプレミスからのマウントについては記載がない。"
            "利用側を AWS へ移せる場合の参考値は後述する。",
            url=SOURCE_S3FILES_QUOTAS,
        ),
        "",
    ]

    # Where request charges do start to matter: small objects.
    size_rows = []
    for mib in (8 / 1024, 64 / 1024, 0.25, 1.0, 4.0, 64.0):
        variant = replace(rh, object_mib=mib)
        c = read_request_costs(variant)
        direct = sum(c["direct"].values())
        ap = sum(c["s3ap"].values())
        flex = sum(c["flexcache"].values())
        size_rows.append(
            [
                f"{mib * 1024:,.0f} KiB",
                f"{variant.read_requests:,.0f}",
                usd(direct),
                usd(ap),
                usd(flex),
                f"{direct / tiered_egress(variant.read_gib) * 100:.1f}%",
            ]
        )
    out += [
        t("#### リクエスト課金が効いてくるのはオブジェクトが小さいとき"),
        "",
        t(
            "読み出す総量は同じで、オブジェクトサイズだけを変える。回数が変わるので課金額も変わる。"
        ),
        "",
        *table(
            [
                t("平均オブジェクトサイズ"),
                t("月間の読み出し回数"),
                t("S3 を直接読む"),
                t("S3 AP 経由"),
                t("この構成 (FlexCache)"),
                t("直接読む場合の転送料金に対する比"),
            ],
            size_rows,
        ),
        "",
        t(
            "最右列が読みどころである。オブジェクトが数 MiB 以上なら、リクエスト課金は転送料金の 1% に届かない。"
            "一桁 KiB まで小さくすると数十 % に達し、このときは転送とリクエストの両方が問題になる。"
            "**「S3 の API コールが高額になる」という見立てが成立するのは、この小オブジェクト側の領域である**。"
            "オブジェクトが大きいワークロードでは、削減対象は転送量に絞ってよい。"
        ),
        "",
    ]
    return out


def read_side_totals(rh: ReadHeavy) -> dict[str, float]:
    """Transfer and request charges for reading, split so either can be seen to dominate."""
    costs = read_request_costs(rh)
    direct_requests = sum(costs["direct"].values())
    direct_egress = tiered_egress(rh.read_gib)
    cache_requests = sum(costs["flexcache"].values())
    cache_egress = tiered_egress(rh.working_set_gib * (1 + rh.refetch_fraction))
    # Both sides carry their storage, or the side that has a file system would be charged for
    # holding the data while the side reading the bucket would not.
    direct_storage = tiered_s3_storage(rh.dataset_gib)
    cache_fixed = sum(rh.origin_lines().values())
    return {
        "direct_egress": direct_egress,
        "direct_requests": direct_requests,
        "direct_storage": direct_storage,
        "direct_total": direct_egress + direct_requests + direct_storage,
        "cache_egress": cache_egress,
        "cache_requests": cache_requests,
        "cache_fixed": cache_fixed,
        "cache_total": cache_egress + cache_requests + cache_fixed,
    }


def render_read_cost_matrix(rh: ReadHeavy) -> list[str]:
    """Both read-side charges in one grid, so a design can be located on it.

    The two charges were shown in separate sweeps, which left the reader unable to tell which one
    their own workload runs into. They respond to different remedies -- transfer to carrying fewer
    bytes, requests to making fewer calls -- so the design decision depends on knowing which
    dominates, and for some workloads it is both.
    """
    sizes = (8 / 1024, 64 / 1024, 1.0, 4.0)
    read_counts = (1, 10, 50)

    rows = []
    for mib in sizes:
        for reads in read_counts:
            v = read_side_totals(
                replace(rh, object_mib=mib, reads_per_file=float(reads))
            )
            share = v["direct_requests"] / v["direct_total"] * 100
            if v["direct_total"] < v["cache_total"]:
                verdict = t("直接読むほうが安い")
            elif share >= 30:
                verdict = t("**両方**")
            elif share >= 5:
                verdict = t("転送 (リクエストも無視できない)")
            else:
                verdict = t("転送")
            rows.append(
                [
                    f"{mib * 1024:,.0f} KiB",
                    f"{reads}",
                    usd(v["direct_egress"]),
                    usd(v["direct_requests"]),
                    f"{share:.0f}%",
                    usd(v["direct_total"]),
                    usd(v["cache_total"]),
                    t(
                        "{ratio} 倍",
                        ratio=f"{v['direct_total'] / v['cache_total']:.1f}",
                    ),
                    verdict,
                ]
            )

    return [
        t("### 転送とリクエストの同時確認"),
        "",
        t(
            "読み取り側の課金は転送とリクエストの 2 つで、効く手が違う。"
            "転送はバイト数を減らすことで下がり、リクエストは呼び出し回数を減らすことで下がる。"
            "**どちらが支配項かで打つ手が変わる**ので、自分のワークロードがどこにいるかを先に確かめる。"
        ),
        "",
        t(
            "作業セットとデータセットの量は固定し、平均オブジェクトサイズと読み取り回数だけを振る。"
            "合計にはどちらの側も保管料金を含める"
            "(直接読む側は S3 Standard、この構成は SSD とキャパシティプールとスループット)。"
            "変動するのは転送とリクエストの 2 列である。"
        ),
        "",
        *table(
            [
                t("平均オブジェクト"),
                t("読み取り回数 / 月"),
                t("転送"),
                t("リクエスト"),
                t("リクエストの占率"),
                t("直接読む計"),
                t("この構成"),
                t("倍率"),
                t("支配項"),
            ],
            rows,
        ),
        "",
        t(
            "読み方は 2 つある。**縦に見ると回数の効果**が出る。"
            "回数が増えて増えるのは転送だけで、リクエストの占率はほぼ変わらない。"
            "**横に見るとサイズの効果**が出る。サイズを小さくすると転送は変わらず"
            "リクエストだけが増えるので、占率が上がる。"
        ),
        "",
        t("#### 支配項ごとの打ち手"),
        "",
        *table(
            [t("支配項"), t("症状"), t("効く手"), t("効かない手")],
            [
                [
                    t("転送"),
                    t("同じデータを何度も読む。オブジェクトは数 MiB 以上"),
                    t(
                        "作業セットだけを運ぶ (FlexCache)、利用側の移設、Direct Connect で単価を下げる"
                    ),
                    t("オブジェクトをまとめる。回数は減っても運ぶバイト数は変わらない"),
                ],
                [
                    t("リクエスト"),
                    t("オブジェクトが一桁 KiB で、読み出し回数が非常に多い"),
                    t(
                        "オブジェクトをまとめて大きくする、S3 API を経由しない読み出し経路にする"
                    ),
                    t("転送単価の交渉。金額の大半がリクエスト側にある"),
                ],
                [
                    t("両方"),
                    t("小さいオブジェクトを繰り返し読む"),
                    t(
                        "まとめる (リクエスト) とキャッシュする (転送) の併用。片方だけでは残る"
                    ),
                    t("片方だけの対処"),
                ],
                [
                    t("どちらも小さい"),
                    t("読み取り回数が少ない。ファイルプロトコルの要件もない"),
                    t("S3 を直接読む。ファイルシステムの固定費を負わない"),
                    t("キャッシュの導入。固定費のほうが大きい"),
                ],
            ],
        ),
        "",
        t(
            "この構成の列がサイズと回数でほとんど動かないのは、"
            "読み出しが S3 API を経由せず、運ぶのが作業セットに限られるためである。"
            "**そのぶん固定費が先に立つ**ので、読み取りが少ない領域では不利になる。"
            "表の「直接読むほうが安い」行がその領域である。"
        ),
        "",
    ]


def render_migrated_to_aws(rh: ReadHeavy) -> list[str]:
    """The same reads with the consumers inside AWS, where egress disappears.

    Included because it is the honest upper bound on what any storage-layer choice can save. If the
    workload can move, moving it removes the entire transfer charge, which is larger than every
    difference between the options. This architecture exists for the cases where it cannot move,
    and saying that plainly is better than leaving the comparison looking like the only lever.
    """
    reads = rh.read_requests
    objects = rh.working_set_gib * 1024 / rh.object_mib
    metadata_gib = S3FILES_METADATA_KIB / (1024 * 1024)
    storage = tiered_s3_storage(rh.dataset_gib)
    on_hps = rh.object_mib * 1024 <= S3FILES_DEFAULT_THRESHOLD_KIB

    storage_label = t("ストレージ (S3 Standard、{size})", size=gib(rh.dataset_gib))
    transfer_label = t("データ転送")
    direct = {
        storage_label: storage,
        t("S3 GET ({count} 回)", count=f"{reads:,.0f}"): reads * S3["tier2"].usd,
        transfer_label: 0.0,
    }
    files = {
        storage_label: storage,
        t(
            "S3 GET ({count} 回、しきい値超のためバケットから直接)",
            count=f"{reads:,.0f}",
        ): reads * S3["tier2"].usd,
        t("S3 Files メタデータ読み取り"): reads * metadata_gib * S3FILES["read"].usd,
        t("S3 Files メタデータ取り込み"): objects * metadata_gib * S3FILES["write"].usd,
        t("S3 Files 高性能ストレージ"): 0.0,
        transfer_label: 0.0,
    }
    fsx = dict(rh.origin_lines())
    fsx[transfer_label] = 0.0

    out = [
        t("#### 参考 — 利用側を AWS へ移した場合"),
        "",
        t(
            "この構成の前提は「利用側が AWS の外にいて、動かせない」ことである。"
            "動かせるなら話は変わるので、参考としてその場合を並べる。"
        ),
        "",
        t(
            "**同一リージョン内のデータ転送には課金がない**。"
            "上の表で {egress} を占めていた転送料金がそのまま消える。"
            "ストレージ層をどう選ぶかで動く金額より、この 1 項目のほうが大きい。",
            egress=usd(tiered_egress(rh.read_gib)),
        ),
        "",
    ]
    for label, lines in (
        (t("EC2 から S3 を直接読む"), direct),
        (t("EC2 から S3 Files でファイルとして読む"), files),
        (t("FSx for ONTAP を同一リージョンで読む"), fsx),
    ):
        total = sum(lines.values())
        rows = [[k, usd(v)] for k, v in lines.items()]
        rows.append([t("**合計 (月額)**"), f"**{usd(total)}**"])
        out += [f"**{label}**", "", *table([t("内訳"), t("月額")], rows), ""]

    d, f, x = sum(direct.values()), sum(files.values()), sum(fsx.values())
    out += [
        t(
            "S3 Files は直接読む場合との差が {delta} しかない。"
            "平均オブジェクトサイズ {object_mib} MiB は"
            "しきい値 {threshold} KiB を超えるため"
            "{not_resident}"
            "保管の課金が増えないためである。"
            "POSIX のファイルセマンティクスを S3 のデータに与える手段としては安い。",
            delta=usd(f - d),
            object_mib=f"{rh.object_mib:g}",
            threshold=f"{S3FILES_DEFAULT_THRESHOLD_KIB:,.0f}",
            not_resident="" if on_hps else t("データが高性能ストレージに載らず"),
        ),
        "",
        t(
            "FSx for ONTAP を同一リージョンで使う場合は {total} で、"
            "直接読む場合の {ratio} 倍になる。"
            "転送料金という差が消えた状態では、ファイルシステムの固定費が残るためである。"
            "この状況で FSx for ONTAP を選ぶ理由は費用ではなく、"
            "SMB、NFSv3、ONTAP のデータ管理機能、あるいはオンプレミスとの併用といった要件になる。",
            total=usd(x),
            ratio=f"{x / d:.1f}",
        ),
        "",
        t(
            "**読み取り側の費用を下げる手段として、利用側の移設が最も効く**。"
            "移設できるなら、まずそれを検討する。"
            "この構成が対象とするのは、装置が現地にある、計測対象との距離が要る、"
            "既存設備の投資が残っている、といった理由で移設できない場合である。"
        ),
        "",
    ]
    return out


def render_read_heavy(rh: ReadHeavy = READ_HEAVY) -> list[str]:
    """The read side, where egress rather than storage decides the bill."""
    egress_direct = tiered_egress(rh.read_gib)
    egress_full = tiered_egress(rh.dataset_gib)
    egress_cache = tiered_egress(rh.working_set_gib * (1 + rh.refetch_fraction))

    storage_label = t("ストレージ (S3 Standard、{size})", size=gib(rh.dataset_gib))
    direct = {
        storage_label: tiered_s3_storage(rh.dataset_gib),
        t(
            "GET リクエスト ({count} 回)", count=f"{rh.read_requests:,.0f}"
        ): rh.read_requests * S3["tier2"].usd,
        t(
            "**データ転送 (読んだ量 {size} がそのまま出る)**", size=gib(rh.read_gib)
        ): egress_direct,
    }
    full_copy = {
        storage_label: tiered_s3_storage(rh.dataset_gib),
        t("データ転送 (全量 {size} を 1 回)", size=gib(rh.dataset_gib)): egress_full,
        t("DataSync 転送"): rh.dataset_gib * DATASYNC["basic_gb"].usd,
    }
    cache = dict(rh.origin_lines())
    cache[
        t(
            "データ転送 (作業セット {size} + 再取得 {refetch})",
            size=gib(rh.working_set_gib),
            refetch=f"{rh.refetch_fraction:.0%}",
        )
    ] = egress_cache

    out = [
        t("### 読み取りが繰り返されるとき — 効くのは Egress"),
        "",
        t(
            "ここまでの試算は利用側が同一リージョンにいることを前提にしていた。"
            "同一リージョン内のデータ転送には課金がないため、比較は保存単価とリクエスト単価の話になる。"
        ),
        "",
        t(
            "**利用側がオンプレミスにいると話が変わる**。"
            "データ転送はリージョンから出たバイト数に課金されるので、"
            "同じファイルを読み直した回数だけ倍になる。"
            "キャッシュが取り除くのはまさにこの倍数である。"
        ),
        "",
        *table(
            [t("前提"), t("値")],
            [
                [t("データセット全体 (論理)"), gib(rh.dataset_gib)],
                [
                    t("月間の作業セット (実際に触るユニークなバイト数)"),
                    gib(rh.working_set_gib),
                ],
                [t("同じファイルを読む回数 / 月"), f"{rh.reads_per_file:g}"],
                [t("月間の読み出し総量"), gib(rh.read_gib)],
                [t("平均オブジェクトサイズ"), f"{rh.object_mib:g} MiB"],
                [t("キャッシュの再取得率の仮定"), f"{rh.refetch_fraction:.0%}"],
                [t("転送経路"), t("インターネット (段階単価)")],
            ],
        ),
        "",
        f"- {t(rh.note)}",
        "",
    ]

    for label, lines in (
        (t("オンプレミスから S3 を直接読む"), direct),
        (t("S3 から全量をオンプレミスへコピーして読む (DataSync)"), full_copy),
        (t("FSx for ONTAP + FlexCache で読む (この構成)"), cache),
    ):
        total = sum(lines.values())
        rows = [[k, usd(v)] for k, v in lines.items()]
        rows.append([t("**合計 (月額)**"), f"**{usd(total)}**"])
        out += [f"**{label}**", "", *table([t("内訳"), t("月額")], rows), ""]

    d_total, f_total, c_total = (
        sum(direct.values()),
        sum(full_copy.values()),
        sum(cache.values()),
    )
    out += [
        t(
            "直接読む構成では、転送料金だけで {egress} "
            "({share}%) を占める。"
            "保存料金とリクエスト料金は誤差に近い。"
            "この構成は同じ読み取りを {cache_total} で提供し、"
            "直接読む場合の {ratio} 分の 1 になる。",
            egress=usd(egress_direct),
            share=f"{egress_direct / d_total * 100:.0f}",
            cache_total=usd(c_total),
            ratio=f"{d_total / c_total:.1f}",
        ),
        "",
        t(
            "全量コピーとの差は転送量の差である。"
            "コピーはデータセット全量 {dataset} を運ぶ。"
            "キャッシュは作業セット {working_set} と再取得分だけを運ぶ。"
            "月額では {copy_total} と {cache_total} の差になる。"
            "加えて、オンプレミス側に確保する容量が全量か作業セット分かで違う。"
            "こちらは AWS の請求には出ない。",
            dataset=gib(rh.dataset_gib),
            working_set=gib(rh.working_set_gib),
            copy_total=usd(f_total),
            cache_total=usd(c_total),
        ),
        "",
    ]

    # Request charges alone, at a read count where the transfer argument is already decided. The
    # original hypothesis behind this architecture was that S3 request charges hurt as much as
    # egress. At these object sizes they do not, and saying so is more useful than implying they do.
    out += render_read_requests(replace(rh, reads_per_file=10.0))

    out += render_read_cost_matrix(rh)
    out += render_migrated_to_aws(replace(rh, reads_per_file=10.0))

    # The number of reads is the whole argument, so show it as a curve.
    rows = []
    for r in (1, 5, 10, 30, 50, 100):
        variant = replace(rh, reads_per_file=float(r))
        d = (
            tiered_s3_storage(variant.dataset_gib)
            + variant.read_requests * S3["tier2"].usd
            + tiered_egress(variant.read_gib)
        )
        c = sum(variant.origin_lines().values()) + tiered_egress(
            variant.working_set_gib * (1 + variant.refetch_fraction)
        )
        rows.append(
            [
                t("{count} 回", count=r),
                gib(variant.read_gib),
                usd(d),
                usd(c),
                t("{ratio} 倍", ratio=f"{d / c:.1f}") if c else "—",
            ]
        )
    out += [
        t("#### 読み取り回数に対する感度"),
        "",
        t("同じ作業セットを何回読むかだけを変えて、他の前提は固定する。"),
        "",
        *table(
            [
                t("読み取り回数 / 月"),
                t("月間の読み出し総量"),
                t("直接読む構成"),
                t("この構成"),
                t("直接読む構成が何倍か"),
            ],
            rows,
        ),
        "",
        t(
            "読み取りが 1 回なら直接読むほうが安い。"
            "運ぶ量が同じで、ファイルシステムの固定費を負わないためである。"
            "回数が増えると直接読む構成の転送料金だけが比例して増え、"
            "キャッシュ側は増えない。**損益分岐は読み取り回数で決まる。**"
        ),
        "",
        t(
            "Direct Connect を使う場合、転送単価は {dx} / GB の定額になり"
            " (インターネットの最初の 10 TB は {internet} / GB)、"
            "倍率は下がるが構造は変わらない。ポート料金は別に発生し、接続する施設によって変わる。",
            dx=unit_usd(EGRESS["dx"].usd),
            internet=unit_usd(EGRESS["internet"].usd),
        ),
        "",
        t(
            "この節の前提で最も効くのは作業セットの割合である。"
            "作業セットがデータセット全体に近づくほどキャッシュの利点は薄れ、"
            "全量コピーとの差が縮む。逆に参照が局所的なほど差が開く。"
        ),
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
        files_cell = usd(sum(files.values())) if files else t("要件を満たさない")
        rows.append(
            [
                t(sc.title).split(" — ")[0],
                f"{sc.object_mib * 1024:,.0f} KiB",
                usd(sync_total),
                usd(ap_total),
                files_cell,
            ]
        )

    out = [
        t("### 3 つの選択肢を並べる — 収集と利用が同じ場所の場合"),
        "",
        t(
            "ここでは配布側を足さない。**バケットから DataSync で FSx for ONTAP にコピーすれば、"
            "その FSx for ONTAP 自体が NFS / SMB で読み書きできるので、Cache を置く理由がない**。"
            "Cache が費用に見合うのは、利用側がファイルシステムと別の場所にいる場合だけである。"
            "その場合の比較は Cache と全量コピーの対比（上の表）になる。"
            "この表は 3 案がいずれもファイルシステム 1 つ、または 0 つで済む単一サイトの比較である。"
        ),
        "",
        t(
            "この表は「利用側にファイルとして配る」ことを前提にした比較である。"
            "利用側が S3 API で足りるなら配布層そのものが不要で、"
            "各ワークロードの試算にある S3 単独の金額が下限になる。"
        ),
        "",
        t(
            "3 列目の S3 Files は、S3 バケットをファイルシステムとしてマウントする選択肢である。"
            "FSx for ONTAP を持たないため固定費の下限がなく、正本はバケットに残る。"
            "対応プロトコルは NFSv4.1 と NFSv4.2 で、**NFSv3 と SMB は対象外**である"
            " ([非対応事項とクォータ]({quotas_url}))。"
            "EC2 では S3 Files のマウントヘルパー (`amazon-efs-utils` に含まれる) が必要で、"
            "`s3files` というファイルシステムタイプでマウントする"
            " ([マウント手順]({mounting_url}))。"
            "対応するコンピュートは EC2、Lambda、EKS、ECS である"
            " ([S3 Files の概要]({overview_url}))。"
            "費用だけでは決められない仕様上の制約が複数あるので、"
            "この表の金額は後述の[S3 Files を選ぶ場合の仕様](#s3-files-を選ぶ場合の仕様)と併せて読む。",
            quotas_url=SOURCE_S3FILES_QUOTAS,
            mounting_url=SOURCE_S3FILES_MOUNTING,
            overview_url=SOURCE_S3FILES_OVERVIEW,
        ),
        "",
        *table(
            [
                t("ワークロード"),
                t("平均オブジェクト"),
                "S3 + DataSync + FSx for ONTAP",
                t("FSx for ONTAP S3 AP (この構成)"),
                "S3 + S3 Files",
            ],
            rows,
        ),
        "",
        t(
            "オブジェクトサイズで結果が反転する。"
            "S3 Files は既定のしきい値 ({threshold} KiB) を超えるファイルを"
            "高性能ストレージに載せず、バケットから直接ストリームする。"
            "ストレージ課金が発生しないので、大きいオブジェクトを読むワークロードでは安い。"
            "しきい値以下のファイルは高性能ストレージに取り込まれ、"
            "{rate} / GB-Mo が効くので、小さいオブジェクトでは高くつく。",
            threshold=f"{S3FILES_DEFAULT_THRESHOLD_KIB:,.0f}",
            rate=unit_usd(S3FILES["storage"].usd),
        ),
        "",
        t(
            "大きいオブジェクトの行で S3 Files の金額がほぼ S3 Standard の保存料金に見えるのは、"
            "計上漏れではなく設計どおりである。1 MiB 以上の読み出しは高性能ストレージを経由せず"
            "バケットから直接ストリームされ、ファイルシステム側のデータ課金が発生しない。"
            "残るのは S3 の GET リクエストと 4 KiB のメタデータ読み取りだけで、"
            "オブジェクトが大きければ回数が少ないため金額に出ない。"
            "S3 の GET と PUT はどの行でも計上している。"
        ),
        "",
        t(
            "**配布サイトを増やしたときの増え方は 3 案で違う**。"
            "この構成は Origin 1 つに対してサイトごとに Cache を足すので、"
            "1 サイトあたり Origin 論理の 1 割程度で増える。"
            "DataSync 方式はサイトごとに全量コピーを置くので、1 サイトあたり全量で増える。"
            "S3 Files はファイルシステムあたり 1 VPC なのでサイトごとにファイルシステムを作るが、"
            "同じバケットに複数のファイルシステムを付けられ、"
            "課金されるのは各ファイルシステムが実際に使った分だけである。"
            "サイト数が増えるほど全量コピー方式が不利になる。"
        ),
        "",
        t(
            "S3 Files が安く出るワークロードで、それでもこの構成を選ぶ理由は費用ではない。"
            "利用側が構成を変えられない装置である、SMB が要る、AWS 外にいる、"
            "ONTAP のデータ管理機能を収集直後のデータに効かせたい、といった要件の側にある。"
            "費用だけで選ぶなら、その要件がない限り S3 Files のほうが合う場面がある。"
        ),
        "",
    ]

    # Why the large-object columns land where they do. The arithmetic is short and it is the whole
    # explanation, so it belongs in the document rather than in a reader's head.
    # Largest dataset among the workloads whose objects sit above the S3 Files threshold. Chosen by
    # logical size rather than object size so the efficiency sweep below lands on a workload where
    # a non-zero efficiency is plausible; sweeping it on pre-compressed media would be theatre.
    big = max(
        (s for s in SCENARIOS if s.object_mib * 1024 > S3FILES_DEFAULT_THRESHOLD_KIB),
        key=lambda s: s.stored_gib,
    )
    dep = DEPLOYMENTS[big.deployment]
    big_ssd = max(
        dep["min_ssd_gib"],
        math.ceil(
            big.stored_gib
            * (1 - big.pool_fraction)
            * (1 - big.efficiency_ssd)
            * (1 + big.ssd_headroom)
        ),
    )
    big_ssd_cost = big_ssd * dep["ssd"].usd
    big_s3_storage = tiered_s3_storage(big.stored_gib)
    out += [
        t("#### 大きいオブジェクトで S3 Files が安くなる理由"),
        "",
        t(
            "「{workload}」の内訳を並べると理由が 1 行で出る。"
            "S3 Files は**しきい値を超えるファイルのデータを高性能ストレージに載せない**ので、"
            "保管の課金は S3 Standard の単価だけになる。"
            "FSx for ONTAP は作業セット相当を SSD に置く。",
            workload=t(big.title).split(" — ")[0],
        ),
        "",
        *table(
            [t("比較項目"), t("値")],
            [
                [t("論理データ量"), gib(big.stored_gib)],
                [
                    t("S3 Files の保管 (論理全量を S3 Standard に)"),
                    usd(big_s3_storage),
                ],
                [
                    t(
                        "この構成の SSD 分のみ ({size} × {rate})",
                        size=gib(big_ssd),
                        rate=unit_usd(dep["ssd"].usd),
                    ),
                    usd(big_ssd_cost),
                ],
                [
                    t("SSD 分が S3 Standard 全量の何倍か"),
                    t("{ratio} 倍", ratio=f"{big_ssd_cost / big_s3_storage:.2f}"),
                ],
            ],
        ),
        "",
        t(
            "論理データの {share} を SSD に置くだけで、"
            "論理全量を S3 Standard に置いた金額を上回る。"
            "さらにスループットキャパシティの固定費が乗る。S3 Files にはその項目がない。",
            share=f"{1 - big.pool_fraction:.0%}",
        ),
        "",
        t(
            "引き換えになっているものも同じ表から読める。"
            "S3 Files でしきい値を超えるファイルは、読み出しのたびにバケットから取得される。"
            "低レイテンシが要るならしきい値を上げることになり、"
            "上げた分は {rate} / GB-Mo の課金対象になる。"
            "この安さは、読み出しが S3 のレイテンシで行われることと引き換えである。",
            rate=unit_usd(S3FILES["storage"].usd),
        ),
        "",
    ]

    # Storage efficiency is the assumption with the most leverage, and it is an assumption.
    eff_rows = []
    for eff in (0.0, 0.20, 0.40, 0.60, 0.75):
        variant = replace(big, efficiency_ssd=eff)
        ap = sum(fsx_s3ap(variant).values())
        files = s3_files_option(variant)
        note = ""
        if eff == 0.40:
            note = t("AWS 公表値の地震探査データ")
        elif eff == 0.65:
            note = t("AWS 公表値の汎用ファイル共有")
        elif eff == 0.75:
            note = t("AWS 公表値のエンジニアリングデータ")
        eff_rows.append(
            [
                f"{eff:.0%}",
                f"{eff * POOL_EFFICIENCY_RETENTION:.0%}",
                usd(ap),
                usd(sum(files.values())) if files else "—",
                note,
            ]
        )
    out += [
        t("#### ストレージ効率の仮定に対する感度"),
        "",
        t(
            "効率の仮定は、この文書で最も金額を動かす仮定である。"
            "「{workload}」で SSD 層の効率を振ると次のようになる"
            "（キャパシティプール層は常にその半分と仮定）。",
            workload=t(big.title).split(" — ")[0],
        ),
        "",
        *table(
            [
                t("SSD 層の効率"),
                t("プール層の効率"),
                t("この構成の月額"),
                t("S3 + S3 Files の月額"),
                t("備考"),
            ],
            eff_rows,
        ),
        "",
        t(
            "**S3 Files の列は動かない。** ONTAP の重複排除と圧縮は S3 の保管料金に効かないので、"
            "効率をどう仮定しても S3 Files 側の金額は変わらない。"
            "つまり効率の仮定は、この構成に有利な方向にしか働かない。"
            "楽観的な効率を置くと、この構成が実際より良く見える。"
        ),
        "",
        t(
            "階層化を有効にしている環境で高い効率を期待するのは慎重に扱う。"
            "**階層化されたデータには背景の効率化処理が動かない**。"
            "SSD にいる間に適用された分だけが保持され、"
            "効率化が走る前に階層化されたブロックは削減なしでプールに残る"
            " ([FSx for ONTAP のドキュメント]({fsx_url})、"
            "[NetApp KB]({netapp_url}))。"
            "cooling period が短い構成や `All` ポリシーでは、プール層の効率は 0% に寄る。",
            fsx_url=SOURCE_FSX_TIER_EFFICIENCY,
            netapp_url=SOURCE_NETAPP_TIER_EFFICIENCY,
        ),
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
                    t("{days} 日", days=days),
                    f"{active:.0%}",
                    usd(total),
                    t("既定値") if days == 30 else "",
                ]
            )
        out += [
            t(
                "小さいオブジェクトの場合、高性能ストレージの有効期限が最大のレバーになる。"
                "「{workload}」で期限を振ると次のようになる"
                "(既定は 30 日、設定可能な範囲は 1 日から 365 日)。",
                workload=t(sc.title).split(" — ")[0],
            ),
            "",
            *table(
                [
                    t("有効期限"),
                    t("アクティブ割合"),
                    t("S3 + S3 Files の月額"),
                    t("備考"),
                ],
                sweep,
            ),
            "",
            t(
                "期限を詰めれば下がるが、期限外のファイルを読むとバケットからの取り込みが再度発生する。"
                "読み取りの時間的な偏りが小さいワークロードでは、期限を詰めても取り込みの往復で戻ってくる。"
            ),
            "",
            t(
                "しきい値のほうも同じ構造を持つ。"
                "しきい値を上げれば小さくないファイルも低レイテンシで読めるが、"
                "その分が高性能ストレージの課金対象になる。"
                "この列の安さは、しきい値を超えるファイルが S3 のレイテンシで読まれることと引き換えである。"
            ),
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
        t("### 既に FSx for ONTAP がある場合の増分"),
        "",
        t(
            "この構成が対象とする状況では、利用側が NFS / SMB を要求するため FSx for ONTAP は既にある。"
            "そこに S3 の受け口を足すときの比較は、"
            "グリーンフィールドの「S3 か FSx for ONTAP か」ではなく「増分としてどちらが安いか」になる。"
        ),
        "",
        t(
            "前提は上の「{workload}」と同じ (3 億オブジェクト / 月、64 KiB)。"
            "SSD とスループットは既存ワークロードのために既に払っているものとして、増分だけを並べる。",
            workload=t(SCENARIOS[0].title),
        ),
        "",
        *table(
            [t("増分"), t("内訳"), t("月額")],
            [
                [
                    t("S3 AP を足す"),
                    t("S3 AP 経由 PUT のみ"),
                    usd(ap_incremental),
                ],
                [
                    t("S3 バケットと同期ジョブを足す"),
                    t("S3 保存 + S3 PUT + 同期の読み出し GET + DataSync 転送"),
                    usd(alt_incremental),
                ],
                [t("差"), "", f"**{usd(alt_incremental - ap_incremental)}**"],
            ],
        ),
        "",
        t(
            "S3 AP はアクセスポイント自体に時間課金がないため、増分はリクエスト課金に集約される。"
            "同期ジョブ側の増分には、同じバイト列を 2 系統で持つ保存料金が含まれる。"
            "この差は容量が増えても縮まらない。"
        ),
        "",
    ]


# --------------------------------------------------------------------------- baseline grid
#
# A dedicated dataclass rather than a reused `Scenario`. The scenarios couple the stored volume to
# the ingest: `stored_gib = ingest_gib * retention_months`, so stored follows from what is written.
# This grid does the opposite — it fixes the stored logical volume at a common 20 TiB and derives the
# read and write volumes from three ratios, which is the whole point of a like-for-like baseline.
# Forcing that onto `Scenario` would make the monthly write volume set the retained volume, which is
# exactly the conflation design section 3.3 forbids. `BaselineCell` has no `industry` field — the
# grid is deliberately workload-agnostic.
#
# A pattern is held as three numbers, not as two volumes:
#
#   working-set ratio w   the share of the stored objects that are read within the month
#   reads per object n    how many times each working-set object is read
#   churn rate c          bytes written per month / stored bytes
#
# and the volumes follow: read = stored x w x n, write = stored x c. Stating a read volume alone
# ("20 TiB a month") hides whether it is the whole data set once or a tenth of it ten times, and
# those two are not interchangeable once tiering is in play. The ratios are integer percentages so
# `stored x pct x n / 100` is an exact integer for every pattern held here.
#
# Pricing is deliberately NOT a function of w. `fsx_component` and `s3_files_option` read only the
# stored volume, the read and write volumes and the object size, so two patterns with the same read
# and write volumes price identically at every size. Making the price follow w would mean rewriting
# the capacity-pool share and the S3 Files active share from the working set, and neither is
# measured here; see the three "fixed premises" the generated section states.
#
# The pricing still runs through the existing derivation helpers (`fsx_component`, `fsx_s3ap`,
# `s3_files_option`): `BaselineCell` exposes the same attribute and property names those functions
# read, so object-count, NFS-ops, S3-requests and capacity-pool-billed-requests stay the separate
# quantities they already are in the model rather than being recomputed here.

# How a number in a pattern is known. "sourced": a public document gives the figure or its form.
# "repository": reused from an assumption elsewhere in this repository; not a measurement.
# "placeholder": no source and no repository assumption; placed to make the arithmetic work.
BASELINE_BASES = ("sourced", "repository", "placeholder")

BASELINE_SOURCE_URLS = {
    "efs_url": "https://aws.amazon.com/blogs/storage/scalable-cloud-native-file-storage-at-pennies-per-gb-month-with-amazon-efs/",
    "sizing_url": "https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/",
    "ycsb_url": "https://github.com/brianfrankcooper/YCSB/wiki/Core-Workloads",
    "mlperf_url": "https://mlcommons.org/benchmarks/storage/",
}

# Fixed modelling assumptions of the grid, held constant so the only variables are size and pattern.
BASELINE_EFFICIENCY_SSD = 0.40
BASELINE_POOL_FRACTION = 0.30


@dataclass(frozen=True)
class BaselinePattern:
    """A read/write pattern held as working-set ratio, reads per object and churn rate."""

    key: str  # "P1" ... "P8"
    name: str  # Japanese source text; `t()` supplies the English
    working_set_pct: int  # w: share of stored objects read within the month, in percent
    reads_per_object: int  # n: reads of each working-set object per month
    churn_pct: int  # c: bytes written per month / stored bytes, in percent
    placeholder: (
        bool  # True: no source for the values; placed to make the arithmetic work
    )
    basis: tuple[str, str, str]  # how (w, n, c) are known; each one of BASELINE_BASES
    position: (
        str  # Japanese source text, may carry {w} {n} {c} and the URL placeholders
    )

    def __post_init__(self) -> None:
        if not re.fullmatch(r"P\d+", self.key):
            raise ValueError(f"pattern key must be 'P' and digits: {self.key!r}")
        if not 0 < self.working_set_pct <= 100:
            raise ValueError(f"{self.key}: working_set_pct must be in (0, 100]")
        if not isinstance(self.reads_per_object, int) or self.reads_per_object < 1:
            raise ValueError(f"{self.key}: reads_per_object must be an integer >= 1")
        if not 0 <= self.churn_pct <= 100:
            # Above 100 the writes are no longer replacements of what is stored.
            raise ValueError(f"{self.key}: churn_pct must be in [0, 100]")
        if len(self.basis) != 3 or any(b not in BASELINE_BASES for b in self.basis):
            raise ValueError(f"{self.key}: basis must be 3 values of {BASELINE_BASES}")

    @property
    def read_multiple(self) -> float:
        """R: monthly read volume / stored volume."""
        return self.working_set_pct * self.reads_per_object / 100

    @property
    def touches_whole_volume(self) -> bool:
        """w + c >= 100: reads and writes together may reach every stored object.

        The reads and the writes can overlap, so the sum is only an upper bound on the share
        touched. Below 100 the whole volume cannot be touched; at or above it, it may be.
        """
        return self.working_set_pct + self.churn_pct >= 100


@dataclass(frozen=True)
class BaselineCell:
    """One cell of the common 20 TiB baseline grid: a size crossed with a pattern.

    Stored volume is fixed and logical. The read and write volumes are derived from the pattern, so
    the object count written and the object count read are derived separately and never equated
    with the retained volume. Everything a pricing helper reads off a `Scenario` is provided here
    under the same name.
    """

    pattern: BaselinePattern
    object_mib: float
    stored_gib: float  # common 20 TiB logical, fixed across the grid

    # Fixed modelling assumptions, held constant across the grid so the only variables are size and
    # pattern. Stated here, not buried in the render function.
    efficiency_ssd: float = BASELINE_EFFICIENCY_SSD
    pool_fraction: float = BASELINE_POOL_FRACTION
    deployment: str = "saz1"
    tput_headroom: float = 4.0
    ssd_headroom: float = 0.20
    retention_months: float = 1.0  # steady state: the 20 TiB is resident for the month
    s3files_viable: bool = True
    s3files_threshold_kib: float = S3FILES_DEFAULT_THRESHOLD_KIB
    s3files_expiration_days: float = S3FILES_DEFAULT_EXPIRY_DAYS

    @property
    def file_protocol_required(self) -> bool:
        """The grid is workload-agnostic, so no cell requires NFS/SMB. `s3_only` reads this."""
        return False

    @property
    def object_kib(self) -> float:
        return self.object_mib * 1024

    @property
    def working_set_gib(self) -> float:
        """Bytes read at least once in the month: stored x w."""
        return self.stored_gib * self.pattern.working_set_pct / 100

    @property
    def unread_gib(self) -> float:
        """Bytes not read at all within the month: stored x (1 - w)."""
        return self.stored_gib * (100 - self.pattern.working_set_pct) / 100

    @property
    def read_gib_per_month(self) -> float:
        """Monthly read volume = stored x w x n."""
        return (
            self.stored_gib
            * (self.pattern.working_set_pct * self.pattern.reads_per_object)
            / 100
        )

    @property
    def write_gib_per_month(self) -> float:
        """Monthly write volume = stored x churn rate."""
        return self.stored_gib * self.pattern.churn_pct / 100

    @property
    def objects_stored(self) -> float:
        """Object count = stored bytes / size. Separate from the read and write counts below."""
        return self.stored_gib / self.object_mib * 1024

    @property
    def working_set_objects(self) -> float:
        return self.objects_stored * self.pattern.working_set_pct / 100

    @property
    def objects_per_month(self) -> float:
        """Objects written per month = write volume / size. The S3 PUT / NFS-write count.

        Distinct from `objects_stored`: writing 1 TiB/month into a 20 TiB resident set replaces part
        of it, it does not add to it.
        """
        return self.write_gib_per_month / self.object_mib * 1024

    @property
    def reads_per_month(self) -> float:
        """Objects read per month = read volume / size. The S3 GET / NFS-read count.

        Not the same quantity as the capacity-pool billed request count, which the pricing helper
        derives separately in FabricPool 4 MiB units and which stays UNCONFIRMED (see below).
        """
        return self.read_gib_per_month / self.object_mib * 1024

    @property
    def read_share_pct(self) -> float:
        """Read bytes as a share of read + write bytes. A byte ratio, not an operation-count ratio."""
        return 100 * self.read_gib_per_month / self._moved_gib

    @property
    def write_share_pct(self) -> float:
        return 100 * self.write_gib_per_month / self._moved_gib

    @property
    def _moved_gib(self) -> float:
        return self.read_gib_per_month + self.write_gib_per_month

    @property
    def ingest_gib(self) -> float:
        """Bytes written per month. Used only by the sync landing-area helper if ever called."""
        return self.write_gib_per_month

    @property
    def efficiency_pool(self) -> float:
        return self.efficiency_ssd * POOL_EFFICIENCY_RETENTION

    @property
    def required_mbps(self) -> float:
        """Sustained throughput from read + write volume, in MB/s averaged over the month."""
        return self._moved_gib * 1024 / SECONDS_PER_MONTH


# Common input: 20 TiB logical, the same logical workload presented to both methods. Four object
# sizes crossed with eight patterns; the stored volume is the same 20 TiB in every cell.
BASELINE_STORED_TIB = 20
BASELINE_SIZES_KIB = (64, 1024, 4096, 16384)  # 64 KiB, 1 MiB, 4 MiB, 16 MiB
BASELINE_PATTERNS: tuple[BaselinePattern, ...] = (
    BaselinePattern(
        key="P1",
        name="コールド保管",
        working_set_pct=5,
        reads_per_object=1,
        churn_pct=0,
        placeholder=True,
        basis=("placeholder", "placeholder", "sourced"),
        position="**仮置き**。出典のある値ではなく、算術を通すための仮置き。"
        "作業セット {w}%、回数 {n}、書き込みなし",
    ),
    BaselinePattern(
        key="P2",
        name="全件を 1 回読む",
        working_set_pct=100,
        reads_per_object=1,
        churn_pct=0,
        placeholder=False,
        basis=("sourced", "sourced", "sourced"),
        position="書き込みのない読み取り専用の形。データセット全体を読む点が MLPerf Storage の "
        "Unet3D に近い（[MLPerf Storage]({mlperf_url})）。"
        "YCSB C は読み取りのみだが Zipf 分布で偏って読むため、"
        "全件を 1 回ずつ読む形とは違う（[YCSB]({ycsb_url})）",
    ),
    BaselinePattern(
        key="P3",
        name="ホット 20% を再読",
        working_set_pct=20,
        reads_per_object=5,
        churn_pct=0,
        placeholder=False,
        basis=("sourced", "placeholder", "sourced"),
        position="作業セット比 {w}% は、データの 2 割がホット、8 割がコールドという比を述べる "
        "2 つのブログによる（[EFS ブログ]({efs_url})、"
        "[FSx for ONTAP サイジングブログ]({sizing_url})）。"
        "どちらも算出方法とデータセットを示していない。"
        "**回数 {n} は出典がなく**、R を 1 倍に揃えるために置いた",
    ),
    BaselinePattern(
        key="P4",
        name="小さい作業セットを強く再読",
        working_set_pct=10,
        reads_per_object=10,
        churn_pct=0,
        placeholder=False,
        basis=("repository", "repository", "sourced"),
        position="作業セット {w}% ({ws_gib}) は、本文の「読み取りが繰り返されるとき」の節の"
        "作業セットと同じ大きさ。月 {n} 回は、その節の「読み取り回数に対する感度」表にある行の 1 つ。"
        "その節の本表は月 30 回で、capacity pool の割合も 70%"
        "（この節の固定は {pool_pct}%）と違う。"
        "いずれも本リポジトリの試算前提であり、測定値ではない",
    ),
    BaselinePattern(
        key="P5",
        name="読み多めに少量取り込み",
        working_set_pct=10,
        reads_per_object=10,
        churn_pct=5,
        placeholder=False,
        basis=("repository", "repository", "placeholder"),
        position="読み取りは P4 と同じ（本リポジトリの試算前提）。"
        "書き込みを保存量の {c}%（{write_tib} TiB）とした。"
        "読み : 書きのバイト比は {read_share} : {write_share} で、"
        "YCSB B の読み 95 : 更新 5 に近い形だが、"
        "YCSB B はオペレーション数の比であり同じ量ではない（[YCSB]({ycsb_url})）。"
        "チャーン率 {c}% は置いた値",
    ),
    BaselinePattern(
        key="P6",
        name="読み書き混在",
        working_set_pct=50,
        reads_per_object=4,
        churn_pct=100,
        placeholder=True,
        basis=("placeholder", "placeholder", "placeholder"),
        position="**仮置き**。出典のある値ではなく、算術を通すための仮置き。"
        "作業セット {w}%、回数 {n}、保存量と同量の書き込み",
    ),
    BaselinePattern(
        key="P7",
        name="小オブジェクトの大量書き込み",
        working_set_pct=100,
        reads_per_object=2,
        churn_pct=100,
        placeholder=False,
        basis=("repository", "repository", "repository"),
        position="全オブジェクトを月に 1 回置き換え、各オブジェクトを {n} 回読む形。"
        "「車載 / IoT テレメトリ」の前提（{auto_objects} 個 / 月、64 KiB、読み出し "
        "{auto_reads} 回、保持 1 か月）に沿った形で、本リポジトリの試算前提。"
        "違う点が 3 つある。保存量はその節の {auto_stored} ではなく {stored_tib} TiB に揃える。"
        "capacity pool の割合はその節の {auto_pool_pct}% ではなくこの節の {pool_pct}%、"
        "SSD の圧縮率はその節の {auto_eff_pct}% ではなくこの節の {eff_pct}%。"
        "64 KiB のとき書き込みは {objs_64k} 個（その節は {auto_objects} 個）",
    ),
    BaselinePattern(
        key="P8",
        name="書き込み中心",
        working_set_pct=10,
        reads_per_object=1,
        churn_pct=100,
        placeholder=True,
        basis=("placeholder", "placeholder", "placeholder"),
        position="**仮置き**。出典のある値ではなく、算術を通すための仮置き。"
        "作業セット {w}%、回数 {n}、保存量と同量の書き込み",
    ),
)


def baseline_cells() -> list[BaselineCell]:
    stored_gib = BASELINE_STORED_TIB * GIB_PER_TIB
    return [
        BaselineCell(pattern=pattern, object_mib=kib / 1024, stored_gib=stored_gib)
        for pattern in BASELINE_PATTERNS
        for kib in BASELINE_SIZES_KIB
    ]


def baseline_same_price_groups() -> list[list[BaselinePattern]]:
    """Patterns whose subtotals are identical at every size, for both priced methods.

    Derived from the prices themselves rather than from the inputs, so it stays true if the pricing
    ever starts to depend on the working-set ratio: the group then disappears instead of the
    document going on to claim it.
    """
    by_signature: dict[tuple[float, ...], list[BaselinePattern]] = {}
    for pattern in BASELINE_PATTERNS:
        signature: list[float] = []
        for cell in baseline_cells():
            if cell.pattern is not pattern:
                continue
            files = s3_files_option(cell, split_metadata=True)
            assert files is not None  # the grid is always viable for S3 Files
            signature += [
                round(sum(fsx_s3ap(cell).values()), 6),
                round(sum(files.values()), 6),
            ]
        by_signature.setdefault(tuple(signature), []).append(pattern)
    return [group for group in by_signature.values() if len(group) > 1]


def baseline_s3_only(cell: BaselineCell) -> dict[str, float] | None:
    """S3 alone, for the patterns with no writes only.

    The write path differs by method (an S3 API PUT, an NFS write plus a sync, a PUT through S3
    Access Points), and one table for all of them would mix the write assumptions. This is a choice
    of scope for the grid, not a statement that S3 alone cannot take writes.
    """
    return s3_only(cell) if cell.pattern.churn_pct == 0 else None


def _size_label(kib: float) -> str:
    return f"{kib:,.0f} KiB" if kib < 1024 else f"{kib / 1024:,.0f} MiB"


def _tib(value_gib: float) -> str:
    return f"{value_gib / GIB_PER_TIB:g}"


def _keys(patterns: list[BaselinePattern]) -> str:
    return t("・").join(p.key for p in patterns)


def _whole(value: float) -> int:
    """An object count is a whole number; refuse to round away a fraction."""
    rounded = round(value)
    if abs(value - rounded) > 1e-6:
        raise ValueError(f"expected a whole number, got {value!r}")
    return int(rounded)


def _position_fields(pattern: BaselinePattern) -> dict[str, object]:
    """Values a pattern's `position` text may interpolate, all derived from the model."""
    telemetry = next(sc for sc in SCENARIOS if sc.key == "telemetry")
    stored_gib = BASELINE_STORED_TIB * GIB_PER_TIB
    probe = BaselineCell(pattern=pattern, object_mib=64 / 1024, stored_gib=stored_gib)
    return {
        "w": pattern.working_set_pct,
        "n": pattern.reads_per_object,
        "c": pattern.churn_pct,
        "ws_gib": gib(probe.working_set_gib),
        "write_tib": _tib(probe.write_gib_per_month),
        "read_share": f"{probe.read_share_pct:.1f}",
        "write_share": f"{probe.write_share_pct:.1f}",
        "objs_64k": f"{probe.objects_per_month:,.0f}",
        "stored_tib": BASELINE_STORED_TIB,
        "pool_pct": f"{BASELINE_POOL_FRACTION:.0%}".rstrip("%"),
        "eff_pct": f"{BASELINE_EFFICIENCY_SSD:.0%}".rstrip("%"),
        "auto_objects": f"{telemetry.objects_per_month:,}",
        "auto_reads": f"{telemetry.reads_per_object:g}",
        "auto_stored": gib(telemetry.stored_gib),
        "auto_pool_pct": f"{telemetry.pool_fraction:.0%}".rstrip("%"),
        "auto_eff_pct": f"{telemetry.efficiency_ssd:.0%}".rstrip("%"),
    }


def baseline_position(pattern: BaselinePattern) -> str:
    return t(pattern.position, **BASELINE_SOURCE_URLS, **_position_fields(pattern))


def _baseline_cell_rows(cell: BaselineCell) -> list[list[str]]:
    """The ten rows of a cell's derived-quantity table. Rows 1-8 are the items every cell shows."""
    p = cell.pattern
    stored = gib(cell.stored_gib)
    ws = gib(cell.working_set_gib)
    written = gib(cell.write_gib_per_month)

    if p.working_set_pct == 100:
        working_set = t(
            "100% = 保存量の全体 ({gib}) / {count} 個。月内に全件が読まれる",
            gib=stored,
            count=f"{cell.working_set_objects:,.0f}",
        )
    else:
        working_set = t(
            "{pct}% = {gib} ({tib} TiB) / {count} 個。残り {rest_pct}% ({rest_gib}) は月内に読まれない",
            pct=p.working_set_pct,
            gib=ws,
            tib=_tib(cell.working_set_gib),
            count=f"{cell.working_set_objects:,.0f}",
            rest_pct=100 - p.working_set_pct,
            rest_gib=gib(cell.unread_gib),
        )

    if p.churn_pct == 0:
        write_row = t("0 GiB / 0 個 / チャーン率 0% (書き込みなし)")
        retention = t(
            "書き込みなし。保存量は {gib} のまま一定。"
            "書き込みがあるパターンでも、書き込みは既存オブジェクトの置き換えで保存量は変わらない",
            gib=stored,
        )
    else:
        write_row = t(
            "{gib} ({tib} TiB) / {count} 個 / チャーン率 {pct}% (保存量の {ratio} 倍)",
            gib=written,
            tib=_tib(cell.write_gib_per_month),
            count=f"{cell.objects_per_month:,.0f}",
            pct=p.churn_pct,
            ratio=f"{p.churn_pct / 100:g}",
        )
        retention = t(
            "書き込みは既存オブジェクトの置き換えで、保存量は {gib} のまま一定。月を通して積み増さない",
            gib=stored,
        )

    return [
        [
            t("1. 保存量 (論理) と保存オブジェクト数"),
            t(
                "{gib} ({tib} TiB) / {count} 個",
                gib=stored,
                tib=_tib(cell.stored_gib),
                count=f"{cell.objects_stored:,.0f}",
            ),
        ],
        [t("2. オブジェクトサイズ"), _size_label(cell.object_kib)],
        [t("3. 作業セット (月内に読まれる部分)"), working_set],
        [
            t("4. 作業セット内の読み取り回数"),
            t("作業セットの各オブジェクトを月 {n} 回", n=p.reads_per_object),
        ],
        [
            t("5. 月間読み取り (バイト / 回数 / 保存量に対する倍数 R)"),
            t(
                "{gib} ({tib} TiB) = {ws_gib} × {n} 回 / {requests} 回 / R = {r} 倍",
                gib=gib(cell.read_gib_per_month),
                tib=_tib(cell.read_gib_per_month),
                ws_gib=ws,
                n=p.reads_per_object,
                requests=f"{cell.reads_per_month:,.0f}",
                r=f"{p.read_multiple:g}",
            ),
        ],
        [
            t("6. 月間書き込み (バイト / 個数 / 保存量に対する比 = チャーン率)"),
            write_row,
        ],
        [
            t("7. 読み : 書き (バイト比。操作数の比ではない)"),
            f"{cell.read_share_pct:.1f} : {cell.write_share_pct:.1f}",
        ],
        [t("8. リテンション"), retention],
        [
            t("capacity pool 課金リクエスト数"),
            t("未確認 (GET あたりの回数が未測定)"),
        ],
        [t("平均所要スループット"), f"{cell.required_mbps:,.1f} MB/s"],
    ]


def render_baseline_grid() -> list[str]:
    """The common 20 TiB baseline: 4 object sizes x 8 patterns, both methods per cell.

    Thirty-two cells, each giving the FSx-for-ONTAP and S3-Files breakdowns (and S3 alone where the
    pattern has no writes) with a subtotal. Every subtotal is a 主要費目小計, not a 月額総額: the
    capacity-pool read-request count is left UNCONFIRMED, so no total is complete and none is
    labelled as if it were.
    """
    patterns = BASELINE_PATTERNS
    sizes = ", ".join(_size_label(k) for k in BASELINE_SIZES_KIB)
    stored_gib = BASELINE_STORED_TIB * GIB_PER_TIB
    groups = baseline_same_price_groups()
    same_price = t(" と ").join(f"({_keys(group)})" for group in groups)
    small = [p for p in patterns if not p.touches_whole_volume]
    large = [p for p in patterns if p.touches_whole_volume]
    placeholders = [p for p in patterns if p.placeholder]
    repo_based = [p for p in patterns if "repository" in p.basis]
    read_only = [p for p in patterns if p.churn_pct == 0]
    parameter_names = (
        t("{key} の作業セット比"),
        t("{key} の回数"),
        t("{key} のチャーン率"),
    )
    unsourced = [
        parameter_names[i].format(key=p.key)
        for p in patterns
        if not p.placeholder
        for i, basis in enumerate(p.basis)
        if basis == "placeholder"
    ]
    example = next(p for p in patterns if p.key == "P4")
    example_cell = next(
        c for c in baseline_cells() if c.pattern is example and c.object_kib == 4096
    )

    out = [
        t("### 共通ベースライン — 20 TiB を同じ条件で"),
        "",
        t(
            "ここまでのユースケース別の試算は、ワークロードごとに前提が違う。"
            "それぞれが現実のどれかに寄っているぶん、方式そのものの差を同じ土俵で見るには向かない。"
            "この節は逆に、**論理 20 TiB という 1 つの土俵**を固定し、"
            "オブジェクトサイズ ({sizes}) と、{count} つの読み書きパターン ({first}〜{last}) だけを振る。"
            "各パターンは、作業セット比・作業セット内の読み取り回数・チャーン率の 3 つで決まり、"
            "月間の読み取り量と書き込み量はそこから導く。"
            "両方式に同じ論理ワークロードを与える。",
            sizes=sizes,
            count=len(patterns),
            first=patterns[0].key,
            last=patterns[-1].key,
        ),
        "",
        t(
            "保存量 (論理) はどのセルでも 20 TiB で固定である。"
            "書き込みは既存オブジェクトの置き換えで、月を通して積み増さない。"
            "**月間書き込み量を平均保持量と同一視しない**。"
            "20 TiB の定常保存に対して、月に 1 TiB 書くとはその一部を置き換えることであって、"
            "積み増すことではない。",
        ),
        "",
        t(
            "各セルは 4 つの量を別々に導く。"
            "**保存オブジェクト数** (保存バイト / サイズ)、"
            "**月間書き込みオブジェクト数** (書き込み量 / サイズ、S3 の PUT と NFS の書き込み操作に対応)、"
            "**月間読み取り回数** (読み取り量 / サイズ、S3 の GET と NFS の読み取り操作に対応)、"
            "そして **capacity pool の課金リクエスト数** である。"
            "最後の 1 つは FabricPool の 4 MiB 単位の読み取り操作数で、"
            "GET 1 回あたりの回数は**未確認 (UNCONFIRMED)** のまま置く。"
            "この 4 つを同じ数として扱わない。"
        ),
        "",
        t("#### 式と読み方の例"),
        "",
        t("各セルの量は、次の 5 本の式で導く。"),
        "",
        "```text",
        t("月間読み取り量 = 保存量 × 作業セット比 × 作業セット内の読み取り回数"),
        t("月間読み取り回数 = 月間読み取り量 ÷ オブジェクトサイズ"),
        t("保存量に対する倍数 R = 作業セット比 × 作業セット内の読み取り回数"),
        t("月間書き込み量 = 保存量 × チャーン率"),
        t("月間書き込み個数 = 月間書き込み量 ÷ オブジェクトサイズ"),
        "```",
        "",
        t(
            "例: {key} は、保存量 {stored} のうち {w}% ({ws}) を作業セットとし、"
            "その各オブジェクトを月 {n} 回読む。"
            "月間読み取り量は {ws} × {n} = {read} で、保存量の {r} 倍 (R = {r}) になる。"
            "{size} なら {ws_objects} 個を {n} 回読むので {requests} 回。"
            "残り {rest_pct}% ({rest}) は月内に一度も読まれない。"
            "「オブジェクトを月 N 回読む」とだけ書くと、"
            "N 回の対象が全オブジェクトか作業セットかで総量が {factor:g} 倍変わる。"
            "この節では対象を作業セットと明記し、総量を保存量との倍数 R でも示す。",
            key=example.key,
            stored=gib(stored_gib),
            w=example.working_set_pct,
            ws=gib(example_cell.working_set_gib),
            n=example.reads_per_object,
            read=gib(example_cell.read_gib_per_month),
            r=f"{example.read_multiple:g}",
            size=_size_label(example_cell.object_kib),
            ws_objects=f"{example_cell.working_set_objects:,.0f}",
            requests=f"{example_cell.reads_per_month:,.0f}",
            rest_pct=100 - example.working_set_pct,
            rest=gib(example_cell.unread_gib),
            factor=100 / example.working_set_pct,
        ),
        "",
        t(
            "作業セット比と回数は、月間読み取り量を分解して示す軸である。"
            "この表の金額は、月間読み取り量・月間書き込み量・オブジェクトサイズだけで決まり、"
            "作業セット比には連動しない。"
            "月間の読み取り量・書き込み量が同じパターン {groups} は、どのサイズでも金額が同じになる。",
            groups=same_price,
        ),
        "",
        t(
            "この表の 3 つの前提は作業セット比と切り離している。"
            "(a) FSx for ONTAP の capacity pool は全パターンで保存量の {pool}%。"
            "(b) S3 Files の高性能ストレージ ({threshold} KiB 以下のサイズ) は保存量の全量をアクティブとして計上。"
            "(c) 書き込みのないセルの S3 Files ({threshold} KiB 以下) は、"
            "初回読み出しのストリームを計上せず、読み取りをすべて高性能ストレージの読み取りとして計上。"
            "{small_groups} は、作業セット比とチャーン率の和が 100% 未満で、保存量の全体には触れられない。"
            "(a)(b) を触れられる量に合わせる前提に置き換えると、小計は下がる向きになる。"
            "{large_groups} は和が 100% 以上で、保存量の全体に及びうる。"
            "全体に及ぶと置いて (a) を置き換えると、FSx for ONTAP の小計は上がる向きになる。"
            "どちらの向きも試算上の感度で、測定ではない。",
            pool=f"{BASELINE_POOL_FRACTION:.0%}".rstrip("%"),
            threshold=f"{S3FILES_DEFAULT_THRESHOLD_KIB:g}",
            small_groups=_keys(small),
            large_groups=_keys(large),
        ),
        "",
        t("#### パターンの一覧"),
        "",
        *table(
            [
                t("パターン"),
                t("名前"),
                t("作業セット比"),
                t("作業セット内の回数"),
                t("月間読み取り量 (R)"),
                t("月間書き込み量 (チャーン率)"),
                t("読み : 書き (バイト比)"),
                t("位置づけ"),
            ],
            [
                [
                    p.key,
                    t(p.name),
                    f"{p.working_set_pct}%",
                    t("{n} 回", n=p.reads_per_object),
                    t(
                        "{gib} (R = {r} 倍)",
                        gib=gib(
                            stored_gib * p.working_set_pct * p.reads_per_object / 100
                        ),
                        r=f"{p.read_multiple:g}",
                    ),
                    t("0 GiB (書き込みなし)")
                    if p.churn_pct == 0
                    else t(
                        "{gib} (チャーン率 {pct}%)",
                        gib=gib(stored_gib * p.churn_pct / 100),
                        pct=p.churn_pct,
                    ),
                    _ratio_text(stored_gib, p),
                    baseline_position(p),
                ]
                for p in patterns
            ],
        ),
        "",
        t(
            "{placeholders} の値は出典がなく、算術を通すために置いた。"
            "{repo_assumed} の値のうち表の位置づけで「試算前提」と書いたものは、"
            "本リポジトリの試算前提であって測定値ではない。"
            "{unsourced}は、出典も試算前提もなく置いた値である。",
            placeholders=_keys(placeholders),
            repo_assumed=_keys(repo_based),
            unsourced=t("、").join(unsourced),
        ),
        "",
        t(
            "両方式とも、下の内訳は**主要費目小計**であって月額総額ではない。"
            "capacity pool の読み取りリクエスト数が未確認であること、"
            "および S3 のバージョニング非現行版・バックアップ・通信費を算入していないことによる。"
            "S3 Files の内訳は、4 KiB × 操作のメタデータ課金を取り込み側と読み取り側の別行で示し、"
            "どちらも小計に算入している。"
            "S3 Files のメタデータ行 (4 KiB × 操作) は、1 MiB 以上の読み取りにも立つかを未確認のまま小計に算入している。"
            "除いた場合の小計は、`python3 tools/finops_model.py --baseline-json` の "
            "`subtotal_excluding_metadata_usd` で読める。"
        ),
        "",
        t(
            "S3 単独の内訳表は、書き込みのないパターン ({read_only}) にだけ置く。"
            "方式ごとに書き込みの経路 (S3 API の PUT、NFS の書き込みと同期、S3 Access Points 経由の PUT) が違い、"
            "同じ表に並べると書き込みの前提が混ざるためである。"
            "範囲の決めであって、書き込みを含む S3 単独の構成が成り立たないという主張ではない。",
            read_only=_keys(read_only),
        ),
        "",
    ]

    # Metadata block: the same provenance every cost table in this document carries.
    dep = DEPLOYMENTS["saz1"]
    out += [
        *table(
            [t("項目"), t("値")],
            [
                [t("リージョン"), f"`{REGION}` ({t(REGION_LABEL)})"],
                [t("単価スナップショット"), PRICE_SNAPSHOT],
                [t("通貨"), t("USD、税別")],
                [t("保存量 (論理、全セル共通)"), gib(stored_gib)],
                [t("デプロイ"), f"{t(dep['label'])} (`{dep['api']}`)"],
                [
                    t("ストレージ効率の仮定 (SSD / プール層)"),
                    f"{BASELINE_EFFICIENCY_SSD:.0%} / "
                    f"{BASELINE_EFFICIENCY_SSD * POOL_EFFICIENCY_RETENTION:.0%}",
                ],
                [t("キャパシティプールへ落とす割合"), f"{BASELINE_POOL_FRACTION:.0%}"],
                [
                    t("1 か月の秒数"),
                    t(
                        "{seconds} 秒 (30 × 24 × 3600)",
                        seconds=f"{SECONDS_PER_MONTH:,}",
                    ),
                ],
                [t("GiB / GB-Mo の換算"), t("論理 GiB を GB-Mo の単価に当てる")],
            ],
        ),
        "",
    ]

    for cell in baseline_cells():
        out += [
            t(
                "#### パターン {pattern} — オブジェクト {size}",
                pattern=cell.pattern.key,
                size=_size_label(cell.object_kib),
            ),
            "",
            *table([t("導出量"), t("値")], _baseline_cell_rows(cell)),
            "",
        ]

        no_first_read_stream = (
            cell.pattern.churn_pct == 0
            and cell.object_kib <= cell.s3files_threshold_kib
        )
        for label, lines, note in (
            (t("FSx for ONTAP S3 AP (この構成)"), fsx_s3ap(cell), None),
            (
                t("S3 バケット + S3 Files"),
                s3_files_option(cell, split_metadata=True),
                t(
                    "書き込みがないセルの S3 Files ({threshold} KiB 以下) は、"
                    "初回読み出しのストリームを計上しない。"
                    "読み取りはすべて高性能ストレージの読み取りとして計上している",
                    threshold=f"{S3FILES_DEFAULT_THRESHOLD_KIB:g}",
                )
                if no_first_read_stream
                else None,
            ),
            (
                t("S3 単独 (利用側も S3 API)"),
                baseline_s3_only(cell),
                None,
            ),
        ):
            if lines is None:
                continue
            subtotal = sum(lines.values())
            rows = [[item, usd(cost)] for item, cost in lines.items()]
            rows.append(
                [
                    t("**主要費目小計 / major-line-item subtotal**"),
                    f"**{usd(subtotal)}**",
                ]
            )
            out += [f"**{label}**", "", *table([t("内訳"), t("月額")], rows), ""]
            if note:
                out += [note, ""]

    return out


def _ratio_text(stored_gib: float, pattern: BaselinePattern) -> str:
    """Read : write byte ratio of a pattern. Size does not change it, so any cell would do."""
    probe = BaselineCell(pattern=pattern, object_mib=1.0, stored_gib=stored_gib)
    return f"{probe.read_share_pct:.1f} : {probe.write_share_pct:.1f}"


# ------------------------------------------------------------------------ machine-readable


def _in_language[T](lang: str, build: Callable[[], T]) -> T:
    """Run `build()` with the module language set to `lang`, then put the previous one back."""
    global _LANG
    if lang not in LANGS:
        raise SystemExit(f"finops-model: unknown language {lang!r}")
    previous, _LANG = _LANG, lang
    try:
        return build()
    finally:
        _LANG = previous


def _method_json(lines: dict[str, float]) -> dict[str, object]:
    subtotal = sum(lines.values())
    return {
        "lines": [{"label": label, "usd": usd_} for label, usd_ in lines.items()],
        "subtotal_usd": subtotal,
        "subtotal_display": usd(subtotal),
    }


def baseline_json(lang: str = "ja") -> dict[str, object]:
    """The baseline grid as plain data, derived from the same cells the document is rendered from.

    A figure that reads this does not retype a number. Nothing here is computed a second time: the
    quantities are the `BaselineCell` properties and the amounts are the pricing helpers' lines.
    `lines[].label` and `position` follow `lang`; `name_ja` and `name_en` are always both present.
    """

    def build() -> dict[str, object]:
        cells = baseline_cells()
        sample = cells[0]
        stored_gib = BASELINE_STORED_TIB * GIB_PER_TIB
        patterns: list[dict[str, object]] = []
        for pattern in BASELINE_PATTERNS:
            cell_docs: list[dict[str, object]] = []
            for cell in (c for c in cells if c.pattern is pattern):
                files_lines = s3_files_option(cell, split_metadata=True)
                assert files_lines is not None
                ingest_usd, read_usd = s3_files_metadata_usd(cell)
                files = _method_json(files_lines)
                files["metadata_usd"] = {"ingest": ingest_usd, "read": read_usd}
                files["subtotal_excluding_metadata_usd"] = (
                    sum(files_lines.values()) - ingest_usd - read_usd
                )
                direct = baseline_s3_only(cell)
                cell_docs.append(
                    {
                        "size_kib": _whole(cell.object_kib),
                        "stored_objects": _whole(cell.objects_stored),
                        "working_set_gib": cell.working_set_gib,
                        "working_set_objects": _whole(cell.working_set_objects),
                        "unread_gib": cell.unread_gib,
                        "read_gib": cell.read_gib_per_month,
                        "read_requests": _whole(cell.reads_per_month),
                        "write_gib": cell.write_gib_per_month,
                        "write_objects": _whole(cell.objects_per_month),
                        "average_mbps": cell.required_mbps,
                        "methods": {
                            "fsx_s3ap": _method_json(fsx_s3ap(cell)),
                            "s3_files": files,
                            "s3_direct": None
                            if direct is None
                            else _method_json(direct),
                        },
                    }
                )
            probe = next(c for c in cells if c.pattern is pattern)
            patterns.append(
                {
                    "id": pattern.key,
                    "name_ja": pattern.name,
                    "name_en": _in_language("en", lambda p=pattern: t(p.name)),
                    "working_set_pct": pattern.working_set_pct,
                    "reads_per_object": pattern.reads_per_object,
                    "churn_pct": pattern.churn_pct,
                    "read_multiple": pattern.read_multiple,
                    "read_write_byte_ratio_pct": [
                        round(probe.read_share_pct, 1),
                        round(probe.write_share_pct, 1),
                    ],
                    "placeholder": pattern.placeholder,
                    "basis": dict(
                        zip(
                            ("working_set", "reads_per_object", "churn"),
                            pattern.basis,
                            strict=True,
                        )
                    ),
                    "position": baseline_position(pattern),
                    "cells": cell_docs,
                }
            )
        return {
            "schema_version": 1,
            "generated_by": "tools/finops_model.py --baseline-json",
            "region": REGION,
            "price_snapshot": PRICE_SNAPSHOT,
            "currency": "USD",
            "stored_gib": _whole(stored_gib),
            "sizes_kib": list(BASELINE_SIZES_KIB),
            "pricing_depends_on_working_set": False,
            "price_inputs": ["object_size", "read_bytes", "write_bytes"],
            "fixed_premises": [
                "fsx_capacity_pool_share_is_fixed_in_every_pattern",
                "s3files_high_performance_storage_is_fully_active_at_or_below_threshold",
                "s3files_books_no_first_read_stream_when_there_are_no_writes",
            ],
            "assumptions": {
                "deployment": DEPLOYMENTS[sample.deployment]["api"],
                "efficiency_ssd": sample.efficiency_ssd,
                "pool_fraction": sample.pool_fraction,
                "retention_months": sample.retention_months,
                "s3files_threshold_kib": sample.s3files_threshold_kib,
                "s3files_expiration_days": sample.s3files_expiration_days,
            },
            "patterns": patterns,
        }

    return _in_language(lang, build)


def render(lang: str = "ja") -> str:
    global _LANG
    if lang not in LANGS:
        raise SystemExit(f"finops-model: unknown language {lang!r}")
    _LANG = lang
    out = [
        BEGIN,
        "",
        t("<!-- 生成物。編集しない。tools/finops_model.py で再生成する -->"),
        "",
        *render_prices(),
        *render_request_asymmetry(),
        *render_floor(),
        *render_object_size_sensitivity(),
        t("### ユースケース別の試算"),
        "",
        t(
            "いずれも**試算**であり実測ではない。単価は上の単価表、使用量は各表の前提に置いた仮定である。"
        ),
        t(
            "自分のワークロードで置き換えるべき値は、月間オブジェクト数、平均オブジェクトサイズ、"
            "保持期間、読み出し回数、ストレージ効率の 5 つ。"
        ),
        "",
    ]
    for sc in SCENARIOS:
        out += render_scenario(sc)
    out += render_baseline_grid()
    out += render_read_heavy()
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


def translation_gaps() -> tuple[list[str], list[str]]:
    """What still stands between the model and an English document.

    Two kinds, and the second is the one that matters. Missing keys are strings that reached `t()`
    with no English entry. Residue is Japanese in the rendered English output — which catches the
    larger class: a string that never reached `t()` at all. Counting only the missing keys would have
    reported zero before a single call site was converted, and reported the model ready.

    Missing keys are collected by rendering repeatedly, because the first miss aborts the render and
    everything after it goes unseen.
    """
    global _LANG
    missing: list[str] = []
    while True:
        try:
            block = render("en")
            break
        except MissingTranslation as gap:
            if gap.source in missing:  # a stand-in that did not get us further
                block = ""
                break
            missing.append(gap.source)
            TRANSLATIONS[gap.source] = (
                gap.source
            )  # stand in, only to reach the next gap
    for source in missing:
        TRANSLATIONS.pop(source, None)
    _LANG = "ja"
    residue = [line for line in block.split("\n") if CJK.search(line)]
    return missing, residue


def splice(text: str, block: str, doc: Path) -> str:
    pattern = re.compile(re.escape(BEGIN) + r".*?" + re.escape(END), re.DOTALL)
    if not pattern.search(text):
        raise SystemExit(f"{doc}: markers {BEGIN} / {END} not found")
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
    parser.add_argument(
        "--translation-gaps",
        action="store_true",
        help="list the generated strings that have no English entry yet",
    )
    parser.add_argument(
        "--baseline-json",
        action="store_true",
        help="print the common baseline grid as JSON (figures read this instead of retyping numbers)",
    )
    parser.add_argument(
        "--lang",
        choices=LANGS,
        default=None,
        help="language of the labels in --baseline-json output (default: ja)",
    )
    args = parser.parse_args()

    if args.lang and not args.baseline_json:
        parser.error("--lang only applies to --baseline-json")
    if args.baseline_json:
        if args.write or args.check or args.show_prices or args.translation_gaps:
            parser.error(
                "--baseline-json cannot be combined with --write, --check, "
                "--show-prices or --translation-gaps"
            )
        print(
            json.dumps(baseline_json(args.lang or "ja"), ensure_ascii=False, indent=2)
        )
        return 0

    if args.show_prices:
        show_prices()
        return 0

    if args.translation_gaps:
        missing, residue = translation_gaps()
        for source in missing:
            print(f"no entry: {source}")
        for line in residue:
            print(f"residue : {line}")
        print(
            f"\n{len(missing)} string(s) without an English entry, "
            f"{len(residue)} line(s) of Japanese left in the English render",
            file=sys.stderr,
        )
        return 0

    if not (args.write or args.check):
        print(render(), end="")
        return 0

    # English is skipped, not half-written, while any string is still untranslated. A document that
    # renders with Japanese left in it would pass this script and fail `make en-lang` later, with the
    # cause several steps back.
    #
    # Skipping is only tolerable while the English document does not exist yet. Once it does, a new
    # gap would mean this script silently stopped maintaining a document that is still in the
    # repository: `--check` would compare Japanese, report "current", and leave the English tables
    # frozen at whatever the prices were when the last gap was closed. So the same condition is a
    # warning before the promotion and an error after it.
    missing, residue = translation_gaps()
    gaps = len(missing) + len(residue)
    if gaps and doc_for("en").exists():
        print(
            f"finops-model: {len(missing)} string(s) without an English entry and "
            f"{len(residue)} line(s) of Japanese in the English render, but "
            f"{doc_for('en').relative_to(ROOT)} exists. Its cost tables cannot be regenerated "
            "until every string is translated.\n"
            "  Run: python3 tools/finops_model.py --translation-gaps",
            file=sys.stderr,
        )
        return 1
    languages = LANGS if not gaps else ("ja",)
    if gaps:
        print(
            f"finops-model: {len(missing)} string(s) without an English entry and "
            f"{len(residue)} line(s) of Japanese in the English render; generating Japanese only. "
            "Run --translation-gaps to list them.",
            file=sys.stderr,
        )

    stale: list[str] = []
    for lang in languages:
        doc = doc_for(lang)
        if not doc.exists():
            if lang == "ja":
                raise SystemExit(f"{doc}: not found")
            continue  # the English document is created by the promotion, not by this script
        original = doc.read_text(encoding="utf-8")
        updated = splice(original, render(lang), doc)
        if updated == original:
            continue
        if args.write:
            doc.write_text(updated, encoding="utf-8")
            print(f"finops-model: rewrote {doc.relative_to(ROOT)}")
        else:
            stale.append(str(doc.relative_to(ROOT)))

    if args.check and stale:
        print(
            "finops-model: generated cost tables are stale in "
            + ", ".join(stale)
            + "\n  Run: python3 tools/finops_model.py --write",
            file=sys.stderr,
        )
        return 1
    print("finops-model: current")
    return 0


if __name__ == "__main__":
    sys.exit(main())
