# S3 Access Point — design guide (the collect layer in detail)

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/limits/s3ap-design-guide.md) | [English](s3ap-design-guide.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

<!-- Source: the design considerations, compatibility notes and performance considerations of the
     sibling repository FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns, reorganised for this architecture's point of
     view. https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns -->

This covers the detail worth knowing when designing this architecture's collect layer (the S3 Access
Point). The limits are on [a separate page](s3-access-point.md); the architecture as a whole is in
[Architecture](../../architecture.md).

## Supported S3 operations

The FSx for ONTAP S3 AP supports a subset of the S3 API. It is not identical to Amazon S3 ([compatibility table](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)).

### Confirmed working

| Operation | Note |
|---|---|
| GetObject | Range GET supported. No size limit on download |
| PutObject | A single PUT is up to 5 GiB |
| ListObjectsV2 | Prefix / Delimiter / MaxKeys supported |
| HeadObject | — |
| DeleteObject | — |
| MultipartUpload | CreateMultipartUpload / UploadPart / CompleteMultipartUpload |
| CopyObject | Within the same AP and the same Region only. The `x-amz-object-annotation-directive` header is not supported ([compatibility table](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)) |

### Not supported (an error is returned)

| Operation | Returns | Alternative |
|---|---|---|
| Conditional writes (If-None-Match) | 501 NotImplemented | Mutual exclusion in the application |
| S3 Annotations (PutObjectAnnotation and similar) | 501 NotImplemented | Write to a standard S3 bucket and annotate there |

### Supported with conditions

| Operation | Condition | State in this repository |
|---|---|---|
| UploadPartCopy | The compatibility table states same-AP, same-Region only | **Measured with a source inside the same access point, it returns `NoSuchKey`** ([measurement record](../../../ja/verification/s3ap-operations.md) (Japanese), 2026-08-19). **`CopyObject` given the identical `CopySource` succeeds in the same run**, which is the control. The measurement runs opposite to the table. Whether `UploadPartCopy` is unsupported outright **cannot be decided here**: no other source namespace copies successfully on this endpoint, since a source in a different access point is refused for `CopyObject` too. The earlier single observation of `404 NoSuchKey` for a source outside the access point **does not fit, because a different access point yields `InvalidArgument`** |

### Features that do not exist

| Feature | Alternative |
|---|---|
| S3 Event Notification | Polling, or the ONTAP native audit log. **FPolicy + EventBridge is not a substitute** (see below) |
| Lifecycle rules | FabricPool / ONTAP tiering policy |
| Versioning | ONTAP Snapshot |
| Object Lock / WORM | SnapLock Compliance / Enterprise |
| S3 Select | Athena + Glue Data Catalog |
| SSE-S3 / SSE-KMS | NAE / NVE (ONTAP volume encryption) |
| Cross-AP Copy | DataSync / rsync |

### Presigned URL

**The compatibility table currently states `Presign — Not supported`** ([compatibility table](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)).

