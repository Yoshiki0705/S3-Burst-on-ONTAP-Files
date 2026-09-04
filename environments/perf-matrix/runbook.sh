#!/usr/bin/env bash
# =================================================================================================
# The protocol-matrix measurement, in the order the steps have to happen.
#
# Not a one-shot script. Each phase is a subcommand, because two of them are gates that a human has
# to read the output of before the next one is worth running:
#
#   - `preflight` refuses to go further if a documented-unsupported case is in the plan, or if the
#     NVMe read cache is still enabled on the file system whose disk path is about to be measured.
#   - `costs` prints what is currently running and what it bills per hour. Run it between phases.
#
# The order matters in one specific way: **the NVMe read cache has to be off before the disk-path
# read, and turning it off is an ONTAP CLI operation, not an AWS one.** A read taken with it on is
# served from cache and the SSD IOPS setting has no effect on the number, which is the single mistake
# that cost the most re-measurement last time.
#
# Nothing here creates a resource that cannot be deleted. No SnapLock, no retention, no Object Lock.
# =================================================================================================
set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
PREFIX="${NAME_PREFIX:-perfmatrix}"
STACK_CLIENTS="${PREFIX}-clients"
STACK_EFS="${PREFIX}-efs"
STACK_GEN2="${PREFIX}-gen2"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\n=== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "$1 is not on PATH"; }
require aws
require python3

# --- phases --------------------------------------------------------------------------------------

deploy_clients() {
  [[ -n "${VPC_ID:-}" && -n "${SUBNET_ID:-}" ]] || die "set VPC_ID and SUBNET_ID"
  log "clients: $STACK_CLIENTS"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_CLIENTS" \
    --template-file "$HERE/template-clients.yaml" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset
  CLIENT_SG="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  printf 'ClientSecurityGroupId=%s\n' "$CLIENT_SG"
}

deploy_efs() {
  local sg; sg="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  # Provisioned at the ap-northeast-1 maximum. This is the most expensive line in the whole
  # measurement at about $30.30/hour, and it bills from CREATE_COMPLETE, not from first mount.
  log "EFS: $STACK_EFS (provisioned 3072 MiBps, about \$30.30/hour from now)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_EFS" \
    --template-file "$HERE/template-efs.yaml" \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ClientSecurityGroupId=$sg" \
      "ThroughputMode=provisioned" "ProvisionedThroughputInMibps=3072" "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset
}

deploy_gen2() {
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die "set FSXADMIN_SECRET_ARN to a Secrets Manager secret with a 'password' key"
  local sg; sg="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  # The template takes bytes and CloudFormation cannot multiply, so the conversion happens here.
  # 900 GiB holds more than twice the 256 GB in-memory cache, which is what the read has to exceed.
  local vol_gib="${VOLUME_SIZE_GIB:-900}"
  local vol_bytes=$(( vol_gib * 1024 * 1024 * 1024 ))
  log "gen2 FSx for ONTAP: $STACK_GEN2 (6144 MBps, ${vol_gib} GiB volume, about \$22.66/hour from now)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_GEN2" \
    --template-file "$HERE/template-fsxn-gen2.yaml" \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ClientSecurityGroupId=$sg" \
      "ThroughputCapacityPerHAPair=6144" "ProvisionedSsdIops=200000" \
      "VolumeSizeBytes=$vol_bytes" \
      "FsxAdminPasswordSecretArn=$FSXADMIN_SECRET_ARN" "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset
}

# Raises the existing first-generation file system to its ap-northeast-1 maximum. Separate from the
# stacks because that file system is not managed by this directory, and a template that adopted it
# could delete it.
raise_gen1() {
  [[ -n "${GEN1_FS_ID:-}" ]] || die "set GEN1_FS_ID"
  log "gen1 $GEN1_FS_ID -> 2048 MBps, USER_PROVISIONED 80000 IOPS"
  printf 'This change took 24 minutes to apply when measured. Continue? [y/N] '
  read -r reply; [[ "$reply" == "y" ]] || die "aborted"
  aws fsx update-file-system --region "$REGION" --file-system-id "$GEN1_FS_ID" \
    --ontap-configuration 'ThroughputCapacity=2048,DiskIopsConfiguration={Mode=USER_PROVISIONED,Iops=80000}'
}

