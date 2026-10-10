#!/usr/bin/env bash
# =================================================================================================
# S3 Files THROUGHPUT measurement — host-side driver for S-1..S-4.
#
# This complements ./runbook.sh (which creates the S3 Files file system, mount target, access
# point and host, and tears them all down). That runbook measured reflection and semantics on a
# t3.small. THIS script drives VDBENCH against the S3 Files mount to measure throughput, IOPS,
# concurrency and host count, per docs/ja/verification/s3files-throughput-matrix-plan.md
# (patterns S-1..S-4). It writes no measured value into the repository; it produces VDBENCH
# reports that a human reads and transcribes into a verification record.
#
# WHAT THIS SCRIPT DOES NOT CREATE: the file system and host come from ./runbook.sh. Create them
# first with a throughput-class instance, NOT the t3.small default:
#
#   VPC_ID=vpc-... SUBNET_ID=subnet-... INSTANCE_TYPE=c5n.9xlarge HOST_VOLUME_GIB=60 \
#     ./runbook.sh create
#
# c5n.9xlarge has a 50 Gbps GUARANTEED (not "Up to") baseline. A smaller or "Up to" instance puts
# the client's own network allowance inside the range being measured, so a ceiling found on it
# cannot be attributed to S3 Files. HOST_VOLUME_GIB=60 holds VDBENCH, Java and the AES-CTR
# generator; the 600 GiB test file lives on the S3 Files mount, not on the root volume.
#
# VDBENCH CANNOT BE AUTO-DOWNLOADED. Oracle requires an interactive sign-in and licence
# acceptance. Stage it to an S3 bucket the host role can read, and pass STAGING_BUCKET:
#
#   aws s3 cp vdbench50407.zip s3://<staging-bucket>/tooling/vdbench.zip
#   STAGING_BUCKET=<staging-bucket> ./throughput-runbook.sh prepare
#
# The s3files-compare host created with --associate-public-ip-address CAN reach the internet for
# dnf and pip, so Java and the data generator install directly; only VDBENCH needs staging.
#
# Usage (run after ./runbook.sh create):
#   STAGING_BUCKET=b ./throughput-runbook.sh prepare   # install java/vdbench/generator, make data
#   ./throughput-runbook.sh s1-s2                       # single-host full workload (S-1 + S-2)
#   ./throughput-runbook.sh s3-cache                    # cache-temperature pair (S-3)
#   ./throughput-runbook.sh collect                     # pull reports + CloudWatch to ./results/
#
# S-4 (host count) needs more than one host and a shared start epoch; it is intentionally NOT in
# this single-host driver. Its shape is in vdbench-linux-s3files-ladder.txt and the orchestration
# mirrors environments/perf-matrix/ladder.sh. Add it only once S-1..S-3 have landed.
#
# Every command here runs ON THE MEASUREMENT HOST over SSM from the operator's machine. The
# `ssm` helper sends a command document and waits. Nothing in this script is billable on its own;
# the file system and host created by ./runbook.sh are. Run ./runbook.sh destroy when done.
# =================================================================================================
set -uo pipefail

REGION=${AWS_REGION:-ap-northeast-1}
STATE=${STATE:-./.s3files-run.env}
MOUNT=${MOUNT:-/mnt/bench/s3files}
PARM_SRC=${PARM_SRC:-../perf-matrix/vdbench}   # the shared VDBENCH parameter files
RESULTS=${RESULTS:-./results}

die() { echo "error: $*" >&2; exit 1; }
step() { printf '\n== %s ==\n' "$1"; }

command -v aws >/dev/null || die "aws CLI not found"
[[ -f "$STATE" ]] || die "no $STATE; run ./runbook.sh create first (with INSTANCE_TYPE=c5n.9xlarge)"
# shellcheck source=/dev/null  # state file written by runbook.sh create; contents are ids, not code
source "$STATE"
: "${IID:?no IID in state}" "${FS:?no FS in state}" "${AP:?no AP in state}" "${BUCKET:?no BUCKET in state}"