At the same time, presigning is a client-side signature computation, not an API call to the server.
The URL it produces executes an ordinary `GetObject`, with the signature in query parameters instead
of the Authorization header. Since `GetObject` is supported, presigned URL access cannot be blocked
without breaking `GetObject` itself. A sibling repository has measured a presigned `GetObject`
succeeding (ONTAP 9.18.1P3D1). The version-dependent scope is stated in NetApp KB articles (v4 from
9.11.1, v2 and v4 from 9.16.1). The mechanism, the version requirements and a list of alternatives
are in the [sibling repository's compatibility notes](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/s3ap-compatibility-notes.md).

**While the public documentation says `Not supported`, do not let a production workload depend on
it.** The behaviour can change without a deprecation notice. Where time-limited access is needed,
design for API Gateway plus Lambda, CloudFront signed URLs, or temporary STS credentials. What has
**`PutObject` and `HeadObject` have now been measured too** ([measurement record](../../../ja/verification/s3ap-operations.md) (Japanese),
2026-08-19). All three succeed, under SigV4 and under SigV2, which agrees with the
NetApp KB version scope above. **The guidance not to depend on it while the table says
`Not supported` is unchanged**: that it works is not a guarantee that it will keep working without a
deprecation notice.

**SigV2 includes Content-Type in the string to sign**, so a header the client adds on its own
invalidates the signature; SigV4 signs only `host` by default and is unaffected. With boto3 the
signature version has to be set explicitly — `generate_presigned_url` emits SigV2 otherwise, and
`client.meta.config.signature_version` reports `s3v4` either way, so the reported value does not
tell you which was generated. That is client-side behaviour, not a property of FSx for ONTAP.

This architecture's path does not use presigned URLs.
Depending on it in a production workload is not recommended.

## Designing concurrency and throughput

**The S3 AP, NFS and SMB all share the same FSx for ONTAP provisioned throughput.**
When the collect layer (S3 AP writes) and the serve layer (FlexCache NFS / SMB reads) sit on the same
file system, they contend for bandwidth. In this architecture the Origin and the Cache are separate
clusters, so it is not normally a problem — but **if a client mounts NFS directly against the Origin
cluster**, the throughput split has to be accounted for.

### Three limits apply to throughput, not one

**Treating "provisioned throughput" as a single ceiling gets it wrong.** Three limits apply and the
real one is the lowest
(see the [performance specifications](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html)).

| Limit | Set by | Value for ap-northeast-1, first-generation Single-AZ |
|---|---|---|
| Network I/O | throughput capacity | per step; at the 128 MBps step, 150 MBps baseline |
| Disk I/O (file server side) | throughput capacity | same as the step (128 at the 128 step, 2048 at the 2048 step) |
| **Disk I/O (SSD side)** | **provisioned SSD IOPS** | **768 MBps per TiB** and 3,072 IOPS per TiB *while SSD IOPS are on `AUTOMATIC`* |

**Reads and writes also have different ceilings.** Per HA pair:

| | Read | Write |
|---|---|---|
| First-generation Single-AZ (ap-northeast-1 and others) | 2,048 MBps | **750 MBps** |
| First-generation Multi-AZ (same) | 2,048 MBps | 1,300 MBps |

**Writes are lower because they are replicated to the secondary file server.** One write operation
is documented as consuming twice the network throughput.

Two things to establish when designing:

1. **Whether SSD IOPS match the step.** With 1 TiB of SSD on `AUTOMATIC`, disk throughput stops at
   768 MBps however high the step goes. Two ways past it: 2.67 TiB or more of SSD, or SSD IOPS set to
   `USER_PROVISIONED`. Raising SSD IOPS from 3,072 to 40,000 and changing nothing else took a
   280 GiB read from 286.1 to 2,042.1 MB/s, a 7.14-fold difference. So the 768 MBps figure is not a
   ceiling that capacity sets; it is what the default IOPS level happens to come to.

   > **That 7.14x is an observation with no established mechanism.** CloudWatch later showed that on
   > the fast side **98.5 to 99.9% of the bytes never reached the disks.** 280 GiB exceeds this step's
   > 238 GiB cache by only 18%, so "a read that could not be cached" was too generous a label. A
   > repeat also moved 2,042.1 to 2,667.2, so **the "99.7% of the step" coincidence did not hold.**
   > **Check item 3 below before provisioning IOPS.**
2. **Whether the workload is read- or write-dominated.** For write-dominated work the ceiling comes
   from the 750 MBps side, and stepping above the equivalent of 750 MBps does nothing.

Two steps were measured (the record is
[in Japanese](../../../ja/verification/throughput-iops-concurrency.md) (Japanese)): **at the
128 MBps step the step was the binding limit (129.5 MB/s, 101%), and at the 2048 MBps step it was
not** (497.1 MB/s, 66% of the 750 MBps write ceiling). A 16-fold step increase gave 3.8 times the
write throughput.

**A third lever sits on the client, it costs nothing, and it is the one that held up best.** A
default Linux NFS mount opens one TCP connection per server, and a single flow inside a VPC is capped
near 5 Gbps. The same sweep was run on two file systems on different days.

| File system | 1 stream | 4 streams | 8 streams |
|---|---|---|---|
| First (default mount) | 588.1 | 589.9 | 589.7 |
| Second (default mount) | 613.1 | 618.7 | 618.7 |
| Second (`nconnect=16`) | 1,140.6 | 2,904.6 | **3,062.8** |

**A default mount moves less than 1% when stream count goes up eightfold**, because the client is
what answers. `nconnect=16` gives **4.95 times** the rate at 8 streams. **This is the only finding
here that reproduced independently twice, so check the mount before buying a larger step.**

### Five defaults to clear before measuring your own environment

Every figure above was measured wrongly at least once because of a default. **All five produce a
plausible-looking number, so the result alone does not reveal them.** Clear them first.

| Default | What happens | How it shows | What to do |
|---|---|---|---|
| A Linux NFS mount opens one TCP connection | Stops near 590 MB/s and **does not respond to stream count** | 1, 4 and 8 streams give the same rate | `nconnect=16` |
| `dd if=/dev/zero` | Zero blocks never reach the disks and **come back at four times the ceiling** | The figure exceeds a published limit | Incompressible data (generate it with `openssl enc -aes-256-ctr`) |
| Inline storage efficiency is on for the volume | A compressible or identical payload is collapsed. **A factor of four on reads, under 5% on writes** | `space_savings.dedupe_percent` is high | Turn it off for the measurement, **before writing any data** -- straight after a write the background scan is running and the change is refused |
| `DiskIopsConfiguration: AUTOMATIC` | 3 IOPS/GiB makes the read IOPS-bound, well below the throughput ceiling | MB/s divided by IOPS is implausibly small for an IO size | `USER_PROVISIONED` |
| **A read that exceeds the cache only slightly** | The cached share dominates, so **the disk path is not what is being measured** | CloudWatch `DiskReadBytes` over `DataReadBytes` is a few percent or less | Read **at least twice** the cache in one pass |

**Write every figure as a share of a published limit.** When the share is far from 100%, doubt the
measurement rather than the number. **A figure that is too low deserves the same suspicion as one
that is too high** -- above, 37% and 400% were both measurement errors.

**And the more neatly a figure lands on a limit, the more it needs measuring again on another day.**
The same environment and conditions repeat to **within 0.2%** (four replicate pairs). **A repeat that
moves 30% is not variance; it means the conditions were not what they were thought to be.** The
"99.7% of the step's disk throughput" coincidence lasted one day.

### How to see whether ONTAP is saturated

The `fsxadmin` credential cannot reach ONTAP's node-level statistics
(`/api/cluster/nodes?fields=statistics` returns nothing, and the `private/cli` equivalents return
`API not found`). **CloudWatch publishes 33 metrics for the file system, and the answer is there.**
<!-- allow:naming the CloudWatch namespace name -->

| What you want | Metric |
|---|---|
| Whether ONTAP is saturated | `CPUUtilization` |
| Whether reads come from disk | `DiskReadBytes` over `DataReadBytes` |
| Whether the network binds | `NetworkThroughputUtilization` |
| Whether disk throughput binds | `FileServerDiskThroughputUtilization` |
| Whether SSD IOPS bind | `DiskIopsUtilization` |

Measured: **21-24% CPU at 417 MB/s through the S3 Access Point, and 18-23% at 800 MB/s over NFS.**
**Twice the throughput at the same CPU, so the cost of the protocol difference is not inside ONTAP.**

### How to decide concurrency

The starting point is this relation.

```text
max concurrency ≈ provisioned throughput ÷ bandwidth consumed per request
```

Bandwidth consumed per request comes from the object size and the time one request takes. Both have
to be measured against your own workload; neither can be derived from the throughput step.

That makes the order of work:

1. Measure the elapsed time and the throughput at concurrency 1, at a representative object size
2. Raise concurrency while recording the rate of `SlowDown` (503) and p99
3. Take the ceiling just below where that rate exceeds what you can absorb

**Where an existing NFS / SMB workload is present, subtract its share when designing.**

#### Request rate plateaus well before SSD IOPS does

**For a design that handles many small objects, calculating from SSD IOPS gets it wrong.** Measured
request rates through the S3 Access Point (4 KiB and 64 KiB objects, 128 MBps, 3,072 SSD IOPS, 20
seconds per point, zero 503s at every point):

| Concurrency | 4 KiB write | 4 KiB read | 64 KiB write |
|---|---|---|---|
| 16 | 153.9 | 330.3 | 171.2 |
| 64 | **415.3** | **630.3** | **415.9** |
| 256 | 420.8 | 594.0 | 404.4 |

In req/s. **Writes plateau near 420 req/s and reads near 600, which is 14 to 20 percent of the 3,072
SSD IOPS.** Object size barely matters (415.3 against 415.9 for 4 KiB versus 64 KiB), and raising
concurrency from 64 to 256 adds nothing.

The limit is the S3 API request path, not storage IOPS. **Provisioning additional SSD IOPS
($0.0204/IOPS-Mo) therefore does not raise the request rate available through S3.** Establish which
one you are hitting before buying more.

#### Aggregate throughput does not grow with more clients

**The purchased capacity is shared.** Summed totals with identical hosts, from one up to four
(8 MiB objects, concurrency 16, c5n.2xlarge):

| Phase | 1 host | 2 hosts | 3 hosts | 4 hosts | 4/1 |
|---|---|---|---|---|---|
| Write | 129.4 | 130.9 | 131.5 | 131.0 | **1.01x** |
| Read | 480.9 | 600.7 | 598.6 | 612.3 | 1.27x |

In MB/s, summed. **Writes stay flat all the way to four hosts**, and per host the figure is the total
divided by the count: 129.4, 65.3, 43.5, 33.0. **Size capacity per file system, not per client.**

The 1.27x on reads is not the ceiling moving. **One host (480.9) does not reach it**; two hosts get
to 600.7 and it is flat from there. The ceiling is about 600 MB/s, and on an 8 vCPU host the TLS work
at concurrency 16 saturates first, so **more than one client was needed to see the ceiling at all.**

(As a control, the same measurement against Amazon S3 gives 4.22x on writes and 4.10x on reads, with
per-host throughput unchanged. The ceilings differ in kind; the record is
[in Japanese](../../../ja/verification/throughput-iops-concurrency.md#クライアント台数を-1-から-4-まで上げたとき) (Japanese).)

#### The collect and serve layers compete for the same capacity

**The claim at the top of this section has a measurement behind it.** Two ten-minute write runs, one
of which was joined partway through by a FlexCache in another Region reading the same origin.

| Window | With other load | Without |
|---|---|---|
| 0 to 510 s | 127.8 to 130.3 MB/s | 127.8 to 130.6 MB/s |
| 510 to 600 s | **112.7, then 66.8, then 66.0** | 129.2, 130.0, 130.0 |

**Writes through the S3 Access Point roughly halved.** The only difference between the two runs was
the concurrent FlexCache fill. This is why throughput sharing has to be considered when clients read
or write the origin cluster directly.

#### Burst mechanisms play no part in writes here

Cut into 30-second intervals, ten minutes of continuous writing stayed within **127.8 to 130.6 MB/s
across all 20 intervals**, averaging 129.6. No decline, no exhaustion. **The purchased step is the
ceiling from the first second to the last.**

So a short measurement will not accidentally capture burst capacity on this configuration. **The
converse also holds: waiting does not make it faster.**

#### What happened when that procedure was run

The procedure above was executed and recorded in the throughput measurement
(2026-09-01, ap-northeast-1, 128 MBps, 8 MiB objects — the record is
[in Japanese](../../../ja/verification/throughput-iops-concurrency.md) (Japanese)). How well the
relation predicted the outcome:

| Step | Result |
|---|---|
| Time at concurrency 1 | p50 331.5 ms, 21.8 MB/s |
| Concurrency the relation gives | 128 ÷ 25.3 ≈ **5** |
| Where saturation begins, measured | between concurrency 4 (97.5 MB/s) and 16 (129.5 MB/s) |
| Where it plateaus, measured | concurrency 16 (129.5 MB/s) |

**The relation lands close to the knee and understates the concurrency needed to reach the
plateau.** It works as a starting point, but stopping at the figure it gives leaves the purchased
step unused.

**The roughly 330 ms fixed cost per request barely depends on size** (363.7 ms at 1 MiB, 331.5 ms
at 8 MiB). Smaller objects therefore consume less bandwidth per request and need more concurrency:
at 1 MiB, throughput was still climbing at concurrency 64.

### Behaviour when throughput saturates

**Saturation did not produce `SlowDown` (503).** Across both steps (128 MBps and 2048 MBps), at
1 MiB and 8 MiB by concurrency 1/4/16/64, **all 32 points recorded zero 503s** (measured with
retries disabled so they would be counted; the record is
[in Japanese](../../../ja/verification/throughput-iops-concurrency.md) (Japanese)). Writes did
plateau at the purchased figure, so saturation was certainly reached.

**Saturation showed up as queueing instead.** At 8 MiB, raising concurrency from 16 to 64 left
throughput unchanged (129.5 to 127.5 MB/s) while p50 grew from 985.7 ms to 3885.8 ms. **Bandwidth
does not increase; only latency does, in proportion to concurrency.**

Two consequences for design:

- **The 503 rate cannot be used to detect saturation.** Step 2 above is still the right thing to
  record, but in this environment saturation arrived without a single 503. **Detect it from p99.**
- **A timeout arrives first.** Latency keeps growing, so the client read timeout becomes the
  effective ceiling before anything else does.

This is not a claim that `SlowDown` cannot be returned. It means it was not observed across these
32 points. Code for the case where it is returned is still needed: exponential backoff (base 1
second, max 30 seconds), and boto3's `adaptive` retry mode. **Disable retries when measuring,
though.** `adaptive` absorbs 503s internally, so leaving it on makes a throttled endpoint look
merely slow.

## Directory design

### Files per directory

**What sets the ceiling is the volume's `maxdir-size`.** When a directory reaches it, the client gets
an out-of-space error (`ENOSPC`) and can no longer create files. The value is a per-volume setting and
can be raised with `volume modify -maxdir-size`, but **the documentation states plainly that raising
it could affect performance** ([maximum directory size](https://docs.netapp.com/us-en/ontap/volumes/cautions-increasing-maximum-directory-size-concept.html)).

So there are two things to check at design time.

1. **The current `maxdir-size` on the target volume.** The default depends on the ONTAP version and
   on system memory
2. **The number of entries you expect in one directory.** As entries grow, `readdir` and
   `ListObjectsV2` take longer

**This repository has no measurement of entry count against response time.** That is why it carries
no threshold in file counts: check `maxdir-size` in your own environment and partition finely enough
that the expected entry count stays well short of it.

### Recommended partition design

In this architecture's collect layer, the key of an S3 PutObject maps directly onto the directory
structure.

```text
# Hive-style date partitions (recommended)
s3://<ap-alias>/data/year=2026/month=08/day=10/sensor_001.json

# Tenant and date hybrid
s3://<ap-alias>/tenant-a/2026/08/10/report.pdf

# Hash buckets (a large number of uniform files)
s3://<ap-alias>/objects/a3/b2/object-uuid-001.bin
```

### Anti-patterns

| What not to do | The problem | The fix |
|---|---|---|
| A full LIST at the root `/` | Scans the whole volume. Tens of seconds to a timeout at a few hundred thousand objects | Always specify a Prefix |
| Ingesting many flat keys without slashes | Every file concentrates in the root directory | Use hierarchical partitions |
| Recursive LIST (no Delimiter) | Recursively walks every subdirectory | LIST one level at a time |
| Putting a FlexCache on the ingest volume | There is no point caching a write destination, and they contend for throughput | Separate the ingest and consume volumes |
| `find /mnt/vol/` on the NFS side | Ignores the partition structure and walks everything | Use a manifest, or generate the path |

### Choosing the partition granularity

**Partition down to a granularity where the entries in one directory stay well short of
`maxdir-size`.** The table below is a starting shape, **not a figure derived from measurement.** Work
out the number of partitions you need from your own ingest rate and `maxdir-size` before using it.

| Ingest rate | Granularity to start from | Example |
|---|---|---|
| Hundreds per day | `year/month/day/` | Batch ingest, reports |
| Thousands per hour | `year/month/day/hour/` | IoT telemetry |
| Tens of thousands per hour | `year/month/day/hour/` plus per device | Large-scale IoT |
| Hundreds of thousands per hour | Two-character hash buckets (256 ways) | UUID-based objects |

## Volume design — separate ingest from consume

**An S3 key design is the NFS-side directory structure.** When heavy ingest and NFS reads share one
volume, throughput contention and directory bloat happen at the same time.

### Recommended layout

```text
Origin FS (FSx for ONTAP)
├── vol_ingest_telemetry    ← S3 AP attached (IoT ingest)
│   └── /year=YYYY/month=MM/day=DD/hour=HH/{device}_{uuid}.json
├── vol_ingest_artifacts    ← S3 AP attached (CI/CD artefacts)
│   └── /{repo}/{branch}/{build_id}/{artifact}
├── vol_shared_data         ← S3 AP attached (design data, shared assets)
│   └── /{project}/{version}/{filename}
└── vol_processed           ← NFS only (processed, for distribution)
    └── /{output_type}/{date}/{result}

Cache Site (FlexCache)
├── fc_shared_data          ← a cache of vol_shared_data
└── fc_processed            ← a cache of vol_processed
    (vol_ingest_* is not cached)
```

### Design principles

| Principle | Reason |
|---|---|
| Do not put a FlexCache on an ingest volume | There is no point caching a write destination. It wastes throughput |
| FlexCache the consume volumes only | Only the data that is needed gets pulled |
| Separate the ingest and consume volumes | Avoids throughput contention, and lets size and tiering be set independently for each |
| Attach the S3 AP to the ingest volume | NFS / SMB alone is enough for the consume side |

### Tiering on the ingest volume

`AUTO` tiering works for data that is ingested frequently, consumed soon after, and then goes cold.
Data past the 31-day default cooling period moves to the capacity tier, holding down SSD cost.
The FlexCache side holds only hot data, so it is unaffected by tiering.

## Strategies for finding files on the NFS side

When consuming data ingested through the S3 AP over NFS / SMB, provide **a way to know what was
ingested** rather than walking the directory.

### The manifest pattern (recommended)

Write a manifest file when ingest completes, and have the NFS side read only that:

```text
# At the end of the ingest side (Lambda / pipeline)
s3://ap-alias/data/year=2026/month=08/day=10/_manifest_14.json
Contents: {"files": ["hour=14/sensor_001.json", ...], "count": 42, "timestamp": "..."}

# A script on the NFS side
cat /mnt/cache/data/year=2026/month=08/day=10/_manifest_14.json | jq -r '.files[]'
# → processes only the ingested files, without walking the directory
```

### The path generation pattern

Where the partition structure is known, generate the path in the script and access it directly:

```bash
# A script that processes yesterday's data — without using find
YESTERDAY=$(date -d "yesterday" +%Y/month=%m/day=%d)
for f in /mnt/cache/data/year=$YESTERDAY/*.json; do
  process "$f"
done
```

### inotifywait / FPolicy events

To shorten the delay before a file is noticed, make it event driven: process the file when it
appears. **`inotify` cannot do that here.** It watches the local kernel's VFS, and when watching a
network filesystem, **events are not reported if the change was made on a remote system**
([inotify(7)](https://man7.org/linux/man-pages/man7/inotify.7.html)). Writes in this architecture arrive at the origin over the S3 Access Point
and the cache pulls them in afterwards, so `inotify` on a client mounting the cache does not fire.

The server-side candidate is [FPolicy](https://docs.netapp.com/us-en/ontap/nas-audit/fpolicy-config-types-concept.html), and **on the origin side it is now settled that it does
not work.** A write arriving over the S3 Access Point raises no FPolicy notification, and is not
blocked even by a `mandatory` synchronous policy (measured 2026-08-26, ONTAP 9.18.1P3D1, with both
UNIX and WINDOWS identity — see [the measured FPolicy / S3 Access Point coverage](https://github.com/Yoshiki0705/FSx-for-ONTAP-Observability-integrations/blob/main/docs/en/s3ap-monitoring-coverage-implications.md)). An FPolicy event accepts only `cifs`, `nfsv3` or
`nfsv4` as its protocol; there is no value for the S3 path.

**Whether it fires on the cache side is still unverified.** Writes in this architecture arrive at
the origin, so even if a FlexCache fill were to raise an FPolicy event on the cache, that is a
separate question. Do not design on a mechanism that has not been verified.

Two substitutes are confirmed to work. The ONTAP native audit log records S3 Access Point
operations as `Source=HTTP` (object operations) and `Source=S3` (LIST), though without the
requester. ARP detects high-entropy files written through the access point. Both were observed on
the origin side; the cache side is equally unverified.

Polling with a periodic `ls` costs in proportion to the number of directory entries. It is workable
where the tree is split as described under [directory design](#directory-design).

## Multiprotocol consistency

In this architecture the main path is "write through the S3 AP, read over NFS / SMB". The reverse
direction and simultaneous writes need care.

| Scenario | Behaviour | Risk |
|---|---|---|
| **S3 AP PutObject completes, then an NFS / SMB read** | **Whatever is visible is always the complete object.** Propagation still takes time (p50 9 ms on the same volume, p50 8 ms through FlexCache; [verification record](../../verification/flexcache-s3ap-visibility.md)) | Low. This is the main path. **The client-side cache dominates, though** — at the mount defaults (`acdirmin=30` / `acdirmax=60`) a file can stay invisible for up to a minute |
| An S3 AP GET during an NFS write | Data mid-write may be read (a partial read) | Data inconsistency |
| An S3 AP write plus FlexCache write-back on the same file | The cache's dirty data is discarded (XLD revoke) | Data conflict |
| An S3 AP GET on the old key straight after an NFS rename | NotFound on the old key (the rename propagates immediately) | Key management in the application |

### Using it safely in this architecture

**On the main path (S3 AP to FlexCache NFS / SMB) a half-written object is never read.** A multipart
upload does not appear on the NFS side until `CompleteMultipartUpload`, and a single `PutObject` is
always complete once visible
([verification record](../../verification/flexcache-s3ap-visibility.md)).

**That is not the same as "visible the moment it completes".** Propagation on the server side takes
some milliseconds, and the client-side cache expiry sits on top of it. At the mount defaults a
deletion took 2,171 ms to show up
([same-volume verification record](../../verification/s3ap-nfs-visibility.md)). Where freshness is a
requirement, set `actimeo` explicitly.

**Patterns to avoid:**

- Writing to the same file through the S3 AP and over NFS / SMB at the same time
- FlexCache write-back and an S3 AP write targeting the same file
  (this architecture confines the Cache to reads, so it does not normally arise)

## Choosing between FlexVol and FlexGroup

| Criterion | FlexVol | FlexGroup |
|---|---|---|
| Maximum size | About 100 TB (the practical ceiling) | PB scale |
| File count ceiling | About 2 billion | number of constituents × 2 billion |
| FlexCache origin support | ONTAP 9.12.1 or later | ONTAP 9.13.1 or later (with constraints) |
| S3 AP support | ✅ | ✅ |
| Intended use | A single workload / PoC | Large-scale data / multi-tenant |
| Recommendation here | Start from verification and small scale | Large-scale production |

On a FlexCache whose origin is a FlexGroup, a NAS bucket can be created (and with
`-is-s3-enabled true`, [S3 data access works too](../../verification/cross-protocol-directions.md)).

## Procedure for designing the read-side cost

When the consuming side sits outside AWS, read-side charges come from **data transfer** and
**requests**, and different measures work on each. A design that looks at only one gets the other back.
The monetary estimates are in
[FinOps cost structure](../comparison/finops-s3-vs-s3ap.md); only the procedure is here.

### Step 1 — establish four quantities

Nothing can be judged without these. Do not fill them in by guessing.

| Quantity | What to measure | Example of how |
|---|---|---|
| Dataset size | The logical bytes held | S3 Storage Lens, `aws s3 ls --summarize`, volume usage |
| Working set size | The unique bytes actually touched in a month | From S3 server access logs or CloudTrail data events, total the size of the unique keys |
| Average object size | Dataset size ÷ object count | The object count from S3 Storage Lens |
| Reads of the same data | How many times the same key is read in a month | The distribution of GET counts per key in the access log. Look at the median and the top, not the mean |

**Do not flatten the read count into a mean.** A distribution where a few files are read hundreds of
times is common, and in that case judge from the top keys rather than the overall average.

### Step 2 — calculate which term dominates

```text
monthly transfer     = working set size × read count
transfer charge      = monthly transfer × transfer unit price (tiered over the internet, flat on DX)

monthly requests     = (working set size ÷ average object size) × read count
request charge       = monthly requests × GET unit price

request share        = request charge ÷ (transfer charge + request charge)
```

The share changes what to do. The rough guide is in the "looking at transfer and requests together"
table in [FinOps cost structure](../comparison/finops-s3-vs-s3ap.md).

| Share | Dominant term | What to do |
|---|---|---|
| Roughly under 5% | Transfer | Reduce the bytes carried. Place only the working set on the serve side |
| 5 to 30% | Transfer-leaning, but requests matter too | Transfer first, then how objects are grouped |
| 30% or more | Both | Combine grouping (requests) with caching (transfer). One alone leaves the other |

### Step 3 — design according to the dominant term

**When transfer dominates.** What is reduced is bytes.

- Place only the working set on the serve side. A full copy means carrying some multiple of the working
  set
- If the consuming side can move to AWS, that is what works best (within one Region it is free)
- Lower the unit price with Direct Connect. Port and circuit charges are separate, so judge it against
  the transfer volume
- **Making objects larger does not reduce transfer.** The count falls; the bytes do not

**When requests dominate.** What is reduced is the number of calls.

- Group at the collection stage. A larger file also means fewer reads
- Move reads onto the file protocol. An NFS / SMB read is not an S3 request
- Reduce listing. `ListObjectsV2` is priced as Tier1, an order of magnitude above GET

**When both dominate.** Do both. With one alone, the remaining side becomes dominant.

### Step 4 — check it does not collide with the collect-side design

Grouping objects larger for the read side runs into the collect side's constraints.

| The result of grouping | The constraint hit |
|---|---|
| A single object exceeds 5 GiB | The S3 AP's single `PutObject` limit. Split it into multipart |
| A whole object exceeds 50 GiB | The S3 AP limit. The judgement comes after transfer, so validate on the client before sending |
| Larger than the granularity the consuming side needs | Parts that go unused get carried too, increasing transfer. Match the read unit |

Conversely, splitting finer than the consuming side's read unit means several reads per operation, which
increases the request count. **Matching the grouping granularity to the consuming side's read unit** is
the criterion.

### Step 5 — watch in operation for the premises breaking

An estimate rests on assumptions. If any of these three drift, the conclusion changes.

| What to monitor | What happens when it drifts | Where to look |
|---|---|---|
| Cache hit rate | If the working set is larger than assumed, misses rise and transfer exceeds the estimate | The FlexCache hit rate (obtainable through Harvest) |
| The distribution of read counts | If the count falls, the cache's fixed cost stops being earned back | GET counts per key in the access log |
| Transfer volume | Crossing a tier boundary changes the unit price | `APN1-DataTransfer-Out-Bytes` in Cost Explorer |

The response to a falling hit rate is to grow the Cache, but **a Cache volume cannot be tiered**, so
the added capacity is SSD cost outright. Growth in the working set goes straight to the bill.

## Boundaries that span layers, and the traps in them

The limits themselves are on [a separate page](s3-access-point.md).
Collected here are **the combinations where limits from different layers interact and become a
problem**. None of them is easy to notice from reading a single page.

### The size boundaries differ by layer

| Boundary | Value | Layer it applies to | Stage |
|---|---|---|---|
| S3 AP single `PutObject` | 5 GiB | collect | verified |
| S3 AP one `UploadPart` | 5 GiB | collect | verified |
| S3 AP whole object | 50 GiB | collect | verified |
| S3 AP `GetObject` | No size limit (Range GET supported) | collect | verified |
| File size FlexCache write-back has been verified to | Under 100 GB | serve | documented ([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)) |
| WAN round trip FlexCache write-back has been verified to | Within 200 ms | serve | As above |

**As long as collection goes through the S3 AP, these two do not collide.** A whole object stops at
50 GiB, so it necessarily stays inside write-back's verified range of 100 GB.

The collision arrives when the path changes. **When a file is written directly from NFS / SMB on the
Cache side, there is nothing on the S3 AP side to stop the size.** With write-back enabled, a file past
100 GB leaves the verified range. In a design where the serve side generates large files — rendering
output, simulation results, assembling an archive — confirm this boundary at design time.

### The 50 GiB judgement happens after the payload has been transferred

The 50 GiB whole-object limit is judged at `CompleteMultipartUpload`. That is, **it fails after every
part has been transferred**. The time spent transferring and the request charges do not come back.
Validate the size on the client before sending.

### Snapshot interval and write-back

Taking a snapshot on the Origin **reclaims outstanding dirty data from every write-back Cache tied to
that Origin volume**. During a period of heavy writing, this reclaim needs several retries
([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)).

Taking snapshots at a short interval for protection sits badly with write-back. If both are required,
offset the snapshot interval from the write peak, or consolidate serve-side writes on the Origin.

### Thin provisioning and write-back switching silently

A write-back Cache **switches automatically to write-around once the Origin volume's free space falls
to 20% or below**. The threshold is evaluated against **both** the free space the Origin reports and the
aggregate's physical free space. If the Origin is overprovisioned, it switches sooner than expected
([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)).

No error is raised when it switches. It shows up as increased write latency. In a design that runs
capacity tight, do not place a performance premise on write-back.

### A Cache cannot be tiered, so growth in the working set becomes SSD outright

A Cache volume is not tiered ([supported and unsupported features](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html)).
Even where `AUTO` tiering on the Origin keeps its SSD small, **the serve side has no such escape**.
Whatever the working set grows by becomes added SSD.

The sizing guidance is at least 10% of the origin, and 10% is also the default at creation
([sizing guidance](https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html)).
On a small origin, the 1 TiB SSD floor bites before the ratio does.
How the cost falls out is collected in
[FinOps cost structure](../comparison/finops-s3-vs-s3ap.md).

### The Cache has to be a FlexGroup; write-back recommends a single constituent

AWS documentation requires **the FlexCache volume to be a FlexGroup**
([creating a FlexCache](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/create-flexcache.html)).
The write-back guidelines, meanwhile, recommend **configuring the whole Cache volume as a single
constituent** to avoid unintended eviction
([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)).
Satisfying both gives "a FlexGroup with one constituent".

In addition, this architecture's verification found that **attempting to create a FlexGroup through the
ONTAP CLI produced a compatibility error with the FabricPool aggregate, and it had to be created through
the FSx for ONTAP API**
([verification record](../../verification/cross-protocol-directions.md)).
Whether it succeeds depends on the creation path, so a CLI failure is not grounds for concluding it is
impossible.

### Above 10 origin volumes, write-around

AWS documentation cites write-around for read-centric, latency-insensitive cases,
**or where a FlexCache origin volume count on the origin file system exceeds 10**
([replication with FlexCache](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)).
In a fan-out design that adds sites, this count bears on whether write-back is available.

### A rename is expensive in both layers

An S3 key is the NFS-side path, so re-partitioning is a directory rename.
With write-back enabled, **a renamed file is evicted from the Cache, and no other operation can proceed
until the dirty data has drained to the Origin**
([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)).

Do not operate on the assumption that the key design can be redone. Build a structure that does not have
to move in the first place.
(If S3 Files is taken as the alternative, a rename there is also a copy and delete of every object under
the prefix. The detail is in
[FinOps cost structure](../comparison/finops-s3-vs-s3ap.md))

### A name collision can only be prevented at the key design stage

`part1/part2` and `part1/part2/part3` cannot both exist on NAS.
The former requires a file and the latter a directory of the same name
([NAS data requirements](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html)).

Placing a manifest at `.../day=10/_manifest_14.json` and also creating `.../day=10/_manifest_14/` at the
same level collides. Do not use the same name for a leaf and for the level beneath it.

### With write-back, only some attributes can be changed from the Cache side

On a write-back-enabled Cache, only timestamps, mode bits, NT ACLs, owner, group and size can be set.
Any other attribute change is forwarded to the Origin, and **the file may be evicted from the Cache**
([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)).
Where an application using extended attributes runs on the serve side, confirm this beforehand.

### SMB write oplocks are unavailable with write-back

On a write-back-enabled Cache, SMB Opportunistic Locks for writes are not supported
([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)).
Where an SMB client's performance premise depends on oplocks, it cannot be combined with write-back.

### The version requirements apply to both the Origin and the Cache

| Item | Requirement |
|---|---|
| S3 AP (collect layer) | ONTAP 9.17.1 or later |
| FlexCache write-back | Available from ONTAP 9.15.1. Important improvements landed in 9.17.1P1, and that or later is strongly recommended on both the Origin and the Cache. 9.15.1 is not recommended for production ([guidelines](https://docs.netapp.com/us-en/ontap/flexcache-writeback/flexcache-write-back-guidelines.html)) |
| FlexCache duality (NAS bucket) | ONTAP 9.18.1 or later, plus `-is-s3-enabled true` (advanced privilege) |

Deciding the version from the collect layer's requirement alone leaves it short at the point where
write-back is used on the serve side.
**Add both sides' requirements together first, then decide the version.**

## Related documents

| Document | Contents |
|---|---|
| [Limits](s3-access-point.md) | Size, name and configuration prerequisites |
| [FinOps cost structure](../comparison/finops-s3-vs-s3ap.md) | Billing dimensions, estimates per configuration, and the alternatives' specification constraints |
| [Support matrix](../../support-matrix.md) | The support matrix for the collect and serve layers |
| [Architecture](../../architecture.md) | What this architecture solves and does not solve |
| [Decisions that come first](../../design-first-decisions.md) | The order for deciding security style and volume design |
| [PoC checklist](../../poc-checklist.md) | What to confirm, and in what order |
| [Sibling repository: compatibility notes](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns) | The detail of the Lambda / Step Functions integration |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/limits/s3ap-design-guide.md) | [English](s3ap-design-guide.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
