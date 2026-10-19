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
from itertools import pairwise
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
    # Shared assumption fields, carried on both Scenario and BaselineCell so a pricing helper reads
    # the same name on either. Every default here reproduces the current formula: None means "model
    # chooses" (throughput, active fraction), and POOL_EFFICIENCY_RETENTION / "written" / "none" are
    # the values the model already used. See ASSUMPTION_SPECS for the public keys.
    pool_efficiency_retention: float = POOL_EFFICIENCY_RETENTION
    throughput_mbps: int | None = None
    active_fraction: float | None = None
    first_read_mode: str = "written"
    first_read_stream_billing: str = "none"

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
        return self.efficiency_ssd * self.pool_efficiency_retention

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
    # None means the model chooses the tier; a reader's explicit value skips choose_throughput.
    tput = (
        choose_throughput(sc.required_mbps, dep["tput_options"], sc.tput_headroom)
        if sc.throughput_mbps is None
        else sc.throughput_mbps
    )

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

    The read-side operation count carries `metadata_multiplier`, a BaselineCell-only field left at
    1.0 by default; a Scenario does not have it, so `getattr` keeps the current formula for it. The
    import side is never multiplied: the observation behind the multiplier is of the read-side
    metadata metric, and the ingest-side metric could not be told apart from zero. See
    ASSUMPTION_SPECS for `metadata_multiplier`.
    """
    metadata_gib = S3FILES_METADATA_KIB / (1024 * 1024)
    read_multiplier = getattr(sc, "metadata_multiplier", 1.0)
    return (
        sc.objects_per_month * metadata_gib * S3FILES["write"].usd,
        sc.reads_per_month * metadata_gib * read_multiplier * S3FILES["read"].usd,
    )


def _is_round_percent(fraction: float) -> bool:
    """True when `fraction * 100` is a whole number within floating-point tolerance.

    The equality is deliberately not exact: `0.07 * 100` is 7.0000000000000009, not 7, so a strict
    comparison would push the baseline's 100% onto the one-decimal path and break byte equality.
    """
    return abs(fraction * 100 - round(fraction * 100)) < 1e-9


def _resolve_first_read_objects(sc: Scenario | BaselineCell) -> float:
    """How many objects are streamed on first read, from `first_read_mode`.

    "written" is the current default (objects written this month). "none" counts nothing.
    "working_set" counts the working-set objects, a BaselineCell-only quantity; a Scenario has no
    working set, so the mode is only valid on a cell (parse/validate forbids it on a Scenario).
    """
    mode = sc.first_read_mode
    if mode == "none":
        return 0.0
    if mode == "working_set":
        working_set = getattr(sc, "working_set_objects", None)
        if working_set is None:
            raise ValueError(
                "first_read_mode='working_set' needs working_set_objects (BaselineCell only)"
            )
        return float(working_set)
    return float(sc.objects_per_month)


def s3_files_option(
    sc: Scenario | BaselineCell,
    split_metadata: bool = False,
    first_read_objects: float | None = None,
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
    on first read does not emit the zero-valued stream line.

    `first_read_objects` is how many objects are read for the first time, and so streamed from the
    bucket, in the month. The default is the objects written in the month: the model counts a first
    read only for an object it has just written, so a scenario with no writes streams nothing. An
    object that already sits in the bucket is also read for the first time through the file system,
    and the model does not count that. A caller can pass the number to see what counting it does,
    and what it sees is partial: passing it adds the GET requests and removes the same reads from
    high-performance storage, and leaves out the import write (`S3FILES["write"]`, at least
    `S3FILES_MIN_IO_KIB`) that a first read also brings. That write is not derived from the read
    count: the default trigger imports the data of every file at or below the threshold when a
    directory is first accessed, so its size depends on which directories are touched. The net
    direction of counting the first read is therefore not determined by this model.
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

    # C1 (PR-A2): non-current versions are extra S3 Standard storage. S3 Files requires bucket
    # versioning and keeps old versions on every edit (documented: the S3 Files sync page), so a
    # reader who retains them pays for the extra GiB. Priced as the marginal tiered cost on top of
    # the current volume. Default 0 books nothing, so the baseline output is unchanged.
    noncurrent_gib = getattr(sc, "noncurrent_version_gib", 0.0)
    if noncurrent_gib > 0:
        lines[t("S3 Standard 非現行バージョンの保持")] = tiered_s3_storage(
            sc.stored_gib + noncurrent_gib
        ) - tiered_s3_storage(sc.stored_gib)

    if object_kib <= sc.s3files_threshold_kib:
        retention_days = sc.retention_months * 30.0
        # None (default) keeps the retention-window formula; a reader's value is used as given.
        active = (
            min(1.0, sc.s3files_expiration_days / retention_days)
            if sc.active_fraction is None
            else sc.active_fraction
        )
        # Large file reads (1 MiB or larger file IO) are always streamed directly from the bucket,
        # even when the file sits on high-performance storage, and carry an S3 GET plus a 4 KiB
        # metadata read with no file read charge. The metering page states this of the I/O size, not
        # the file size; this model treats one read as reading the whole object, so a file of 1 MiB
        # or more is read with a 1 MiB-or-larger I/O. That assumption is stated in the note, and the
        # real I/O size (NFS rsize and similar) is unverified. The default threshold is 128 KiB, so
        # no object of 1 MiB or more enters this branch by default and the default output is
        # unchanged; large_io only becomes true once the threshold is raised to 1 MiB or more.
        #   https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html
        large_io = object_kib >= 1024.0
        # A file smaller than the minimum billable size is charged as that size.
        floor_factor = max(1.0, S3FILES_MIN_FILE_KIB / object_kib)
        hps_gib = sc.stored_gib * active * floor_factor
        io_kib = max(object_kib, S3FILES_MIN_IO_KIB)
        import_gib = sc.objects_per_month * io_kib / (1024 * 1024)
        # The first read of a file not yet on high-performance storage is streamed from the bucket
        # and carries an S3 GET plus a metadata read, with no file read charge. It is that read
        # which triggers the asynchronous import. Only the reads after it are served from
        # high-performance storage and metered as file reads.
        #
        # An explicit `first_read_objects` (used by the sensitivity helper) wins. Otherwise
        # `first_read_mode` decides: "written" is the current default (objects written this month),
        # "none" counts nothing, "working_set" counts the working-set objects.
        if first_read_objects is not None:
            streamed_reads = float(first_read_objects)
        else:
            streamed_reads = _resolve_first_read_objects(sc)
        if large_io:
            # Every read of a 1 MiB-or-larger file streams directly from the bucket, so all reads
            # are GETs and none are served as file reads from high-performance storage.
            streamed_reads = sc.reads_per_month
        else:
            # A read that happens for the first time is still a single read, so the number of
            # first-read streams cannot exceed the month's reads. Cap it: a cell whose written or
            # working-set count exceeds the reads (default P8 64 KiB, `read_scale < 1`,
            # `first_read_mode=working_set`) would otherwise book more GETs than there are reads.
            streamed_reads = min(streamed_reads, sc.reads_per_month)
        hps_reads = max(0.0, sc.reads_per_month - streamed_reads)
        read_gib = hps_reads * io_kib / (1024 * 1024)

        active_label = f"{active:.0%}" if _is_round_percent(active) else f"{active:.1%}"
        lines[
            t("S3 Files 高性能ストレージ (アクティブ {share})", share=active_label)
        ] = hps_gib * S3FILES["storage"].usd
        if large_io:
            lines[t("GET リクエスト (1 MiB 以上はバケットから直接ストリーム)")] = (
                streamed_reads * S3["tier2"].usd
            )
        elif not split_metadata or streamed_reads > 0:
            lines[t("GET リクエスト (初回読み出しはバケットからストリーム)")] = (
                streamed_reads * S3["tier2"].usd
            )
        # Only when the reader asks for it: a first read charged as a file read of at least 32 KiB.
        # The default "none" leaves the current branch untouched; a cell that streams nothing on
        # first read emits no line either way. A 1 MiB-or-larger read never carries a file read
        # charge, so this line does not apply when large_io.
        if (
            not large_io
            and sc.first_read_stream_billing == "file_read"
            and streamed_reads > 0
        ):
            stream_io_gib = (
                streamed_reads * max(object_kib, S3FILES_MIN_IO_KIB) / (1024 * 1024)
            )
            lines[
                t(
                    "S3 Files 初回ストリームのファイル読み取り ({count} 個 × {size})",
                    count=f"{streamed_reads:,.0f}",
                    size=_size_label(max(object_kib, S3FILES_MIN_IO_KIB)),
                )
            ] = stream_io_gib * S3FILES["read"].usd
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
        # The read-side label carries the multiplier only when it is non-default, so the baseline
        # output (multiplier 1.0) keeps the current label and its byte identity.
        multiplier = getattr(sc, "metadata_multiplier", 1.0)
        if multiplier == 1.0:
            read_label = t(
                "S3 Files メタデータ読み取り ({ops} 操作 × 4 KiB)",
                ops=f"{sc.reads_per_month:,.0f}",
            )
        else:
            read_label = t(
                "S3 Files メタデータ読み取り ({ops} 操作 × 4 KiB × {m})",
                ops=f"{sc.reads_per_month:,.0f}",
                m=f"{multiplier:g}",
            )
        lines[read_label] = read_usd

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
# "definition": true by definition, so there is nothing to source or to assume. It is the churn
# rate of a pattern with no writes (0%), and nothing else.
BASELINE_BASES = ("sourced", "repository", "placeholder", "definition")

BASELINE_SOURCE_URLS = {
    "efs_url": "https://aws.amazon.com/blogs/storage/scalable-cloud-native-file-storage-at-pennies-per-gb-month-with-amazon-efs/",
    "sizing_url": "https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/",
    "ycsb_url": "https://github.com/brianfrankcooper/YCSB/wiki/Core-Workloads",
    "mlperf_url": "https://mlcommons.org/benchmarks/storage/",
}

# Fixed modelling assumptions of the grid, held constant so the only variables are size and pattern.
BASELINE_EFFICIENCY_SSD = 0.40
BASELINE_POOL_FRACTION = 0.30
# The grid's SSD provisioning headroom. Named as a constant so `resolve()` and the BaselineCell
# default read one source rather than two copies of 0.20.
BASELINE_SSD_HEADROOM = 0.20


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
        # "definition" says the value is zero by construction, so it can only be the churn of a
        # pattern that writes nothing. Anywhere else it would pass a chosen value off as a given.
        if ("definition" in self.basis[:2]) or (
            self.basis[2] == "definition" and self.churn_pct != 0
        ):
            raise ValueError(
                f"{self.key}: 'definition' is only the basis of a 0% churn"
            )

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
    ssd_headroom: float = BASELINE_SSD_HEADROOM
    retention_months: float = 1.0  # steady state: the 20 TiB is resident for the month
    s3files_viable: bool = True
    s3files_threshold_kib: float = S3FILES_DEFAULT_THRESHOLD_KIB
    s3files_expiration_days: float = S3FILES_DEFAULT_EXPIRY_DAYS
    # Shared with Scenario; every default reproduces the current formula. See ASSUMPTION_SPECS.
    pool_efficiency_retention: float = POOL_EFFICIENCY_RETENTION
    throughput_mbps: int | None = None
    active_fraction: float | None = None
    first_read_mode: str = "written"
    first_read_stream_billing: str = "none"
    # BaselineCell-only (M-4). read_scale multiplies monthly read volume; metadata_multiplier scales
    # the read-side metadata operation count. A Scenario does not carry these.
    read_scale: float = 1.0
    metadata_multiplier: float = 1.0
    # BaselineCell-only (C1, PR-A2). Retention-days cost inputs, both 0 by default so no line is
    # booked. noncurrent_version_gib is the S3 Files side (non-current versions, priced as extra S3
    # Standard storage; documented from the sync page). snapshot_gib is the FSx for ONTAP side,
    # which is NOT put into the formula: which tier snapshot data sits in is policy-dependent and
    # the official pages disagree, so it is an input kept at 0 with an open (未確認) note.
    noncurrent_version_gib: float = 0.0
    snapshot_gib: float = 0.0

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
        """Monthly read volume = stored x w x n, times read_scale.

        read_scale is 1.0 by default and the multiplication is skipped then, so the default returns
        the current expression unchanged rather than relying on `x * 1.0 == x`.
        """
        base = (
            self.stored_gib
            * (self.pattern.working_set_pct * self.pattern.reads_per_object)
            / 100
        )
        return base if self.read_scale == 1.0 else base * self.read_scale

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
        return self.efficiency_ssd * self.pool_efficiency_retention

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
        basis=("placeholder", "placeholder", "definition"),
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
        basis=("placeholder", "placeholder", "definition"),
        position="書き込みのない読み取り専用の形。大きいファイルを順次読み、書き込みがない点が MLPerf Storage の "
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
        basis=("sourced", "placeholder", "definition"),
        position="作業セット比 {w}% は、データの 2 割がホット、8 割がコールドという比を述べる "
        "2 つのブログによる（[EFS ブログ]({efs_url})、"
        "[FSx for ONTAP サイジングブログ]({sizing_url})）。"
        "どちらも算出方法とデータセットを示していない。"
        "ブログが述べるのはホットなデータの容量比で、月内に読まれる割合とは述べていない。"
        "**回数 {n} は出典がなく**、R を 1 倍に揃えるために置いた",
    ),
    BaselinePattern(
        key="P4",
        name="小さい作業セットを強く再読",
        working_set_pct=10,
        reads_per_object=10,
        churn_pct=0,
        placeholder=False,
        basis=("repository", "repository", "definition"),
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


# ------------------------------------------------------------------------ assumptions (PR-A)
#
# The thirteen public assumption keys live in one registry. The CLI parse, the validation, the
# `--list-assumptions` table, the override echo in the JSON, and (in PR-B) the sensitivity section's
# list of assumptions all read it, so there is one place a key is defined and one place its baseline
# value, domain and tier are stated. Threading the values through BaselineCell / Scenario fields
# rather than module state keeps `baseline_cells(Assumptions())` a pure function of its argument.


class AssumptionError(ValueError):
    """A reader's assumption value or combination could not be accepted.

    Carries a stable `code` so a test checks the classification while only the language test reads
    the wording. `key` and `value` are the offending key and its string value where applicable.
    """

    def __init__(
        self, code: str, message: str, key: str | None = None, value: str | None = None
    ) -> None:
        super().__init__(message)
        self.code = code
        self.key = key
        self.value = value


# Error messages are the one CLI output localized to JA/EN: they answer a reader's own input, and a
# reader of the Japanese document reads them in Japanese. Argument-combination errors stay English
# (`parser.error`), as the existing convention has them. Keys are the Japanese source text, per the
# `t()` convention; `_assumption_error` wraps the lookup so `_LANG` governs the language.


def _assumption_error(
    lang: str,
    code: str,
    ja: str,
    *,
    key: str | None = None,
    value: str | None = None,
    **fmt: object,
) -> AssumptionError:
    # `key` and `value` are both the error's attributes and placeholders in the message, so they
    # join `fmt` for the interpolation. Entries that do not use them simply ignore the extra keys.
    placeholders = dict(fmt)
    if key is not None:
        placeholders.setdefault("key", key)
    if value is not None:
        placeholders.setdefault("value", value)

    def build() -> str:
        return t(ja, **placeholders)

    return AssumptionError(code, _in_language(lang, build), key=key, value=value)


_FLOAT_RE = re.compile(r"[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?\Z")
_INT_RE = re.compile(r"\d+\Z")
_NONFINITE_WORDS = {
    "nan",
    "inf",
    "+inf",
    "-inf",
    "infinity",
    "+infinity",
    "-infinity",
}


def _sep(lang: str) -> str:
    """List separator for `lang`: a comma-space in English, an ideographic comma in Japanese.

    Resolved from the `lang` argument rather than `t("、")` so it is correct even when it is built
    as an eager argument outside the `_in_language` block that renders the surrounding message.
    """
    return ", " if lang == "en" else "、"


@dataclass(frozen=True)
class AssumptionSpec:
    """One public assumption: its kind, baseline value, domain check and source tier."""

    key: str
    kind: str  # "float" | "int" | "enum"
    baseline: Callable[[], object]  # the current model's value for this key
    tier: str  # 基準値の区分: 公式 / 観測 / 試算前提 / 仮置き / 定義
    description_ja: str
    domain_text_ja: str = ""  # human text of the accepted range, for the range error
    choices: tuple[str, ...] = ()  # enum keys, case-sensitive
    in_domain: Callable[[float], bool] | None = None  # float range check
    reader_decides_ja: str = ""  # for --list-assumptions
    auto: bool = False  # accepts the literal "auto" (= unspecified)


def _baseline_deployment_api() -> str:
    return DEPLOYMENTS[BaselineCell.deployment]["api"]


# Registry. Order is the canonical key order used by `resolve()`, `--list-assumptions`, and the
# stage-2 validation sweep.
ASSUMPTION_SPECS: dict[str, AssumptionSpec] = {
    "deployment": AssumptionSpec(
        key="deployment",
        kind="enum",
        baseline=_baseline_deployment_api,
        tier="試算前提",
        description_ja="デプロイ形態（可用性と世代）",
        choices=tuple(d["api"] for d in DEPLOYMENTS.values()),
        reader_decides_ja="決める（可用性要件）",
    ),
    "efficiency_ssd": AssumptionSpec(
        key="efficiency_ssd",
        kind="float",
        baseline=lambda: BASELINE_EFFICIENCY_SSD,
        tier="仮置き",
        description_ja="SSD 層のストレージ効率",
        domain_text_ja="0 以上 1 未満",
        in_domain=lambda x: 0.0 <= x < 1.0,
        reader_decides_ja="決められる（データの性質）",
    ),
    "pool_efficiency_retention": AssumptionSpec(
        key="pool_efficiency_retention",
        kind="float",
        baseline=lambda: POOL_EFFICIENCY_RETENTION,
        tier="仮置き",
        description_ja="キャパシティプール層に残る SSD 効率の割合",
        domain_text_ja="0 以上 1 以下",
        in_domain=lambda x: 0.0 <= x <= 1.0,
        reader_decides_ja="データごとに測る（一般値なし）",
    ),
    "pool_fraction": AssumptionSpec(
        key="pool_fraction",
        kind="float",
        baseline=lambda: BASELINE_POOL_FRACTION,
        tier="仮置き",
        description_ja="キャパシティプールへ落とす割合",
        domain_text_ja="0 以上 1 以下",
        in_domain=lambda x: 0.0 <= x <= 1.0,
        reader_decides_ja="決められる",
    ),
    "ssd_headroom": AssumptionSpec(
        key="ssd_headroom",
        kind="float",
        baseline=lambda: BASELINE_SSD_HEADROOM,
        tier="試算前提",
        description_ja="SSD のプロビジョニング余裕",
        domain_text_ja="0 以上 1 以下",
        in_domain=lambda x: 0.0 <= x <= 1.0,
        reader_decides_ja="決める（運用方針）",
    ),
    "throughput_mbps": AssumptionSpec(
        key="throughput_mbps",
        kind="int",
        baseline=lambda: "auto",
        tier="試算前提",
        description_ja="スループットキャパシティ（指定の段 MBps、auto でモデルが選ぶ）",
        reader_decides_ja="決める（ピーク要件）",
        auto=True,
    ),
    "active_fraction": AssumptionSpec(
        key="active_fraction",
        kind="float",
        baseline=lambda: "auto",
        tier="仮置き",
        description_ja="S3 Files 高性能ストレージのアクティブ割合（auto で現行の式）",
        domain_text_ja="0 以上 1 以下",
        in_domain=lambda x: 0.0 <= x <= 1.0,
        reader_decides_ja="アクセスの形で決まる",
        auto=True,
    ),
    "s3files_threshold_kib": AssumptionSpec(
        key="s3files_threshold_kib",
        kind="float",
        baseline=lambda: S3FILES_DEFAULT_THRESHOLD_KIB,
        tier="公式",
        description_ja="S3 Files の取り込みしきい値（KiB）",
        domain_text_ja="0 より大きい。格子のサイズと同値は不可",
        in_domain=lambda x: x > 0.0,  # the grid-size limit is a stage-2 check
        reader_decides_ja="決める（設定）",
    ),
    "first_read_mode": AssumptionSpec(
        key="first_read_mode",
        kind="enum",
        baseline=lambda: "written",
        tier="仮置き",
        description_ja="初回ストリームに数える個数（written: 書いた個数 / none: 0 / working_set: 作業セット）",
        choices=("written", "none", "working_set"),
        reader_decides_ja="読み取りの時間的な偏りで決まる",
    ),
    "first_read_stream_billing": AssumptionSpec(
        key="first_read_stream_billing",
        kind="enum",
        baseline=lambda: "none",
        tier="仮置き",
        description_ja="初回ストリームのファイル読み取り課金（none: なし / file_read: 課金する）",
        choices=("none", "file_read"),
        reader_decides_ja="課金の実際が未確認（両方で試算できる）",
    ),
    "metadata_multiplier": AssumptionSpec(
        key="metadata_multiplier",
        kind="float",
        baseline=lambda: 1.0,
        tier="仮置き",
        description_ja="読み取り側メタデータの操作数倍率",
        domain_text_ja="0 以上の有限値",
        in_domain=lambda x: x >= 0.0,
        reader_decides_ja="マウントオプションで動く",
    ),
    "read_scale": AssumptionSpec(
        key="read_scale",
        kind="float",
        baseline=lambda: 1.0,
        tier="定義",
        description_ja="月間読み取り量に掛ける倍率（1.0 = パターンの定義どおり）",
        domain_text_ja="0 より大きい有限値",
        in_domain=lambda x: x > 0.0,
        reader_decides_ja="決める（自分のワークロード）",
    ),
    "stored_tib": AssumptionSpec(
        key="stored_tib",
        kind="float",
        baseline=lambda: float(BASELINE_STORED_TIB),
        tier="定義",
        description_ja="保存量（TiB）",
        domain_text_ja="0 より大きい有限値",
        in_domain=lambda x: x > 0.0,
        reader_decides_ja="決める",
    ),
    # C1 (PR-A2): retention-days cost inputs. Both default to 0, so the baseline output is
    # unchanged. noncurrent_version_gib goes into the S3 Files subtotal as extra S3 Standard
    # storage (documented from the sync page). snapshot_gib is an input only: it is not put into
    # any formula because the tier snapshot data occupies is policy-dependent and the official
    # pages disagree, so it stays open (未確認). See s3_files_option (C1) and the impl note.
    "noncurrent_version_gib": AssumptionSpec(
        key="noncurrent_version_gib",
        kind="float",
        baseline=lambda: 0.0,
        tier="試算前提",
        description_ja="非現行バージョンの保持容量（GiB、S3 Files 側）。S3 Standard の増分として算入",
        domain_text_ja="0 以上の有限値",
        in_domain=lambda x: x >= 0.0,
        reader_decides_ja="決める（バージョニングの保持方針）",
    ),
    "snapshot_gib": AssumptionSpec(
        key="snapshot_gib",
        kind="float",
        baseline=lambda: 0.0,
        tier="試算前提",
        description_ja="スナップショットの保持容量（GiB、FSx for ONTAP 側）。層・課金が未確認のため式に算入せず入力のみ（open 未確認）",
        domain_text_ja="0 以上の有限値",
        in_domain=lambda x: x >= 0.0,
        reader_decides_ja="決める（スナップショットの保持方針）",
    ),
}


@dataclass(frozen=True)
class Assumptions:
    """Reader-supplied assumptions. Every field defaults to None = unspecified = the baseline.

    None is unspecified and uses the baseline value. A value equal to the baseline is still an
    override: the output then carries a notice and the key is listed, so "I set it to the baseline
    on purpose" and "I left it alone" are told apart. The `auto` fields never hold the string
    "auto"; parse maps `auto` to None (= unspecified), so the types stay int|None and float|None.
    """

    deployment: str | None = None
    efficiency_ssd: float | None = None
    pool_efficiency_retention: float | None = None
    pool_fraction: float | None = None
    ssd_headroom: float | None = None
    throughput_mbps: int | None = None  # None = auto (model chooses the tier)
    active_fraction: float | None = None  # None = auto (current formula)
    s3files_threshold_kib: float | None = None
    first_read_mode: str | None = None
    first_read_stream_billing: str | None = None
    metadata_multiplier: float | None = None
    read_scale: float | None = None
    stored_tib: float | None = None
    # C1 (PR-A2): noncurrent_version_gib books an S3 Files line when > 0; snapshot_gib is input
    # only, not in any formula (open/unconfirmed tier). Both 0 by default.
    noncurrent_version_gib: float | None = None
    snapshot_gib: float | None = None


def specified(a: Assumptions) -> dict[str, object]:
    """The keys the reader set (not None), as a dict. These are the overrides."""
    return {
        key: getattr(a, key) for key in ASSUMPTION_SPECS if getattr(a, key) is not None
    }


def resolve(a: Assumptions) -> dict[str, object]:
    """Effective value of all thirteen keys: the override where set, else the baseline."""
    out: dict[str, object] = {}
    for key, spec in ASSUMPTION_SPECS.items():
        value = getattr(a, key)
        out[key] = spec.baseline() if value is None else value
    return out


def _localized(lang: str, ja: str, **fmt: object) -> str:
    """Resolve `t(ja, **fmt)` under `lang` without leaving module state changed.

    Nested placeholder values (a kind word, a domain phrase) must be in the error's language, but
    they are built eagerly as arguments outside the `_in_language` block that renders the message —
    so each is wrapped here to pick up the target language.
    """
    return _in_language(lang, lambda: t(ja, **fmt))


def _coerce_float(spec: AssumptionSpec, value: str, lang: str) -> float:
    text = value.strip()
    if spec.auto and text == "auto":
        return (
            math.nan
        )  # sentinel; caller treats auto as unspecified before this is used
    # NaN / infinity are not-finite, not a type error: Python would parse them to a float, so the
    # fault is the value. Caught case-insensitively here (the regex does not match them) and again
    # after float() for forms like 1e999 that overflow to inf.
    if text.lower() in _NONFINITE_WORDS:
        raise _assumption_error(
            lang,
            "not_finite",
            "`{key}` は有限の数値で指定する（NaN と無限大は不可）",
            key=spec.key,
            value=value,
        )
    if not _FLOAT_RE.match(text):
        raise _assumption_error(
            lang,
            "type",
            "`{key}` の値 `{value}` を {kind} として読めない",
            key=spec.key,
            value=value,
            kind=_localized(lang, "数値"),
        )
    number = float(text)
    if not math.isfinite(number):
        raise _assumption_error(
            lang,
            "not_finite",
            "`{key}` は有限の数値で指定する（NaN と無限大は不可）",
            key=spec.key,
            value=value,
        )
    return number


def _coerce_int(spec: AssumptionSpec, value: str, lang: str) -> int:
    text = value.strip()
    if spec.auto and text == "auto":
        return -1  # sentinel; caller treats auto as unspecified before this is used
    if not _INT_RE.match(text):
        raise _assumption_error(
            lang,
            "type",
            "`{key}` の値 `{value}` を {kind} として読めない",
            key=spec.key,
            value=value,
            kind=_localized(lang, "整数"),
        )
    return int(text)


def _coerce_enum(spec: AssumptionSpec, value: str, lang: str) -> str:
    text = value.strip()
    if text not in spec.choices:
        raise _assumption_error(
            lang,
            "choice",
            "`{key}` は {choices} のいずれかで指定する（指定値 {value}）",
            key=spec.key,
            value=value,
            choices=_sep(lang).join(spec.choices),
        )
    return text


def parse_assumptions(items, lang: str = "ja") -> Assumptions:
    """Parse a sequence of `key=value` strings into an Assumptions.

    Stage 1 of validation (format, key existence, duplicates, type, single-item range) runs here in
    argument order, stopping at the first offender. `auto` for throughput/active maps to None, so no
    `auto` string ever reaches the dataclass. The cross-item checks are stage 2 (validate).
    """
    fields: dict[str, object] = {}
    seen: list[str] = []
    for item in items:
        if "=" not in item or item.split("=", 1)[0].strip() == "":
            raise _assumption_error(
                lang,
                "bad_format",
                "`{item}` は key=value の形ではない",
                value=item,
                item=item,
            )
        raw_key, raw_value = item.split("=", 1)
        key = raw_key.strip()
        if key not in ASSUMPTION_SPECS:
            raise _assumption_error(
                lang,
                "unknown_key",
                "未知の前提 `{key}`。使えるキーは `--list-assumptions` で確認する",
                key=key,
                value=raw_value,
            )
        if key in seen:
            raise _assumption_error(
                lang,
                "duplicate",
                "`{key}` が複数回指定されている",
                key=key,
                value=raw_value,
            )
        seen.append(key)
        if raw_value.strip() == "":
            raise _assumption_error(
                lang,
                "type",
                "`{key}` の値 `{value}` を {kind} として読めない",
                key=key,
                value=raw_value,
                kind=_kind_word(ASSUMPTION_SPECS[key], lang),
            )
        spec = ASSUMPTION_SPECS[key]
        parsed = _parse_one(spec, raw_value, lang)
        if parsed is None:  # auto -> unspecified
            continue
        fields[key] = parsed
    return Assumptions(**fields)


def _kind_word(spec: AssumptionSpec, lang: str) -> str:
    ja = {"float": "数値", "int": "整数", "enum": "列挙"}[spec.kind]
    return _localized(lang, ja)


def _parse_one(spec: AssumptionSpec, raw_value: str, lang: str):
    """Parse and single-item-range-check one value. Returns None when the value means `auto`."""
    if spec.kind == "enum":
        return _coerce_enum(spec, raw_value, lang)
    if spec.kind == "int":
        number = _coerce_int(spec, raw_value, lang)
        if number == -1 and spec.auto and raw_value.strip() == "auto":
            return None
        return number
    # float
    stripped = raw_value.strip()
    if spec.auto and stripped == "auto":
        return None
    value = _coerce_float(spec, raw_value, lang)
    if spec.in_domain is not None and not spec.in_domain(value):
        raise _assumption_error(
            lang,
            "range",
            "`{key}` の指定値 {value} は許容範囲 {domain} の外",
            key=spec.key,
            value=raw_value,
            domain=_localized(lang, spec.domain_text_ja),
        )
    return value


def validate_assumptions(a: Assumptions, lang: str = "ja") -> None:
    """Stage 2: cross-item checks, evaluated in registry key order, independent of argument order.

    Stage 1 (format, type, single-item range) has already run during parse. The Python API path
    skips stage 1 (the dataclass holds typed values), so this also range-checks the float fields it
    is given, so a programmatic caller cannot slip an out-of-range value past the CLI's stage 1.
    """
    values = {key: getattr(a, key) for key in ASSUMPTION_SPECS}

    # Re-run the single-item float range for the Python API path.
    for key, spec in ASSUMPTION_SPECS.items():
        value = values[key]
        if value is None or spec.kind != "float":
            continue
        number = float(value)
        if not math.isfinite(number):
            raise _assumption_error(
                lang,
                "not_finite",
                "`{key}` は有限の数値で指定する（NaN と無限大は不可）",
                key=key,
                value=repr(value),
            )
        if spec.in_domain is not None and not spec.in_domain(number):
            raise _assumption_error(
                lang,
                "range",
                "`{key}` の指定値 {value} は許容範囲 {domain} の外",
                key=key,
                value=f"{number:g}",
                domain=_localized(lang, spec.domain_text_ja),
            )

    # first_read_mode choices (Python API may set an unknown string).
    for key in ("first_read_mode", "first_read_stream_billing", "deployment"):
        value = values[key]
        spec = ASSUMPTION_SPECS[key]
        if value is not None and value not in spec.choices:
            raise _assumption_error(
                lang,
                "choice",
                "`{key}` は {choices} のいずれかで指定する（指定値 {value}）",
                key=key,
                value=str(value),
                choices=_sep(lang).join(spec.choices),
            )

    # s3files_threshold_kib: not equal to a grid size. A threshold of 1 MiB or more is now allowed:
    # the high-performance branch streams reads of 1 MiB or larger directly (GET + 4 KiB metadata
    # read), matching the metering page, so the model no longer overcounts there (PR-F).
    threshold = values["s3files_threshold_kib"]
    if threshold is not None and any(
        abs(threshold - size) < 1e-9 for size in BASELINE_SIZES_KIB
    ):
        raise _assumption_error(
            lang,
            "threshold_on_grid",
            "`s3files_threshold_kib` を格子のサイズ（{sizes}）と同じ値にできない。"
            "ちょうどのサイズの扱いが公式の文面で揃っていない",
            key="s3files_threshold_kib",
            value=f"{threshold:g}",
            sizes=_sep(lang).join(_size_label(s) for s in BASELINE_SIZES_KIB),
        )

    # throughput_mbps against the effective deployment's tier set.
    tput = values["throughput_mbps"]
    if tput is not None:
        effective_dep = values["deployment"] or _baseline_deployment_api()
        dep = next(d for d in DEPLOYMENTS.values() if d["api"] == effective_dep)
        tiers = dep["tput_options"]
        if tput not in tiers:
            raise _assumption_error(
                lang,
                "throughput_tier",
                "スループット {value} MBps は {deployment} の段 {tiers} にない",
                key="throughput_mbps",
                value=str(tput),
                deployment=effective_dep,
                tiers=_sep(lang).join(str(x) for x in tiers),
            )


def _internal_deployment_key(api: str) -> str:
    """Map a public API deployment value (SINGLE_AZ_1 ...) to the internal key (saz1 ...)."""
    for internal, dep in DEPLOYMENTS.items():
        if dep["api"] == api:
            return internal
    raise ValueError(f"unknown deployment api: {api!r}")


def _apply_assumptions(cell: BaselineCell, resolved: dict[str, object]) -> BaselineCell:
    """Return a cell with the resolved assumptions applied. Pure; used per cell.

    `stored_tib` is applied as `stored_gib`; `throughput_mbps`/`active_fraction` pass through as
    None when the resolved value is the string "auto". The mutation test swaps this name.
    """
    throughput = resolved["throughput_mbps"]
    active = resolved["active_fraction"]
    deployment = _internal_deployment_key(str(resolved["deployment"]))
    return replace(
        cell,
        stored_gib=float(resolved["stored_tib"]) * GIB_PER_TIB,
        efficiency_ssd=float(resolved["efficiency_ssd"]),
        pool_efficiency_retention=float(resolved["pool_efficiency_retention"]),
        pool_fraction=float(resolved["pool_fraction"]),
        ssd_headroom=float(resolved["ssd_headroom"]),
        deployment=deployment,
        throughput_mbps=None if throughput == "auto" else int(throughput),
        active_fraction=None if active == "auto" else float(active),
        s3files_threshold_kib=float(resolved["s3files_threshold_kib"]),
        first_read_mode=str(resolved["first_read_mode"]),
        first_read_stream_billing=str(resolved["first_read_stream_billing"]),
        metadata_multiplier=float(resolved["metadata_multiplier"]),
        read_scale=float(resolved["read_scale"]),
        noncurrent_version_gib=float(resolved["noncurrent_version_gib"]),
        snapshot_gib=float(resolved["snapshot_gib"]),
    )


def baseline_cells(
    assumptions: Assumptions | None = None,
    patterns=None,
    lang: str = "ja",
) -> list[BaselineCell]:
    """The 32-cell grid (or `len(patterns) x 4`), with any reader assumptions applied.

    `assumptions=None` reproduces the current grid byte for byte: no override is applied and the
    cells keep their class defaults. The `lang`/`patterns` arguments let a caller substitute the
    pattern set (validated by BaselinePattern.__post_init__) without changing module state.
    """
    use_patterns = BASELINE_PATTERNS if patterns is None else tuple(patterns)
    if assumptions is None:
        stored_gib = BASELINE_STORED_TIB * GIB_PER_TIB
        return [
            BaselineCell(pattern=pattern, object_mib=kib / 1024, stored_gib=stored_gib)
            for pattern in use_patterns
            for kib in BASELINE_SIZES_KIB
        ]
    resolved = resolve(assumptions)
    stored_gib = BASELINE_STORED_TIB * GIB_PER_TIB
    cells = [
        BaselineCell(pattern=pattern, object_mib=kib / 1024, stored_gib=stored_gib)
        for pattern in use_patterns
        for kib in BASELINE_SIZES_KIB
    ]
    return [_apply_assumptions(cell, resolved) for cell in cells]


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


def _books_no_first_read_stream(cell: BaselineCell) -> bool:
    """A cell with no writes at or below the S3 Files threshold: the model streams no first read."""
    return cell.pattern.churn_pct == 0 and cell.object_kib <= cell.s3files_threshold_kib


def _first_read_stream_sensitivity(cell: BaselineCell) -> tuple[float, float]:
    """S3 Files subtotal as modelled, and with every working-set object streamed once on first read.

    Only the GET requests and the reads they remove are counted; the import write is not (see
    `s3_files_option`), so the second value is not the subtotal of counting the first read.
    """
    modelled = s3_files_option(cell, split_metadata=True)
    counted = s3_files_option(
        cell, split_metadata=True, first_read_objects=cell.working_set_objects
    )
    assert modelled is not None and counted is not None
    return sum(modelled.values()), sum(counted.values())


def _enumeration_usd(cell: BaselineCell) -> float:
    """First listing of the whole stored volume: a 4 KiB metadata write per stored object, once."""
    return (
        cell.objects_stored
        * (S3FILES_METADATA_KIB / (1024 * 1024))
        * S3FILES["write"].usd
    )


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


def _count(value: float, strict: bool = True) -> float:
    """A count, whole-checked under the baseline (`strict`) and left fractional when overridden.

    The baseline grid keeps the current strict check (existing tests depend on it). Once a reader
    scales reads or stores a fractional TiB, the derived object counts are no longer whole, so the
    override path emits them as floats rather than failing.
    """
    return _whole(value) if strict else value


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

    # The largest amount the unconfirmed metadata lines could add among the cells of 1 MiB or more,
    # and what share of that cell's S3 Files subtotal it is. Derived, so it follows the prices.
    def _metadata_delta(cell: BaselineCell) -> float:
        return sum(s3_files_metadata_usd(cell))

    large_object_cells = [c for c in baseline_cells() if c.object_kib >= 1024]
    delta_cell = max(large_object_cells, key=_metadata_delta)
    delta_lines = s3_files_option(delta_cell, split_metadata=True)
    assert delta_lines is not None
    metadata_delta_max = _metadata_delta(delta_cell)
    metadata_share_max = 100 * metadata_delta_max / sum(delta_lines.values())

    # Counting the first-read stream that premise (c) leaves out, in the cells where (c) applies.
    # The note quotes the GET-and-read change only, and words it as a decrease, so a cell where that
    # change is not a decrease stops the render. The net direction is not claimed.
    no_stream_cells = [c for c in baseline_cells() if _books_no_first_read_stream(c)]
    stream_changes = {id(c): _first_read_stream_sensitivity(c) for c in no_stream_cells}
    if any(after >= before for before, after in stream_changes.values()):
        raise ValueError(
            "the GET and read change of the first-read stream is no longer a decrease"
        )
    stream_cell = min(
        no_stream_cells,
        key=lambda c: stream_changes[id(c)][1] - stream_changes[id(c)][0],
    )
    stream_before, stream_after = stream_changes[id(stream_cell)]

    # The one-off cost of the first listing of the whole stored volume, at each size. It is the
    # metadata write only. At or below the import threshold the default trigger also imports the
    # data, which this figure does not include, so the two ranges of sizes are written apart.
    def _enumeration_at(sizes_kib: list[float]) -> str:
        return t("、").join(
            t(
                "{size} で {amount}",
                size=_size_label(kib),
                amount=usd(
                    _enumeration_usd(
                        BaselineCell(
                            pattern=patterns[0],
                            object_mib=kib / 1024,
                            stored_gib=stored_gib,
                        )
                    )
                ),
            )
            for kib in sizes_kib
        )

    enumeration_small = _enumeration_at(
        [k for k in BASELINE_SIZES_KIB if k <= S3FILES_DEFAULT_THRESHOLD_KIB]
    )
    enumeration_large = _enumeration_at(
        [k for k in BASELINE_SIZES_KIB if k > S3FILES_DEFAULT_THRESHOLD_KIB]
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
            "(c) を置き換え、作業セットの各オブジェクトの初回読み出しを計上すると、"
            "増える項目は、バケットからの GET と、高性能ストレージへの取り込み書き込み "
            "(${write_price} / GB、最小 {min_io} KiB)、減る項目は、高性能ストレージの読み取りである。"
            "取り込み書き込みは、ディレクトリを最初にたどったとき "
            "{threshold} KiB 以下のファイルのデータをまとめて取り込む既定の挙動に従い、"
            "読まれたオブジェクトの数とは対応しないので、このモデルは数えていない。"
            "差し引きの向きは、このモデルでは確定していない。"
            "取り込み書き込みを含めず、GET の増加と読み取りの減少だけを見ると、"
            "(c) が当てはまる {stream_cells} セルの中では "
            "{stream_pattern} の {stream_size} の変化が最大で、{stream_before} から {stream_after} へ、"
            "{stream_delta} ({stream_pct}%) 下がる。この額に取り込み書き込みは入っていない。"
            "示した向きと金額はいずれも試算上の感度で、測定ではない。",
            pool=f"{BASELINE_POOL_FRACTION:.0%}".rstrip("%"),
            threshold=f"{S3FILES_DEFAULT_THRESHOLD_KIB:g}",
            write_price=f"{S3FILES['write'].usd:g}",
            min_io=f"{S3FILES_MIN_IO_KIB:g}",
            small_groups=_keys(small),
            large_groups=_keys(large),
            stream_cells=len(no_stream_cells),
            stream_pattern=stream_cell.pattern.key,
            stream_size=_size_label(stream_cell.object_kib),
            stream_before=usd(stream_before),
            stream_after=usd(stream_after),
            stream_delta=usd(stream_before - stream_after),
            stream_pct=f"{100 * (stream_before - stream_after) / stream_before:.1f}",
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
            "S3 Files のメタデータ行 (4 KiB × 操作) のうち、読み取り側が 4 MiB のオブジェクトの読み取りにも立つことは、"
            "請求の数量で観測した"
            "([請求数量の突き合わせ](../../verification/s3files-billing-reconciled.md)。"
            "1 MiB I/O と 4 MiB I/O、m5.large、1 環境)。"
            "1 MiB と 16 MiB のオブジェクトの読み取りは観測していない。取り込み側が 1 MiB 以上のオブジェクトにも立つかは、未確認である。"
            "[計量ページ](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html)は"
            "バケットからの直接読み取りに 4 KiB のメタデータ読み取りが付くと書き、"
            "[料金ページ](https://aws.amazon.com/s3/pricing/)は同じ読み取りに S3 の GET 課金だけが付くと書いている。"
            "2 ページの文面は揃っていない。"
            "読み取り側は、請求の数量にメタデータ読み取りが含まれていたため、小計に算入している。"
            "取り込み側は実測がないため、算入したままにしている。"
            "除くと、1 MiB 以上のセルの小計は最大 {delta} (そのセルの小計の {pct}%) 下がる。"
            "増える方向もある。"
            "1 回の読み取りにメタデータ操作が k 回付く場合は、読み取り側の行が k 倍になる。"
            "4 MiB の読み取りでは、1 個あたり約 6.0 回 × 約 4.1 KiB を観測した (1 環境、1 回の観測)。"
            "6 回の内訳は未確認である。"
            "既定は 1 操作 × 4 KiB のままで、観測値には変えていない。"
            "ディレクトリの初回列挙は、ファイル 1 個ごとに 4 KiB の書き込みを計量する。"
            "{stored_tib} TiB を列挙した場合の 1 回限りの額 ({enumeration_small}) は、"
            "メタデータ分だけの額で、{threshold} KiB 以下のファイルのデータの取り込み書き込み "
            "(${write_price} / GB) は含まない。"
            "既定のトリガ (ディレクトリの初回アクセス) は、このサイズのファイルのデータも取り込むためである。"
            "{threshold} KiB を超えるサイズ ({enumeration_large}) では、"
            "データは取り込まれず直接読まれるので、この額はメタデータ分のみである。"
            "モデルはどちらも算入していない。"
            "どちらも測っていない。"
            "セルごとの除いた小計は、`python3 tools/finops_model.py --baseline-json` の "
            "`subtotal_excluding_metadata_usd` で読める。",
            delta=usd(metadata_delta_max),
            pct=f"{metadata_share_max:.1f}",
            stored_tib=BASELINE_STORED_TIB,
            enumeration_small=enumeration_small,
            enumeration_large=enumeration_large,
            threshold=f"{S3FILES_DEFAULT_THRESHOLD_KIB:g}",
            write_price=f"{S3FILES['write'].usd:g}",
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

        no_first_read_stream = _books_no_first_read_stream(cell)
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


def _max_tier(cell: BaselineCell) -> int:
    return DEPLOYMENTS[cell.deployment]["tput_options"][-1]


def _throughput_out_of_model_range(cell: BaselineCell) -> bool:
    """True when throughput is auto and the required tier would exceed the deployment's maximum.

    choose_throughput caps at the maximum tier, so the subtotal there is a value for a configuration
    that does not exist; the JSON flags it rather than presenting it as real.
    """
    if cell.throughput_mbps is not None:
        return False
    return cell.required_mbps * (1 + cell.tput_headroom) > _max_tier(cell)


def _specified_tier_below_average(cell: BaselineCell) -> bool:
    """True when the reader fixed a throughput tier below the cell's sustained requirement."""
    return (
        cell.throughput_mbps is not None and cell.required_mbps > cell.throughput_mbps
    )


