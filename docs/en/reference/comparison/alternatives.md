# Comparison with the alternatives

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/comparison/alternatives.md) | [English](alternatives.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

When both S3 and file storage are needed, practice generally lands on one of the following.
All of them are reasonable choices; the problem is not the choice itself but that **the cost of it is
hard to see**.

Suited and unsuited conditions are written at the same granularity. This architecture's own unsuited
conditions go in the same column.

| Approach | Suited when | Not suited when |
|---|---|---|
| S3 alone | A new application, a flat namespace, S3 features needed (versioning, lifecycle, event notifications) | Existing NFS / SMB applications or equipment cannot be changed, POSIX semantics are needed |
| Files alone | The protocol is fixed and the collecting side is on the same network | The collecting side assumes the S3 API, or an external service has to write |
| Files copied to S3 | The target set is settled and the freshness requirement is loose (daily is enough) | Freshness is needed, the volume is large, deletions have to propagate |
| S3 behind a file gateway / FUSE | Read-centric, and the policy of making S3 the source of truth is settled | Locking or atomic rename is needed, metadata operations are frequent |
| S3 mounted as a file system with S3 Files | The consuming side is Linux compute on AWS and can install the mount helper. The policy of making S3 the source of truth is settled | Equipment that cannot be changed, SMB, NFSv3, a consuming side outside AWS. A file-system write has to reach S3 within 60 seconds. Archive storage classes have to be readable as files |
| Dual management | The uses are completely separate and never have to be reconciled | Audit obligations apply, cost reduction is required |
| Replicated to sites with SnapMirror | The site needs the whole dataset and writes there too | Full transfer is to be avoided, or there are many sites |
| **Collect over S3, serve to NFS / SMB with FlexCache (this architecture)** | Collection over S3, consumption over the existing file protocols. Consumption is read-centric. Only the range needed is placed at the site | S3-specific features are needed, NAS-unfriendly names are used heavily, S3 reads are needed on the cache side too, the write-back preconditions (ONTAP version, origin-side resources) cannot be carried |

## What each one costs you

### Making files the source of truth and copying to S3 for analysis or distribution

Replicating data on NAS to S3 with DataSync, rsync, robocopy or a bespoke ETL.

| Cost | Detail |
|---|---|
| Freshness | What is downstream is always "as of the copy". The job interval becomes the lag |
| Double capacity | Two billed copies of the same bytes. If deletion propagation is missed, the gap keeps widening |
| Divergent permissions | POSIX / NTFS ACLs on the file side, IAM and bucket policies on the S3 side. "Who can read this" cannot be answered from one place in an audit |
| Operations | Detecting sync failures, re-running partial failures, and propagating renames and deletions become permanent operational items |

### Making S3 the source of truth and substituting file access with a gateway or FUSE

| Cost | Detail |
|---|---|
| Semantic gap | Locking, atomicity of `rename`, partial updates, `stat` frequency — the expectations of POSIX / SMB do not match what an object actually is |
| Metadata performance | Degrades readily on workloads with many small files or heavy directory traversal |
| Split authentication and audit | Where AD integration or existing ACLs cannot be carried over, the permission model has to be redesigned |
| An added failure surface | The gateway layer becomes a new single point of failure and a new operational object |

### Managing both as sources of truth

| Cost | Detail |
|---|---|
| No source of truth | When a difference appears, most organisations have no rule for deciding which side is right |
| Explicability | Which side holds retention, tamper-proofing and audit logging becomes ambiguous, and it cannot be explained in an audit |
| Cost | Capacity, transfer and API requests all occur twice, and the room to reduce them is invisible |

### Mounting S3 as a file system with S3 Files

Reading and writing with file-system semantics, including locking and POSIX permissions, while
keeping S3 as the source of truth. Only the active working set is held in the performance tier, which
makes the idea close to FlexCache.

| Cost | Detail |
|---|---|
| Consuming-side prerequisites | The mount helper (included in `amazon-efs-utils`) is required. Supported compute is Amazon EC2, AWS Lambda, Amazon EKS and Amazon ECS |
| Protocol | NFSv4.1 and NFSv4.2. NFSv3 and SMB are out of scope. Locking is advisory only, and NFS ACLs and Kerberos are not supported |
| Freshness | A change on the bucket side typically reaches the file system in seconds. A change on the file-system side goes to the bucket after writes have been idle for 60 seconds |
| Preconditions | S3 versioning is mandatory on the bucket. A design for expiring noncurrent versions is needed separately |
| Conflict | If both sides change the same file, the bucket becomes authoritative and the file-system copy is moved to lost and found |
| Archive storage classes | Glacier tiers and the Intelligent-Tiering archive tiers cannot be read from the file system |
| Where it runs | Compute on AWS is the premise. It cannot be used from on-premises equipment |
| Shape of the cost | The performance tier and the read and write charges are added on top of the bucket cost for the source of truth. The threshold and expiry settings move it substantially |
| ONTAP features | ONTAP data management features such as Snapshot, FlexClone and SnapMirror are out of scope |

Costs are compared in
[FinOps cost structure](../../../ja/reference/comparison/finops-s3-vs-s3ap.md) (Japanese).
For reading large objects from Linux on AWS, it can come out cheaper than this architecture.

### Collect over S3, serve with FlexCache (this architecture)

| Cost | Detail |
|---|---|
| Supported operations | Not all of S3 is available. Event notifications, lifecycle and versioning are out of scope |
| Namespace | Object names are constrained. Not suited to workloads that use NAS-unfriendly names heavily |
| Write path | The cache is writable. The default write-around responds only once the origin has committed, so its latency is high; write-back (ONTAP 9.15.1 or later) commits on the cache and writes to the origin asynchronously ([replication with FlexCache](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)). This architecture is described on the premise that collection is consolidated on the origin through the S3 Access Point |
| Object access on the cache side | Not provided. If a site needs the S3 API, consider a different architecture |
| Version prerequisites | The collect layer needs ONTAP 9.17.1 or later. If an existing cluster is below that, an upgrade has to be considered first |
| The unverified core | The behaviour until something written is readable on the cache side is unverified ([verification status](../../verification-status.md)) |
| Ordering in the design | The consuming side's protocol has to be decided before the origin is created ([decisions that come first](../../design-first-decisions.md)) |

## Breaking the problem down by axis

Whichever approach is taken, a cost appears somewhere on the following axes.
This architecture addresses mainly 1 to 4, and does not address 5 or part of 6.

| # | Axis | What actually happens |
|---|---|---|
| 1 | Consistency and freshness | Copy lag, partial sync, deletions that do not propagate. "As of when is the data at the destination" cannot be answered |
| 2 | A single origin of permission | Two permission systems. Every review costs the work of reconciling both |
| 3 | Capacity and cost | The same data billed twice. Transfer and API request charges. A gateway that runs even when idle |
| 4 | Operational load | Monitoring and re-running sync jobs becomes routine work. During an incident, "which side do we fix" has to be decided |
| 5 | Mismatched performance characteristics | Objects are strong at large sequential reads, NAS at metadata operations and random access. Leaning to one degrades the other |
| 6 | Portability | A design leaning on cloud-specific APIs does not take the same shape on-premises or on another cloud |

## Who wants what

This is a role-based summary. It is not based on interviews with real individuals or organisations.

| Role | Requirement | The constraint they cannot give up |
|---|---|---|
| Data / AI engineer | Wants to write over the S3 API. The collecting tools and services assume S3 | No budget to rebuild the collection entry point |
| Verification facilities, production, CAE / EDA, medical imaging on the floor | NFS / SMB cannot be changed. Equipment and applications stay as they are | Swapping the protocol is not among the options |
| Security / audit | Wants to show "who can read which data" from a single basis | An architecture with two permission models is expensive to explain |
| Cost management | Wants to stop paying for double capacity. Wants the increment to be predictable | An improvement whose saving cannot be measured does not get approved |
| Infrastructure / architect | Wants to reuse the same design on-premises and on several clouds | A single-cloud-only design cannot be standardised |

That fork in the requirement — collect over S3, consume over NFS / SMB — is exactly the situation this
architecture is for.

## Related documents

| Document | Contents |
|---|---|
| [Choosing](../decision-trees/choosing-this-architecture.md) | The flowchart that turns this table into a decision |
| [FinOps cost structure](../../../ja/reference/comparison/finops-s3-vs-s3ap.md) (Japanese) | This table's "cost" broken into billing dimensions and estimated per configuration |
| [Architecture](../../architecture.md) | What this architecture solves and does not solve |
| [Verification status](../../verification-status.md) | The unverified scope |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/comparison/alternatives.md) | [English](alternatives.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
