# Ingest once over S3, serve it to the floor over NFS — S3 Burst on ONTAP Files

<!-- Target: dev.to (English). Japanese version: ../ja/introducing-s3-burst-on-ontap-files.md
     Japanese is the authoritative version; this is a translation.
     Pre-publish check: make all (naming, sources and stated numbers are all checked).
     Delete this comment before publishing. -->

## TL;DR

- A repository for the shape where **ingest speaks S3 and consumers keep speaking NFS / SMB**, with
  no copy job in between → [s3-burst-on-ontap-files](https://github.com/Yoshiki0705/s3-burst-on-ontap-files)
- The S3 Access Point is attached to the **origin volume only**. No object access on the cache side.
- Measured the two-protocol visibility of a single volume: **S3 to NFS is p50 9 ms, NFS to S3 is
  p50 873 ms. The directions differ by about two orders of magnitude.**
- **The central claim is still unverified.** Visibility on a FlexCache *cache* volume was not
  measured. The repository mechanically enforces not writing unverified things as verified.
- In one case the client's mount options mattered more than the storage did.

## Who this is for

- You have NFS / SMB workloads and want the ingest side to accept the S3 API.
- You want to serve reads at several sites without transferring everything to each of them.
- You are weighing up an Amazon FSx for NetApp ONTAP S3 Access Point together with FlexCache.

No ONTAP background is assumed; terms are explained as they appear.

## The problem

When you need both object and file access, practice tends to land on one of three shapes.

1. Keep files authoritative and copy to S3 for analytics.
2. Make S3 authoritative and put a gateway or FUSE in front of existing applications.
3. Treat both as authoritative and manage them in parallel.

All three are reasonable. The difficulty is not the choice — it is that **the cost is hard to see**.

With the first, downstream always sees the moment of the last copy: the job interval becomes the
staleness, the same bytes are billed twice, and a missed deletion makes the gap grow. Permissions
also split — POSIX or NTFS ACLs on one side, IAM and bucket policy on the other — so an audit
question about who can read a file has two answers instead of one.

With the second, locking, `rename` atomicity and partial updates do not line up between POSIX or SMB
expectations and what an object store actually is. The gateway also becomes a new single point of
failure.

With the third, when the two diverge, most organisations have no rule for deciding which one is right.

## The shape

What it does is simple.

| Layer | Mechanism | Protocol |
|---|---|---|
| Collect (write) | FSx for ONTAP S3 Access Point, **on the origin volume only** | S3 API |
| Source of truth | FSx for ONTAP origin volume | — |
| Distribute | FlexCache | cluster / SVM peering between ONTAP systems |
| Consume (read) | Cache volume at the consuming site | NFS / SMB only |

The `burst` in the name means fanning collected data out to the file-protocol side. It has nothing to
do with FSx for ONTAP throughput burst credits. Because the word collides, the README says so in its
first sentence.

### Why no S3 on the cache side

**The write path stays single.** The origin is authoritative and writes always go through the
AWS-side S3 Access Point. Whether the cache writes back (write-back or write-around) stops being a
design question, and the cache settles into the read-oriented role FlexCache is suited to.

**No object-layer implementation differences reach the consuming site.** "Show these files as
objects" exists under several different names and implementations. This design uses that capability
in exactly one place, on the origin, so all the cache side has to provide is FlexCache and a file
protocol.

### Two mechanisms that are easy to conflate

This deserves care, because the names are close and both summarise as "access an ONTAP volume over
S3".

| Name | Implemented by | What it does | Minimum |
|---|---|---|---|
| S3 Access Point attached to FSx for ONTAP | AWS | Attaches an AWS-side endpoint to an ONTAP volume | ONTAP 9.17.1+ |
| FlexCache duality | NetApp | Gives a **cache volume** ONTAP's own S3 access | ONTAP 9.18.1+ |

**These are separate mechanisms.** Different implementer, different way to enable, different minimum
version. Because duality and attaching an S3 Access Point are separate mechanisms, "duality arrived
in 9.18.1, therefore it can be attached to a cache volume" does not follow — and neither does the
negative form.

This design uses neither. The distinction is spelled out anyway, because **descriptions that mix the
two are in circulation**. Cite one as evidence for the other and a reader designs against a premise
that does not exist.

The repository prevents that conflation **mechanically**: `make audit` rejects a line that mentions
both duality and an S3 Access Point without also saying they are separate mechanisms. Correct prose
needs no marker; only a careless line fails.

## What was measured

Visibility on a **single volume** accessed through both an S3 Access Point and NFS.

### Conditions

| Item | Value |
|---|---|
| Date | 2026-08-09 (UTC) |
| Region | ap-northeast-1 |
| Deployment type | SINGLE_AZ_1, one HA pair |
| Throughput | 128 MBps (provisioned) |
| Volume | UNIX security style, AUTO tiering |
| Client | EC2 in the same subnet, NFSv3 |
| Concurrency | 1 |
| Method | write and read on the **same host, same clock** |
| ONTAP version | **could not be determined** (below) |

### Results

**S3 PutObject to visible over NFS** (64 B, `actimeo=0`, n=30)

| min | p50 | p90 | p99 |
|---|---|---|---|
| 7 ms | 9 ms | 11 ms | 15 ms |

**NFS write to readable through the S3 Access Point** (`actimeo=0`)

| Size | n | min | p50 | p90 | p99 |
|---|---|---|---|---|---|
| 64 B | 30 | 679 ms | 873 ms | 1,165 ms | 1,439 ms |
| 1 MiB | 30 | 700 ms | 904 ms | 1,423 ms | 1,650 ms |
| 8 MiB | 10 | 993 ms | 1,169 ms | 1,444 ms | 1,928 ms |

### What follows from that

**The directions differ by about two orders of magnitude.** Same data, same volume, same host: single
digit milliseconds one way, about a second the other.

**The slow direction is dominated by a fixed component.** Growing the object 128,000 times, from
64 B to 8 MiB, moves p50 only from 873 ms to 1,169 ms, and the floor from 679 ms to 993 ms. A
component that scales with data only becomes visible at 8 MiB; most of the delay is **independent of
size**. That points at a periodic refresh rather than data movement.

"Points at" is deliberate. The period itself was not observed — this is how the behaviour looks from
outside, not a statement about the implementation.

**A partial object never appears on the file side.** A multipart upload was not visible over NFS
until `CompleteMultipartUpload`. So there is no need to guard against reading a half-written file.

### The most practical finding was not about the storage

Measuring how a deletion propagates produced this:

| Mount options | S3 delete to gone from NFS |
|---|---|
| `actimeo=0` | 7 ms |
| Linux defaults | 2,171 ms |

**Over 300 times apart** — and the cause is the NFS client's attribute and directory cache, not the
storage. Linux defaults are `acdirmin=30` and `acdirmax=60`, so a file appearing in a directory the
client has already listed can stay invisible for up to a minute. A completed multipart object was
still absent three seconds later on a default mount.

**Most "I wrote it but cannot see it" reports are explained here.** Use `actimeo=0` when measuring or
when freshness matters; use the defaults when re-reading the same files.

## What was not measured

This is half the point of the article.

**The central claim — when an object written through the S3 Access Point becomes visible on a
FlexCache cache volume — is unverified.** The measurement above is a single volume and does not go
through FlexCache. The former is a prerequisite for the latter, not an answer to it.

The reason was environmental: no cluster administrative credential was available for the verification
clusters, creating a FlexCache has no AWS API and must go through ONTAP, and there was no network
path between the two file systems.

**The ONTAP version could not be determined either.** The FSx for ONTAP `DescribeFileSystems` call
omitted `FileSystemTypeVersion` for the file system in question, and the ONTAP REST API will not
report a version without credentials. So the figures above are **reproducible only up to that one
unknown.**

Publishing nothing was an option. Stated conditions make a measurement useful, so the numbers are
published with a table in the repository setting out exactly what they do and do not support.

## Deployment templates

So the same measurement can be reproduced, the environment ships in two halves.

| Side | Tool | Contents |
|---|---|---|
| Collect (origin) | CloudFormation | File system, SVM, origin volume, **an in-VPC verification host**, and a generated `fsxadmin` credential |
| Serve (cache) | Terraform (ONTAP provider) | FlexCache volume and a read-only NFS export |

Two tools because **the serve side can live outside AWS**: on-premises ONTAP, ONTAP Select, or a
second FSx for ONTAP. Once ONTAP is the target, an AWS control plane cannot express it.

### Why the verification host is in the template

Not decoration. Two reasons.

**The ONTAP management endpoint is reachable only from inside the VPC**, and FlexCache has no AWS
API. Without an in-VPC host, the serve side cannot be built at all.

**A visibility measurement needs the write and the read on one clock.** Two hosts is a comparison of
two clocks, which at millisecond scale is not a measurement.

### What was deliberately left out

| Item | Why |
|---|---|
| Cluster and SVM peering | Needs IP reachability between two clusters' intercluster LIFs, which across VPCs means peering and routes. A template quietly changing routing is worse than one that says it does not. **This is also the most common cause of a failed FlexCache creation**, so both guides say to check it first |
| S3 Access Point | CloudFormation has no resource for attaching one to an FSx for ONTAP volume, so the CLI does it. Putting a Lambda in the trust path of every deployment for one API call is not a good trade |
| Immutability features | SnapLock and snapshot locking are **entirely absent**. Enabling either makes the volume, its SVM and the whole file system undeletable for the retention period, and a verification environment is the worst place for that |

The last one is enforced by a test: neither template may contain any of those parameter names.

## On not writing unverified things as verified

The part that took the most care is the prose checking. An unverified claim read as a guarantee makes
a reader design against a premise that does not exist.

Four stages, mapped one-to-one onto their words:

| Stage | Meaning |
|---|---|
| verified | Reproduced in a real environment, with the environment stated |
| documented | Documented, not reproduced here |
| unverified | Not checked |
| unconfirmed | No public statement found. **Not "cannot be done"** |

On top of that, the following are rejected mechanically:

- a line covering both mechanisms without saying they differ;
- wording that ranks options without stating every option's exclusion conditions at the same
  granularity;
- a pattern count in prose that disagrees with the filesystem — counts are recomputed from the
  directories, and a count of zero is reported as a broken reader rather than as "none yet".

## What to confirm next

Ordered by which answers unblock design, not by cost.

1. Whether, and how quickly, an object written through the access point can be read on the cache
   (**highest priority, unverified**).
2. FlexCache from an FSx for ONTAP origin to an on-premises ONTAP cache (documented as supported, not
   verified on hardware).
3. Behaviour as the number of caches per origin grows.
4. Whether other platforms can be the cache (**unconfirmed**).

AWS documents exactly three FlexCache configurations, and with FSx for ONTAP as the origin the cache
is **on-premises ONTAP or FSx for ONTAP only**. Everything else is recorded as unconfirmed. "It is
ONTAP-based, so it works" is not a conclusion this repository draws.

## FAQ

**Q. Do I get all of S3?**
No. The supported operation set is limited, and event notification, lifecycle and versioning are out
of scope.

**Q. Can I use any object name?**
No. S3 names go to 1024 bytes and file or directory names to 255 characters. Names without a slash
all land in the root directory, which becomes a performance problem in quantity.

**Q. Can I write to the cache?**
Not in this design. Writes are concentrated on the origin's S3 Access Point.

**Q. What has to be decided first?**
**Whether the consuming site uses NFS or SMB.** The origin's security style bears on it and is
treated as inherited at cache creation time, so it has to be settled **before the origin volume
exists**. The supporting text is Azure NetApp Files' cache volume requirements; whether the same rule
holds on this architecture's main path is unconfirmed. Deciding early is still worth it — the rework
if it holds is large, and there is nothing to lose if it does not.

**Q. Where should I start reading?**
[Architecture](https://github.com/Yoshiki0705/s3-burst-on-ontap-files/blob/main/docs/ja/architecture.md)
→ [how to choose](https://github.com/Yoshiki0705/s3-burst-on-ontap-files/blob/main/docs/ja/reference/decision-trees/choosing-this-architecture.md)
→ [verification status](https://github.com/Yoshiki0705/s3-burst-on-ontap-files/blob/main/docs/ja/verification-status.md).
Ruling the design out quickly is treated as a feature.

## Closing

The cases this does not suit are written down too. If you need S3-specific features, use names that
are not NAS-friendly, write heavily at the consuming site, or need object access on the cache, another
approach fits better.

The most welcome contribution is a **verification result**, and **a negative result is worth as much
as a positive one**. "This combination does not work" is stronger than "unconfirmed" and harder to
come by. There is an issue form for it.

- Repository: <https://github.com/Yoshiki0705/s3-burst-on-ontap-files>

This article is technical information compiled by an individual and is not an official position of
any organisation. Support status depends on both the AWS service specification and the ONTAP version.
Confirm in your own environment before applying any of it to production.
