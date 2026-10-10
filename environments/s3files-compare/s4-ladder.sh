#!/usr/bin/env bash
# =================================================================================================
# S-4: S3 Files host-count ladder. Launch N identical c5n.2xlarge clients, mount S3 Files on each,
# read the same file (and, separately, disjoint ranges) at counts 1/2/4/8 with a shared start epoch,
# and sum the per-host steady-window throughput.
#
# Adapted from environments/perf-matrix/ladder.sh. The differences from that NFS/ONTAP ladder:
#   - Target is S3 Files, mounted via the mount helper (efs-proxy per host), not an ONTAP SVM LIF.
#   - No nconnect (S3 Files does not support it; the mount hangs if requested).
#   - Server-side corroboration is CloudWatch AWS/S3/Files DataReadBytes, not an ONTAP port counter
#     (there is no customer-reachable ONTAP here; the backend is EFS).
#   - Each host has its OWN efs-proxy, so a per-host ceiling and a shared-service ceiling are both
#     plausible; the same-data vs disjoint pair is what separates them.
#
# Reuses the already-created S3 Files file system and host role from ./runbook.sh create (state in
# .s3files-run.env) and the dedicated VPC/subnet (.bench-net.env). The 600 GiB file1 written by
# ./throughput-runbook.sh prepare is the shared read target.
#
# Usage:
#   STAGING_BUCKET=<bucket> ./s4-ladder.sh launch     # 8x c5n.2xlarge, mount, stage vdbench, fill-check
#   ./s4-ladder.sh run [1 2 4 8]                       # same-file ladder
#   ./s4-ladder.sh disjoint [8]                        # non-overlapping ranges at N hosts
#   ./s4-ladder.sh stop                                # terminate the ladder hosts
# =================================================================================================
set -uo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
STATE="${STATE:-./.s3files-run.env}"
NET="${NET:-./.bench-net.env}"
MOUNT="${MOUNT:-/mnt/bench/s3files}"
PARM="vdbench-linux-s3files-ladder.txt"
LADDER_COUNT="${LADDER_COUNT:-8}"
INSTANCE_TYPE="${LADDER_INSTANCE_TYPE:-c5n.2xlarge}"

die() { printf 's4: %s\n' "$*" >&2; exit 1; }
# shellcheck source=/dev/null
source "$STATE"
# shellcheck source=/dev/null
source "$NET"
: "${FS:?}" "${AP:?}" "${HOST_ROLE:?}" "${BUCKET:?}" "${SUBNET_ID:?}" "${HOST_SG:?}"

send() {
  local timeout="$1"; shift
  local -a ids=("$@")
  local json
  json=$(python3 -c 'import json,sys; print(json.dumps({"commands":[ln for ln in sys.stdin.read().split("\n") if ln.strip()!=""]}))')
  aws ssm send-command --region "$REGION" --instance-ids "${ids[@]}" \
    --document-name AWS-RunShellScript --cli-input-json "{\"Parameters\":$json}" \
    --timeout-seconds "$timeout" --query 'Command.CommandId' --output text
}
wait_cmd() {
  local cmd="$1" limit="$2" i pending
  for ((i=0; i<limit; i++)); do
    # shellcheck disable=SC2016
    pending=$(aws ssm list-command-invocations --region "$REGION" --command-id "$cmd" \
      --query 'length(CommandInvocations[?Status==`InProgress` || Status==`Pending`])' --output text)
    [[ "$pending" == "0" ]] && return 0
    sleep 15
  done
  return 1
}
out_of() { aws ssm get-command-invocation --region "$REGION" --command-id "$1" --instance-id "$2" --query 'StandardOutputContent' --output text; }