def _changes_text(a: Assumptions, resolved_baseline: dict[str, object]) -> str:
    """`key=value（基準 value）` list for the notice, baseline-equal keys marked."""
    parts: list[str] = []
    for key in ASSUMPTION_SPECS:
        value = getattr(a, key)
        if value is None:
            continue
        baseline = resolved_baseline[key]
        if _value_equals_baseline(value, baseline):
            parts.append(
                t("{key}={value}（基準と同じ値を明示）", key=key, value=_fmt(value))
            )
        else:
            parts.append(
                t(
                    "{key}={value}（基準 {baseline}）",
                    key=key,
                    value=_fmt(value),
                    baseline=_fmt(baseline),
                )
            )
    return t("、").join(parts)


def _value_equals_baseline(value: object, baseline: object) -> bool:
    if isinstance(value, (int, float)) and isinstance(baseline, (int, float)):
        return float(value) == float(baseline)
    return value == baseline


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:g}"
    return str(value)


def _notice_caveat(a: Assumptions, cells: list[BaselineCell]) -> str:
    """The caveat clauses of the notice, in fixed order, only the ones that apply."""
    spec_keys = set(specified(a))
    clauses: list[str] = []

    placeholder_keys = [
        key for key in spec_keys if ASSUMPTION_SPECS[key].tier == "仮置き"
    ]
    if placeholder_keys:
        clauses.append(
            t(
                "仮置きまたは未測定の前提を含む: {keys}。",
                keys=t("、").join(k for k in ASSUMPTION_SPECS if k in placeholder_keys),
            )
        )
    if "first_read_mode" in spec_keys:
        clauses.append(
            t(
                "初回読み出しを数える変種は取り込み書き込みを含まない部分的な計上で、"
                "小計の増減の向きは定まらない。"
            )
        )
    if a.first_read_stream_billing == "file_read":
        clauses.append(
            t(
                "初回ストリームにファイル読み取り課金が付くかどうかは、"
                "公式の文面が揃わず、課金の実際は未確認である。"
            )
        )
    if "throughput_mbps" in spec_keys:
        clauses.append(t("スループットは読者の指定で、モデルが選んだ段ではない。"))
        below = sum(1 for c in cells if _specified_tier_below_average(c))
        if below:
            clauses.append(t("指定の段が平均所要を下回るセルが {n} 個ある。", n=below))
    if "throughput_mbps" not in spec_keys:
        out_of_range = sum(1 for c in cells if _throughput_out_of_model_range(c))
        if out_of_range:
            clauses.append(
                t(
                    "{n} 個のセルは、必要なスループットがこの構成の最大段を超え、"
                    "FSx for ONTAP の小計が最大段で頭打ちになっている（モデルの適用範囲外）。",
                    n=out_of_range,
                )
            )
    return "".join(clauses)


