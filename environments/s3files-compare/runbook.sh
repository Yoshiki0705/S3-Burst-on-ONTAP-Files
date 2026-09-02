#!/usr/bin/env bash
# =================================================================================================
# S3 Files measurement environment — create, measure, destroy.
#
# This is the CLI sequence that was actually run on 2026-09-01 to produce
# docs/ja/verification/s3files-measured.md, reduced to the steps that mattered and made idempotent.
# The CloudFormation template in this directory builds the same thing declaratively but has not been
# deployed; this script is the path with evidence behind it.
#
# It creates billable resources. They are small — the measured S3 Files charge for one 30-iteration
# run was $0.001023 — but the EC2 host and the bucket are not free, so run `destroy` when done.
#
# Nothing here enables an immutability feature. There is no Object Lock, no retention and no vault
# lock, so every object and version deletes on request. Versioning IS enabled, because S3 Files
# requires it; versioning is not immutability.
#
# Usage:
#   ./runbook.sh create     # bucket, sync role, file system, mount target, access point, host
#   ./runbook.sh measure    # install the client, mount, run the measurement
#   ./runbook.sh metrics    # pull the CloudWatch counters and price the run
#   ./runbook.sh destroy    # remove everything this script created, then verify nothing remains
#
# Prerequisites: AWS CLI v2 (v1 cannot resolve the s3files endpoint), credentials for the target
# account, and an existing VPC and subnet passed in as environment variables:
#   VPC_ID=vpc-0123456789abcdef0 SUBNET_ID=subnet-0123456789abcdef0 ./runbook.sh create
# =================================================================================================
set -uo pipefail

REGION=${AWS_REGION:-ap-northeast-1}
PREFIX=${PREFIX:-s3burst-s3files-verify}
STATE=${STATE:-./.s3files-run.env}
ITERATIONS=${ITERATIONS:-30}
# t3.small is enough for the semantics and reflection-time measurement this script was written for.
# It is not enough to find where the file path's throughput stops: the client's own network
# allowance and the CPU cost of `efs-proxy --tls` both land inside the range being measured, so a
# ceiling found on it cannot be attributed to S3 Files. Override for a throughput sweep, and use the
# same instance type as any FSx for ONTAP measurement being compared against.
INSTANCE_TYPE=${INSTANCE_TYPE:-t3.small}
HOST_VOLUME_GIB=${HOST_VOLUME_GIB:-20}

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n== %s ==\n' "$1"; }
save() { echo "$1=$2" >> "$STATE"; }

command -v aws >/dev/null || die "aws CLI not found"
[[ "$(aws --version 2>&1)" == aws-cli/2* ]] || die "AWS CLI v2 is required for the s3files commands"

