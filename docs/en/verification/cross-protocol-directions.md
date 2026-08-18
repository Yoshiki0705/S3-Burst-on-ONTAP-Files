# Verification record — all-directions visibility comparison and the NAS bucket constraints

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/verification/cross-protocol-directions.md) | [English](cross-protocol-directions.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

## Overview

Four directions of propagation were compared under identical conditions, and in addition it was
checked whether an ONTAP NAS bucket (FlexCache duality) can be enabled on FSx for ONTAP.

## Verification environment

| Item | Value |
|---|---|
| Date measured | 2026-08-09 (UTC) |
| Region | ap-northeast-1 |
| ONTAP version | NetApp Release 9.18.1P3D1 (both clusters) |
| Origin cluster | File system 1 (`fs-0123456789abcdef0`, acting as Origin), SINGLE_AZ_1, 128 MBps |
| Cache cluster | File system 2 (`fs-0123456789abcdef0`, acting as the on-premises-equivalent Cache), SINGLE_AZ_1, 128 MBps |
| Connection | VPC peering (same Region, same account) |
| Origin volume | `s3burst_origin_vol2`, SVM `fsxsvm02`, UNIX |
| Cache volume | `s3burst_cache_vol2`, FlexCache |
| S3 Access Point | `s3burst-verify-ap`, UNIX (root) |
| Client | EC2 inside the Cache VPC. The NFS mount to the Origin goes over VPC peering |
| Mount | NFSv3, `actimeo=0` |
| Object size | 64 B |
| Concurrency | 1 |
| Method | boto3 persistent session, same host (a single clock) |

> **Note on the identity**: this measurement used the UNIX root user as the access point identity. Every request through the access point is authorized as that one identity, so root removes the file-permission layer entirely ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md)). It is recorded as the condition it was, not as a recommendation. Use a dedicated user holding only the permissions the write path needs, and split access points by purpose (`FileSystemIdentity` cannot be changed after creation).

## Results for all four directions

| # | Direction | p50 | p90 | p99 | max | n |
|---|---|---|---|---|---|---|
| 1 | NFS write (Origin) to S3 AP `GetObject` | 44 ms | 49 ms | 328 ms | 328 ms | 30 |
| 2 | NFS write (Origin) to FlexCache NFS read | 6 ms | 7 ms | 25 ms | 25 ms | 30 |
| 3 | S3 AP PutObject to FlexCache NFS read | 8 ms | 9 ms | 19 ms | 19 ms | 30 |
| 4 | S3 AP PutObject to Origin NFS direct read | 3 ms | 5 ms | 8 ms | 8 ms | 30 |

## What can be read from this

**The difference between directions 3 and 4 is what FlexCache adds.** +5 ms at p50 (3 ms to 8 ms).
Over VPC peering within one Region, FlexCache is close to transparent.

**Direction 2 is faster than direction 3.** An NFS write commits directly to the Origin's file system,
so there is no S3 API overhead, and it propagates to FlexCache in p50 6 ms. This is one of the reasons
this architecture states that writes are consolidated on the Origin.

**Direction 1 (NFS to S3 AP) is the slowest.** p50 44 ms, dominated by the read path on the S3 AP side.
That said, this is the overhead per S3 API call, not latency of the volume itself.

### On the discrepancy with the earlier measurement (873 ms)

The first measurement reported the NFS to S3 AP direction as p50 873 ms.
The difference is **the measurement method**. The first run launched the `aws s3api get-object` command
each time, so CLI process startup and a TLS handshake occurred on every call. This run uses a boto3
persistent session and reuses the connection.

Most of the 873 ms was CLI startup cost, not storage propagation delay.
**The correct value is this run's p50 44 ms.**

A reference to this correction has been added to the first record
([same-volume verification record](s3ap-nfs-visibility.md)). The description suggesting a fixed
interval was based on mistaking CLI overhead for propagation, and is withdrawn.

## Verifying the ONTAP S3 NAS bucket (FlexCache duality)

### Result: works on a regular volume, no S3 data access on a FlexCache volume

The verification proceeded in stages and the conclusion changed at each one. The final state comes
first, the sequence after it.

**NAS bucket on a regular volume: fully working** (NFS write to ONTAP S3 read, contents matched).
**NAS bucket on a FlexCache volume: creation succeeds, but S3 data operations return `AccessDenied`.**