def _notice_text(a: Assumptions, cells: list[BaselineCell]) -> str:
    resolved_baseline = {key: spec.baseline() for key, spec in ASSUMPTION_SPECS.items()}
    changes = _changes_text(a, resolved_baseline)
    caveat = _notice_caveat(a, cells)
    return t(
        "この出力は基準の前提と異なる（変更 {count} 件: {changes}）。"
        "公開文書の値ではない。{caveat}",
        count=len(specified(a)),
        changes=changes,
        caveat=caveat,
    )


def _assumption_overrides(a: Assumptions) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    for key, spec in ASSUMPTION_SPECS.items():
        value = getattr(a, key)
        if value is None:
            continue
        out.append(
            {
                "key": key,
                "value": value,
                "baseline": spec.baseline(),
                "tier": spec.tier,
            }
        )
    return out


# Fixed-premise identifiers removed when the reader overrides the key they describe.
_PREMISE_FOR_KEY = {
    "active_fraction": "s3files_high_performance_storage_is_fully_active_at_or_below_threshold",
    "first_read_mode": "s3files_books_no_first_read_stream_when_there_are_no_writes",
}


def baseline_json(
    lang: str = "ja", assumptions: Assumptions | None = None
) -> dict[str, object]:
    """The baseline grid as plain data, derived from the same cells the document is rendered from.

    A figure that reads this does not retype a number. Nothing here is computed a second time: the
    quantities are the `BaselineCell` properties and the amounts are the pricing helpers' lines.
    `lines[].label` and `position` follow `lang`; `name_ja` and `name_en` are always both present.

    `assumptions=None`, or an Assumptions with no key set, reproduces the current output byte for
    byte — none of the override keys appear. When at least one key is set, a `notice` and the
    `baseline_assumptions`/`assumption_overrides` keys are added, `position` is dropped (it is phrased
    for the baseline quantities), object counts become fractional, and each cell carries the
    out-of-range / tier-below-average flags.
    """
    overridden = assumptions is not None and bool(specified(assumptions))

    def build() -> dict[str, object]:
        cells = baseline_cells(assumptions)
        sample = cells[0]
        strict = not overridden
        patterns: list[dict[str, object]] = []
        for index, pattern in enumerate(BASELINE_PATTERNS):
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
                doc: dict[str, object] = {
                    "size_kib": _whole(cell.object_kib),
                    "stored_objects": _count(cell.objects_stored, strict),
                    "working_set_gib": cell.working_set_gib,
                    "working_set_objects": _count(cell.working_set_objects, strict),
                    "unread_gib": cell.unread_gib,
                    "read_gib": cell.read_gib_per_month,
                    "read_requests": _count(cell.reads_per_month, strict),
                    "write_gib": cell.write_gib_per_month,
                    "write_objects": _count(cell.objects_per_month, strict),
                    "average_mbps": cell.required_mbps,
                    "methods": {
                        "fsx_s3ap": _method_json(fsx_s3ap(cell)),
                        "s3_files": files,
                        "s3_direct": None if direct is None else _method_json(direct),
                    },
                }
                if overridden:
                    doc["throughput_out_of_model_range"] = (
                        _throughput_out_of_model_range(cell)
                    )
                    doc["specified_tier_below_average"] = _specified_tier_below_average(
                        cell
                    )
                cell_docs.append(doc)
            probe = next(c for c in cells if c.pattern is pattern)
            pattern_doc: dict[str, object] = {
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
            }
            if not overridden:
                pattern_doc["position"] = baseline_position(pattern)
            pattern_doc["cells"] = cell_docs
            patterns.append(pattern_doc)

        fixed_premises = [
            "fsx_capacity_pool_share_is_fixed_in_every_pattern",
            "s3files_high_performance_storage_is_fully_active_at_or_below_threshold",
            "s3files_books_no_first_read_stream_when_there_are_no_writes",
        ]
        if overridden:
            removed = {
                _PREMISE_FOR_KEY[key]
                for key in specified(assumptions)
                if key in _PREMISE_FOR_KEY
            }
            fixed_premises = [p for p in fixed_premises if p not in removed]

        document: dict[str, object] = {
            "schema_version": 1,
            "generated_by": "tools/finops_model.py --baseline-json",
        }
        if overridden:
            document["baseline_assumptions"] = False
            document["assumption_overrides"] = _assumption_overrides(assumptions)
            document["notice"] = _notice_text(assumptions, cells)
        document.update(
            {
                "region": REGION,
                "price_snapshot": PRICE_SNAPSHOT,
                "currency": "USD",
                "stored_gib": _count(sample.stored_gib, strict),
                "sizes_kib": list(BASELINE_SIZES_KIB),
                "pricing_depends_on_working_set": False,
                "price_inputs": ["object_size", "read_bytes", "write_bytes"],
                "fixed_premises": fixed_premises,
                "assumptions": _assumptions_block(assumptions, sample, overridden),
                "patterns": patterns,
            }
        )
        return document

    return _in_language(lang, build)


