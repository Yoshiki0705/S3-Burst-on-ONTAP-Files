# Support matrix — collect layer and serve layer

<!-- lang-switcher:start -->
🌐 [日本語](../ja/support-matrix.md) | [English](support-matrix.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

<!-- Provenance and divergence
     This table started from the sibling repository FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns,
     docs/support-matrix-fsx-ontap-flexcache-s3ap.md.
     https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/support-matrix-fsx-ontap-flexcache-s3ap.md

     It is not a copy. It diverges as follows, and the reasons are kept with it.

     1. The four-platform-column shape (FSx for ONTAP / on-premises ONTAP / Cloud Volumes ONTAP /
        Lab-Simulator) was dropped in favour of splitting by collect layer and serve layer. In this
        architecture the two layers can be considered separately, and one table spanning both makes
        a reader guess which layer a row is about.
     2. The row for "attaching an S3 Access Point to a cache volume" was dropped. The newer text in
        the source repository treats it as possible and cites the FlexCache duality FAQ as evidence,
        but those are separate mechanisms and the support status of one cannot serve as evidence for
        the other. This architecture uses neither, so the row itself becomes unnecessary.
     3. The per-ONTAP-version feature table (9.8 to 9.15.1) was not carried over. Its axis stops at
        9.15.1, and a table that is not updated hands the reader a stale premise. The required
        version is stated on each row instead.
     4. The presigned URL row was dropped. It has no bearing on this architecture's path, and the
        description varies within the source repository, so copying it would propagate only the
        variance.
     5. The handling of unconfirmed items was consolidated into [verification status](verification-status.md).
-->

Support depends on both the AWS service specification and the ONTAP version, and cannot be judged
from the ONTAP version alone. What the table states is a starting point for design; in a PoC, always
confirm against the real environment.

What is verified and what is unverified is kept separate in
[verification status](verification-status.md). This table shows what the public documentation states;
it is not a record of hardware confirmation.

## Collect layer — taking writes over the S3 API

| Platform | Mechanism | Minimum requirement |
|---|---|---|
| Amazon FSx for NetApp ONTAP | S3 Access Point | ONTAP 9.17.1 or later. Access point and volume in the same Region and the same account ([restrictions](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html)) |
| On-premises ONTAP (AFF / FAS), ONTAP Select | ONTAP S3 native bucket / S3 NAS bucket | native from ONTAP 9.8, NAS bucket from 9.12.1 |
| Cloud Volumes ONTAP | ONTAP S3 | [S3 is listed among the supported client protocols](https://docs.netapp.com/us-en/bluexp-cloud-volumes-ontap/concept-client-protocols.html) <!-- allow:vendor-ref part of the source URL, not a product proposal --> |
| Azure NetApp Files | object REST API | Requires a volume with existing data (an empty volume will not do) |
| Google Cloud NetApp Volumes | S3 multiprotocol | ONTAP mode only |

The differences in name and implementer are collected in the
[glossary](reference/glossary/object-access-on-ontap.md). This architecture uses only the first row.

## Serve layer — fanning out with FlexCache

AWS states the following three supported FlexCache configurations for FSx for ONTAP
([supported configurations](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html)).

| Origin | Cache | Position in this architecture |
|---|---|---|
| On-premises ONTAP | FSx for ONTAP | The reverse direction. Out of scope here |
| FSx for ONTAP | On-premises ONTAP | **This architecture's main path** |
| FSx for ONTAP | FSx for ONTAP | Usable for in-Region and cross-Region replication |

Whether Cloud Volumes ONTAP, ONTAP Select, Azure NetApp Files or Google Cloud NetApp Volumes can be
the cache when FSx for ONTAP is the origin is not covered by this table. **For now it is treated as
unconfirmed.** It is never summarised as "it works because it is ONTAP-based".

For reference, Azure NetApp Files has cache volumes that target an external ONTAP or Cloud Volumes
ONTAP origin
([cache volumes](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-volumes)). Whether
FSx for ONTAP can be used as the origin is not stated explicitly in the
[requirements](https://learn.microsoft.com/en-us/azure/azure-netapp-files/cache-requirements), so it
is treated as something to verify.

## Constraints on the collect layer

| Constraint | Detail |
|---|---|
| Supported operations | A subset of the S3 API. Event notifications, lifecycle, versioning, Object Lock, Requester Pays and conditional writes are out of scope; the storage class is `FSX_ONTAP` and encryption is `SSE-FSX` only; Block Public Access is always on and cannot be changed. The full list is in [limits](reference/limits/s3-access-point.md#features-out-of-scope) ([compatibility table](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-points-for-fsxn-object-api-support.html)) |
| Authorisation | Both the AWS side (IAM and the access point policy) and the ONTAP side (the file system identity) have to permit it ([two-layer authorisation](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/s3-ap-manage-access-fsxn.html)) |
| `NetworkOrigin` | Cannot be changed after creation (changing it means deleting and recreating). **Reachability is decided by where the caller is and how it is routed, not by the origin type.** A Gateway endpoint only routes traffic that originates inside the VPC, so a caller arriving over VPN, Direct Connect, a peered VPC or Transit Gateway needs an Interface endpoint ([network access](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)) |
| Object names | An S3 name is up to 1024 bytes and a file or directory name up to 255 characters. `part1/part2` and `part1/part2/part3` cannot both exist on NAS ([NAS data requirements](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html)) |
| Size limits | 5 GiB per single `PutObject` and per `UploadPart`, 50 GiB for a whole object. Against the documentation's "GB" wording, the measured values were binary prefixes. The whole-object limit is judged at `CompleteMultipartUpload`, so it fails after the entire payload has been transferred ([verification status](verification-status.md)) |
| Windows identity | An AD join is not required. Where a domain is not available, use a workgroup-mode CIFS server ([procedure](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html); NTLM only, no Kerberos). **If AD is joined**, every data operation then needs reachability to an AD domain controller, and `HeadBucket` succeeds even when AD is unreachable, so it cannot be used as a connectivity check |
| Volume names | Alphanumerics and underscores only |
| Auditing | What ONTAP's file access auditing records is the identity fixed on the access point, not the calling IAM principal. **Splitting access points by purpose is what sets the granularity of the audit.** Identifying the caller requires correlating with AWS CloudTrail; what cannot be attributed is listed in [limits](reference/limits/s3-access-point.md#what-the-audit-trail-can-and-cannot-attribute) ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md#who-appears-in-the-audit-log)) |
| Monitoring | **FPolicy does not see the collect path.** Operations through the S3 Access Point raise no notification and are not blocked even by a `mandatory` synchronous policy. The ONTAP native audit log does record them (`Source=HTTP` / `Source=S3`). ARP detects writes through the access point. Controls driven by an FPolicy notification — detection, DLP, blocking — do not apply to this path ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-S3AccessPoints-Serverless-Patterns/blob/main/docs/errata-fpolicy-s3ap-coverage.en.md)) |
| Interoperability with ONTAP features | Measured 2026-08-26 on 9.18.1P3D1, on the S3 Access Point path: **qtrees work, a quota refuses an S3 PUT, FlexClone works at both volume granularity (the clone can carry its own access point) and file granularity (the clone is visible as an object through the access point), a FlexGroup can take an access point, and a clone of that FlexGroup can be created**. The file-granularity clone returns 202 but leaves no job record, so **failure is not observable** (volume-create and volume-clone jobs are retrievable, which is the control). The four items NetApp records as unsupported for ONTAP S3 (qtrees, quotas, FlexClone, and a volume clone of a FlexGroup volume containing ONTAP S3 buckets) did not appear as restrictions on this path. The real traps are elsewhere: an NTFS volume + UNIX identity on an SVM with no CIFS server attaches as `AVAILABLE` and then refuses every data operation with `AccessDenied`. Under a gapless poll, a volume created on the ONTAP side took 599 s for a FlexGroup and 1,177 s for a FlexClone volume to appear in the AWS API, while a separate run was still absent at 1,258 s (documented "several minutes"; the three disagree, so none is an upper bound). **Anything not measured is treated as unverified.** Per item: [interoperability](reference/limits/s3ap-interoperability.md) (the question came from [ONTAP S3 interoperability](https://docs.netapp.com/us-en/ontap/s3-config/ontap-s3-interoperability-concept.html)) |
| IaC | Declarable with `AWS::FSx::S3AccessPointAttachment`. There is no update handler and `S3AccessPoint` is create-only, so **editing the policy alone means a delete and a recreate**. It is not taggable. The ONTAP identity is a user name; numeric UID / GID belong to the OpenZFS configuration ([pattern](../../patterns/collect/s3-access-point-attachment/README.md)) |

## Constraints on the serve layer

| Constraint | Detail |
|---|---|
| Security style | Treated as an item inherited from the origin at cache creation time and not settable on the cache. For the source and the unconfirmed scope see [decisions that come first](design-first-decisions.md) |
| Caches per origin | AWS documentation recommends write-around above 10 origin volumes. The behaviour as the number of fan-out targets grows is unverified |
| Deletion order | Do not delete the origin side while a cache still exists. Releasing the cache and the SVM peer comes before removing the peering |
| Writes on the cache side | Not addressed here. Writes are consolidated on the origin-side S3 Access Point |

## Related documents

| Document | Contents |
|---|---|
| [Architecture](architecture.md) | The collect and serve layers as a whole |
| [Verification status](verification-status.md) | The distinction between verified and unverified |
| [Decisions that come first](design-first-decisions.md) | The relationship between security style and protocol |
| [Portability](portability.md) | Considering a replacement one layer at a time |
| [Glossary](reference/glossary/object-access-on-ontap.md) | The mechanism names and their implementers |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/support-matrix.md) | [English](support-matrix.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
