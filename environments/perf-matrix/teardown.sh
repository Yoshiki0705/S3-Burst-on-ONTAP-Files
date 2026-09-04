#!/usr/bin/env bash
# =================================================================================================
# Delete everything this directory created, and put the pre-existing file system back.
#
# The order is not arbitrary. The two most expensive resources go first, before anything that could
# fail and leave them running: at $30.30 and $22.66 an hour, a teardown that stops halfway through
# because a client would not terminate is a teardown that costs money for the rest of the day.
#
# It also verifies rather than trusts. A delete call returning without error is not evidence the
# resource is gone -- the check at the end reads the state back, and exits non-zero if anything
# tagged for deletion is still there. That is the difference between "I ran teardown" and "it is
# deleted".
#
# The first-generation file system is **not** deleted. It predates this directory and holds the other
# measurements; it is only stepped back down to 128 MBps, which is where its cost goes from $4.90 to
# $0.37 an hour.
# =================================================================================================
set -uo pipefail   # not -e: a failure on one resource must not skip the ones after it

REGION="${AWS_REGION:-ap-northeast-1}"
PREFIX="${NAME_PREFIX:-perfmatrix}"
FAILED=0

log()  { printf '\n=== %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; FAILED=1; }

delete_stack() {
  local name="$1"
  if ! aws cloudformation describe-stacks --region "$REGION" --stack-name "$name" >/dev/null 2>&1; then
    printf 'not present: %s\n' "$name"; return 0
  fi
  log "deleting stack $name"
  aws cloudformation delete-stack --region "$REGION" --stack-name "$name" \
    || { warn "delete-stack failed for $name"; return 1; }
  aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$name" \
    || warn "stack $name did not reach DELETE_COMPLETE; check its events"
}

# Most expensive first. EFS provisioned throughput bills from creation, not from first mount.
log "step 1 of 4: the two hourly-billed targets"
delete_stack "${PREFIX}-efs"
delete_stack "${PREFIX}-gen2"

log "step 2 of 4: clients"
delete_stack "${PREFIX}-clients"

log "step 3 of 4: step the pre-existing first-generation file system back down"
if [[ -n "${GEN1_FS_ID:-}" ]]; then
  # Not deleted: it predates this directory. Stepping the throughput capacity down is what stops the
  # bulk of its cost. SSD capacity cannot be reduced, so that part stays either way.
  # if/else rather than `A && B || C`: with the chained form, a failing printf would run warn and
  # report a step-down that actually succeeded as a failure.
  if aws fsx update-file-system --region "$REGION" --file-system-id "$GEN1_FS_ID" \
       --ontap-configuration 'ThroughputCapacity=128,DiskIopsConfiguration={Mode=AUTOMATIC}'; then
    printf 'requested 128 MBps and AUTOMATIC IOPS on %s\n' "$GEN1_FS_ID"
  else
    warn "could not step $GEN1_FS_ID down; it is still billing at the raised rate"
  fi
  printf 'This change takes time to apply. Confirm with the check below, not with this call.\n'
else
  printf 'GEN1_FS_ID not set; skipping the step-down. If it was raised, it is still billing.\n'
fi

# The part that makes this a teardown rather than a delete attempt.
log "step 4 of 4: verify"
left_fsx="$(aws fsx describe-file-systems --region "$REGION" \
  --query "FileSystems[?Tags[?Key=='DeleteAfterMeasurement' && Value=='true']].FileSystemId" \
  --output text 2>/dev/null)"
left_efs="$(aws efs describe-file-systems --region "$REGION" \
  --query 'FileSystems[].FileSystemId' --output text 2>/dev/null)"
left_ec2="$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:DeleteAfterMeasurement,Values=true" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null)"

[[ -n "$left_fsx" ]] && warn "FSx for ONTAP still tagged for deletion: $left_fsx"
[[ -n "$left_ec2" ]] && warn "EC2 still tagged for deletion: $left_ec2"
if [[ -n "$left_efs" ]]; then
  # EFS file systems are listed without a tag filter on purpose: this account had none before this
  # measurement, so anything here is either ours or something that appeared meanwhile. Either way it
  # bills, so it gets named rather than filtered away.
  warn "EFS file systems present (this account had none before the measurement): $left_efs"
fi

gen1_state="$(aws fsx describe-file-systems --region "$REGION" \
  --query "FileSystems[?FileSystemId=='${GEN1_FS_ID:-none}'].OntapConfiguration.ThroughputCapacity" \
  --output text 2>/dev/null)"
[[ -n "$gen1_state" ]] && printf 'first-generation throughput capacity now reads: %s MBps\n' "$gen1_state"

if [[ "$FAILED" -eq 0 ]]; then
  log "teardown verified: nothing tagged for deletion remains"
else
  log "teardown INCOMPLETE. The lines above are still billing. Do not treat this run as done."
  exit 1
fi
