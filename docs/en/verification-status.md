# Verification status — separating verified from unverified

<!-- lang-switcher:start -->
🌐 [日本語](../ja/verification-status.md) | [English](verification-status.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

This repository is public. So that an unverified item is never read as a guarantee of behaviour, the
stage is stated explicitly and nothing unverified is written in the assertive form.

| Stage | Meaning |
|---|---|
| verified | Reproduced in a real environment. The environment (ONTAP version, Region, configuration) is stated alongside |
| documented | Stated in AWS or vendor documentation. Not confirmed against real hardware |
| unverified | Not confirmed. Either documented but not followed through on hardware, or not documented at all |
| unconfirmed | No statement found in public documentation. This is not the same as "cannot be done" |

"The documentation says so" and "it works" are different claims. Do not cite the first as the second.

## Current state

| Item | Stage | Basis |
|---|---|---|
| Supported operations and measured size limits of the FSx for ONTAP S3 Access Point | verified | Measured in the sibling repository [fsxn-s3ap-serverless-patterns](https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns). 5 GiB for a single `PutObject`, 50 GiB for a whole object, and the limit is judged at `CompleteMultipartUpload` |
| On an Active Directory joined SVM, every data operation through the S3 Access Point needs reachability to an AD domain controller | verified | Same repository. `HeadBucket` succeeds even when AD is unreachable, so it is a false positive |
| FlexCache with FSx for ONTAP as origin and on-premises ONTAP as cache | documented / not confirmed on hardware | Stated in AWS's [supported configurations](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) |
| How an object written through the S3 Access Point appears over NFS on the **same volume** | verified | [Verification record](verification/s3ap-nfs-visibility.md). 2026-08-09, ap-northeast-1, SINGLE_AZ_1 / 128 MBps, UNIX, NFSv3, `actimeo=0`, n=30. S3 to NFS is p50 9 ms; NFS to S3 is p50 873 ms (64 B). **The ONTAP version could not be determined** (the record explains why) |
| Whether a partial object mid-multipart-upload is visible on the file side | verified | Same record. It does not appear over NFS until `CompleteMultipartUpload` |
| The effect of NFS client mount options on visibility | verified | Same record. A deletion propagates in 7 ms with `actimeo=0` and in 2,171 ms on a default mount. The defaults are `acdirmin=30` / `acdirmax=60` |
| NFS write (origin) until readable through the S3 Access Point | verified | [All-directions comparison](../ja/verification/cross-protocol-directions.md) (Japanese). p50 44 ms (boto3 persistent session). **The initial 873 ms was a mismeasurement of CLI startup cost and is withdrawn** |
| NFS write (origin) until readable over FlexCache cache NFS | verified | Same record. p50 6 ms. An NFS write commits directly to the origin, so it is faster than going through S3 |
| Whether an ONTAP S3 NAS bucket (FlexCache duality — separate mechanisms from the S3 Access Point) can be used on FSx for ONTAP | **regular volume: works / FlexCache: no data access** | [All-directions comparison](../ja/verification/cross-protocol-directions.md) (Japanese). On a regular volume, NFS write to ONTAP S3 `GetObject` succeeded (the S3 user can be created through the CLI). On a FlexCache volume, creating the NAS bucket and `HeadBucket` succeed but `GetObject` and `ListObjects` return AccessDenied. ONTAP 9.18.1P3D1, FSx for ONTAP |
| How an object written through the S3 Access Point appears on the **FlexCache cache volume** | **verified** | [FlexCache verification record](verification/flexcache-s3ap-visibility.md). 2026-08-09, ap-northeast-1, ONTAP 9.18.1P3D1 on both clusters, over VPC peering, UNIX, NFSv3, `actimeo=0`, n=30. **S3 to FlexCache NFS is p50 14 ms.** A partial multipart is not visible until `CompleteMultipartUpload`. A deletion propagates in 9 ms |
| The mapping between security style and fan-out protocol, and its inheritance at cache creation | unverified | The basis is Azure NetApp Files' cache volume requirements. Whether the same rule holds on this architecture's main path has not been confirmed ([decisions that come first](design-first-decisions.md)) |
| Whether Cloud Volumes ONTAP / ONTAP Select / Azure NetApp Files / Google Cloud NetApp Volumes can be the cache when FSx for ONTAP is the origin | unconfirmed | Not listed in AWS's supported configuration table |
| Behaviour as the number of caches per origin grows | unverified | AWS documentation recommends write-around above 10 origin volumes, which may bear on how many fan-out targets to design for |
| The relationship between ONTAP 9.18.1 FlexCache duality and attaching an S3 Access Point to a volume | treated as separate mechanisms | The implementer and the enabling procedure both differ. The support status of one is never used as evidence for the other. This architecture uses neither, so there is no design impact |
| Performance characteristics on each platform | not measured | If measured, state the environment, object size, concurrency and throughput configuration alongside |
| Cost | not measured | State a sample run and a production estimate separately |

## How performance and cost figures are handled

A figure that was not measured is not written. A figure that was measured is written with all of the
following:

- the date measured
- the Region
- the ONTAP version
- the file system generation, configuration and throughput setting
- the object size and concurrency
- what was measured (client side, or a service metric)

A figure missing any of these cannot be reproduced, so it is useless for comparison and for
estimation alike. Where the sibling repository holds a figure, it is not copied across unless the
environment is stated with it.

> **A note on figures**: some documents in the sibling repository state a measured time for a write
> through the S3 Access Point to become readable over NFS on the cache side. This repository treats
> that as unverified, as the table above shows. The reason is that the measurement conditions
> (cluster configuration, cache settings, object size) have not been confirmed to match this
> architecture's main path. It is not a statement that the figure is wrong.

> **Do not read a same-volume measurement as the FlexCache answer**: the figures in the
> [verification record](verification/s3ap-nfs-visibility.md) are for a single volume
> accessed both through the S3 Access Point and over NFS. FlexCache is not in the path. The former is
> a precondition for the latter, but the former's figure cannot be quoted as the latter's answer.
> Keeping those two apart is half the reason this table exists.

### Why the ONTAP version could not be stated

The ONTAP version could not be determined for the measurement above. `DescribeFileSystems` on
FSx for ONTAP did not return `FileSystemTypeVersion` for the existing file system in question, and
the ONTAP REST API does not return the version without credentials.

**This gap closes if the environment is created fresh.** The
[collect-side template](../../environments/aws-origin/template.yaml) creates the `fsxadmin`
credentials at the same time as the file system, makes them readable from the verification host, and
provides a route to ONTAP on port 443. Borrowing an existing environment to measure in can leave this
kind of information unobtainable after the fact.

## Raising a stage

- unconfirmed to documented: attach the source URL
- documented to verified: attach the environment information above and the confirmation procedure
- Lowering a stage is always fine. Evidence is required only for raising one

## Related documents

| Document | Contents |
|---|---|
| [PoC checklist](poc-checklist.md) | The order in which to confirm unverified items |
| [Support matrix](support-matrix.md) | What the public documentation states |
| [Decisions that come first](design-first-decisions.md) | Judgements that are unconfirmed but expensive to reverse |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/verification-status.md) | [English](verification-status.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
