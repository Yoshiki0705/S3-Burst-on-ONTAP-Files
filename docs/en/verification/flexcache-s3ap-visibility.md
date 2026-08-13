# Verification record — when a write through the S3 Access Point becomes visible on the FlexCache cache volume

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/verification/flexcache-s3ap-visibility.md) | [English](flexcache-s3ap-visibility.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

**This is the record that verifies this architecture's central claim.** It measures when an object
written to the Origin volume through the S3 Access Point becomes readable over an NFS mount on a Cache
volume in a different cluster, by way of FlexCache.

## Verification environment

| Item | Value |
|---|---|
| Date measured | 2026-08-09 (UTC) |
| Region | ap-northeast-1 |
| Origin cluster | File system 1 (`fs-0123456789abcdef0`, acting as Origin), SINGLE_AZ_1, 128 MBps, 1 HA pair |
| Cache cluster | File system 2 (`fs-0123456789abcdef0`, acting as the on-premises-equivalent Cache), SINGLE_AZ_1, 128 MBps, 1 HA pair |
| **ONTAP version** | **NetApp Release 9.18.1P3D1** (identical on both clusters) |
| Connection | VPC peering (same Region, same account) |
| Origin volume | `s3burst_origin_vol2`, SVM `fsxsvm02`, security style UNIX |
| Cache volume | `s3burst_cache_vol2`, SVM `FSxN_OnPre`, FlexCache (`use_tiered_aggregate: true`) |
| S3 Access Point | `s3burst-verify-ap`, file system identity UNIX (root), `NetworkOrigin` unspecified (Internet) |
| Client | EC2 in the same VPC and the same subnet as the Cache cluster, NFSv3 |
| Mount | `actimeo=0` (to measure server-side propagation) |
| Object size | 64 B |
| Concurrency | 1 |
| Method | The write (S3 PutObject) and the read (NFS `cat`) run on the **same host against the same clock** |

## Results

### S3 PutObject (Origin) until readable over FlexCache Cache NFS

| n | min | p50 | p90 | p99 | max |
|---|---|---|---|---|---|
| 30 | 10 ms | 14 ms | 18 ms | 19 ms | 19 ms |

### First read against a read after a cache hit

| Read | Time |
|---|---|
| First (not yet pulled into the Cache) | 16 ms |
| Second and later (already pulled into the Cache) | 3 to 5 ms |

### Visibility during a multipart upload

| Point in time | On the Cache NFS side |
|---|---|
| After part 1 uploaded, before `CompleteMultipartUpload` | **not visible** |
| After `CompleteMultipartUpload` | visible (6,291,456 bytes, 8 ms later) |

### Deletion propagation

| Operation | Time |
|---|---|
| S3 DeleteObject until gone from Cache NFS (`actimeo=0`) | 9 ms |

## Compared with the same-volume measurement

| Direction | Same volume p50 | Through FlexCache p50 | Difference |
|---|---|---|---|
| S3 PutObject until readable over NFS | 9 ms | 14 ms | +5 ms |
| S3 DeleteObject until gone from NFS | 7 ms | 9 ms | +2 ms |

**FlexCache adds about 5 ms.** Under these conditions — same Region, over VPC peering, client in the
same subnet — whether FlexCache is in the path is barely visible.

## What can be read from this

- **This architecture's central claim holds.** An object written to the Origin through the S3 Access
  Point is readable over an NFS mount on the Cache volume, by way of FlexCache, in 10 to 19 ms
- **A partial object does not appear on the Cache side either.** There is no need to worry about
  reading a half-written file during a multipart upload
- **Deletions also propagate in milliseconds.** 9 ms under `actimeo=0`
- **The second and later reads take 3 to 5 ms.** Once the FlexCache cache is populated, the round trip
  to the Origin is no longer needed

## What cannot be read from this

| Question | Why this measurement cannot answer it |
|---|---|
| What happens at a remote site or in a high-latency environment | This was measured in the same Region over VPC peering (sub-millisecond network latency) |
| What the throughput is | Concurrency 1 and 64 B objects. This is not a throughput measurement |
| What happens with on-premises ONTAP as the Cache | Both sides are FSx for ONTAP. On-premises is unverified |
| What happens with SMB or the NTFS security style | NFS and UNIX only |
| What happens as the number of fan-out targets grows | There is only one Cache |
| What happens with mount options other than `actimeo=0` | `actimeo=0` only. At the defaults the NFS client cache dominates (measured in the [same-volume verification record](s3ap-nfs-visibility.md)) |

## Creating and deleting the verification environment

| Item | State |
|---|---|
| VPC peering | created, measured, **deleted** |
| Cluster peer / SVM peer | created, measured, **deleted** (because releasing the SVM peer is asynchronous the cluster peer remains as orphaned, but with no network route it transitions to unavailable and is not billed) |
| FlexCache volume | **deleted** |
| Origin volume | **deleting** (DELETE issued through the FSx for ONTAP API) |
| S3 Access Point | **deleted** |
| Security group rules | **all 6 deleted** |
| Test objects | **0** (confirmed within the script) |
| Temporary IAM permissions | **0** (confirmed returned to the pre-run state) |

## How to reproduce

1. Prepare two FSx for ONTAP file systems and connect them with VPC peering
2. Create a volume on the Origin side and attach an S3 Access Point to it
3. Create the cluster peer, then the SVM peer, then the FlexCache, in that order
   ([deploying the serve side](../deployment/onprem-terraform.md))
4. Mount the Cache-side volume over NFS with `actimeo=0`
5. **Run the write and the read on the same host** (a single clock)
6. Repeat about 30 times and read the distribution
7. Record the environment (every item in the table above) together with the figures
8. **Delete in the order FlexCache, SVM peer, cluster peer, route, peering. In the reverse order a
   resource is left that cannot be deleted**

## Related documents

| Document | Contents |
|---|---|
| [Same-volume verification record](s3ap-nfs-visibility.md) | Reading and writing the Origin volume over both S3 and NFS (FlexCache not in the path) |
| [Verification status](../verification-status.md) | The stage of each claim |
| [Support matrix](../support-matrix.md) | Supported configurations and constraints |
| [PoC checklist](../poc-checklist.md) | The order to verify in |
| [Architecture](../architecture.md) | The whole picture |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/verification/flexcache-s3ap-visibility.md) | [English](flexcache-s3ap-visibility.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