def _assumptions_block(
    assumptions: Assumptions | None, sample: BaselineCell, overridden: bool
) -> dict[str, object]:
    """The `assumptions` object of the JSON.

    Baseline: the current six keys, byte for byte. Override: the thirteen effective values plus the
    two existing keys that are not registry keys (`retention_months`, `s3files_expiration_days`),
    which a schema-1 reader still expects. The two auto keys read "auto" when unspecified.
    """
    if not overridden:
        return {
            "deployment": DEPLOYMENTS[sample.deployment]["api"],
            "efficiency_ssd": sample.efficiency_ssd,
            "pool_fraction": sample.pool_fraction,
            "retention_months": sample.retention_months,
            "s3files_threshold_kib": sample.s3files_threshold_kib,
            "s3files_expiration_days": sample.s3files_expiration_days,
        }
    resolved = resolve(assumptions)
    block = dict(resolved)
    block["retention_months"] = sample.retention_months
    block["s3files_expiration_days"] = sample.s3files_expiration_days
    return block


def baseline_table(lang: str = "ja", assumptions: Assumptions | None = None) -> str:
    """A compact Markdown table of the grid's FSx for ONTAP and S3 Files subtotals.

    One row per pattern, two columns per size (FSx for ONTAP, S3 Files). It introduces no new
    calculation — the subtotals are the same `fsx_s3ap` and `s3_files_option(split_metadata=True)`
    the document already prints. When the reader overrode any assumption, the notice is quoted at
    the top and an out-of-range cell is marked with `※`.
    """
    overridden = assumptions is not None and bool(specified(assumptions))

    def build() -> str:
        cells = baseline_cells(assumptions)
        by_key: dict[str, dict[float, BaselineCell]] = {}
        for cell in cells:
            by_key.setdefault(cell.pattern.key, {})[cell.object_kib] = cell
        out: list[str] = []
        if overridden:
            out += ["> " + _notice_text(assumptions, cells), ""]
        else:
            out += [t("基準の前提（公開文書と同じ）"), ""]
        headers = [t("パターン")]
        for size in BASELINE_SIZES_KIB:
            label = _size_label(size)
            headers += [
                t("{size} FSx for ONTAP", size=label),
                t("{size} S3 Files", size=label),
            ]
        rows: list[list[str]] = []
        any_out_of_range = False
        for pattern in BASELINE_PATTERNS:
            row = [pattern.key]
            for size in BASELINE_SIZES_KIB:
                cell = by_key[pattern.key][size]
                files = s3_files_option(cell, split_metadata=True)
                assert files is not None
                fsx_value = usd(sum(fsx_s3ap(cell).values()))
                if overridden and _throughput_out_of_model_range(cell):
                    fsx_value += "※"
                    any_out_of_range = True
                row += [fsx_value, usd(sum(files.values()))]
            rows.append(row)
        out += table(headers, rows)
        out.append("")
        if any_out_of_range:
            out += [
                t("※ 必要なスループットが最大段を超える。モデルの適用範囲外"),
                "",
            ]
        out += [
            t("主要費目小計。月額総額ではない。試算であり実測ではない"),
            "",
        ]
        return "\n".join(out).rstrip() + "\n"

    return _in_language(lang, build)


def _render_assumption_list(lang: str = "ja") -> str:
    """The `--list-assumptions` table: key, kind, baseline, domain, tier, description."""

    def build() -> str:
        headers = [
            t("キー"),
            t("型"),
            t("既定値"),
            t("検証"),
            t("基準値の区分"),
            t("読者が決められるか"),
            t("説明"),
        ]
        kind_word = {"float": t("数値"), "int": t("整数"), "enum": t("列挙")}
        rows: list[list[str]] = []
        for key, spec in ASSUMPTION_SPECS.items():
            baseline = spec.baseline()
            if spec.choices:
                domain = t("、").join(spec.choices)
            else:
                domain = t(spec.domain_text_ja) if spec.domain_text_ja else "—"
            rows.append(
                [
                    key,
                    kind_word[spec.kind],
                    _fmt(baseline),
                    domain,
                    t(spec.tier),
                    t(spec.reader_decides_ja),
                    t(spec.description_ja),
                ]
            )
        return "\n".join(table(headers, rows)).rstrip() + "\n"

    return _in_language(lang, build)


# ------------------------------------------------------------------ sensitivity (PR-B)
#
# The sensitivity section shows how the baseline subtotals move as each assumption is placed
# differently, and at what value the lower-subtotal side changes. The declarations below live here,
# not in ASSUMPTION_SPECS: a sweep point is a modelling choice of where to probe, and its range basis
# (sourced / observed / reused / mechanical) is the discipline the section exists to carry. No point
# is declared without a basis (a test enforces it), and the "sourced range" of a key is derived from
# these declarations rather than held as a second constant that could drift from them.

# The five figure patterns crossed with the two figure sizes. The 32-cell grid stays in the baseline
# section; here only these are shown, so the section stays readable.
SENSITIVITY_PATTERNS = ("P1", "P4", "P5", "P6", "P8")
SENSITIVITY_SIZES_KIB = (64, 4096)

# A sweep point: a value to probe, its range basis, which sizes it applies to, and a note. The basis
# is one of the four range vocabularies; the note carries a UNCONFIRMED-style caveat where one is
# owed (observation not confirmed in billing, source text not confirmed as charged).
RANGE_BASES = ("sourced", "observed", "reused", "mechanical")


@dataclass(frozen=True)
class SweepPoint:
    value: object  # float for numeric keys, str for enum keys
    basis: str  # one of RANGE_BASES
    sizes: tuple[int, ...]  # which of SENSITIVITY_SIZES_KIB this point applies to
    note_ja: str = ""

    def __post_init__(self) -> None:
        if self.basis not in RANGE_BASES:
            raise ValueError(
                f"range basis must be one of {RANGE_BASES}: {self.basis!r}"
            )
        for size in self.sizes:
            if size not in SENSITIVITY_SIZES_KIB:
                raise ValueError(f"sweep size {size} not in {SENSITIVITY_SIZES_KIB}")


_BOTH = SENSITIVITY_SIZES_KIB  # (64, 4096)
_K64 = (64,)
_M4 = (4096,)


# The sweep points per key. Baseline is not listed here; the render inserts the baseline row. Points
# within a key are listed in model (declaration) order. Enum keys ("deployment", "throughput_mbps"
# as a tier set, "first_read_mode", "first_read_stream_billing") carry their alternatives here too,
# but are handled in the one-at-a-time table's "direction differs" column, not the break-even table.
SWEEPS: dict[str, tuple[SweepPoint, ...]] = {
    "deployment": (
        SweepPoint(
            "MULTI_AZ_1", "sourced", _BOTH, "公式の提供形態。可用性構成も変わる"
        ),
        SweepPoint(
            "SINGLE_AZ_2", "sourced", _BOTH, "公式の提供形態。可用性構成も変わる"
        ),
        SweepPoint(
            "MULTI_AZ_2", "sourced", _BOTH, "公式の提供形態。可用性構成も変わる"
        ),
    ),
    "efficiency_ssd": (
        SweepPoint(0.0, "mechanical", _BOTH),
        SweepPoint(0.20, "mechanical", _BOTH),
        SweepPoint(0.65, "sourced", _BOTH, "AWS 公表表"),
        SweepPoint(0.75, "sourced", _BOTH, "AWS 公表表"),
    ),
    "pool_efficiency_retention": (
        SweepPoint(0.0, "mechanical", _BOTH),
        SweepPoint(0.25, "mechanical", _BOTH),
        SweepPoint(1.0, "mechanical", _BOTH),
    ),
    "pool_fraction": (
        SweepPoint(0.0, "reused", _BOTH, "別節のテレメトリ"),
        SweepPoint(0.50, "mechanical", _BOTH),
        SweepPoint(0.70, "reused", _BOTH, "別節の読み取り中心"),
        SweepPoint(
            0.80,
            "reused",
            _BOTH,
            "サイジングブログの cold:hot 80/20。cold:hot 比が pool_fraction と同じ量かは未確認",
        ),
        SweepPoint(0.95, "mechanical", _BOTH),
    ),
    "ssd_headroom": (
        SweepPoint(0.0, "mechanical", _BOTH),
        SweepPoint(
            0.25, "sourced", _BOTH, "公式の SSD 使用率 80% 以下の推奨から算術で導く"
        ),
        SweepPoint(0.50, "mechanical", _BOTH),
    ),
    "throughput_mbps": (
        SweepPoint(256, "sourced", _BOTH, "SINGLE_AZ_1 の段"),
        SweepPoint(512, "sourced", _BOTH, "SINGLE_AZ_1 の段"),
        SweepPoint(1024, "sourced", _BOTH, "SINGLE_AZ_1 の段"),
        SweepPoint(2048, "sourced", _BOTH, "SINGLE_AZ_1 の段"),
    ),
    "active_fraction": (
        SweepPoint(0.05, "mechanical", _K64),
        SweepPoint(0.10, "mechanical", _K64),
        SweepPoint(0.20, "mechanical", _K64),
        SweepPoint(0.50, "mechanical", _K64),
    ),
    "s3files_threshold_kib": (
        SweepPoint(32.0, "mechanical", _K64),
        SweepPoint(512.0, "mechanical", _K64),
    ),
    "first_read_mode": (
        SweepPoint(
            "none", "mechanical", _K64, "モデルの変種。部分計上で、向きは定まらない"
        ),
        SweepPoint(
            "working_set",
            "mechanical",
            _K64,
            "モデルの変種。部分計上で、向きは定まらない",
        ),
    ),
    "first_read_stream_billing": (
        SweepPoint(
            "file_read",
            "sourced",
            _K64,
            "公式の計量ページの例の文面が出典。課金の実際は未確認",
        ),
    ),
    "metadata_multiplier": (
        SweepPoint(0.0, "mechanical", _BOTH),
        SweepPoint(3.0, "mechanical", _BOTH),
        SweepPoint(
            2.0,
            "observed",
            _K64,
            "64 KiB の対照で約 2.0 回/個、1 オブジェクト 1 パス読み。CloudWatch 指標の 1 回の観測。64 KiB の対照と 4 MiB を合わせた全窓の合計が請求の読み取り数量と 0.5% 以内で一致 (点ごとの一致ではない、1 環境)、回数の内訳は未確認",
        ),
        SweepPoint(
            6.0,
            "observed",
            _M4,
            "4 MiB で約 6.0 回/個、1 オブジェクト 1 パス読み。CloudWatch 指標の 1 回の観測。64 KiB の対照と 4 MiB を合わせた全窓の合計が請求の読み取り数量と 0.5% 以内で一致 (点ごとの一致ではない、1 環境)、回数の内訳は未確認",
        ),
    ),
    "read_scale": (
        SweepPoint(0.1, "mechanical", _BOTH),
        SweepPoint(0.5, "mechanical", _BOTH),
        SweepPoint(2.0, "mechanical", _BOTH),
        SweepPoint(10.0, "mechanical", _BOTH),
    ),
    "stored_tib": (
        SweepPoint(5.0, "mechanical", _BOTH),
        SweepPoint(10.0, "mechanical", _BOTH),
        SweepPoint(50.0, "mechanical", _BOTH),
        SweepPoint(100.0, "mechanical", _BOTH),
    ),
}

