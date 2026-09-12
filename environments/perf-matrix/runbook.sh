#!/usr/bin/env bash
# =================================================================================================
# The protocol-matrix measurement, in the order the steps have to happen.
#
# Not a one-shot script. Each phase is a subcommand, because several of them are gates that a human
# has to read the output of before the next one is worth running:
#
#   - `preflight` refuses to go further if a documented-unsupported case is in the plan, or if the
#     NVMe read cache is still enabled on the file system whose disk path is about to be measured.
#   - `windows-status` reads whether the Windows client actually joined the domain. A CREATE_COMPLETE
#     stack means the association exists, not that the join happened.
#   - `costs` prints what is currently running and what it bills per hour. Run it between phases.
#
# The order matters in three specific ways:
#
#   1. **The NVMe read cache has to be off before the disk-path read**, and turning it off is an ONTAP
#      CLI operation, not an AWS one. A read taken with it on is served from cache and the SSD IOPS
#      setting has no effect on the number -- the single mistake that cost the most re-measurement.
#   2. **The directory comes before the storage targets.** It takes 15 to 30 minutes to create. Doing
#      it after would spend that wait with $53/hour of EFS and FSx for ONTAP sitting idle.
#   3. **EFS Provisioned comes last and leaves first.** At about $9/hour (1,024 MiBps, the account limit) it is still an unstoppable line
#      here, it bills from CREATE_COMPLETE rather than from first mount, and it is wanted for exactly
#      one pattern. It gets its own stack so that `drop-efs-provisioned` can remove it the moment that
#      pattern is done, without touching anything else.
#
# Nothing here creates a resource that cannot be deleted. No SnapLock, no retention, no Object Lock.
#
# One operational note. `ad` and `gen2` run for 15 to 40 minutes, and bash reads a script
# incrementally rather than all at once -- so editing this file while one of those is in flight
# corrupts the running invocation's parse and it dies with a syntax error at a line that is fine on
# disk. The deploy itself survives, because the failure lands after the wait returns, but the exit
# status is a lie. If a long phase is running and this file needs editing, run the phase from a copy.
# =================================================================================================
set -euo pipefail

PY_BIN="${PY_BIN:-python3}"
REGION="${AWS_REGION:-ap-northeast-1}"
PREFIX="${NAME_PREFIX:-perfmatrix}"
STACK_CLIENTS="${PREFIX}-clients"
STACK_EFS="${PREFIX}-efs"
STACK_EFS_PROV="${PREFIX}-efs-prov"
STACK_GEN2="${PREFIX}-gen2"
STACK_AD="${PREFIX}-ad"
STACK_WINDOWS="${PREFIX}-windows"
STACK_SMB_SVM="${PREFIX}-smb-svm"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

