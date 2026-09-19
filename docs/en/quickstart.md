# The first hour: check that what S3 wrote can be read as a file
<!-- lang-switcher:start -->
🌐 [日本語](../ja/quickstart.md) | [English](quickstart.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->

Japanese is the authoritative version of this repository for technical accuracy; report any
discrepancy you find here.

One pass through this architecture in **the smallest form it has**. No decisions to make: fill in
two parameters, run six commands in order, delete it at the end.

**Nothing is measured here.** A throughput figure taken on a default configuration measures
something other than what it appears to (the last section says which defaults, and why).

## What this builds

| Item | Value |
|---|---|
| Built | One FSx for ONTAP file system (128 MBps, 1,024 GiB SSD), an SVM, a 10 GiB origin volume, one verification host (t3.small) |
| Checked | **That an object written through the S3 API can be read as a file from a host that mounts the same volume over NFS** |
| Time | 25 to 35 minutes to create, 10 minutes to check, 40 to 60 minutes to tear down |
| Cost | **About $0.4 per hour** (calculated from ap-northeast-1 list prices, retrieved 2026-09-04; the breakdown is in [the cost structure per verification pattern](../ja/reference/comparison/finops-performance-test-patterns.md) (Japanese)) |
| Not built | FlexCache, the serve side, Active Directory, SMB, a client sized for measurement |

**One pass establishes the semantics and nothing else.** "What was written is visible" and "it can
be read this fast" are separate questions, and the second one costs an order of magnitude more to
answer.

## Prerequisites

- One VPC and one subnet. **The file system and the verification host go in the same subnet**
- An authenticated `aws` CLI, and Python 3.12 or later
- The subnet must reach Session Manager. **Where it cannot, the host comes up healthy and is simply
  absent from Session Manager** -- the next step reads that

**No key pair.** The verification host has no inbound rule; you reach it through Session Manager.

## 1. Check the prerequisites

```bash
git clone https://github.com/Yoshiki0705/S3-Burst-on-ONTAP-Files
cd S3-Burst-on-ONTAP-Files
make preflight-pre VPC=vpc-xxxxxxxx SUBNET=subnet-xxxxxxxx MBPS=128
```

**What stops here is what is expensive to discover later.**

| What it reads | If it does not hold |
|---|---|
| Region-wide throughput capacity (10,240 MB/s by default; **other people's file systems share the pool**) | Creation fails. **You find out 25 minutes in** |
| The subnet is in the stated VPC, and has free addresses | Creation fails |
| Reachability to Session Manager | The host starts and never appears in Session Manager. **Twenty minutes with nothing saying why** |

Proceed when it prints `preflight: nothing blocking`.

## 2. Create the stack

**There are 21 parameters and two of them need a value.** The rest work as they are.

```bash
aws cloudformation create-stack \
  --stack-name s3burst-quickstart --region ap-northeast-1 \
  --template-body file://environments/aws-origin/template.yaml \
  --capabilities CAPABILITY_IAM \
  --parameters \
    ParameterKey=VpcId,ParameterValue=vpc-xxxxxxxx \
    ParameterKey=SubnetId,ParameterValue=subnet-xxxxxxxx

aws cloudformation wait stack-create-complete \
  --stack-name s3burst-quickstart --region ap-northeast-1
```

**`OriginVolumeSecurityStyle` defaults to `UNIX`, which pairs with NFS.** Set `NTFS` if the serve
side will be SMB. **Changing it later means rebuilding the serve layer**
([Decisions that come first](design-first-decisions.md)). This page continues with the UNIX default.

Note three outputs.

```bash
aws cloudformation describe-stacks --stack-name s3burst-quickstart \
  --region ap-northeast-1 \
  --query 'Stacks[0].Outputs[?OutputKey==`OriginVolumeId`||OutputKey==`StorageVirtualMachineId`||OutputKey==`VerificationHostId`].[OutputKey,OutputValue]' \
  --output text
```

## 3. Create the S3 Access Point

**Create the identity's user first.** The access point authorizes every request as the **UNIX user
named in `FileSystemIdentity`**, and a new SVM has only `root`, `pcuser` and `nobody`. **Create the
writing user yourself, and make it the owner of the volume root.**

Two calls on the ONTAP side, run from the verification host because the management endpoint is
VPC-only.

```bash
# On the host. PW is the fsxadmin password, from the OntapAdminSecretArn output
H=https://management.<FileSystemId>.fsx.ap-northeast-1.amazonaws.com/api
curl -s -k -u "fsxadmin:$PW" -X POST -H 'Content-Type: application/json' \
  -d '{"svm":{"name":"origin_svm"},"name":"s3ap","id":1001}' "$H/name-services/unix-groups"
curl -s -k -u "fsxadmin:$PW" -X POST -H 'Content-Type: application/json' \
  -d '{"svm":{"name":"origin_svm"},"name":"s3ap-writer","id":1001,"primary_gid":1001}' \
  "$H/name-services/unix-users"
```

**Give that user the volume root.** Doing it after the mount in step 4 also works, but **before the
access point exists is the tidier order** -- fixing permissions afterwards only adds a round of
working out why a write was refused.

```bash
sudo chown 1001:1001 /mnt/origin-noac     # the mount is the one from step 4
```

> **Being non-root is not itself the control.** What decides is **the effective permission that
> identity holds on the volume root**. This one writes, so it owns the root. **For a read-only access
> point, choose an identity the volume withholds write from** -- at `755`, one that is neither the
> owner nor in the owning group. The material for that decision is in
> [Deploying the collect side](deployment/aws-cloudformation.md#3-create-the-s3-access-point).

```bash
cd environments/aws-origin
cp access-point.example.json access-point.json
# Replace VolumeId and VpcId with the values above, and delete the keys starting with "_comment"
aws fsx create-and-attach-s3-access-point \
  --region ap-northeast-1 --cli-input-json file://access-point.json
cd ../..
```

**Pass a JSON file.** The positional form of `--ontap-configuration` parses badly, and the error it
produces does not point at the quoting.

> **`"Type": "ONTAP"` is required.** The example file did not carry it, so **the first end-to-end run
> of this page, on 2026-09-19, stopped at `Missing required parameter in input: "Type"`.** The
> example is fixed; it remains an easy field to miss when assembling the input by hand.

**Every request through the access point is authorized as one identity.** Callers are not
distinguished. The default is fine for this pass, but **a read-only access point needs the AWS-side
policy and the file-system permissions decided together**
([Deploying the collect side](deployment/aws-cloudformation.md#3-create-the-s3-access-point)).

## 4. Write, then read it as a file

```bash
aws ssm start-session --target <VerificationHostId> --region ap-northeast-1
```

On the host, read the SVM's NFS endpoint and mount it.

**Mount by DNS name.** The form is
`<StorageVirtualMachineId>.<FileSystemId>.fsx.<region>.amazonaws.com`.

```bash
SVM_DNS=<StorageVirtualMachineId>.<FileSystemId>.fsx.ap-northeast-1.amazonaws.com
sudo mount -t nfs -o nfsvers=3,actimeo=0 "$SVM_DNS":/origin_vol /mnt/origin-noac
```

> **Do not call `aws fsx describe-...` from the host.** This subnet carries only the Session Manager
> endpoints, so a request to `fsx.<region>.amazonaws.com` **times out**
> (`Connect timeout on endpoint URL: "https://fsx.ap-northeast-1.amazonaws.com/"`).
> **Walked into on 2026-09-19, following this page.** Resolve the IP from your own machine if you
> need it. **The DNS name needs no API call.**

**`actimeo=0` is there for a reason.** Linux caches a directory listing for up to 60 seconds, so
**a new file can be invisible for a minute regardless of what the storage did.** Use it when
freshness is the thing being checked: a deletion was reflected in 7 ms against more than 2 seconds
at the default.

Write, then read.

```bash
AP=arn:aws:s3:ap-northeast-1:<account-id>:accesspoint/<access-point-name>
echo hello > /tmp/check.txt
aws s3api put-object --bucket "$AP" --key check.txt --body /tmp/check.txt
cat /mnt/origin-noac/check.txt
aws s3api delete-object --bucket "$AP" --key check.txt
```

> **`--body` will not take standard input.** `--body /dev/stdin` fails with
> **`Blob values must be a path to a file`**, not with a length complaint. **Write the file first,
> then pass it** -- which is what `/tmp/check.txt` above is for. **Hit on 2026-09-19, the first time
> these steps were run.** This is a place where piping is the obvious move, so the extra line is
> deliberate.

**`hello` coming back is this architecture's central claim, confirmed once in your own account.**
The measured timings, and what they do and do not support, are in
[S3 Access Point and NFS visibility](verification/s3ap-nfs-visibility.md).

## 5. Tear it down

**The charge stops when the deletion finishes, not when it starts.**

```bash
aws fsx detach-and-delete-s3-access-point --region ap-northeast-1 --name <access-point-name>

# **Wait for it to be gone.** The call above returns at once and prints nothing.
while aws fsx describe-s3-access-point-attachments --region ap-northeast-1 \
        --names <access-point-name> >/dev/null 2>&1; do sleep 15; done

aws cloudformation delete-stack --stack-name s3burst-quickstart --region ap-northeast-1
aws cloudformation wait stack-delete-complete --stack-name s3burst-quickstart --region ap-northeast-1
make sweep
```

> **Moving on without waiting fails the stack deletion.** `detach-and-delete-s3-access-point` is
> **asynchronous and returns no body.** Deleting the stack immediately afterwards stops on the volume
> with `Cannot delete volume while it has one or multiple S3 access points: [<name>]`, and the stack
> lands in `DELETE_FAILED` (**walked into on 2026-09-19, following this page** -- three seconds
> later).
>
> **The completion signal is `describe-s3-access-point-attachments` answering
> `S3AccessPointAttachmentNotFound`.** The detach command's own output is empty and indicates
> neither success nor failure. **Re-running the stack deletion afterwards works**; nothing is left
> in a broken state.

**Do not skip `make sweep`.** Four kinds of resource do not stop with the stack, and **the final
backup carries no tags and a null file system id**, so a tag-filtered sweep finds none of them.
Once you have read the report and agree, `make sweep DELETE=1`.

## Why this stops here

**Measuring on this configuration returns something other than what it appears to.** The defaults
below invalidate a measurement, and **not one of them makes the number look unusual.**

| Default | What it does |
|---|---|
| One TCP connection for the NFS mount | Flat at about 590 MB/s. The same measurement with `nconnect` was 4.95 times higher |
| A `dd if=/dev/zero` payload | Zero blocks never reach storage, so the path is not being measured |
| Inline efficiency on the volume | Compression absorbs the payload and returns figures above the purchased ceiling |
| `DiskIopsConfiguration` at `AUTOMATIC` | SSD IOPS becomes the ceiling first |
| A read that only just exceeds the read cache | A read meant for the disk path is served from cache |
| SMB Multichannel disabled | Flat at 574 MB/s for 1 MiB sequential. Four channels was 3.88 times that |
| **`tcp-max-xfer-size` at 64 KiB** | A mount asking for `rsize=1048576` succeeds and still gets 64 KiB. Raising it was +21% on the same measurement |
| **Measuring from one client at low concurrency** | **You get that configuration's figure, not a ceiling.** Correcting the transfer size and the thread count moved a measured 1,195 to 1,646 MB/s |

**Two documents come before measuring**: the figures and their conditions in
[Performance expectations](performance-expectations.md), and the environments and pass conditions in
[the reproduction guide](../ja/verification/reproduction-guide.md) (Japanese).
**If the design can proceed without measuring, that is faster and cheaper.**

## What to read next

| Next question | Document |
|---|---|
| What this solves and does not solve | [The shape of the architecture](architecture.md) |
| Whether your current setup fits | [Starting from what you run today](reference/decision-trees/from-your-current-setup.md) |
| Fitting the parameters to your environment | [Choosing parameters](deployment/choosing-parameters.md) |
| Building the serve side as well | [Deploying the collect side](deployment/aws-cloudformation.md), then [the serve side](deployment/onprem-terraform.md) |
| Performance expectations | [Performance expectations](performance-expectations.md) |
| List every measurement record | [Index of measurement records](../ja/verification/README.md) (Japanese) |
| What differs from a production deployment | [From verification to production](../ja/from-verification-to-production.md) (Japanese) |

---

<!-- lang-switcher:start -->
🌐 [日本語](../ja/quickstart.md) | [English](quickstart.md) | [🏠 Repository home](README.md)
<!-- lang-switcher:end -->