# Keys handled by enumeration (no continuous break-even): their alternatives are shown in the
# one-at-a-time table's "direction differs" column, not the break-even table.
ENUM_SWEEP_KEYS = (
    "deployment",
    "throughput_mbps",
    "first_read_mode",
    "first_read_stream_billing",
)

# The continuous numeric keys the break-even table covers, plus the special-cased threshold key.
BREAKEVEN_NUMERIC_KEYS = (
    "pool_fraction",
    "efficiency_ssd",
    "pool_efficiency_retention",
    "ssd_headroom",
    "active_fraction",
    "metadata_multiplier",
    "read_scale",
    "stored_tib",
)

# Search domain [lo, hi] and axis per numeric key. "log" axes are geometric; "linear" are even. The
# zero of a multiplier axis is probed as a separate point. read_scale and stored_tib are truncated
# per cell to the model's applicable range (see _hi_model). The axis widths are mechanical choices;
# stored_tib's 2**10 upper bound has no sourced maximum (noted in the table).
SEARCH_DOMAINS: dict[str, dict[str, object]] = {
    "pool_fraction": {"lo": 0.0, "hi": 1.0, "axis": "linear"},
    "efficiency_ssd": {"lo": 0.0, "hi": 0.99, "axis": "linear"},
    "pool_efficiency_retention": {"lo": 0.0, "hi": 1.0, "axis": "linear"},
    "ssd_headroom": {"lo": 0.0, "hi": 1.0, "axis": "linear"},
    "active_fraction": {"lo": 0.0, "hi": 1.0, "axis": "linear"},
    "metadata_multiplier": {"lo": 2.0**-10, "hi": 2.0**24, "axis": "log", "zero": True},
    "read_scale": {"lo": 2.0**-10, "hi": 2.0**24, "axis": "log", "truncate": True},
    "stored_tib": {"lo": 2.0**-3, "hi": 2.0**10, "axis": "log", "truncate": True},
}

_BISECT_N = 256  # intervals the truncated domain is split into before bracketing
_BISECT_TOL = 1e-9  # relative half-width at which bisection stops
_BISECT_MAX_ITERS = 80
_STEP_USD = (
    1.0  # |d(b) - d(a)| above this on the final interval is reported as a step change
)
_EVAL_CAP = 100_000  # a bisection runaway tripwire, not a performance target


def sourced_range(key: str) -> tuple[float, float] | None:
    """The sourced range of a numeric key: min..max of its basis=='sourced' points, or None.

    Derived from SWEEPS, so there is one place a point's basis is stated. A single sourced point is
    not a range; the caller distinguishes that case by reading `sourced_points`.
    """
    values = sorted(sourced_points(key))
    if len(values) < 2:
        return None
    return (values[0], values[-1])


def sourced_points(key: str) -> list[float]:
    """Numeric values of a key's sourced sweep points (empty for enum-only or no sourced points)."""
    return [
        float(p.value)
        for p in SWEEPS.get(key, ())
        if p.basis == "sourced" and isinstance(p.value, (int, float))
    ]


def _sens_cell(
    pattern_key: str, kib: int, assumptions: Assumptions | None
) -> BaselineCell:
    """One figure cell under the given assumptions."""
    cells = baseline_cells(assumptions)
    return next(
        c for c in cells if c.pattern.key == pattern_key and c.object_kib == kib
    )


def _subtotals(cell: BaselineCell) -> tuple[float, float]:
    """(FSx for ONTAP S3 AP subtotal, S3 Files subtotal) for a cell, both split_metadata=True."""
    files = s3_files_option(cell, split_metadata=True)
    assert files is not None  # the grid is always viable for S3 Files
    return sum(fsx_s3ap(cell).values()), sum(files.values())


def _d(pattern_key: str, kib: int, key: str, value: object) -> float:
    """d(x) = S3 Files subtotal - FSx for ONTAP subtotal, with `key` set to `value`, others baseline."""
    cell = _sens_cell(pattern_key, kib, Assumptions(**{key: value}))
    fsx, files = _subtotals(cell)
    return files - fsx


def _sigma(d_value: float) -> int:
    """-1 when S3 Files is lower (d < 0), +1 otherwise. d == 0 falls to +1 (a determinism rule)."""
    return -1 if d_value < 0 else +1


def _hi_model(
    pattern_key: str, kib: int, key: str, assumptions: Assumptions | None
) -> float:
    """Largest multiplier of `key` keeping the cell inside the model's applicable range (M-5).

    read_scale and stored_tib scale required_mbps linearly, so a closed form gives the value at which
    required_mbps * (1 + headroom) reaches the maximum tier: x_b * max_tier / (base * (1 + headroom)).
    Returned as the key's own unit (a read_scale multiplier, or TiB for stored_tib).
    """
    base_cell = _sens_cell(pattern_key, kib, assumptions)
    max_tier = _max_tier(base_cell)
    headroom = base_cell.tput_headroom
    if key == "read_scale":
        x_b = 1.0
        base_required = base_cell.required_mbps  # at read_scale 1.0
    elif key == "stored_tib":
        x_b = base_cell.stored_gib / GIB_PER_TIB
        base_required = base_cell.required_mbps  # at the baseline stored volume
    else:
        return math.inf
    if base_required <= 0:
        return math.inf
    return x_b * max_tier / (base_required * (1.0 + headroom))


@dataclass(frozen=True)
class BreakEven:
    """One side change of a numeric key in a cell."""

    x_star: float
    low_below: str  # "FSx for ONTAP" or "S3 Files": the lower side for x < x_star
    low_above: str  # the lower side for x >= x_star
    step_change: bool  # the final interval's d jumps by more than _STEP_USD
    sourced_relation: (
        str  # "inside" | "outside" | "point_below" | "point_above" | "none"
    )


class _EvalCounter:
    """Counts d(x) evaluations across one render, so a test can assert the cap holds."""

    def __init__(self) -> None:
        self.count = 0

    def bump(self) -> None:
        self.count += 1
        if self.count > _EVAL_CAP:
            raise RuntimeError(f"sensitivity exceeded {_EVAL_CAP} evaluations")


def _domain_points(key: str, hi: float) -> list[float]:
    """The N+1 split points of [lo, hi] on the key's axis, plus a 0 point for a zero-bearing axis.

    hi is the already-truncated upper bound (hi' in the design): [lo, hi'] is split into N intervals,
    so a narrow applicable range still gets full resolution. The baseline value is inserted so the
    baseline direction is always one of the evaluated points.
    """
    domain = SEARCH_DOMAINS[key]
    lo = float(domain["lo"])
    axis = domain["axis"]
    points: list[float] = []
    if domain.get("zero"):
        points.append(0.0)
    if axis == "log":
        lo = max(lo, 1e-12)
        ratio = (hi / lo) ** (1.0 / _BISECT_N)
        points += [lo * ratio**i for i in range(_BISECT_N + 1)]
    else:
        step = (hi - lo) / _BISECT_N
        points += [lo + step * i for i in range(_BISECT_N + 1)]
    baseline = (
        float(ASSUMPTION_SPECS[key].baseline()) if _baseline_is_numeric(key) else None
    )
    if baseline is not None and lo <= baseline <= hi and baseline not in points:
        points.append(baseline)
    return sorted(set(points))


def _baseline_is_numeric(key: str) -> bool:
    try:
        return isinstance(float(ASSUMPTION_SPECS[key].baseline()), float)
    except (TypeError, ValueError):
        return False


def _midpoint(a: float, b: float, axis: str) -> float:
    """Geometric mean for a log axis away from zero; arithmetic mean otherwise."""
    if axis == "log" and a > 0 and b > 0:
        return math.sqrt(a * b)
    return (a + b) / 2.0


def _bisect_breakevens(
    pattern_key: str, kib: int, key: str, counter: _EvalCounter
) -> tuple[list[BreakEven], float]:
    """Every sign change of d(x) for a numeric key in a cell, and the truncated upper bound hi'.

    Deterministic: the domain is truncated to hi' first, split into N intervals, every adjacent pair
    with differing sigma is bisected to a fixed tolerance. No randomness, time, or environment.
    """
    domain = SEARCH_DOMAINS[key]
    axis = str(domain["axis"])
    hi = float(domain["hi"])
    if domain.get("truncate"):
        hi = min(hi, _hi_model(pattern_key, kib, key, None))

    def d_at(x: float) -> float:
        counter.bump()
        return _d(pattern_key, kib, key, x)

    points = [p for p in _domain_points(key, hi) if p <= hi + 1e-12]
    sigmas = [(x, _sigma(d_at(x))) for x in points]
    results: list[BreakEven] = []
    for (a, sa), (b, sb) in pairwise(sigmas):
        if sa == sb:
            continue
        lo_a, hi_b = a, b
        for _ in range(_BISECT_MAX_ITERS):
            if hi_b - lo_a <= _BISECT_TOL * max(1.0, abs(hi_b)):
                break
            m = _midpoint(lo_a, hi_b, axis)
            if _sigma(d_at(m)) == sa:
                lo_a = m
            else:
                hi_b = m
        x_star = _midpoint(lo_a, hi_b, axis)
        d_lo = d_at(lo_a)
        d_hi = d_at(hi_b)
        step = abs(d_hi - d_lo) > _STEP_USD
        low_below = "S3 Files" if sa < 0 else "FSx for ONTAP"
        low_above = "S3 Files" if sb < 0 else "FSx for ONTAP"
        results.append(
            BreakEven(
                x_star=x_star,
                low_below=low_below,
                low_above=low_above,
                step_change=step,
                sourced_relation=_sourced_relation(key, x_star),
            )
        )
    return results, hi


def _sourced_relation(key: str, x_star: float) -> str:
    """Where x_star sits relative to the key's sourced range (or single sourced point)."""
    rng = sourced_range(key)
    if rng is not None:
        return "inside" if rng[0] <= x_star <= rng[1] else "outside"
    points = sourced_points(key)
    if len(points) == 1:
        return "point_below" if x_star < points[0] else "point_above"
    return "none"


def _dense_has_no_sign_change(pattern_key: str, kib: int, key: str) -> bool:
    """A 4096-point dense sweep of the truncated domain shows no sign change (for the "none" claim).

    Used only by the test backstop, not by the rendered sentences. Returns True when sigma never
    changes across the dense grid, so a break-even missed by the 256-interval split would be caught.
    """
    domain = SEARCH_DOMAINS[key]
    axis = str(domain["axis"])
    lo = float(domain["lo"])
    hi = float(domain["hi"])
    if domain.get("truncate"):
        hi = min(hi, _hi_model(pattern_key, kib, key, None))
    n = 4096
    xs: list[float] = []
    if domain.get("zero"):
        xs.append(0.0)
    if axis == "log":
        lo = max(lo, 1e-12)
        ratio = (hi / lo) ** (1.0 / n)
        xs += [lo * ratio**i for i in range(n + 1)]
    else:
        step = (hi - lo) / n
        xs += [lo + step * i for i in range(n + 1)]
    sigmas = {_sigma(_d(pattern_key, kib, key, x)) for x in xs}
    return len(sigmas) == 1


def _out_of_model(cell: BaselineCell) -> bool:
    """The cell's required throughput exceeds the maximum tier with throughput auto (M-5)."""
    return _throughput_out_of_model_range(cell)


def _low_side(fsx: float, files: float) -> str:
    """The lower-subtotal side, as a product name (never a quality word)."""
    return "S3 Files" if files < fsx else "FSx for ONTAP"


def _side_label(side: str) -> str:
    """Localized product name for a side token."""
    return side if side == "S3 Files" else t("FSx for ONTAP")


def _sens_cell_subtotals(
    pattern_key: str, kib: int, assumptions: Assumptions | None
) -> str:
    """A cell as `FSx for ONTAP {usd} / S3 Files {usd}`, with ※ when out of the applicable range."""
    cell = _sens_cell(pattern_key, kib, assumptions)
    fsx, files = _subtotals(cell)
    mark = " ※" if _out_of_model(cell) else ""
    return t(
        "FSx for ONTAP {fsx} / S3 Files {files}{mark}",
        fsx=usd(fsx),
        files=usd(files),
        mark=mark,
    )


def _direction_differs(key: str, value: object, sizes: tuple[int, ...]) -> str:
    """Patterns whose lower side differs from the baseline when `key`=`value`, over `sizes`.

    A cell driven out of the applicable range by the value is excluded from the direction judgement
    (its subtotal is not a real configuration), per M-5.
    """
    differing: list[str] = []
    for kib in sizes:
        for pattern_key in SENSITIVITY_PATTERNS:
            base_cell = _sens_cell(pattern_key, kib, None)
            base_fsx, base_files = _subtotals(base_cell)
            base_low = _low_side(base_fsx, base_files)
            over_cell = _sens_cell(pattern_key, kib, Assumptions(**{key: value}))
            if _out_of_model(over_cell):
                continue
            over_fsx, over_files = _subtotals(over_cell)
            over_low = _low_side(over_fsx, over_files)
            if over_low != base_low:
                differing.append(f"{pattern_key} {_size_label(kib)}")
    return t("、").join(differing) if differing else "—"


def _basis_word(basis: str) -> str:
    return {
        "sourced": t("出典"),
        "observed": t("観測"),
        "reused": t("再利用"),
        "mechanical": t("機械的"),
    }[basis]


def _tier_word(tier: str) -> str:
    return t(tier)


def _n_eq_1_pattern(pattern_key: str) -> bool:
    """P1 and P8 read each working-set object once (n=1); the metadata observation matches them."""
    pattern = next(p for p in BASELINE_PATTERNS if p.key == pattern_key)
    return pattern.reads_per_object == 1


# -------------------------------------------------------------------- the eight subsections


def _sens_intro() -> list[str]:
    """The `###` heading, the introduction, the direction sentences, and the fixed misreading notes."""
    base_pct_pool = f"{BASELINE_POOL_FRACTION:.0%}".rstrip("%")
    out = [
        t("### 基準の前提と感度"),
        "",
        t(
            "この節は、基準の前提（論理 20 TiB、capacity pool {pool}%、SSD 効率 {eff}% など）で出した"
            "小計が、前提の置き方でどう動くかを示す。表の小計はモデルの計算値で、実測ではない。"
            "いずれも**主要費目小計**であって月額総額ではない。",
            pool=base_pct_pool,
            eff=f"{BASELINE_EFFICIENCY_SSD:.0%}".rstrip("%"),
        ),
        "",
        t(
            "対象は、図で使う 5 パターン（{patterns}）× 2 サイズ（64 KiB、4 MiB）である。"
            "32 セル全部の格子は「共通ベースライン」の節にある。"
            "小計の低い側はセルに印を置かず、基準と低い側が入れ替わったパターンを別列に挙げる。",
            patterns=t("・").join(SENSITIVITY_PATTERNS),
        ),
        "",
    ]
    out += _sens_direction_sentences()
    out += [
        t("#### 誤読を防ぐ注"),
        "",
    ]
    notes = [
        t(
            "1. 前提を動かす範囲には、出典のあるものと機械的なものがある。表の「範囲の根拠」列で"
            "区別する。機械的な値（0%、50%、100%、0.5 倍、2 倍など）は、振る位置を決めただけで、"
            "確率的な幅や起こりやすさを表さない。"
        ),
        t(
            "2. 出典の厚みが両側で違う。FSx for ONTAP 側には効率、cold:hot 比、SSD 使用率の推奨、"
            "デプロイ形態に公式の数値がある。S3 Files 側のアクティブ割合には、今回読んだ公式ページに"
            "数値の範囲がない。表で FSx for ONTAP の前提の行が出典ありで、S3 Files の前提の行が"
            "機械的な範囲に偏るのは、この差による。"
        ),
        t(
            "3. 小計の動く幅を製品の性質と読まない。4 MiB のセルの S3 Files の小計は S3 Standard の"
            "保管料が大半を占める。動きが小さいのはこのセルの構成による。"
        ),
        t(
            "4. 「出典のある範囲」は、範囲の根拠が「出典」の点の最小〜最大の区間である。"
            "点が 1 つしかない前提は区間にならず、「出典のある値が 1 点」と書く。"
        ),
        t(
            "5. FSx for ONTAP の小計は、必要なスループットが構成の最大段を超えると、最大段で頭打ちになる。"
            "その領域はモデルの適用範囲外である。損益分岐の算出は、探索範囲を適用範囲の上限で切り詰めて"
            "この領域を含めない。1 つずつ動かした表・シナリオ・2 つの前提の組の表では、適用範囲外に"
            "落ちたセルの値に ※ を付けて載せ、そのセルを向きの導出から除く。"
        ),
        t(
            "6. 「1 つずつ動かした表」は、他の前提を基準に固定している。複数を同時に動かした結果は"
            "「シナリオ」の節にある。1 つずつでは向きが変わらない前提でも、同時に動かすと変わりうる。"
        ),
        t(
            "7. 基準の値は推奨値ではない。基準は、全パターンを同じ条件で並べるために置いた値である。"
        ),
        t(
            "8. 基準の前提では、アクティブ割合は上限の 100% で、S3 Files の小計を上げる方向に"
            "動かせる余地がない。この前提は下げる方向にだけ振る。これは基準の置き方の性質で、"
            "製品の性質を述べるものではない。"
        ),
    ]
    for note in notes:
        out += [note, ""]
    return out


