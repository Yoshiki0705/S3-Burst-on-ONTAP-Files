# PoC checklist

<!-- lang-switcher:start -->
🌐 [日本語](../ja/poc-checklist.md) | [English](poc-checklist.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

<!-- Provenance and divergence
     This started from the sibling repository FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns,
     docs/flexcache-poc-checklist.md.
     https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/flexcache-poc-checklist.md

     Divergences:
     1. The order was rearranged from "cheapest first" to "whatever blocks the design until it is
        answered, first".
     2. Rather than collect-layer-only or serve-layer-only, phase 1 is the end to end path: write
        through the S3 Access Point and read over NFS / SMB. That is where this architecture's core
        claim sits.
     3. The open question the original listed — whether an S3 Access Point can be attached to a
        cache volume — was dropped. This architecture exposes no object access on the cache side, so
        there is nothing to confirm.
     4. Success criteria are written as "what cannot be written until this is answered" per item,
        rather than as an empty template. An empty KPI table stays empty.
-->

The order is not by cost but by **what blocks the design until it is answered**. Do not skip 1 and
jump to 4 or 5.

The stage of each item corresponds to [verification status](verification-status.md).

## Decide pass and fail before measuring

**Decide afterwards and whatever came out becomes a pass.** Write these three down before starting a
phase, and keep them with the result. A blank among them means the phase is not ready to start.

| To decide | How to write it | What a blank costs |
|---|---|---|
| What is measured | One figure or one boolean. Not "is it fast" but "p50 from the `PutObject` response to a successful `open` over NFS on the cache side" | The definition moves between runs and nothing is comparable |
| The pass line | A threshold drawn from the workload, with the reasoning. "A replay reads 200 files, so above 50 ms per file the preparation exceeds ten seconds, which we cannot absorb" | Whatever came out reads as a pass |
| What happens on a fail | The move to make, and who decides if there is none | A fail turns into "measure it again" |

**Do not adopt this repository's figures as your pass line.** Phase 1's p50 8 ms was measured in one
Region over VPC peering under sub-millisecond network latency; a path that reaches a site is a
different number ([verification status](verification-status.md)). Use it as a reference by running
the same procedure in your own environment and comparing your own figure against it.

**Not being able to measure is also a result.** "Peering could not be established, so phase 2 was
never entered" is stronger information than "unverified", and it saves the time of the next person
down the same path.

## 1. Whether something written through the S3 Access Point can be read on the cache side

Environment needed: two existing FSx for ONTAP file systems, or FSx for ONTAP and on-premises ONTAP.
While this is open, "can the site read it as soon as it is collected" has no answer. It is the core of
the architecture.

**With two FSx for ONTAP file systems this is verified and the checks below are done**
([FlexCache verification record](verification/flexcache-s3ap-visibility.md); NFSv3 and SMB, UNIX,
64 B, `actimeo=0`). **They still apply as written when confirming it in your own environment, or with
the cache on on-premises ONTAP.** The conditions that remain are under "The scope of the central
claim" in [verification status](verification-status.md).

- [ ] Attach an S3 Access Point to the Origin volume
- [ ] Write an object with `PutObject`
- [ ] Confirm the same file is visible from the NFS / SMB mount on the cache side
- [ ] Measure how long it takes from the write until it is readable (record the date, Region, ONTAP
      version, object size and cache settings)
- [ ] Confirm what is visible from the cache side partway through a multipart upload (whether a
      partial file appears, or nothing until `CompleteMultipartUpload`)
- [ ] Confirm how a deletion on the origin side appears on the cache side
- [ ] Confirm how an overwrite propagates
- [x] Try `UploadPartCopy` with **a source inside the same access point** → **`NoSuchKey`**
      ([measurement record](../ja/verification/s3ap-operations.md) (Japanese), 2026-08-19).
      `CopyObject` given the identical `CopySource` succeeds in the same run, which is the control.
      AWS documents same-AP copies as supported
- [ ] Try `UploadPartCopy` with a source in a standard S3 bucket. **Whether `UploadPartCopy` is
      supported at all is still undecided**, because no other source namespace copies successfully
      on this endpoint

Record results in the table in [verification status](verification-status.md). When writing a figure,
always state the environment with it.

## 2. FlexCache from an FSx for ONTAP origin to an on-premises ONTAP cache

Environment needed: peering with on-premises ONTAP.
This is the main path. AWS states it as a supported configuration, but it has not been confirmed on
hardware.

**The peering path is outside this repository.** Neither the Terraform nor the CloudFormation
creates a cluster or SVM peer. That absence is the most common reason a FlexCache creation fails, so
settle the preconditions first ([deploying the on-premises side](deployment/onprem-terraform.md)).

Preconditions, before peering

- [ ] Check the on-premises ONTAP version (FlexCache needs 9.5 or later, write-back 9.15.1 or later;
      [support matrix](support-matrix.md))
- [ ] Confirm both clusters have intercluster LIFs and can reach each other
- [ ] Confirm the ports ONTAP cluster peering uses are open along the path -- both the AWS security
      group and the firewall at the site
- [ ] Check the MTU along the path. An uneven MTU over Direct Connect or VPN stalls large reads
- [ ] Where the path crosses another cloud, confirm first that the segment connects privately.
      **There are two ways that is decided** — the published Region pairs for a managed service,
      overlapping locations for a partner route
      ([cross-cloud connectivity](multi-cloud-connectivity.md))
- [ ] Measure the round-trip latency of the path first. **It is the baseline for comparing against
      phase 1**, whose figures were taken under sub-millisecond latency, and it is what explains the
      difference
- [ ] Confirm the cache volume can be created as a FlexGroup, which is what a cache is

Steps

- [ ] Establish the cluster peer and the SVM peer
- [ ] Create the Cache volume
- [ ] Confirm whether the origin's security style is inherited by the cache
      (the unconfirmed item in [decisions that come first](design-first-decisions.md))
- [ ] Confirm both UNIX + NFS and NTFS + SMB (mixed is out of scope, being not recommended)
- [ ] Confirm that only the range actually read is transferred
- [ ] **Repeat phase 1's measurement over this path.** Same script, same object size, same
      `actimeo`. Change the conditions and there is no telling whether the difference is the path or
      the settings
- [ ] Record that a second read is faster, meaning it landed in the cache, and by how much
- [ ] Confirm the deletion order (whether it releases in the order cache, SVM peer, cluster peer).
      **Do not delete the origin side while a cache still exists**

## 3. Behaviour as the number of fan-out targets grows

Environment needed: several FSx for ONTAP file systems. This bears on how many fan-out targets to
design for.

- [ ] Add caches incrementally
- [ ] Confirm whether behaviour changes either side of the boundary at which AWS documentation
      recommends write-around (above 10 origin volumes)
- [ ] Record the load on the origin side

## 4. Whether other platforms can be the cache

Environment needed: costs on another cloud. This is the item that closes the "unconfirmed" rows in the
portability table.

- [ ] Whether Cloud Volumes ONTAP can be the cache
- [ ] Whether ONTAP Select can be the cache
- [ ] Whether an Azure NetApp Files cache volume can take FSx for ONTAP as its origin
- [ ] Whether Google Cloud NetApp Volumes can be the cache

**The reverse direction is a separate item.** All four above have FSx for ONTAP as the origin;
another cloud's file storage as the origin sits outside the supported configuration table
([portability](portability.md)).

- [ ] Confirm first whether the far side exposes cluster peering externally. **If it does not, this
      stops before FlexCache can be measured at all**, so it is the first branch
- [ ] Whether Google Cloud NetApp Volumes can be the origin with FSx for ONTAP as the cache
- [ ] Whether Azure NetApp Files can be the origin with FSx for ONTAP as the cache

**File storage that is not ONTAP is out of scope for this phase.** Google Cloud Filestore, Azure
Managed Lustre, Azure Blob NFS and OCI File Storage do not hold as a mechanism, so there is no
"unconfirmed" for a measurement to close
([cross-cloud connectivity](multi-cloud-connectivity.md)).

Every result goes into the table in [portability](portability.md). Record the negative results too.

## 5. FlexCache duality

Environment needed: ONTAP 9.18.1.

This is not a premise of the architecture. It and attaching an S3 Access Point to a volume are
**separate mechanisms**, so confirming it produces no evidence about the collect layer. Leave it last.

- [x] Confirm what it can do (not as a premise for adopting it here, but to keep the distinction
      intact). A NAS bucket on a regular volume works, and on a FlexCache volume `GetObject` and
      `ListObjectsV2` succeeded after `flexcache config modify -is-s3-enabled true` at advanced
      privilege ([all directions](verification/cross-protocol-directions.md)).
      **This result is not evidence about what the S3 Access Point supports. They are separate
      mechanisms**

## How to write the record

- Put the environment first (Region, ONTAP version, file system generation and configuration,
  throughput setting)
- Write what was confirmed, what could not be confirmed, and what was not attempted, as three
  separate things
- Keep the failed observations. "It did not work" is stronger information than "unconfirmed"
- Do not write personal names, account IDs, internal IPs or support case numbers

## On irreversible operations

A PoC is the worst place to put an irreversible operation. A verification resource that cannot be
deleted becomes a long-lived bill and blocks everything sitting beside it.

**A feature whose purpose is to remove your ability to delete — SnapLock, tamperproof snapshots,
Object Lock — is not enabled without an instruction that names the retention period.** The detail is
in the irreversible operations section of [AGENTS.md](../../AGENTS.md).

## Related documents

| Document | Contents |
|---|---|
| [Verification status](verification-status.md) | Where results are recorded |
| [Decisions that come first](design-first-decisions.md) | The unconfirmed items checked in phase 2 |
| [Support matrix](support-matrix.md) | The support status each item presupposes |
| [Portability](portability.md) | Where phase 4 results land |
| [Cross-cloud connectivity](multi-cloud-connectivity.md) | What a path crossing another cloud presupposes |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/poc-checklist.md) | [English](poc-checklist.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
