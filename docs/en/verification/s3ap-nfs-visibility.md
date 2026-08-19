# Verification record — mutual visibility of the S3 Access Point and NFS (same volume)

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/verification/s3ap-nfs-visibility.md) | [English](s3ap-nfs-visibility.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

**This record is not a verification of FlexCache.** What was measured is visibility when a single
volume is accessed both through the S3 Access Point and over NFS.
When something written through the S3 Access Point becomes visible on the **FlexCache cache volume**
remains a separate question ([verification status](../verification-status.md)).

Not conflating those two is the most important point in this record. The former is a precondition for
the latter, but the former's figures cannot be quoted as the latter's answer.

## Verification environment

| Item | Value |
|---|---|
| Date measured | 2026-08-09 (UTC) |
| Region | ap-northeast-1 |
| Deployment type | SINGLE_AZ_1, 1 HA pair |
| Throughput | 128 MBps (provisioned) |
| SSD capacity | 1024 GiB, `AUTOMATIC` 3072 IOPS |
| Volume | 1228 MB, security style UNIX, tiering `AUTO` (31 days), storage efficiency enabled |
| S3 Access Point | file system identity UNIX (root), `NetworkOrigin` is Internet |
| Client | EC2 in the same VPC and subnet, kernel 6.1.161-183.298.amzn2023, nfs-utils 2.5.4 |
| Protocol | NFSv3 |
| Object size | 64 B / 1 MiB / 8 MiB |
| Concurrency | 1 |
| Method | The write and the read run on the **same host against the same clock** |
| **ONTAP version** | **could not be determined** (see below) |

> **Note on the identity**: this measurement used the UNIX root user as the access point identity. Every request through the access point is authorized as that one identity, so root removes the file-permission layer entirely ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--file-system-permissions-are-what-narrow-access)). It is recorded as the condition it was, not as a recommendation. Use a dedicated user holding only the permissions the write path needs, and split access points by purpose (`FileSystemIdentity` cannot be changed after creation).

### Why the ONTAP version is not stated

This repository requires the ONTAP version to be stated alongside a measurement. For this measurement
it is not stated. There were two reasons, and neither could be worked around.

- `DescribeFileSystems` on FSx for ONTAP did not return `FileSystemTypeVersion` for this existing file
  system (the field is absent from the response entirely)
- The ONTAP REST API does not return the version without credentials (`401`), and no `fsxadmin`
  credentials were available for this verification

**These figures are therefore incompletely reproducible, in that one respect: the version is
unknown.** So that the gap closes on a freshly created environment, the
[collect-side template](../../../environments/aws-origin/template.yaml) creates the credentials at the
same time as the file system and provides a route to ONTAP.

## Results

### S3 PutObject until readable over NFS

Mounted with `actimeo=0`, to measure server-side propagation rather than the client's cache expiry.

| Object size | n | min | p50 | p90 | p99 | max |
|---|---|---|---|---|---|---|
| 64 B | 30 | 7 ms | 9 ms | 11 ms | 15 ms | 15 ms |

### NFS write until readable through the S3 Access Point

> **Correction**: the values in this table were measured by launching the `aws s3api get-object`
> command each time, so each includes CLI process startup and a TLS handshake. A re-measurement using
> a boto3 persistent session gave **p50 44 ms**. Most of the 873 ms was CLI startup cost, not storage
> propagation delay. The correct value and the all-directions comparison are in the
> [all-directions record](../verification/cross-protocol-directions.md).

| Object size | n | min | p50 | p90 | p99 | max |
|---|---|---|---|---|---|---|
| 64 B | 30 | 679 ms | 873 ms | 1,165 ms | 1,439 ms | 1,439 ms |
| 1 MiB | 30 | 700 ms | 904 ms | 1,423 ms | 1,650 ms | 1,650 ms |
| 8 MiB | 10 | 993 ms | 1,169 ms | 1,444 ms | 1,928 ms | 1,928 ms |

### Deletion propagation (S3 DeleteObject until gone from NFS)

| Mount option | Time |
|---|---|
| `actimeo=0` | 7 ms |
| default | 2,171 ms |

### Visibility during a multipart upload

| Point in time | On the NFS side |
|---|---|
| After part 1 uploaded, before `CompleteMultipartUpload` | **not visible** |
| After `CompleteMultipartUpload` (`actimeo=0`) | visible (6,291,456 bytes) |
| After `CompleteMultipartUpload` (default mount, 3 seconds later) | still not visible |

## What can be read from this

**The two directions differ by about two orders of magnitude.** S3 to NFS is single-digit
milliseconds; NFS to S3 is around a second. The same data, the same volume and the same host produce
that gap.

**The slow direction is dominated by S3 API overhead.** A re-measurement using a boto3 persistent
session brought it down to p50 44 ms. The values in the table above are kept only as a reference that
includes CLI startup cost; for the correct comparison see the
[all-directions comparison](../verification/cross-protocol-directions.md).

**A partial object does not appear on the file side.** A multipart upload was not visible over NFS
until `CompleteMultipartUpload`. The result is that there is no need to worry about reading a
half-written file.

**The client's mount options govern the result.** This is an operational matter rather than an
implementation one. Linux defaults to `acdirmin=30` / `acdirmax=60`, so a file appearing in a
directory the client has already listed can be invisible for up to a minute regardless of the storage
side. That is what produced 7 ms against 2,171 ms for deletion propagation, and it is the same reason
a completed multipart object was still not visible three seconds later on a default mount.

## What cannot be read from this

| Question | Why this measurement cannot answer it |
|---|---|
| When it becomes visible on the FlexCache Cache side | FlexCache is not in the path. This is a same-volume measurement |
| What the throughput is | Concurrency 1, up to 8 MiB, on 128 MBps provisioned throughput. This is not a configuration for measuring throughput |
| What happens at another throughput setting or another generation | Only one configuration was measured |
| What happens with a large number of small files | One at a time, sequentially. Concurrency and bulk ingest were not measured |
| Whether SMB behaves the same | NFSv3 only |
| Whether the NTFS security style behaves the same | UNIX only |
| Which ONTAP version these figures are for | Could not be determined, as stated above |

## How to reproduce

1. Deploy the [collect side](../deployment/aws-cloudformation.md) and attach an S3 Access Point to the
   Origin volume
2. Mount twice on the verification host, once with `actimeo=0` and once with the defaults
3. **Run the write and the read on the same host.** Splitting them across two hosts compares clocks,
   which at millisecond scale is not a measurement
4. Repeat about 30 times rather than once, and read the distribution
5. Record the environment (every item in the table above) together with the figures

## Cleanup

Every object and mount created for this measurement was removed (0 objects remaining under the target
prefix, mounts released). Because an existing volume was borrowed for the run, nothing outside the
measurement prefix was touched.

## Related documents

| Document | Contents |
|---|---|
| [Verification status](../verification-status.md) | The stage of each claim |
| [PoC checklist](../poc-checklist.md) | What to confirm next |
| [Deploying the collect side](../deployment/aws-cloudformation.md) | The environment for reproducing this |
| [Limits](../reference/limits/s3-access-point.md) | Size limits and their sources |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/verification/s3ap-nfs-visibility.md) | [English](s3ap-nfs-visibility.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