# ------------------------------------------------------------------------------------------ create
create() {
  : "${VPC_ID:?set VPC_ID}" "${SUBNET_ID:?set SUBNET_ID}"
  [[ -f "$STATE" ]] && die "$STATE exists; run destroy first or move it aside"
  : > "$STATE"
  local acct bucket role_arn fs mt ap host_sg mt_sg iid ami
  acct=$(aws sts get-caller-identity --query Account --output text)
  local tags="Key=Project,Value=s3-burst-on-ontap-files Key=Environment,Value=verify"

  step "bucket, with the three hard prerequisites"
  bucket="${PREFIX}-$(openssl rand -hex 4)"
  aws s3api create-bucket --bucket "$bucket" --region "$REGION" \
    --create-bucket-configuration "LocationConstraint=${REGION}" >/dev/null
  # Versioning: S3 Files synchronises with version-specific API operations and refuses a bucket
  # without it. Encryption: SSE-S3 or SSE-KMS only. ACLs disabled: S3 Files does not preserve S3
  # ACLs across changes made through the file system.
  aws s3api put-bucket-versioning --bucket "$bucket" --versioning-configuration Status=Enabled
  aws s3api put-bucket-encryption --bucket "$bucket" --server-side-encryption-configuration \
    '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"},"BucketKeyEnabled":true}]}'
  aws s3api put-public-access-block --bucket "$bucket" --public-access-block-configuration \
    'BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true'
  aws s3api put-bucket-ownership-controls --bucket "$bucket" \
    --ownership-controls 'Rules=[{ObjectOwnership=BucketOwnerEnforced}]'
  save BUCKET "$bucket"; echo "  $bucket"

  step "synchronisation role"
  # The service principal is elasticfilesystem.amazonaws.com, not s3files.amazonaws.com. S3 Files is
  # built on Amazon EFS and assumes the role under the EFS principal. Verified by the service
  # creating its EventBridge rule with ManagedBy: elasticfilesystem.amazonaws.com -- the create call
  # succeeding proves nothing, because S3 Files does not validate the role at creation time and a
  # wrong trust policy leaves the file system stuck in `creating` instead.
  cat > /tmp/rb-trust.json <<EOF
{"Version":"2012-10-17","Statement":[{"Effect":"Allow",
 "Principal":{"Service":"elasticfilesystem.amazonaws.com"},"Action":"sts:AssumeRole",
 "Condition":{"StringEquals":{"aws:SourceAccount":"${acct}"},
   "ArnLike":{"aws:SourceArn":"arn:aws:s3files:${REGION}:${acct}:file-system/*"}}}]}
EOF
  cat > /tmp/rb-sync.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3:ListBucket","s3:ListBucketVersions"],
  "Resource":"arn:aws:s3:::${bucket}"},
 {"Effect":"Allow","Action":["s3:AbortMultipartUpload","s3:DeleteObject*","s3:GetObject*",
  "s3:List*","s3:PutObject*"],"Resource":"arn:aws:s3:::${bucket}/*"},
 {"Effect":"Allow","Action":["events:DeleteRule","events:DisableRule","events:EnableRule",
  "events:PutRule","events:PutTargets","events:RemoveTargets"],
  "Condition":{"StringEquals":{"events:ManagedBy":"elasticfilesystem.amazonaws.com"}},
  "Resource":["arn:aws:events:*:*:rule/DO-NOT-DELETE-S3-Files*"]},
 {"Effect":"Allow","Action":["events:DescribeRule","events:ListRuleNamesByTarget",
  "events:ListRules","events:ListTargetsByRule"],"Resource":["arn:aws:events:*:*:rule/*"]}]}
EOF
  role_arn=$(aws iam create-role --role-name "${PREFIX}-sync-role" \
    --assume-role-policy-document file:///tmp/rb-trust.json --tags $tags \
    --query 'Role.Arn' --output text)
  aws iam put-role-policy --role-name "${PREFIX}-sync-role" --policy-name sync --policy-document file:///tmp/rb-sync.json
  rm -f /tmp/rb-trust.json /tmp/rb-sync.json
  save SYNC_ROLE "${PREFIX}-sync-role"
  sleep 15   # IAM propagation; a create that fails now says nothing about the trust policy

  step "file system"
  # --bucket takes an ARN, not a name.
  fs=$(aws s3files create-file-system --region "$REGION" --bucket "arn:aws:s3:::${bucket}" \
    --role-arn "$role_arn" --accept-bucket-warning \
    --tags "key=Project,value=s3-burst-on-ontap-files" "key=Environment,value=verify" \
    --query fileSystemId --output text)
  save FS "$fs"; echo "  $fs"
  until [[ "$(aws s3files get-file-system --region "$REGION" --file-system-id "$fs" \
    --query status --output text)" == available ]]; do sleep 10; done
  echo "  available"
  # Control: the service only creates this rule if it really assumed the role.
  aws events list-rules --region "$REGION" --name-prefix DO-NOT-DELETE-S3-Files \
    --query 'Rules[0].ManagedBy' --output text | sed 's/^/  role assumed by: /'

  step "security groups and mount target"
  host_sg=$(aws ec2 create-security-group --group-name "${PREFIX}-host" --vpc-id "$VPC_ID" \
    --description "S3 Files measurement host. No inbound; access via SSM." --query GroupId --output text)
  mt_sg=$(aws ec2 create-security-group --group-name "${PREFIX}-mt" --vpc-id "$VPC_ID" \
    --description "S3 Files mount target. Inbound 2049 from the measurement host only." --query GroupId --output text)
  # One port. The helper's TLS and IAM ride the same 2049, so there is no second rule to add.
  aws ec2 authorize-security-group-ingress --group-id "$mt_sg" \
    --ip-permissions "IpProtocol=tcp,FromPort=2049,ToPort=2049,UserIdGroupPairs=[{GroupId=$host_sg}]" >/dev/null
  save HOST_SG "$host_sg"; save MT_SG "$mt_sg"
  mt=$(aws s3files create-mount-target --region "$REGION" --file-system-id "$fs" \
    --subnet-id "$SUBNET_ID" --security-groups "$mt_sg" --query mountTargetId --output text)
  save MT "$mt"
  until [[ "$(aws s3files get-mount-target --region "$REGION" --mount-target-id "$mt" \
    --query status --output text)" == available ]]; do sleep 10; done
  echo "  $mt available"

  step "access point"
  # Required, not optional. Without ClientRootAccess a scoped policy denies even mkdir by root at
  # the mount root. Mapping to a POSIX identity is the documented alternative and does not hand out
  # a permission that bypasses POSIX checks.
  ap=$(aws s3files create-access-point --region "$REGION" --file-system-id "$fs" \
    --posix-user "uid=1000,gid=1000" \
    --root-directory "path=/measure,creationPermissions={ownerUid=1000,ownerGid=1000,permissions=0755}" \
    --query accessPointId --output text)
  save AP "$ap"; echo "  $ap  (mount root becomes /measure -- pass --key-prefix measure/ to the script)"

  step "measurement host"
  cat > /tmp/rb-ec2-trust.json <<'EOF'
{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}
EOF
  cat > /tmp/rb-host.json <<EOF
{"Version":"2012-10-17","Statement":[
 {"Effect":"Allow","Action":["s3files:ClientMount","s3files:ClientWrite"],
  "Resource":"arn:aws:s3files:${REGION}:${acct}:file-system/${fs}"},
 {"Effect":"Allow","Action":["s3:GetObject","s3:GetObjectVersion","s3:PutObject","s3:DeleteObject",
  "s3:DeleteObjectVersion","s3:AbortMultipartUpload","s3:ListMultipartUploadParts"],
  "Resource":"arn:aws:s3:::${bucket}/*"},
 {"Effect":"Allow","Action":["s3:ListBucket","s3:ListBucketVersions"],"Resource":"arn:aws:s3:::${bucket}"},
 {"Effect":"Allow","Action":["s3files:GetFileSystem","s3files:ListMountTargets",
  "s3files:GetSynchronizationConfiguration"],"Resource":"*"}]}
