# What to expect before measuring
<!-- lang-switcher:start -->
🌐 [日本語](../ja/performance-expectations.md) | [English](performance-expectations.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

**This page exists so that the measurement does not have to be repeated.** Every figure below was
measured in this repository, and **every figure carries the conditions that produced it** — because
whether those conditions match yours is what decides if the number transfers.

| If you want to | Read |
|---|---|
| Know what will bind in your configuration | [The kinds of ceiling](#the-kinds-of-ceiling-and-which-ones-actually-bound), below |
| Take a figure into a design | [Expectations by layer](#expectations-by-layer). **Keep the conditions column** |
| Measure it yourself | [The reproduction guide](../ja/verification/reproduction-guide.md) (Japanese) — one environment per question, with its acceptance gate |
| Know what invalidates a measurement | [Performance testing considerations](../ja/reference/performance-testing-guide.md) (Japanese) |
| Price a verification environment | [Cost structure per verification pattern](../ja/reference/comparison/finops-performance-test-patterns.md) (Japanese) |

> **No figure originates here.** Each one lives in a measurement record, linked from its row.
> **The record is authoritative and this page is an index.** Where they disagree, believe the record.

## The kinds of ceiling, and which ones actually bound

**Before comparing two throughput figures, establish which kind of ceiling each one hit.** Put two
different kinds in the same column and you get a table shaped like a comparison.

| Kind | Set by | Raised by | Example from this repository |
|---|---|---|---|
| **A ceiling you bought** | The throughput capacity specified on the file system | Specifying more (billed hourly) | Writes over the S3 API path. Adding clients does not add up: 1.01x at four |
| **The disk path** | Provisioned SSD IOPS | More IOPS ($0.0204 per IOPS-month) | A cold read on first-generation 2048: 256.47 MB/s with `DiskIopsUtilization` at 112% |
| **The HA pair** | Generation and configuration | More HA pairs | 750 MBps of write on first-generation Single-AZ |
| **Client network** | Instance type | More clients | About 500 MB/s per client against Amazon S3; eight clients scale 8.04 to 8.23x |
| **A process on the client** | vCPU | A larger client | About 450 MB/s reading Amazon S3 Files, held by `efs-proxy` CPU |
| **One flow** | Connections the protocol opens | `nconnect`, or more sessions | About 590 MB/s on a default NFS mount; `nconnect=16` gives 4.95x |
| **How much comes from cache** | Whether clients read overlapping regions | Decided by the workload, not by a setting | **5.5x on the same file system at the same connection count**: 11,916.29 against 2,173.37 MB/s |

**The last three bound most often in practice.** Before writing that you measured the storage,
**add a client.** If the total grows, what you measured was the client. **Adding threads will not
tell you** — on a saturated path throughput does not move and only latency scales: 512 to 2,048
threads moved throughput 0.07% and latency from 216.6 to 860.3 ms.

## Expectations by layer

### Collect side (writing over the S3 API)

| Configuration | Measured | What bound it | Conditions |
|---|---|---|---|
| First-generation 128 MBps | write 133.4 MB/s (**104%** of the specified value) | The throughput capacity specified | 8 MiB, concurrency 64, incompressible |
| First-generation 2048 MBps | write 415 MB/s (**55%** of the 750 HA-pair ceiling) | The HA-pair write ceiling | As above. **Where the other 45% goes is not established** |
| First-generation 128 MBps | read 579.3 MB/s (**4.5x** the specified value) | Not established | 8 MiB, concurrency 16 |
| Small objects | 279 to 605 req/s | The S3 Access Point request path | 4 KiB and 64 KiB, concurrency 64 and 256. **16x the throughput capacity and 13x the SSD IOPS do not raise it** |

**Do not size reads from a write ceiling.** The same configuration differs by 4.5x.

### Serve side (reading over NFS or SMB)

| Configuration | Measured | What bound it | Conditions |
|---|---|---|---|
| First-generation 2048, SSD IOPS 3,072 | 256.47 MB/s | **SSD IOPS** (112% utilization) | 512 GiB in one pass, 1 MiB sequential, 8 streams, `o_direct` |
| First-generation 2048, SSD IOPS 40,000 | **1,246.67 MB/s** | **Client-side settings** (disk 67%, IOPS 43%, network 43% -- none saturated) | As above, NVMe read cache disabled, **`rsize` 64 KiB and 8 threads** |
| The same, two clients on disjoint 300 GiB each | **1,901.48 MB/s** in total (982 + 920) | **The file system's disk path** (102 to 103% utilization) | 1 MiB, eight streams per client, NVMe read cache disabled |
| The same, **one client at `rsize` 1 MiB and 16 threads** | **1,646.17 MB/s** | **The file system's disk path** (**102.6%** utilization) | **One client reaches the same ceiling two did.** 1,446.66 at eight threads (77.2% utilization); flat at 1,647 to 1,649 for 32 and 64, where only the response time doubles |

> **Above 100% in those two rows is not burst.** On the first generation the denominator of that
> metric is the **specified value itself** (2,048 MB/s), so above 100% means it delivered more than
> the specified value. **This configuration publishes no burst-balance metric at all** (0 of 77
> contain `Balance`). The 203.5% on second-generation 1,536 is a ratio against a baseline of 1,536,
> so **the same metric has a different denominator per generation.** Both rows also pinned the
> server side at about 2,040 MB/s — the same ceiling — so the difference in the client-reported
> totals is not a difference in what the file system delivered
> ([measurement](../ja/verification/throughput-iops-concurrency.md#保持された-cloudwatch-で閉じた-2-点2026-09-20) (Japanese)).
| Second-generation 2048, SSD IOPS 3,072, 1 MiB transfers | 300.95 MB/s | **SSD IOPS** (103% utilization) | 512 GiB once, `rsize=wsize=1048576`, eight streams |
| Second-generation 2048, SSD IOPS 40,000, 1 MiB transfers | **1,215.06 MB/s** | **Not established** (IOPS 34%) | As above. **Sixteen times the transfer size leaves the ratio at 4.04x** |
| Second-generation 1,536 | read 2,882 MB/s for 27 minutes, then 1,439 | The network baseline, about twice the specified value | 1 MiB sequential |
| Second-generation 6,144, eight clients | same region **11,916.29** / disjoint **2,173.37** | Memory in the first case, the disk path in the second | 128 connections, working set held at 600 GiB |
| Second-generation 6,144, SMB, eight clients | same range **10,721.19** / one eighth each **4,225.31** | As above | Multichannel, four channels |
| Through FlexCache (cache 128, origin 2048) | first pass **207.53** / resident **210.59** | **The cache's own throughput step**, and it was bursting | 100 GiB in one pass, 1 MiB, eight streams |
| The same pair, reading the origin directly (control) | **1,706.67** | The origin's memory (`DiskReadBytes` was 0) | As above |

**5.5x on one file system at one connection count.** What decides it is **whether the clients read
overlapping regions**. Settle that before counting clients.

### Sustained writes (whether they decay)

| Configuration | Steady window | Against the published figure | Decay within the window |
|---|---|---|---|
| Second-generation 1,536 (NFS) | **1,333 MB/s** | **2.60x** the 512 the general rule gives | None observed |
| Second-generation 6,144 (NFS) | **2,063 / 2,097 MB/s** | **2.05x** the 1,024 in the exception table | None observed, at 900 s and at 1,800 s |
| Second-generation 6,144 (SMB) | **1,488.03 MB/s** | — | None observed, but 12.4% below the 1,698.42 of a 300 s window. **The 12.4% gap against the 300 s window's 1,698.42 does not reproduce** (re-measured 2026-09-20: the long window came out 4.0% higher, so the original pair reads as a one-off) |

**The design consequence is over-provisioning, not under.** Working backwards from the published
figure buys more throughput capacity than the measurement needs (second-generation capacity is
$2.013 per MBps-month, ap-northeast-1, retrieved 2026-09-04). **The discrepancy has been filed with
AWS; the record will be updated when there is an answer.**

### Block (iSCSI and NVMe/TCP)

| Measurement | Measured | Note |
|---|---|---|
| iSCSI, one counted TCP connection | 1,135.18 MB/s | Two connections give **the same figure**. What binds at one is not the capacity of a flow |
| iSCSI, 16 connections | 1,970.43 MB/s | Dividing required bandwidth by 625 MBps is out by 1.82x at one connection and 0.20x at 16 |
| NVMe/TCP, one I/O queue | 591.64 MB/s | — |
| NVMe/TCP, as documented | **1,288.87 to 3,407.60 MB/s** | **2.64x across three deployments. One figure cannot size this** |
| One deployment, before and after restoring layout | 1,239.15 to **2,298.54** | **1.85x.** Only small random writes break it; 300 s of sequential writes move it 0.03% |
| 4 KiB random read | About **66%** of the specified SSD IOPS | The same ratio at four points. **Sequential reads do not depend on specified IOPS** |

**The spread is on-disk layout.** After 300 s of 4 KiB random writes, each disk-side read falls from
87 to 89 KiB down to 11.7 KiB, disk IOPS rise 7.3x and saturate. **30 s does not break it; 300 s does.**

### Alternatives measured from the same host

| Path | Measured | Where it bound |
|---|---|---|
| FSx for ONTAP S3 Access Point | write 133.4 / 415 MB/s | **The throughput capacity specified**, shared across clients |
| Amazon S3 | eight clients: write 4,783.2 / read 3,992.2 MB/s | **Client network** — about 500 MB/s each, linear to eight |
| Amazon S3 Files | read about 450 MB/s | **`efs-proxy` CPU on the client.** Lack of `nconnect` support is not the cause |

**Three paths, three different places.** Which resource is the bottleneck matters more to a design
than the value of the ceiling.

## Figures that do not transfer

| Figure | Why it does not transfer |
|---|---|
| A single block sequential-read figure | **The same configuration varies 2.64x across environments** |
| Anything measured at `iorate=max` | **A saturation point is not an operating point.** The same 2,364 MB/s sits at 216 ms and at 860 ms. With a target of 4,400 IOPS: 4,406 MB/s at 8.86 ms; unbounded: 4,204 MB/s at 121.79 ms |
| A window of 300 s or less | **It contains burst.** Second-generation 1,536 held 2,882 MB/s for 27 minutes and then fell to 1,439 |
| First-generation reasoning applied to second | **The specified value means something different** — a disk baseline, with the network at roughly twice it. Carrying it over misses reads by 2x |
| FlexCache "2.31x" | **Both sides were 128 MBps.** Raising only the origin to 2048 MBps **inverts it: the origin is 8.1 times faster** (measured 2026-09-18). **The ratio comes from the pair of throughput steps, so do not cite one side of it alone** |
| A sequential write measured on Rocky Linux | **It does not match RHEL.** Medians differ by 7.0% and the spreads by an order: 29.6% against 2.1%. Reads and 4 KiB random writes do match, within 0.1% and 0.3% |
| An NFS figure used for SMB | **Not measured.** The multiplicity comes from different places: connections the client specifies against channels that get negotiated |

## What a citation has to carry

**Strip the conditions and the figure stops saying what ceiling it is.** These travel with it:

1. Generation and specified value (first-generation 128 or 2048; second-generation 1,536 or 6,144)
2. SSD capacity and provisioned IOPS (`AUTOMATIC`, or the number)
3. Whether the NVMe read cache was on (**it is on by default** on first-generation Single-AZ at 2 GBps and above)
4. Working set against the in-memory cache (if it does not exceed it, the figure is the cache)
5. Window length (300 s or less contains burst)
6. Whether a target rate was given, or `iorate=max`
7. Concurrency, connection count, `nconnect`, channel count
8. Whether the payload was incompressible (all-zero blocks never reach disk and return at 4x the ceiling)
9. **The ONTAP release** (`FileSystemTypeVersion` is null for FSx for ONTAP; read it from the cluster API)

**The ninth went unrecorded twice in a row here**, so
`environments/perf-matrix/runbook.sh preflight` now reads it and refuses to continue without it.

## Still unexplained

**"Not measured" or "not explained", never "cannot be done".**

| Item | State |
|---|---|
| The ceiling near 1,250 MB/s at 40,000 IOPS | **Identified (2026-09-19/20): not a resource, two settings.** `rsize` at 64 KiB (+21% once raised to 1 MiB) and a concurrency of eight (+14% at sixteen, flat after). **What saturates past them is the file system side** (102.6% utilization, i.e. 102.6% of the specified 2,048), and **one client reaches the same ceiling two did.** There is no saturated client-side device |
| ~~Server-side counters against the client-side tool~~ | **Closed (2026-09-20). It was a measurement-method finding.** Start the window on a minute boundary and compare only the whole minutes wholly inside it, and **the two agree to within 0.2%** (271.04 against 271.57; 326.70 against 326.07). The 19% came from taking, as the server-side figure, minutes that carried load for only part of their 60 seconds. Nothing on the product side needs restating. [Evidence](../ja/verification/throughput-iops-concurrency.md#窓を分境界に合わせた-2-系統の比較2026-09-20) (Japanese) |
| About 300 MB/s on first-generation 128 | Neither the disk nor the network burst ceiling is reached, and the burst balance is not exhausted |
| Why first-generation 2048 writes stop at 55% of the HA-pair ceiling | Two candidates (writes consuming twice the network, per-request fixed cost) are not separated |
| Why the block amplification splits between 0.8 and 1.5 | Neither layout nor write history. **One remaining candidate, the ONTAP patch release, cannot be selected on FSx for ONTAP, so no controlled experiment is available** |
| The 12.4% between SMB at 300 s and at 900 s | **The window ladder was run, but on the single-channel path** (2026-09-18, flat to 0.07%). **The four-channel path, where the gap appeared, is unmeasured.** The remaining candidate is that the channel count fell during the run, which is a hypothesis |

Stages and the full list are in [verification status](verification-status.md).

## Related documents

- [The reproduction guide](../ja/verification/reproduction-guide.md) (Japanese) — environment, parameters, gate and cost per question
- [Performance testing considerations](../ja/reference/performance-testing-guide.md) (Japanese) — defaults to change, and what starts mattering once a run is going
- [Verification status](verification-status.md) — the stage of every claim
- [Cost structure per verification pattern](../ja/reference/comparison/finops-performance-test-patterns.md) (Japanese)
- [The measurement environment](../../environments/perf-matrix/README.md) (Japanese) — the fourteen steps and why they are in that order

<!-- lang-switcher:start -->
🌐 [日本語](../ja/performance-expectations.md) | [English](performance-expectations.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
