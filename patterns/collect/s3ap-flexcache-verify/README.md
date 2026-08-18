# s3ap-flexcache-verify — Verification Environment Pattern

Deploys the infrastructure needed to measure S3 AP → FlexCache visibility latency
on existing FSx for ONTAP file systems.

## What it creates

| Resource | Purpose |
|---|---|
| VPC Peering | Connects origin and cache VPCs |
| Routes | Bidirectional routing between VPCs |
| SG Rules | Intercluster (10000, 11104-11105), NFS (2049), SMB (445), ONTAP REST (443) |
| EC2 Instance | Measurement host in cache VPC (SSM access, no SSH key needed) |
| FSx for ONTAP Volume | Origin test volume with chosen security style |
| IAM Role | S3 + Secrets Manager access for the test host |

## What requires manual steps (post-deploy)

CloudFormation does not support these FSx for ONTAP resources natively:

1. **S3 Access Point** — `aws fsx create-and-attach-s3-access-point`
2. **Cluster Peer** — ONTAP CLI `cluster peer create`
3. **SVM Peer** — ONTAP CLI `vserver peer create`
4. **FlexCache** — ONTAP CLI `volume flexcache create`

The stack's `PostDeploySteps` output provides the exact commands.

## Deploy

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name s3burst-verify \
  --parameter-overrides file://params.json \
  --capabilities CAPABILITY_IAM
```

## Measure

After completing post-deploy steps, connect to the test host via SSM:

```bash
aws ssm start-session --target <TestHostInstanceId>

# Run measurement
sudo python3 /opt/s3burst/measure_visibility.py \
  --s3ap-alias <S3_AP_ALIAS> \
  --nfs-lif <CACHE_DATA_LIF_IP> \
  --fc-path /s3burst_verify_fc \
  --origin-path /s3burst_verify \
  --iterations 30 \
  --output /tmp/results.json
```

For SMB measurement (the SVM needs a CIFS server; an Active Directory join is one way to get one,
[workgroup mode](https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/smb-server-workgroup-setup.html) is the
documented alternative):

```bash
sudo python3 /opt/s3burst/measure_visibility.py \
  --s3ap-alias <S3_AP_ALIAS> \
  --nfs-lif <CACHE_DATA_LIF_IP> \
  --fc-path /s3burst_verify_fc \
  --origin-path /s3burst_verify \
  --smb-share smbtest \
  --smb-user "DOMAIN\\Admin" \
  --smb-pass "Password" \
  --output /tmp/results.json
```

## Teardown

```bash
# 1. Delete FlexCache (ONTAP CLI)
volume unmount -vserver <svm> -volume s3burst_verify_fc
volume offline -vserver <svm> -volume s3burst_verify_fc
volume flexcache delete -vserver <svm> -volume s3burst_verify_fc

# 2. Delete S3 Access Point
aws fsx detach-and-delete-s3-access-point --name s3burst-verify-ap

# 3. Delete CloudFormation stack (removes peering, routes, SG rules, EC2, volume)
aws cloudformation delete-stack --stack-name s3burst-verify
```

## Security style note

This template offers UNIX and NTFS only. `mixed` is not included because it is
[not recommended by AWS](https://aws.amazon.com/blogs/storage/enabling-multiprotocol-workloads-with-amazon-fsx-for-netapp-ontap/)
(labeled "advanced users only"). See [design-first-decisions](../../../docs/ja/design-first-decisions.md).