def _sens_direction_sentences() -> list[str]:
    """The five data-driven direction sentences, each with a true/false branch chosen from the model."""
    out: list[str] = []
    out += _direction_baseline_sentence()
    out += _direction_4mib_sentence()
    out += _direction_4mib_simultaneous_sentence()
    out += _direction_64kib_sentence()
    out += _direction_unmeasured_sentence()
    return out


def _baseline_low_sides(kib: int) -> dict[str, str]:
    """The lower side of each figure pattern at a size, under the baseline assumptions."""
    sides: dict[str, str] = {}
    for pattern_key in SENSITIVITY_PATTERNS:
        fsx, files = _subtotals(_sens_cell(pattern_key, kib, None))
        sides[pattern_key] = _low_side(fsx, files)
    return sides


def _direction_baseline_sentence() -> list[str]:
    low64 = _baseline_low_sides(64)
    low4m = _baseline_low_sides(4096)
    same64 = len(set(low64.values())) == 1
    same4m = len(set(low4m.values())) == 1
    opposed = (
        same64 and same4m and next(iter(low64.values())) != next(iter(low4m.values()))
    )
    if opposed:
        sentence = t(
            "基準の前提では、図の 5 パターンのうち 64 KiB のセルは {low64} の小計が低く、"
            "4 MiB のセルは {low4m} の小計が低い。向きを分けているのはオブジェクトサイズである。",
            low64=_side_label(next(iter(low64.values()))),
            low4m=_side_label(next(iter(low4m.values()))),
        )
    else:
        parts: list[str] = []
        for kib in SENSITIVITY_SIZES_KIB:
            sides = low64 if kib == 64 else low4m
            for pattern_key in SENSITIVITY_PATTERNS:
                parts.append(
                    t(
                        "{pattern} {size}: {low}",
                        pattern=pattern_key,
                        size=_size_label(kib),
                        low=_side_label(sides[pattern_key]),
                    )
                )
        sentence = t(
            "基準の前提で小計が低い側は、セルごとに次のとおり: {cells}。",
            cells=t("、").join(parts),
        )
    return [sentence, ""]


def _4mib_sourced_sign_changes() -> dict[str, list[str]]:
    """4 MiB patterns whose direction changes at any sourced point, keyed by `key=value`."""
    changes: dict[str, list[str]] = {}
    for key, points in SWEEPS.items():
        for point in points:
            if 4096 not in point.sizes or point.basis != "sourced":
                continue
            differing: list[str] = []
            for pattern_key in SENSITIVITY_PATTERNS:
                base_fsx, base_files = _subtotals(_sens_cell(pattern_key, 4096, None))
                over_cell = _sens_cell(
                    pattern_key, 4096, Assumptions(**{key: point.value})
                )
                if _out_of_model(over_cell):
                    continue
                over_fsx, over_files = _subtotals(over_cell)
                if _low_side(over_fsx, over_files) != _low_side(base_fsx, base_files):
                    differing.append(pattern_key)
            if differing:
                changes[f"{key}={_fmt(point.value)}"] = differing
    return changes


def _direction_4mib_sentence() -> list[str]:
    counter = _EvalCounter()
    sourced_changes = _4mib_sourced_sign_changes()
    # x* for each numeric key outside the sourced range, over all 4 MiB figure cells.
    outside_by_key: dict[str, list[float]] = {}
    for key in BREAKEVEN_NUMERIC_KEYS:
        xs: list[float] = []
        for pattern_key in SENSITIVITY_PATTERNS:
            results, _ = _bisect_breakevens(pattern_key, 4096, key, counter)
            for be in results:
                if be.sourced_relation in (
                    "outside",
                    "point_below",
                    "point_above",
                    "none",
                ):
                    xs.append(be.x_star)
        if xs:
            outside_by_key[key] = xs
    if not sourced_changes:
        if outside_by_key:
            clauses: list[str] = []
            for key, xs in outside_by_key.items():
                lo, hi = min(xs), max(xs)
                clauses.append(
                    t(
                        "{key} が {lo}〜{hi} の範囲で低い側が入れ替わる",
                        key=key,
                        lo=f"{lo:.3g}",
                        hi=f"{hi:.3g}",
                    )
                )
            sentence = t(
                "4 MiB のセルは、出典のある点で前提を 1 つずつ動かしても向きが変わらない。"
                "出典のある範囲の外では、{clauses}（詳細は損益分岐の表）。",
                clauses=t("、").join(clauses),
            )
        else:
            sentence = t(
                "4 MiB のセルは、出典のある点で前提を 1 つずつ動かしても向きが変わらない。"
                "出典のある範囲の外でも、探索範囲では向きが変わらない。"
            )
    else:
        parts = [
            t("{kv}: {pats}", kv=kv, pats=t("・").join(pats))
            for kv, pats in sourced_changes.items()
        ]
        sentence = t(
            "4 MiB のセルのうち、出典のある点で向きが変わるのは次のとおり: {parts}。",
            parts=t("、").join(parts),
        )
    return [sentence, ""]


def _direction_4mib_simultaneous_sentence() -> list[str]:
    j1 = _scenario_assumptions("J1")
    flips = 0
    for pattern_key in SENSITIVITY_PATTERNS:
        base_fsx, base_files = _subtotals(_sens_cell(pattern_key, 4096, None))
        over_fsx, over_files = _subtotals(_sens_cell(pattern_key, 4096, j1))
        if _low_side(over_fsx, over_files) != _low_side(base_fsx, base_files):
            flips += 1
    if flips == 0:
        sentence = t("J1 では 4 MiB のどのパターンでも低い側は変わらない。")
    else:
        # Which single-key revert keeps or removes the flip.
        kept: list[str] = []
        removed: list[str] = []
        for key in ("pool_fraction", "efficiency_ssd", "pool_efficiency_retention"):
            reverted = _scenario_assumptions("J1", drop=key)
            still = 0
            for pattern_key in SENSITIVITY_PATTERNS:
                base_fsx, base_files = _subtotals(_sens_cell(pattern_key, 4096, None))
                over_fsx, over_files = _subtotals(
                    _sens_cell(pattern_key, 4096, reverted)
                )
                if _low_side(over_fsx, over_files) != _low_side(base_fsx, base_files):
                    still += 1
            (kept if still > 0 else removed).append(key)
        sentence = t(
            "FSx for ONTAP の小計が下がる側へ 3 前提を同時に動かすと（J1）、{n} パターンで"
            "低い側が入れ替わる。3 前提のうち pool 層の効率の保持（1.0）には出典がない。"
            "J1 から 1 前提だけを基準に戻すと、入れ替わりが残るのは {kept}、消えるのは {removed} である。",
            n=flips,
            kept=t("・").join(kept) if kept else t("なし"),
            removed=t("・").join(removed) if removed else t("なし"),
        )
    return [sentence, ""]


def _direction_64kib_sentence() -> list[str]:
    counter = _EvalCounter()
    per_pattern: dict[str, float] = {}
    for pattern_key in SENSITIVITY_PATTERNS:
        results, _ = _bisect_breakevens(pattern_key, 64, "active_fraction", counter)
        if results:
            per_pattern[pattern_key] = results[0].x_star
    if per_pattern:
        parts = [
            t("{pattern} {x}", pattern=k, x=f"{v:.3g}") for k, v in per_pattern.items()
        ]
        sentence = t(
            "64 KiB のセルの向きは、S3 Files の高性能ストレージのアクティブ割合に依存する。"
            "アクティブ割合が {parts}（それぞれ以下）で S3 Files の小計が低くなる。"
            "残りのパターンは探索範囲では入れ替わらない。基準の値は 100% で、この割合は"
            "**仮置き・未測定**である。",
            parts=t("、").join(parts),
        )
        observation = t(
            "隣接の実測では、作業セット 5% / 20% のとき `StorageBytes` の 5.47% / 21.89% が"
            "高性能ストレージの指標に載った（1 回の観測、2026-10-17、ap-northeast-1、"
            "`ON_DIRECTORY_FIRST_ACCESS`。`StorageBytes` はデータとメタデータの合計で、"
            "作業セット比は実験が設定した値。アクティブ割合そのものの測定ではない）。"
        )
        return [sentence, "", observation, ""]
    sentence = t(
        "64 KiB のセルは、アクティブ割合を 0〜100% の範囲で動かしても向きが変わらない。"
        "基準の値は 100% で、この割合は**仮置き・未測定**である。"
    )
    return [sentence, ""]


def _direction_unmeasured_sentence() -> list[str]:
    placeholder_keys = [
        key for key, spec in ASSUMPTION_SPECS.items() if spec.tier == "仮置き"
    ]
    sentence = t(
        "{keys} は未測定または出典のない仮置きである。表の値はこれらを仮置きしたものである。",
        keys=t("、").join(placeholder_keys),
    )
    return [sentence, ""]


def _sens_assumption_list() -> list[str]:
    """#### 前提の一覧: the registry keys plus the immovable premises, with tier and moving side."""
    out = [
        t("#### 前提の一覧"),
        "",
        t(
            "「基準値の区分」は基準値の出どころ（公式 / 観測 / 試算前提 / 仮置き / 定義）で、"
            "次の表の「範囲の根拠」（出典 / 観測 / 再利用 / 機械的）とは別の区分である。"
            "「出典のある範囲」は、範囲の根拠が「出典」の点の最小〜最大の区間を指す。"
            "「再利用」は、このリポジトリの別の節が置いた値の再利用で、外部の根拠でも測定でもない。"
        ),
        "",
    ]
    headers = [
        t("前提"),
        t("基準の値"),
        t("基準値の区分"),
        t("出典・根拠"),
        t("読者が決められるか"),
        t("小計が動く側"),
    ]
    rows: list[list[str]] = []
    for key, spec in ASSUMPTION_SPECS.items():
        rows.append(
            [
                f"`{key}`",
                _fmt(spec.baseline()),
                _tier_word(spec.tier),
                t(spec.description_ja),
                t(spec.reader_decides_ja),
                _moving_side(key),
            ]
        )
    # Immovable premises.
    rows += [
        [
            t("リージョン"),
            f"`{REGION}`",
            _tier_word("定義"),
            t("検証リージョン"),
            t("—"),
            t("—"),
        ],
        [
            t("単価の日付"),
            PRICE_SNAPSHOT,
            _tier_word("定義"),
            t("Price List のスナップショット日"),
            t("—"),
            t("—"),
        ],
        [
            t("保存量の定義"),
            t("論理 {tib} TiB", tib=BASELINE_STORED_TIB),
            _tier_word("定義"),
            t("全セル共通の土俵"),
            t("—"),
            t("—"),
        ],
        [
            t("価格の作業セット比非連動"),
            t("連動しない"),
            _tier_word("定義"),
            t("金額は読み書き量とサイズで決まる"),
            t("—"),
            t("—"),
        ],
    ]
    out += table(headers, rows)
    out += [""]
    return out


MOVE_EPS_USD = (
    1e-6  # a subtotal that differs from the baseline by more than this has "moved"
)


def _moving_flags(key: str, kib: int) -> tuple[bool, bool] | None:
    """Whether `key` moves P4's (FSx for ONTAP, S3 Files) subtotal at `kib`; None if not tried there.

    "Tried" means a SWEEPS point of the key applies to this size. This is the single place the
    moving-side judgement is made: `_moving_side` (the table column, both sizes together) and
    `sensitivity_json`'s `assumption_axes[key].moves_p4` (one size at a time) both read it.
    """
    points = [p for p in SWEEPS.get(key, ()) if kib in p.sizes]
    if not points:
        return None
    base_fsx, base_files = _subtotals(_sens_cell("P4", kib, None))
    moves_fsx = False
    moves_files = False
    for point in points:
        over_fsx, over_files = _subtotals(
            _sens_cell("P4", kib, Assumptions(**{key: point.value}))
        )
        if abs(over_fsx - base_fsx) > MOVE_EPS_USD:
            moves_fsx = True
        if abs(over_files - base_files) > MOVE_EPS_USD:
            moves_files = True
    return moves_fsx, moves_files


def _moving_word(flags: tuple[bool, bool] | None) -> str | None:
    """The `moves_p4` vocabulary: fsx / s3_files / both / none, or None when not tried."""
    if flags is None:
        return None
    return {
        (True, True): "both",
        (True, False): "fsx",
        (False, True): "s3_files",
        (False, False): "none",
    }[flags]


def _moving_side(key: str) -> str:
    """Which subtotal a key moves: FSx for ONTAP / S3 Files / both, derived from the model."""
    moves_fsx = False
    moves_files = False
    for kib in SENSITIVITY_SIZES_KIB:
        flags = _moving_flags(key, kib)
        if flags is not None:
            moves_fsx = moves_fsx or flags[0]
            moves_files = moves_files or flags[1]
    if moves_fsx and moves_files:
        return t("両側")
    if moves_fsx:
        return t("FSx for ONTAP")
    if moves_files:
        return "S3 Files"
    return t("—")


def _sens_one_at_a_time() -> list[str]:
    """#### 前提を 1 つずつ動かしたときの小計: one table per size, baseline row first."""
    out = [
        t("#### 前提を 1 つずつ動かしたときの小計"),
        "",
        t(
            "他の前提を基準に固定し、1 つの前提だけを動かしたときの小計である。"
            "セルは `FSx for ONTAP {小計} / S3 Files {小計}`（USD / 月、主要費目小計）。"
            "低い側を示す印は置かず、「向きが基準と異なるパターン」列に、基準と低い側が入れ替わった"
            "パターンを並べる（なければ —）。※ は必要なスループットが最大段を超え、モデルの適用範囲外のセル。"
        ),
        "",
    ]
    for kib in SENSITIVITY_SIZES_KIB:
        out += _one_at_a_time_table(kib)
    return out


def _one_at_a_time_table(kib: int) -> list[str]:
    headers = [
        t("前提"),
        t("値"),
        *SENSITIVITY_PATTERNS,
        t("向きが基準と異なるパターン"),
        t("範囲の根拠"),
    ]
    rows: list[list[str]] = []
    # Baseline row.
    rows.append(
        [
            t("基準"),
            t("基準"),
            *[_sens_cell_subtotals(p, kib, None) for p in SENSITIVITY_PATTERNS],
            "—",
            "—",
        ]
    )
    unmoved_keys: list[str] = []
    for key, points in SWEEPS.items():
        applicable = [p for p in points if kib in p.sizes]
        if not applicable:
            continue
        # Does the key move any of the five patterns' subtotals at this size?
        moved = False
        for point in applicable:
            for pattern_key in SENSITIVITY_PATTERNS:
                base = _subtotals(_sens_cell(pattern_key, kib, None))
                over = _subtotals(
                    _sens_cell(pattern_key, kib, Assumptions(**{key: point.value}))
                )
                if abs(over[0] - base[0]) > 1e-9 or abs(over[1] - base[1]) > 1e-9:
                    moved = True
                    break
            if moved:
                break
        if not moved:
            unmoved_keys.append(key)
            continue
        for point in applicable:
            note = ""
            if key == "metadata_multiplier" and point.basis == "observed":
                # n>1 patterns need the UNCONFIRMED re-read note.
                note = t("（n>1 のパターンは再読み取りの操作数が未測定）")
            rows.append(
                [
                    f"`{key}`" if point is applicable[0] else "",
                    _fmt(point.value),
                    *[
                        _sens_cell_subtotals(p, kib, Assumptions(**{key: point.value}))
                        for p in SENSITIVITY_PATTERNS
                    ],
                    _direction_differs(key, point.value, (kib,)),
                    f"{_basis_word(point.basis)}{note}",
                ]
            )
    out = [
        t("オブジェクト {size} の場合", size=_size_label(kib)),
        "",
        *table(headers, rows),
        "",
    ]
    if unmoved_keys:
        out += [
            t(
                "このサイズでは次の前提は小計を動かさない: {keys}。",
                keys=t("、").join(f"`{k}`" for k in unmoved_keys),
            ),
            "",
        ]
    return out