#### Regular volume (NAS bucket read: succeeded)

Operated through the ONTAP CLI (SSH) on an SVM that had never used an S3 AP (`snapmirror-s3-test`).
The REST API refuses to create an S3 user; the CLI succeeds.

| Operation | Method | Result |
|---|---|---|
| Confirm the S3 service | CLI | ✅ already present (`sm-s3-server`, HTTP port 80, `up`) |
| Create an S3 user | REST API | ❌ `The user does not have permission to access the requested resource` |
| Create an S3 user | CLI `vserver object-store-server user create` | ✅ access key and secret key obtained |
| Create the NAS bucket | CLI | ✅ (`type: nas`, `nas-path: /duality_test`) |
| Bucket policy | CLI | ✅ |
| NFS write to `GetObject` | boto3 to `http://<data-lif>:80` | ✅ **succeeded, contents matched** |
| `ListObjectsV2` | As above | ✅ object list returned |
| `PutObject` | As above | ❌ `AccessDenied` (a NAS bucket is a read-only view, as documented) |

#### FlexCache volume (NAS bucket: creation succeeded, no data access)

| Operation | Result |
|---|---|
| FlexVol Origin to FlexCache to NAS bucket creation | ❌ `Only FlexCache volumes with FlexGroup origin volumes support NAS buckets` |
| FlexGroup Origin creation (CLI `-auto-provision-as flexgroup`) | ❌ `No suitable storage... Aggregates not matching FabricPool requirements: aggr1` |
| FlexGroup Origin creation (FSx for ONTAP API `VolumeStyle: FLEXGROUP`, 200 GiB, `ConstituentsPerAggregate: 2`) | ✅ |
| FlexGroup Origin to FlexCache creation (50 GB) | ✅ |
| NAS bucket creation on the FlexCache | ✅ (`type: nas`, `nas-path: /duality_fc_fg`) |
| Bucket policy (`* / *` wildcard) | ✅ |
| `HeadBucket` | ✅ |
| `ListObjectsV2` | ❌ **`AccessDenied`** |
| `GetObject` (the file was written over NFS, permissions `644`) | ❌ **`AccessDenied`** |

**With the same SVM, the same S3 user and the same bucket policy, `GetObject` succeeds on a regular
volume and is refused on a FlexCache volume.** Making the file's UNIX permissions world-readable does
not change the result.

#### The decisive isolation: a comparison under identical conditions

Within one session, NAS buckets were created on both a FlexVol (regular) and a FlexCache and tested
simultaneously with the same S3 user, the same wildcard policy and the same data LIF.

| Operation | FlexVol NAS bucket (`getobj_flexvol`) | FlexCache NAS bucket (`duality_fc_fg`) |
|---|---|---|
| HeadBucket | ✅ | ✅ |
| ListObjectsV2 | ✅ (KeyCount=1) | ❌ AccessDenied |
| GetObject | ✅ **SUCCESS** (`FLEXVOL-GETOBJECT-TEST`) | ❌ AccessDenied |
| Read over NFS | ✅ | ✅ |

Both files were written over NFS and made world-readable with `chmod 644`.
**The problem is specific to the FlexCache volume**, not to being a FlexGroup (the regular volume test
also succeeded on a FlexVol).

### Correction to the previous conclusion

The previous report said access was impossible because an S3 user could not be created. That was the
conclusion at the point where only the REST API had been tried; **through the ONTAP CLI (SSH), creating
an S3 user succeeds.** The cause was that `fsxadmin`'s permission mapping differs between the REST API
and the CLI.

### Constraints specific to FSx for ONTAP (summary)

| Item | State |
|---|---|
| Operating ONTAP S3 on an SVM with an S3 AP enabled | ❌ permissions move to the AWS side |
| Operating ONTAP S3 on an SVM not using an S3 AP (CLI) | ✅ |
| Operating ONTAP S3 on an SVM not using an S3 AP (REST API) | ❌ user creation is refused |
| NAS bucket on a regular volume, read over S3 | ✅ |
| NAS bucket on a FlexCache volume, read over S3 | ❌ then ✅ **confirmed working with `-is-s3-enabled true`** (see below) |
| Creating a FlexGroup through the CLI | ❌ compatibility error with the FabricPool aggregate |
| Creating a FlexGroup through the FSx for ONTAP API | ✅ (minimum 100 GiB per constituent) |

