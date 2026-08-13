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

| Origin | Cache | Stage |
|---|---|---|
| On-premises ONTAP | FSx for ONTAP | documented (out of scope here; the reverse direction) |
| FSx for ONTAP | On-premises ONTAP | documented / not confirmed on hardware (**this architecture's main path**) |
| FSx for ONTAP | FSx for ONTAP | documented |

### Combinations the table does not include

Whether the following can be the cache when FSx for ONTAP is the origin is not covered by AWS's
supported configuration table.

| Cache candidate | Stage |
|---|---|
| Cloud Volumes ONTAP | unconfirmed |
| ONTAP Select | unconfirmed |
| Azure NetApp Files | unconfirmed |
| Google Cloud NetApp Volumes | unconfirmed |

**Unconfirmed means "no statement was found in public documentation", not "cannot be done".** Equally,
it is never written as "it works because it is ONTAP-based". Neither has any basis.

The procedure for confirming this is in phase 4 of the
[PoC checklist](../ja/poc-checklist.md) (Japanese). This table gets updated once there is a result.

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
| [PoC checklist](../ja/poc-checklist.md) (Japanese) | The procedure for closing the unconfirmed items |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/portability.md) | [English](portability.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