EOF
  aws iam create-role --role-name "${PREFIX}-host-role" \
    --assume-role-policy-document file:///tmp/rb-ec2-trust.json --tags $tags >/dev/null
  aws iam put-role-policy --role-name "${PREFIX}-host-role" --policy-name client --policy-document file:///tmp/rb-host.json
  aws iam attach-role-policy --role-name "${PREFIX}-host-role" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore
  aws iam create-instance-profile --instance-profile-name "${PREFIX}-host-role" >/dev/null
  aws iam add-role-to-instance-profile --instance-profile-name "${PREFIX}-host-role" --role-name "${PREFIX}-host-role"
  rm -f /tmp/rb-ec2-trust.json /tmp/rb-host.json
  save HOST_ROLE "${PREFIX}-host-role"
  sleep 15
  ami=$(aws ssm get-parameter --region "$REGION" \
    --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 \
    --query Parameter.Value --output text)
  iid=$(aws ec2 run-instances --region "$REGION" --image-id "$ami" --instance-type "$INSTANCE_TYPE" \
    --subnet-id "$SUBNET_ID" --security-group-ids "$host_sg" --associate-public-ip-address \
    --iam-instance-profile "Name=${PREFIX}-host-role" \
    --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
    --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=${HOST_VOLUME_GIB},VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=${PREFIX}-host},{Key=Project,Value=s3-burst-on-ontap-files},{Key=Environment,Value=verify}]" \
    --query 'Instances[0].InstanceId' --output text)
  save IID "$iid"
  aws ec2 wait instance-running --region "$REGION" --instance-ids "$iid"
  until [[ "$(aws ssm describe-instance-information --region "$REGION" \
    --filters "Key=InstanceIds,Values=$iid" --query 'length(InstanceInformationList)' --output text)" == 1 ]]
  do sleep 10; done
  echo "  $iid registered with SSM"
  echo
  echo "state written to $STATE. Next: ./runbook.sh measure"
}

