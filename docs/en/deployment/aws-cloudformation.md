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

> **Security note**: choosing `NTFS` requires the SVM to be joined to Active Directory, which this
> template does not do. On an AD-joined SVM **every** data operation through the S3 Access Point
> needs a reachable domain controller. `HeadBucket` succeeds even when the controller is unreachable,
> so it cannot be used to check connectivity. Always verify with a data operation.

## 2. Create the stack

```bash
cd environments/aws-origin
cp params.example.json params.json    # params.json is gitignored
# replace VpcId and SubnetId with your own

aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name s3burst-origin \
  --parameter-overrides file://params.json \
  --capabilities CAPABILITY_IAM \
  --region ap-northeast-1
```

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
> `AWS::FSx::FileSystem` exposes no attribute for it. The FSx API is not dependable either — on an
> existing file system `DescribeFileSystems` omitted `FileSystemTypeVersion` entirely. The reliable
> source is ONTAP itself, which is part of why this stack ships the credential and the port to reach
> it.

## 3. Create the S3 Access Point

CloudFormation has no resource for attaching an S3 Access Point to an FSx for ONTAP volume, so this
step uses the CLI.

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
| `FileSystemIdentity` | **Every request through the access point is authorized as this one identity.** Per-file ownership on the volume does not carry through it. Scope access with the access point policy and IAM. |
| `NetworkOrigin` | **Immutable after creation.** `VPC` keeps a single-host measurement off the public path. `Internet` is writable from outside but is not reachable through an S3 Gateway VPC endpoint. |

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
3. Detach the S3 Access Point.

   ```bash
   aws fsx detach-and-delete-s3-access-point --region ap-northeast-1 --name s3burst-origin-ap
   ```

4. Delete the stack.

   ```bash
   aws cloudformation delete-stack --stack-name s3burst-origin --region ap-northeast-1
   aws cloudformation wait stack-delete-complete --stack-name s3burst-origin --region ap-northeast-1
   ```

The Secrets Manager secret is deleted with a recovery window by default. Either wait, or pass
`--force-delete-without-recovery` deliberately, before reusing the name.

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
| `AccessDenied` through the access point | The AWS side (IAM and the access point policy) **and** the ONTAP side (file system identity) must both allow it |
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
