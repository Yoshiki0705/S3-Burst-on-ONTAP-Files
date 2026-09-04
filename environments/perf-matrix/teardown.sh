#!/usr/bin/env bash
# =================================================================================================
# Delete everything this directory created, and put the pre-existing file system back.
#
# The order is not arbitrary, and two different constraints set it.
#
# **Cost first.** The two most expensive resources go before anything that could fail and leave them
# running: at $30.30 and $22.78 an hour, a teardown that stops halfway because a client would not
# terminate is a teardown that costs money for the rest of the day.
#
# **Dependencies second, and they cut the other way from cost.** The SMB SVM lives on the
# second-generation file system, so it goes before that file system or the file system will not delete.
# It is also joined to the directory, and so is the Windows client -- deleting an AD-joined resource
# after its directory is gone leaves FSx for ONTAP trying to remove a computer object from a domain
# that no longer answers. So the directory goes last of the created things, not first.
#
# **And one rule has to be revoked before anything can be deleted at all.** `runbook.sh ad-ports` adds
# rules to the directory's security group that reference the client group and the file system group.
# EC2 refuses to delete a security group while another group's rule names it, so those two stacks
# cannot be deleted until the references are gone. That is step 4, and it sits after the SMB SVM so
# that the SVM still has a reachable controller while it is being removed.
#
# It also verifies rather than trusts. A delete call returning without error is not evidence the
# resource is gone -- the check at the end reads the state back, and exits non-zero if anything tagged
# for deletion is still there. That is the difference between "I ran teardown" and "it is deleted".
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
log "step 1 of 7: the hourly-billed storage targets"
delete_stack "${PREFIX}-efs-prov"
delete_stack "${PREFIX}-efs"

# The SMB SVM goes while it can still reach a controller: FSx removes a computer object from the
# domain as part of deleting an AD-joined SVM.
log "step 2 of 7: the SMB SVM, while the directory still answers"
delete_stack "${PREFIX}-smb-svm"

# Domain-joined, but leaving the domain is not a precondition for terminating an instance.
log "step 3 of 7: the Windows client"
delete_stack "${PREFIX}-windows"

# **This step is why the two below can be deleted at all.** `runbook.sh ad-ports` added rules to the
# directory's own security group that *reference* the client group and the file system group, and EC2
# refuses to delete a security group while another group's rule still names it. Without this, the two
# stack deletions below fail on their security groups and the whole teardown stops with the file system
# still billing.
log "step 4 of 7: revoke the directory rules that reference the groups about to be deleted"
if aws cloudformation describe-stacks --region "$REGION" --stack-name "${PREFIX}-ad" >/dev/null 2>&1; then
  dir_id="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "${PREFIX}-ad" \
    --query "Stacks[0].Outputs[?OutputKey=='DirectoryId'].OutputValue" --output text 2>/dev/null)"
  sg_ad="$(aws ds describe-directories --region "$REGION" --directory-ids "$dir_id" \
    --query 'DirectoryDescriptions[0].VpcSettings.SecurityGroupId' --output text 2>/dev/null)"
  if [[ -n "$sg_ad" && "$sg_ad" != "None" ]]; then
    for stack_key in "${PREFIX}-clients:ClientSecurityGroupId" "${PREFIX}-gen2:FileSystemSecurityGroupId"; do
      src="$(aws cloudformation describe-stacks --region "$REGION" --stack-name "${stack_key%%:*}" \
        --query "Stacks[0].Outputs[?OutputKey=='${stack_key##*:}'].OutputValue" --output text 2>/dev/null)"
      [[ -n "$src" && "$src" != "None" ]] || continue
      if aws ec2 revoke-security-group-ingress --region "$REGION" --group-id "$sg_ad" \
           --ip-permissions "IpProtocol=-1,UserIdGroupPairs=[{GroupId=$src}]" >/dev/null 2>&1; then
        printf 'revoked: %s -> %s\n' "$src" "$sg_ad"
      else
        printf 'nothing to revoke (or already gone): %s -> %s\n' "$src" "$sg_ad"
      fi
    done
  else
    warn "could not read the directory security group; if the two deletions below fail on a security group, this is why"
  fi
else
  printf 'no directory stack; nothing to revoke\n'
fi

log "step 5 of 7: the file system, then the clients"
delete_stack "${PREFIX}-gen2"
delete_stack "${PREFIX}-clients"

