# Reading from the setup you already run

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/decision-trees/from-your-current-setup.md) | [English](from-your-current-setup.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

**Whether this architecture applies to you is not decided by product names.** It is decided by where
the data lands, where it is read from, and what carries it between the two.

Below are five **shapes**. No product is named, because the same shape holds across several products,
and **which shape you are in decides more than which product you use.** Once the shape is clear, go
into the branches in [the selection flowchart](choosing-this-architecture.md).

**Each row also states this architecture's own excluding conditions.** Stating only one side leaves
nothing to choose between.

## Shape 1 — collection into objects, and reads through a copy

**What you run now.** An application or a device writes into object storage, the consuming side wants
files, so a transfer job or a sync process copies into file storage. **Reads wait for the copy.**

| Item | Detail |
|---|---|
| What this architecture replaces | **The copy step itself.** Collection stays on the S3 API, reads become NFS / SMB through FlexCache, and no job sits between them |
| What it does not replace | **Object-storage features.** Versioning, lifecycle and event notifications are unavailable on the S3 Access Point path. **Event-driven work has no ONTAP-side substitute either** — FPolicy does not fire on this path |
| Confirm first | Whether the object names can be expressed on NAS (255 characters, hierarchy, rejected characters) |
| Unsuited when | **Collection is many small objects.** Measured, it flattens at roughly 420 req/s writing and 600 req/s reading ([verification status](../../verification-status.md)) |

**This is the most direct shape to move from.** What is given up is the S3-specific features; what is
gained is the disappearance of the copy step.

## Shape 2 — file storage per site, with the whole dataset replicated

**What you run now.** There is file storage wherever data is read, and replication or transfer
distributes the same content. **Holding everything means paying for capacity and transfer on what is
never read.**

| Item | Detail |
|---|---|
| What this architecture replaces | **Replicating the whole dataset.** FlexCache holds **only what was actually read**, so site capacity follows the working set |
| What it does not replace | **The availability of the source of truth.** A cache is not a recovery unit. If the origin is lost the cache cannot answer ([architecture](../../architecture.md)) |
| Confirm first | **Cluster peering and SVM peering.** They are a precondition here and [the Terraform side does not create them](../../deployment/onprem-terraform.md). **This is the most common reason a FlexCache creation fails** |
| Unsuited when | **The site writes heavily.** Writes go back to the origin, so a write-led site fits a different design — making the site the source of truth, or bidirectional replication |

**The first read is slower.** Measured in the same environment, reading data that is not cached came
out at **one 2.88th** of the cached figure ([architecture](../../architecture.md)). **For data read
only once, that cost is never amortised.**

## Shape 3 — file storage as the source of truth, with objects downstream

**What you run now.** The source of truth is NAS, and data is pushed out to object storage for
analysis or distribution.

| Item | Detail |
|---|---|
| Does this architecture fit | **No.** This architecture runs in over the S3 API and out as files. For the other direction, ONTAP's own S3 support or tiering is more direct |
| The part that is still usable | **Using FlexCache for read distribution to sites alone** does work. The collect side does not have to be an S3 Access Point |
| Confirm first | Whether the readers are genuinely remote. **In the same place as the origin, the cache's SSD and the peering operations are cost with nothing returned** |

## Shape 4 — a transfer or sync service on a schedule

**What you run now.** A transfer service runs on a schedule, carrying data between objects and files.

| Item | Detail |
|---|---|
| What this architecture replaces | **The idea of a schedule.** With no copy, the wait is not the schedule interval but the cache filling on first read |
| What it does not replace | **What the transfer service provides.** Bandwidth control, verification, filters and reports are not in FlexCache |
| Where the decision turns | **Whether the freshness requirement is met by the schedule interval.** If it is, the transfer is enough. **"Daily is enough, so use transfer" is not a figure this repository measured** — judge from the minimum interval of the service you use |
| Unsuited when | **Collection and distribution are in the same place.** Then this architecture's distribute layer is not needed |

## Shape 5 — the consuming side asks for block storage

**What you run now.** The readers ask for block devices over iSCSI or NVMe/TCP.

| Item | Detail |
|---|---|
| Does this architecture fit | **Out of scope.** FlexCache distributes volumes; **it does not distribute LUNs or namespaces** |
| What this repository does have | Block measurements ([F-1 / F-2 / F-3](../../../ja/verification/perf-matrix-results.md#f-1-iscsi-の実測) (Japanese)). They are **figures from a client attached directly to the same file system**, not distribution to a site |
| Read them with this in mind | They are raw-device figures, **not figures for a configuration carrying a file system.** The window is 300 seconds and includes burst. **The same configuration measured 2.64x apart across deployments** |

## What to decide first, whichever shape applies

**Whether the consuming site uses NFS or SMB.** It pairs with the origin's security style
(UNIX / NTFS), and **it is decided before the origin volume is created.**

**The cache inherits it from the origin. Measured**
([the inheritance record](../../../ja/verification/flexcache-security-style-inheritance.md) (Japanese),
FSx for ONTAP on both sides). **And there is no path to choose again on the cache side** — no argument
takes it at creation, and ONTAP refuses to change it afterwards. **So the reason to decide first is
not prudence; it is that there is no later.** The detail is in
[decisions that come first](../../design-first-decisions.md).

## What to read next

| Purpose | Document |
|---|---|
| Decide adoption through branches | [Selection flowchart](choosing-this-architecture.md) |
| Compare the conditions against other approaches | [Alternatives](../comparison/alternatives.md) |
| The cost breakdown | [FinOps cost structure](../comparison/finops-s3-vs-s3ap.md) |
| How far each claim has been taken | [Verification status](../../verification-status.md) |
| Actually build it | [Collect side](../../deployment/aws-cloudformation.md) / [Serve side](../../deployment/onprem-terraform.md) |

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/decision-trees/from-your-current-setup.md) | [English](from-your-current-setup.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