### The bearing on this architecture

**Addendum (2026-08-10): FlexCache duality was confirmed to work with `-is-s3-enabled true`.**

Feedback from the NetApp product team established that S3 access has to be enabled explicitly on the
FlexCache volume:

```bash
set -privilege advanced
flexcache config modify -vserver snapmirror-s3-test -volume duality_fc_s3en -is-s3-enabled true
```

The results after setting it:

| Operation | `-is-s3-enabled` unset | after `-is-s3-enabled true` |
|---|---|---|
| HeadBucket | ✅ | ✅ |
| ListObjectsV2 | ❌ AccessDenied | ✅ KeyCount=1 |
| GetObject | ❌ AccessDenied | ✅ **contents matched** |

It was also confirmed that `fsxadmin` can run advanced privilege commands.
Source: [Enable S3 access to NAS FlexCache volumes](https://docs.netapp.com/us-en/ontap/flexcache/enable-flexcache-duality.html)

**Even so, this architecture continues to recommend using NFS / SMB on the cache side.** The reasons:

- ONTAP native S3 (the NAS bucket) and the AWS-managed S3 Access Point are separate mechanisms
- A NAS bucket is read-only (no `PutObject`)
- Advanced privilege plus S3 user management is additionally required
- There is no governance through IAM integration or an access point policy

## State of the verification environment

Every resource has been deleted (the same form as the "creating and deleting the verification
environment" section of the [FlexCache verification record](flexcache-s3ap-visibility.md)).

## Additional verification over SMB

### Verification environment (the SMB addition)

| Item | Value |
|---|---|
| Date measured | 2026-08-10 (UTC) |
| CIFS server | `SMBTEST01` (SVM `snapmirror-s3-test`, domain `s3burst.local`) |
| Active Directory | AWS Managed AD (Standard), `s3burst.local` |
| Mount method | `mount -t cifs`, option `cache=none`, SMB 3.0 |
| Comparison | NFS (`actimeo=0`) in the same environment, measured in parallel |

### Result: S3 AP PutObject to FlexCache read (protocol comparison)

| Protocol | Mount method | p50 | p90 | max | n |
|---|---|---|---|---|---|
| **SMB** | `mount -t cifs`, `cache=none` | **7 ms** | 8 ms | 9 ms | 30 |
| **NFS** | `mount -t nfs`, `actimeo=0` | **7 ms** | 8 ms | 15 ms | 30 |

**Over persistent connections, SMB and NFS are equivalent.** There is no difference by protocol.

### Measured with smbclient (for reference)

Using `smbclient`, which starts a process and establishes a session each time:

| Protocol | Method | p50 | p90 | max |
|---|---|---|---|---|
| SMB | `smbclient` (session established each time) | 43 ms | 68 ms | 443 ms |
| NFS (same environment, for reference) | `mount -t nfs`, `actimeo=0` | 7 ms | 17 ms | 28 ms |

Most of the 43 ms is the overhead of establishing the SMB session. This has the same shape as the
`aws s3api` CLI cold-start problem — the cause of the 873 ms reported for NFS to S3 AP in the first
measurement — and **it does not occur in production, where persistent connections are used.**

### Implications

- The consume (read) layer of this architecture delivers the same performance over NFS and over SMB
- The protocol choice follows from the client OS and the security model, not from performance
- Using SMB requires Active Directory (FSx for ONTAP does not support workgroup mode)
- Accessing an Origin with the UNIX security style over SMB applies access control based on UNIX
  permissions rather than NTFS ACLs

## Related documents

| Document | Contents |
|---|---|
| [FlexCache verification record](flexcache-s3ap-visibility.md) | The first FlexCache propagation measurement |
| [Same-volume verification record](s3ap-nfs-visibility.md) | The first same-volume measurement (the NFS to S3 direction is corrected in this record) |
| [Verification status](../verification-status.md) | The stage of each claim |
| [Glossary](../reference/glossary/object-access-on-ontap.md) | Telling the mechanisms apart |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/verification/cross-protocol-directions.md) | [English](cross-protocol-directions.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