# The gate that matters. A disk-path read taken with the NVMe cache enabled is a cache measurement.
preflight() {
  log "preflight"
  python3 "$HERE/../../scripts/protocol_matrix_harness.py" --dry-run

  log "NVMe read cache state (must be disabled before the disk-path read)"
  cat <<'NOTE'
This cannot be read or changed through the AWS API. Over the ONTAP CLI:

    system node external-cache show
    system node external-cache modify -node * -is-enabled false
    system node external-cache show          # confirm both nodes report false

Judge by the second show, not by the modify returning without error.

With the cache off, a read only has to exceed the in-memory cache: 256 GB at 2048 MBps and at
6144 MBps. Read at least 512 GB in one pass.
NOTE
  printf 'Confirmed the NVMe read cache is disabled on every target being measured? [y/N] '
  read -r reply; [[ "$reply" == "y" ]] || die "stopping: measure the cache off, or record that it was on"
}

# What is billing right now, so the answer is never "I thought it was stopped".
# shellcheck disable=SC2016  # the backticks are JMESPath, not command substitution
costs() {
  log "running resources that bill by the hour"
  aws fsx describe-file-systems --region "$REGION" \
    --query 'FileSystems[?Lifecycle==`AVAILABLE`].{Id:FileSystemId,Depl:OntapConfiguration.DeploymentType,MBps:OntapConfiguration.ThroughputCapacity,Iops:OntapConfiguration.DiskIopsConfiguration.Iops,SSD:StorageCapacity}' \
    --output table
  aws efs describe-file-systems --region "$REGION" \
    --query 'FileSystems[].{Id:FileSystemId,Mode:ThroughputMode,Mibps:ProvisionedThroughputInMibps,SizeBytes:SizeInBytes.Value}' \
    --output table
  aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:DeleteAfterMeasurement,Values=true" "Name=instance-state-name,Values=running" \
    --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,Name:Tags[?Key==`Name`]|[0].Value}' \
    --output table
  cat <<'NOTE'
Hourly, at ap-northeast-1 On-Demand prices read on 2026-09-04:
  EFS provisioned 3072 MiBps   $30.30
  gen2 6144 MBps + 200k IOPS   $22.66
  gen1 2048 MBps + 80k IOPS    $ 4.90 each
  c5n.9xlarge                  $ 2.45
  c5n.2xlarge                  $ 0.54 each
EFS Elastic is not on this list because it bills per GB accessed, not per hour.
NOTE
}

stack_output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

usage() {
  cat <<'USAGE'
Usage: runbook.sh <phase>

  clients      Create the measurement clients and the shared security group
  efs          Create the EFS target (provisioned 3072 MiBps, about $30.30/hour)
  gen2         Create the second-generation FSx for ONTAP target (about $22.66/hour)
  raise-gen1   Raise the existing first-generation file system to 2048 MBps (prompts; takes ~24 min)
  preflight    Print the support matrix and gate on the NVMe read cache being disabled
  costs        Show what is billing by the hour right now
  teardown     Hand off to teardown.sh

Environment: VPC_ID, SUBNET_ID, GEN1_FS_ID, FSXADMIN_SECRET_ARN, NAME_PREFIX, AWS_REGION
USAGE
}

case "${1:-}" in
  clients)    deploy_clients ;;
  efs)        deploy_efs ;;
  gen2)       deploy_gen2 ;;
  raise-gen1) raise_gen1 ;;
  preflight)  preflight ;;
  costs)      costs ;;
  teardown)   exec "$HERE/teardown.sh" ;;
  *)          usage; exit 1 ;;
esac
