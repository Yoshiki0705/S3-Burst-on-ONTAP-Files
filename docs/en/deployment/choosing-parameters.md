# Choosing parameters: five of them need thought
<!-- lang-switcher:start -->
🌐 [日本語](../../ja/deployment/choosing-parameters.md) | [English](choosing-parameters.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

**There are 21 parameters** in
[`environments/aws-origin/template.yaml`](../../../environments/aws-origin/template.yaml). Two must
be filled in, three need a judgement, and the rest work as they are.

Cost comes first, because **only three places change it by an order of magnitude** and tuning
anything else does not move the figure.

## Three places where the cost changes by an order of magnitude

| Parameter | Default | Unit price | 128 against 2048 |
|---|---|---|---|
| **`ThroughputCapacityMBps`** | 128 | **$0.906 per MBps-month** (first generation) | About $0.16 per hour at 128, about **$2.58 per hour** at 2048. **Billed whether or not it is used** |
| **`HostInstanceType`** | `t3.small` | Instance price | `t3.small` is about $0.03 per hour, `c5n.9xlarge` is **$2.448 per hour**. **Stopping the instance stops this one** |
| **`StorageCapacityGiB`** | 1024 | **$0.15 per GB-month** | About $0.21 per hour for 1,024 GiB. **Billed on what is provisioned, not on what is used** |

Prices are ap-northeast-1 list prices, retrieved 2026-09-04. The breakdown and the other billing
dimensions are in [the cost structure per verification pattern](../../ja/reference/comparison/finops-performance-test-patterns.md) (Japanese).

**A fourth cost sits outside this template.** SSD IOPS lives in `DiskIopsConfiguration`, which the
template does not expose. The default is `AUTOMATIC` -- 3 IOPS per provisioned GiB -- and **it
becomes the read ceiling before anything else does.** Raising it is a post-creation
`aws fsx update-file-system` (**$0.0204 per IOPS-month for the addition**, 18 to 23 minutes to apply
when measured, and **a six-hour cooldown before it can be lowered**).

> **This is not a place to buy the larger option for safety.** Holding first-generation 2048 MBps
> costs about $1,855 a month. **If the question is semantics, 128 answers it**; raise the value only
> to measure, then lower it or delete the file system.

## The two that must be filled in

| Parameter | How to decide |
|---|---|
| `VpcId` | An existing VPC. The template does not create one |
| `SubnetId` | **The file system and the verification host both land here.** The host has to reach the management endpoint, and a single AZ keeps cross-AZ latency out of a measurement |

```bash
aws ec2 describe-vpcs --query 'Vpcs[].[VpcId,CidrBlock,Tags[?Key==`Name`]|[0].Value]' --output table
aws ec2 describe-subnets --filters Name=vpc-id,Values=vpc-xxxxxxxx \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock]' --output table
```

**Whether the subnet you picked will do is what `make preflight-pre` reads**: free addresses,
reachability to Session Manager, and the Region's quota headroom.

## Three that cannot be changed later

| Parameter | Why it is fixed | How to decide |
|---|---|---|
| **`OriginVolumeSecurityStyle`** | **Treated as inherited by the cache from the origin.** Changing it means rebuilding the serve layer | **`UNIX` for NFS**, **`NTFS` for SMB**. `MIXED` is not offered, because AWS describes it as for advanced users only. `NTFS` also needs a CIFS server on the SVM, which this template does not create |
| The access point's `FileSystemIdentity` | Immutable after creation | **Every request through the access point is authorized as this one identity.** Use separate access points for read-only and for writing |
| The access point's `NetworkOrigin` | Immutable after creation | `VPC` for a single-host check. Either way, calling from inside the VPC needs an S3 VPC endpoint and a route to it |

**The last two are not parameters of this template** -- the access point is created by a second
stack or by the CLI. **They are listed here because the ordering is the same for all three**: notice
any of them after the fact and something has to be rebuilt. The reasoning is in
[Decisions that come first](../design-first-decisions.md).

## Three that need a judgement

| Parameter | Default | When to change it |
|---|---|---|
| `DeployVerificationHost` | `true` | **`false` if you already have a host in the VPC.** Without one, no ONTAP-level step is possible at all -- FlexCache, peering, reading the release. The management endpoint is a private address |
| `AssociatePublicIp` | `false` | **`true` in a subnet with neither a NAT gateway nor VPC endpoints.** It is not an inbound path: the host's security group has no inbound rule. The output of `make preflight-pre` is enough to decide |
| `HostS3DataAccess` | `false` | **`true` when the host itself writes to S3.** Mounting does not need it. Having set it, narrow `HostS3ResourceArns` to the real ARNs -- the default is `*` |

> **The `*` default is deliberately visible rather than hidden.** The S3 Access Point comes from a
> separate stack and an S3 Files file system from a separate runbook, so **neither ARN exists when
> this template is applied.** Narrow them afterwards in an account shared with other people's
> buckets. `HostS3FilesResourceArns` and `HostEfsResourceArns` are separate statements: narrowing
> `HostS3ResourceArns` does not reach them.

## When to change the rest

| Parameter | Default | When it matters |
|---|---|---|
| `FileSystemName`, `SvmName`, `OriginVolumeName` | `s3burst-origin`, `origin_svm`, `origin_vol` | Running more than one in an account. **ONTAP names take alphanumerics and underscores only**, no hyphens |
| `OriginVolumeSizeMB` | 10240 (10 GiB) | When measuring. **A read measurement needs room for at least twice the in-memory cache in one pass** |
| `HostVolumeSizeGiB` | 20 | When the measurement tool and its logs have to fit (VDBENCH plus a JDK is several GiB) |
| `AllowFlexCachePeering`, `PeerSecurityGroupId` | `false`, empty | **Only when the cache side is a separate stack.** Both are needed before either takes effect. **Turning this on makes teardown order-dependent** ([Tear down](aws-cloudformation.md#5-tear-down)) |
| `HostS3ResourceArns`, `HostS3FilesResourceArns`, `HostEfsResourceArns` | `*` | Narrow after creation, as above |
| `ProjectName`, `Environment` | `s3-burst-on-ontap-files`, `verify` | Tags. **There is no `prod` value on purpose** -- this template builds a verification environment, not a production pattern ([From verification to production](../../ja/from-verification-to-production.md) (Japanese)) |

## Estimating for your own environment

**Do not reuse the figures in this repository as your own.** Unit prices differ by Region and change
over time.

1. **Fix the configuration** -- the three places above, and nothing else
2. **Work out the hourly rate**: `ThroughputCapacityMBps × $ per MBps-month ÷ 730`, plus
   `StorageCapacityGiB × $ per GB-month ÷ 730`, plus the instance
3. **Multiply by how long you hold it**, including the teardown. Deleting a file system took 53
   minutes when measured, and 63 minutes at 2.2 TiB
4. **Read `make sweep` afterwards.** A forgotten final backup or unattached volume stays for months
   -- four io2 volumes came to $361 a month

Where the unit prices come from, and the billing dimensions behind them, are in
[the FinOps cost structure](../reference/comparison/finops-s3-vs-s3ap.md).

## Related documents

- [The first hour](../quickstart.md) -- one pass through the smallest form
- [Deploying the collect side](aws-cloudformation.md) -- every step, and the table for when it does not work
- [Decisions that come first](../design-first-decisions.md) -- the one to settle before the origin volume exists
- [From verification to production](../../ja/from-verification-to-production.md) (Japanese) -- taking this template further
- [The cost structure per verification pattern](../../ja/reference/comparison/finops-performance-test-patterns.md) (Japanese) -- unit prices and what gets left behind

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/deployment/choosing-parameters.md) | [English](choosing-parameters.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
