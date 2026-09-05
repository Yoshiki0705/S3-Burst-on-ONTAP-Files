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
#   3. **EFS Provisioned comes last and leaves first.** At $30.30/hour it is the most expensive line
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
# like against an FSx for ONTAP throughput capacity setting, and costs $30.30/hour to hold.
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
      params=("ThroughputMode=provisioned" "ProvisionedThroughputInMibps=3072")
      log "EFS provisioned 3072 MiBps: $stack (about \$30.30/hour from CREATE_COMPLETE)"
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
  [[ -n "${VPC_ID:-}" && -n "${SUBNET_ID:-}" ]] || die "set VPC_ID and SUBNET_ID"
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die "set FSXADMIN_SECRET_ARN to a Secrets Manager secret with a 'password' key"
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
  log "gen2 FSx for ONTAP: $STACK_GEN2 (6144 MBps, ${ssd_gib} GiB SSD, ${vol_gib} GiB volume, about \$23.03/hour)"
  aws cloudformation deploy \
    --region "$REGION" \
    --stack-name "$STACK_GEN2" \
    --template-file "$HERE/template-fsxn-gen2.yaml" \
    --parameter-overrides \
      "VpcId=$VPC_ID" "SubnetId=$SUBNET_ID" "ClientSecurityGroupId=$sg" \
      "AdSecurityGroupId=$sg_ad" \
      "ThroughputCapacityPerHAPair=6144" "ProvisionedSsdIops=$iops" \
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
      "StagingBucketName=${STAGING_BUCKET:-}" "NamePrefix=$PREFIX" \
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
  [[ "$state" == "Success" ]] || die "the command did not succeed (status: $state)"
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
  EFS provisioned 3072 MiBps   $30.30   delete to stop
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
       -> preflight -> efs elastic -> measure -> efs provisioned -> measure -> drop it -> teardown

  ad                     Create AWS Managed Microsoft AD (15-30 min, ~$0.146/hour). Do this first.
  clients                Create the Linux clients and the shared security group
  gen2                   Create the second-generation FSx for ONTAP target (~$23.03/hour)
  ad-ports               Read the directory's security group and admit the clients and SVM interfaces
  smb-svm                Create the SMB-only SVM and its NTFS volume, unjoined
  join-svm               Join that SVM to the directory, and poll until it is CREATED
  windows                Create the Windows client and its domain-join association (~$2.448/hour)
  windows-status         Read whether the instance arrived and whether the join ran
  nvme-cache show|off    Read or disable the NVMe read cache over the ONTAP REST API
  nfs-xfer-size show|raise  Read or raise tcp-max-xfer-size. **65536 by default, and it caps rsize**
  raise-gen1             Raise the existing first-generation file system to 2048 MBps (~24 min)
  preflight              Print the support matrix and gate on the NVMe read cache being disabled
  efs elastic            Create the EFS target in elastic mode ($0.07/GB accessed, no hourly charge)
  efs provisioned        Create a second EFS in provisioned mode at 3072 MiBps (~$30.30/hour)
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
  optional   NAME_PREFIX AWS_REGION VOLUME_SIZE_GIB GEN2_STORAGE_GIB GEN2_SSD_IOPS AD_DOMAIN_NAME
             AD_SHORT_NAME AD_ADMIN_USER SVM_NETBIOS_NAME SMB_SVM_ID
USAGE
}

case "${1:-}" in
  ad)                   deploy_ad ;;
  ad-ports)             ad_ports ;;
  clients)              deploy_clients ;;
  efs)                  deploy_efs "${2:-elastic}" ;;
  drop-efs-provisioned) drop_efs_provisioned ;;
  gen2)                 deploy_gen2 ;;
  smb-svm)              deploy_smb_svm ;;
  join-svm)             join_svm ;;
  windows)              deploy_windows ;;
  windows-status)       windows_status ;;
  raise-gen1)           raise_gen1 ;;
  nvme-cache)           nvme_cache "${2:-show}" ;;
  nfs-xfer-size)        nfs_xfer_size "${2:-show}" ;;
  preflight)            preflight ;;
  costs)                costs ;;
  teardown)             exec "$HERE/teardown.sh" ;;
  *)                    usage; exit 1 ;;
esac