def _sens_breakeven(counter: _EvalCounter) -> list[str]:
    """#### 小計の高低が入れ替わる前提の値: deterministic bisection per numeric key, two tables."""
    out = [
        t("#### 小計の高低が入れ替わる前提の値"),
        "",
        t(
            "連続な数値の前提について、低い側が入れ替わる値 x* を決定的な二分法で求める。"
            "探索範囲を適用範囲の上限で切り詰め、256 区間に分けて符号の変わる区間を二分する。"
            "値は有効数字 3 桁。「なし」は探索範囲内で入れ替わらないことを指し、範囲外の主張はしない。"
            "列挙の前提（`deployment`、`throughput_mbps`、`first_read_mode`、`first_read_stream_billing`）は、"
            "「前提を 1 つずつ動かしたとき」の表の「向きが基準と異なるパターン」列で扱う。"
            "`active_fraction` は 64 KiB のみ、4 MiB は「対象外」。"
        ),
        "",
    ]
    headers = [
        t("前提"),
        *[f"64 KiB {p}" for p in SENSITIVITY_PATTERNS],
        *[f"4 MiB {p}" for p in SENSITIVITY_PATTERNS],
    ]
    rows: list[list[str]] = []
    for key in BREAKEVEN_NUMERIC_KEYS:
        row = [f"`{key}`"]
        for kib in SENSITIVITY_SIZES_KIB:
            for pattern_key in SENSITIVITY_PATTERNS:
                row.append(_breakeven_cell(pattern_key, kib, key, counter))
        rows.append(row)
    # s3files_threshold_kib handled by the size comparison, 64 KiB only.
    rows.append(_threshold_row())
    out += table(headers, rows)
    # Search ranges note.
    out += ["", _breakeven_ranges_note(), ""]
    return out


def _breakeven_cell(pattern_key: str, kib: int, key: str, counter: _EvalCounter) -> str:
    if key == "active_fraction" and kib == 4096:
        return t("対象外")
    results, hi = _bisect_breakevens(pattern_key, kib, key, counter)
    truncated = SEARCH_DOMAINS[key].get("truncate")
    if not results:
        if truncated:
            return t("なし（{hi} まで）", hi=f"{hi:.3g}")
        return t("なし")
    parts: list[str] = []
    for be in results:
        rel = _sourced_relation_text(key, be.sourced_relation)
        step = t("、段差") if be.step_change else ""
        parts.append(
            t(
                "{x}（{below}未満で{low_below}、以上で{low_above}{rel}{step}）",
                x=f"{be.x_star:.3g}",
                below="",
                low_below=_side_label(be.low_below),
                low_above=_side_label(be.low_above),
                rel=rel,
                step=step,
            )
        )
    return t("、").join(parts)


def _sourced_relation_text(key: str, relation: str) -> str:
    if relation == "inside":
        return t("、出典のある範囲内")
    if relation == "outside":
        return t("、出典のある範囲の外")
    if relation in ("point_below", "point_above"):
        pts = sourced_points(key)
        value = pts[0] if pts else 0.0
        side = t("より小さい") if relation == "point_below" else t("より大きい")
        return t(
            "、出典のある値は 1 点（{value}）で x* はそれ{side}",
            value=f"{value:g}",
            side=side,
        )
    return t("、出典のある範囲なし（機械的な探索範囲）")


def _threshold_row() -> list[str]:
    """s3files_threshold_kib: a size comparison, not a continuous axis. 64 KiB only."""
    row = ["`s3files_threshold_kib`"]
    for kib in SENSITIVITY_SIZES_KIB:
        for pattern_key in SENSITIVITY_PATTERNS:
            if kib >= 1024:
                row.append(t("対象外"))
                continue
            # below-size (32 KiB) vs above-size-under-1MiB (512 KiB) representatives.
            base_cell = _sens_cell(pattern_key, kib, None)
            base_low = _low_side(*_subtotals(base_cell))
            below = _sens_cell(
                pattern_key, kib, Assumptions(s3files_threshold_kib=32.0)
            )
            above = _sens_cell(
                pattern_key, kib, Assumptions(s3files_threshold_kib=512.0)
            )
            below_low = _low_side(*_subtotals(below))
            above_low = _low_side(*_subtotals(above))
            if below_low != base_low or above_low != base_low:
                row.append(
                    t("しきい値が {size} 未満のとき入れ替わる", size=_size_label(kib))
                )
            else:
                row.append(t("なし"))
    return row


def _breakeven_ranges_note() -> str:
    parts: list[str] = []
    for key in BREAKEVEN_NUMERIC_KEYS:
        domain = SEARCH_DOMAINS[key]
        lo, hi = float(domain["lo"]), float(domain["hi"])
        parts.append(t("`{key}`: {lo}〜{hi}", key=key, lo=f"{lo:.3g}", hi=f"{hi:.3g}"))
    return t(
        "探索範囲 [lo, hi]: {ranges}。`read_scale` と `stored_tib` の上限は、"
        "必要スループットが最大段以内に収まる値（セルごと）で切り詰める。"
        "`stored_tib` の上限 {stored_hi} TiB は出典のない機械的な値である。"
        "区間内に 2 点以上の入れ替わりが 1 区間（1/256）に収まる場合は検出できない"
        "（テストの密な走査で現行の価格では見落としがないことを確かめている）。",
        ranges=t("、").join(parts),
        stored_hi=f"{float(SEARCH_DOMAINS['stored_tib']['hi']):.3g}",
    )


# -------------------------------------------------------------------- scenarios (J0-J4)

# Each scenario is a set of simultaneous assumption overrides. J4 uses a size-specific
# metadata_multiplier (2 at 64 KiB, 6 at 4 MiB), so its value is resolved per size.
SCENARIO_DEFS: dict[str, dict[str, object]] = {
    "J0": {"name_ja": "基準の前提", "n": 0, "overrides": {}, "basis_ja": "—"},
    "J1": {
        "name_ja": "FSx for ONTAP の小計が下がる側へ 3 前提を同時に寄せる",
        "n": 3,
        "overrides": {
            "pool_fraction": 0.80,
            "efficiency_ssd": 0.75,
            "pool_efficiency_retention": 1.0,
        },
        "basis_ja": "出典 1（効率 0.75、AWS 公表表）、再利用 1（pool 0.80、cold:hot を当てた。算出方法は未確認）、機械的 1（保持 1.0、出典なし）",
    },
    "J2": {
        "name_ja": "FSx for ONTAP の小計が上がる側へ 3 前提を同時に寄せる",
        "n": 3,
        "overrides": {
            "pool_fraction": 0.0,
            "efficiency_ssd": 0.0,
            "ssd_headroom": 0.25,
        },
        "basis_ja": "再利用 1（pool 0）、機械的 1（効率 0）、出典 1（余裕 0.25）",
    },
    "J3": {
        "name_ja": "S3 Files の小計が下がる側へ 2 前提を同時に寄せる",
        "n": 2,
        "overrides": {"active_fraction": 0.05, "metadata_multiplier": 0.0},
        "basis_ja": "すべて機械的",
    },
    "J4": {
        "name_ja": "S3 Files の小計が上がる側へ 2 前提を同時に寄せる",
        "n": 2,
        "overrides": {
            "first_read_stream_billing": "file_read",
            "metadata_multiplier": None,
        },
        "basis_ja": "出典 1（公式の例の文面。課金の実際は未確認）、観測 1（サイズ別の 1 回の観測。全窓の合計(点ごとではない)は請求の読み取り数量と一致、回数の内訳は未確認）",
    },
}

# The intended lower-moving side of each direction-bearing scenario, used by the render-time check.
SCENARIO_DIRECTION: dict[str, str] = {
    "J1": "FSx for ONTAP",  # the FSx subtotal goes down
    "J2": "FSx for ONTAP",  # the FSx subtotal goes up
    "J3": "S3 Files",
    "J4": "S3 Files",
}


def _scenario_assumptions(
    scenario_id: str, kib: int | None = None, drop: str | None = None
) -> Assumptions:
    """The Assumptions for a scenario, resolving J4's size-specific metadata_multiplier.

    `drop` removes one key (used to decompose J1 / J3 by reverting one premise to baseline).
    """
    overrides = dict(SCENARIO_DEFS[scenario_id]["overrides"])
    if "metadata_multiplier" in overrides and overrides["metadata_multiplier"] is None:
        overrides["metadata_multiplier"] = 6.0 if kib == 4096 else 2.0
    if drop is not None:
        overrides.pop(drop, None)
    return Assumptions(**overrides)


def _check_scenario_directions() -> None:
    """A direction-bearing scenario name must not be contradicted by any figure cell (M-2).

    The check fails the render if a cell's lower side flips the opposite way to the scenario's name.
    A cell where the subtotal does not move (J4's file_read at 4 MiB) is not a contradiction.
    """
    for scenario_id, moving_side in SCENARIO_DIRECTION.items():
        for kib in SENSITIVITY_SIZES_KIB:
            assumptions = _scenario_assumptions(scenario_id, kib)
            for pattern_key in SENSITIVITY_PATTERNS:
                base_fsx, base_files = _subtotals(_sens_cell(pattern_key, kib, None))
                over_fsx, over_files = _subtotals(
                    _sens_cell(pattern_key, kib, assumptions)
                )
                # The named side must not move up when the name says the opposite.
                if moving_side == "FSx for ONTAP":
                    up = SCENARIO_DEFS[scenario_id]["name_ja"].find("上がる") >= 0
                    moved = over_fsx - base_fsx
                else:
                    up = SCENARIO_DEFS[scenario_id]["name_ja"].find("上がる") >= 0
                    moved = over_files - base_files
                # "down" scenario: a positive move on the named side contradicts the name.
                if not up and moved > 1e-6:
                    raise ValueError(
                        f"{scenario_id} names a decrease but {pattern_key} {kib} moves "
                        f"{moving_side} up by {moved:.4f}"
                    )
                if up and moved < -1e-6:
                    raise ValueError(
                        f"{scenario_id} names an increase but {pattern_key} {kib} moves "
                        f"{moving_side} down by {-moved:.4f}"
                    )


def _sens_two_assumptions(counter: _EvalCounter) -> list[str]:
    """#### 2 つの前提の組での入れ替わり: active_fraction x pool_fraction, efficiency_ssd x pool."""
    out = [
        t("#### 2 つの前提の組での入れ替わり"),
        "",
        t(
            "1 次元の損益分岐は他の前提に依存する。依存の大きい 2 つの組を同じ算出で出す。"
            "セルは入れ替わる値 x*（なければ「なし」）。"
        ),
        "",
    ]
    # Table 1: active_fraction break-even, fixing pool_fraction, 64 KiB.
    out += [
        t("固定: `pool_fraction`、動かす: `active_fraction`（64 KiB）"),
        "",
    ]
    pool_fixes_1 = (0.0, 0.30, 0.50, 0.80, 0.95)
    headers1 = [t("`pool_fraction`"), *SENSITIVITY_PATTERNS]
    rows1: list[list[str]] = []
    for pool in pool_fixes_1:
        row = [_fmt(pool)]
        for pattern_key in SENSITIVITY_PATTERNS:
            row.append(
                _two_dim_cell(
                    pattern_key, 64, "active_fraction", {"pool_fraction": pool}, counter
                )
            )
        rows1.append(row)
    out += table(headers1, rows1)
    out += [""]
    # Table 2: efficiency_ssd break-even, fixing pool_fraction x pool_efficiency_retention, 4 MiB.
    out += [
        t(
            "固定: `pool_fraction` × `pool_efficiency_retention`、動かす: `efficiency_ssd`（4 MiB）"
        ),
        "",
    ]
    pool_fixes_2 = (0.30, 0.70, 0.80)
    retention_fixes = (0.5, 1.0)
    headers2 = [
        t("`pool_fraction` / `pool_efficiency_retention`"),
        *SENSITIVITY_PATTERNS,
    ]
    rows2: list[list[str]] = []
    for pool in pool_fixes_2:
        for retention in retention_fixes:
            row = [f"{_fmt(pool)} / {_fmt(retention)}"]
            for pattern_key in SENSITIVITY_PATTERNS:
                row.append(
                    _two_dim_cell(
                        pattern_key,
                        4096,
                        "efficiency_ssd",
                        {"pool_fraction": pool, "pool_efficiency_retention": retention},
                        counter,
                    )
                )
            rows2.append(row)
    out += table(headers2, rows2)
    out += [""]
    return out


def _two_dim_cell(
    pattern_key: str,
    kib: int,
    moving_key: str,
    fixed: dict[str, object],
    counter: _EvalCounter,
) -> str:
    """x* of `moving_key` with the `fixed` keys held, in one cell. "なし" when no sign change."""
    domain = SEARCH_DOMAINS[moving_key]
    axis = str(domain["axis"])
    lo = float(domain["lo"])
    hi = float(domain["hi"])

    def d_at(x: float) -> float:
        counter.bump()
        over = dict(fixed)
        over[moving_key] = x
        cell = _sens_cell(pattern_key, kib, Assumptions(**over))
        fsx, files = _subtotals(cell)
        return files - fsx

    step = (hi - lo) / _BISECT_N
    points = [lo + step * i for i in range(_BISECT_N + 1)]
    sigmas = [(x, _sigma(d_at(x))) for x in points]
    for (a, sa), (b, sb) in pairwise(sigmas):
        if sa == sb:
            continue
        lo_a, hi_b = a, b
        for _ in range(_BISECT_MAX_ITERS):
            if hi_b - lo_a <= _BISECT_TOL * max(1.0, abs(hi_b)):
                break
            m = _midpoint(lo_a, hi_b, axis)
            if _sigma(d_at(m)) == sa:
                lo_a = m
            else:
                hi_b = m
        return f"{_midpoint(lo_a, hi_b, axis):.3g}"
    return t("なし")


def _sens_scenarios() -> list[str]:
    """#### 複数の前提を同時に動かしたシナリオ: J0-J4 with per-size tables and J1/J3 decomposition."""
    _check_scenario_directions()
    out = [
        t("#### 複数の前提を同時に動かしたシナリオ"),
        "",
        t(
            "複数の前提を同時に動かした結果である。名前は動かす方向（その側の小計が下がる / 上がる）で付け、"
            "「有利」「不利」は使わない。J1〜J4 は 3・3・2・2 前提で、完全には揃わない。"
            "基準のアクティブ割合が上限の 100% で S3 Files の小計を上げる余地がなく、上げる側に置ける前提が"
            "`metadata_multiplier`・`first_read_stream_billing` に限られること、"
            "および向きの定まらない `first_read_mode=none` を J3 から外したことによる。"
            "同時に動かした値の組は予測でも推奨でもなく、向きが変わりうることを示す例である。"
        ),
        "",
    ]
    for kib in SENSITIVITY_SIZES_KIB:
        out += _scenario_table(kib)
    out += [
        t(
            "J1 のような組み合わせが実在の構成として成立するか（pool 80% で SSD の最小値に当たる場合など）は"
            "確認していない。"
        ),
        "",
    ]
    return out