# ----------------------------------------------------------------------------------------- measure
measure() {
  source "$STATE"
  local script
  script=$(mktemp /tmp/rb-measure-XXXX.sh)
  cat > "$script" <<EOF
set -u
# Amazon Linux 2023 ships python3.9 as python3; the measurement script needs 3.12 (datetime.UTC).
# botocore must come from dnf: pip3 install fails on this AMI. Without botocore the mount still
# succeeds but logs "Failed to import botocore" and CloudWatch metrics are unavailable.
dnf install -y -q amazon-efs-utils attr python3.12 python3.12-pip python3-botocore >/dev/null 2>&1
python3.12 -m pip install -q --root-user-action=ignore boto3 >/dev/null 2>&1
mkdir -p /mnt/s3files
mountpoint -q /mnt/s3files || mount -t s3files -o accesspoint=${AP},actimeo=0 ${FS}:/ /mnt/s3files
# Read what actually applied. actimeo expands into four ac* options and the literal string never
# appears, so grepping for "actimeo" reports a false negative on a correct mount.
findmnt -T /mnt/s3files -o FSTYPE,OPTIONS -n
cd /opt/s3files-measure 2>/dev/null || { echo "copy scripts/measure_s3files_visibility.py and measure_visibility.py to /opt/s3files-measure first"; exit 1; }
python3.12 measure_s3files_visibility.py --file-system-id ${FS} --bucket ${BUCKET} \\
  --mount-point /mnt/s3files --key-prefix measure/ --iterations ${ITERATIONS} \\
  --timeout 300 --poll-interval 0.5 --output result.json --csv result.csv
EOF
  echo "run this on ${IID} over SSM (direction 2 alone takes ~60 s per iteration):"
  echo
  cat "$script"
  rm -f "$script"
}

# ----------------------------------------------------------------------------------------- metrics
metrics() {
  source "$STATE"
  echo "namespace AWS/S3/Files, dimension FileSystemId=${FS}"
  echo "billable byte counters (Sum), then the service's own sync lag:"
  for m in DataWriteBytes DataReadBytes MetadataWriteBytes MetadataReadBytes StorageBytes; do
    printf '  %-20s ' "$m"
    aws cloudwatch get-metric-statistics --region "$REGION" --namespace AWS/S3/Files \
      --metric-name "$m" --dimensions Name=FileSystemId,Value="$FS" \
      --start-time "$(date -u -v-2H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
      --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 3600 --statistics Sum Maximum \
      --query 'Datapoints[].[Sum,Maximum]' --output text | tr '\n' ' '
    echo
  done
  for m in ImportAge ExportAge PendingExports LostAndFoundFiles; do
    printf '  %-20s ' "$m"
    aws cloudwatch get-metric-statistics --region "$REGION" --namespace AWS/S3/Files \
      --metric-name "$m" --dimensions Name=FileSystemId,Value="$FS" \
      --start-time "$(date -u -v-2H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)" \
      --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 300 --statistics Maximum \
      --query 'max(Datapoints[].Maximum)' --output text
  done
  echo
  echo "price: read \$0.04/GB, write \$0.07/GB, high-performance storage \$0.36/GB-Mo (ap-northeast-1, 2026-08-01)"
}

# ----------------------------------------------------------------------------------------- destroy
gone() {
  # $1 = the get- subcommand, $2 = the flag, $3 = the id. Polls until the resource stops resolving.
  local label="$4"
  for _ in $(seq 1 40); do
    aws s3files "$1" --region "$REGION" "$2" "$3" >/dev/null 2>&1 || { echo "  $label gone"; return 0; }
    sleep 15
  done
  echo "  WARNING: $label still present after 10 minutes" >&2
  return 1
}

