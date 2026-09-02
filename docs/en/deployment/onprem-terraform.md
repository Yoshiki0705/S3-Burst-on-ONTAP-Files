# Deploying the serve side (outside AWS / Terraform)

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/deployment/onprem-terraform.md) | [English](onprem-terraform.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

This builds the serve side: the FlexCache volume and a read-only NFS export. The configuration is
[`environments/onprem-cache/`](../../../environments/onprem-cache/).

Build the collect side first — see [Deploying the collect side](aws-cloudformation.md). A FlexCache
cannot be created without its origin.

## Time required

| Step | Estimate |
|---|---|
| 1. Check the prerequisites | 10 min |
| 2. Establish peering | 20-60 min, depending on your network |
| 3. `terraform apply` | 5 min |
| 4. Mount and check | 10 min |
| 5. Tear down | 10 min |

## 1. Prerequisites

- The origin volume from the collect side exists.
- An ONTAP cluster for the cache: on-premises AFF or FAS, ONTAP Select, or a second FSx for ONTAP.

  > **Supported-configuration note**: AWS documents exactly three FlexCache configurations, and with
  > FSx for ONTAP as the origin the cache is **on-premises ONTAP or FSx for ONTAP only**. Whether
  > Cloud Volumes ONTAP, ONTAP Select, Azure NetApp Files or Google Cloud NetApp Volumes can be the
  > cache is **unconfirmed** — no public statement was found either way. "It is ONTAP-based, so it
  > works" does not follow. See [Portability](../portability.md).

- **Run Terraform from somewhere that can reach the cache cluster's management endpoint.** When the
  cache is a second FSx for ONTAP that endpoint is VPC-only, so running from a laptop produces a
  network timeout that does not look like a configuration error.
- Terraform 1.9 or later.

## 2. Establish peering

**This configuration does not create peering.** Cluster peering and SVM peering must exist first.

What is required is IP reachability between the two clusters' intercluster LIFs. Across VPCs that
means VPC peering or a transit gateway, with **routes on both sides**. That topology is owned outside
this repository, so this configuration does not touch it.

**This is the most common reason a FlexCache creation fails**, and the error usually names a
permission or connectivity problem rather than the missing peering. If `apply` fails, check peering
before anything else.

```bash
# on the cache cluster
cluster peer show
vserver peer show
```

### Five things that actually went wrong doing this

A record of running the whole sequence over the REST API against two FSx for ONTAP file systems
(ONTAP 9.18.1P5, 2026-09-01; the measurement record is
[in Japanese](../../ja/verification/throughput-iops-concurrency.md#flexcache-経由の読み取り) (Japanese)).
**In each case the error message names a symptom rather than the cause.**

| Symptom | Actual cause |
|---|---|
| `Aggregates not matching FabricPool requirements: aggr1` | **`use_tiered_aggregate` defaults to false.** FSx for ONTAP aggregates are FabricPool-attached, so the default asks for a non-FabricPool aggregate and finds none. **Setting it true works.** The message names the aggregate and never mentions the flag |
| `Volume ... results in a volume that is too small - 20GB` | **The minimum FlexCache volume is 50 GB.** 20 GiB was rejected |
| `The value "180" is invalid for field "return_timeout" (<0..120>)` | `return_timeout` caps at 120 |
| The SVM peer stays `pending` | **It has to be accepted explicitly on the origin side**: `PATCH /api/svm/peers/{uuid}` with `{"state":"peered"}`. The initiating side reads `initiated`, the other `pending` |
| ONTAP REST returns HTTP 401 with `User is not authorized.` | **An authentication mismatch, not a permissions problem.** The generated fsxadmin password was not the file system's effective password. See the corresponding row in the verification status |

Deletion has an order too, and **each step blocks the next with a message that does not name it.**

1. **Unjunction the volume inside ONTAP** (`PATCH /api/storage/volumes/{uuid}` with
   `{"nas":{"path":""}}`). This is not the client `umount`; skipping it stops with
   `Volume ... must be unmounted before being taken offline`
2. Delete the FlexCache
3. **Delete the SVM peers and wait for them to go.** The delete is asynchronous, so moving on
   immediately fails
4. Delete the cluster peers. With an SVM peer still present this is refused with
   `SVM peering relationships exist with the cluster`

**Confirm by counting, not by the return value of the delete.** A run that merely failed to
authenticate produces output that reads as "there is nothing there". That trap was hit for real: the
teardown ran on a host that could not read the secret and reported that no FlexCache existed.

### Three more things when the cache is in another Region

The same procedure run across Regions -- origin in ap-northeast-1, cache in ap-northeast-3, joined by
an inter-Region VPC peering
([record](../../ja/verification/throughput-iops-concurrency.md#リージョンを跨いだ-flexcache読み手が遠い場合) (Japanese)).
**Three failures appear that do not happen within one Region.**

| Symptom | What is actually wrong |
|---|---|
| The ONTAP REST call returns an empty body and `curl` reports success | **The DNS name of an FSx for ONTAP management endpoint resolves only inside that file system's own VPC.** An inter-Region VPC peering does not carry the private hosted zone. Use the IP addresses instead of the name (below) |
| A security group rule cannot reference the peer's security group ID | **Security group references do not work across Regions.** Write CIDRs. The ports needed are **11104-11105** for intercluster, **443** for ONTAP REST, and **2049** for NFS |
| The host cannot read the other Region's Secrets Manager secret | The host role only permits its own stack's secret. Grant it explicitly with an inline policy. **Remove that policy before deleting the stack, or the role delete fails** |

The management and intercluster addresses come from the API, which also removes the need to look up
the ONTAP LIFs.

```bash
aws fsx describe-file-systems --file-system-ids <fs-id> --region <cache region> \
  --query 'FileSystems[0].OntapConfiguration.Endpoints.{Management:Management.IpAddresses,Intercluster:Intercluster.IpAddresses}'
```

**All three present as nothing happening rather than as a failure to create.** An empty body reads
like a failed credential or an absent object, so **make one call by IP rather than by name** first and
let that separate the two.

## 3. `terraform apply`

```bash
cd environments/onprem-cache
cp terraform.tfvars.example terraform.tfvars    # terraform.tfvars is gitignored
# fill in the values

export TF_VAR_cache_cluster_password="$(aws secretsmanager get-secret-value \
  --secret-id <secret-id> --query SecretString --output text | jq -r .password)"

terraform init
terraform plan
terraform apply
```

**Do not put the password in `terraform.tfvars`.** Terraform writes variable values into the state
file in clear text, including values marked sensitive, so the password would be readable in two places
instead of one. Keep state in a backend with encryption and access control as well.

`allowed_clients` takes the consuming site's network and has no default: an export rule is an access
control decision, and `0.0.0.0/0` is rejected by a variable validation rather than merely discouraged.

### What gets created

| Resource | Notes |
|---|---|
| FlexCache volume | The cache volume is created *by* the FlexCache relationship. **No separate volume resource.** |
| Export policy | Read-only. `rw_rule` and `superuser` are `none`. |

FlexCache is sparse: it holds the blocks that have actually been read, not a copy of the origin.
`cache_volume_size_gb` is a **ceiling**, not an allocation.

> **Size note**: the default of 50 GB is the minimum FlexCache volume size on FSx for ONTAP as
> recorded in a sibling repository. It is **unverified here**, so treat it as a starting point — if
> your cluster accepts less, it costs less.

Write mode is left at its default. Enabling writeback means that an S3 Access Point write and a
cache-side write to the same file cause the cache's dirty data to be discarded. In this architecture
writes are concentrated on the origin, so there is no reason to enable it.

## 4. Mount and check

```bash
sudo mount -t nfs -o nfsvers=3,actimeo=0 <cache-svm-nfs-ip>:/cache_vol /mnt/cache
```

`terraform output mount_command` prints both forms.

**The mount options change what you see.** With Linux defaults (`acdirmin=30`, `acdirmax=60`) a file
appearing in a directory the client has already listed can be invisible for up to a minute. This was
measured on the collect side — see the
[verification record](../verification/s3ap-nfs-visibility.md).

> **Stated as unverified**: that an object written through the S3 Access Point becomes readable over
> NFS on the cache side **is verified with FSx for ONTAP on the cache side too**
> ([FlexCache verification record](../verification/flexcache-s3ap-visibility.md)).
> **With on-premises ONTAP as the cache, which is what this guide covers, it is unverified.** The
> latency of that path, and whether the security style is inherited, are both first answered there.
> Record whatever you observe here, with its environment, in
> [Verification status](../verification-status.md). A negative result is as valuable as a positive
> one.

## 5. Tear down

**The order changes the outcome.**

```bash
terraform destroy
```

Then, before the collect side, release:

1. the SVM peer
2. the cluster peer
3. VPC peering or the transit gateway attachment
4. the collect-side stack — see [Deploying the collect side](aws-cloudformation.md)

`terraform destroy` removes the cache volume and the export policy only. The peering it was not
created here, and it is not removed here.

## When it does not work

| Symptom | Where to look |
|---|---|
| `terraform init` cannot fetch the provider | Registry reachability. The provider version is pinned exactly |
| `apply` fails with a permission or connection error | **Peering first.** The error does not name the missing peering |
| Unreachable or timing out | If the cache is FSx for ONTAP the management endpoint is VPC-only. Run from inside the VPC |
| Certificate validation fails | For a lab cluster with a self-signed certificate set `validate_certs = false` **deliberately**. Do not loosen the default |
| A security style difference appears on every plan | It is not settable on the cache. Decide it on the origin |
| Cannot write to the cache | The export policy is read-only, by intent. Writes go to the origin's S3 Access Point |

## Related documents

| Document | Contents |
|---|---|
| [Deploying the collect side](aws-cloudformation.md) | The origin half |
| [Decisions that come first](../design-first-decisions.md) | Security style and protocol |
| [Portability](../portability.md) | Supported configurations and unconfirmed combinations |
| [Verification record](../verification/s3ap-nfs-visibility.md) | Measured figures and conditions |
| [PoC checklist](../poc-checklist.md) | The order to confirm things in |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/deployment/onprem-terraform.md) | [English](onprem-terraform.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