# Send a shell command to the host over SSM and wait for it, streaming stdout/stderr back.
# The command is passed via a JSON parameters FILE, not an inline --parameters string: inline
# interpolation lets the local shell mangle redirects and heredocs before they reach send-command
# ("ambiguous redirect"). The file carries the script verbatim as a single JSON array element.
ssm() {
  local cmd="$1" cid pf
  pf=$(mktemp /tmp/ssm-parm-XXXX.json)
  python3 -c 'import json,sys;print(json.dumps({"commands":[sys.argv[1]]}))' "$cmd" > "$pf"
  cid=$(aws ssm send-command --region "$REGION" --instance-ids "$IID" \
    --document-name AWS-RunShellScript --comment "s3files-throughput" \
    --parameters "file://$pf" \
    --query 'Command.CommandId' --output text) || { rm -f "$pf"; die "send-command failed"; }
  rm -f "$pf"
  # Poll rather than `aws ssm wait command-executed`: the built-in waiter gives up well before a
  # multi-minute step (dnf, a 600 GiB fill) finishes, and reported the still-running command as a
  # failure. SSM_MAX_POLLS * 20s bounds the wait; a 600 GiB fill at the file-path rate fits in the
  # default (120 polls = 40 min).
  local status i
  for ((i=0; i<${SSM_MAX_POLLS:-120}; i++)); do
    status=$(aws ssm get-command-invocation --region "$REGION" --instance-id "$IID" \
      --command-id "$cid" --query 'Status' --output text 2>/dev/null)
    [[ "$status" == Success || "$status" == Failed || "$status" == Cancelled || "$status" == TimedOut ]] && break
    sleep 20
  done
  aws ssm get-command-invocation --region "$REGION" --instance-id "$IID" --command-id "$cid" \
    --query 'StandardOutputContent' --output text
  if [[ "$status" != Success ]]; then
    aws ssm get-command-invocation --region "$REGION" --instance-id "$IID" --command-id "$cid" \
      --query 'StandardErrorContent' --output text >&2
    die "remote command ended ${status:-unknown}"
  fi
}