# Last of the created things, for the reason in the header.
log "step 6 of 8: the directory"
delete_stack "${PREFIX}-ad"

# Not a stack: created by hand because the clients have no route to PyPI or GitHub and the tooling had
# to arrive over S3. It holds VDBENCH, which is licensed, so it does not get left behind.
log "step 7 of 8: the staging bucket"
if [[ -n "${STAGING_BUCKET:-}" ]]; then
  if aws s3api head-bucket --bucket "$STAGING_BUCKET" >/dev/null 2>&1; then
    aws s3 rm "s3://$STAGING_BUCKET" --recursive --only-show-errors \
      || warn "could not empty s3://$STAGING_BUCKET"
    aws s3api delete-bucket --bucket "$STAGING_BUCKET" --region "$REGION" \
      || warn "could not delete s3://$STAGING_BUCKET"
  else
    printf 'not present: s3://%s\n' "$STAGING_BUCKET"
  fi
else
  printf 'STAGING_BUCKET not set; skipping. If a staging bucket was created, it still holds VDBENCH.\n'
fi

log "step 8 of 8: step the pre-existing first-generation file system back down"
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
log "verify"
left_fsx="$(aws fsx describe-file-systems --region "$REGION" \
  --query "FileSystems[?Tags[?Key=='DeleteAfterMeasurement' && Value=='true']].FileSystemId" \
  --output text 2>/dev/null)"
left_svm="$(aws fsx describe-storage-virtual-machines --region "$REGION" \
  --query "StorageVirtualMachines[?Tags[?Key=='DeleteAfterMeasurement' && Value=='true']].StorageVirtualMachineId" \
  --output text 2>/dev/null)"
left_efs="$(aws efs describe-file-systems --region "$REGION" \
  --query 'FileSystems[].FileSystemId' --output text 2>/dev/null)"
left_ec2="$(aws ec2 describe-instances --region "$REGION" \
  --filters "Name=tag:DeleteAfterMeasurement,Values=true" \
            "Name=instance-state-name,Values=pending,running,stopping,stopped" \
  --query 'Reservations[].Instances[].InstanceId' --output text 2>/dev/null)"
# Managed AD carries no tags -- AWS::DirectoryService::MicrosoftAD has no Tags property -- so this one
# cannot be filtered the way the others are. Every directory in the Region is listed instead, and
# reading it is the job: this account had none before the measurement.
left_ad="$(aws ds describe-directories --region "$REGION" \
  --query 'DirectoryDescriptions[].DirectoryId' --output text 2>/dev/null)"

[[ -n "$left_fsx" ]] && warn "FSx for ONTAP still tagged for deletion: $left_fsx"
[[ -n "$left_svm" ]] && warn "storage virtual machines still tagged for deletion: $left_svm"
[[ -n "$left_ec2" ]] && warn "EC2 still tagged for deletion: $left_ec2"
if [[ -n "$left_efs" ]]; then
  # EFS file systems are listed without a tag filter on purpose: this account had none before this
  # measurement, so anything here is either ours or something that appeared meanwhile. Either way it
  # bills, so it gets named rather than filtered away.
  warn "EFS file systems present (this account had none before the measurement): $left_efs"
fi
[[ -n "$left_ad" ]] && warn "directories present (this account had none before the measurement): $left_ad"

if [[ -n "${STAGING_BUCKET:-}" ]] && aws s3api head-bucket --bucket "$STAGING_BUCKET" >/dev/null 2>&1; then
  warn "staging bucket still present: s3://$STAGING_BUCKET (it holds licensed VDBENCH)"
fi

gen1_state="$(aws fsx describe-file-systems --region "$REGION" \
  --query "FileSystems[?FileSystemId=='${GEN1_FS_ID:-none}'].OntapConfiguration.ThroughputCapacity" \
  --output text 2>/dev/null)"
[[ -n "$gen1_state" ]] && printf 'first-generation throughput capacity now reads: %s MBps\n' "$gen1_state"

if [[ "$FAILED" -eq 0 ]]; then
  log "teardown verified: nothing tagged for deletion remains"
  # Not a cost, but it is state this measurement created and it outlives the stacks.
  printf 'Note: computer objects for the SVM and the Windows client are gone with the directory.\n'
  printf 'If the directory was kept, remove them there before reusing their NetBIOS names.\n'
else
  log "teardown INCOMPLETE. The lines above are still billing. Do not treat this run as done."
  exit 1
fi
