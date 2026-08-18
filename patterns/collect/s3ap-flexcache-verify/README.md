# s3ap-flexcache-verify — Verification Environment Pattern

> **Status: `functionally-tested`** — deployed in ap-northeast-1 and used for the measurements in
> [the FlexCache verification record](../../../docs/ja/verification/flexcache-s3ap-visibility.md) and
> [the all-directions comparison](../../../docs/ja/verification/cross-protocol-directions.md)
> (2026-08-09 and 2026-08-10, ONTAP 9.18.1P3D1, both sides FSx for ONTAP). **The steps this template
> does not cover — the cluster peer, the SVM peer and the FlexCache itself — were run by hand, and
> with on-premises ONTAP as the cache nothing here has been exercised.** The vocabulary is defined in
> [the pattern template](../../_template/README.md#状態).

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

### Narrow the test host's permissions after step 1

The access point is created after the stack, so its ARN is not known at first deployment.
`S3AccessPointArn` therefore defaults to `*`, which grants `PutObject` and `GetObject` on every
bucket the role can reach. That is tolerable only in an isolated verification account. Once
`create-and-attach-s3-access-point` has returned an ARN, update the stack with it:

```bash
aws cloudformation deploy \
  --template-file template.yaml \
  --stack-name s3burst-verify \
  --parameter-overrides S3AccessPointArn=<ACCESS_POINT_ARN> \
  --capabilities CAPABILITY_IAM
```

`SmbCredentialSecretName` bounds the Secrets Manager read to one secret. It defaults to
`s3burst/smb-reader`, matching the `--secret-id` used under [Measure](#measure). If the secret is
named something else, set the parameter, otherwise `GetSecretValue` is denied.

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

The password is not a command-line argument. Supply it through the environment, or from Secrets
Manager with `--smb-cred-secret`. Use an account that can read the share; an administrator is not
needed.

```bash
sudo SMB_PASSWORD="$(aws secretsmanager get-secret-value \
  --secret-id s3burst/smb-reader --query SecretString --output text)" \
  python3 /opt/s3burst/measure_visibility.py \
  --s3ap-alias <S3_AP_ALIAS> \
  --nfs-lif <CACHE_DATA_LIF_IP> \
  --fc-path /s3burst_verify_fc \
  --origin-path /s3burst_verify \
  --smb-share smbtest \
  --smb-user "DOMAIN\\smbreader" \
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