# ------------------------------------------------------------------------------------------ prepare
prepare() {
  : "${STAGING_BUCKET:?set STAGING_BUCKET (the bucket holding tooling/vdbench.zip)}"
  step "mount S3 Files (helper inserts efs-proxy --tls; mount target is 127.0.0.1)"
  # actimeo is NOT set here: this is a throughput measurement, not a reflection one, and the page
  # cache is bypassed by o_direct in the VDBENCH files instead. nconnect is NOT passed: S3 Files
  # does not support it and the mount hangs if it is requested.
  # botocore is REQUIRED and must come from dnf (pip install fails on this AMI). Without it the
  # mount helper logs "Failed to import botocore" and the NFS mount to the local proxy times out
  # even though efs-proxy connects to the mount target -- the authorization path needs botocore.
  ssm "set -e
    mkdir -p ${MOUNT}
    dnf install -y -q amazon-efs-utils java-17-amazon-corretto-headless python3.12 python3-botocore >/dev/null 2>&1
    mountpoint -q ${MOUNT} || timeout 120 mount -t s3files -o accesspoint=${AP} ${FS}:/ ${MOUNT}
    findmnt -T ${MOUNT} -o FSTYPE,OPTIONS -n"

  step "stage VDBENCH from S3 (Oracle licence blocks a direct download)"
  # vdbench50407.zip unzips into a vdbench50407/ subdirectory. Do NOT symlink the launcher: the
  # vdbench shell script builds its classpath from `dirname $0`, so a symlink resolves the classpath
  # under the symlink's directory and fails with "Could not find or load main class Vdb.Vdbmain"
  # (documented in environments/perf-matrix/README.md). Use a wrapper that execs the real path.
  ssm "set -e
    mkdir -p /opt/bench/parm /opt/bench/gen
    aws s3 cp s3://${STAGING_BUCKET}/tooling/vdbench.zip /tmp/vdbench.zip --region ${REGION}
    rm -rf /opt/vdbench && mkdir -p /opt/vdbench
    (cd /opt/vdbench && unzip -oq /tmp/vdbench.zip)
    vdbin=\$(find /opt/vdbench -maxdepth 2 -name vdbench -type f | head -1)
    [[ -n \"\$vdbin\" ]] || { echo 'vdbench executable not found after unzip'; exit 1; }
    chmod +x \"\$vdbin\"
    printf '#!/usr/bin/env bash\nexec %s \"\$@\"\n' \"\$vdbin\" > /usr/local/bin/vdbench
    chmod +x /usr/local/bin/vdbench
    /usr/local/bin/vdbench -t 2>&1 | tail -3"

  step "non-compressible data generator (zero-fill returns above the ceiling on ONTAP; S3 Files is on EFS, same risk)"
  # AES-CTR over /dev/zero is orders faster than /dev/urandom and gzip-incompressible. The 600 GiB
  # file is written through the S3 Files mount; S3 Files syncs it to the bucket (the ~60 s export
  # window applies to the fill, not to the read). Verify incompressibility on a sample.
  ssm "set -e
    cat > /opt/bench/gen/fill.sh <<'EOF'
#!/usr/bin/env bash
set -e
target=\"\$1\"; size_gib=\"\$2\"
openssl enc -aes-256-ctr -pass pass:s3files-bench -nosalt </dev/zero 2>/dev/null \\
  | head -c \$(( size_gib * 1024 * 1024 * 1024 )) > \"\$target\"
sz=\$(head -c 134217728 \"\$target\" | gzip -c | wc -c)
echo \"gzip of first 128MiB: \$sz bytes (incompressible if ~134217728)\"
EOF
    chmod +x /opt/bench/gen/fill.sh
    echo 'generator ready'"

  step "write the 600 GiB test file onto the S3 Files mount"
  ssm "set -e
    /opt/bench/gen/fill.sh ${MOUNT}/file1 600
    ls -l ${MOUNT}/file1
    echo 'waiting for the export window to drain before measuring'
    sleep 90"
  echo
  echo "prepared. next: ./throughput-runbook.sh s1-s2"
}

# push a parameter file (and its includes) to the host, then run it
run_parm() {
  local parm="$1" out="$2"
  [[ -f "${PARM_SRC}/${parm}" ]] || die "missing ${PARM_SRC}/${parm}"
  local b64
  for f in "$parm" workloads-common.txt; do
    [[ -f "${PARM_SRC}/${f}" ]] || continue
    b64=$(base64 < "${PARM_SRC}/${f}" | tr -d '\n')
    ssm "echo ${b64} | base64 -d > /opt/bench/parm/${f}"
  done
  step "run ${parm} -> ${out}"
  ssm "set -e
    cd /opt/bench/parm
    rm -rf /opt/bench/${out}
    /usr/local/bin/vdbench -f ${parm} -o /opt/bench/${out} 2>&1 | tail -5
    echo '--- totals ---'
    grep -hE 'avg_|Run ' /opt/bench/${out}/totals.html 2>/dev/null | sed 's/<[^>]*>//g' | tail -20 || true"
}

# ------------------------------------------------------------------------------------------- s1-s2
s1_s2() { run_parm vdbench-linux-s3files.txt out-s3files; }

# ------------------------------------------------------------------------------------------- s3
s3_cache() {
  step "S-3: hot (sub-threshold, on high-performance storage) vs cold (threshold lowered, bucket-direct)"
  # Flip the ingest threshold via the sync configuration, hold object size fixed, and read the same
  # 64 KiB object on each side. This isolates PATH from SIZE, the way s3files-measured.md did for
  # latency, but here for throughput. Restore the default afterwards and confirm by API, not output.
  ssm "set -e
    echo 'current sync configuration:'
    aws s3files get-synchronization-configuration --region ${REGION} --file-system-id ${FS} \
      --query '{threshold:sizeLessThan,trigger:trigger,days:daysAfterLastAccess}' --output json
    echo 'lower the threshold so 64 KiB reads bucket-direct (cold path), then measure, then restore'
    echo 'NOTE: threshold/temperature runs are driven interactively — see the plan S-3 section'"
  echo "S-3 is a guided step: the threshold flip and the warm/cold pairing are described in"
  echo "docs/ja/verification/s3files-throughput-matrix-plan.md (S-3). Run s1-s2 first."
}

# --------------------------------------------------------------------------------------- collect
collect() {
  mkdir -p "$RESULTS"
  step "copy VDBENCH reports off the host via S3 (host has no inbound; push to the measurement bucket)"
  ssm "set -e
    cd /opt/bench
    for d in out-s3files out-s3files-ladder; do
      [[ -d \$d ]] && tar -czf /tmp/\$d.tgz \$d && aws s3 cp /tmp/\$d.tgz s3://${BUCKET}/reports/ --region ${REGION} || true
    done
    echo 'uploaded reports to s3://${BUCKET}/reports/'"
  aws s3 sync "s3://${BUCKET}/reports/" "${RESULTS}/" --region "$REGION" || true

  step "CloudWatch AWS/S3/Files during the run (ceiling attribution)"
  # DiskReadBytes vs DataReadBytes tells whether a read came from the bucket or high-performance
  # storage -- the same distinction s3files-measured.md used to catch a "cache, not disk" read.
  local since
  since=$(date -u -v-3H +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || date -u -d '3 hours ago' +%Y-%m-%dT%H:%M:%SZ)
  for m in DataReadBytes MetadataReadBytes DataWriteBytes StorageBytes; do
    printf '  AWS/S3/Files %-20s ' "$m"
    aws cloudwatch get-metric-statistics --region "$REGION" --namespace AWS/S3/Files \
      --metric-name "$m" --dimensions Name=FileSystemId,Value="$FS" \
      --start-time "$since" --end-time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
      --period 300 --statistics Sum Maximum \
      --query 'sort_by(Datapoints,&Timestamp)[-1].[Sum,Maximum]' --output text 2>/dev/null || echo "n/a"
  done
  echo
  echo "reports in ${RESULTS}/. Read totals.html; transcribe into the verification record with the"
  echo "environment attached, and name the ceiling (efs-proxy CPU / EFS quota / ingest path) or 'judged indeterminate'."
}

case "${1:-}" in
  prepare) prepare ;;
  s1-s2) s1_s2 ;;
  s3-cache) s3_cache ;;
  collect) collect ;;
  *) die "usage: $0 {prepare|s1-s2|s3-cache|collect}" ;;
esac