discover() {
  local id; local -a found=()
  while IFS= read -r id; do [[ -n "$id" ]] && found+=("$id"); done < <(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=s3files-ladder-*" 'Name=instance-state-name,Values=running' \
    --query 'sort_by(Reservations[].Instances[], &Tags[?Key==`Name`]|[0].Value)[].InstanceId' --output text | tr '\t' '\n')
  [[ ${#found[@]} -gt 0 ]] || die "no running s3files-ladder-* instances"
  HOST_IDS=("${found[@]}")
  printf 's4: %s ladder host(s)\n' "${#HOST_IDS[@]}" >&2
}

cmd_launch() {
  : "${STAGING_BUCKET:?set STAGING_BUCKET}"
  local ami
  ami=$(aws ssm get-parameter --region "$REGION" --name /aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64 --query Parameter.Value --output text)
  printf 's4: launching %s x %s\n' "$LADDER_COUNT" "$INSTANCE_TYPE"
  for n in $(seq 1 "$LADDER_COUNT"); do
    aws ec2 run-instances --region "$REGION" --image-id "$ami" --instance-type "$INSTANCE_TYPE" \
      --subnet-id "$SUBNET_ID" --security-group-ids "$HOST_SG" --associate-public-ip-address \
      --iam-instance-profile "Name=${HOST_ROLE}" \
      --metadata-options "HttpTokens=required,HttpEndpoint=enabled" \
      --block-device-mappings "DeviceName=/dev/xvda,Ebs={VolumeSize=20,VolumeType=gp3,Encrypted=true,DeleteOnTermination=true}" \
      --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=s3files-ladder-$(printf '%02d' "$n")},{Key=Project,Value=s3-burst-on-ontap-files},{Key=Environment,Value=verify}]" \
      --query 'Instances[0].InstanceId' --output text >/dev/null
  done
  printf 's4: waiting for SSM registration\n'
  sleep 40
  discover
  for id in "${HOST_IDS[@]}"; do
    until [[ "$(aws ssm describe-instance-information --region "$REGION" --filters "Key=InstanceIds,Values=$id" --query 'length(InstanceInformationList)' --output text)" == 1 ]]; do sleep 8; done
  done
  printf 's4: all %s registered. mounting + staging vdbench\n' "${#HOST_IDS[@]}"
  local cmd
  cmd=$(send 900 "${HOST_IDS[@]}" <<SCRIPT
set -e
mkdir -p ${MOUNT} /opt/bench/parm
dnf install -y -q amazon-efs-utils java-17-amazon-corretto-headless python3.12 python3-botocore >/dev/null 2>&1
mountpoint -q ${MOUNT} || timeout 120 mount -t s3files -o accesspoint=${AP} ${FS}:/ ${MOUNT}
findmnt -T ${MOUNT} -o FSTYPE -n
aws s3 cp s3://${STAGING_BUCKET}/tooling/vdbench.zip /tmp/vdbench.zip --region ${REGION}
rm -rf /opt/vdbench && mkdir -p /opt/vdbench && (cd /opt/vdbench && unzip -oq /tmp/vdbench.zip)
vdbin=\$(find /opt/vdbench -maxdepth 2 -name vdbench -type f | head -1)
printf '#!/usr/bin/env bash\nexec %s "\$@"\n' "\$vdbin" > /usr/local/bin/vdbench && chmod +x /usr/local/bin/vdbench
ls -l ${MOUNT}/file1 2>&1 | head -1 || echo "WARNING file1 missing"
echo READY-\$(hostname -s)
SCRIPT
)
  wait_cmd "$cmd" 50 || die "launch provisioning did not finish"
  for id in "${HOST_IDS[@]}"; do out_of "$cmd" "$id" | grep -E 'READY|WARNING|s3files|nfs' | sed "s/^/  $id: /"; done
}

cloudwatch_read_bytes() {
  local since; since=$(date -u -v-6M +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '6 min ago' +%Y-%m-%dT%H:%M:%SZ)
  aws cloudwatch get-metric-statistics --region "$REGION" --namespace AWS/S3/Files \
    --metric-name DataReadBytes --dimensions Name=FileSystemId,Value="$FS" \
    --start-time "$since" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" --period 60 --statistics Sum \
    --query 'sort_by(Datapoints,&Timestamp)[].[Timestamp,Sum]' --output text 2>/dev/null | tail -8
}

run_ladder() {
  local mode="$1"; shift
  local -a points=("$@")
  [[ ${#points[@]} -gt 0 ]] || points=(1 2 4 8)
  discover
  # Push the ladder parameter file to every host. launch does not do this, and vdbench errors with
  # Vdb_scan.parm_error on a missing file rather than saying the file is absent.
  local parm_b64 pushcmd
  parm_b64=$(base64 < "../perf-matrix/vdbench/${PARM}" | tr -d '\n')
  pushcmd=$(send 120 "${HOST_IDS[@]}" <<SCRIPT
mkdir -p /opt/bench/parm
echo ${parm_b64} | base64 -d > /opt/bench/parm/${PARM}
grep -c '^sd=' /opt/bench/parm/${PARM}
SCRIPT
)
  wait_cmd "$pushcmd" 20 || die "param push did not finish"
  local n epoch cmd id line mb resp total reported
  for n in "${points[@]}"; do
    (( n >= 1 && n <= ${#HOST_IDS[@]} )) || die "host count $n outside 1..${#HOST_IDS[@]}"
    local -a ids=("${HOST_IDS[@]:0:n}")
    epoch=$(( $(date +%s) + 90 ))
    local id_list; id_list=$(printf '%s ' "${ids[@]}")
    printf '\n=== %s: %s host(s), epoch %s\n' "$mode" "$n" "$epoch"
    if [[ "$mode" == disjoint ]]; then
      cmd=$(send 900 "${ids[@]}" <<SCRIPT
set -uo pipefail
TOK=\$(curl -s -X PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
ME=\$(curl -s -H "X-aws-ec2-metadata-token: \$TOK" 'http://169.254.169.254/latest/meta-data/instance-id')
IDX=-1; i=0; for h in ${id_list}; do [ "\$h" = "\$ME" ] && IDX=\$i; i=\$((i+1)); done
[ "\$IDX" -ge 0 ] || { echo ABORT-notinlist; exit 1; }
SPAN=\$(python3 -c "print(f'{100/${n}:.4f}')"); LO=\$(python3 -c "print(f'{\$IDX*\$SPAN:.4f}')"); HI=\$(python3 -c "print(f'{(\$IDX+1)*\$SPAN:.4f}')")
sed "s|,lun=${MOUNT}/file1\$|,lun=${MOUNT}/file1,range=(\$LO,\$HI)|" /opt/bench/parm/${PARM} > /opt/bench/parm/s4-dj.txt
grep -q 'range=(' /opt/bench/parm/s4-dj.txt || { echo ABORT-norange; exit 1; }
rm -rf /opt/bench/out-s4-dj-${n}
while [ "\$(date +%s)" -lt ${epoch} ]; do sleep 1; done
cd /opt/bench/parm; /usr/local/bin/vdbench -f s4-dj.txt -o /opt/bench/out-s4-dj-${n} > /var/log/vdb-s4dj-${n}.log 2>&1
echo "rc=\$? host=\$(hostname -s)"; grep -E 'avg_61-[0-9]+' /var/log/vdb-s4dj-${n}.log || { echo NOAVG; tail -15 /var/log/vdb-s4dj-${n}.log; }
SCRIPT
)
    else
      cmd=$(send 900 "${ids[@]}" <<SCRIPT
set -uo pipefail
findmnt -no FSTYPE ${MOUNT} | grep -q nfs || { echo MOUNT-GONE; exit 1; }
rm -rf /opt/bench/out-s4-${n}
while [ "\$(date +%s)" -lt ${epoch} ]; do sleep 1; done
cd /opt/bench/parm; /usr/local/bin/vdbench -f ${PARM} -o /opt/bench/out-s4-${n} > /var/log/vdb-s4-${n}.log 2>&1
echo "rc=\$? host=\$(hostname -s)"; grep -E 'avg_61-[0-9]+' /var/log/vdb-s4-${n}.log || { echo NOAVG; tail -15 /var/log/vdb-s4-${n}.log; }
SCRIPT
)
    fi
    wait_cmd "$cmd" 60 || die "point $n did not finish"
    total=0; reported=0
    for id in "${ids[@]}"; do
      line=$(out_of "$cmd" "$id" | grep -E 'avg_61-[0-9]+' | head -1 || true)
      [[ -z "$line" ]] && { printf '  ! %s no steady line\n' "$id"; out_of "$cmd" "$id" | tail -4 | sed 's/^/    /'; continue; }
      mb=$(awk '{print $4}' <<<"$line"); resp=$(awk '{print $7}' <<<"$line")
      total=$(python3 -c "print(f'{$total + $mb:.2f}')"); reported=$((reported+1))
      printf '    %-21s %10s MB/s  %8s ms\n' "$id" "$mb" "$resp"
    done
    if [[ "$reported" -ne "$n" ]]; then printf '  RESULT %s n=%s PARTIAL total=%s over %s/%s\n' "$mode" "$n" "$total" "$reported" "$n"; continue; fi
    printf '  RESULT %s n=%s total=%s MB/s  per-host=%s MB/s\n' "$mode" "$n" "$total" "$(python3 -c "print(f'{$total/$n:.2f}')")"
    printf '  CloudWatch DataReadBytes (per-min Sum, high-perf storage reads):\n'; cloudwatch_read_bytes | sed 's/^/    /'
  done
}

cmd_stop() {
  discover
  aws ec2 terminate-instances --region "$REGION" --instance-ids "${HOST_IDS[@]}" \
    --query 'TerminatingInstances[].{Id:InstanceId,S:CurrentState.Name}' --output text
}

declare -a HOST_IDS=()
case "${1:-}" in
  launch) cmd_launch ;;
  run) shift; run_ladder same "$@" ;;
  disjoint) shift; run_ladder disjoint "$@" ;;
  stop) cmd_stop ;;
  *) die 'usage: s4-ladder.sh {launch|run [counts]|disjoint [count]|stop}' ;;
esac
