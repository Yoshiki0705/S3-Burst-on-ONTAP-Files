# Portability — replacing one layer at a time

<!-- lang-switcher:start -->
🌐 [日本語](../ja/portability.md) | [English](portability.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

This architecture splits into two layers, and portability can be considered for each separately.
Swapping the collect layer leaves the serve layer's design unchanged, and the reverse holds too.

That is why there is no single table spanning both layers. Making a reader guess which layer a row is
about is how a discussion about supported versions stops making sense.

## Collect layer — the side that takes writes over the S3 API

The names and the implementers differ, so reading the
[glossary](reference/glossary/object-access-on-ontap.md) first makes the mapping easier to follow.

| Platform | Mechanism | Minimum requirement | Stage |
|---|---|---|---|
| Amazon FSx for NetApp ONTAP | S3 Access Point | ONTAP 9.17.1 or later. Access point and volume in the same Region and the same account | verified (sibling repository) |
| On-premises ONTAP (AFF / FAS), ONTAP Select | ONTAP S3 native bucket / S3 NAS bucket | native from ONTAP 9.8, NAS bucket from 9.12.1 | documented |
| Cloud Volumes ONTAP | ONTAP S3 | [S3 is listed among the supported client protocols](https://docs.netapp.com/us-en/bluexp-cloud-volumes-ontap/concept-client-protocols.html) <!-- allow:vendor-ref part of the source URL, not a product proposal --> | documented |
| Azure NetApp Files | object REST API | Requires a volume with existing data (an empty volume will not do) | documented |
| Google Cloud NetApp Volumes | S3 multiprotocol | ONTAP mode only | documented |

Placing the collect layer outside AWS means using ONTAP's own S3 capability rather than an S3 Access
Point. The minimum version and the enabling procedure both differ, so it does not port across as-is.
The serve layer's design is unaffected by that difference.

## Serve layer — the side that fans out with FlexCache

AWS states exactly three supported FlexCache configurations for FSx for ONTAP
([supported configurations](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)).

The verdicts are normalised to four words. `documented` (stated in a primary source),
`locally verified` (measured in this repository), `unverified` (stated somewhere but not followed on
hardware), `unconfirmed` (no statement found in public documentation).
**`unconfirmed` does not mean "cannot be done".** Equally, it is never written as "it works because
it is ONTAP-based". Neither has any basis.

| Platform | As origin | As cache (origin is FSx for ONTAP) | Minimum version | Protocols | Primary source | Constraints | Verdict |
|---|---|---|---|---|---|---|---|
| Amazon FSx for NetApp ONTAP | ✅ the origin in this architecture | ✅ in the supported configurations | ONTAP 9.17.1 or later for the collect layer | NFS / SMB | [supported configurations](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) | The cache must be a FlexGroup. The cache side cannot be tiered | **locally verified** (same Region over VPC peering; NFSv3 on 2026-08-09, SMB on 2026-08-10. Conditions and scope in [verification status](verification-status.md)) |
| On-premises ONTAP (AFF / FAS) | ✅ stated as the reverse direction | ✅ in the supported configurations (**this architecture's main path**) | FlexCache needs ONTAP 9.5 or later; write-back 9.15.1 or later | NFS / SMB | [supported configurations](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html) | The cluster / SVM peering path is provided outside this repository | **unverified** (stated, but not followed on hardware) |
| ONTAP Select | Collect layer possible over ONTAP S3 ([support matrix](support-matrix.md)) | Not in the supported configuration table | — | NFS / SMB | — | — | **unconfirmed** |
| Cloud Volumes ONTAP | Collect layer possible over ONTAP S3 | Not in the supported configuration table | — | NFS / SMB | — | — | **unconfirmed** |
| Azure NetApp Files | Collect layer possible over the object REST API | Not in the supported configuration table. ANF has cache volumes, but does not list FSx for ONTAP as an origin | — | NFS / SMB | [cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes) (origin is external ONTAP or Cloud Volumes ONTAP) | The object REST API is not supported on cache volumes | **unconfirmed** |
| Google Cloud NetApp Volumes | Collect layer possible over S3 multiprotocol (ONTAP mode only) | Not in the supported configuration table | — | NFS / SMB | — | — | **unconfirmed** |

**An empty `Primary source` cell means we looked and did not find one.**
It is not a claim that none exists. It gets filled in once one is found.

The procedure for confirming this is in phase 4 of the
[PoC checklist](poc-checklist.md). This table gets updated once there is a result.

### The reverse direction — another cloud's file storage as the origin

Every row above has **FSx for ONTAP as the origin**. The reverse direction, another cloud's file
storage as the origin with FSx for ONTAP as the cache, is absent from AWS's supported configuration
table. **That direction sits outside the table.** It is kept separate because the verdict splits two
ways.

| Origin side | Verdict | Why |
|---|---|---|
| Google Cloud NetApp Volumes | **unconfirmed** | It has an ONTAP mode, but the supported configuration table does not mention it |
| Azure NetApp Files | **unconfirmed** | ONTAP-based, but the supported configuration table does not mention it |
| Google Cloud Filestore, Azure Managed Lustre, Azure Blob NFS, OCI File Storage | **out of scope as a mechanism** | Not ONTAP. FlexCache requires ONTAP cluster and SVM peering |

**Do not write `unconfirmed` and "out of scope as a mechanism" with the same word.** The first can
have its stage raised by a primary source or by a measurement; the second rests on a different
premise. Network reachability does not change the second one.

The connectivity itself is covered in
[cross-cloud connectivity](multi-cloud-connectivity.md).

### Reference — Azure NetApp Files cache volumes

Azure NetApp Files has cache volumes that target an external ONTAP or Cloud Volumes ONTAP origin
([cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes)). Whether
FSx for ONTAP can be used as the origin is not stated explicitly in the
[requirements](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-requirements), which
is why the table above marks it unconfirmed.

The preconditions the same requirements text lists are quoted in
[decisions that come first](design-first-decisions.md), including the statement about security style
inheritance. Whether the same conditions apply on this architecture's main path is unconfirmed and is
treated as something to confirm.

## What porting changes and what it does not

| Unchanged | Changed |
|---|---|
| The division of roles: collect over the S3 API, consume over NFS / SMB | The name of the collect-layer mechanism and how it is enabled |
| The source of truth is the origin volume, and the write path is single | The minimum ONTAP version |
| The cache is read-oriented | The management interface (AWS API or ONTAP REST API) |
| The need to decide the consuming protocol before creating the origin | Which combinations are stated as supported configurations |

## Related documents

| Document | Contents |
|---|---|
| [Architecture](architecture.md) | The two layers as a whole |
| [Support matrix](support-matrix.md) | The constraints in one place |
| [Verification status](verification-status.md) | The definition of the stages |
| [Glossary](reference/glossary/object-access-on-ontap.md) | The names of the collect-layer mechanisms |
| [PoC checklist](poc-checklist.md) | The procedure for closing the unconfirmed items |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/portability.md) | [English](portability.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
