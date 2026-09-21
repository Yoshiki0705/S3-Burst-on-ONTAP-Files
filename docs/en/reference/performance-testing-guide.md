# Considerations when measuring file and object storage performance on AWS

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/performance-testing-guide.md) | [English](performance-testing-guide.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Collects, in one place, what to check before measuring Amazon EFS, Amazon S3, Amazon S3 Files, and
Amazon FSx for NetApp ONTAP (hereafter FSx for ONTAP). **Almost every figure withdrawn from a past
measurement traced back to one of the items listed here.**

This document is meant to be read before measuring; it does not contain measurement results.
Results are reached from [verification status](../verification-status.md).

## Three tables to read first

### 1. There is more than one ceiling

**Before "fast or slow," settle which ceiling you are hitting.** The kind of ceiling differs by
service, and the same MB/s means something different depending on which one it is.

> **Knowing where you are hitting decides what to do about it.** The table below lists the kinds
> of ceiling; the procedure for narrowing down which one a measured figure hit is separate.
> Because **the right move is the opposite depending on which ceiling you hit**, **split the two
> client-side ceilings from the two file-system-side ceilings first**
> ([triaging a measured throughput figure](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/reference/decision-trees/measured-throughput-triage.md#結論)
> (Japanese)). This section enumerates the kinds of ceiling; it does not carry the triage decision
> tree.

| Service | What the ceiling is | How to raise it |
|---|---|---|
| FSx for ONTAP | **The minimum** of the provisioned throughput capacity, the disk throughput coming off the SSD, and the ceiling per HA pair | Raise the provisioned value, raise SSD IOPS, change generation |
| Amazon EFS | A file-system-wide ceiling (set by throughput mode) and a **per-client ceiling** | Change mode, add clients, change how it's mounted |
| Amazon S3 | The service side is elastic. In practice the ceiling is the **client-side bandwidth** and the request rate per prefix | Add clients, split prefixes |
| Amazon S3 Files | The CPU of the proxy process on the client | Use a larger client |

### 2. A separate ceiling reachable from a single client

**You can hit a client-side ceiling before reaching the service-side one.** Miss this and what
you measured stops being the service's performance.

| Item | Value | Source |
|---|---|---|
| Per EC2 network flow | Full duplex **5 Gbps** | [Amazon EC2 instance network bandwidth](https://docs.aws.amazon.com/ec2/latest/instancetypes/ec2-instance-network-bandwidth.html) |
| TCP connections for Linux NFS | **One per server** by default. Up to 16 with `nconnect` | [FSx for ONTAP performance](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html) |
| Per EFS client | **1,500 MiBps** (Elastic, with `amazon-efs-utils` 2.0+ or the EFS CSI driver). **500 MiBps otherwise** | [Amazon EFS quotas](https://docs.aws.amazon.com/efs/latest/ug/limits.html) |
| EFS `nconnect` | **Not supported** | [Using NFS to mount EFS](https://docs.aws.amazon.com/efs/latest/ug/mounting-fs-old.html) |

> **Measuring EFS with a plain `mount -t nfs` caps out at 500 MiBps.** Whether you use the mount
> helper changes the per-client ceiling by 3x. **Record which one you mounted with, before
> measuring.**

**Pick an instance type whose bandwidth is not listed as "Up to."** With an "Up to 25 Gbps"
figure, hitting a plateau doesn't tell you whether it's the service side or the client side.

### 3. Settings to change from default before measuring

**Every one of these measures fine left at default, and the number that comes back doesn't look
unnatural.**

| Item | Left at default | Fix |
|---|---|---|
| TCP connections for Linux NFS | Plateaus around 590 MB/s. Doesn't respond to stream count | `nconnect=16` (not available on EFS) |
| Data from `dd if=/dev/zero` | Zero blocks never reach disk; comes back at 4x the published ceiling | Incompressible data (from `/dev/urandom`) |
| Inline efficiency on the volume | Compressible data gets collapsed | Turn off **before writing data** |
| `DiskIopsConfiguration: AUTOMATIC` | IOPS-limited at 3 IOPS/GiB | `USER_PROVISIONED` |
| Reading just past the read cache | The fraction served from cache dominates; you aren't measuring the disk path | See the section below |
| Specified `rsize` / `wsize` | Requesting 1048576 can silently settle at 65536 | Confirm the **effective value** via `/proc/mounts` |
| **Window length** (e.g. 5 minutes) | **Measures while burst capacity remains. Measured 2.0x too high** | Run until the balance is exhausted ([measured](../../ja/verification/throughput-capacity-burst-and-baseline.md) (Japanese)) |
| **Elapsed time since the last write** | Contends with delayed write-back, **reads 20% low for about 90 seconds** | Leave a 2+ minute gap. Build the wait into the parameter file |

## What only bites once the run is underway

**The three tables above can be checked before starting. This section assumes every pre-start
check has passed, and covers what breaks a run already in progress.** All of these were hit in
the [measurement records](../../ja/verification/perf-matrix-results.md) (Japanese), and **every one of
them is documented.** Behaving differently from what you expected doesn't mean the behavior is
undocumented.

### Capacity held by automated backups

**A backup first takes a volume snapshot, that snapshot sits inside the volume and consumes
capacity, and it stays there until the next backup**
([Protecting your data with volume backups](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-backups.html)).
For overwrite-heavy workloads, **the blocks from before the overwrite are retained, so what you
wrote becomes capacity as written.** Further, **data deleted from the active file system is not
freed as long as a snapshot still references it**
([why a snapshot consumes free space](https://repost.aws/knowledge-center/fsx-ontap-correct-snapshot-spill)).
`rm`-ing a measurement file does not return the space.

> **Checking `snapshot-policy` and the snapshot count before starting doesn't prevent this.**
> Both read as normal before the run. **The snapshot doesn't exist yet.** If the template doesn't
> set a retention configuration, the default applies. **"Not written" is not "disabled."**

There is a documented mechanism on the reclaim side too. `volume autosize` (`grow` /
`grow_shrink`) and snapshot autodelete work together, and `-space-mgmt-try-first` decides which is
tried first
([What is volume autosize in Data ONTAP?](https://kb.netapp.com/on-prem/ontap/Ontap_OS/OS-KBs/What_is_volume_autosize_in_Data_ONTAP)).
**The default is `autosize_mode: off` with autodelete unconfigured, so neither comes to help.**

### Write throughput collapsing as utilization rises

**Writes drop off once the volume fills up, with the same settings and the same workload.**
Measured, utilization went from 88% to 100% (9.9 GiB free), and throughput went from
**2,200 MB/s to 267 MB/s** (1/8th) (ap-northeast-1, second-generation Single-AZ, 6,144 MBps /
200,000 IOPS provisioned, 4,096 GiB SSD, overwrite-heavy sequential writes. Conditions and
timeline in the [measurement records](../../ja/verification/perf-matrix-results.md) (Japanese)).

**A design that doesn't record utilization during a measurement ships this collapse as a
"performance result."** Sample utilization at the same cadence as throughput, and **if the
utilization at a dropped point can't be explained, discard that point.**

**Size capacity against bytes overwritten, not file size.** For a 15-minute window, the amount
that can be retained is effective throughput x 15 minutes.

### Cache control that only works by splitting the working set

![The two ceilings a read can hit](../../_assets/images/s3burst-two-ceilings.svg)

**There is more than one ceiling — two — and which one you hit is decided by the workload.** On
the same file server, a read served from cache heads toward the network-path ceiling, while a read
for data not in cache heads toward the disk-path ceiling. **Whether your threads' working set
overlaps decides which one you measured.**

| Where the read is served from | Ceiling type | Condition to approach it |
|---|---|---|
| In-memory + NVMe read cache | Network path | **Overlap** the region threads read |
| SSD storage | Disk path (provisioned IOPS) | **Don't overlap** the region threads read |

**"Where you read from" moves read throughput more than the provisioned value or the client
count.** On the same file system, the same workload shape, and the same connection count (8 hosts
x 128 connections), **sharing the same file measured 11,916.29 MB/s, and non-overlapping regions
measured 2,173.37 MB/s** — a **5.5x** spread
([measurement records](../../ja/verification/perf-matrix-results.md) (Japanese)). This is because the
fraction served from the file server's two cache layers (in-memory and NVMe) dominates, and **SSD
IOPS is used only when a read hits neither cache**, as documented
([Performance](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)).

**The only way to control the fraction served from cache is splitting the working set on the
workload side.** No setting to disable the cache, or to specify its size, is published
(**unconfirmed** — meaning I haven't found documentation of one, not that none exists). So:

- To **measure the disk path**, assign each thread a **non-overlapping** region
- To **measure the cache path**, **deliberately share** the same region
- **Record which one you measured.** A figure without that record can't be compared

> **Avoid pointing multiple streams at the same file.** VDBENCH formats per SD, and that claims
> capacity you didn't intend. Use a separate file per region.

### Cross-checking by working backward from the multiplier

**Confirm the client-reported total against what actually crossed the wire, separately.**
Measured, taking the diff of the file server's cumulative port counter (`nic_common`'s
`transmit_bytes`) against a client-reported total of 11,916.29 MB/s produced
**12,173.0 MiB/s = 102 Gbps**.

**Don't use the instantaneous counter.** In the same environment, `transmit_bytes_per_sec`
returned 0 even while traffic was actually flowing. **Take the diff of the cumulative value.**

This cross-check was the only path to catching a wrong assumption about where the ceiling sat.
**The hypothesis that a single LIF was the ceiling was disproved by this 102 Gbps.**

### Small random writes disturbing the layout on disk

**A sequential read's figure moves by 1.8x depending on what was written right before it.**
Measured on the same deployment, the same device.

| What happened right before | 1 MiB sequential read |
|---|---|
| Right after fill / three more sequential reads | 2,263.8-2,268.4 MB/s (0.2% spread) |
| **30 minutes idle** | 2,258.5 MB/s (**unchanged**) |
| **300 seconds of sequential writes** | 2,365.59 MB/s (**unchanged**) |
| 4 KiB random writes for **30 seconds** | 2,343.63 MB/s (-0.9%) |
| **4 KiB random writes for 300 seconds** | **546.02-1,272.8 MB/s (-77%)** |
| Refilled sequentially afterward | 2,364.18 MB/s (**fully recovers**) |

**Reads don't break it, idle time doesn't break it, sequential writes don't break it. Only small,
random writes break it.** The mechanism is **the layout on disk** — a single disk-side read drops
from 87-89 KiB to 11.7 KiB (1/7.5th), and disk IOPS rises 7.3x, saturating at 89-95% of the
provisioned value. **`DiskReadBytes ÷ DataReadBytes` is around 100%, so even the fast side is
reading from disk** — it wasn't still in cache
([measurement](../../ja/verification/perf-matrix-results.md#配置が崩れるとディスク側の-1-回が-75-分の-1-になること) (Japanese)).

- **Record whether small random writes ran right before the read** (see the table above). Without
  that, no number of reads or 30 minutes idle moves it; with it, it moves 1.8x
- **The threshold sits somewhere between 30 and 300 seconds; exactly where is unknown**
- **4 KiB random reads are unaffected.** Whatever the layout, it's still a single disk-side read

Which metrics are available on the block side — no LUN dimension and no protocol dimension — is
covered on the
[playbook side](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/block-storage/notes/what-block-monitoring-shows.md#実測した次元とメトリクス)
(Japanese).

### The four CloudWatch metrics to check first

**`DiskIopsUtilization` alone doesn't get you there.** It tells you whether you're saturated, but
not **why** (because a single read is small). To isolate the layout disturbance above, take these
four.

| Metric | What it answers |
|---|---|
| `DataReadBytes` | Bytes of read the client requested |
| `DataReadOperations` | Count of reads the client requested |
| `DiskReadBytes` | Bytes actually read on the disk side |
| `DiskReadOperations` | Count actually read on the disk side |

`DiskReadBytes ÷ DataReadBytes` near 100% means it's reading from disk (not cache). The larger the
ratio of `DiskReadOperations` to `DataReadOperations`, the more a single request is being split
into on the disk side — in this article's example it rose 7.3x, and that was the cause of the
saturation.

## FSx for ONTAP — the two-tier read cache

**The file server has two tiers of read cache, in-memory and NVMe**
([Performance](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)). And **SSD
IOPS is used only when a read hits neither cache**, as documented. Miss this and you can't measure
the effect of raising SSD IOPS.

What's published differs by tier for ap-northeast-1 (first-generation Single-AZ).

| Tier | At 2048 MBps provisioned | Source |
|---|---|---|
| In-memory | **256 GB** | The performance spec's "other regions" table |
| NVMe read cache | **Not listed** | No column in that table. The four regions that have a column show 1,900 GB at the same 2048 MBps |

The NVMe side only has its conditions in a separate section. **Attached to Single-AZ 1 created on
or after 2022-11-28 with a provisioned throughput capacity of 2 GBps or more.** On the actual
system, confirmable via `system node external-cache`.

**There are two ways to measure the disk path.**

| Method | What it needs | Cost |
|---|---|---|
| Read more than the two tiers combined in one pass | If NVMe is worth 1,900 GB, that's roughly 4 TB scale reads. SSD capacity needs to be at least that much too | SSD capacity cost grows |
| Disable the NVMe cache and measure | `external-cache modify -is-enabled false` | The 256 GB in-memory tier remains, so you still need to read more than 2x that |

## FSx for ONTAP — how the ceiling differs by generation

**First-generation Single-AZ has one HA pair, and the write ceiling is set there.** Raising the
provisioned value doesn't move it.

| Item | First-generation Single-AZ (ap-northeast-1) | Second-generation Single-AZ |
|---|---|---|
| HA pairs | 1 | **Up to 12** |
| Read ceiling (per HA pair) | 2,048 MBps | **6,144 MBps** |
| Write ceiling (per HA pair) | **750 MBps** | **1,024 MBps** |
| How writes work | The fixed value above | The full provisioned read value; writes run at roughly 1/3 |

Source: [Performance](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html).

> **This verification is done on first generation.** Chosen for general cost fit.
> **But on first generation, 750 MBps of writes is the ceiling, and no amount of raising the
> provisioned value moves it.** For a workload that needs write throughput beyond that, or that
> needs several GB/s of aggregate throughput from a single file system, **second generation can
> reach further than first generation can.** Because up to 12 HA pairs can be lined up, **cost per
> unit of performance can favor second generation** as the required performance rises (there's a
> range first generation can't reach at all, where the two aren't comparable to begin with). If
> the requirement exceeds 750 MBps of writes, decide the generation from the performance
> requirement, not the other way around.

## Amazon EFS — a ceiling that shifts with mode, and Tokyo's inclusion in the higher tier

**There are three modes — Elastic, Provisioned, and Bursting — and the ceiling is set by mode and
region** ([Amazon EFS quotas](https://docs.aws.amazon.com/efs/latest/ug/limits.html)).
**ap-northeast-1 is in Elastic's higher tier.**

| Mode | ap-northeast-1 read | Same, write |
|---|---|---|
| **Elastic** | **60 GiBps** | **5 GiBps** |
| Provisioned | 3 GiBps | 1 GiBps |
| Bursting | 3 GiBps | 1 GiBps |

> **If you're after maximum performance, it's Elastic.** Provisioned only means "you can specify
> it" — Tokyo's ceiling there is 1/20th of Elastic. **Guessing performance from the mode's name
> misleads you.**

Two conversions are needed.

- **Reads are metered at 1:3.** The "60 GiBps" above is post-metering, and reads are counted more
  cheaply than other operations. Reads and writes are designed to sum to 100%, so using 33% on
  reads leaves only 67% for writes.
- **The file-system-wide ceiling and the per-client ceiling are different things.** Reaching
  60 GiBps needs multiple clients side by side. A single client caps at the 1,500 MiBps (or
  500 MiBps) noted above.

Mount options to avoid are documented. **`noac` / `actimeo=0` / `lookupcache=none` carry a large
performance impact**
([EFS performance tips](https://docs.aws.amazon.com/efs/latest/ug/performance-tips.html)). Don't
put a throughput measurement taken with `actimeo=0` — intended to measure propagation speed — in
the same table as a throughput result.

## Amazon S3 — prefixes and client count

**The service side is elastic; the figure a single host sees is the client-side ceiling.**

| Item | Value | Source |
|---|---|---|
| Request rate | **3,500 PUT/COPY/POST/DELETE**, **5,500 GET/HEAD** per second, per prefix | [Performance design patterns for Amazon S3](https://docs.aws.amazon.com/AmazonS3/latest/userguide/optimizing-performance-design-patterns.html) |
| Prefix count | No limit | Same |
| How it scales | Automatic but **gradual**. **HTTP 503 (Slow Down)** returns in the meantime | Same |

What this affects in measurement design.

- **Record whether prefixes were split.** Using a separate prefix per host means you never tested
  the per-prefix ceiling. **That changes what "throughput scaled linearly" means.**
- **Always record the count of 503s.** A nonzero count means you measured mid-scale-up.
- **Don't measure with retries left enabled.** If 503s are retried transparently, throughput drops
  but nothing surfaces as an error.

## Amazon S3 Files — a client-side process sitting in the path

**The mount target is `127.0.0.1`, connecting to a transfer process on the client (`efs-proxy`).**
That's why the plateau can be that process's CPU on the client.

| Item | Value | Source |
|---|---|---|
| `nconnect` | **Not supported** | [Unsupported features, limits, and quotas](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-quotas.html) |
| NFS version | NFSv4.1 / 4.2 (some 4.2 features unsupported) | Same |
| Bucket -> file propagation | Usually a few seconds. Up to 2,400 objects/sec, 700 MB/s | [Performance specifications](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-files-performance.html) |
| File -> bucket propagation | Batched roughly every 60 seconds. Up to 800 files/sec, 2,700 MB/s | Same |

**What `nconnect` increases is the connection count between the client and the proxy.** If the
plateau is the proxy's own CPU, supporting it doesn't help you reach further. **Attach a
`timeout` when trying an unsupported mount option.** It can hang and lose the measurement.

## Combinations measurable per protocol

**Check feasibility first.** An unsupported combination fails before measurement even starts.
Details in
[protocol feasibility](../../ja/verification/protocol-matrix-efs-vs-ontap.md) (Japanese).

| Protocol | Amazon EFS | FSx for ONTAP |
|---|---|---|
| SMB | Not supported | Supported (2.0 / 3.0 / 3.1.1) |
| NFSv3 | Not supported | Supported |
| NFSv4.0 / NFSv4.1 | **Supported** | **Supported** |
| NFSv4.2 | Not supported | Supported |

**The only pair that can share the same row is NFSv4.0 and NFSv4.1.**

### Extra prerequisites that appear only when measuring SMB

**SMB isn't just about the measurement tool and the client OS.** Three more things are needed.

| Prerequisite | Why |
|---|---|
| Active Directory | The SVM can't serve SMB without joining it |
| A Windows client | EFS can't be mounted from Windows, so the SMB row is FSx for ONTAP only |
| Reachability to a domain controller | A joined SVM needs to reach a controller on file access |

**Joining AD changes the character of the measured figures.** On an SVM with CIFS enabled, ONTAP
performs a win-to-unix name-mapping lookup for some file system operations, and that lookup
requires a reachable controller.

- **Joining the SVM used for NFS to AD puts that step in the NFS measurement's path too.** If
  measuring both SMB and NFS, **use separate SVMs.** The two share throughput capacity, so
  **don't measure them at the same time.**
- **The controller doesn't sit on the data path.** No bytes cross it. **It sits on the
  authentication and name-mapping path**, so if the controller is in a different AZ, that latency
  can end up inside the SMB figure.
- **Measuring as a member of `Domain Admins` bypasses part of the permission evaluation.** If a
  representative figure is needed, measure as a non-privileged account.
- **Record the volume's security style.** It changes which permission model is consulted.

## Choosing a measurement tool, and boundaries not to mix

| Target | Tool | Unit returned |
|---|---|---|
| NFS / SMB | [auto_vdbench](https://github.com/shuichi-taketani/auto_vdbench) (drives Oracle VDBENCH) | IOPS, latency, throughput |
| S3 API | `scripts/measure_s3_throughput.py` | Throughput, req/s, p50 |
| Actual I/O on the storage side | ONTAP volume counters | ops/s, average size and service time per I/O |
| Node CPU, disk reachability | Amazon CloudWatch (`AWS/FSx`) <!-- allow:naming this is the CloudWatch namespace name itself --> | Utilization, `DiskReadBytes` ÷ `DataReadBytes` |
| **Block (raw device / NVMe namespace)** | **VDBENCH directly** (auto_vdbench can't be used) | IOPS, throughput |

**auto_vdbench doesn't generate S3 API workload.** VDBENCH runs against a mount path. When putting
two figures side by side, **write down that the tools differ.** VDBENCH's IOPS and S3's req/s
aren't counting the same thing.

**auto_vdbench can't drive block either.** It's built to create test files under `testfile_dir`,
so **it can't be pointed at a raw device or an NVMe namespace.** As a result, **the block side has
no curve swept across target IOPS and no cutoff — every run is a single `iorate=max` point**
([limits of the block-side records](../../ja/verification/perf-matrix-results.md#測定条件上の共通条件からの差分) (Japanese)). The condition for putting a block figure in the same table as a file-protocol figure
is on the
[playbook side](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/performance/notes/a-single-connection-measures-the-client.md#ブロックの値をこの表に並べる条件)
(Japanese).

### Don't put a target-IOPS point and an `iorate=max` point in the same column

**Even with the same tool, different ways of applying load are different quantities.** A point
measured against a target IOPS and a point run flat-out at the ceiling can have **similar
throughput and an order-of-magnitude difference in response time.**

| How it was run | Throughput | Response time |
|---|---|---|
| Target 4,400 IOPS | **4,406 MB/s** | **8.86 ms** |
| Unbounded (`iorate=max`) | 4,204 MB/s | **121.79 ms** |

**The unbounded run is 5% lower in throughput and 14x in response time**
([measured](../../ja/verification/perf-matrix-results.md#fsx-for-ontap-第二世代nconnect16auto_vdbench目標値を振った系列) (Japanese)). **Recording a single `iorate=max` point as "the ceiling" leaves a number lower than
what's reachable, with response time an order of magnitude worse.**

**And throughput alone doesn't tell you where on the saturation curve you are.** The same
2,364 MB/s appears at 216.6 ms with 512 threads and 860.3 ms with 2,048 threads — throughput moves
only 0.07%
([measured](../../ja/verification/perf-matrix-results.md#1-台のクライアントの上限が同時実行数でないこと) (Japanese)). **If measuring at saturation, always report response time alongside it.** With
concurrency fixed, `concurrency ÷ IOPS` becomes an identity, but **that's a derived value, not a
measurement.**

**Client-side measurement and storage-side counters are looking at different things.** Counting
differs by protocol, so compare paths using the same counter on the storage side.

## What to always record alongside a measurement

**Missing any one of these makes the result unreproducible.**

- Date, region, AZ
- File system generation, deployment type, provisioned throughput capacity, SSD capacity, SSD IOPS
  setting
- EFS throughput mode, and the client used to mount (plain `mount` or the helper)
- Protocol and version, **the effective mount options** (not the specified ones)
- Nature of the test data (incompressible, or compressible)
- Block size / object size, concurrency, measurement duration
- **How load was applied** (target IOPS, or `iorate=max`), and **that point's response time**
  (above)
- **Whether small random writes ran right before the read** (see "layout on disk" below)
- Repeat count, and reproducibility under the same condition
- Count of 503s / errors
- Cache state (NVMe enabled or disabled, ratio of bytes read to cache size)
- Whether another SVM on the same file system was active (capacity is shared)
- For SMB: dialect, the account used to mount, the volume's security style, the domain
  controller's AZ
- **Burst credit balance** (below)

### Burst credit balance, and what happens if you don't record it

**This item was missing from my own measurements.** The list above enumerates conditions of the
target being measured, but **how much credit the file system held at that moment is a state, not
a condition.**

> **A measurement with no recorded balance doesn't reproduce.** Run a short test with credit
> banked and you get burst performance; run the same test after it's exhausted and you get
> baseline performance. **The same procedure returns different numbers**
> ([how burst and credits break a benchmark](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/performance/notes/what-you-cannot-read-from-cloudwatch.md#ベンチマークを壊すバーストとクレジット)
> (Japanese), documented).

**The balance is readable via `FileServerDiskThroughputBalance` and `FileServerDiskIopsBalance`.**
Unlike other metrics, these two are published at a **5-minute interval** (same source).

**I did not directly watch the balance for the 128 MBps configuration**
(recorded as unmeasured in [verification status](../verification-status.md)). The same
configuration's read converging on 297-317 MB/s for both warm and cold is consistent with hitting a
burst plateau, but **consistency is not a recorded balance.**

#### Watched directly at second-generation 1,536 MBps

**Measured on 2026-09-10 while tracking the balance.** This is exactly what this section asks for
([measured](../../ja/verification/throughput-capacity-burst-and-baseline.md) (Japanese)).

| Observation | Value |
|---|---|
| 1 MiB sequential read, starting from a full balance | **2,882 MB/s for 27 minutes 10 seconds** |
| The instant the balance was exhausted | **A single 10-second interval, dropping to 1,439 MB/s** (not a gradual slide) |
| `FileServerDiskThroughputBalance` | 99% -> 0% over 27 minutes. **The point it hit 0 matches the client-side step down** |
| Recovery while idle | **About 17 points per 5 minutes, roughly 30 minutes to full** |
| Re-measured 600 seconds with the balance exhausted | 1,439 MB/s (0.35% spread) |

**A 5-minute measurement comes back 2.0x too high.** And **`FileServerDiskThroughputUtilization`
is a ratio against baseline, so it exceeds 100%** (median during burst: 203.5%). **Over 100% is the
file system's own evidence that it's in a burst.**

**A configuration where no such balance exists publishes zero data points for this metric.**
Second-generation Single-AZ only has a disk burst at 1,536 or below; at 6,144,
`FileServerDiskThroughputBalance` comes back empty. **Not zero — absent.** The NVMe read cache is
the same shape: at 1,536, `system/node/external-cache` returns zero records (not
`is_enabled: false`); at 6,144, it returns two records, enabled by default.

> **Recording the balance isn't for adding one more number — it's for determining which ceiling
> was hit.** At 1,536, the network baseline and disk burst were both 3,125 MB/s, and **during the
> burst, `NetworkThroughputUtilization` at 98% and `DiskReadBytes` at 3,125 MB/s both looked like
> ceilings at once, undecidable.** That the post-exhaustion 1,439 was 93.7% of the disk baseline of
> 1,536 is what put the bottleneck on the disk side.

**And latency, from the storage-side metrics, is only ever an average.** Volume latency is
published as total time over total operation count, and Sum is the only valid statistic, so
dividing it **structurally produces the average over that period.**
[If p99 is needed, it has to be measured on the client side](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/ja/domains/performance/notes/what-you-cannot-read-from-cloudwatch.md#結論)
(documented, Japanese). **If p50 / p99 appears in the list above, note which side it was measured
on.**

## Items hit and withdrawn from past measurements

**A list to avoid repeating.** Details in
[measured throughput, IOPS, and concurrency](../../ja/verification/throughput-iops-concurrency.md) (Japanese).

| What was hit | What happened |
|---|---|
| Zero-filled data | Reads came back at 4x the published ceiling; the warm/cold difference and the FlexCache comparison both broke |
| Estimating cache size | At 280 GiB, only 18% over the 256 GB in-memory tier, 98.5-99.9% still wasn't going to disk |
| Matching a provisioned value | A reading of "99.7% of provisioned" moved 30% on a different day; the match was coincidence |
| Comparing paths with compressible data | Comparing two figures that had collapsed differently. Re-measuring with the same volume counter changed the gap from 35% to 41% |
| A single-host ceiling | About 500 MB/s was read as S3's ceiling; it was the client's own ceiling |
| **Measuring in a short window** | A 150-second window on the 1,536 MBps configuration reproduced 2,882 MB/s twice. **What reproduced was the value during a burst** — 27 minutes later it was 1,439 MB/s |
| **Reading right after fill** | A read started 1 second after fill finished came back 20% low for 90 seconds, and disagreed **39%** with the same shape started 2 minutes 31 seconds later |
| **Comparing configurations across time** | Measured four configurations in sequence and wrote "1.73x from the policy." Elapsed time, which wasn't meant to change, changed too. **When comparing configuration A against configuration B, match the elapsed time from write to read** |
| **Watching only `DiskIopsUtilization`** | Read 82% as "close to the ceiling." **Wrote that without knowing what saturation looks like** (it actually saturates at 89-98%). The relationship to the ceiling only emerges from taking all four metrics |

### Three disproved hypotheses (each survived until a control experiment was run)

**Plausibility is not evidence.** In the block measurements, three explanations were proposed in
turn and disproved in turn.

| Hypothesis proposed | What disproved it |
|---|---|
| "If it exceeds the provisioned value, it must be returning from memory" | `DiskReadBytes ÷ DataReadBytes` was 104-181% across all five deployments. **Every one was reading from disk** |
| "The layout on disk also determines the amplification for 4 KiB random reads" | Amplification stayed at 190-208% even right after refilling sequentially restored the 88 KiB layout |
| "Whether 4 KiB random writes ever ran on that device determines the amplification" | **All five observations followed it, without exception.** Measuring from right after a fresh fill — with no history at all — already produced the same value |

**The third was the heaviest.** It survived until a control experiment was run, was mechanistically
plausible, and was wrong. **When writing "all n cases followed it" as evidence, also check how many
un-varied variables happened to line up in the same direction** (in these five, the ONTAP patch
version and the client also happened to line up).

**The same check is needed before using concurrency to explain a ceiling.** The block sequential
read moved 0.07% at 4x the thread count; the NFS 4 KiB random read moved only 2.2%. **The identity
`concurrency ÷ response time = measured IOPS` is Little's law, not a cause.**

## Related documents

| Document | Content |
|---|---|
| [Protocol feasibility](../../ja/verification/protocol-matrix-efs-vs-ontap.md) (Japanese) | Which combinations can be mounted |
| [Per-protocol throughput measurement plan](../../ja/verification/throughput-protocol-matrix-plan.md) (Japanese) | Measurement patterns and the environment each needs |
| [Measured throughput, IOPS, and concurrency](../../ja/verification/throughput-iops-concurrency.md) (Japanese) | Existing measurements, and their limits |
| [Measured provisioned value, burst, and baseline](../../ja/verification/throughput-capacity-burst-and-baseline.md) (Japanese) | **The provisioned value is not a read ceiling.** Burst capacity lasting 27 minutes and recovering in 30, and a 2.0x swing from window length |
| [Comparing S3 Files against this architecture](../../ja/verification/s3files-vs-flexcache.md) (Japanese) | Where the design points differ |
| [Performance terms, Japanese-English](../../ja/reference/glossary/performance-terms-ja-en.md) (Japanese) | Terms for ceiling types and measurement conditions |
| [Verification status](../verification-status.md) | The stage each claim is at |

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/reference/performance-testing-guide.md) | [English](performance-testing-guide.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