def _scenario_table(kib: int) -> list[str]:
    headers = [t("シナリオ"), *SENSITIVITY_PATTERNS, t("向きが基準と異なるパターン")]
    rows: list[list[str]] = []
    for scenario_id in ("J0", "J1", "J2", "J3", "J4"):
        n = SCENARIO_DEFS[scenario_id]["n"]
        label = t("{id}（{n} 前提）", id=scenario_id, n=n) if n else scenario_id
        assumptions = _scenario_assumptions(scenario_id, kib)
        rows.append(
            [
                label,
                *[
                    _sens_cell_subtotals(p, kib, assumptions)
                    for p in SENSITIVITY_PATTERNS
                ],
                _scenario_direction_differs(assumptions, kib),
            ]
        )
        # Decomposition rows for J1 (3 premises) and J3 (2 premises).
        if scenario_id in ("J1", "J3"):
            for key in SCENARIO_DEFS[scenario_id]["overrides"]:
                reverted = _scenario_assumptions(scenario_id, kib, drop=key)
                rows.append(
                    [
                        t("{id} − {key}", id=scenario_id, key=key),
                        *[
                            _sens_cell_subtotals(p, kib, reverted)
                            for p in SENSITIVITY_PATTERNS
                        ],
                        _scenario_direction_differs(reverted, kib),
                    ]
                )
    return [
        t("オブジェクト {size} の場合", size=_size_label(kib)),
        "",
        *table(headers, rows),
        "",
    ]


def _scenario_direction_differs(assumptions: Assumptions, kib: int) -> str:
    differing: list[str] = []
    for pattern_key in SENSITIVITY_PATTERNS:
        base_cell = _sens_cell(pattern_key, kib, None)
        over_cell = _sens_cell(pattern_key, kib, assumptions)
        if _out_of_model(over_cell):
            continue
        if _low_side(*_subtotals(over_cell)) != _low_side(*_subtotals(base_cell)):
            differing.append(pattern_key)
    return t("・").join(differing) if differing else "—"


def _sens_not_included() -> list[str]:
    """#### 算入していない費目: the retention note at the top, then the items table."""
    out = [
        t("#### 算入していない費目"),
        "",
        t(
            "非現行バージョンの保持（S3 Files 側）は `--assume noncurrent_version_gib=GiB` で入力でき、"
            "S3 Standard の増分として小計に算入する（既定 0）。スナップショットの保持（FSx for ONTAP 側）は "
            "`--assume snapshot_gib=GiB` で入力を受けるが、どの層に置かれ、どう課金されるかが公式文面で揃わず、"
            "式には算入しない（既定 0、open 未確認）。どちらも保持日数から容量を導く式は未測定なので、容量を直接与える。"
        ),
        "",
        t(
            "数値は書かない。「根拠の確からしさ」は documented / verified / hypothesis / open の 4 語で付ける。"
        ),
        "",
    ]
    headers = [t("費目"), t("向き"), t("根拠"), t("根拠の確からしさ"), t("状態")]
    rows = [
        [
            t("スナップショットの保持（FSx for ONTAP 側）"),
            t("FSx for ONTAP の小計が上がる見込み"),
            t("保持分がどの層に置かれ、どう課金されるかで公式文面が揃わない"),
            t("open（未確認。方向も未確認）"),
            t("入力あり（snapshot_gib）、式に算入しない"),
        ],
        [
            t("pool 配置分のメタデータ用 SSD"),
            t("FSx for ONTAP の小計が上がる"),
            t(
                "公式の文面「ファイルのメタデータは常に SSD 層に残る」。目安は 1 点（サイジングブログ）"
            ),
            t(
                "documented（公式のボリューム容量ページ、サイジングブログ）。基準単位は open"
            ),
            t("未算入（PR-A2 の判断待ち）"),
        ],
        [
            t("SSD IOPS の追加、バックアップ、スナップショット予約"),
            t("FSx for ONTAP の小計が上がる"),
            t("単価と課金の仕組みをこの設計では公式文書で読んでいない"),
            t("open"),
            t("未算入"),
        ],
        [
            t("pool への書き込みリクエスト"),
            t("FSx for ONTAP の小計が上がる"),
            t("モデルに単価が定義済みで、式に使っていない（コードで確認）"),
            t("open（コードの事実は verified）"),
            t("未算入"),
        ],
        [
            t("pool 読み取りの操作数"),
            t("FSx for ONTAP の小計"),
            t("数え方が文書内で 3 通りあり、未確認"),
            t("open"),
            t("小計に算入しているが未確認"),
        ],
        [
            t("S3 Access Points 経由の GET"),
            t("FSx for ONTAP の小計が上がる"),
            t(
                "モデルは経由の PUT だけを足す（コードで確認）。GET の課金は単価と経路に依存"
            ),
            t("open（コードの事実は verified、単価は未再取得）"),
            t("未算入"),
        ],
        [
            t("高性能ストレージ上のメタデータの保管"),
            t("S3 Files の小計が上がる"),
            t(
                "公式は、アクセスしたディレクトリのメタデータは期限切れにならないと書く。課金の基準が文書にない"
            ),
            t("documented（公式の計量ページ）。課金の基準は open"),
            t("未算入"),
        ],
    ]
    out += table(headers, rows)
    out += [""]
    return out


def _sens_procedure() -> list[str]:
    """#### 自分の値での試算手順: the reader's own-value commands and how to read them."""
    out = [
        t("#### 自分の値での試算手順"),
        "",
        t(
            "受け付ける前提の一覧は `--list-assumptions` で確認する。"
            "自分の環境の値は `--assume key=value` で与え、公開文書の値とは比べない。"
            "比べるのは、同じ前提を置いた 2 つの出力どうしである。"
            "小計は主要費目小計で、月額総額ではない。"
        ),
        "",
        "```bash",
        t("# 1. 受け付ける前提の一覧（キー、既定値、許容範囲、基準値の区分）"),
        "python3 tools/finops_model.py --list-assumptions",
        "",
        t(
            "# 2. 自分の環境の値で小計の表を出す（保存量 50 TiB、Multi-AZ、SSD 層の効率 65%、pool 70%）"
        ),
        "python3 tools/finops_model.py --baseline-table \\",
        "  --assume stored_tib=50 --assume deployment=MULTI_AZ_1 \\",
        "  --assume efficiency_ssd=0.65 --assume pool_fraction=0.70",
        "",
        t(
            "# 3. 内訳まで JSON で出し、英語のラベルで保存する（アクティブ割合を測った値に置き換えた例）"
        ),
        "python3 tools/finops_model.py --baseline-json --lang en --assume active_fraction=0.10 > my-run.json",
        "```",
        "",
        t("値はコマンドの書式の例で、勧める値でも結果の予測でもない。"),
        "",
    ]
    return out


def _assumption_axes() -> dict[str, object]:
    """What a figure needs to draw one axis per assumption: the effective baseline, the search range,
    the scale, and which subtotal the key moves at each of P4's two sizes.

    Additive to `sensitivity_json` (schema_version stays 1); derived from `SWEEPS` (13 keys),
    `SEARCH_DOMAINS` and `ASSUMPTION_SPECS`, so nothing here is typed a second time.
    `moves_p4` is evaluated for pattern P4 only, one size at a time, by `_moving_flags`; the
    document's "小計が動く側" column is the union of the two sizes. `null` means the key was not tried
    at that size. The upper search bound `domain_hi` is the definition; whether a cell's right end was
    cut to the applicable range is read from that cell's `break_even` `hi`, not stored per key.
    """
    base_cell = _sens_cell("P4", SENSITIVITY_SIZES_KIB[0], None)
    axes: dict[str, object] = {}
    for key in SWEEPS:
        moves = {
            str(kib): _moving_word(_moving_flags(key, kib))
            for kib in SENSITIVITY_SIZES_KIB
        }
        if key in SEARCH_DOMAINS:
            domain = SEARCH_DOMAINS[key]
            if key == "active_fraction":
                # "auto" in the registry; the effective value is the retention-window formula.
                baseline = min(
                    1.0,
                    base_cell.s3files_expiration_days
                    / (base_cell.retention_months * 30.0),
                )
            else:
                baseline = float(ASSUMPTION_SPECS[key].baseline())
            axes[key] = {
                "baseline": baseline,
                "lo": float(domain["lo"]),
                "domain_hi": float(domain["hi"]),
                "scale": str(domain["axis"]),
                "zero_probe": bool(domain.get("zero", False)),
                "moves_p4": moves,
            }
        else:
            baseline = ASSUMPTION_SPECS[key].baseline()
            axes[key] = {
                "baseline": float(baseline)
                if isinstance(baseline, (int, float))
                else baseline,
                "scale": "enum" if key in ENUM_SWEEP_KEYS else "discrete",
                "moves_p4": moves,
            }
    return axes


def sensitivity_json(lang: str = "ja") -> dict[str, object]:
    """The sensitivity section as plain data, so a figure (PR-C) reads it instead of retyping numbers.

    The render functions and this structure are checked for agreement by a test (the table values
    equal the JSON values). `schema_version: 1`, same shape convention as `--baseline-json`.
    """

    def build() -> dict[str, object]:
        counter = _EvalCounter()
        one_at_a_time: dict[str, list[dict[str, object]]] = {}
        for kib in SENSITIVITY_SIZES_KIB:
            size_rows: list[dict[str, object]] = []
            for key, points in SWEEPS.items():
                for point in points:
                    if kib not in point.sizes:
                        continue
                    cells = {}
                    for pattern_key in SENSITIVITY_PATTERNS:
                        cell = _sens_cell(
                            pattern_key, kib, Assumptions(**{key: point.value})
                        )
                        fsx, files = _subtotals(cell)
                        cells[pattern_key] = {
                            "fsx_s3ap_usd": fsx,
                            "s3_files_usd": files,
                            "out_of_model_range": _out_of_model(cell),
                        }
                    size_rows.append(
                        {
                            "key": key,
                            "value": point.value,
                            "basis": point.basis,
                            "cells": cells,
                        }
                    )
            one_at_a_time[str(kib)] = size_rows
        breakeven: dict[str, list[dict[str, object]]] = {}
        for key in BREAKEVEN_NUMERIC_KEYS:
            entries: list[dict[str, object]] = []
            for kib in SENSITIVITY_SIZES_KIB:
                if key == "active_fraction" and kib == 4096:
                    continue
                for pattern_key in SENSITIVITY_PATTERNS:
                    results, hi = _bisect_breakevens(pattern_key, kib, key, counter)
                    entries.append(
                        {
                            "pattern": pattern_key,
                            "size_kib": kib,
                            "hi": hi,
                            "break_evens": [
                                {
                                    "x_star": be.x_star,
                                    "low_below": be.low_below,
                                    "low_above": be.low_above,
                                    "step_change": be.step_change,
                                    "sourced_relation": be.sourced_relation,
                                }
                                for be in results
                            ],
                        }
                    )
            breakeven[key] = entries
        scenarios: dict[str, list[dict[str, object]]] = {}
        for kib in SENSITIVITY_SIZES_KIB:
            rows: list[dict[str, object]] = []
            for scenario_id in ("J0", "J1", "J2", "J3", "J4"):
                assumptions = _scenario_assumptions(scenario_id, kib)
                cells = {}
                for pattern_key in SENSITIVITY_PATTERNS:
                    cell = _sens_cell(pattern_key, kib, assumptions)
                    fsx, files = _subtotals(cell)
                    cells[pattern_key] = {
                        "fsx_s3ap_usd": fsx,
                        "s3_files_usd": files,
                        "out_of_model_range": _out_of_model(cell),
                    }
                rows.append({"id": scenario_id, "cells": cells})
            scenarios[str(kib)] = rows
        return {
            "schema_version": 1,
            "generated_by": "tools/finops_model.py --sensitivity-json",
            "patterns": list(SENSITIVITY_PATTERNS),
            "sizes_kib": list(SENSITIVITY_SIZES_KIB),
            "one_at_a_time": one_at_a_time,
            "break_even": breakeven,
            "scenarios": scenarios,
            "sourced_ranges": {
                key: sourced_range(key) for key in BREAKEVEN_NUMERIC_KEYS
            },
            "assumption_axes": _assumption_axes(),
        }

    return _in_language(lang, build)


def render_sensitivity() -> list[str]:
    """The baseline-assumptions-and-sensitivity section (PR-B).

    One `###` with eight `####` subsections, built from the model. Every subtotal shown is recomputed
    from `baseline_cells` under an `Assumptions` override, so the table and the model cannot diverge.
    The direction-bearing scenario names are checked against the data at render time (ValueError on a
    mismatch), so a name that stops matching the prices stops the render rather than lingering.
    """
    counter = _EvalCounter()
    out: list[str] = []
    out += _sens_intro()
    out += _sens_assumption_list()
    out += _sens_one_at_a_time()
    out += _sens_breakeven(counter)
    out += _sens_two_assumptions(counter)
    out += _sens_scenarios()
    out += _sens_not_included()
    out += _sens_procedure()
    return out


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
    out += render_sensitivity()
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


def _check_flag_combinations(parser: argparse.ArgumentParser, args) -> None:
    """Enforce the mode-flag and --assume/--lang combination rules.

    The three new mode flags (--baseline-table, --list-assumptions, and in PR-B --sensitivity-json)
    cannot be combined with any other mode flag. --assume applies only to --baseline-json and
    --baseline-table. --lang applies only to the three label-bearing modes. Every violation is a
    `parser.error`, which exits 2, so the shell sees usage errors and value errors alike as 2.
    """
    # The existing mode flags, kept as-is.
    existing_modes = {
        "--write": args.write,
        "--check": args.check,
        "--show-prices": args.show_prices,
        "--translation-gaps": args.translation_gaps,
        "--baseline-json": args.baseline_json,
    }
    new_modes = {
        "--baseline-table": args.baseline_table,
        "--list-assumptions": args.list_assumptions,
        "--sensitivity-json": args.sensitivity_json,
    }
    active_existing = [name for name, on in existing_modes.items() if on]
    active_new = [name for name, on in new_modes.items() if on]

    # A new mode cannot be combined with any other mode (new or existing).
    if active_new and (active_existing or len(active_new) > 1):
        others = sorted(set(active_existing + active_new) - {active_new[0]})
        parser.error(f"{active_new[0]} cannot be combined with {', '.join(others)}")

    # The existing --baseline-json exclusivity is preserved unchanged.
    if args.baseline_json and (
        args.write or args.check or args.show_prices or args.translation_gaps
    ):
        parser.error(
            "--baseline-json cannot be combined with --write, --check, "
            "--show-prices or --translation-gaps"
        )

    # --assume: only with --baseline-json or --baseline-table.
    if args.assume and not (args.baseline_json or args.baseline_table):
        parser.error("--assume applies only to --baseline-json or --baseline-table")

    # --lang: only with the label-bearing modes.
    if args.lang and not (
        args.baseline_json
        or args.baseline_table
        or args.list_assumptions
        or args.sensitivity_json
    ):
        parser.error(
            "--lang applies only to --baseline-json, --baseline-table, "
            "--list-assumptions or --sensitivity-json"
        )


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
        "--baseline-table",
        action="store_true",
        help="print the baseline grid's FSx for ONTAP and S3 Files subtotals as a Markdown table",
    )
    parser.add_argument(
        "--list-assumptions",
        action="store_true",
        help="print the registry of reader-settable assumptions",
    )
    parser.add_argument(
        "--sensitivity-json",
        action="store_true",
        help="print the sensitivity section's structure as JSON (figures read this instead of retyping numbers)",
    )
    parser.add_argument(
        "--assume",
        action="append",
        default=[],
        metavar="key=value",
        help="override a baseline assumption (repeatable); with --baseline-json or --baseline-table",
    )
    parser.add_argument(
        "--lang",
        choices=LANGS,
        default=None,
        help="language of the labels in --baseline-json / --baseline-table / --list-assumptions "
        "and assumption-validation errors (default: ja)",
    )
    args = parser.parse_args()

    _check_flag_combinations(parser, args)
    lang = args.lang or "ja"

    if args.list_assumptions:
        print(_render_assumption_list(lang), end="")
        return 0

    if args.sensitivity_json:
        print(json.dumps(sensitivity_json(lang), ensure_ascii=False, indent=2))
        return 0

    if args.baseline_json or args.baseline_table:
        try:
            assumptions = parse_assumptions(args.assume, lang) if args.assume else None
            if assumptions is not None:
                validate_assumptions(assumptions, lang)
        except AssumptionError as error:
            print(f"finops-model: {error}", file=sys.stderr)
            return 2
        if args.baseline_json:
            print(
                json.dumps(
                    baseline_json(lang, assumptions), ensure_ascii=False, indent=2
                )
            )
        else:
            print(baseline_table(lang, assumptions), end="")
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
