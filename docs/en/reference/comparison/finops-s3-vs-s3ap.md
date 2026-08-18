# FinOps — the cost structure of a standard S3 bucket and an FSx for ONTAP S3 Access Point

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/comparison/finops-s3-vs-s3ap.md) | [English](finops-s3-vs-s3ap.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

Cost becomes a problem in two typical places.

One is the **read side**. Data placed in S3 is read over the S3 API by consumers outside AWS. Read
the same file many times and data transfer is charged on the bytes that left the Region, multiplying
by the number of reads. GET requests scale with the count too.
This is what the architecture is trying to solve.

The other is the **collect side**, where making the entry point an S3 bucket or an FSx for ONTAP S3
AP changes how request and storage rates show up.

This document breaks both down into billing dimensions and estimates several configurations. The
read side comes first because that is where the larger figure tends to be.

This is not a table for picking the cheaper option. What a FinOps decision needs is which dimension
the cost lands on, what that dimension imposes on the surrounding workloads, and what becomes fixed
once the configuration is chosen.

How the numbers are handled, stated up front. **Unit prices are real values read from the AWS Price
List API**, with the Region and the date applicability starts. **Usage figures are assumptions**, and
the monthly totals derived from them are estimates. The two are never mixed into one table, so that
an estimate is not mistaken for a measurement.

## The conclusion

| Situation | The choice that suits it on cost | Why |
|---|---|---|
| The same data is read repeatedly from outside AWS | FSx for ONTAP + FlexCache | Transfer is charged on bytes read. A cache carries the working set once |
| Read from outside AWS, but each piece of data only once | Read S3 directly | The same bytes move, and there is no reason to carry a file system floor |
| The consumers can move into AWS | Consider moving them first | Transfer within a Region is free, and that is larger than anything the storage layer moves |
| The consumers are Linux in AWS and need POSIX with S3 as the source of truth | S3 Files | With large objects the difference from reading directly is small. NFSv3 and SMB are out of scope |
| The consumers speak the S3 API and no file protocol is needed | An S3 bucket alone | There is no reason to carry the FSx for ONTAP floor |
| Small objects written often | FSx for ONTAP S3 AP | The request rate becomes the dominant term and the gap is wide. The threshold is calculated under [estimates](#estimates) |
| Large objects handled infrequently, and the consumers require NFS or SMB | The cost difference is small | The reason to choose is not cost but whether you want to run a sync job |
| FSx for ONTAP is already there | FSx for ONTAP S3 AP | The comparison becomes an increment. The floor is carried by the existing workload |
| A new FSx for ONTAP file system is required, and both the data volume and the requirements are small | An S3 bucket alone, or revisit the requirement | You need a reason that recovers the monthly floor |
| Mostly long-term retention, rarely read | The S3 Glacier storage classes | FSx for ONTAP has no equivalent retrieval-charge model |
| What the distribution side needs is the working set, not all of the data | A FlexCache cache volume | The cache is sparse, so roughly a tenth of the origin in SSD is enough |
| The consumers are Linux compute in AWS and the mount helper can be installed | S3 Files | No FSx for ONTAP floor. Cheaper still with large objects |
| The consumers are equipment whose configuration cannot be changed, need SMB, or are outside AWS | FSx for ONTAP S3 AP + FlexCache | S3 Files targets Linux on EC2 / Lambda / EKS / ECS and does not offer SMB |
| All of the data has to be local at the distribution site at all times | A full copy (SnapMirror or similar) | A cache cannot be tiered, so holding everything in one costs more than a copy |

Two axes narrow the field before cost does: the protocols the consumers can speak, and the write
path.

- [Supported protocols and versions side by side](#supported-protocols-and-versions-side-by-side) — whether there is equipment fixed on NFSv3, or a stage of the pipeline that uses SMB, narrows the options first
- [Writing on the distribution side](#writing-on-the-distribution-side--the-two-flexcache-modes) — a cache is writable, and freshness and latency come out differently under the default write-around and asynchronous write-back

## How the billing dimensions correspond

"Put an object and read it" is the same sentence on both sides, but the axes charged for are not the
same. An item one side has and the other does not is a design constraint as it stands.

| Dimension | S3 bucket | FSx for ONTAP + S3 AP |
|---|---|---|
| Storage | GB-Mo per storage class, banded down by volume | GB-Mo of SSD and GB-Mo of capacity pool |
| Storage floor | None | 1 TiB of SSD |
| Bandwidth | No provisioning needed in advance | Throughput capacity chosen in advance, in MBps-Mo |
| IOPS | Not a billed item | 3 IOPS per GiB of SSD included. Anything beyond that in IOPS-Mo |
| Requests | Tier 1 / Tier 2, priced differently per storage class | Tier 1 / Tier 2 through an S3 AP (their own rates), plus capacity pool reads and writes |
| Retrieval | Infrequent-access tiers and the Glacier classes charge per GB retrieved | No such item. The capacity pool is charged per request |
| Minimum storage duration | 30 days for the infrequent-access tiers, longer for the Glacier classes | None |
| Minimum billable object size | 128 KB for Standard-IA | None |
| Tiering | Lifecycle transitions carry a request charge | Automatic tiering. The transition itself is not a billed item |
| Backup | Versioning and replication are charged as capacity | GB-Mo of backup storage |
| Data transfer | Standard S3 data transfer rates | Traffic through an S3 AP is treated as standard S3 data transfer too |
| Compliance retention | Object Lock (no additional charge) | SnapLock (a separate licence item) |
| Software licence | None | ONTAP's data management features need no additional licence. SnapLock is separate |
| Reading over a file protocol | Adding S3 Files puts high-performance storage plus read and write charges on top of the authoritative bucket | A FlexCache cache volume. It cannot be tiered, so all of it is SSD |

## Three structural differences

### 1. Whether there is a floor

An S3 bucket charges for what is used and has no floor. The smallest FSx for ONTAP file system is
1 TiB of SSD and one throughput capacity step, billed every month whatever the usage.
Building a new one needs a reason that recovers that floor. Where one already exists, this item
drops out of the comparison.

### 2. Requests are not priced the same way on both sides

The same `PutObject` carries a different rate depending on whether it lands on an S3 bucket or an
FSx for ONTAP volume. The FSx for ONTAP side is cheaper: by more than 4x on PUT and more than 12x on
GET.

### 3. Storage rates are asymmetric too, and the capacity pool reverses them

SSD is more expensive than S3 Standard. The capacity pool is cheaper than S3 Standard. Which way the
total leans depends on the tiering ratio and on storage efficiency, so "FSx for ONTAP storage is
expensive" and "it is cheap" are both unsupportable as blanket statements.

## What constrains dropping an S3 storage class

Dropping a tier to cut the storage rate gives the saving back on another dimension. In a collection
workload writing small objects often, that return tends to bite.

| Constraint | What it is | Source |
|---|---|---|
| Minimum billable object size | 128 KB for Standard-IA. A 6 KB object is billed as 128 KB | [S3 FAQ](https://aws.amazon.com/s3/faqs/) |
| Minimum storage duration | 30 days for Standard-IA and One Zone-IA, 90 days for Glacier Flexible Retrieval, 180 days for Glacier Deep Archive | [Lifecycle considerations](https://docs.aws.amazon.com/AmazonS3/latest/userguide/lifecycle-expire-general-considerations.html) |
| Transition requests | Moving data by PUT / COPY / lifecycle carries a request charge | [S3 pricing](https://aws.amazon.com/s3/pricing/) |
| Retrieval charges | Standard-IA and the Glacier classes add a per-GB retrieval charge | Price List API (the unit price table below) |
| Higher request rates | Dropping a tier raises the Tier 1 and Tier 2 rates | Price List API (the unit price table below) |
| Excluded from Intelligent-Tiering | Objects under 128 KB are not auto-tiered and continue to be charged at the frequent-access rate | [S3 pricing](https://aws.amazon.com/s3/pricing/) |

The last row bears directly on small-object collection. Putting telemetry averaging 64 KiB into
Intelligent-Tiering produces no tiering saving at all. Objects under 128 KB keep being charged in the
frequent-access tier.

## What constrains the FSx for ONTAP configuration

| Constraint | What it is |
|---|---|
| The deployment type cannot be changed | Generation and AZ configuration are fixed at creation. Migrating means restoring from backup, SnapMirror, or DataSync |
| Multi-AZ doubles the SSD rate | Decide on whether tolerance of an AZ failure is a requirement. Transfer for cross-AZ replication is included in the throughput charge |
| Cross-AZ access on Single-AZ | Reading or writing from outside the file system's preferred AZ is $0.01/GB in each direction. It does not arise on Multi-AZ file systems created on or after 2022-02-23 |
| Throughput rises in steps | Chosen from a list, not a continuous value. One step up is one step up in cost |
| The second generation starts at 384 MBps | Three steps above the first generation's 128 MBps. With no use for the ceilings (512 TiB of SSD, 200,000 IOPS, up to 12 HA pairs on Single-AZ), that is headroom paid for and left idle |
| A cache volume cannot be tiered | A FabricPool origin can be cached, but the cache volume itself is not tiered ([supported and unsupported features](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html)). All of the distribution side sits on SSD |
| Cache sizing decides the cost | The working set is enough, not all of the origin. NetApp's sizing guidance is at least 10%, which is also the default at creation ([sizing guidance](https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html)) |

Sources are [availability and deployment options](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html)
and [FSx for ONTAP pricing](https://aws.amazon.com/fsx/netapp-ontap/pricing/).

## How storage efficiency is handled

The figures in the estimates move a great deal with the storage efficiency assumption. Where the
numbers come from, first.

AWS publishes typical savings per workload ([managing storage capacity](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-storage-capacity.html)).

| Workload | Compression only | Deduplication only | Compression + deduplication |
|---|---|---|---|
| General-purpose file sharing | 50% | 30% | 65% |
| Virtual servers and desktops | 55% | 70% | 70% |
| Databases | 65-70% | 0% | 65-70% |
| Engineering data | 55% | 30% | 75% |
| Seismic data | 40% | 3% | 40% |

Each scenario's SSD-tier efficiency is the closest workload from this table. Which one was applied,
and why, is stated in each scenario's assumptions.

### Tiering changes the premise

**Background efficiency processing does not run on tiered data.** Only reductions applied while the
block was on SSD carry over to the pool, and a block tiered before efficiency ran stays in the pool
with no reduction at all.

| Source | What it says |
|---|---|
| [FSx for ONTAP documentation](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/manage-vol-SE.html) | Background efficiency is not run on data after it has been tiered to the capacity pool. Reductions from its time on SSD do carry over |
| [NetApp KB](https://kb.netapp.com/Advice_and_Troubleshooting/Data_Storage_Software/ONTAP_OS/Does_ONTAP_apply_efficiencies_to_blocks_that_are_tiered-out_to_Fabricpool%3F) | Blocks tiered before efficiency was applied remain in the capacity tier without it |

The capacity pool tier therefore cannot be given the same figure as the SSD tier. The estimates below
assume the pool tier is **50% of the SSD tier**. That is an assumption, not a sourced value. With a
short cooling period, or an `All` policy, it tends towards 0%. At `AUTO` with the 31-day default there
is room for efficiency to run before tiering.

Treat an assumption above 40% with care in an environment where tiering is enabled. An optimistic
premise works in the direction of making this architecture look cheaper than it is (the options that
use S3 for storage do not benefit from ONTAP efficiency, so their figures do not move). How much it
matters is visible in the sensitivity table under [estimates](#estimates).

## Estimates

The following is generated by `tools/finops_model.py`. Regenerate it with `make finops-write`
whenever a unit price changes. `make finops` detects a mismatch between the generated block and the
current model, and is part of the commit gate.

<!-- finops-model:begin -->

<!-- Generated. Do not edit. Regenerate with tools/finops_model.py -->

### Unit prices

Asia Pacific (Tokyo) (`ap-northeast-1`), on demand, excluding tax. Read from the AWS Price List API on 2026-08-09; `effective` is the date the API returned as the start of applicability.

**These are the values as read on that date.** Check the current ones against [S3 pricing](https://aws.amazon.com/s3/pricing/) and [FSx for ONTAP pricing](https://aws.amazon.com/fsx/netapp-ontap/pricing/), and regenerate with `make finops-write` when updating them (`make finops` detects the drift).

| Service | Billed item | Unit price | effective |
|---|---|---|---|
| S3 | S3 Standard storage (first 50 TiB) | $0.025 / GB-Mo | 2026-08-01 |
| S3 | S3 Standard-IA storage | $0.0138 / GB-Mo | 2026-08-01 |
| S3 | S3 One Zone-IA storage | $0.011 / GB-Mo | 2026-08-01 |
| S3 | S3 Glacier Instant Retrieval storage | $0.005 / GB-Mo | 2026-08-01 |
| S3 | S3 Intelligent-Tiering Frequent Access tier | $0.025 / GB-Mo | 2026-08-01 |
| S3 | S3 Intelligent-Tiering Infrequent Access tier | $0.0138 / GB-Mo | 2026-08-01 |
| S3 | S3 Intelligent-Tiering Archive Instant Access tier | $0.005 / GB-Mo | 2026-08-01 |
| S3 | S3 standard PUT / COPY / POST / LIST | $0.0047 / 1,000 | 2026-08-01 |
| S3 | S3 standard GET and all other requests | $0.00037 / 1,000 | 2026-08-01 |
| S3 | S3 Standard-IA PUT / COPY / POST / LIST | $0.01 / 1,000 | 2026-08-01 |
| S3 | S3 Standard-IA GET and all other requests | $0.001 / 1,000 | 2026-08-01 |
| S3 | S3 Standard-IA retrieval | $0.01 / GB | 2026-08-01 |
| S3 | S3 Glacier Instant Retrieval retrieval | $0.03 / GB | 2026-08-01 |
| S3 | PUT / COPY / POST / LIST through an S3 AP (to FSx for ONTAP) | $0.00108 / 1,000 | 2026-08-01 |
| S3 | GET and all other requests through an S3 AP (to FSx for ONTAP) | $0.000029 / 1,000 | 2026-08-01 |
| FSx for ONTAP | SSD storage, Single-AZ (first / second generation) | $0.15 / GB-Mo | 2026-07-01 |
| FSx for ONTAP | SSD storage, Multi-AZ (first / second generation) | $0.3 / GB-Mo | 2026-07-01 |
| FSx for ONTAP | Throughput capacity, Single-AZ first generation | $0.906 / MBps-Mo | 2026-07-01 |
| FSx for ONTAP | Throughput capacity, Single-AZ second generation | $2.013 / MBps-Mo | 2026-07-01 |
| FSx for ONTAP | Throughput capacity, Multi-AZ first generation | $1.511 / MBps-Mo | 2026-07-01 |
| FSx for ONTAP | Throughput capacity, Multi-AZ second generation | $3.148 / MBps-Mo | 2026-07-01 |
| FSx for ONTAP | Additional SSD IOPS, Single-AZ | $0.0204 / IOPS-Mo | 2026-07-01 |
| FSx for ONTAP | Additional SSD IOPS, Multi-AZ | $0.0408 / IOPS-Mo | 2026-07-01 |
| FSx for ONTAP | Capacity pool storage, Single-AZ | $0.0238 / GB-Mo | 2026-07-01 |
| FSx for ONTAP | Capacity pool storage, Multi-AZ | $0.0476 / GB-Mo | 2026-07-01 |
| FSx for ONTAP | Capacity pool read requests | $0.00037 / 1,000 | 2026-07-01 |
| FSx for ONTAP | Capacity pool write requests | $0.0047 / 1,000 | 2026-07-01 |
| FSx for ONTAP | Backup storage | $0.05 / GB-Mo | 2026-07-01 |
| S3 Files | S3 Files high-performance storage (active data only) | $0.36 / GB-Mo | 2026-08-01 |
| S3 Files | S3 Files data read | $0.04 / GB | 2026-08-01 |
| S3 Files | S3 Files data write | $0.07 / GB | 2026-08-01 |
| Data transfer | Data transfer out to the internet (first 10 TB) | $0.114 / GB | 2026-06-01 |
| Data transfer | Data transfer over Direct Connect (Tokyo; port charges separate) | $0.041 / GB | 2026-07-01 |
| DataSync | DataSync transfer (Basic mode) | $0.0125 / GB | 2025-09-01 |
| DataSync | DataSync transfer (Enhanced mode) | $0.015 / GB | 2025-09-01 |
| DataSync | DataSync task execution (Enhanced mode) | $0.55 / task execution | 2025-09-01 |

S3 Standard storage is priced in volume bands (first 50 TiB $0.025, next 450 TB $0.024, beyond 500 TB $0.023 per GB-Mo). The estimates below follow those bands.

### Requests are not priced the same way on both sides

The same API operation carries a different unit price depending on whether it lands on an S3 bucket or on an FSx for ONTAP volume.

| Operation | To an S3 bucket | Through an S3 AP (to FSx for ONTAP) | Ratio, bucket to S3 AP |
|---|---|---|---|
| PUT / COPY / POST / LIST | $0.0047 / 1,000 | $0.00108 / 1,000 | 4.35x |
| GET and all other requests | $0.00037 / 1,000 | $0.000029 / 1,000 | 12.76x |

Moving to an infrequent-access tier widens the gap rather than closing it. A PUT to S3 Standard-IA is $0.01 / 1,000, which is 9.3x the S3 AP price. Dropping a tier to cut the storage rate gives the saving back on the request side of a write-heavy workload.

### The floor

An S3 bucket has no floor: store nothing and nothing is billed. The smallest FSx for ONTAP file system is 1 TiB of SSD and one throughput capacity step, and that much is billed every month whatever the usage.

| Deployment | API value | Minimum SSD | Minimum throughput | SSD portion | Throughput portion | Monthly floor |
|---|---|---|---|---|---|---|
| Single-AZ, first generation | `SINGLE_AZ_1` | 1,024 GiB | 128 MBps | $153.60 | $115.97 | **$269.57** |
| Multi-AZ, first generation | `MULTI_AZ_1` | 1,024 GiB | 128 MBps | $307.20 | $193.41 | **$500.61** |
| Single-AZ, second generation | `SINGLE_AZ_2` | 1,024 GiB | 384 MBps | $153.60 | $772.99 | **$926.59** |
| Multi-AZ, second generation | `MULTI_AZ_2` | 1,024 GiB | 384 MBps | $307.20 | $1,208.83 | **$1,516.03** |

The second generation starts at 384 MBps, three steps above the first generation's 128 MBps. The reason to choose it is not the price per MBps but the ceilings: 512 TiB of SSD, 200,000 IOPS, and up to 12 HA pairs on Single-AZ ([generation comparison](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/high-availability-AZ.html)). Choosing it for a workload that has no use for those ceilings means paying for headroom that stays idle.

### Why object size decides this

Requests are billed by count, not by volume. Writing the same 1 GiB in smaller objects takes more requests, and past a point the request charge overtakes the storage charge.

| Average object size | PUTs per GiB | PUT to a bucket, per GiB | PUT through an S3 AP, per GiB | Bucket PUT as a multiple of one month of S3 Standard storage |
|---|---|---|---|---|
| 8 KiB | 131,072 | $0.616 | $0.1416 | 24.6x |
| 32 KiB | 32,768 | $0.154 | $0.0354 | 6.2x |
| 64 KiB | 16,384 | $0.077 | $0.0177 | 3.1x |
| 128 KiB | 8,192 | $0.0385 | $0.00884736 | 1.5x |
| 256 KiB | 4,096 | $0.0193 | $0.00442368 | 0.8x |
| 1,024 KiB | 1,024 | $0.0048128 | $0.00110592 | 0.2x |
| 8,192 KiB | 128 | $0.0006016 | $0.00013824 | 0.0x |

Below an average object size of roughly 197 KiB, the PUT charge to an S3 bucket exceeds one month of S3 Standard storage for the same bytes. For a collection workload writing small objects often, the request price is the dominant term, not the storage price.

### Estimates by use case

Every figure below is an **estimate**, not a measurement. The unit prices are the table above; the usage figures are assumptions stated with each table.
Five values are the ones to replace with your own: monthly object count, average object size, retention period, read count, and storage efficiency.

#### Vehicle / IoT telemetry — small objects, written often

Industries this fits: Automotive, manufacturing, IoT

| Assumption | Value |
|---|---|
| Objects per month | 300,000,000 |
| Average object size | 64 KiB |
| Written per month | 18,311 GiB |
| Retention period (months) | 1 |
| Steady-state stored volume (logical) | 18,311 GiB |
| Reads per object | 2 |
| Assumed storage efficiency (SSD tier) | 50% — Mostly text and JSON, but with little duplicate content. AWS's published 50% for general-purpose file sharing with compression only is applied |
| Assumed storage efficiency (capacity pool tier) | 25% — background efficiency does not run on tiered data, so this is assumed to be 50% of the SSD-tier figure |
| Deployment | Single-AZ, first generation (`SINGLE_AZ_1`) |
| Average throughput required | 21.7 MB/s |
| Fraction tiered to the capacity pool | 0% |
| Throughput headroom | the smallest step that covers 5x the average requirement |
| SSD provisioning headroom | 20% above the post-efficiency figure |
| Retention in the S3 landing area (months) | 0.25 — assumed to be expired by a lifecycle rule once the sync has run |
| Do the consumers require a file protocol? | No |

- 300 million objects a month (10 million a day) arriving at 64 KiB each
- S3 alone is shown for reference, on the assumption that the consumers can speak the S3 API. If NFS or SMB is required, it is not an option

**S3 alone (consumers also speak the S3 API)**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard) | $457.76 |
| PUT requests | $1,410.00 |
| GET requests | $222.00 |
| **Total (monthly)** | **$2,089.76** |
| Per logical GiB | $0.1141 |

**S3 bucket + DataSync + FSx for ONTAP**

| Line item | Monthly |
|---|---|
| SSD storage (10,987 GiB) | $1,648.05 |
| Throughput capacity (128 MBps) | $115.97 |
| Storage (S3 Standard, landing area 4,578 GiB) | $114.44 |
| PUT requests (to an S3 bucket) | $1,410.00 |
| GET / LIST requests (read by the sync task) | $112.41 |
| DataSync transfer | $228.88 |
| **Total (monthly)** | **$3,629.75** |
| Per logical GiB | $0.1982 |

**FSx for ONTAP S3 AP (this architecture)**

| Line item | Monthly |
|---|---|
| SSD storage (10,987 GiB) | $1,648.05 |
| Throughput capacity (128 MBps) | $115.97 |
| PUT requests (through an S3 AP) | $324.00 |
| **Total (monthly)** | **$2,088.02** |
| Per logical GiB | $0.114 |

**S3 bucket + S3 Files**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard; the authoritative copy stays in the bucket) | $457.76 |
| PUT requests (to an S3 bucket) | $1,410.00 |
| S3 Files high-performance storage (100% active) | $6,591.80 |
| GET requests (the first read is streamed from the bucket) | $111.00 |
| S3 Files write (import onto high-performance storage) | $1,361.85 |
| S3 Files read (reads after import, plus metadata) | $823.97 |
| **Total (monthly)** | **$10,756.38** |
| Per logical GiB | $0.5874 |

This architecture is $1,541.73 (42%) a month cheaper than the one with a sync job in the middle. The largest term in the difference is "PUT requests (to an S3 bucket)", which accounts for 91% of it.

#### HiL test benches — distributing drive logs to the equipment

Industries this fits: Automotive (AV / ADAS)

| Assumption | Value |
|---|---|
| Objects per month | 20,000,000 |
| Average object size | 1,024 KiB |
| Written per month | 19,531 GiB |
| Retention period (months) | 2 |
| Steady-state stored volume (logical) | 39,062 GiB |
| Reads per object | 1.5 |
| Assumed storage efficiency (SSD tier) | 40% — Mostly sensor-derived binary. AWS's closest published figure, 40% for seismic data, is applied |
| Assumed storage efficiency (capacity pool tier) | 20% — background efficiency does not run on tiered data, so this is assumed to be 50% of the SSD-tier figure |
| Deployment | Single-AZ, first generation (`SINGLE_AZ_1`) |
| Average throughput required | 19.3 MB/s |
| Fraction tiered to the capacity pool | 30% |
| Throughput headroom | the smallest step that covers 5x the average requirement |
| SSD provisioning headroom | 20% above the post-efficiency figure |
| Retention in the S3 landing area (months) | 0.25 — assumed to be expired by a lifecycle rule once the sync has run |
| Do the consumers require a file protocol? | Yes |

- The test benches speak nothing but an NFS or SMB mount, so S3 alone does not meet the requirement
- 30% is assumed to be re-read rarely enough to tier to the capacity pool

**S3 alone (consumers also speak the S3 API)**: not costed, because it does not meet the requirement (the consumers require a file protocol).

**S3 bucket + DataSync + FSx for ONTAP**

| Line item | Monthly |
|---|---|
| SSD storage (19,688 GiB) | $2,953.20 |
| Throughput capacity (128 MBps) | $115.97 |
| Capacity pool storage (9,375 GiB) | $223.13 |
| Capacity pool read requests | $3.33 |
| Storage (S3 Standard, landing area 4,883 GiB) | $122.07 |
| PUT requests (to an S3 bucket) | $94.00 |
| GET / LIST requests (read by the sync task) | $7.49 |
| DataSync transfer | $244.14 |
| **Total (monthly)** | **$3,763.33** |
| Per logical GiB | $0.0963 |

**FSx for ONTAP S3 AP (this architecture)**

| Line item | Monthly |
|---|---|
| SSD storage (19,688 GiB) | $2,953.20 |
| Throughput capacity (128 MBps) | $115.97 |
| Capacity pool storage (9,375 GiB) | $223.13 |
| Capacity pool read requests | $3.33 |
| PUT requests (through an S3 AP) | $21.60 |
| **Total (monthly)** | **$3,317.22** |
| Per logical GiB | $0.0849 |

**S3 bucket + S3 Files**: not costed, because it does not meet the requirement (The test benches are physical equipment outside AWS whose configuration cannot be changed, so the mount helper cannot be installed).

This architecture is $446.10 (12%) a month cheaper than the one with a sync job in the middle. The largest term in the difference is "DataSync transfer", which accounts for 55% of it.

#### EDA / CAE — bursty reads, heavy metadata traffic

Industries this fits: Semiconductors, manufacturing

| Assumption | Value |
|---|---|
| Objects per month | 60,000,000 |
| Average object size | 256 KiB |
| Written per month | 14,648 GiB |
| Retention period (months) | 3 |
| Steady-state stored volume (logical) | 43,945 GiB |
| Reads per object | 4 |
| Assumed storage efficiency (SSD tier) | 75% — AWS's published 75% for engineering data (compression plus deduplication) is applied |
| Assumed storage efficiency (capacity pool tier) | 38% — background efficiency does not run on tiered data, so this is assumed to be 50% of the SSD-tier figure |
| Deployment | Single-AZ, second generation (`SINGLE_AZ_2`) |
| Average throughput required | 28.9 MB/s |
| Fraction tiered to the capacity pool | 40% |
| Throughput headroom | the smallest step that covers 5x the average requirement |
| SSD provisioning headroom | 20% above the post-efficiency figure |
| Retention in the S3 landing area (months) | 0.25 — assumed to be expired by a lifecycle rule once the sync has run |
| Do the consumers require a file protocol? | Yes |

- The toolchain requires POSIX semantics, so S3 alone does not meet the requirement
- The second generation is chosen for its ceilings (512 TiB of SSD, 200,000 IOPS), not for its unit price

**S3 alone (consumers also speak the S3 API)**: not costed, because it does not meet the requirement (the consumers require a file protocol).

**S3 bucket + DataSync + FSx for ONTAP**

| Line item | Monthly |
|---|---|
| SSD storage (7,911 GiB) | $1,186.65 |
| Throughput capacity (384 MBps) | $772.99 |
| Capacity pool storage (10,986 GiB) | $261.47 |
| Capacity pool read requests | $35.52 |
| Storage (S3 Standard, landing area 3,662 GiB) | $91.55 |
| PUT requests (to an S3 bucket) | $282.00 |
| GET / LIST requests (read by the sync task) | $22.48 |
| DataSync transfer | $183.11 |
| **Total (monthly)** | **$2,835.78** |
| Per logical GiB | $0.0645 |

**FSx for ONTAP S3 AP (this architecture)**

| Line item | Monthly |
|---|---|
| SSD storage (7,911 GiB) | $1,186.65 |
| Throughput capacity (384 MBps) | $772.99 |
| Capacity pool storage (10,986 GiB) | $261.47 |
| Capacity pool read requests | $35.52 |
| PUT requests (through an S3 AP) | $64.80 |
| **Total (monthly)** | **$2,321.44** |
| Per logical GiB | $0.0528 |

**S3 bucket + S3 Files**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard; the authoritative copy stays in the bucket) | $1,098.63 |
| PUT requests (to an S3 bucket) | $282.00 |
| GET requests (streamed straight from the bucket) | $88.80 |
| S3 Files write (metadata import) | $16.02 |
| S3 Files read (metadata) | $36.62 |
| **Total (monthly)** | **$1,522.08** |
| Per logical GiB | $0.0346 |

This architecture is $514.34 (18%) a month cheaper than the one with a sync job in the middle. The largest term in the difference is "PUT requests (to an S3 bucket)", which accounts for 55% of it.

#### Media / rendering — large objects, few requests

Industries this fits: Media, entertainment

| Assumption | Value |
|---|---|
| Objects per month | 50,000 |
| Average object size | 512,000 KiB |
| Written per month | 24,414 GiB |
| Retention period (months) | 3 |
| Steady-state stored volume (logical) | 73,242 GiB |
| Reads per object | 3 |
| Assumed storage efficiency (SSD tier) | 0% — Already-compressed material. Neither compression nor deduplication is assumed to save anything |
| Assumed storage efficiency (capacity pool tier) | 0% — background efficiency does not run on tiered data, so this is assumed to be 50% of the SSD-tier figure |
| Deployment | Single-AZ, first generation (`SINGLE_AZ_1`) |
| Average throughput required | 38.6 MB/s |
| Fraction tiered to the capacity pool | 80% |
| Throughput headroom | the smallest step that covers 5x the average requirement |
| SSD provisioning headroom | 20% above the post-efficiency figure |
| Retention in the S3 landing area (months) | 0.25 — assumed to be expired by a lifecycle rule once the sync has run |
| Do the consumers require a file protocol? | Yes |

- The render nodes mount over NFS, so S3 alone does not meet the requirement
- The request price difference barely matters here. Throughput and storage are what move the total

**S3 alone (consumers also speak the S3 API)**: not costed, because it does not meet the requirement (the consumers require a file protocol).

**S3 bucket + DataSync + FSx for ONTAP**

| Line item | Monthly |
|---|---|
| SSD storage (17,579 GiB) | $2,636.85 |
| Throughput capacity (256 MBps) | $231.94 |
| Capacity pool storage (58,594 GiB) | $1,394.53 |
| Capacity pool read requests | $0.04 |
| Storage (S3 Standard, landing area 6,104 GiB) | $152.59 |
| PUT requests (to an S3 bucket) | $0.23 |
| GET / LIST requests (read by the sync task) | $0.02 |
| DataSync transfer | $305.18 |
| **Total (monthly)** | **$4,721.38** |
| Per logical GiB | $0.0645 |

**FSx for ONTAP S3 AP (this architecture)**

| Line item | Monthly |
|---|---|
| SSD storage (17,579 GiB) | $2,636.85 |
| Throughput capacity (256 MBps) | $231.94 |
| Capacity pool storage (58,594 GiB) | $1,394.53 |
| Capacity pool read requests | $0.04 |
| PUT requests (through an S3 AP) | $0.05 |
| **Total (monthly)** | **$4,263.42** |
| Per logical GiB | $0.0582 |

**S3 bucket + S3 Files**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard; the authoritative copy stays in the bucket) | $1,809.01 |
| PUT requests (to an S3 bucket) | $0.23 |
| GET requests (streamed straight from the bucket) | $0.06 |
| S3 Files write (metadata import) | $0.01 |
| S3 Files read (metadata) | $0.02 |
| **Total (monthly)** | **$1,809.34** |
| Per logical GiB | $0.0247 |

This architecture is $457.96 (10%) a month cheaper than the one with a sync job in the middle. The largest term in the difference is "DataSync transfer", which accounts for 67% of it.

#### Genomics — sequencer output to an HPC cluster

Industries this fits: Life sciences, research

| Assumption | Value |
|---|---|
| Objects per month | 2,000,000 |
| Average object size | 8,192 KiB |
| Written per month | 15,625 GiB |
| Retention period (months) | 6 |
| Steady-state stored volume (logical) | 93,750 GiB |
| Reads per object | 2 |
| Assumed storage efficiency (SSD tier) | 40% — FASTQ and BAM are partly compressed already. AWS's closest published figure, 40% for seismic data, is applied |
| Assumed storage efficiency (capacity pool tier) | 20% — background efficiency does not run on tiered data, so this is assumed to be 50% of the SSD-tier figure |
| Deployment | Single-AZ, first generation (`SINGLE_AZ_1`) |
| Average throughput required | 18.5 MB/s |
| Fraction tiered to the capacity pool | 70% |
| Throughput headroom | the smallest step that covers 5x the average requirement |
| SSD provisioning headroom | 20% above the post-efficiency figure |
| Retention in the S3 landing area (months) | 0.25 — assumed to be expired by a lifecycle rule once the sync has run |
| Do the consumers require a file protocol? | Yes |

- The HPC cluster mounts over NFS, so S3 alone does not meet the requirement
- Long retention dominates, which makes tiering to the capacity pool the largest lever

**S3 alone (consumers also speak the S3 API)**: not costed, because it does not meet the requirement (the consumers require a file protocol).

**S3 bucket + DataSync + FSx for ONTAP**

| Line item | Monthly |
|---|---|
| SSD storage (20,250 GiB) | $3,037.50 |
| Throughput capacity (128 MBps) | $115.97 |
| Capacity pool storage (52,500 GiB) | $1,249.50 |
| Capacity pool read requests | $1.04 |
| Storage (S3 Standard, landing area 3,906 GiB) | $97.66 |
| PUT requests (to an S3 bucket) | $9.40 |
| GET / LIST requests (read by the sync task) | $0.75 |
| DataSync transfer | $195.31 |
| **Total (monthly)** | **$4,707.12** |
| Per logical GiB | $0.0502 |

**FSx for ONTAP S3 AP (this architecture)**

| Line item | Monthly |
|---|---|
| SSD storage (20,250 GiB) | $3,037.50 |
| Throughput capacity (128 MBps) | $115.97 |
| Capacity pool storage (52,500 GiB) | $1,249.50 |
| Capacity pool read requests | $1.04 |
| PUT requests (through an S3 AP) | $2.16 |
| **Total (monthly)** | **$4,406.16** |
| Per logical GiB | $0.047 |

**S3 bucket + S3 Files**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard; the authoritative copy stays in the bucket) | $2,301.20 |
| PUT requests (to an S3 bucket) | $9.40 |
| GET requests (streamed straight from the bucket) | $1.48 |
| S3 Files write (metadata import) | $0.53 |
| S3 Files read (metadata) | $0.61 |
| **Total (monthly)** | **$2,313.22** |
| Per logical GiB | $0.0247 |

This architecture is $300.96 (6%) a month cheaper than the one with a sync job in the middle. The largest term in the difference is "DataSync transfer", which accounts for 65% of it.

### When the same data is read repeatedly — egress is what decides it

Every estimate so far assumed the consumers sit in the same Region. Transfer within a Region is not charged, which is why the comparison came down to storage and request rates.

**With the consumers on premises it is a different question.** Data transfer is charged on bytes leaving the Region, so it multiplies by the number of times the same file is read again. That multiplier is exactly what a cache removes.

| Assumption | Value |
|---|---|
| Whole dataset (logical) | 20,480 GiB |
| Monthly working set (unique bytes actually touched) | 2,048 GiB |
| Reads of the same file per month | 30 |
| Total read per month | 61,440 GiB |
| Average object size | 4 MiB |
| Assumed cache refetch rate | 20% |
| Transfer path | Internet (tiered rate) |

- A reference dataset re-read 30 times a month. The shape assumed is a workload that reads the same input over and over — regression testing, replay, reconciliation

**Reading S3 directly from on premises**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard, 20,480 GiB) | $512.00 |
| GET requests (15,728,640) | $5.82 |
| **Data transfer (all 61,440 GiB read leaves the Region)** | $5,693.44 |
| **Total (monthly)** | **$6,211.26** |

**Copying everything from S3 to on premises and reading it there (DataSync)**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard, 20,480 GiB) | $512.00 |
| Data transfer (the whole 20,480 GiB, once) | $2,078.72 |
| DataSync transfer | $256.00 |
| **Total (monthly)** | **$2,846.72** |

**Reading through FSx for ONTAP + FlexCache (this architecture)**

| Line item | Monthly |
|---|---|
| SSD storage (4,424 GiB) | $663.60 |
| Throughput capacity (128 MBps) | $115.97 |
| Capacity pool storage (11,469 GiB) | $272.96 |
| Data transfer (working set 2,048 GiB plus 20% refetch) | $280.17 |
| **Total (monthly)** | **$1,332.69** |

Reading directly, transfer alone accounts for $5,693.44 (92%). Storage and requests are close to rounding error. This architecture serves the same reads for $1,332.69, a 4.7th of reading directly.

The difference from a full copy is a difference in bytes moved. The copy carries the whole dataset, 20,480 GiB. The cache carries the working set, 2,048 GiB, plus refetches. Monthly, that is $2,846.72 against $1,332.69. On top of it, the capacity provisioned on premises is the whole dataset in one case and the working set in the other. That part does not appear on an AWS bill.

#### Request charges at 10 reads

The assumptions are those above, with the read count fixed at 10. A working set of 2,048 GiB in 4 MiB objects is 524,288 unique objects and 5,242,880 reads.

| Approach | Line item | Total request charges |
|---|---|---|
| Reading the S3 bucket directly | S3 GET (5,242,880) $1.94 | **$1.94** |
| Reading through an FSx for ONTAP S3 AP | GET through an S3 AP (5,242,880) $0.15, Capacity pool reads (440,402 operations) $0.16 | **$0.31** |
| Reading FSx for ONTAP + FlexCache over NFS / SMB (this architecture) | Capacity pool reads (440,402 operations, cache fill only) $0.16 | **$0.16** |
| A full copy with S3 + DataSync | S3 GET (5,242,880; the whole dataset, once) $1.94, S3 LIST $0.02 | **$1.96** |

**At this scale request charges are not the dominant term.** Transfer under the same conditions is $2,078.72, which is 1,072x the $1.94 of request charges incurred by reading directly. What this architecture does on the read side is carry fewer bytes, not pay a lower request rate.

Reading through FlexCache incurs no S3 requests at all, because the consumers read over NFS or SMB. What remains is the read from the origin's capacity pool while the cache fills, counted in the operation size FabricPool works in, 4 MB.

S3 Files is not in this table. **It is not available to the consumers this architecture is for.** The protocols supported are NFSv4.1 and NFSv4.2 only; NFSv3 and SMB are not ([unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html)). That rules out equipment fixed on NFSv3 and any Windows stage of a pipeline. The supported compute the documentation lists is EC2, Lambda, EKS and ECS, with nothing said about mounting from on premises. The case where the consumers can move into AWS is priced further down.

#### Request charges start to matter when the objects are small

The total read stays the same and only the object size changes. The count changes with it, and so does the charge.

| Average object size | Reads per month | Reading S3 directly | Through an S3 AP | This architecture (FlexCache) | As a share of the transfer charge for reading directly |
|---|---|---|---|---|---|
| 8 KiB | 2,684,354,560 | $993.21 | $78.01 | $0.16 | 47.8% |
| 64 KiB | 335,544,320 | $124.15 | $9.89 | $0.16 | 6.0% |
| 256 KiB | 83,886,080 | $31.04 | $2.60 | $0.16 | 1.5% |
| 1,024 KiB | 20,971,520 | $7.76 | $0.77 | $0.16 | 0.4% |
| 4,096 KiB | 5,242,880 | $1.94 | $0.31 | $0.16 | 0.1% |
| 65,536 KiB | 327,680 | $0.12 | $0.17 | $0.16 | 0.0% |

The rightmost column is the one to read. At a few MiB and above, request charges do not reach 1% of the transfer charge. Down at single-digit KiB they reach tens of percent, and at that point both transfer and requests are problems. **"S3 API calls get expensive" holds in this small-object region, and only there.** For a workload with large objects, bytes moved is the only thing worth attacking.

### Looking at transfer and requests together

There are two charges on the read side, transfer and requests, and they respond to different remedies. Transfer falls by carrying fewer bytes; requests fall by making fewer calls. **Which one dominates decides what to do**, so locate your own workload first.

The working set and dataset sizes are fixed; only average object size and read count vary. Both totals include storage — S3 Standard for reading directly, SSD plus capacity pool plus throughput for this architecture. The two columns that move are transfer and requests.

| Average object | Reads per month | Transfer | Requests | Request share | Total, reading directly | This architecture | Ratio | Dominant term |
|---|---|---|---|---|---|---|---|---|
| 8 KiB | 1 | $233.47 | $99.32 | 12% | $844.79 | $1,332.85 | 0.6x | Reading directly is cheaper |
| 8 KiB | 10 | $2,078.72 | $993.21 | 28% | $3,583.93 | $1,332.85 | 2.7x | Transfer (requests not negligible) |
| 8 KiB | 50 | $9,216.00 | $4,966.06 | 34% | $14,694.06 | $1,332.85 | 11.0x | **Both** |
| 64 KiB | 1 | $233.47 | $12.42 | 2% | $757.89 | $1,332.85 | 0.6x | Reading directly is cheaper |
| 64 KiB | 10 | $2,078.72 | $124.15 | 5% | $2,714.87 | $1,332.85 | 2.0x | Transfer |
| 64 KiB | 50 | $9,216.00 | $620.76 | 6% | $10,348.76 | $1,332.85 | 7.8x | Transfer (requests not negligible) |
| 1,024 KiB | 1 | $233.47 | $0.78 | 0% | $746.25 | $1,332.85 | 0.6x | Reading directly is cheaper |
| 1,024 KiB | 10 | $2,078.72 | $7.76 | 0% | $2,598.48 | $1,332.85 | 1.9x | Transfer |
| 1,024 KiB | 50 | $9,216.00 | $38.80 | 0% | $9,766.80 | $1,332.85 | 7.3x | Transfer |
| 4,096 KiB | 1 | $233.47 | $0.19 | 0% | $745.67 | $1,332.85 | 0.6x | Reading directly is cheaper |
| 4,096 KiB | 10 | $2,078.72 | $1.94 | 0% | $2,592.66 | $1,332.85 | 1.9x | Transfer |
| 4,096 KiB | 50 | $9,216.00 | $9.70 | 0% | $9,737.70 | $1,332.85 | 7.3x | Transfer |

There are two ways to read it. **Down a column is the effect of the read count.** Raising the count raises transfer alone; the request share barely moves. **Across a row is the effect of size.** Making the objects smaller leaves transfer unchanged and raises requests, so the share climbs.

#### What to do about each dominant term

| Dominant term | Symptom | What helps | What does not |
|---|---|---|---|
| Transfer | The same data is read many times, in objects of a few MiB or more | Carry only the working set (FlexCache), move the consumers, or lower the rate with Direct Connect | Batching the objects. The count falls but the bytes moved do not |
| Requests | Objects of single-digit KiB, read a very large number of times | Batch into larger objects, or read by a path that does not go through the S3 API | Negotiating the transfer rate. Most of the money is on the request side |
| Both | Small objects, read repeatedly | Batching (for requests) and caching (for transfer) together. Either alone leaves the other | Addressing only one of the two |
| Neither | Few reads, and no file-protocol requirement | Read S3 directly and carry no file system floor | Introducing a cache. The floor costs more than it saves |

This architecture's column barely moves with size or count because the reads do not go through the S3 API and what is carried is limited to the working set. **The floor is therefore what stands out**, which puts it behind in the low-read region — the rows marked "Reading directly is cheaper".

#### For reference — with the consumers moved into AWS

This architecture assumes the consumers are outside AWS and cannot be moved. If they can be moved it is a different question, so that case is priced here for reference.

**Transfer within a Region is not charged.** The $2,078.72 of transfer in the table above disappears entirely. That single line is larger than anything the choice of storage layer moves.

**Reading S3 directly from EC2**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard, 20,480 GiB) | $512.00 |
| S3 GET (5,242,880) | $1.94 |
| Data transfer | $0.00 |
| **Total (monthly)** | **$513.94** |

**Reading as files from EC2 through S3 Files**

| Line item | Monthly |
|---|---|
| Storage (S3 Standard, 20,480 GiB) | $512.00 |
| S3 GET (5,242,880; above the threshold, so straight from the bucket) | $1.94 |
| S3 Files metadata read | $0.80 |
| S3 Files metadata import | $0.14 |
| S3 Files high-performance storage | $0.00 |
| Data transfer | $0.00 |
| **Total (monthly)** | **$514.88** |

**Reading FSx for ONTAP in the same Region**

| Line item | Monthly |
|---|---|
| SSD storage (4,424 GiB) | $663.60 |
| Throughput capacity (128 MBps) | $115.97 |
| Capacity pool storage (11,469 GiB) | $272.96 |
| Data transfer | $0.00 |
| **Total (monthly)** | **$1,052.53** |

S3 Files differs from reading directly by only $0.94. An average object size of 4 MiB is above the 128 KiB threshold, so the data is not held on high-performance storage and storage charges do not increase. As a way to give POSIX file semantics to data in S3, it is inexpensive.

FSx for ONTAP in the same Region is $1,052.53, 2.0x reading directly, because with the transfer difference gone the file system floor is what is left. The reason to choose FSx for ONTAP here is not cost but a requirement: SMB, NFSv3, ONTAP's data management features, or running alongside on-premises systems.

**Moving the consumers is the most effective way to reduce read-side cost.** If they can move, consider that first. This architecture is for the cases where they cannot: the equipment is on site, proximity to what is being measured is required, or investment in existing facilities has not been written off.

#### Sweeping the read count

Only the number of times the same working set is read changes; every other assumption is held.

| Reads per month | Total read per month | Reading directly | This architecture | Ratio, direct to this architecture |
|---|---|---|---|---|
| 1 | 2,048 GiB | $745.67 | $1,332.69 | 0.6x |
| 5 | 10,240 GiB | $1,680.33 | $1,332.69 | 1.3x |
| 10 | 20,480 GiB | $2,592.66 | $1,332.69 | 1.9x |
| 30 | 61,440 GiB | $6,211.26 | $1,332.69 | 4.7x |
| 50 | 102,400 GiB | $9,737.70 | $1,332.69 | 7.3x |
| 100 | 204,800 GiB | $18,451.40 | $1,332.69 | 13.8x |

At one read, reading directly is cheaper: the same bytes move and no file system floor is carried. As the count rises, only the transfer charge for reading directly rises with it, while the cache side does not. **The break-even point is a read count.**

Over Direct Connect the rate is a flat $0.041 per GB (against $0.114 per GB for the first 10 TB to the internet), which lowers the ratio without changing the structure. Port charges are separate and depend on the facility.

The assumption with the most leverage in this section is the working set as a share of the dataset. The closer it gets to the whole dataset, the less a cache is worth and the smaller the gap to a full copy. The more localised the access, the wider the gap.

### The distribution side — an all-SSD cache volume

Every estimate so far looks only at the collection side, the origin. This architecture places a FlexCache cache volume on the distribution side, which is charged separately.

A cache volume cannot be tiered. ONTAP allows a FabricPool origin to be cached, but **the cache volume itself is not tiered** ([supported and unsupported features](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html)). All of the cache therefore sits on SSD.

That works because the cache is sparse. FlexCache does not replicate all of the origin's data; it holds only the blocks actually read. NetApp's sizing guidance recommends **at least 10%** of the origin, which is also the default at creation ([sizing guidance](https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html)). Read-heavy workloads are commonly run at 5-15%, and within that band an all-SSD footprint is affordable.

Below is the monthly cost of the distribution side at a cache ratio of 10%, against a full copy at the same site. The full copy is a normal volume, so it is costed with tiering available to it. Costing it as all-SSD would widen the gap, and would not be a fair comparison.

| Workload | Origin logical | Cache SSD (post-efficiency, 10%) | Cache at 10%, monthly | Cache at 20%, monthly | Full copy, monthly | Ratio, copy to cache |
|---|---|---|---|---|---|---|
| HiL test benches | 39,062 GiB | 2,813 GiB | $537.92 | $959.72 | $3,292.29 | 6.1x |
| EDA / CAE | 43,945 GiB | 1,319 GiB | $313.82 | $511.52 | $1,564.09 | 5.0x |
| Media / rendering | 73,242 GiB | 8,790 GiB | $1,550.44 | $2,868.79 | $4,263.32 | 2.7x |
| Genomics | 93,750 GiB | 6,750 GiB | $1,128.47 | $2,140.97 | $4,402.97 | 3.9x |

The gap is narrowest where a large share of the origin is tiered: the copy can tier too, which blunts the difference in SSD rates. Where most of the data is hot, the copy has to sit on SSD as well and the gap widens.

Monthly cost against cache ratio, shown on the workload with the largest origin, Genomics (93,750 GiB).

| Cache ratio | Cache SSD | Cache, monthly | Note |
|---|---|---|---|
| 10% | 6,750 GiB | $1,128.47 | the lower bound in the sizing guidance, and the default at creation |
| 15% | 10,125 GiB | $1,634.72 |  |
| 20% | 13,500 GiB | $2,140.97 | for comparison when the working set does not fit |
| 25% | 16,875 GiB | $2,647.22 |  |
| 50% | 33,750 GiB | $5,178.47 |  |
| 100% | 67,500 GiB | $10,240.97 | effectively a copy, and more expensive than one because it cannot tier |

A ratio of 100% is not a defensible choice. Putting everything in a cache that cannot tier costs more than putting a full copy in a normal volume that can. Sizing a cache at full size, as a "replacement for a copy", lands here.

### The three options side by side — collection and consumption at the same site

No distribution side is added here. **Copy from a bucket into FSx for ONTAP with DataSync and that FSx for ONTAP already serves NFS and SMB, so there is nothing for a cache to do.** A cache earns its cost only when the consumers sit somewhere other than the file system, and the comparison for that case is cache against full copy, in the table above. This table is the single-site case, where every option is one file system or none.

This table assumes the data is delivered to the consumers as files. If the S3 API is enough for them, no distribution layer is needed at all, and the S3-alone figure in each workload's estimate is the floor.

The third column, S3 Files, mounts an S3 bucket as a file system. There is no FSx for ONTAP and so no fixed floor, and the authoritative copy stays in the bucket. The protocols supported are NFSv4.1 and NFSv4.2; **NFSv3 and SMB are not** ([unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html)). On EC2 it needs the S3 Files mount helper (shipped in `amazon-efs-utils`) and is mounted with the `s3files` file system type ([mounting instructions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html)). The supported compute is EC2, Lambda, EKS and ECS ([S3 Files overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html)). Several constraints here cannot be settled on cost, so read these figures together with [specifications that decide whether S3 Files fits](#specifications-that-decide-whether-s3-files-fits) below.

| Workload | Average object | S3 + DataSync + FSx for ONTAP | FSx for ONTAP S3 AP (this architecture) | S3 + S3 Files |
|---|---|---|---|---|
| Vehicle / IoT telemetry | 64 KiB | $3,629.75 | $2,088.02 | $10,756.38 |
| HiL test benches | 1,024 KiB | $3,763.33 | $3,317.22 | does not meet the requirement |
| EDA / CAE | 256 KiB | $2,835.78 | $2,321.44 | $1,522.08 |
| Media / rendering | 512,000 KiB | $4,721.38 | $4,263.42 | $1,809.34 |
| Genomics | 8,192 KiB | $4,707.12 | $4,406.16 | $2,313.22 |

Object size flips the result. S3 Files does not hold files above its default threshold (128 KiB) on high-performance storage; it streams them straight from the bucket. No storage charge arises, which makes it cheap for a workload reading large objects. Files at or below the threshold are imported onto high-performance storage at $0.36 per GB-Mo, which makes it expensive for small objects.

On the large-object rows the S3 Files figure looks like little more than S3 Standard storage. That is the design, not a missing line. Reads at 1 MiB and above bypass high-performance storage and stream from the bucket, so no file system data charge arises. What remains is the S3 GET and a 4 KiB metadata read, and with large objects the count is low enough not to show. S3 GET and PUT are counted on every row.

**The three grow differently as distribution sites are added.** This architecture adds a cache per site against one origin, so each site adds roughly a tenth of the origin's logical size. The DataSync approach places a full copy per site, so each site adds the whole dataset. S3 Files is one VPC per file system, so a file system is created per site; several file systems can attach to the same bucket, and each is charged for what it actually uses. The more sites, the worse the full-copy approach looks.

Where S3 Files comes out cheaper, the reason to choose this architecture anyway is not cost. It is a requirement: the consumers are equipment whose configuration cannot be changed, SMB is needed, they are outside AWS, or ONTAP's data management features have to reach the data as soon as it is collected. On cost alone, and absent such a requirement, there are cases where S3 Files fits better.

#### Why S3 Files is cheaper for large objects

Laying out the line items for Genomics gives the reason in one line. S3 Files **does not hold the data of above-threshold files on high-performance storage**, so storage is charged at the S3 Standard rate and nothing more. FSx for ONTAP puts the equivalent of the working set on SSD.

| Item | Value |
|---|---|
| Logical data | 93,750 GiB |
| S3 Files storage (all logical data in S3 Standard) | $2,301.20 |
| This architecture, SSD portion only (20,250 GiB x $0.15) | $3,037.50 |
| SSD portion as a multiple of all-S3-Standard | 1.32x |

Putting 30% of the logical data on SSD already exceeds the cost of holding all of it in S3 Standard. The throughput capacity floor is on top of that. S3 Files has no such line.

The same table shows what is given up for it. An above-threshold file in S3 Files is fetched from the bucket on every read. If low latency is needed, the threshold has to be raised, and what is raised above it becomes billable at $0.36 per GB-Mo. The low figure is paid for in read latency.

#### Sweeping the storage efficiency assumption

Efficiency is the assumption that moves the figures in this document most. Sweeping the SSD-tier efficiency on Genomics gives the following, with the capacity pool tier always assumed to be half of it.

| SSD-tier efficiency | Pool-tier efficiency | This architecture, monthly | S3 + S3 Files, monthly | Note |
|---|---|---|---|---|
| 0% | 0% | $6,743.54 | $2,313.22 |  |
| 20% | 10% | $5,575.00 | $2,313.22 |  |
| 40% | 20% | $4,406.16 | $2,313.22 | AWS's published figure for seismic data |
| 60% | 30% | $3,237.63 | $2,313.22 |  |
| 75% | 38% | $2,361.04 | $2,313.22 | AWS's published figure for engineering data |

**The S3 Files column does not move.** ONTAP deduplication and compression do not reach S3 storage charges, so no efficiency assumption changes that figure. The assumption can therefore only work in this architecture's favour. An optimistic figure makes it look better than it is.

Be careful expecting a high figure where tiering is enabled. **Background efficiency processing does not run on tiered data.** Only what was applied while the block was on SSD is preserved, and a block tiered before efficiency ran stays in the pool with no reduction at all ([FSx for ONTAP documentation](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/manage-vol-SE.html), [NetApp KB](https://kb.netapp.com/Advice_and_Troubleshooting/Data_Storage_Software/ONTAP_OS/Does_ONTAP_apply_efficiencies_to_blocks_that_are_tiered-out_to_Fabricpool%3F)). With a short cooling period, or an `All` policy, the pool-tier figure tends towards 0%.

For small objects the expiry on high-performance storage is the largest lever. Sweeping it on Vehicle / IoT telemetry gives the following (the default is 30 days; the configurable range is 1 to 365).

| Expiry (days) | Active share | S3 + S3 Files, monthly | Note |
|---|---|---|---|
| 1 | 3% | $4,384.31 |  |
| 3 | 10% | $4,823.76 |  |
| 7 | 23% | $5,702.67 |  |
| 30 | 100% | $10,756.38 | default |
| 90 | 100% | $10,756.38 |  |

Shortening it lowers the figure, but reading a file that has expired triggers another import from the bucket. Where reads are spread evenly over time, what shortening saves comes back as import round trips.

The threshold has the same structure. Raising it lets larger files be read at low latency, and what is raised becomes billable on high-performance storage. This column's low figure is paid for by above-threshold files being read at S3 latency.

### The increment when FSx for ONTAP is already there

In the situation this architecture is for, the consumers require NFS or SMB, so FSx for ONTAP is already there. Adding a way in over S3 is therefore not the greenfield question "S3 or FSx for ONTAP" but "which increment is cheaper".

The assumptions are those of Vehicle / IoT telemetry — small objects, written often above (300 million objects a month at 64 KiB). SSD and throughput are taken as already paid for by the existing workload, so only the increment is shown.

| Increment | Line item | Monthly |
|---|---|---|
| Add an S3 AP | PUT through the S3 AP, nothing else | $324.00 |
| Add an S3 bucket and a sync job | S3 storage + S3 PUT + the sync job's GET + DataSync transfer | $1,865.73 |
| Difference |  | **$1,541.73** |

An S3 Access Point carries no hourly charge of its own, so its increment reduces to request charges. The sync job's increment includes storage for holding the same bytes in two places. That difference does not narrow as capacity grows.

<!-- finops-model:end -->

## Value that does not appear in the cost, and its reverse

A FinOps decision does not close on the invoice alone. If the same figure buys different things, the
figure is not enough to compare on. What is gained and what is given up for it are laid out at the
same granularity.

| Gained | What it is | How it bears on cost |
|---|---|---|
| Freshness | Data is on the volume at the moment it is written. There is no structure in which a sync job's interval becomes the delay | Does not show in the figures. Where freshness is a requirement, the alternative has to shorten its interval, and transfer and requests rise by that much |
| A single source of truth | The same bytes are not held in two places. A deletion happens once | Double capacity disappears. So does the structure in which a divergence keeps widening |
| A consolidated write path | Writes are consolidated onto the S3 Access Point on the origin. Authorization takes the form of both the S3 AP side and the ONTAP side having to allow it | Effort in review cycles. Does not appear on the invoice. **What the audit log records is the identity fixed on the access point, not the calling IAM principal.** If per-principal tracing is a requirement, budget for splitting access points or for correlating with AWS CloudTrail |
| Fewer things to operate | Detecting sync failures, re-running partial ones, and confirming that renames and deletes propagated leave routine operations | Does not appear on the invoice. Human cost, and the cost of judgement during an incident |
| ONTAP's data management features reach data as soon as it is collected | Collected data can be protected with Snapshot as it is, cloned for verification with FlexClone, and replicated with SnapMirror | No additional licence. Building the equivalent out of S3 mechanisms lands on other billed items |
| Less carried to the distribution side | FlexCache pulls only the blocks requested from the origin. All of the data is not placed at the site | Roughly a tenth of the origin in SSD is enough on the distribution side. The difference from a full copy is in the distribution table under [estimates](#estimates) |

| Given up | What it is |
|---|---|
| S3-specific features | Event notifications, lifecycle and versioning are out of scope. Design a substitute with polling or FPolicy |
| Freedom in a flat namespace | Object names are constrained. Not suited to a workload that leans on names which are not NAS-friendly |
| Elastic bandwidth | Throughput capacity is chosen in advance. It does not stretch with demand the way S3 does |
| A choice of storage classes | There is no model that cuts the storage rate steeply in exchange for a retrieval charge. The one tier available is the capacity pool |
| Object access on the distribution side | The cache side does not offer the S3 API |
| Tiering on the cache side | A cache volume cannot be tiered. A working set that grows becomes SSD cost directly |
| Locality of a cache miss | A miss goes back to the origin, consuming its throughput and, across an AZ or Region, transfer charges |

None of the first four rows appears on an invoice. Compared on cost alone, a workload handling large
objects infrequently shows little difference. In that case the basis for choosing is in reading the
second table against the first.

## Specifications that decide whether S3 Files fits

Some workloads in the estimates above come out cheaper on S3 Files. Choosing on the figure alone
would be a mistake, so the specification constraints that do not appear in the cost are collected
here. All of it is what the AWS documentation states, not measured in this architecture.

### Supported protocols and versions side by side

In a design that delivers files, the NFS version the consumers can speak decides the options. The
three options cover different ranges.

| Option | Protocols supported | Source |
|---|---|---|
| FSx for ONTAP (origin / cache) | NFS v3, v4.0, v4.1, v4.2 and SMB. NVMe and iSCSI are available too | [How FSx for ONTAP works](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/how-it-works-fsx-ontap.html) |
| S3 Files | NFSv4.1 and NFSv4.2. **NFSv3 and SMB are out of scope** | [Unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |
| Amazon EFS (what S3 Files is built on) | NFSv4.0 and NFSv4.1 | [What is EFS](https://docs.aws.amazon.com/efs/latest/ug/whatisefs.html) |

S3 Files is built on EFS, and the supported versions do not match. EFS's v4.0 is out of scope, and
v4.2 is in instead. A shared foundation is not grounds for inferring a version; check each in its own
documentation.

Where there is equipment fixed on NFSv3, that difference narrows the options as it stands. The same
holds for a stage of the pipeline that uses SMB: everything other than FSx for ONTAP drops out.

### The protocol and what it assumes of the consumers

| Item | What it is | Source |
|---|---|---|
| Protocols supported | NFSv4.1 and NFSv4.2. **NFSv3 and SMB are out of scope** | [Unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |
| Locking | Advisory throughout. Mandatory locking and deny share are not supported | Same |
| NFS ACLs | Not supported. POSIX permission bits are | Same |
| Kerberos | Not supported. Authentication that assumes AD integration cannot be brought over | Same |
| `nconnect` | Not supported. Multiple connections cannot be tuned through a mount option | Same |
| How to mount | On EC2 the mount helper (`amazon-efs-utils`) is required, and it is mounted with the `s3files` type | [Mounting instructions](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-mounting.html) |
| Supported compute | EC2, Lambda, EKS, ECS | [S3 Files overview](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files.html) |
| VPC | One VPC per file system, one mount target per AZ | [Unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |

SMB and NFSv3 being out of scope bears directly on the situation this architecture is for. An
existing Windows stage, or equipment fixed on NFSv3, cannot be a consumer.

### Synchronisation delay

| Direction | Behaviour | Source |
|---|---|---|
| Bucket to file system | S3 event notifications are watched and changes appear **usually within seconds**. That applies only to files whose data is currently on high-performance storage; a file evicted by expiry is not updated until it is next accessed | [How synchronisation works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html) |
| File system to bucket | After writes stop, it waits **about 60 seconds** and exports in a batch | [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) |

The 60 seconds on the export side is not a wait but a period of **write inactivity**. In the
documentation's example, an application appending every 30 seconds for five minutes has its export
begin in the sixth minute. Nothing reaches the bucket while the appends continue. For a file written
without a break, such as a log, freshness as seen from the S3 API lags by that much.

Where collection happens over the S3 API and the consumers only read, the seconds on the import side
are what matter. Design the consumers to write back and the 60 seconds on the export side becomes
the freshness downstream.

| Synchronisation rate limit | Value | Source |
|---|---|---|
| Import | 2,400 objects/second and 700 MB/second per file system | [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) |
| Export | 800 files/second and 2,700 MB/second per file system | Same |

Changes beyond the synchronisation rate are queued and processed in order. A rising `PendingExports`
is what indicates that state ([best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-best-practices.html)).

### What is counted

The S3 Files figure can look like storage and nothing else, so the line items are made explicit. With
large objects **the request count is low enough not to show in the figure**, but it is counted.

| Item | Files at or below the threshold | Files above the threshold |
|---|---|---|
| S3 Standard storage (the authoritative copy stays in the bucket) | Counted | Counted |
| S3 PUT (collection) | Counted | Counted |
| S3 GET | Counted. The first read is streamed from the bucket, and that is what triggers the import | Counted. Every read is a stream from the bucket |
| S3 Files high-performance storage | Counted, for the active share only | Does not arise. The data is not held there |
| S3 Files write | Counted: the import (data plus metadata) | Counted: metadata only |
| S3 Files read | Counted: reads after import, plus metadata | Counted: metadata only |

A read of 1 MiB or more is streamed straight from the bucket even when the data is on
high-performance storage, and no file system data charge arises ([how metering works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-metering.html)).
That specification is why the large-object estimates lean towards storage.

**Some things are not counted**, so do not use these figures as an estimate as they stand.

| Not counted | What it is |
|---|---|
| Metadata storage | File metadata is held on high-performance storage and is not removed when the data expires ([how synchronisation works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html)). It accumulates in proportion to object count. At 4 KiB each, 300 million files is about 1,144 GiB, or about 2,861 GiB if the 10 KiB minimum billable size applies. Which basis is billed is not stated in the documentation, so the item is named without asserting a figure |
| Non-current version storage | S3 versioning is mandatory, so these accumulate. Expiring them through lifecycle has to be designed separately |
| Splitting of large reads | Where one read is split into several GETs internally, the GET count is higher than estimated. The granularity of the split is not documented |
| Cross-Region data transfer | A single Region is assumed |

### Consistency and conflicts

| Item | What it is | Source |
|---|---|---|
| Which side wins | The bucket is authoritative. If the file system side and the bucket side change the same file at once, the file system's copy is moved to a lost and found directory | [Best practices](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-best-practices.html) |
| Recommendation | Fix the write path to either the file system or the bucket, not both | Same |
| Versioning | **S3 versioning is mandatory** on the linked bucket. A change on the file system side is written as a new version | [How synchronisation works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html) |

Versioning being mandatory bears on cost. Storage for non-current versions accumulates, so expiring
them through lifecycle has to be designed. `chmod` and `chown` create a new version too. The estimates
above do not include this.

### Namespace and structural constraints

This overlaps with what the architecture's [S3 AP design guide](../limits/s3ap-design-guide.md)
covers.

| Item | Value | Source |
|---|---|---|
| Path components | Directory and file names up to 255 bytes | [Unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |
| Object keys | Beyond 1,024 bytes in total, the object cannot be exported | Same |
| Keys that cannot be POSIX | `foo//bar`, `foo/./bar`, `foo/../bar`, and keys containing a null byte are inaccessible | Same |
| Hard links | Not supported | Same |
| Directory depth | Up to 1,000 levels | Same |
| Rename and move | S3 has no rename, so every object under the prefix is copied and deleted. Renaming a directory of 100,000 files takes minutes to reach the bucket | [How synchronisation works](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-synchronization.html) |
| Large prefixes | Naming a prefix large enough for a rename to take up to four hours (about 12 million objects) is an error. `--AcceptBucketWarning` overrides it | Same |

Laying a large number of objects flat in one folder makes renames and the first listing heavy. This is
the same consideration as making the entry point an S3 AP: either choice needs a directory design.

### The relationship to storage classes

| Item | What it is | Source |
|---|---|---|
| The archive classes | Objects in S3 Glacier Flexible Retrieval, S3 Glacier Deep Archive, and the archive and deep archive tiers of Intelligent-Tiering **cannot be read from the file system**. They have to be restored over the S3 API first | [Unsupported features and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |
| S3 ACLs | Changes made on the file system side are not preserved | Same |

Not being able to read the archive classes bears on how much freedom the cost design has. Drop a tier
to the archive classes to cut the storage rate and it can no longer be read as a file. With S3 Files
as the delivery path, data that has to be readable as a file stays in the Standard classes.

### The corresponding constraints on this architecture

So that the comparison is not written strictly on one side only, this architecture's constraints are
listed at the same granularity.

| Item | What it is |
|---|---|
| Operations supported by the collect layer | Not all of S3. Event notifications, lifecycle and versioning are out of scope ([limits](../limits/s3-access-point.md)) |
| Writing on the serve layer | A cache is writable. The default write-around responds after the origin has committed, so its latency is high. Write-back is asynchronous and fast, with the conditions above attached |
| Tiering on the serve layer | A cache volume cannot be tiered |
| Object access on the serve layer | The cache side does not offer the S3 API |
| Version assumed by the collect layer | ONTAP 9.17.1 or later |
| Fixed cost | The throughput capacity and SSD floor, every month |

## Writing on the distribution side — the two FlexCache modes

A cache volume is not read-only; it can be written to. There are two modes, and freshness and latency
come out differently under the default and the alternative.

| Mode | Behaviour | Source |
|---|---|---|
| write-around (default) | The write is forwarded from the cache to the origin. The client is not answered until the origin has committed it to storage and replied. It crosses the network both ways, so its latency is higher than write-back | [Replication with FlexCache](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) |
| write-back (ONTAP 9.15.1 and later) | The write is committed on the cache side and answered immediately, and written to the origin **asynchronously**. Writes run at close to local speed | Same |

The AWS documentation points to write-back for write-heavy workloads that need low latency, and to
write-around for read-heavy workloads that are not latency-sensitive, or where there are more than
ten origin volumes. Specify `-is-writeback-enabled true` at creation, or change it later with
`volume flexcache config modify -is-writeback-enabled` (advanced privilege required)
([creating a FlexCache](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/create-flexcache.html)).

On freshness, it is the property of the default write-around that matters. Because it answers only
after the origin has committed, **there is no window in which a write on the cache side is absent
from the origin**. It is not a structure that waits for an asynchronous batch, so nothing lags as
seen from the source of truth. It is a design that takes freshness in exchange for latency.

### Conditions attached to write-back

Enabling it adds conditions. They are design constraints rather than cost, so they are collected
here.

| Item | What it is | Source |
|---|---|---|
| ONTAP version | Available from 9.15.1, but 9.17.1P1 carries important improvements and is strongly recommended on both the origin and the cache. 9.15.1 is not recommended for production | [Write-back guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html) |
| Configuration | A single constituent for the whole cache volume is recommended. Multiple constituents invite unintended evictions | Same |
| The verified range | Tested with files under 100 GB and a WAN round trip between cache and origin within 200 ms | Same |
| Rename | Renaming a file evicts it from the cache. No other operation can proceed until the dirty data has drained to the origin | Same |
| Attributes that can be changed | The cache side can set timestamps, mode bits, NT ACLs, owner, group and size. Anything else is forwarded to the origin and can cause an eviction | Same |
| Snapshots on the origin | Taking a snapshot on the origin reclaims outstanding dirty data from every associated write-back cache. Heavy writing means several retries | Same |
| SMB | On a write-back-enabled cache, SMB opportunistic locks (oplocks) for writing are not supported | Same |
| Free space on the origin | At 20% or less free on the origin volume it switches to write-around automatically. The threshold is evaluated against both the origin's reported figure and the aggregate's physical free space, so an over-provisioned configuration switches earlier than expected | Same |
| Network | A narrow or lossy inter-cluster network affects write-back performance strongly | Same |
| Resources on the origin | 128 GB of RAM and 20 or more CPUs per origin node are strongly recommended. For a scale-up FSx for ONTAP configuration, 1,024 GiB or more of SSD is cited as the reference point | [TCO case study](https://aws.amazon.com/blogs/storage/how-a-customer-reduced-storage-tco-by-28-with-amazon-fsx-for-netapp-ontap/) |
| Licence | FlexCache needs no additional licence, write-back included | Same |
| Peering | Inter-cluster peering between origin and cache, and SVM peering with the FlexCache option, are required | Same |

This architecture collects into the origin over an S3 AP and describes the distribution side as
read-heavy, not because a cache cannot be written to, but because that avoids carrying the conditions
above. Where the distribution side genuinely has heavy writes, write-back is an option. In that case,
include the version requirement and the origin-side resources in the estimate.

## The effect on surrounding workloads

Adding an entry point for collection affects the existing NFS and SMB workloads. Cost moves in order
to absorb that effect, so looking at the request rate alone leads to the wrong decision.

| Effect | What it is | How it shows in cost |
|---|---|---|
| Shared throughput capacity | S3 AP requests and NFS / SMB traffic both come out of the same file system's throughput capacity | Running short of headroom means one step up. From 128 to 256 MBps on Single-AZ first generation is +$115.97 a month |
| Too much concurrency | Measured in a sister repository: against a 128 MBps file system, concurrency 25 gave a P99 of 894 ms and concurrency 50 stretched to 1,703 ms | The latency reaches the file clients on the same file system too. Trying to solve it by raising concurrency works in the wrong direction |
| Shared IOPS | 3 IOPS per GiB of SSD is included. Collection that writes many small objects consumes IOPS | Beyond what is included, additional IOPS are charged |
| Tiering against reads | Capacity pool read requests cost more per request than a GET through an S3 AP | Tiering aggressively to cut storage gives it back on the request side for data that is read often |
| The cost of the distribution side (FlexCache) | A cache is another file system, or another platform. It cannot be tiered, so all of it is SSD | Inside AWS that is one more floor. With a small origin the cache sits at the 1 TiB SSD floor. On premises it becomes that platform's cost |
| Cache misses return to the origin | A read of a block not in the cache goes to the origin | It consumes the origin's throughput. A cache too small for the working set raises the miss rate, which leads to reinforcing the origin |
| Backup capacity | More collected means more to back up | GB-Mo of backup storage rises with it |
| Snapshots | Frequent writes and deletes increase the blocks a snapshot holds | SSD consumption rises, which feeds back into how much SSD is provisioned |

The first two rows matter most in practice. Adding collection degrades latency on the distribution
side, and stepping throughput up to deal with it can cancel out the difference won on request rates.
In a design that puts collection and distribution on the same file system, put throughput headroom in
the estimate as a cost item from the start.

## Licensing

| Item | How it works | Source |
|---|---|---|
| ONTAP's data management features | FlexCache, SnapMirror, Snapshot, FlexClone, deduplication and compression are included in the FSx for ONTAP price. There is no separate licence to procure | For FlexCache, the AWS Storage Blog states "included with your ONTAP purchase ... No extra license is required" ([source](https://aws.amazon.com/blogs/storage/how-a-customer-reduced-storage-tco-by-28-with-amazon-fsx-for-netapp-ontap/)) |
| SnapLock | A separate licence item. The AWS Storage Blog lists the cost components as "SSD storage, SSD IOPS, Capacity Pool usage, throughput capacity, backups, and SnapLock licensing", and SnapLock usage appears in the billing report in GB-Month | [Sizing](https://aws.amazon.com/blogs/storage/how-to-size-an-amazon-fsx-for-netapp-ontap-file-system/) and [the billing report](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/FSxONTAP-Billing.html) |
| The S3 AP itself | There is no per-access-point hourly charge. What is charged is requests and data transfer | [FSx for ONTAP pricing](https://aws.amazon.com/fsx/netapp-ontap/pricing/) |
| Where the distribution side is not FSx for ONTAP | Placing a cache on on-premises ONTAP or similar adds that platform's licensing and maintenance | [Portability](../../portability.md) |

Where compliance retention is a requirement, estimate SnapLock as a separate item. The estimates
above do not include it. The Tokyo rate could not be read from the Price List API, so the item is
named without a figure.

Where the fixed cost sits differs by approach. In an approach with a gateway or FUSE in the path, the
software licence and a permanently running instance are the permanent cost. Here, committing
throughput capacity in advance plays the same role. Neither is an approach without a fixed cost; they
differ in where it sits.

## Making the cost visible

The usage types to follow in Cost Explorer. The prefix is `APN1-` for the Tokyo Region and differs
elsewhere.

| What you want to see | Service | Usage type |
|---|---|---|
| SSD storage (Single-AZ first generation) | FSx for ONTAP | `APN1-Storage.SAZ_2N:SSD` |
| SSD storage (Single-AZ second generation) | FSx for ONTAP | `APN1-Storage.SAZ_2N2:SSD` |
| SSD storage (Multi-AZ first / second generation) | FSx for ONTAP | `APN1-Storage.MAZ:SSD` / `APN1-Storage.MAZ2:SSD` |
| Throughput capacity (Single-AZ first / second generation) | FSx for ONTAP | `APN1-ThroughputCapacity.SAZ_2N` / `APN1-ThroughputCapacity.SAZ_2N2` |
| Additional SSD IOPS (Single-AZ first generation) | FSx for ONTAP | `APN1-ProvisionedSSDIOPS.SAZ_2N` |
| Capacity pool storage | FSx for ONTAP | `APN1-Storage.SAZ_2N:CPoolStd` |
| Capacity pool reads / writes | FSx for ONTAP | `APN1-Requests.SAZ_2N:CPoolStdRd` / `APN1-Requests.SAZ_2N:CPoolStdWr` |
| Backup | FSx for ONTAP | `APN1-BackupUsage` |
| **PUT / COPY / POST / LIST through an S3 AP** | **S3** | `APN1-Requests-FSXONTAP-Tier1` |
| **GET and all other requests through an S3 AP** | **S3** | `APN1-Requests-FSXONTAP-Tier2` |

The two bold rows need attention. Requests through an S3 AP are destined for an FSx for ONTAP volume
and yet are **billed as Amazon S3**. A report narrowed to FSx for ONTAP alone loses the cost of the
collection path entirely. To follow what collection costs, put the FSx for ONTAP usage types and the
S3-side usage types containing `FSXONTAP` in the same report.

## Levers for reducing cost

| Lever | When it works | Side effect |
|---|---|---|
| Batch into larger objects | Request charges exceed storage charges | It stops matching the consumers' read unit. Too coarse and refetching rises |
| Lower the tiering threshold | A large share of the data is read rarely | Capacity pool read requests rise. Counterproductive for data that is read often |
| Right-size throughput from measurement | It is over-provisioned | It falls in steps, and cutting too far affects the existing NFS / SMB |
| Enable storage efficiency | Data that compresses or deduplicates | No effect on already-compressed material |
| Shorten the retention period | There is room in the retention requirement | It can conflict with audit requirements |
| Choose Single-AZ | A single AZ satisfies the availability requirement | It stops on an AZ failure. DR has to be designed separately, and access from outside the preferred AZ carries transfer charges |
| Choose the first generation | You have no use for the second generation's ceilings | The deployment type cannot be changed, so needing the ceilings later means migration work |
| Move collection onto an S3 AP and fold the sync job away | A sync job is part of routine operations | If S3-specific features were in use, a substitute is required |
| Size the cache to the working set | The distribution side does not need all of the data | Too small raises the miss rate and consumes the origin's throughput |
| Make the cache side Single-AZ | The cache can be rebuilt from the origin | Distribution stops while it is rebuilt. Have a recovery procedure ready |
| Do not back up the cache side | The cache is not the source of truth | It assumes the origin's backup design |

The last lever also has a part that does not appear in the cost. Monitoring sync jobs, re-running
partial failures, and confirming that deletions propagated leave the list of operational items. That
part does not appear on the invoice, and the invoice is not all that FinOps covers.

## When this architecture does not suit on cost

| Condition | Why |
|---|---|
| Large average object size, few requests | The difference in request rates does not bite. The cost difference is small and the basis for choosing moves to operations |
| The S3 API is enough for the consumers | There is no reason to carry the FSx for ONTAP floor |
| Mostly long-term retention, rarely read | The Glacier storage rate and retrieval charge model fits better |
| The data volume is small | The monthly floor cannot be recovered |
| S3-specific features are needed | Event notifications, lifecycle and versioning are out of scope ([limits](../limits/s3-access-point.md)) |
| The S3 API is needed on the distribution side | This architecture does not offer it ([comparison with the alternatives](alternatives.md)) |
| The consumers are limited to Linux compute in AWS and read large objects | S3 Files comes out cheaper: there is no floor, and above-threshold files are streamed straight from the bucket |

## Assumptions and limits

| Item | What it is |
|---|---|
| Scope of the unit prices | Tokyo Region, on demand, excluding tax. Savings Plans, private pricing and the free tier are not included |
| Where the unit prices come from | The AWS Price List API. The date applicability starts is the `effective` column of the unit price table |
| Usage | All assumed. Estimates, not measurements |
| Storage efficiency | The SSD tier uses AWS's published per-workload figures. The capacity pool tier is assumed to be 50% of the SSD tier, which is not a sourced value ([how storage efficiency is handled](#how-storage-efficiency-is-handled)) |
| Cache ratio | Assumed as a share of the origin's logical data. The default is 10%, matching the lower bound of NetApp's sizing guidance and the default at creation. 20% is shown alongside for comparison |
| The S3 Files threshold and expiry | The defaults are assumed (128 KiB, 30 days). Both are configurable and both move cost and latency |
| S3 Files versioning | Mandatory, but storage for non-current versions is not included in the estimates |
| S3 Files metadata storage | It remains on high-performance storage, but the billing basis is not stated in the documentation, so it is not included in the estimates. It is not negligible where the object count is high |
| Whether S3 Files is available | Judged per workload, on whether the consumers are Linux compute in AWS that can have the mount helper installed |
| The cache's availability configuration | Single-AZ is assumed, on the premise that a cache can be rebuilt from the origin |
| Not included in the estimates | SnapLock, additional SSD IOPS, snapshot reserve, cross-Region data transfer, Direct Connect port charges, and on-premises equipment and licences |
| Data transfer | Included in the read-side estimates. The rate is the tiered internet rate, or flat for Direct Connect. On-premises circuit costs are not included |
| The cache refetch rate | Assumed as a share of the working set. Treated as a plausible range for read-heavy reference workloads, but not measured on real equipment. The actual value is set by change frequency and the eviction configuration |
| The working set share | Assumed at a tenth of the whole dataset. Likewise treated as a plausible range rather than measured. The larger this share, the less a cache is worth and the smaller the gap to a full copy |
| The latency figures | Measured in the sister repository [FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns). They change with the environment |
| Recalculating | `make finops-write` (`python3 tools/finops_model.py --write`) |

Unit prices change. Before using the figures in this document as an estimate, check what is currently
assumed with `python3 tools/finops_model.py --show-prices` and compare it against the Price List API.

## Related documents

| Document | What it covers |
|---|---|
| [Comparison with the alternatives](alternatives.md) | Comparison on axes other than cost, and what each costs you |
| [How to choose](../decision-trees/choosing-this-architecture.md) | A flowchart for the adoption decision |
| [Limits — the collect layer](../limits/s3-access-point.md) | Size and naming limits, and what is out of scope |
| [S3 AP design guide](../limits/s3ap-design-guide.md) | Concurrency design, directory design |
| [The shape of the architecture](../../architecture.md) | What this architecture solves and does not solve |
| [Verification status](../../verification-status.md) | The definition of each stage and the current state |

---
<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/comparison/finops-s3-vs-s3ap.md) | [English](finops-s3-vs-s3ap.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