log() { printf '\n=== %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

require() { command -v "$1" >/dev/null 2>&1 || die "$1 is not on PATH"; }
require aws
require python3

stack_output() {
  aws cloudformation describe-stacks --region "$REGION" --stack-name "$1" \
    --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text
}

# --- clients -------------------------------------------------------------------------------------

deploy_clients() {
  # cheap to create, but pointless without the instrument. `tooling` reads the bucket rather than the variable, and dies on a gap.
  tooling

  [[ -n "${VPC_ID:-}" && -n "${SUBNET_ID:-}" ]] || die "set VPC_ID and SUBNET_ID"
  log "clients: $STACK_CLIENTS"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_CLIENTS" \
    --template-file "$HERE/template-clients.yaml" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "NamePrefix=$PREFIX" \
      "StagingBucketName=${STAGING_BUCKET:-}" "FsxAdminSecretArn=${FSXADMIN_SECRET_ARN:-}" \
    --no-fail-on-empty-changeset
  printf 'ClientSecurityGroupId=%s\n' "$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  [[ -n "${STAGING_BUCKET:-}" ]] \
    || printf 'STAGING_BUCKET not set: the clients have no S3 read access, and this subnet has no path to PyPI or GitHub.\n'
}

# --- directory -----------------------------------------------------------------------------------

# First, because it is the slowest thing here and the only one whose wait costs nothing.
deploy_ad() {
  [[ -n "${VPC_ID:-}" ]] || die "set VPC_ID"
  [[ -n "${SUBNET_ID:-}" && -n "${SUBNET_ID_2:-}" ]] \
    || die "set SUBNET_ID and SUBNET_ID_2: Managed AD requires two subnets in two Availability Zones"
  [[ "$SUBNET_ID" != "$SUBNET_ID_2" ]] || die "SUBNET_ID_2 must be a different subnet, in a different AZ"
  [[ -n "${AD_SECRET_ARN:-}" ]] || die "set AD_SECRET_ARN to a Secrets Manager secret with a 'password' key"
  log "Managed AD: $STACK_AD (about \$0.146/hour; 15-30 minutes to create)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_AD" \
    --template-file "$HERE/template-ad.yaml" \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetIds=$SUBNET_ID,$SUBNET_ID_2" \
      "AdDomainName=${AD_DOMAIN_NAME:-perfmatrix.local}" \
      "AdShortName=${AD_SHORT_NAME:-PERFMATRIX}" \
      "AdAdminPasswordSecretArn=$AD_SECRET_ARN" \
    --no-fail-on-empty-changeset
  printf 'DirectoryId=%s\n' "$(stack_output "$STACK_AD" DirectoryId)"
  printf 'DnsIpAddresses=%s\n' "$(stack_output "$STACK_AD" DirectoryDnsIpAddresses)"
}

# Whether the directory's own security group already admits the clients and the SVM interfaces is
# something to read rather than assume. This reads it and adds what is missing.
# **Read-only by default, and usually a no-op.** Managed AD creates a security group that already
# admits the whole VPC CIDR on every AD port -- verified on a real directory: 53, 88, 123, 135, 138,
# 389, 445, 464, 636, 3268-3269, tcp 1024-65535 and icmp, all from the VPC CIDR. So when the clients
# and the SVM interfaces are inside the directory's VPC, as they are here, nothing needs adding.
#
# Adding security-group-identity rules on top is not free: a group named by another group's rule cannot
# be deleted, so each one becomes something teardown has to revoke first, in the right order. Set
# AD_PORTS_ADD=1 only when the read below shows the traffic is genuinely not admitted.
ad_ports() {
  local dir_id sg_ad sg_clients sg_fs
  dir_id="$(stack_output "$STACK_AD" DirectoryId)"
  [[ -n "$dir_id" && "$dir_id" != "None" ]] || die "no DirectoryId; run './runbook.sh ad' first"
  sg_ad="$(aws ds describe-directories --region "$REGION" --directory-ids "$dir_id" \
    --query 'DirectoryDescriptions[0].VpcSettings.SecurityGroupId' --output text)"
  [[ -n "$sg_ad" && "$sg_ad" != "None" ]] || die "could not read the directory's security group"
  sg_clients="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  sg_fs="$(stack_output "$STACK_GEN2" FileSystemSecurityGroupId)"
  # Both are required rather than optional. Skipping a missing one quietly would leave the SVM
  # interfaces unable to reach a controller, and `join-svm` would then fail in a way that reads as a
  # permissions problem rather than a missing rule.
  [[ -n "$sg_clients" && "$sg_clients" != "None" ]] || die "no client security group; run './runbook.sh clients' first"
  [[ -n "$sg_fs" && "$sg_fs" != "None" ]] || die "no file system security group; run './runbook.sh gen2' first"

  local vpc_cidr
  vpc_cidr="$(aws ec2 describe-vpcs --region "$REGION" --vpc-ids "$VPC_ID" \
    --query 'Vpcs[0].CidrBlock' --output text)"

  log "directory security group $sg_ad: inbound rules"
  aws ec2 describe-security-group-rules --region "$REGION" --filters "Name=group-id,Values=$sg_ad" \
    --query 'SecurityGroupRules[?!IsEgress].{Proto:IpProtocol,From:FromPort,To:ToPort,Cidr:CidrIpv4,Group:ReferencedGroupInfo.GroupId}' \
    --output table

  # Kerberos, LDAP and SMB. If the VPC CIDR is admitted on these three, everything in the VPC can
  # reach a controller and there is nothing to add.
  local port covered=1
  for port in 88 389 445; do
    if [[ -z "$(aws ec2 describe-security-group-rules --region "$REGION" \
                  --filters "Name=group-id,Values=$sg_ad" \
                  --query "SecurityGroupRules[?!IsEgress && CidrIpv4=='$vpc_cidr' && FromPort<=\`$port\` && ToPort>=\`$port\`].SecurityGroupRuleId" \
                  --output text)" ]]; then
      printf 'port %s is NOT admitted from %s\n' "$port" "$vpc_cidr"
      covered=0
    fi
  done

  if (( covered )); then
    log "the VPC CIDR $vpc_cidr is admitted on 88, 389 and 445"
    printf 'Everything in this VPC can already reach a controller. Nothing to add.\n'
    printf 'clients: %s\nSVM interfaces: %s\n' "$sg_clients" "$sg_fs"
    [[ -n "${AD_PORTS_ADD:-}" ]] || return 0
    printf 'AD_PORTS_ADD is set, so adding the group rules anyway.\n'
  fi

  if [[ -z "${AD_PORTS_ADD:-}" ]]; then
    die "some AD ports are not admitted. Review the table above, then re-run with AD_PORTS_ADD=1"
  fi

  # All protocols from these two groups only. The AD port set spans TCP and UDP from 53 through the
  # dynamic RPC range; writing it out per port would not narrow *who* can reach the controllers, which
  # is what actually restricts this.
  local src
  for src in "$sg_clients" "$sg_fs"; do
    if aws ec2 authorize-security-group-ingress --region "$REGION" --group-id "$sg_ad" \
         --ip-permissions "IpProtocol=-1,UserIdGroupPairs=[{GroupId=$src,Description=\"perfmatrix: AD ports from the measurement clients and the SVM interfaces\"}]" \
         >/dev/null 2>&1; then
      printf 'added: %s -> %s\n' "$src" "$sg_ad"
    else
      printf 'not added (already present, or refused): %s -> %s\n' "$src" "$sg_ad"
    fi
  done

  log "verify: re-read"
  aws ec2 describe-security-group-rules --region "$REGION" --filters "Name=group-id,Values=$sg_ad" \
    --query 'SecurityGroupRules[?!IsEgress].ReferencedGroupInfo.GroupId' --output text
}

# --- storage targets -----------------------------------------------------------------------------

# EFS twice over, because the two modes answer different questions and only one of them is affordable
# to leave running. Elastic has the higher ceiling in ap-northeast-1 (60 GiBps read against 3 GiBps)
# and bills per GB accessed; Provisioned is the reserved-rate mode, which is what compares like for
# like against an FSx for ONTAP throughput capacity setting, and costs about $9/hour to hold at 1,024 MiBps.
deploy_efs() {
  local mode="${1:-elastic}"
  local stack params
  [[ -n "${VPC_ID:-}" && -n "${SUBNET_ID:-}" ]] || die "set VPC_ID and SUBNET_ID"
  local sg; sg="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  case "$mode" in
    elastic)
      stack="$STACK_EFS"
      params=("ThroughputMode=elastic")
      log "EFS elastic: $stack (no hourly throughput charge; \$0.07 per GB accessed)"
      ;;
    provisioned)
      stack="$STACK_EFS_PROV"
      # 1,024 MiB/s, not the 3,072 this asked for first. The account's limit is
      # 1,024 and the stack fails at create with "exceeds the maximum limit
      # 1024.000000 MiB/s" -- a Service Quotas value, so an account that has
      # requested an increase may accept more. Raise it here only after
      # confirming the quota, not on the assumption that a larger number works.
      stack="$STACK_EFS_PROV"
      params=("ThroughputMode=provisioned" "ProvisionedThroughputInMibps=${EFS_PROVISIONED_MIBPS:-1024}")
      log "EFS provisioned ${EFS_PROVISIONED_MIBPS:-1024} MiBps: $stack (about \$9/hour at 1,024 from CREATE_COMPLETE)"
      cat <<'NOTE'
This is the most expensive resource in the environment and it is wanted for one pattern only.
Run that pattern, then './runbook.sh drop-efs-provisioned' immediately -- not at the end of the day.
NOTE
      printf 'Continue? [y/N] '
      read -r reply; [[ "$reply" == "y" ]] || die "aborted"
      ;;
    *) die "usage: runbook.sh efs [elastic|provisioned]" ;;
  esac
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$stack" \
    --template-file "$HERE/template-efs.yaml" \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ClientSecurityGroupId=$sg" \
      "${params[@]}" "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset
}

# Its own phase so the expensive one can go the moment its single pattern is finished, rather than
# waiting for a full teardown.
drop_efs_provisioned() {
  log "deleting $STACK_EFS_PROV"
  aws cloudformation delete-stack --region "$REGION" --stack-name "$STACK_EFS_PROV"
  aws cloudformation wait stack-delete-complete --region "$REGION" --stack-name "$STACK_EFS_PROV" \
    || die "$STACK_EFS_PROV did not reach DELETE_COMPLETE; it is still billing -- check its events"
  # Read the state back. A delete call returning without error is not evidence.
  log "verify: no EFS file system should remain from this stack"
  aws efs describe-file-systems --region "$REGION" \
    --query 'FileSystems[].{Id:FileSystemId,Mode:ThroughputMode,Mibps:ProvisionedThroughputInMibps}' \
    --output table
}

deploy_gen2() {
  # the most expensive resource here. `tooling` reads the bucket rather than the variable, and dies on a gap.
  tooling

  [[ -n "${VPC_ID:-}" && -n "${SUBNET_ID:-}" ]] || die "set VPC_ID and SUBNET_ID"
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die "set FSXADMIN_SECRET_ARN to a Secrets Manager secret with a 'password' key"
  # Varied by pattern G, which is the whole of that measurement, so it cannot stay a literal. The
  # three values are the only ones SINGLE_AZ_2 accepts, and the template's AllowedValues rejects the
  # rest before a 25-minute create finds out.
  local tp="${GEN2_THROUGHPUT:-6144}"
  case "$tp" in
    1536|3072|6144) ;;
    *) die "GEN2_THROUGHPUT must be 1536, 3072 or 6144 (the values SINGLE_AZ_2 accepts); got '$tp'" ;;
  esac
  # Opens the iSCSI and NVMe/TCP path and adds the volume a LUN or namespace goes in. Off unless asked,
  # so a run that does not measure block produces the rules it produced before that existed.
  local block="${GEN2_BLOCK:-false}"
  local sg; sg="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  # The template takes bytes and CloudFormation cannot multiply, so the conversion happens here.
  # 900 GiB holds more than twice the 256 GB in-memory cache, which is what the read has to exceed.
  local vol_gib="${VOLUME_SIZE_GIB:-900}"
  local vol_bytes=$(( vol_gib * 1024 * 1024 * 1024 ))
  # 4,096 GiB, and the reason is IOPS rather than capacity. Two 900 GiB volumes only need 2,048, but
  # FSx for ONTAP refuses more than 50 provisioned SSD IOPS per GB of SSD -- so 200,000 IOPS needs at
  # least 4,000 GiB. Without the headroom, SSD IOPS binds before the throughput capacity does and the
  # result is an IOPS measurement wearing a throughput label.
  local ssd_gib="${GEN2_STORAGE_GIB:-4096}"
  local iops="${GEN2_SSD_IOPS:-200000}"
  # Checked here rather than discovered at create time: the service rejects the ratio with a
  # BadRequest, and by then the stack has rolled back and the wait is spent.
  local max_iops=$(( ssd_gib * 50 ))
  if (( iops > max_iops )); then
    die "$iops provisioned SSD IOPS needs at least $(( (iops + 49) / 50 )) GiB of SSD; ${ssd_gib} GiB allows ${max_iops}. Raise GEN2_STORAGE_GIB or lower GEN2_SSD_IOPS."
  fi
  printf 'SSD %s GiB allows up to %s provisioned IOPS; requesting %s\n' "$ssd_gib" "$max_iops" "$iops"
  # SSD capacity is not the only ceiling, and this check was missing the other one. The published
  # specification for second-generation Single-AZ gives an SSD drive IOPS baseline per throughput
  # capacity, and states that the achievable ceiling is set by throughput capacity even when more is
  # provisioned. So a deploy can be accepted, billed, and unable to reach what was bought.
  #
  # A warning rather than a refusal: holding IOPS constant across a series while throughput capacity
  # moves is a legitimate design, and it is what pattern G does. It just has to be a decision rather
  # than a surprise on the invoice.
  local reachable_iops
  case "$tp" in
    384)   reachable_iops=12500 ;;
    768)   reachable_iops=25000 ;;
    1536)  reachable_iops=50000 ;;
    3072)  reachable_iops=100000 ;;
    6144)  reachable_iops=200000 ;;
    # Unreachable while GEN2_THROUGHPUT is validated to the three values above, but the arithmetic
    # below must be defined for whatever gets added next.
    *)     reachable_iops="$max_iops" ;;
  esac
  if (( iops > reachable_iops )); then
    printf 'WARNING: at %s MBps the SSD IOPS baseline is %s, so %s of the %s requested cannot be\n' \
      "$tp" "$reachable_iops" "$(( iops - reachable_iops ))" "$iops"
    printf '         reached at this throughput capacity. Unreachable IOPS above the included\n'
    # shellcheck disable=SC2016  # $0.0204 is a price, not an expansion
    printf '         3-per-GiB allowance still bill at $0.0204 per IOPS-month: about $%s per month.\n' \
      "$($PY_BIN -c "print(f'{max(0, $iops - max($reachable_iops, 3 * $ssd_gib)) * 0.0204:,.0f}')")"
    printf '         https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html\n'
  fi
  # Empty unless the directory exists. When set, the template adds SMB ingress and the outbound rule
  # without which an AD join cannot complete.
  local sg_ad=""
  if aws cloudformation describe-stacks --region "$REGION" --stack-name "$STACK_AD" >/dev/null 2>&1; then
    local dir_id; dir_id="$(stack_output "$STACK_AD" DirectoryId)"
    sg_ad="$(aws ds describe-directories --region "$REGION" --directory-ids "$dir_id" \
      --query 'DirectoryDescriptions[0].VpcSettings.SecurityGroupId' --output text 2>/dev/null || true)"
    [[ "$sg_ad" == "None" ]] && sg_ad=""
    printf 'directory present; passing AdSecurityGroupId=%s\n' "$sg_ad"
  else
    printf 'no directory stack; deploying NFS-only (no SMB ingress, no AD egress)\n'
  fi
  # Derived rather than stated. The hourly figure was a literal next to a literal throughput value,
  # so every configuration printed the cost of the most expensive one.
  local per_hour
  per_hour="$($PY_BIN -c "
tp=$tp; ssd=$ssd_gib; prov=$iops
print(f'{(tp*2.013 + ssd*0.15 + max(0, prov - 3*ssd)*0.0204)/730:.2f}')")"
  log "gen2 FSx for ONTAP: $STACK_GEN2 (${tp} MBps, ${ssd_gib} GiB SSD, ${iops} IOPS, ${vol_gib} GiB volume, about \$${per_hour}/hour at list price)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_GEN2" \
    --template-file "$HERE/template-fsxn-gen2.yaml" \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ClientSecurityGroupId=$sg" \
      "AdSecurityGroupId=$sg_ad" \
      "ThroughputCapacityPerHAPair=$tp" "ProvisionedSsdIops=$iops" \
      "EnableBlockProtocols=$block" \
      "StorageCapacityGiB=$ssd_gib" "VolumeSizeBytes=$vol_bytes" \
      "FsxAdminPasswordSecretArn=$FSXADMIN_SECRET_ARN" "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset \
    --disable-rollback
  # --disable-rollback because the slowest resource in this stack is created first. A file system takes
  # roughly 25 minutes, and a validation failure on the volume after that discards all of it. With
  # rollback disabled the stack stops at CREATE_FAILED with the file system intact, and the deploy can
  # be retried against it once the failing resource is fixed. It is the one stack here where that
  # trade is worth making: a half-created file system still bills, so read `costs` if a retry is not
  # going to happen promptly.
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

# --- SMB -----------------------------------------------------------------------------------------

deploy_smb_svm() {
  local fs_id; fs_id="$(stack_output "$STACK_GEN2" FileSystemId)"
  [[ -n "$fs_id" && "$fs_id" != "None" ]] || die "no FileSystemId; run './runbook.sh gen2' first"
  local vol_gib="${VOLUME_SIZE_GIB:-900}"
  local vol_bytes=$(( vol_gib * 1024 * 1024 * 1024 ))
  log "SMB SVM: $STACK_SMB_SVM on $fs_id (created unjoined; 'join-svm' performs the join)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_SMB_SVM" \
    --template-file "$HERE/template-smb-svm.yaml" \
    --parameter-overrides \
      "FileSystemId=$fs_id" "SvmNetBiosName=${SVM_NETBIOS_NAME:-PMSMB1}" \
      "VolumeSizeBytes=$vol_bytes" "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset
  printf 'SmbStorageVirtualMachineId=%s\n' "$(stack_output "$STACK_SMB_SVM" SmbStorageVirtualMachineId)"
}

deploy_windows() {
  [[ -n "${SUBNET_ID:-}" ]] || die "set SUBNET_ID"
  local sg dir_id dir_name dns
  sg="$(stack_output "$STACK_CLIENTS" ClientSecurityGroupId)"
  dir_id="$(stack_output "$STACK_AD" DirectoryId)"
  dir_name="$(stack_output "$STACK_AD" DomainName)"
  dns="$(stack_output "$STACK_AD" DirectoryDnsIpAddresses)"
  [[ -n "$dir_id" && "$dir_id" != "None" ]] || die "no DirectoryId; run './runbook.sh ad' first"
  log "Windows client: $STACK_WINDOWS (about \$2.448/hour while running)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_WINDOWS" \
    --template-file "$HERE/template-windows.yaml" \
    --capabilities CAPABILITY_IAM \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ClientSecurityGroupId=$sg" \
      "DirectoryId=$dir_id" "DirectoryName=$dir_name" "DirectoryDnsIpAddresses=$dns" \
      "StagingBucketName=${STAGING_BUCKET:-}" "BenchUserSecretArn=${BENCHUSER_SECRET_ARN:-}" \
      "AdAdminSecretArn=${AD_SECRET_ARN:-}" \
      "NamePrefix=$PREFIX" \
    --no-fail-on-empty-changeset
  printf 'WindowsInstanceId=%s\n' "$(stack_output "$STACK_WINDOWS" WindowsInstanceId)"

  # Re-run the join deliberately. The association's own first run can fire before the instance has set
  # its DNS or before the Directory Service endpoint answers, and CloudFormation cannot order those --
  # the endpoint is conditional, so nothing can DependsOn it.
  local assoc; assoc="$(stack_output "$STACK_WINDOWS" DomainJoinAssociationId)"
  if [[ -n "$assoc" && "$assoc" != "None" ]]; then
    printf 'triggering the domain join association once, now that the endpoint exists\n'
    aws ssm start-associations-once --region "$REGION" --association-ids "$assoc" \
      || printf 'could not trigger it; it will still run on its own schedule\n'
  fi
  printf 'Now run: ./runbook.sh windows-status\n'
}

# The stack reaching CREATE_COMPLETE says the association exists. This says whether the instance
# arrived in Systems Manager and whether the join actually ran.
windows_status() {
  local instance assoc
  instance="$(stack_output "$STACK_WINDOWS" WindowsInstanceId)"
  assoc="$(stack_output "$STACK_WINDOWS" DomainJoinAssociationId)"
  [[ -n "$instance" && "$instance" != "None" ]] || die "no Windows instance; run './runbook.sh windows' first"

  log "Systems Manager: is the instance there at all"
  # An instance absent from this list is usually a private subnet without the ssm, ssmmessages and
  # ec2messages interface endpoints, and it looks like a directory problem from every other angle.
  aws ssm describe-instance-information --region "$REGION" \
    --filters "Key=InstanceIds,Values=$instance" \
    --query 'InstanceInformationList[].{Id:InstanceId,Ping:PingStatus,Platform:PlatformName,Agent:AgentVersion}' \
    --output table

  log "domain join association: outcome"
  aws ssm describe-association-executions --region "$REGION" --association-id "$assoc" \
    --query 'AssociationExecutions[0:3].{Status:Status,Created:CreatedTime,Detail:DetailedStatus}' \
    --output table

  cat <<'NOTE'
`Success` here is still second-hand. Confirm from the instance itself:

    aws ssm start-session --target <instance-id>
    (Get-ComputerInfo).CsDomain          # the domain name, not WORKGROUP
    Get-DnsClientServerAddress           # must show the controller addresses

If the association failed, the reason is in the command output rather than in the status above:

    aws ssm list-command-invocations --instance-id <instance-id> --details \
      --query 'CommandInvocations[0].CommandPlugins[].Output'
NOTE
}

# Joins the SMB SVM to the directory. A separate step from the stack on purpose: a join that lands in
# MISCONFIGURED is corrected by running this again against the same SVM, whereas a failure inside
# CloudFormation rolls the SVM back and leaves an orphaned computer object whose name must not be
# reused.
join_svm() {
  [[ -n "${AD_SECRET_ARN:-}" ]] || die "set AD_SECRET_ARN"
  local svm_id dir_id domain short dns
  svm_id="${SMB_SVM_ID:-$(stack_output "$STACK_SMB_SVM" SmbStorageVirtualMachineId)}"
  [[ -n "$svm_id" && "$svm_id" != "None" ]] || die "no SMB SVM; run './runbook.sh smb-svm' first"
  dir_id="$(stack_output "$STACK_AD" DirectoryId)"

  # Read the domain's own values back rather than retyping them. The short name is what the
  # intermediate organizational unit is named after, and a mismatch there is the most common cause of
  # a join that fails without explaining itself.
  domain="$(aws ds describe-directories --region "$REGION" --directory-ids "$dir_id" \
    --query 'DirectoryDescriptions[0].Name' --output text)"
  short="$(aws ds describe-directories --region "$REGION" --directory-ids "$dir_id" \
    --query 'DirectoryDescriptions[0].ShortName' --output text)"
  dns="$(aws ds describe-directories --region "$REGION" --directory-ids "$dir_id" \
    --query 'DirectoryDescriptions[0].DnsIpAddrs' --output text)"

  # AWS Managed AD puts computer objects under an intermediate OU named after the short name. Omitting
  # that middle component is a documented cause of failure, so it is derived here rather than guessed.
  local ou="OU=Computers,OU=${short}"
  local part
  for part in ${domain//./ }; do ou="${ou},DC=${part}"; done

  log "joining $svm_id to $domain"
  printf 'OU: %s\nNetBIOS: %s\nDnsIps: %s\n' "$ou" "${SVM_NETBIOS_NAME:-PMSMB1}" "$dns"

  # Built by python3 into a mode-600 temporary file, and removed on exit. The password is neither in
  # this script nor in the process arguments, where `ps` would show it.
  local cfg; cfg="$(mktemp)"
  chmod 600 "$cfg"
  # shellcheck disable=SC2064  # expand $cfg now: the trap must name this file, not whatever is set later
  trap "rm -f '$cfg'" EXIT

  local secret
  secret="$(aws secretsmanager get-secret-value --region "$REGION" --secret-id "$AD_SECRET_ARN" \
    --query SecretString --output text)"

  # FileSystemAdministratorsGroup is Domain Admins, not AWS Delegated FSx Administrators: the delegated
  # group has insufficient permissions for an SVM join and the failure reads as "unmet port
  # requirements or insufficient service account permissions", which sends you to the wrong layer.
  SECRET_JSON="$secret" OU_DN="$ou" DOMAIN="$domain" DNS_IPS="$dns" \
  NETBIOS="${SVM_NETBIOS_NAME:-PMSMB1}" AD_USER="${AD_ADMIN_USER:-Admin}" \
  python3 - "$cfg" <<'PY'
import json, os, sys

secret = json.loads(os.environ["SECRET_JSON"])
config = {
    "NetBiosName": os.environ["NETBIOS"],
    "SelfManagedActiveDirectoryConfiguration": {
        "DomainName": os.environ["DOMAIN"],
        "OrganizationalUnitDistinguishedName": os.environ["OU_DN"],
        "UserName": os.environ["AD_USER"],
        "Password": secret["password"],
        "DnsIps": os.environ["DNS_IPS"].split(),
        "FileSystemAdministratorsGroup": "Domain Admins",
    },
}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(config, handle)
PY

  aws fsx update-storage-virtual-machine --region "$REGION" \
    --storage-virtual-machine-id "$svm_id" \
    --active-directory-configuration "file://$cfg" \
    --query 'StorageVirtualMachine.Lifecycle' --output text
  rm -f "$cfg"

  # Poll. The call returning is not the join succeeding.
  #
  # **And `Lifecycle` alone cannot answer this.** An unjoined SVM is already `CREATED`, so polling for
  # that returns on the first read and reports success before anything has happened -- observed: it
  # printed "joined" while the SMB endpoint was still null, and the endpoint only appeared about a
  # minute later. The evidence of a join is the join's own output: a NetBIOS name and an SMB endpoint.
  log "polling for the join's own output (2-5 minutes is normal)"
  local i state netbios smb
  for i in $(seq 1 40); do
    read -r state netbios smb <<<"$(aws fsx describe-storage-virtual-machines --region "$REGION" \
      --storage-virtual-machine-ids "$svm_id" \
      --query 'StorageVirtualMachines[0].[Lifecycle,ActiveDirectoryConfiguration.NetBiosName,Endpoints.Smb.DNSName]' \
      --output text)"
    printf '  %2d/40 lifecycle=%s netbios=%s smb=%s\n' "$i" "$state" "$netbios" "$smb"
    [[ "$smb" != "None" && -n "$smb" ]] && break
    case "$state" in
      MISCONFIGURED|FAILED) break ;;
    esac
    sleep 15
  done

  if [[ "$smb" == "None" || -z "$smb" ]]; then
    aws fsx describe-storage-virtual-machines --region "$REGION" \
      --storage-virtual-machine-ids "$svm_id" \
      --query 'StorageVirtualMachines[0].LifecycleTransitionReason.Message' --output text
    cat <<'NOTE'
MISCONFIGURED is recoverable against this same SVM. Before retrying, check in this order:
  1. Does the directory security group admit the SVM interfaces?  ./runbook.sh ad-ports
  2. Was the gen2 stack deployed with AdSecurityGroupId set?      ./runbook.sh gen2
     Without its outbound rule the SVM cannot reach a controller at all.
  3. Is the OU path right, including the intermediate OU named after the short name?
  4. Set SVM_NETBIOS_NAME to a name not used before -- a failed attempt leaves a computer object
     behind, and reusing its name collides.
NOTE
    die "no SMB endpoint after the join (lifecycle: $state). The SVM is not usable over SMB yet."
  fi

  printf '\njoined. SMB endpoint: %s\n' "$smb"
}

# --- gates and accounting ------------------------------------------------------------------------

# Reads or changes the NVMe read cache over the ONTAP REST API, from a client, because there is no AWS
# API for it. Run as `nvme-cache show` or `nvme-cache off`.
#
# The password is read on the client from Secrets Manager rather than passed in: a Run Command's
# parameters are kept in Systems Manager's command history.
nvme_cache() {
  local action="${1:-show}"
  local fs_id; fs_id="$(stack_output "$STACK_GEN2" FileSystemId)"
  [[ -n "$fs_id" && "$fs_id" != "None" ]] || die "no FileSystemId; run './runbook.sh gen2' first"
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die "set FSXADMIN_SECRET_ARN"
  local instance; instance="$(stack_output "$STACK_CLIENTS" SingleHostInstanceId)"
  [[ -n "$instance" && "$instance" != "None" ]] || die "no client; run './runbook.sh clients' first"

  local mgmt="management.${fs_id}.fsx.${REGION}.amazonaws.com"
  local read_cmd="curl -s -k -u \"fsxadmin:\$PW\" \"https://${mgmt}/api/private/cli/system/node/external-cache?fields=node,is-enabled\" | python3 -m json.tool"
  local script
  case "$action" in
    show) script="$read_cmd" ;;
    off)
      # PATCH, then sleep, then read. **The PATCH returning is not evidence.** Judge by the second read.
      script="curl -s -k -X PATCH -u \"fsxadmin:\$PW\" -H 'Content-Type: application/json' -d '{\"is_enabled\": false}' \"https://${mgmt}/api/private/cli/system/node/external-cache?node=*\" >/dev/null; sleep 30; $read_cmd"
      ;;
    *) die "usage: runbook.sh nvme-cache [show|off]" ;;
  esac

  log "NVMe read cache on $fs_id: $action"
  ontap_rest_on_client "$instance" "$script"
  printf '\nRead the is_enabled values above. Every node must report false before the disk-path read.\n'
}

# Runs a shell snippet on a client with $PW holding the fsxadmin password, and prints its output.
#
# The password is fetched on the client from Secrets Manager rather than passed in, because a Run
# Command's parameters are retained in Systems Manager's command history.
#
# The payload is built as JSON into a file rather than passed with the --parameters shorthand. The
# shorthand is parsed by the CLI itself and cannot survive the nested quoting these commands need; it
# fails with "Expected: ',', received: 'f'", with the caret pointing inside the curl invocation.
ontap_rest_on_client() {
  local instance="$1" script="$2"
  local payload; payload="$(mktemp)"
  # shellcheck disable=SC2064  # expand now, so the trap names this file
  trap "rm -f '$payload'" RETURN
  SECRET_ARN="$FSXADMIN_SECRET_ARN" REGION_NAME="$REGION" SCRIPT="$script" \
    python3 - "$payload" <<'PY'
import json, os, sys

fetch_password = (
    "PW=$(aws secretsmanager get-secret-value"
    f" --region {os.environ['REGION_NAME']}"
    f" --secret-id {os.environ['SECRET_ARN']}"
    " --query SecretString --output text"
    " | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"password\"])')"
)
payload = {"Parameters": {"commands": ["set -uo pipefail", fetch_password, os.environ["SCRIPT"]]}}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY

  ssm_send_and_wait "$instance" "$payload"
}

# The send-and-poll half, factored out so `run_on_client` is not a second copy of it. Two copies of
# the same shell drifting apart is what the toolchain test one directory over exists to catch.
ssm_send_and_wait() {
  local instance="$1" payload="$2"
  local cmd_id
  cmd_id="$(aws ssm send-command --region "$REGION" --instance-ids "$instance" \
    --document-name AWS-RunShellScript --timeout-seconds 600 \
    --cli-input-json "file://$payload" \
    --query 'Command.CommandId' --output text)"
  local i state
  for i in $(seq 1 30); do
    state="$(aws ssm get-command-invocation --region "$REGION" --command-id "$cmd_id" \
      --instance-id "$instance" --query Status --output text)"
    [[ "$state" == "InProgress" || "$state" == "Pending" ]] || break
    sleep 15
  done
  aws ssm get-command-invocation --region "$REGION" --command-id "$cmd_id" --instance-id "$instance" \
    --query 'StandardOutputContent' --output text
  # **Print stderr too.** Only stdout was reported before, so a failing command inside a phase left no
  # trace: an iSCSI login that logged `iscsiadm: No records found` looked like a phase that had simply
  # counted zero connections, and three of the Pattern F attempts were diagnosed one deployment at a
  # time because of it. The reason a command failed belongs next to the failure.
  local err
  err="$(aws ssm get-command-invocation --region "$REGION" --command-id "$cmd_id" \
    --instance-id "$instance" --query 'StandardErrorContent' --output text)"
  if [[ -n "$err" && "$err" != "None" ]]; then
    printf '\n--- stderr from the client ---\n%s\n' "$err"
  fi
  [[ "$state" == "Success" ]] || die "the command did not succeed (status: $state)"
}

# A client command with no ONTAP credentials in it. `ontap_rest_on_client` prepends a Secrets Manager
# fetch because the ONTAP password must not reach the Systems Manager command history. A plain client
# command needs neither the fetch nor that exposure, so it gets its own entry point rather than
# passing an empty secret through the other one.
run_on_client() {
  local instance="$1" script="$2"
  local payload; payload="$(mktemp)"
  # shellcheck disable=SC2064  # expand now, so the trap names this file
  trap "rm -f '$payload'" RETURN
  SCRIPT="$script" $PY_BIN - "$payload" <<'PY'
import json, os, sys
payload = {"Parameters": {"commands": ["set -uo pipefail", os.environ["SCRIPT"]]}}
with open(sys.argv[1], "w", encoding="utf-8") as handle:
    json.dump(payload, handle)
PY
  ssm_send_and_wait "$instance" "$payload"
}

# **The default that makes FSx for ONTAP look slow.** ONTAP ships tcp-max-xfer-size at 65536, and it is
# a server-side ceiling: a client asking for rsize=1048576 gets 65536 and the mount still succeeds.
# Observed on a freshly created file system, with the request and the grant differing by a factor of 16.
#
# Amazon EFS grants 1 MiB. So measuring FSx for ONTAP at its default against EFS at its default compares
# 64 KiB transfers with 1 MiB ones, and the gap gets recorded as a difference between the products.
#
# Run `nfs-xfer-size show` to read it and `nfs-xfer-size raise` to set 1 MiB. Clients must remount.
nfs_xfer_size() {
  local action="${1:-show}"
  local fs_id; fs_id="$(stack_output "$STACK_GEN2" FileSystemId)"
  [[ -n "$fs_id" && "$fs_id" != "None" ]] || die "no FileSystemId; run './runbook.sh gen2' first"
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die "set FSXADMIN_SECRET_ARN"
  local instance; instance="$(stack_output "$STACK_CLIENTS" SingleHostInstanceId)"
  [[ -n "$instance" && "$instance" != "None" ]] || die "no client; run './runbook.sh clients' first"

  local mgmt="management.${fs_id}.fsx.${REGION}.amazonaws.com"
  local read_cmd="curl -s -k -u \"fsxadmin:\$PW\" \"https://${mgmt}/api/private/cli/vserver/nfs?fields=vserver,tcp-max-xfer-size\" | python3 -m json.tool"
  local script
  case "$action" in
    show) script="$read_cmd" ;;
    raise)
      script="curl -s -k -X PATCH -u \"fsxadmin:\$PW\" -H 'Content-Type: application/json' -d '{\"tcp_max_xfer_size\": 1048576}' \"https://${mgmt}/api/private/cli/vserver/nfs?vserver=*\" >/dev/null; sleep 15; $read_cmd"
      ;;
    *) die "usage: runbook.sh nfs-xfer-size [show|raise]" ;;
  esac

  log "NFS tcp-max-xfer-size on $fs_id: $action"
  ontap_rest_on_client "$instance" "$script"
  cat <<'NOTE'

Every vserver must read 1048576 before the file-protocol measurements.

Then remount, and read the *effective* options rather than trusting the request:

    grep ' /mnt/bench/target ' /proc/mounts

A mount that was granted 65536 after asking for 1048576 succeeds silently.
NOTE
}

# The gate that matters. A disk-path read taken with the NVMe cache enabled is a cache measurement.
# The instrument, before anything that bills.
#
# **VDBENCH cannot be fetched by automation.** It needs an Oracle sign-in and a licence acceptance, so
# it arrives by hand or not at all. That makes it the one prerequisite whose absence cannot be fixed
# in the moment it is discovered -- and it used to be discovered after the file system existed.
#
# Checked by reading the bucket rather than by trusting the variable: STAGING_BUCKET being set says
# where the tooling would be, not that it is there.
tooling() {
  [[ -n "${STAGING_BUCKET:-}" ]] || die "set STAGING_BUCKET; the clients have no route to PyPI, GitHub or Oracle"
  aws s3api head-bucket --bucket "$STAGING_BUCKET" >/dev/null 2>&1 \
    || die "cannot read s3://$STAGING_BUCKET -- wrong name, wrong account, or no permission"
  local listing missing=0
  listing="$(aws s3 ls "s3://$STAGING_BUCKET/" --recursive)" \
    || die "listing s3://$STAGING_BUCKET failed, so this is not a report that it is empty"
  log "staged tooling in s3://$STAGING_BUCKET"
  # One line per artefact, and each says how to produce it. A missing wheel is a five-minute fix; a
  # missing VDBENCH is a licence acceptance.
  if ! grep -qE 'tooling/vdbench[0-9]*\.zip' <<<"$listing"; then
    printf 'MISSING tooling/vdbench<version>.zip\n'
    printf '        Oracle sign-in and licence acceptance required. Download by hand, then:\n'
    printf '        aws s3 cp vdbench50407.zip s3://%s/tooling/\n' "$STAGING_BUCKET"
    missing=1
  fi
  if ! grep -q 'tooling/auto_vdbench.tar.gz' <<<"$listing"; then
    printf 'MISSING tooling/auto_vdbench.tar.gz  (git clone + tar; see the README step 2)\n'
    missing=1
  fi
  if ! grep -q 'wheels/' <<<"$listing"; then
    printf 'MISSING wheels/  (pip download for cp311 manylinux; plotly==5.24.1 and kaleido==0.2.1 pinned)\n'
    missing=1
  fi
  [[ "$missing" -eq 0 ]] || die "the instrument is incomplete; nothing billable is worth creating yet"
  printf 'All three present. VDBENCH is the one that cannot be re-fetched in the moment, so this is the gate.\n'
}

preflight() {
  log "preflight"
  python3 "$HERE/../../scripts/protocol_matrix_harness.py" --dry-run

  log "NVMe read cache state"
  nvme_cache show
  cat <<'NOTE'

If any node reports true, turn it off and confirm:

    ./runbook.sh nvme-cache off

That is a REST call to the ONTAP private CLI passthrough -- there is no AWS API for this setting, and
the PATCH returning without error is not evidence. The phase re-reads the state afterwards.

With the cache off, a read only has to exceed the in-memory cache: 256 GB at 2048 MBps and at
6144 MBps. Read at least 512 GB in one pass.
NOTE
  printf 'Confirmed every node reports is_enabled false? [y/N] '
  read -r reply; [[ "$reply" == "y" ]] || die "stopping: measure the cache off, or record that it was on"
}


# Read the four things an SMB mount needs before trying to mount. Three of them were inferred from
# adjacent data on 2026-09-06 and all three were wrong, and two of the three surface as error
# messages that point somewhere else entirely -- a missing account reads as a wrong password.
# Mechanism and sources: docs/ja/reference/limits/smb-share-and-identifier-reading.md
smb_preflight() {
  local svm_name="${SMB_SVM_NAME:-${PREFIX}-smb-svm}"
  local share="${SMB_SHARE_NAME:-bench}"
  local account="${SMB_BENCH_ACCOUNT:-benchuser}"
  local fs_id; fs_id="$(stack_output "$STACK_GEN2" FileSystemId)"
  local linux; linux="$(stack_output "$STACK_CLIENTS" SingleHostInstanceId)"
  local win; win="$(stack_output "$STACK_WINDOWS" WindowsInstanceId)"
  [[ -n "$fs_id" && "$fs_id" != "None" ]] || die "no gen2 file system; run './runbook.sh gen2' first"
  [[ -n "$linux" && "$linux" != "None" ]] || die "no Linux client; the ONTAP read runs from inside the VPC"
  [[ -n "$win" && "$win" != "None" ]] || die "no Windows client; the account lookup runs on a joined host"
  log "smb-preflight: svm=$svm_name share=$share account=$account"
  "$PY_BIN" "$HERE/../../scripts/smb_preflight.py" \
    --file-system-id "$fs_id" --svm-name "$svm_name" --share "$share" --account "$account" \
    --client-instance-id "$linux" --windows-instance-id "$win" \
    --region "$REGION" --fsxadmin-secret-arn "$FSXADMIN_SECRET_ARN"
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
  aws ds describe-directories --region "$REGION" \
    --query 'DirectoryDescriptions[].{Id:DirectoryId,Name:Name,Type:Type,Edition:Edition,Stage:Stage}' \
    --output table
  aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:DeleteAfterMeasurement,Values=true" "Name=instance-state-name,Values=running" \
    --query 'Reservations[].Instances[].{Id:InstanceId,Type:InstanceType,Name:Tags[?Key==`Name`]|[0].Value}' \
    --output table
  cat <<'NOTE'
Hourly, at ap-northeast-1 On-Demand prices read on 2026-09-04:
  EFS provisioned 1024 MiBps   ~$9      delete to stop
  gen2 6144 MBps + 200k IOPS   $23.03   delete, or lower the specified value
  gen1 2048 MBps + 80k IOPS    $ 4.90   each; lower the specified value
  c5n.9xlarge Linux            $ 2.45   stops when stopped
  c5n.9xlarge Windows          $ 2.45   stops when stopped
  c5n.2xlarge                  $ 0.54   each; stops when stopped
  Managed AD Standard          $ 0.15   $0.073 per controller-hour, two controllers
  gen2 SSD 4096 GiB            included in the $23.03 above, at $0.15 per GB-month
EFS Elastic is not on this list because it bills per GB accessed, not per hour.
NOTE
}

usage() {
  cat <<'USAGE'
Usage: runbook.sh <phase>

Order: ad -> clients -> gen2 -> ad-ports -> smb-svm -> join-svm -> windows -> windows-status
       -> smb-preflight (before any mount)
       -> preflight -> efs elastic -> measure -> efs provisioned -> measure -> drop it -> teardown

  ad                     Create AWS Managed Microsoft AD (15-30 min, ~$0.146/hour). Do this first.
  clients                Create the Linux clients and the shared security group
  gen2                   Create the second-generation FSx for ONTAP target (~$23.03/hour)
  ad-ports               Read the directory's security group and admit the clients and SVM interfaces
  smb-svm                Create the SMB-only SVM and its NTFS volume, unjoined
  join-svm               Join that SVM to the directory, and poll until it is CREATED
  windows                Create the Windows client and its domain-join association (~$2.448/hour)
  windows-status         Read whether the instance arrived and whether the join ran
  smb-preflight          Read the SVM name, the data share, its junction path and the domain
                         account. Run it before mounting: two of these fail with messages that
                         point elsewhere
  nvme-cache show|off    Read or disable the NVMe read cache over the ONTAP REST API

  Block protocols (pattern F). NEVER EXECUTED -- read each phase's output, not its exit status:
  block-packages         Install the iSCSI and NVMe/TCP clients; print the IQN and the NQN
  block-provision iscsi <IQN>  Create the LUN, the igroup and the mapping; print serial-hex
  block-provision nvme <NQN>   Create the namespace and the subsystem; map the host
  block-sessions single|default|multi [n]  Log in, then COUNT the connections opened
  block-nvme-sessions single|default|multi  NVMe/TCP has no nr_sessions: single pins
                         --nr-io-queues=1, which is the only comparable form (see the plan)
  block-preflight        The gate. Check 1 protects the client, not the result
  block-fill <device>    Write the device once with dd; an unwritten thin LUN reads as zeros
  nfs-xfer-size show|raise  Read or raise tcp-max-xfer-size. **65536 by default, and it caps rsize**
  raise-gen1             Raise the existing first-generation file system to 2048 MBps (~24 min)
  tooling                Read the staging bucket. VDBENCH cannot be automated, so this comes first
  preflight              Print the support matrix and gate on the NVMe read cache being disabled
  efs elastic            Create the EFS target in elastic mode ($0.07/GB accessed, no hourly charge)
  efs provisioned        Create a second EFS in provisioned mode at 1024 MiBps (~$9/hour)
  drop-efs-provisioned   Delete that one, immediately after its single pattern
  costs                  Show what is billing right now
  teardown               Hand off to teardown.sh

Environment:
  required   VPC_ID SUBNET_ID
  for AD     SUBNET_ID_2 (different AZ) AD_SECRET_ARN
  for gen2   FSXADMIN_SECRET_ARN
  for gen1   GEN1_FS_ID
  for tools  STAGING_BUCKET -- the clients have no route to PyPI or GitHub, so VDBENCH,
             auto_vdbench and the Python wheels come in over S3
  optional   NAME_PREFIX AWS_REGION VOLUME_SIZE_GIB GEN2_STORAGE_GIB GEN2_SSD_IOPS
             GEN2_THROUGHPUT (1536|3072|6144, default 6144) GEN2_BLOCK (true opens iSCSI/NVMe-TCP) AD_DOMAIN_NAME
             AD_SHORT_NAME AD_ADMIN_USER SVM_NETBIOS_NAME SMB_SVM_ID
USAGE
}

# =================================================================================================
# Block protocols (pattern F). **EVERY PHASE BELOW HAS NEVER BEEN EXECUTED.**
#
# They are written before a measurement window rather than during one, because the window is paid for
# and the alternative is writing the LUN provisioning and the device-identity preflight under time
# pressure -- which is when the preflight is the step that gets skipped.
#
# Linted, not run. Treat the first execution as part of the measurement: read each phase's output
# rather than its exit status, the way `nvme-cache off` is read.
#
# Why these are runbook phases and not CloudFormation: `lun create`, `lun igroup create`,
# `lun mapping create`, `vserver nvme namespace create` and `vserver nvme subsystem create` have no
# equivalent in the FSx API or in AWS::FSx::Volume. The template opens the ports and provides the
# volume; everything inside the volume is ONTAP's.
# =================================================================================================

BLOCK_LUN_GIB="${BLOCK_LUN_GIB:-600}"
BLOCK_LUN_NAME="${BLOCK_LUN_NAME:-${PREFIX}_lun}"
BLOCK_IGROUP="${BLOCK_IGROUP:-${PREFIX}_igroup}"
BLOCK_NS_NAME="${BLOCK_NS_NAME:-${PREFIX}_ns}"
BLOCK_SUBSYSTEM="${BLOCK_SUBSYSTEM:-${PREFIX}_subsys}"
BLOCK_FRIENDLY="${BLOCK_FRIENDLY:-${PREFIX}-blk}"

# Shared preamble for the block phases: the client, the management endpoint and the SVM name, each
# read rather than assumed. The SVM name is not derived from the volume name -- in this environment the
# SVM is hyphen-separated and the volume is underscore-separated, which has already been a wrong guess.
block_context() {
  BLOCK_FS_ID="$(stack_output "$STACK_GEN2" FileSystemId)"
  [[ -n "$BLOCK_FS_ID" && "$BLOCK_FS_ID" != "None" ]] || die "no FileSystemId; run './runbook.sh gen2' first"
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die "set FSXADMIN_SECRET_ARN"
  BLOCK_INSTANCE="$(stack_output "$STACK_CLIENTS" SingleHostInstanceId)"
  [[ -n "$BLOCK_INSTANCE" && "$BLOCK_INSTANCE" != "None" ]] || die "no client; run './runbook.sh clients' first"
  BLOCK_VOL="$(stack_output "$STACK_GEN2" BlockVolumeName)"
  [[ -n "$BLOCK_VOL" && "$BLOCK_VOL" != "None" ]] \
    || die "no BlockVolumeName; deploy gen2 with EnableBlockProtocols=true"
  BLOCK_SVM="$(aws fsx describe-storage-virtual-machines --region "$REGION" \
    --filters "Name=file-system-id,Values=$BLOCK_FS_ID" \
    --query 'StorageVirtualMachines[0].Name' --output text)"
  [[ -n "$BLOCK_SVM" && "$BLOCK_SVM" != "None" ]] || die "could not read the SVM name"
  BLOCK_MGMT="management.${BLOCK_FS_ID}.fsx.${REGION}.amazonaws.com"
  # The block endpoint is read from the API, not assembled from the SVM name. `iscsi.<svm-name>` does
  # not resolve -- the phases built that name and got an empty discovery, an empty `target=` and no
  # login at all (2026-09-12). The API returns both the DNS name and the addresses of the two LIFs;
  # the addresses are what the session and connect phases need, and AWS's own NVMe procedure passes an
  # address to `-a` rather than a name. The NVMe/TCP endpoint is the same one: AWS names its addresses
  # iscsi_1 and iscsi_2 in the NVMe procedure too.
  BLOCK_ISCSI_IPS="$(aws fsx describe-storage-virtual-machines --region "$REGION" \
    --filters "Name=file-system-id,Values=$BLOCK_FS_ID" \
    --query 'StorageVirtualMachines[0].Endpoints.Iscsi.IpAddresses' --output text | tr '\t' ' ')"
  [[ -n "$BLOCK_ISCSI_IPS" && "$BLOCK_ISCSI_IPS" != "None" ]] \
    || die "no iSCSI endpoint addresses on the SVM; deploy gen2 with EnableBlockProtocols=true"
}

# The client packages. Amazon Linux 2023's repositories are reachable over the S3 gateway endpoint even
# though PyPI and GitHub are not, so this needs no staging bucket.
#
# **AWS's NVMe/TCP procedure is written for RHEL 9.3 and these clients are AL2023.** Whether
# `nvme-cli` and the `nvme_tcp` module are both available here is UNCONFIRMED, and it is the one thing
# that can make F-2 unmeasurable. It costs nothing to find out, so this phase runs before the file
# system exists.
block_packages() {
  block_context
  log "installing the iSCSI and NVMe/TCP clients on $BLOCK_INSTANCE"
  run_on_client "$BLOCK_INSTANCE" '
dnf install -y iscsi-initiator-utils device-mapper-multipath nvme-cli
mpathconf --enable --with_multipathd y
sed -i "s/^node.session.timeo.replacement_timeout = .*/node.session.timeo.replacement_timeout = 5/" /etc/iscsi/iscsid.conf
systemctl enable --now iscsid multipathd
modprobe nvme-tcp && echo nvme-tcp > /etc/modules-load.d/nvme-tcp.conf
# The AWS procedure reads /etc/nvme/hostnqn as though installing nvme-cli created it. On RHEL 9.3,
# which that page is written against, it does. **On AL2023 the file is absent after the install**
# (observed 2026-09-12), so the host NQN the subsystem needs does not exist yet. Generate it.
mkdir -p /etc/nvme
[ -s /etc/nvme/hostnqn ] || nvme gen-hostnqn > /etc/nvme/hostnqn
echo "--- what the initiator and host are called ---"
cat /etc/iscsi/initiatorname.iscsi || echo "ABSENT: initiatorname.iscsi"
cat /etc/nvme/hostnqn || echo "ABSENT: /etc/nvme/hostnqn"
echo "--- module and multipath state ---"
lsmod | grep -E "^nvme_tcp|^dm_multipath" || echo "MISSING: a module did not load"
# Read defensively and name the path. A bare `cat` of an absent file ends the script on a non-zero
# status, which SSM reports as a failed invocation -- so an informational read decided the phase.
for p in /sys/module/nvme_core/parameters/multipath /sys/module/nvme_core/parameters/io_timeout; do
  printf "%s = %s\n" "$p" "$(cat "$p" 2>/dev/null || echo ABSENT)"
done
# **The AWS procedure verifies native NVMe multipath by reading that first path and expecting Y.** On
# AL2023 it was ABSENT while io_timeout in the same directory was readable (2026-09-12), so the
# parameter itself is not exposed rather than the directory being missing. Whether the module was built
# with multipath support at all is the question that decides it, so ask the module.
echo "--- is native NVMe multipath compiled in ---"
modinfo nvme_core 2>/dev/null | grep -i multipath || echo "no multipath parameter in modinfo nvme_core"
grep -i 'NVME_MULTIPATH' /boot/config-"$(uname -r)" 2>/dev/null || echo "no NVME_MULTIPATH line in the kernel config"
# The exit status now reflects what the next phases actually need, and nothing else.
rc=0
[ -s /etc/iscsi/initiatorname.iscsi ] || { echo "FAIL: no IQN"; rc=1; }
[ -s /etc/nvme/hostnqn ] || { echo "FAIL: no host NQN"; rc=1; }
exit $rc'
  printf '\nRead the IQN and the NQN above; the provisioning phases need them.\n'
  printf 'A MISSING line means F-2 cannot be measured on this AMI. That is a finding, not a blocker to work around.\n'
  printf 'ABSENT names a file that was not there. It is reported, not treated as a module failure.\n'
}

# iSCSI: LUN, igroup, mapping. Returns the serial-hex, which is what the friendly device name is built
# from -- **the device index is never used**, because the client's root EBS volume is /dev/nvme0n1 and
# indices move with attach order.
block_provision_iscsi() {
  block_context
  local iqn="${1:-}"
  [[ -n "$iqn" ]] || die "usage: runbook.sh block-provision iscsi <client-IQN>  (from 'block-packages')"
  log "creating LUN ${BLOCK_LUN_NAME} (${BLOCK_LUN_GIB} GiB) in ${BLOCK_VOL} on ${BLOCK_SVM}"
  local api="https://${BLOCK_MGMT}/api/private/cli"
  ontap_rest_on_client "$BLOCK_INSTANCE" "
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"path\":\"/vol/${BLOCK_VOL}/${BLOCK_LUN_NAME}\",\"size\":\"${BLOCK_LUN_GIB}GB\",\"ostype\":\"linux\",\"space-allocation\":\"enabled\"}' \
  '${api}/lun' | python3 -m json.tool
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"igroup\":\"${BLOCK_IGROUP}\",\"protocol\":\"iscsi\",\"ostype\":\"linux\",\"initiator\":[\"${iqn}\"]}' \
  '${api}/lun/igroup' | python3 -m json.tool
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"path\":\"/vol/${BLOCK_VOL}/${BLOCK_LUN_NAME}\",\"igroup\":\"${BLOCK_IGROUP}\"}' \
  '${api}/lun/mapping' | python3 -m json.tool
echo '--- serial-hex, state and mapped: the friendly name is built from the serial ---'
curl -s -k -u \"fsxadmin:\$PW\" \
  '${api}/lun?path=/vol/${BLOCK_VOL}/${BLOCK_LUN_NAME}&fields=serial-hex,state,mapped' | python3 -m json.tool"
  printf '\nTake serial-hex from above and add it to /etc/multipath.conf as alias %s, then run block-preflight.\n' "$BLOCK_FRIENDLY"
}

# NVMe/TCP: namespace, subsystem, mapping, host. The namespace and the LUN are separate objects in the
# same volume, so F-1 and F-2 read the same volume without sharing a target.
block_provision_nvme() {
  block_context
  local nqn="${1:-}"
  [[ -n "$nqn" ]] || die "usage: runbook.sh block-provision nvme <client-NQN>  (from 'block-packages')"
  log "creating namespace ${BLOCK_NS_NAME} and subsystem ${BLOCK_SUBSYSTEM} on ${BLOCK_SVM}"
  local api="https://${BLOCK_MGMT}/api/private/cli"
  ontap_rest_on_client "$BLOCK_INSTANCE" "
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"path\":\"/vol/${BLOCK_VOL}/${BLOCK_NS_NAME}\",\"size\":\"${BLOCK_LUN_GIB}GB\",\"ostype\":\"linux\"}' \
  '${api}/vserver/nvme/namespace' | python3 -m json.tool
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"subsystem\":\"${BLOCK_SUBSYSTEM}\",\"ostype\":\"linux\"}' \
  '${api}/vserver/nvme/subsystem' | python3 -m json.tool
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"subsystem\":\"${BLOCK_SUBSYSTEM}\",\"path\":\"/vol/${BLOCK_VOL}/${BLOCK_NS_NAME}\"}' \
  '${api}/vserver/nvme/subsystem/map' | python3 -m json.tool
curl -s -k -u \"fsxadmin:\$PW\" -X POST -H 'Content-Type: application/json' \
  -d '{\"vserver\":\"${BLOCK_SVM}\",\"subsystem\":\"${BLOCK_SUBSYSTEM}\",\"host-nqn\":\"${nqn}\"}' \
  '${api}/vserver/nvme/subsystem/host' | python3 -m json.tool
echo '--- the block LIFs. Both are used, by both protocols ---'
curl -s -k -u \"fsxadmin:\$PW\" \
  '${api}/network/interface?vserver=${BLOCK_SVM}&fields=address,current-node,current-port,service-policy' | python3 -m json.tool"
}

# Sessions. **The point of this phase is that the requested count and the opened count are different
# numbers**, which `nconnect` and SMB Multichannel have each already demonstrated here.
#
# `single` is the only form comparable with the file-side one-connection rows: nr_sessions is per
# node and a login without a portal reaches both nodes, so the default of "one session" opens two
# connections.
block_sessions() {
  block_context
  local mode="${1:-}" count="${2:-8}"
  case "$mode" in
    single|default|multi) ;;
    *) die "usage: runbook.sh block-sessions [single|default|multi] [count]" ;;
  esac
  log "iSCSI sessions: $mode"
  run_on_client "$BLOCK_INSTANCE" "
set -x
iscsiadm --mode node --logoutall=all || true
# The LIF addresses come from the FSx API (see block_context), not from a name built out of the SVM
# name. Discovery against the first one returns both portals.
ips='${BLOCK_ISCSI_IPS}'
echo \"LIF addresses: \$ips\"
first=\$(echo \$ips | awk '{print \$1}')
target=\$(iscsiadm --mode discovery --op update --type sendtargets --portal \"\$first\" | awk '{print \$2}' | head -1)
echo \"target=\$target\"
[ -n \"\$target\" ] || { echo 'FAIL: sendtargets discovery returned no target IQN'; exit 1; }
# **Take the portal from the API addresses, not from parsed iscsiadm output.** Asking iscsiadm for the
# node records of one target prints a full record dump whose first line is a comment, so the previous
# parse handed `# BEGIN RECORD 2.1.4` to --login as a portal and got `No records found` (2026-09-12).
# The addresses are already known -- block_context read them from the FSx API.
#
# **And make the login manual before choosing portals.** Discovery leaves node.startup at automatic on
# this AMI, so iscsid logs into every portal on its own; a single-portal login would silently become two
# sessions, which is exactly the distinction the single-flow point exists to make.
iscsiadm --mode node -T \"\$target\" --op update -n node.startup -v manual
want=1
case '$mode' in
  single)
    # One portal only. This is the single-flow point and the only one comparable with the file rows.
    iscsiadm --mode node -T \"\$target\" --op update -n node.session.nr_sessions -v 1
    iscsiadm --mode node -T \"\$target\" -p \"\$first:3260\" --login
    want=1
    ;;
  default)
    iscsiadm --mode node -T \"\$target\" --op update -n node.session.nr_sessions -v 1
    for ip in \$ips; do iscsiadm --mode node -T \"\$target\" -p \"\$ip:3260\" --login || true; done
    want=2
    ;;
  multi)
    iscsiadm --mode node -T \"\$target\" --op update -n node.session.nr_sessions -v $count
    for ip in \$ips; do iscsiadm --mode node -T \"\$target\" -p \"\$ip:3260\" --login || true; done
    want=\$(( 2 * $count ))
    ;;
esac
set +x
# **The login is asynchronous.** iscsid brings the connection up after --login returns, and on this
# client it took about 100 seconds: a count taken immediately reported 0 established connections while
# the journal showed both sessions becoming operational a minute and a half later. Waiting is not
# assuming -- the number printed below is still the counted one, and it is printed whether or not the
# wait was satisfied.
n=0
for i in \$(seq 1 40); do
  n=\$(iscsiadm --mode session 2>/dev/null | grep -c '^tcp' || true)
  n=\${n:-0}
  [ \"\$n\" -ge \"\$want\" ] && break
  sleep 5
done
echo \"sessions after waiting: \$n (at least \$want expected for $mode)\"
[ \"\$n\" -ge \"\$want\" ] || echo \"WARN: fewer sessions than expected. The counted value is what the result records.\"
# multipath merges paths only once the sessions exist, so the reload belongs after the wait.
multipath -r >/dev/null 2>&1 || true
sleep 5
echo '--- COUNT THE CONNECTIONS. The requested value is not the answer ---'
ss -tn state established '( dport = :3260 )' | tail -n +2 | wc -l
ss -tn state established '( dport = :3260 )'
echo '--- multipath: active and enabled counts must match ---'
multipath -ll || true"
  printf '\nRecord the counted connections next to the requested value. They are two fields, not one.\n'
}

# The gate. Nothing is measured until this passes, and the first check is the one that protects the
# client rather than the result.
# The NVMe/TCP counterpart of `block_sessions`. There is no `nr_sessions` on this side: the NVMe/TCP
# transport maps each queue pair to one TCP connection, so the quantity corresponding to an iSCSI
# session is the queue count. Three separate numbers govern it and none of them is documented to agree
# with the others -- the host's request (`--nr-io-queues`), the subsystem's inherited value (whose own
# description says the value actually used "may vary depending on the host and transport protocol
# used"), and the target's per-node/per-transport/per-priority allocation. A NetApp KB records a
# subsystem set to 15 while the host read NCQA/NSQA of 2. Sources are cited in
# docs/ja/verification/block-protocol-matrix-plan.md.
#
# Two consequences for this function:
#   - `default` uses the form AWS documents (`connect-all -t tcp -w <client_ip> -a <lif> -l 1800`),
#     not a hand-rolled `nvme connect`. That single command reaches both LIFs, so the number it
#     produces is the one a reader following the AWS procedure gets.
#   - the single-flow point therefore cannot use `connect-all`; it pins one LIF and one queue, and it
#     is the only form comparable with the file-side single-connection rows.
#
# Report the requested value, the effective NCQA/NSQA, the counted TCP connections, the driver's
# queue_count and the ANA states. Never a single number called "sessions".
block_nvme_sessions() {
  block_context
  local mode="${1:-}"
  case "$mode" in
    single|default|multi) ;;
    *) die "usage: runbook.sh block-nvme-sessions [single|default|multi]" ;;
  esac
  log "NVMe/TCP sessions: $mode"
  run_on_client "$BLOCK_INSTANCE" "
set -x
nvme disconnect-all || true
# The same endpoint addresses the iSCSI phase uses, read from the FSx API in block_context. AWS's NVMe
# procedure calls them iscsi_1 and iscsi_2 as well.
ips='${BLOCK_ISCSI_IPS}'
echo \"LIF addresses: \$ips\"
first=\$(echo \$ips | awk '{print \$1}')
# The subsystem NQN comes from discovery rather than from a variable, so a rename on the ONTAP side
# cannot leave this phase connecting to a name that no longer exists.
nqn=\$(nvme discover -t tcp -a \"\$first\" -s 8009 | awk '/^subnqn:/{print \$2}' | grep -v discovery | head -1)
echo \"subsystem nqn: \$nqn\"
[ -n \"\$nqn\" ] || { echo 'FAIL: discovery returned no subsystem NQN'; exit 1; }
# The AWS procedure passes the client's own address as the host traddr (-w). Derive it from the route
# to the LIF rather than from a variable: a hard-coded address survives a client rebuild silently.
myip=\$(ip -o route get \"\$first\" | sed -n 's/.* src \\([0-9.]*\\).*/\\1/p' | head -1)
echo \"host traddr: \$myip\"
[ -n \"\$myip\" ] || { echo 'FAIL: could not determine the source address toward the LIF'; exit 1; }
cpus=\$(nproc)
requested=''
case '$mode' in
  single)
    # One LIF, one I/O queue. **This is the single-flow point**, and the only row comparable with the
    # file-side single-connection numbers. connect-all cannot be used: it reaches both LIFs.
    requested=1
    nvme connect -t tcp -a \"\$first\" -s 4420 -n \"\$nqn\" -w \"\$myip\" -l 1800 --nr-io-queues=1
    ;;
  default)
    # Exactly the form in the AWS documentation. One command, both LIFs, queue count left to the
    # host and the target to negotiate.
    requested='(unset: host default)'
    nvme connect-all -t tcp -w \"\$myip\" -a \"\$first\" -l 1800
    ;;
  multi)
    # Same form, with the queue count requested up to the vCPU count. Whether the request survives
    # is the measurement; the target may allocate fewer.
    requested=\$cpus
    nvme connect-all -t tcp -w \"\$myip\" -a \"\$first\" -l 1800 --nr-io-queues=\"\$cpus\"
    ;;
esac
set +x
# The controllers appear after the connect returns, the same way the iSCSI login completes after
# --login returns. Wait for a namespace to be listed before reading anything about it.
for i in \$(seq 1 24); do
  nvme netapp ontapdevices -o column 2>/dev/null | grep -q '^/dev' && break
  sleep 5
done
echo \"--- requested queue count: \$requested (vCPUs: \$cpus) ---\"
echo '--- effective queue count. THIS is what the target allocated, not what was asked for ---'
for n in \$(nvme netapp ontapdevices -o column 2>/dev/null | awk '/^\\/dev/{print \$1}'); do
  echo \"\$n:\"
  nvme get-feature \"\$n\" --feature-id 7 --human-readable 2>/dev/null || echo '  (get-feature failed)'
done
echo '--- COUNT THE CONNECTIONS. The queue count requested is not the answer ---'
ss -tn state established '( dport = :4420 )' | tail -n +2 | wc -l
ss -tn state established '( dport = :4420 )'
echo '--- controllers, queue counts and ANA states ---'
nvme list-subsys || true
for c in /sys/class/nvme/nvme*/queue_count; do [ -e \"\$c\" ] && echo \"\$c = \$(cat \"\$c\")\"; done
echo '--- multipath and iopolicy, as the AWS procedure verifies them ---'
cat /sys/module/nvme_core/parameters/multipath 2>/dev/null || echo 'MISSING'
cat /sys/class/nvme-subsystem/nvme-subsys*/iopolicy 2>/dev/null || true
echo '--- the device to point the parameter file at ---'
nvme netapp ontapdevices -o column || true"
  cat <<'NOTE'

Record five fields, never one number called "sessions":

  1. the requested queue count      (what this phase asked for)
  2. NCQA / NSQA from get-feature   (what the target allocated -- a KB records 15 asked, 2 given)
  3. the counted TCP connections on :4420
  4. queue_count per controller
  5. the ANA state of each controller (one optimized, one non-optimized is expected)

Do not place NVMe default/multi beside the iSCSI rows of the same name. iSCSI varies the portal
count, which the configuration fixes; here the queue count is negotiated between host and target.
NOTE
}

block_preflight() {
  block_context
  log "block preflight on $BLOCK_INSTANCE"
  run_on_client "$BLOCK_INSTANCE" "
fail=0
echo '=== 1. the device the parameter file names must be the ONTAP one ==='
for path in /dev/mapper/${BLOCK_FRIENDLY} \$(nvme netapp ontapdevices -o column 2>/dev/null | awk '/^\\/dev/{print \$1}'); do
  [ -e \"\$path\" ] || continue
  echo \"\$path\"
  lsblk -no NAME,SIZE,MODEL \"\$path\" 2>/dev/null || true
done
if lsblk -no MODEL /dev/mapper/${BLOCK_FRIENDLY} 2>/dev/null | grep -qi 'Elastic Block Store'; then
  echo 'FAIL: that path is the root EBS volume. Writing to it destroys the client.'; fail=1
fi
echo '=== 2. iSCSI multipath: equal numbers of active and enabled ==='
multipath -ll 2>/dev/null | grep -cE 'status=active' || true
multipath -ll 2>/dev/null | grep -cE 'status=enabled' || true
echo '=== 3. NVMe multipath, iopolicy and ANA states ==='
cat /sys/module/nvme_core/parameters/multipath 2>/dev/null || echo 'MISSING'
cat /sys/class/nvme-subsystem/nvme-subsys*/iopolicy 2>/dev/null || true
nvme list-subsys 2>/dev/null | grep -E 'optimized|live' || true
echo '=== 4. the connections that are actually open ==='
printf 'iscsi 3260: '; ss -tn state established '( dport = :3260 )' | tail -n +2 | wc -l
printf 'nvme  4420: '; ss -tn state established '( dport = :4420 )' | tail -n +2 | wc -l
exit \$fail"
  cat <<'NOTE'

Read all four. This phase reports; it does not decide for you.

  1. A FAIL here is the only failure in this environment that costs a client rebuild.
  2. Unequal active/enabled counts mean dm-multipath has not merged the sessions.
  3. NVMe paths are asymmetric by design -- one optimized, one non-optimized. Record both;
     the asymmetry is a candidate explanation for any iSCSI/NVMe difference.
  4. Compare against what was requested. They have differed before, silently.

Then run block-fill before any read is measured: unwritten blocks of a thin LUN return zeros
without reaching disk, which measures nothing.
NOTE
}

# The fill pass. Its only job is that no read is served from unwritten blocks of a thin LUN, which
# return zeros without reaching disk.
#
# **This is dd, not VDBENCH, and the rate it reports is a dd rate.** Two attempts were spent on
# VDBENCH here. Command-line `key=value` arguments are *substitutions* for placeholders in the
# parameter file, not overrides of its workload definitions, so passing `xfersize=1024k rdpct=0 ...`
# against a file that has no such placeholders aborts with `Unused parameter substitution`
# (2026-09-12). Writing a fill definition into the measurement parameter file instead would mean the
# fill and the measurement could no longer diverge without one silently changing the other. dd keeps
# them separate and its own failure mode is visible.
#
# Do not quote the fill rate next to the measured rates. It is a different tool.
block_fill() {
  block_context
  local device="${1:-}"
  [[ -n "$device" ]] || die "usage: runbook.sh block-fill <device path>"
  case "$device" in
    /dev/mapper/*|/dev/nvme*) ;;
    *) die "refusing to write to '$device': fill takes the multipath alias or an nvme namespace" ;;
  esac
  log "filling $device once, with dd"
  printf 'This writes the whole device. Confirm block-preflight check 1 passed first.\n'
  run_on_client "$BLOCK_INSTANCE" "
dev='$device'
[ -b \"\$dev\" ] || { echo \"FAIL: \$dev is not a block device\"; exit 1; }
# Check 1 of the preflight again, at the point of the write. The cost of getting this wrong here is a
# destroyed client, and it costs one lsblk to refuse.
if lsblk -no MODEL \"\$dev\" 2>/dev/null | grep -qi 'Elastic Block Store'; then
  echo 'FAIL: that device is EBS, not ONTAP. Refusing to write.'; exit 1
fi
size=\$(blockdev --getsize64 \"\$dev\")
gib=\$(( size / 1073741824 ))
echo \"device \$dev is \$gib GiB\"
# Non-zero data, so nothing downstream can serve the fill back from a zero-detection path. Storage
# efficiency is disabled on this volume, but the fill should not depend on that being true.
[ -s /tmp/rand1g ] || dd if=/dev/urandom of=/tmp/rand1g bs=1M count=1024 status=none
start=\$(date +%s)
i=0
while [ \"\$i\" -lt \"\$gib\" ]; do
  dd if=/tmp/rand1g of=\"\$dev\" bs=1M count=1024 seek=\$(( i * 1024 )) oflag=direct status=none || break
  i=\$(( i + 1 ))
done
end=\$(date +%s)
elapsed=\$(( end - start ))
[ \"\$elapsed\" -gt 0 ] || elapsed=1
echo \"filled \$i GiB of \$gib in \$elapsed s = \$(( i * 1024 / elapsed )) MB/s (dd, not VDBENCH)\"
[ \"\$i\" -eq \"\$gib\" ] || { echo 'FAIL: the fill did not cover the whole device'; exit 1; }"
  printf '\nThe fill rate above is a dd rate. Do not place it beside the VDBENCH numbers.\n'
}

case "${1:-}" in
  ad)                   deploy_ad ;;
  ad-ports)             ad_ports ;;
  clients)              deploy_clients ;;
  efs)                  deploy_efs "${2:-elastic}" ;;
  drop-efs-provisioned) drop_efs_provisioned ;;
  gen2)                 deploy_gen2 ;;
  smb-svm)              deploy_smb_svm ;;
  smb-preflight)        smb_preflight ;;
  join-svm)             join_svm ;;
  windows)              deploy_windows ;;
  windows-status)       windows_status ;;
  raise-gen1)           raise_gen1 ;;
  nvme-cache)           nvme_cache "${2:-show}" ;;
  block-packages)       block_packages ;;
  block-provision)      case "${2:-}" in
                          iscsi) block_provision_iscsi "${3:-}" ;;
                          nvme)  block_provision_nvme  "${3:-}" ;;
                          *)     die "usage: runbook.sh block-provision [iscsi|nvme] <IQN or NQN>" ;;
                        esac ;;
  block-sessions)       block_sessions "${2:-}" "${3:-8}" ;;
  block-nvme-sessions)  block_nvme_sessions "${2:-}" ;;
  block-preflight)      block_preflight ;;
  block-fill)           block_fill "${2:-}" ;;
  nfs-xfer-size)        nfs_xfer_size "${2:-show}" ;;
  tooling)              tooling ;;
  preflight)            preflight ;;
  costs)                costs ;;
  teardown)             exec "$HERE/teardown.sh" ;;
  *)                    usage; exit 1 ;;
esac
