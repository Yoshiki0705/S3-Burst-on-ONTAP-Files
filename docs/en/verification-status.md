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

## The scope of the central claim

The central claim of this architecture is when an object written to the origin through the S3 Access
Point becomes readable over NFS / SMB on a FlexCache cache volume. **The verified scope and the
unverified scope are stated separately.**

| Scope | Stage |
|---|---|
| Cache on **FSx for ONTAP** (same Region, VPC peering), NFSv3, UNIX, 64 B, `actimeo=0` | **verified** (2026-08-09, ap-northeast-1, ONTAP 9.18.1P3D1 on both clusters, n=30). Across three measurements p50 ranges from 7 to 14 ms; the representative figure is 8 ms |
| The same conditions over SMB (AWS Managed AD joined, `cache=none`) | **verified** (2026-08-10, same environment, n=30) |
| Cache on **on-premises ONTAP** (this architecture's main path) | **unverified**. Present in AWS's supported configurations, not followed through on hardware |
| A remote site or a high-latency path | Unverified. The measurement ran under sub-millisecond network latency |
| NTFS security style, mount options other than `actimeo=0`, more than one cache | Unverified |

**Do not state "the central claim is verified" in one word.** What was verified had FSx for ONTAP on
the cache side too; the on-premises ONTAP cache held out as the main path is unverified. This section
is the single source for the stage, and other documents link here.

## Current state

| Item | Stage | Basis |
|---|---|---|
| Supported operations and measured size limits of the FSx for ONTAP S3 Access Point | verified | Measured in the sibling repository [FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns). 5 GiB for a single `PutObject`, 50 GiB for a whole object, and the limit is judged at `CompleteMultipartUpload` |
| On an Active Directory joined SVM, every data operation through the S3 Access Point needs reachability to an AD domain controller | verified | Same repository. `HeadBucket` succeeds even when AD is unreachable, so it is a false positive |
| Presigned URLs through the S3 Access Point (`PutObject` / `HeadObject` / `GetObject`) | verified | [Measurement record](../ja/verification/s3ap-operations.md) (Japanese). 2026-08-19, ap-northeast-1, SINGLE_AZ_1 / 128 MBps, UNIX, from a client outside AWS, n=30 over 4 runs. All three succeed, under SigV4 and under SigV2. **AWS's compatibility table states `Presign — Not supported`, so the measurement runs opposite to the documentation**, and the guidance not to depend on it in production is unchanged. The ONTAP release could not be determined |
| `UploadPartCopy` with a source inside the same access point | verified (confirmed to fail) | [Measurement record](../ja/verification/s3ap-operations.md) (Japanese). 2026-08-19, same environment. **It returns `NoSuchKey`.** `CopyObject` given the identical `CopySource` succeeds in the same run, which is the control. **AWS's compatibility table states same-AP, same-Region copies are supported, so the measurement runs opposite to the documentation.** Whether `UploadPartCopy` is supported at all **remains undecided**, because a source in a different access point is refused for `CopyObject` too |
| FlexCache with FSx for ONTAP as origin and on-premises ONTAP as cache | documented / not confirmed on hardware | Stated in AWS's [supported configurations](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) |
| How an object written through the S3 Access Point appears over NFS on the **same volume** | verified | [Verification record](verification/s3ap-nfs-visibility.md). 2026-08-09, ap-northeast-1, SINGLE_AZ_1 / 128 MBps, UNIX, NFSv3, `actimeo=0`, n=30. S3 to NFS is p50 9 ms; NFS to S3 is p50 873 ms (64 B). **The ONTAP version could not be determined** (the record explains why) |
| Whether a partial object mid-multipart-upload is visible on the file side | verified | Same record. It does not appear over NFS until `CompleteMultipartUpload` |
| The effect of NFS client mount options on visibility | verified | Same record. A deletion propagates in 7 ms with `actimeo=0` and in 2,171 ms on a default mount. The defaults are `acdirmin=30` / `acdirmax=60` |
| NFS write (origin) until readable through the S3 Access Point | verified | [All-directions comparison](verification/cross-protocol-directions.md). p50 44 ms (boto3 persistent session). **The initial 873 ms was a mismeasurement of CLI startup cost and is withdrawn** |
| NFS write (origin) until readable over FlexCache cache NFS | verified | Same record. p50 6 ms. An NFS write commits directly to the origin, so it is faster than going through S3 |
| Whether an ONTAP S3 NAS bucket (FlexCache duality — **separate mechanisms** from the S3 Access Point) can be used on FSx for ONTAP | **regular volume: works / FlexCache: works with `-is-s3-enabled true`** | [All-directions comparison](verification/cross-protocol-directions.md). On a regular volume, NFS write to ONTAP S3 `GetObject` succeeded (the S3 user can be created through the CLI). On a FlexCache volume `GetObject` and `ListObjectsV2` return AccessDenied by default, and succeeded after `flexcache config modify -is-s3-enabled true` at advanced privilege (2026-08-10). ONTAP 9.18.1P3D1, FSx for ONTAP. Source: [Enable S3 access to NAS FlexCache volumes](https://docs.netapp.com/us-en/ontap/flexcache/enable-flexcache-duality.html) |
| How an object written through the S3 Access Point appears on the **FlexCache cache volume** | **verified** | [FlexCache verification record](verification/flexcache-s3ap-visibility.md). 2026-08-09, ap-northeast-1, ONTAP 9.18.1P3D1 on both clusters, over VPC peering, UNIX, NFSv3, `actimeo=0`, n=30. **S3 to FlexCache NFS is p50 8 ms** (boto3 persistent session; across three measurements it ranges from 7 to 14 ms, and the spread is the measurement method on the S3 client side). Within one session FlexCache adds +5 ms. A partial multipart is not visible until `CompleteMultipartUpload`. A deletion propagates in 9 ms |
| The mapping between security style and fan-out protocol, and its inheritance at cache creation | unverified | The basis is Azure NetApp Files' cache volume requirements. Whether the same rule holds on this architecture's main path has not been confirmed ([decisions that come first](design-first-decisions.md)) |
| Whether Cloud Volumes ONTAP / ONTAP Select / Azure NetApp Files / Google Cloud NetApp Volumes can be the cache when FSx for ONTAP is the origin | unconfirmed | Not listed in AWS's supported configuration table |
| Behaviour as the number of caches per origin grows | unverified | AWS documentation recommends write-around above 10 origin volumes, which may bear on how many fan-out targets to design for |
| The relationship between ONTAP 9.18.1 FlexCache duality and attaching an S3 Access Point to a volume | treated as separate mechanisms | The implementer and the enabling procedure both differ. The support status of one is never used as evidence for the other. This architecture uses neither, so there is no design impact |
| Performance characteristics on each platform | not measured | If measured, state the environment, object size, concurrency and throughput configuration alongside |
| Cost | not measured | State a sample run and a production estimate separately |
| Do operations through the S3 Access Point raise an **FPolicy** notification? | Verified (they do not) | [Verification record](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/errata-fpolicy-s3ap-coverage.en.md). 2026-08-26, ap-northeast-1, ONTAP 9.18.1P3D1. With both UNIX and WINDOWS identity: 0 over a 90-second quiet window, 0 across 9 S3 Access Point data-plane calls, and the file-protocol control on the same volume did fire. An FPolicy event accepts only `cifs`, `nfsv3` or `nfsv4`; `s3` returns HTTP 400 |
| Can **FPolicy `mandatory`** block an operation through the S3 Access Point? | Verified (it cannot) | Same record. Under a synchronous engine with `mandatory=true`, an NFSv3 write is denied with `Permission denied` while PUT, GET, LIST and DELETE through the access point on the same volume all succeed. Disabling the policy lets the identical NFS write through, which is the control |
| Are operations through the S3 Access Point recorded in the **ONTAP native audit log**? | Verified (they are) | Same record. Recorded as `Source=HTTP` (object operations) and `Source=S3` (LIST). But `SubjectUserName` and `SubjectDomainName` are `Not Present` and `SubjectIP` is an AWS service-side address, so **the requester is not recorded**. `HeadObject` produced nothing across six calls. An audit ACE (SACL) is required |
| Does **ARP** detect writes through the S3 Access Point? | Verified (it does) | Same record. ARP 5.0, the generation that needs no learning period. 150 high-entropy files written through the access point were recorded as suspects with reason `High Entropy`, and `attack_probability` reached `moderate`. **`attack_probability` lags the writes by more than ten minutes**, so reading `none` over a short window is a false negative. **Blocking by ARP was not measured** |
| Do FPolicy, auditing or ARP fire on the **cache side**? | Unverified | All of the above was observed on the origin. Writes in this architecture arrive at the origin, so cache-side behaviour remains a separate question |
| Do qtrees, quotas, FlexClone, FlexGroup and a FlexGroup clone work on a volume with an access point attached? | Verified (all of them do) | [Interoperability](reference/limits/s3ap-interoperability.md). 2026-08-26, ap-northeast-1, ONTAP 9.18.1P3D1, SINGLE_AZ_1 / 128 MBps. FlexClone at both volume and file granularity. **The four items NetApp records as unsupported for ONTAP S3 do not appear as restrictions on this path.** The real trap is an NTFS volume + UNIX identity on an SVM with no CIFS server: the attachment reaches `AVAILABLE` and then every data operation returns `AccessDenied` |
| Can the outcome of a file-granularity FlexClone (`POST /api/storage/file/clone`) be judged from the API response? | Verified (it cannot) | Same record. It returns 202 and a job UUID, but the UUID resolves to `404 entry doesn't exist` and appears in none of the 166 visible jobs. **Control:** the same `fsxadmin` retrieves volume-create and volume-clone jobs as `state=success`. A call with a non-existent destination directory also returns 202 and creates nothing. Judge by the destination file |
| How long does a volume created through the ONTAP API take to appear in the AWS API? | Verified (range only; no upper bound established) | Same record. Polled every 20 s with no gaps: a FlexGroup at 599 s, a FlexClone volume at 1,177 s. A separate run was still absent at 1,258 s (the series has a hole). **The three disagree, so this is not an upper bound.** AWS documents "several minutes" |

## How performance and cost figures are handled

A figure that was not measured is not written. A figure that was measured is written with all of the
following:

- the date measured
- the Region
- the ONTAP version
- the file system generation, configuration and throughput setting
- the object size and concurrency
- **the kind of payload** (incompressible, or compressible) and the volume's inline efficiency setting
- **the SSD IOPS setting** (`AUTOMATIC` or `USER_PROVISIONED`, and the value)
- **the client-side mount options** (for NFS, whether `nconnect` is set)
- what was measured (client side, a service metric, or an ONTAP counter)

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

### Why stating the payload is required

**The kind of payload** was added to that list afterwards, and the reason is an actual result.

**A figure measured with a compressible payload cannot be compared against a storage-side limit.**
With inline compression, dedup and compaction enabled on the volume, `/dev/zero` and a repeated
single byte never reach the disks, and a read of them is reconstructed rather than served. In the
measurements, **a 280 GiB read came back at 1.5 times the step's disk throughput and 4 times the
default level.**

So every figure in this table is one of two kinds.

| Kind | What it may be compared against |
|---|---|
| Incompressible (`--body random`, an AES-CTR block) | A storage-side limit |
| Compressible (`--body fill`, `/dev/zero`) | **Only other figures collapsed the same way.** Never read as a share of a limit |

**As things stand, only part of the 2048 MBps step has been re-measured incompressibly.** The
128 MBps step and the FlexCache side still rest on compressible payloads, and the rows concerned say
so.

## Measurements still outstanding, in priority order

**This list was replaced on 2026-09-02, after A to I were all carried out.** The record is
[in Japanese](../ja/verification/throughput-iops-concurrency.md#残していた-9-件を測ったこの記録の数値を-5-つ訂正します) (Japanese).
**Five of the nine corrected a figure that had been published above.**

| # | Item | Result |
|---|---|---|
| A | A control with the payload as the only variable | **Done.** On writes it changes **0.5% (S3) and 4.7% (NFS)**. **The earlier "at least 17%" was wrong and is withdrawn.** Reads change by a factor of four; the asymmetry follows from writes actually sending the bytes while reads can be reconstructed before they are returned |
| B | Re-measure the 128 MBps step incompressibly | **Done.** warm 297.8 against cold 297.2, **a ratio of 1.00.** "warm 1164.1 against cold 751.0, ratio 1.55" is withdrawn |
| C | Re-measure the FlexCache side incompressibly | **Done.** Resident 882.7 to 907.1 against a direct origin read of 383.3, so **FlexCache is 2.31 times faster.** "53% of the origin" had it backwards |
| D | Re-measure small-object IOPS at 40,000 SSD IOPS | **Done.** With the step 16 times higher and SSD IOPS 13 times higher, **not one of the six points rose and writes fell 25%.** The earlier judgement stands |
| E | How to restore inline compression | **Done. It can be restored.** `{"efficiency":{"compression":"inline"}}` then `{"efficiency":{"dedupe":"both"}}` on the documented endpoint. **The condition is that `efficiency.op_state` is `idle`.** The private CLI cannot express it |
| F | Whether S3 Files hits the single-flow limit | **Done. It does not.** Reads reach **451.3 MB/s** at 8 streams and do not rise at 16. 450 MB/s is 3.6 Gbps, below the single-flow limit. The local `efs-proxy` is what stops it (67.3% CPU at 16 streams). The mount's peer is **127.0.0.1**, so `nconnect` structurally cannot reach the service link, and requesting it **hangs the mount** |
| G | Extend the client ladder past four | **Done. No bend through eight.** Writes 8.23x, reads 8.04x, per-host unchanged, 4,783.2 MB/s in total at eight hosts -- 38.3 Gbps. **Each host used its own prefix, so the per-prefix request limit was not tested** |
| H | The part of the 41% inside ONTAP | **Done. It was observable after all.** Not through the ONTAP REST API, but **CloudWatch publishes `CPUUtilization`.** At 417 MB/s through the S3 Access Point the CPU is 21-24%; at 800 MB/s over NFS it is 18-23%. **Twice the throughput at the same CPU, so the cost is outside ONTAP** |
| I | Time-of-day and day-to-day repeatability | **Done, and the result is a caution.** The same environment and conditions repeat to **within 0.2%** (four replicate pairs). The single-flow ceiling also reproduced on a different day and a different file system. But **the 280 GiB read went 2,042.1 to 2,667.2, up 30.6%, and the "99.7% of the step" coincidence did not reproduce** |

**Newly opened**

| Item | Why it is needed | Scale |
|---|---|---|
| Read at least twice the cache in one pass | 280 GiB exceeds this step's 238 GiB cache by only 18%, and in the measurement **98.5 to 99.9% of the bytes never reached the disks.** Measuring the disk path needs a volume of 700 GiB or more and a read of 480 GiB or more. **So the 7.14x from SSD IOPS stands as an observation with no established mechanism** | One file system, a volume of 700 GiB or more |
| Vary only the run duration | Where the 16% between 497.1 (30 s) and 415 (60-90 s) comes from. The payload has been ruled out | One file system, about 15 minutes |
| FlexCache incompressibly at the 2048 MBps step | C was measured with both sides at 128 MBps. Raising the origin puts a direct origin read in the 2,000 MB/s range, so **"FlexCache is 2.31 times faster" may invert with the step** | Two file systems |
| Burst balance at the 128 MBps step | Incompressible warm and cold both land at 297-317, consistent with that step's disk-throughput burst range of 128-600 MBps. **The burst balance was not read directly** | Existing environment |

**J. The irreversible family is deliberately not measured.** SnapLock, snapshot locking, S3 Object
Lock. **Not enabled without an instruction naming the retention value.** In the sibling repository a
128 MiB SnapLock audit log volume made an entire file system undeletable for six months and produced
no usable finding. **A verification environment is not the place for an irreversible operation; it is
the worst place for one.**

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
