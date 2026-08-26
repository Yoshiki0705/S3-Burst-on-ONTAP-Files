# Do ONTAP features work on the S3 Access Point path

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/limits/s3ap-interoperability.md) | [English](s3ap-interoperability.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

There is one question. **On an FSx for ONTAP volume with an S3 Access Point attached, do ONTAP
features work?** If they do not, what fails and how?

The measurements answer it. **Everything measured worked.**

| ONTAP feature | Result on the S3 Access Point path | Stage |
|---|---|---|
| Qtree | Can be created. Appears as an S3 prefix, and an object PUT into it lands inside the qtree | verified |
| Quota | A tree quota on the qtree refuses an S3 PUT | verified |
| FlexClone (volume granularity) | The clone can be made, and **the clone itself can take an S3 Access Point** | verified |
| FlexClone (file granularity) | A file written over S3 can be cloned, and **the clone is visible as an object through the access point** | verified |
| FlexGroup volume | **An S3 Access Point can be attached.** PUT / GET / LIST and multipart all work | verified |
| Clone of a FlexGroup | **The clone can be made** (from a FlexGroup carrying an S3 Access Point) | verified |

All measured 2026-08-26, ap-northeast-1, ONTAP 9.18.1P3D1, SINGLE_AZ_1 / 128 MBps. Procedure and
controls below.

## Where the question came from

NetApp publishes
[ONTAP S3 interoperability](https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-interoperability-concept.html),
which records Qtrees, Quotas, FlexClone, and a volume clone of a FlexGroup volume containing ONTAP S3
buckets as not supported for the **ONTAP S3 server** — the mechanism with which ONTAP serves buckets.

The FSx for ONTAP S3 Access Point is an AWS mechanism, and what it attaches to is a **volume**, not a
bucket. Attaching one stands up an ONTAP S3 server on the SVM, and I/O through the access point goes
through ONTAP's S3 protocol stack (measured). So the same restrictions could plausibly have appeared.
**They did not.**

That table is treated only as the origin of the question. **"Not supported for ONTAP S3, therefore
not supported here" is not a reading the measurements allow.** The reverse is equally unavailable: a
"supported" row in that table is not evidence about this path either.

FPolicy and auditing were settled by a separate measurement, and there the result did match NetApp's
statement.

| Mechanism | On the S3 Access Point path |
|---|---|
| FPolicy | **No notification is raised, and a synchronous `mandatory` policy does not block it either** (NetApp also records ONTAP S3 as unsupported) |
| ONTAP native audit log | **Recorded** (object operations as `Source=HTTP`, LIST as `Source=S3`). The requester is not retained |
| ARP (version 5.0) | **Detects** |

So "ONTAP features do not work on this path" is a false generalisation too. **The answer differs per
mechanism.**

## What was measured, and how

Environment as above. Two 1 GiB UNIX-security-style volumes (one with an access point, one as the
control), one NTFS volume, one 400 GiB FlexGroup. Identity UNIX / `root`. All throwaway, all deleted
afterwards.

### Qtree

| Step | Result |
|---|---|
| Create a qtree in the volume with an access point | Succeeded |
| Control: the same qtree in the volume with no access point | Succeeded. **No difference** |
| `list-objects-v2 --delimiter /` | The qtree appears in CommonPrefixes |
| PUT into the qtree prefix | Succeeded |
| Inspect the qtree contents from ONTAP | The written file is inside the qtree directory |

Incidental finding: a volume with an access point attached carries an internal
`____NTAP_S3_MAPPING` directory at its root, created by the S3 layer. It is visible over NFS and SMB,
so anyone who inspects a collect-layer volume by hand will see it.

### Quota

| Step | Result |
|---|---|
| Set a tree quota on the qtree (space 1 MiB, files 10) and enable quotas on the volume | Succeeded |
| `quota report` | The rule is active, and **the file written over S3 is counted in files used** |
| PUT 15 small objects | **8 succeeded, 7 refused.** files used stopped at exactly 10/10 |
| What the S3 client received on refusal | HTTP 507 `InsufficientCapacity` / `Maximum storage capacity of file system has been reached.` |
| Control: raise the files limit 10 → 50 and re-PUT the refused key with the same body | **Succeeded** |

The control carries the conclusion. Raising the limit alone made the identical PUT succeed, so the
refusal was the quota, not a capacity shortage or a permissions artefact.

**That the error mis-describes its cause matters to the design.** The file system was not full; a
qtree file-count quota was reached. An operator who sees a 507 and "maximum storage capacity of file
system" will consider growing the file system. If quotas are used here, the runbook has to say what
that response actually means.

### FlexClone

Both granularities were measured, and both against a volume with an access point attached.

#### Volume granularity

| Step | Result |
|---|---|
| FlexClone of the volume with an access point | Succeeded. `is_flexclone=true`, `online`, parent recorded |
| Control: FlexClone of the volume with no access point | Succeeded. **No difference** |
| Contents of the clone | The objects written over S3, the qtree contents and `____NTAP_S3_MAPPING`, all present |
| **Attach an access point to the clone** | **Succeeded. `Lifecycle=AVAILABLE`** |
| LIST / GET through the clone's own access point | **Succeeded. The sha256 of a 256 MiB file matched the parent** |
| PUT through the clone's own access point | **Succeeded, and the object does not appear on the parent** (`HeadObject` returns 404) |
| The point in time the clone shows | The base snapshot. A file created on the parent after the snapshot is absent from the clone |

A copy of the collected data can be made without copying the data. It is readable over NFS and SMB,
and also over S3 through the clone's own access point. Writes are independent of the parent.

#### File granularity

`POST /api/storage/file/clone` — FlexClone at file granularity — was run against files written over
S3.

| Target | Result |
|---|---|
| A 256 MiB file at the volume root | Succeeded |
| A file inside a prefix (`/sub/nested.txt`) | Succeeded |
| A clone of a clone | Succeeded |
| A destination directory that does not exist | **Failed, but the response is 202 and the error is not observable** (below) |
| A destination directory created beforehand | Succeeded |

Block sharing was confirmed from the space counters. **Logical 1,350,942,720 B against physical
277,200,896 B.** Cloning a 256 MiB file four times added about 23 MB of physical space. These are not
copies.

What matters is the result seen from S3.

| Check | Result |
|---|---|
| Does a file clone appear in LIST through the access point | **It does, with the right size** |
| `HeadObject` | **Succeeded. `StorageClass=FSX_ONTAP`** |
| sha256 of the four clones and the original, read over S3 | **All five matched** |
| The clone inside a prefix (`sub/nested-clone.txt`) | **Appears, content matches** |
| Overwrite a clone with an S3 PUT | **Succeeded. The source file is unchanged** |

**A file clone is an ordinary object from the S3 side.** A file S3 never wrote is visible, readable
and overwritable through the access point.

**Failure, however, is not observable.** `POST /api/storage/file/clone` returns 202 and a job UUID,
and that UUID cannot be resolved.

| Call | Retrieving the job UUID |
|---|---|
| `POST /storage/file/clone` | **404 `entry doesn't exist`.** Searching all 166 visible jobs found none |
| Control: `POST /storage/volumes` (volume create) | **200, `state=success`** |
| Control: `POST /storage/volumes` (volume clone) | **200, `state=success`** |

The controls rule out a permissions problem. **Only the file-granularity clone leaves no job.** The
call with a non-existent destination directory also returned 202, and nothing had been created.
**Success or failure has to be judged by inspecting the destination file.**

### FlexGroup

Creation has conditions, learned by failing in order.

| Step | Result |
|---|---|
| Create with default parameters | Failed. `Volumes of this type must be at least 50GB` |
| Retry at 50 GiB | Failed. `Aggregates not matching FabricPool requirements: aggr1` |
| Retry with the aggregate named explicitly | Failed. `Minimum size is "400GB"` (8 constituents × 50 GiB) |
| 400 GiB, explicit aggregate, `tiering.policy=none`, thin | **Succeeded** |

The FSx for ONTAP API offers no way to create a FlexGroup, so it is created on the ONTAP side. What
follows is the point.

| Step | Result |
|---|---|
| Appears on the FSx for ONTAP side as `VolumeStyle=FLEXGROUP` | **It does, with an `fsvol-` identifier** |
| **Attach an S3 Access Point to the FlexGroup** | **Succeeded. `Lifecycle=AVAILABLE`** |
| PUT / GET / LIST | **Succeeded. The GET content matched** |
| 12 MiB multipart upload | **Succeeded. `StorageClass=FSX_ONTAP`** |
| Snapshot the FlexGroup | Succeeded |
| **Clone that FlexGroup** | **Succeeded. `style=flexgroup`, `is_flexclone=true`, online** |

That is the row NetApp records as "volume clone of the FlexGroup volume containing ONTAP S3 buckets:
not supported", and a clone of a FlexGroup carrying an S3 Access Point was created.

## What actually failed on this path

The constraints were not on NetApp's side of the table. **Within what was measured, these three are
the real traps.**

### A security-style and identity mismatch fails after the attachment succeeds

| Step | Result |
|---|---|
| Attach with an NTFS-security-style volume + UNIX identity (`root`) | **Succeeded. `Lifecycle=AVAILABLE`** |
| PUT through that access point | **Refused. `AccessDenied`, body only `Access Denied`** |
| Control: same identity, same caller, UNIX volume | PUT / GET / LIST all succeeded |
| CIFS server on this SVM | **None.** The UNIX-to-Windows mapping cannot resolve |

**`AVAILABLE` does not mean the file system layer is healthy.** Attachable and usable are different
properties: IAM and the access point policy are both passed, and the file system layer refuses after
that. The error body is only `Access Denied` and does not name the layer. A refusal at the identity
layer says `no identity-based policy allows ...` instead, so **the difference in the body is the
signal.**

Trying WINDOWS identity on the same SVM does not even complete the attachment.

| Step | Result |
|---|---|
| Attach with WINDOWS identity on an SVM with no CIFS server | **Failed. `did not stabilize` (`NotStabilized`), stack rolled back** |
| Whether an attachment survives the rollback | **It does not.** Nothing was orphaned |

### Waiting for something created in ONTAP to appear on the AWS side

A volume created through the ONTAP API is not immediately in the AWS-side `describe-volumes`. Without
an `fsvol-` identifier, neither `AWS::FSx::S3AccessPointAttachment` nor
`create-and-attach-s3-access-point` can reference it.

| Measurement | Result |
|---|---|
| FlexGroup, polled every 20 s with no gaps | **Appeared at 599 s (about 10 min)**, with an `fsvol-` identifier |
| A FlexClone volume, polled every 20 s with no gaps | **Appeared at 1,177 s (about 19.6 min)**, with an `fsvol-` identifier |
| A separate run (FlexVol and FlexClone) | Still absent at 1,258 s (about 21 min). The series after that has a hole, so the appearance time is unknown |

**The three observations disagree, so this is not an upper bound.** Ten minutes, 19.6 minutes, and
one run still absent at 21. **The order of magnitude is tens of minutes**, which is not enough to
bake a fixed wait into a design. AWS documents the following, and the measurement is longer than its
"several minutes".

> Amazon FSx periodically syncs with ONTAP to ensure consistency. If you create or modify volumes <!-- allow:naming verbatim AWS documentation; the wording is theirs -->
> using NetApp applications, it may take up to several minutes for these changes to be reflected in
> the AWS Management Console, AWS CLI, API and SDKs.
>
> — [Managing FSx for ONTAP resources using NetApp applications](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-resources-ontap-apps.html)

**This delay was initially misread as absence.** From an observation of about 2.5 minutes came the
conclusion that a volume created through the ONTAP API has no `fsvol-` identifier, and from there
that neither a clone nor a FlexGroup could take an access point. Both were wrong: wait, and it
appears, and it attaches. Two and a half minutes is inside AWS's "several minutes", and **"not there
yet" had not been separated from "never appears".**

### The junction path lags in the other direction too

| Step | Result |
|---|---|
| Set a junction path on the clone from the ONTAP side | Succeeded, `online` |
| Attach an access point immediately afterwards | **Failed.** `Amazon FSx is unable to attach S3access point because the volume is not mounted.` (the service's own wording) <!-- allow:naming verbatim service error message --> |
| The AWS-side `JunctionPath` at that moment | `None`. Set in ONTAP, not yet visible to AWS |
| Set it with `aws fsx update-volume` instead | Visible on the AWS side in about 40 s |
| Retry the attachment after that | **Succeeded** |

**The error message was telling the truth.** From the AWS side the volume was not mounted. What was
wrong was the assumption that setting it in ONTAP made it visible to AWS. **Write through the AWS
management plane wherever possible:** the same setting was still unreflected two minutes after being
made through ONTAP, and took about 40 seconds through the FSx for ONTAP API.

### Teardown: a delete that silently reverts

| Step | Result |
|---|---|
| `delete-volume` | Returns `DELETING`, then silently goes back to `CREATED`. Both times |
| Where the reason lives | Only in `LifecycleTransitionReason` on `describe-volumes`: `Failed to delete volume because it has one or more clones.` |
| The actual clones | Already deleted. They were sitting in ONTAP's **volume recovery queue** |
| The flag on the parent | `clone.has_flexclone` still `true` |
| Purge the recovery queue | The flag went `false`, and the same `delete-volume` worked |

A teardown that watches only the AWS-side API gets stuck. The recovery queue appears in neither the
console nor the FSx for ONTAP API. **A success response is not evidence of success:** `DELETING` came
back both times, so judge by the state a few tens of seconds later.

## Not yet measured

| Item | State |
|---|---|
| FlexClone at LUN granularity | Unverified. Creating a LUN requires an iSCSI configuration, which is not on this architecture's path |
| Upper bound on the ONTAP-to-AWS reflection time | Unverified. The three observations disagree |
| FabricPool tiering | Unverified. Needs a different aggregate configuration |
| QoS | Unverified |
| Deduplication / compression / compaction | Unverified |
| SnapMirror | Unverified |
| SnapLock / Object Lock | Unverified. **Irreversible**; not enabled without an instruction naming the retention value |
| Attaching on the cache side | Unverified. Requires a cluster peer and an SVM peer, which this repository's templates do not create. Note that ONTAP FlexCache duality and attaching an S3 Access Point to a volume are separate mechanisms, so neither one's support status is evidence about the other |
| Vscan | Unverified |

"Unverified" is not "cannot be done". Every item in the opening table turned out that way, so on this
path **nothing is known until it is measured.**

## Sources

| Source | About |
|---|---|
| [Access point restrictions](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html) | Same Region, same account, ONTAP 9.17.1 or later |
| [Access point troubleshooting](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/troubleshooting-access-points-for-fsxn.html) | The volume has to be mounted |
| [Access point compatibility](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html) | Which S3 APIs are supported |
| [Managing resources through NetApp applications](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/managing-resources-ontap-apps.html) | The delay before an ONTAP-side change reaches the AWS side |
| [ONTAP S3 interoperability](https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-interoperability-concept.html) | A statement about the ONTAP S3 server. The origin of the question, not a conclusion about this path |
| [S3 Access Point limits](s3-access-point.md) | The constraints this repository has collected, with stages |

## Related documents

| Document | Contents |
|---|---|
| [Object access on ONTAP](../glossary/object-access-on-ontap.md) | The mechanisms named "S3 over files", and which inferences do not hold |
| [S3 Access Point limits](s3-access-point.md) | Limits with source and stage |
| [Verification status](../../verification-status.md) | The four stages and the current state of each claim |
| [The s3-access-point-attachment pattern](../../../../patterns/collect/s3-access-point-attachment/README.md) | The template that manages an access point on its own |

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/limits/s3ap-interoperability.md) | [English](s3ap-interoperability.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
