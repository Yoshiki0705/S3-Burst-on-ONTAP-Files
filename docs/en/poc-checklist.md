# PoC checklist

<!-- lang-switcher:start -->
🌐 [日本語](../ja/poc-checklist.md) | [English](poc-checklist.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

<!-- Provenance and divergence
     This started from the sibling repository fsxn-s3ap-serverless-patterns,
     docs/flexcache-poc-checklist.md.
     https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns/blob/main/docs/flexcache-poc-checklist.md

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

## 1. Whether something written through the S3 Access Point can be read on the cache side

Environment needed: two existing FSx for ONTAP file systems, or FSx for ONTAP and on-premises ONTAP.
While this is open, "can the site read it as soon as it is collected" has no answer. It is the core of
the architecture.

- [ ] Attach an S3 Access Point to the Origin volume
- [ ] Write an object with `PutObject`
- [ ] Confirm the same file is visible from the NFS / SMB mount on the cache side
- [ ] Measure how long it takes from the write until it is readable (record the date, Region, ONTAP
      version, object size and cache settings)
- [ ] Confirm what is visible from the cache side partway through a multipart upload (whether a
      partial file appears, or nothing until `CompleteMultipartUpload`)
- [ ] Confirm how a deletion on the origin side appears on the cache side
- [ ] Confirm how an overwrite propagates

Record results in the table in [verification status](verification-status.md). When writing a figure,
always state the environment with it.

## 2. FlexCache from an FSx for ONTAP origin to an on-premises ONTAP cache

Environment needed: peering with on-premises ONTAP.
This is the main path. AWS states it as a supported configuration, but it has not been confirmed on
hardware.

- [ ] Establish the cluster peer and the SVM peer
- [ ] Create the Cache volume
- [ ] Confirm whether the origin's security style is inherited by the cache
      (the unconfirmed item in [decisions that come first](design-first-decisions.md))
- [ ] Confirm both UNIX + NFS and NTFS + SMB (mixed is out of scope, being not recommended)
- [ ] Confirm that only the range actually read is transferred
- [ ] Confirm the deletion order (whether it releases in the order cache, SVM peer, cluster peer)

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

Every result goes into the table in [portability](portability.md). Record the negative results too.

## 5. FlexCache duality

Environment needed: ONTAP 9.18.1.

This is not a premise of the architecture. It and attaching an S3 Access Point to a volume are
**separate mechanisms**, so confirming it produces no evidence about the collect layer. Leave it last.

- [ ] Confirm what it can do (not as a premise for adopting it here, but to keep the distinction
      intact)

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

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/poc-checklist.md) | [English](poc-checklist.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
