# Deploying the collect side (AWS / CloudFormation)

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/deployment/aws-cloudformation.md) | [English](aws-cloudformation.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

This builds the collect side of the architecture in one stack: the FSx for ONTAP file system, an SVM,
the origin volume, and a verification host inside the VPC. The template is
[`environments/aws-origin/template.yaml`](../../../environments/aws-origin/template.yaml).

The serve side is built with a different tool — see [Deploying the serve side](onprem-terraform.md),
and [the environments index](../../../environments/README.md) for why.

## Time required

| Step | Estimate |
|---|---|
| 1. Check the prerequisites | 5 min |
| 2. Create the stack | 25-40 min, mostly waiting for FSx for ONTAP |
| 3. Create the S3 Access Point | 5 min |
| 4. Mount and check | 10 min |
| 5. Tear down | 20 min |

## 1. Prerequisites

- **Decide the consuming site's protocol first.** Set `OriginVolumeSecurityStyle` to `UNIX` for NFS
  or `NTFS` for SMB. **Changing it later means rebuilding the serve layer.** The reasoning and its
  source are in [Decisions that come first](../design-first-decisions.md). MIXED is
  deliberately not offered.
- One VPC and one subnet. The file system and the verification host go in the same subnet.
- The subnet must reach Systems Manager, through a NAT gateway or SSM VPC endpoints. The verification
  host has no inbound rule and no key pair.
- An authenticated `aws` CLI.

**One command answers whether the prerequisites hold.** The two that bite before anything else --
the Region's quota pool and Session Manager reachability -- both surface **25 minutes, or 20
minutes, after the mistake** rather than at the moment of it.

```bash
make preflight-pre VPC=vpc-xxxxxxxx SUBNET=subnet-xxxxxxxx MBPS=128
```

| What it reads | If it does not hold |
|---|---|
| **Region-wide throughput capacity** (10,240 MB/s by default, shared with every other file system in the account) | Creation fails with `ServiceLimitExceeded`, **about 25 minutes in** |
| Region-wide SSD capacity | As above |
| The subnet is in the stated VPC, and has free addresses | Creation fails |
| **Reachability to Session Manager** (a 0.0.0.0/0 route, or the `ssm`, `ssmmessages` and `ec2messages` endpoints) | The host comes up healthy and is absent from Session Manager. **Twenty minutes with nothing saying why** |

**A quota that could not be read is reported as a finding**, not quietly compared against a default.

> **Security note**: choosing `NTFS` means the SVM needs a CIFS server. **This template creates
> neither a CIFS server nor an Active Directory join.** Joining AD is not required — where a domain is
> not available, workgroup mode is the documented alternative ([procedure](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html); NTLM only, no
> Kerberos). **If you do join AD**, every data operation through the S3 Access Point then needs a
> reachable domain controller. `HeadBucket` succeeds even when the controller is unreachable, so it
> cannot be used to check connectivity. Always verify with a data operation.

## 2. Create the stack

**There are 19 parameters and only two of them have to be edited.** The rest work as they are.
**One more must not be left at its default, because changing it later means a rebuild.**

| Parameter | What to do | Why |
|---|---|---|
| `VpcId` / `SubnetId` | **Replace with your own** | Left as they are, the create fails on IDs that do not exist |
| `OriginVolumeSecurityStyle` | **Defaults to `UNIX`. Set `NTFS` if the consuming side reads over SMB** | **It cannot be changed afterwards** — the one irreversible choice in [what to decide first](../design-first-decisions.md) |
| The other 16 | **Leave them** | They are the values the measurements used. Cost follows the estimate below, and rises in proportion with `StorageCapacityGiB` and `ThroughputCapacityMBps` |

**Finding `VpcId` and `SubnetId`:**

```bash
# List the VPCs in your account, with their Name tag
aws ec2 describe-vpcs --region ap-northeast-1 \
  --query 'Vpcs[].[VpcId,CidrBlock,Tags[?Key==`Name`].Value|[0]]' --output table

# List that VPC's subnets. The file system and the verification host go in the same subnet
aws ec2 describe-subnets --region ap-northeast-1 \
  --filters Name=vpc-id,Values=<the VpcId you chose> \
  --query 'Subnets[].[SubnetId,AvailabilityZone,CidrBlock,AvailableIpAddressCount]' --output table
```

**Look at `AvailableIpAddressCount`.** The file system takes several addresses, so a subnet with few
free ones fails the create — the first row of [when it does not work](#when-it-does-not-work).

```bash
cd environments/aws-origin
cp params.example.json params.json    # params.json is gitignored
#
# To measure throughput, start from params.throughput.example.json instead. It names c5n.9xlarge
# rather than t3.small and grants the host the S3 data path, so it costs materially more. The
# reason behind each difference is in that file's _comment.
# replace VpcId and SubnetId with the values found above

aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name s3burst-origin \
  --parameter-overrides file://params.json \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

> **The parameters to look at first in a shared account.** `HostS3DataAccess=true` opens three
> statements. **All three default to `"*"`, because the buckets and file systems are created outside
> this template.** Narrow all three once their ARNs exist.
>
> | Parameter | Narrowed value | Left at `"*"` |
> |---|---|---|
> | `HostS3ResourceArns` | The bucket / S3 Access Point ARNs | Object actions on every bucket in the account |
> | `HostS3FilesResourceArns` | `arn:aws:s3files:<region>:<account>:file-system/<id>` | Mount rights on every S3 Files file system in the account |
> | `HostEfsResourceArns` | `arn:aws:elasticfilesystem:<region>:<account>:file-system/<id>` | Mount rights on every EFS file system in the account |
>
> **All three can be narrowed.** The two mount parameters used to be described as un-narrowable
> because the client mount actions took no resource-level ARN. The
> [service authorization reference](https://docs.aws.amazon.com/service-authorization/latest/reference/list_s3files.html)
> lists `file-system` as required for `ClientMount`, `ClientWrite` and `ClientRootAccess`.

The `fsxadmin` password is generated into Secrets Manager and never leaves the template. Only the
verification host's IAM role can read it.

> **Operational note**: creating the secret alongside the file system addresses something that
> actually went wrong in an existing verification account, where the `fsxadmin` secret named a file
> system that no longer existed. Every ONTAP-only step — creating a FlexCache relationship among them
> — was therefore unavailable. A credential created with its file system does not develop that
> problem.

### Read the outputs

```bash
aws cloudformation describe-stacks --stack-name s3burst-origin \
  --query 'Stacks[0].Outputs[].{Key:OutputKey,Value:OutputValue}' --output table
```

`ManagementEndpoint` is reachable **from inside the VPC only**, never from a laptop. The ONTAP
version and the SVM's NFS endpoint are not available as CloudFormation attributes, so the outputs
carry the commands that read them instead.

> **Version note**: every published measurement has to state the ONTAP version, and
> `AWS::FSx::FileSystem` exposes no attribute for it. The Amazon FSx API is not dependable either — on an <!-- allow:naming - "Amazon FSx" is the service-family API name, not a shorthand for FSx for ONTAP -->
> existing file system `DescribeFileSystems` omitted `FileSystemTypeVersion` entirely. The reliable
> source is ONTAP itself, which is part of why this stack ships the credential and the port to reach
> it.

## 3. Create the S3 Access Point

`AWS::FSx::S3AccessPointAttachment` declares this, so the preferred route is a second stack:
[`patterns/collect/s3-access-point-attachment/`](../../../patterns/collect/s3-access-point-attachment/README.md).
It is a separate stack rather than part of the one above because the whole access point
configuration is create-only — a policy edit replaces the access point — and because the volume must
not be in a stack that a rename of the access point can disturb.

```bash
aws cloudformation deploy \
  --template-file patterns/collect/s3-access-point-attachment/template.yaml \
  --stack-name s3burst-collect-ap \
  --parameter-overrides file://params.json \
  --region ap-northeast-1
```

The CLI form below remains valid, and is the shorter route for a one-off that no stack has to own.

```bash
cp access-point.example.json access-point.json
# replace VolumeId and VpcId with the stack's outputs, and delete every key starting with _comment
# (the API rejects unknown top-level members)

aws fsx create-and-attach-s3-access-point \
  --region ap-northeast-1 \
  --cli-input-json file://access-point.json
```

**Pass a JSON file rather than positional arguments.** The positional form of
`--ontap-configuration` parses unreliably, and the error it produces does not point at the quoting.

Two decisions:

| Setting | What it means |
|---|---|
| `FileSystemIdentity` | **Every request through the access point is authorized as this one identity**, so callers are indistinguishable from each other. **Restriction lives in two places:** an explicit Deny in the access point policy on the AWS side (narrowing the `Allow` is not a restriction), and the file permissions — mode bits or ACLs — held by this identity on the file system side. **For read-only, decide both layers together.** What settles it is not that the identity is non-root but **the effective permission that identity holds on the volume root** (`uid`, `gid`, mode bits). A non-root identity can still write if the volume root grants it. Stopping it on the AWS side means an explicit Deny in the access point policy, and then even a root identity cannot write. The identity cannot be changed after creation, so a read-only consumer and a writer get separate access points. **The splitting itself is not a measurement but a design consequence of the one below.** What was measured is that with no access point policy attached, changing only the volume root's `uid`, `gid` and mode bits flipped `PutObject` between denial and success ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--file-system-permissions-are-what-narrow-access)). With no policy attached, a non-root identity (`nobody`, uid 65535) has also been measured to serve `GetObject` and to return `AccessDenied` for `PutObject`, while the same volume and the same caller with a root identity served both ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md#binding-a-non-root-identity-stops-writes-with-no-policy-at-all); `ap-northeast-1`, ONTAP 9.18.1P3D1, 2026-08-18). **That measurement depends on the volume being `755`, with no `w` for others.** At `775` or `777`, or where the identity is the owner or in the owning group, it can write. **Without checking the mode bits, "non-root, therefore read-only" does not hold.** |
| `NetworkOrigin` | **Immutable after creation.** `VPC` keeps a single-host measurement off the public path. `Internet` is writable from outside the VPC as well. **Either way, a caller inside the VPC needs an S3 VPC endpoint whose route is associated with that subnet's route table.** A sibling repository has observed connection timeouts from an in-VPC Lambda that had no such route. |

## 4. Mount and check

Connect to the verification host with Session Manager.

```bash
aws ssm start-session --target <VerificationHostId> --region ap-northeast-1
```

Read the SVM's NFS endpoint and mount. Two mount points are prepared.

```bash
NFS_IP=$(aws fsx describe-storage-virtual-machines --region ap-northeast-1 \
  --storage-virtual-machine-ids <StorageVirtualMachineId> \
  --query 'StorageVirtualMachines[0].Endpoints.Nfs.IpAddresses[0]' --output text)

sudo mount -t nfs -o nfsvers=3,actimeo=0 "$NFS_IP":/origin_vol /mnt/origin-noac
sudo mount -t nfs -o nfsvers=3          "$NFS_IP":/origin_vol /mnt/origin-cached
```

**The mount options change what you see, and this is measured, not theoretical.** Linux defaults are
`acdirmin=30` and `acdirmax=60`, so a file appearing in a directory the client has already listed can
stay invisible for up to a minute for reasons unrelated to the storage. A delete was reflected in 7 ms
with `actimeo=0` and took over two seconds with the defaults. Use `actimeo=0` when measuring or when
freshness matters; use the defaults when re-reading the same files.

Check with a **data operation**.

```bash
AP=arn:aws:s3:ap-northeast-1:<account-id>:accesspoint/s3burst-origin-ap
echo hello | aws s3api put-object --bucket "$AP" --key check.txt --body /dev/stdin
cat /mnt/origin-noac/check.txt          # expect this within tens of milliseconds
aws s3api delete-object --bucket "$AP" --key check.txt
```

The measured figures, and what they do and do not support, are in the
[verification record](../verification/s3ap-nfs-visibility.md).

## 5. Tear down

**The order changes the outcome.** Do not delete the collect side while the serve side still exists.

1. Delete the serve side first — see [Deploying the serve side](onprem-terraform.md).
2. Release the SVM peer, then the cluster peer.

   > **Skipping this stalls step 4.** While an SVM peer remains, FSx for ONTAP will not delete the SVM, and the
   > stack fails with `svmLifecycle should be DELETING, but get: MISCONFIGURED`.
   >
   > **And step 4 deletes the only host that can carry out step 2.** The management LIF is a private
   > address, so once the verification host is gone there is no route left into ONTAP.
   >
   > Recovering from the wrong order takes four moves: **stand up a host in the same subnet that can
   > reach ONTAP**, release the peers, and **delete the SVM directly with
   > `aws fsx delete-storage-virtual-machine`** before retrying the stack deletion.
   > **CloudFormation reads the `MISCONFIGURED` lifecycle and declines before calling delete; the FSx for ONTAP
   > API accepts the same call in the same state.**
   >
   > The fourth move is **when to delete that host**. Keep it until the SVM is confirmed gone -- until
   > `aws fsx describe-storage-virtual-machines` no longer returns it. **A failed retry needs the same
   > host again.** This step comes from the sibling repository's DR runbook; here the host was deleted
   > first, the SVM turned out to still be `MISCONFIGURED`, and it had to be stood up twice.
   >
   > The record of walking into this is in
   > [the inheritance record](../../ja/verification/flexcache-security-style-inheritance.md#この手順で踏んだ罠) (Japanese).

3. Detach the S3 Access Point.

   ```bash
   aws fsx detach-and-delete-s3-access-point --region ap-northeast-1 --name s3burst-origin-ap
   ```

4. Delete the stack.

   ```bash
   aws cloudformation delete-stack --stack-name s3burst-origin --region ap-northeast-1
   aws cloudformation wait stack-delete-complete --stack-name s3burst-origin --region ap-northeast-1
   ```

**With `AllowFlexCachePeering` on, there is one move before step 1.**
**While two stacks reference each other's security groups, neither can delete its groups.** EC2
replies `has a dependent object` and **does not name the object**. That failed the origin stack's
deletion twice on 2026-09-18. **Revoke the cross-references on both sides first.**

```bash
# For both groups, find the ingress rules that reference another group, and revoke them
for sg in <origin-fs-sg> <cache-fs-sg>; do
  for id in $(aws ec2 describe-security-group-rules --filters Name=group-id,Values=$sg \
      --query 'SecurityGroupRules[?ReferencedGroupInfo.GroupId!=null].SecurityGroupRuleId' \
      --output text | tr '\t' '\n'); do
    aws ec2 revoke-security-group-ingress --group-id "$sg" --security-group-rule-ids "$id"
  done
done
```

**Once the stack is gone, sweep what it left.** Four kinds of resource do not stop with it: the
final backup, unattached EBS volumes, the secrets, and volumes or SVMs whose parent is gone.

```bash
python3 scripts/sweep_after_teardown.py --region ap-northeast-1              # report only
python3 scripts/sweep_after_teardown.py --region ap-northeast-1 --delete --yes
```

**The final backup carries no tags and its `FileSystem.FileSystemId` is null**, so a tag-filtered
sweep finds none of them. `SkipFinalBackup` is not a property `AWS::FSx::Volume` accepts, so the
backup is always taken.

The Secrets Manager secret is deleted with a recovery window by default. Either wait, or pass
`--force-delete-without-recovery` deliberately, before reusing the name. **The script above
schedules deletion with a seven-day window**, which keeps the one reversible deletion here
reversible.

> **Irreversibility note**: this template enables neither SnapLock nor snapshot locking. Enabling
> either makes the volume, its SVM and **the entire file system** undeletable for the retention
> period, and a verification environment is the worst place for that. Do not enable one without an
> explicit instruction naming the retention value.

## When it does not work

| Symptom | Where to look |
|---|---|
| The stack fails creating the file system | Free IPs in the subnet; characters in the `fsxadmin` password that ONTAP rejects |
| Cannot reach the management endpoint | Are you inside the VPC? The ONTAP management interface is VPC-only |
| `mount` times out | Security groups. NFSv3 uses 111, 635 and 4045-4046 as well as 2049 |
| `AccessDenied` through the access point | The AWS side (IAM and the access point policy) **and** the ONTAP side (file system identity) must both allow it. **The error body says which one.**<br>- an unqualified `Access Denied` and nothing more → **Layer 2**. File permissions are short. **No policy explains it**; check the volume root's owner and mode bits<br>- `... with an explicit deny in a resource-based policy` → Layer 1, hitting an explicit Deny in the access point policy<br>- `... because no identity-based policy allows the s3:<action> action` → Layer 1, with nothing granting it (still an implicit deny)<br>**All three were measured in one environment** ([measured](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md#binding-a-non-root-identity-stops-writes-with-no-policy-at-all)). A Layer 2 denial happens even with no access point policy attached ([same](https://github.com/Yoshiki0705/FSx-for-ONTAP-Adoption-Playbook/blob/main/docs/en/domains/security-governance/notes/access-point-authorization-layers.md#layer-2--file-system-permissions-are-what-narrow-access)). |
| One newly added access point returns `AccessDenied` while the others work | **Where the VPC endpoint policy is restricted, the new access point's ARN is not among the resources it allows.** The default is allow-all, so an environment that has not restricted it never notices the layer ([configuring network access](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/configuring-network-access-for-s3-access-points.html); AWS-documented, not measured here) |
| `HeadBucket` passes but data operations fail | On an AD-joined SVM, domain controller reachability. `HeadBucket` is a false positive |
| Written but not visible over NFS | Mount options. Check on the `actimeo=0` mount point |

## Related documents

| Document | Contents |
|---|---|
| [Deploying the serve side](onprem-terraform.md) | The FlexCache half |
| [Decisions that come first](../design-first-decisions.md) | What to settle before the origin exists |
| [Verification record](../verification/s3ap-nfs-visibility.md) | Measured figures and conditions |
| [PoC checklist](../poc-checklist.md) | The order to confirm things in |
| [Architecture](../architecture.md) | The whole picture |

---

<!-- lang-switcher:start -->
🌐 [日本語](../../ja/deployment/aws-cloudformation.md) | [English](aws-cloudformation.md) | [🏠 Repository home](../README.md)
<!-- lang-switcher:end -->
