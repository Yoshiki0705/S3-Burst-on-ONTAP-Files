# Glossary — the names given to "show files over S3"

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/glossary/object-access-on-ontap.md) | [English](object-access-on-ontap.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

The capability described as "read the same data over S3 or as files" has **a different name and a
different implementation** on each platform. Conflating them is how a discussion about supported
versions stops making sense.

This architecture uses only the first row of the table. The rest are listed as options to weigh when
considering portability or a future variant.

| Name | Implemented by | What it does | Minimum requirement | Position in this architecture |
|---|---|---|---|---|
| S3 Access Point (attached to FSx for ONTAP) | AWS | Attaches an AWS-side endpoint to an ONTAP volume and reads and writes over the S3 API | ONTAP 9.17.1 or later. Access point and volume in the same Region and the same account ([restrictions](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html)) | **Used in the collect layer** |
| ONTAP S3 (native bucket) | NetApp | ONTAP itself acts as an S3 object server and serves a dedicated bucket | ONTAP 9.8 or later, AFF / FAS / ONTAP Select. The S3 licence is free but required ([supported platforms](https://docs.netapp.com/us-en/ontap/s3-config/ontap-version-support-s3-concept.html)) | Reference. The counterpart when the collect layer sits outside AWS |
| ONTAP S3 NAS bucket (S3 multiprotocol) | NetApp | Maps a directory in an **existing** NFS / SMB volume as an S3 bucket | ONTAP 9.12.1 or later ([overview](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/index.html)) | Reference. As above |
| FlexCache duality | NetApp | Permits ONTAP's own S3 access on the **cache volume** | ONTAP 9.18.1 or later, `-is-s3-enabled true` ([FlexCache duality](https://docs.netapp.com/us-en/ontap/flexcache/enable-flexcache-duality.html)) | **Not used.** These are separate mechanisms from the first row and are never treated as one |
| object REST API | Microsoft | Maps an Azure NetApp Files directory as a bucket readable and writable over the S3 API | [object REST API](https://learn.microsoft.com/en-us/azure/azure-netapp-files/object-rest-api-introduction). Not supported on cache volumes | Reference |
| S3 multiprotocol | Google | Provides S3 access on Google Cloud NetApp Volumes | ONTAP mode only ([overview](https://docs.cloud.google.com/netapp/volumes/docs/discover/overview)) | Reference |

## What conflating them gets wrong

Rows one and four have similar names, and both can be summarised as "access an ONTAP volume over S3".
But they are implemented by AWS and by NetApp respectively, they are enabled differently, their
minimum versions differ, and they are **separate mechanisms**.

None of the following inferences therefore holds.

| Inference that does not hold | Why |
|---|---|
| duality became available in ONTAP 9.18.1, therefore an S3 Access Point can be attached to a cache volume | These are separate mechanisms. The implementer and the enabling procedure differ, and the support status of one is not evidence about the other |
| this version does not support duality, therefore an S3 Access Point cannot be attached to a cache volume | Being separate mechanisms, it cannot be used in the negative direction either |
| both are "S3 multiprotocol", therefore the same constraints apply | "S3 multiprotocol" is the name of the ONTAP S3 NAS bucket feature in row three, which is a different thing from row four |

This architecture uses neither. Only row one is used, in the collect layer, and because no object
access is exposed on the cache side, the support status of row four has no bearing on the design.

## Other terms

| Term | Meaning |
|---|---|
| Origin volume | The volume a FlexCache is based on. In this architecture it is the source of truth and the entry point for writes |
| Cache volume | A volume that holds only as much of the origin as is needed. In this architecture it is read-oriented |
| fan-out | Distributing from one origin to several caches |
| write-around | Directing a write made through the cache straight to the origin |
| write-back | Committing on the cache first and returning it to the origin asynchronously. Not a subject of this architecture |
| FileSystemIdentity | The setting that decides which file system identity an access through the S3 Access Point is treated as |
| SVM | Storage Virtual Machine. ONTAP's unit of tenancy |

## Related documents

| Document | Contents |
|---|---|
| [Architecture](../../architecture.md) | The collect and serve layers as a whole |
| [Support matrix](../../support-matrix.md) | Supported configurations and minimum versions |
| [Portability](../../portability.md) | Replacing the collect layer with another mechanism from this table |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/glossary/object-access-on-ontap.md) | [English](object-access-on-ontap.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
