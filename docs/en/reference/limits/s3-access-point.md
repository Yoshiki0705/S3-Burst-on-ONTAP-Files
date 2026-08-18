# Limits — collect layer (FSx for ONTAP S3 Access Point)

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/limits/s3-access-point.md) | [English](s3-access-point.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

Figures are stated with their source and stage. The stages are defined in
[verification status](../../verification-status.md).

## Size

| Item | Value | Stage | Note |
|---|---|---|---|
| Single `PutObject` | 5 GiB | verified | Measured in the sibling repository. Against the documentation's "5 GB" wording, the measured value is the binary prefix (5,368,709,120 bytes) |
| One `UploadPart` | 5 GiB | verified | As above |
| Whole object | 50 GiB | verified | As above. The judgement is made at `CompleteMultipartUpload`, so it fails after the whole payload has been transferred. Validate on the client side first |

Source: measurement records in the sibling repository
[fsxn-s3ap-serverless-patterns](https://github.com/Yoshiki0705/fsxn-s3ap-serverless-patterns).

## Names

| Item | Value | Stage | Source |
|---|---|---|---|
| S3 object name | 1024 bytes | documented | [NAS data requirements](https://docs.netapp.com/us-en/ontap/s3-multiprotocol/nas-data-requirements-client-access-reference.html) |
| File / directory name | 255 characters | documented | As above |
| Name collision | `part1/part2` and `part1/part2/part3` cannot both exist on NAS | documented | As above. The former requires a file and the latter a directory of the same name |
| Volume name | Alphanumerics and underscores only | documented | — |

Every name without a slash lands in the root directory. In quantity that becomes a performance
problem. The source above states explicitly that an object store suits an application that uses
NAS-unfriendly names heavily.

## Configuration prerequisites

| Item | Value | Stage | Source |
|---|---|---|---|
| Minimum ONTAP version | 9.17.1 | documented | [restrictions](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/access-point-for-fsxn-restrictions-limitations-naming-rules.html) |
| Region | Access point and volume in the same Region | documented | As above |
| Account | Access point and volume in the same account | documented | As above |
| `NetworkOrigin` | Cannot be changed after creation | documented | As above. **Reachability is decided by where the caller is and how it is routed, not by the origin type.** A Gateway endpoint only routes traffic originating inside the VPC; a caller arriving over VPN, Direct Connect, a peered VPC or Transit Gateway needs an Interface endpoint ([network access](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html)) |
| Authorisation | Both the AWS side and the ONTAP side have to permit it | documented | [two-layer authorisation](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/s3-ap-manage-access-fsxn.html) |

## Features out of scope

| Feature | State |
|---|---|
| Event notifications | Out of scope. Consider polling or FPolicy |
| Lifecycle | Out of scope |
| Versioning | Out of scope |

## Serve layer (FlexCache)

| Item | Value | Stage | Note |
|---|---|---|---|
| Caches per origin | AWS documentation recommends write-around above 10 origin volumes | documented / behaviour unverified | May bear on how many fan-out targets to design for |
| Supported configurations | Three | documented | Listed in [portability](../../portability.md) |
| Write modes | write-around (default) and write-back (ONTAP 9.15.1 or later) | documented | [replication with FlexCache](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/using-flexcache.html). write-around responds once the origin has committed; write-back commits on the cache and writes to the origin asynchronously |
| Tiering the cache | Not possible | documented | [supported and unsupported features](https://docs.netapp.com/us-en/ontap/flexcache/supported-unsupported-features-concept.html). A FabricPool origin can be cached, but the cache volume itself is not tiered |
| Sizing the cache | At least 10% of the origin is recommended, and 10% is also the default at creation | documented | [sizing guidance](https://docs.netapp.com/us-en/ontap/flexcache/sizing-concept.html) |
| Security style | Treated as an item inherited from the origin at cache creation | unverified | The basis is Azure NetApp Files' cache volume requirements. Unconfirmed on this architecture's main path ([decisions that come first](../../design-first-decisions.md)) |

## Figures that are not written

A performance figure is not written until it has been measured and the environment can be stated with
it. A figure without its environment cannot be reproduced, so it is useless for comparison and for
estimation alike. The required items are in [verification status](../../verification-status.md).

For cost, unit prices and estimates are kept apart. Unit prices are taken from the AWS Price List API
and placed in [FinOps cost structure](../comparison/finops-s3-vs-s3ap.md) with the Region and the
effective date. The monthly figures derived from them depend on assumed usage, so they are treated as
estimates and never mixed with measurements.

## Related documents

| Document | Contents |
|---|---|
| [S3 AP design guide](../../reference/limits/s3ap-design-guide.md) | Supported operations in detail, concurrency design, directory design, multiprotocol consistency |
| [Support matrix](../../support-matrix.md) | The constraints as a whole |
| [Verification status](../../verification-status.md) | The definition of the stages and the current state |
| [Architecture](../../architecture.md) | What this architecture does not solve |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../../ja/reference/limits/s3-access-point.md) | [English](s3-access-point.md) | [🏠 Repository home](../../README.md)
<!-- lang-switcher:end -->