destroy() {
  [[ -f "$STATE" ]] || die "no $STATE"
  source "$STATE"
  # Order is not interchangeable, and four separate constraints enforce it. Three were expected; the
  # fourth was found by running this and having it report a resource left behind:
  #
  #   1. Versioning is a prerequisite of S3 Files, so the bucket holds a version chain and a delete
  #      marker for every object written. `aws s3 rm` removes current versions only.
  #   2. The access point and mount target must go before the file system.
  #   3. The bucket cannot be deleted while a file system is attached to it:
  #      BucketHasS3FileSystemAttached. So the file system goes first, not the bucket.
  #   4. `delete-file-system` refuses with ConflictException while there is data pending export,
  #      and this is NOT reliably visible in the PendingExports metric -- measured 2026-09-01, the
  #      metric read 0 while the delete was still refused. Waiting is the polite answer;
  #      --force-delete is the one that finishes, and it discards data not yet exported.
  #
  # Deletions here are waited on rather than slept through. The first version used fixed sleeps and
  # suppressed errors, which left a file system and a bucket behind while every step looked fine.
  # Only the closing count caught it, which is the argument for having the count.
  step "host"
  if [[ -n "${IID:-}" ]]; then
    aws ec2 terminate-instances --region "$REGION" --instance-ids "$IID" >/dev/null \
      && aws ec2 wait instance-terminated --region "$REGION" --instance-ids "$IID" \
      && echo "  terminated"
  fi
  step "access point"
  if [[ -n "${AP:-}" ]]; then
    aws s3files delete-access-point --region "$REGION" --access-point-id "$AP" || true
    gone get-access-point --access-point-id "$AP" "access point" || true
  fi
  step "mount target"
  if [[ -n "${MT:-}" ]]; then
    aws s3files delete-mount-target --region "$REGION" --mount-target-id "$MT" || true
    gone get-mount-target --mount-target-id "$MT" "mount target" || true
  fi
  step "file system (retrying while exports drain, then forcing)"
  if [[ -n "${FS:-}" ]]; then
    local deleted=no
    for _ in $(seq 1 8); do
      if aws s3files delete-file-system --region "$REGION" --file-system-id "$FS" 2>/tmp/rb-fs-err; then
        deleted=yes; break
      fi
      grep -q ConflictException /tmp/rb-fs-err \
        && echo "  data still pending export; waiting 30 s" \
        || { cat /tmp/rb-fs-err >&2; break; }
      sleep 30
    done
    if [[ "$deleted" == no ]]; then
      echo "  still refusing after the retries; forcing (discards data not yet exported)"
      aws s3files delete-file-system --region "$REGION" --file-system-id "$FS" --force-delete
    fi
    rm -f /tmp/rb-fs-err
    gone get-file-system --file-system-id "$FS" "file system" || true
  fi
  step "bucket: every version and delete marker, then the bucket"
  python3 - "$BUCKET" "$REGION" <<'PY'
import sys, boto3
bucket, region = sys.argv[1], sys.argv[2]
s3 = boto3.client("s3", region_name=region)
n = 0
for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket):
    items = [{"Key": i["Key"], "VersionId": i["VersionId"]}
             for g in ("Versions", "DeleteMarkers") for i in page.get(g, [])]
    for i in range(0, len(items), 1000):
        s3.delete_objects(Bucket=bucket, Delete={"Objects": items[i:i+1000]})
        n += len(items[i:i+1000])
print(f"  removed {n}")
PY
  # Not suppressed: BucketHasS3FileSystemAttached here means the file system above did not go, and
  # a silent failure is what let an earlier run report success with both still standing.
  aws s3api delete-bucket --region "$REGION" --bucket "$BUCKET" && echo "  bucket deleted"
  step "security groups"
  for sg in "${MT_SG:-}" "${HOST_SG:-}"; do
    for _ in $(seq 1 12); do
      aws ec2 delete-security-group --region "$REGION" --group-id "$sg" 2>/dev/null && break
      sleep 10   # the ENIs take a moment to release
    done
  done
  step "IAM"
  aws iam delete-role-policy --role-name "${SYNC_ROLE:-}" --policy-name sync 2>/dev/null
  aws iam delete-role --role-name "${SYNC_ROLE:-}" 2>/dev/null
  aws iam remove-role-from-instance-profile --instance-profile-name "${HOST_ROLE:-}" --role-name "${HOST_ROLE:-}" 2>/dev/null
  aws iam delete-instance-profile --instance-profile-name "${HOST_ROLE:-}" 2>/dev/null
  aws iam delete-role-policy --role-name "${HOST_ROLE:-}" --policy-name client 2>/dev/null
  aws iam detach-role-policy --role-name "${HOST_ROLE:-}" \
    --policy-arn arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore 2>/dev/null
  aws iam delete-role --role-name "${HOST_ROLE:-}" 2>/dev/null
  step "confirm by counting, not by trusting the exit statuses above"
  printf '  file systems left: %s\n' "$(aws s3files list-file-systems --region "$REGION" --query 'length(fileSystems)' --output text)"
  printf '  bucket left:       %s\n' "$(aws s3api list-buckets --query "length(Buckets[?Name=='${BUCKET}'])" --output text)"
  printf '  security groups:   %s\n' "$(aws ec2 describe-security-groups --region "$REGION" --filters "Name=group-name,Values=${PREFIX}-*" --query 'length(SecurityGroups)' --output text)"
  printf '  IAM roles:         %s\n' "$(aws iam list-roles --query "length(Roles[?starts_with(RoleName,'${PREFIX}')])" --output text)"
  mv "$STATE" "${STATE}.destroyed"
}

case "${1:-}" in
  create) create ;;
  measure) measure ;;
  metrics) metrics ;;
  destroy) destroy ;;
  *) die "usage: $0 {create|measure|metrics|destroy}" ;;
esac
