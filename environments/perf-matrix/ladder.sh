#!/usr/bin/env bash
#
# The host-count run: 1, 2, 4, 6, 8 clients against one NFS data LIF.
#
# EXECUTED 2026-09-05. Results in docs/ja/verification/perf-matrix-results.md.
#
# WHAT IT SETTLED, AND HOW IT CAME OUT
#
# A single host reached 4,406 MB/s with nconnect=16. Two readings fit that
# number equally well -- the file system is at its ceiling, or the one NFS
# data LIF the SVM has is at its ceiling -- and nothing in a single-host
# measurement separates them, because a single host reaches both through the
# same path. Adding hosts separates them: they all arrive at the same LIF,
# so if the LIF is the limit the total holds still and the per-host share
# falls.
#
# **The LIF reading was wrong.** Eight hosts put 12,173 MiB/s -- 102 Gbps --
# through that one LIF on that one physical port, with the other node's port
# at zero. The single-host figure was the client's limit, not the storage's.
#
# And then `disjoint` showed the aggregate is not a property of the file
# system either: with the hosts reading regions that do not overlap, the same
# 128 connections carried 2,173 MB/s instead of 11,916. The shared-file
# aggregate was being served from ONTAP's memory. Both numbers are real; they
# answer different questions. Run both, and never publish one alone.
#
# WHY THE HOSTS ARE NOT WIRED TOGETHER
#
# VDBENCH can drive several hosts from one master, but that needs passwordless
# root SSH from the master to every slave. Standing that mesh up means putting
# a root key on nine machines and taking it off again afterwards, and a
# half-removed mesh is a worse artefact to leave behind than a slightly
# harder measurement.
#
# So each host runs its own VDBENCH and the totals are summed here. What makes
# the sum legitimate is that every host waits for a shared wall-clock epoch
# before starting, so the steady windows overlap. SSM dispatch skew is a few
# seconds and the wait absorbs it; the 60-second warmup absorbs what is left.
#
# WHAT IS HELD CONSTANT
#
# Per-host load. Each host offers 64 threads over nconnect=16 whatever the host
# count is, so the only thing that differs between points is how many hosts
# are offering it. Fixing the *total* thread count instead and dividing it by
# the host count would make each point differ in two ways at once, and a
# plateau would again have two candidate causes.
#
# USAGE
#
#   ./ladder.sh run [1 2 4 6 8]     # one point per argument, in order
#   ./ladder.sh mounts              # show the effective mount options everywhere
#   ./ladder.sh unmount             # drop the NFS mounts
#   ./ladder.sh stop                # stop the ladder instances

set -euo pipefail

REGION="${AWS_REGION:-ap-northeast-1}"
PARM="vdbench-linux-nfs-ladder.txt"

NAME_PREFIX="${NAME_PREFIX:-perfmatrix}"

die() { printf 'ladder: %s\n' "$*" >&2; exit 1; }

# Discovered from the Name tag rather than written down here, because a
# tracked file in a public repository is the wrong place for the identifiers
# of somebody's running instances -- and because a hard-coded list goes stale
# the first time the stack is recreated.
#
# Sorted by name, so ladder-1..8 come back in that order every time. Point N
# then uses the first N of them, and the same hosts serve the smaller points:
# a difference between points is not a difference in which machines were used.
discover_hosts() {
  # A read loop rather than `mapfile`, which arrived in bash 4 and so is
  # missing from the bash that ships with macOS.
  local id
  local -a found=()
  # shellcheck disable=SC2016
  while IFS= read -r id; do
    [[ -n "$id" ]] && found+=("$id")
  done < <(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=${NAME_PREFIX}-client-ladder-*" \
              'Name=instance-state-name,Values=running' \
    --query 'sort_by(Reservations[].Instances[], &Tags[?Key==`Name`]|[0].Value)[].InstanceId' \
    --output text | tr '\t' '\n')
  [[ ${#found[@]} -gt 0 ]] || die "no running instances tagged ${NAME_PREFIX}-client-ladder-*"
  HOST_IDS=("${found[@]}")
  printf 'ladder: %s host(s) discovered\n' "${#HOST_IDS[@]}" >&2
}

# Build the SSM parameter JSON in Python. The shorthand --parameters form
# cannot carry these command strings: they contain both quote characters and
# the shorthand parser has no escape for them.
#
# Reads the script from stdin, one command per line.
send() {
  local timeout="$1"; shift
  local -a ids=("$@")
  local json
  json=$(python3 -c '
import json, sys
lines = [ln for ln in sys.stdin.read().split("\n") if ln.strip()]
print(json.dumps({"commands": lines}))
')
  aws ssm send-command --region "$REGION" \
    --instance-ids "${ids[@]}" \
    --document-name AWS-RunShellScript \
    --cli-input-json "{\"Parameters\":$json}" \
    --timeout-seconds "$timeout" \
    --query 'Command.CommandId' --output text
}

wait_cmd() {
  local cmd="$1" limit="$2" i pending
  for ((i = 0; i < limit; i++)); do
    # The backticks are JMESPath literal delimiters, not command substitution,
    # so this expression has to reach the CLI unexpanded.
    # shellcheck disable=SC2016
    pending=$(aws ssm list-command-invocations --region "$REGION" --command-id "$cmd" \
      --query 'length(CommandInvocations[?Status==`InProgress` || Status==`Pending`])' --output text)
    [[ "$pending" == "0" ]] && return 0
    sleep 15
  done
  return 1
}

invocation_output() {
  aws ssm get-command-invocation --region "$REGION" --command-id "$1" \
    --instance-id "$2" --query 'StandardOutputContent' --output text
}

# The client-side sum is not evidence on its own.
#
# At four hosts the sum came to 9,364 MB/s -- above the 6,144 MBps the file
# system is configured for, on a port whose advertised speed is 10 Gbps, and
# with the four hosts agreeing to within 0.02 MB/s. Any of those three alone
# is worth a second look.
#
# Every host reads the same file, which is deliberate: it lets ONTAP serve
# from memory and takes SSD out of the measurement. But it also means one
# read on the server can satisfy four clients, so a client-side sum can count
# bytes that were never sent. The physical port counter cannot: it counts
# frames that actually left.
#
# So each point samples transmit_bytes_per_sec on both nodes' data port while
# the measurement is in its steady window. If the port total tracks the client
# sum, the sum is real. If it is far below, the sum is an artefact and the
# point does not get published as an aggregate.
sample_ontap_port() {
  local epoch="$1"
  [[ -n "${FSXADMIN_SECRET_ARN:-}" ]] || die 'FSXADMIN_SECRET_ARN is not set'
  [[ -n "${GEN2_FS_ID:-}" ]] || die 'GEN2_FS_ID is not set'
  local ONTAP_MGMT_HOST="management.${GEN2_FS_ID}.fsx.${REGION}.amazonaws.com"

  # Two samples of a cumulative counter, differenced. The rate counters that
  # sit beside them (transmit_bytes_per_sec) read zero here, and a counter
  # that reads zero while traffic is flowing is not one to build a check on.
  # A delta over a measured interval needs nothing from the counter but that
  # it keeps counting.
  #
  # Dispatched without waiting, so it runs alongside the measurement.
  send 900 "$SINGLE_CLIENT_ID" <<SCRIPT
set -uo pipefail
PW=\$(aws secretsmanager get-secret-value --region ${REGION} --secret-id '${FSXADMIN_SECRET_ARN}' --query SecretString --output text | python3 -c 'import json,sys;print(json.load(sys.stdin)["password"])')
# Assembled into a variable rather than written as a user:password literal in
# the source. A literal there is what a secret scanner is right to flag, and
# distinguishing "this one interpolates a variable" from "this one does not"
# is not the scanner's job.
CRED="fsxadmin:\${PW}"
fetch() {
  curl -s -k -u "\$CRED" "https://${ONTAP_MGMT_HOST}/api/cluster/counter/tables/\$1/rows?fields=id,counters"
}
# Both samples inside the steady window: warmup ends at epoch+60, the run
# ends at epoch+240.
while [ "\$(date +%s)" -lt \$(( ${epoch} + 75 )) ]; do sleep 1; done
T0=\$(date +%s); fetch nic_common > /tmp/nic0.json; fetch lif > /tmp/lif0.json
sleep 120
T1=\$(date +%s); fetch nic_common > /tmp/nic1.json; fetch lif > /tmp/lif1.json
python3 - "\$T0" "\$T1" <<'PYEOF'
import json, sys

t0, t1 = int(sys.argv[1]), int(sys.argv[2])
dt = t1 - t0

def load(path, counter):
    with open(path) as fh:
        d = json.load(fh)
    out = {}
    for r in d.get("records", []):
        vals = {c.get("name"): c.get("value") for c in r.get("counters", [])}
        v = vals.get(counter)
        if isinstance(v, (int, float)):
            out[r.get("id", "")] = (v, vals.get("svm.name"))
    return out

print(f"sample interval {dt} s")

# Only the physical port. The lif table carries sent_data too, but its rows do
# not come back with an svm label, and two SVMs each have a LIF of the same
# name -- so a per-LIF figure could not be attributed. The port counter needs
# no attribution: it shows which port carried the bytes, and a zero on the
# other node's port is itself the finding.
for label, table, counter, keep in (
    ("physical port", "nic", "transmit_bytes", lambda rid, svm: rid.endswith(":e0e")),
):
    a = load(f"/tmp/{table}0.json", counter)
    b = load(f"/tmp/{table}1.json", counter)
    total = 0.0
    lines = []
    for rid, (v1, svm) in sorted(b.items()):
        if rid not in a or not keep(rid, svm):
            continue
        rate = (v1 - a[rid][0]) / dt / 1048576
        if rate < 1:
            continue
        total += rate
        lines.append(f"      {rid}" + (f" [{svm}]" if svm else "") + f" = {rate:,.1f} MiB/s")
    print(f"  {label} total = {total:,.1f} MiB/s")
    for ln in lines:
        print(ln)
PYEOF
SCRIPT
}

cmd_run() {
  local -a points=("$@")
  [[ ${#points[@]} -gt 0 ]] || points=(1 2 4 6 8)

  local n epoch cmd out line total per_host reported id mb resp
  for n in "${points[@]}"; do
    (( n >= 1 && n <= ${#HOST_IDS[@]} )) || die "host count $n outside 1..${#HOST_IDS[@]}"
    local -a ids=("${HOST_IDS[@]:0:n}")

    # Far enough ahead that every invocation has been dispatched and has
    # reached its wait loop before the epoch arrives.
    epoch=$(( $(date +%s) + 90 ))

    printf '\n=== %s host(s), %s connections offered, start epoch %s\n' \
      "$n" "$(( n * 16 ))" "$epoch"

    local sampler
    sampler=$(sample_ontap_port "$epoch")

    cmd=$(send 900 "${ids[@]}" <<SCRIPT
set -uo pipefail
findmnt -no OPTIONS /mnt/bench/target | grep -q 'nconnect=16' || { echo 'MOUNT NOT AS EXPECTED'; findmnt -no OPTIONS /mnt/bench/target; exit 1; }
rm -rf /opt/bench/out-ladder-${n}
while [ "\$(date +%s)" -lt ${epoch} ]; do sleep 1; done
cd /opt/bench/parm || exit 1
/usr/local/bin/vdbench -f ${PARM} -o /opt/bench/out-ladder-${n} > /var/log/vdbench-ladder-${n}.log 2>&1
echo "rc=\$? host=\$(hostname -s)"
echo "conns=\$(ss -tn state established '( dport = :2049 )' | tail -n +2 | wc -l)"
grep -E 'avg_61-[0-9]+' /var/log/vdbench-ladder-${n}.log || { echo 'NO AVG LINE'; tail -20 /var/log/vdbench-ladder-${n}.log; }
SCRIPT
)
    wait_cmd "$cmd" 70 || die "point $n did not finish"

    total=0; reported=0
    local window=''
    for id in "${ids[@]}"; do
      out=$(invocation_output "$cmd" "$id")
      line=$(printf '%s\n' "$out" | grep -E 'avg_61-[0-9]+' | head -1 || true)
      if [[ -z "$line" ]]; then
        printf '  ! %s produced no steady-state line\n' "$id" >&2
        printf '%s\n' "$out" | tail -5 >&2
        continue
      fi

      # A run that ended early has a shorter window, and a sum over unequal
      # windows is not a sum. Report it rather than averaging it away.
      local this_window
      this_window=$(printf '%s\n' "$line" | grep -oE 'avg_61-[0-9]+' | head -1)
      if [[ -z "$window" ]]; then
        window="$this_window"
      elif [[ "$window" != "$this_window" ]]; then
        printf '  ! %s reported %s, others reported %s -- windows differ\n' \
          "$id" "$this_window" "$window" >&2
      fi
      mb=$(awk '{print $4}' <<<"$line")
      resp=$(awk '{print $7}' <<<"$line")
      total=$(python3 -c "print(f'{$total + $mb:.2f}')")
      reported=$((reported + 1))
      printf '    %-22s %10s MB/s  %9s ms  %s\n' "$id" "$mb" "$resp" \
        "$(printf '%s\n' "$out" | grep -o 'conns=[0-9]*' | head -1)"
    done

    # A point that lost a host is not the point that was asked for. Reporting
    # a sum over fewer hosts as if it were the N-host figure is how a plateau
    # gets invented.
    if [[ "$reported" -ne "$n" ]]; then
      printf '  RESULT n=%s PARTIAL total=%s over %s of %s hosts -- not comparable\n' \
        "$n" "$total" "$reported" "$n"
      continue
    fi

    per_host=$(python3 -c "print(f'{$total / $n:.2f}')")
    printf '  RESULT n=%s window=%s total=%s MB/s  per-host=%s MB/s\n' \
      "$n" "$window" "$total" "$per_host"

    # The server-side check. Printed next to the sum so the two are read
    # together; a sum without it is not reportable as an aggregate.
    if wait_cmd "$sampler" 20; then
      printf '  server-side port counter during the steady window:\n'
      invocation_output "$sampler" "$SINGLE_CLIENT_ID" | sed 's/^/    /'
    else
      printf '  ! the port sampler did not finish -- treat total=%s as unverified\n' "$total"
    fi
  done
}

# The same point, with the hosts reading regions that do not overlap.
#
# WHY IT IS NEEDED
#
# In `run` every host reads the same file, which removes SSD from the
# measurement on purpose. It also means one read on the server can satisfy
# every client, so the aggregate could be largely memory-served and would then
# say little about what the storage can deliver. The port counter proves the
# bytes were sent; it cannot say where they came from.
#
# Here each host gets its own slice of the file, so no block is shared. The
# working set is the whole 600 GB against 256 GB of read cache, so at most
# about 43% of it can be resident. The difference between this aggregate and
# the shared-file one bounds how much the sharing was worth.
#
# Each host computes its own slice from its instance ID's position in the
# list, so this is still a single dispatch and the hosts still start together.
cmd_run_disjoint() {
  local n="${1:-${#HOST_IDS[@]}}"
  (( n >= 1 && n <= ${#HOST_IDS[@]} )) || die "host count $n outside 1..${#HOST_IDS[@]}"
  local -a ids=("${HOST_IDS[@]:0:n}")
  local id_list epoch cmd out line total reported id mb resp
  id_list=$(printf '%s ' "${ids[@]}")
  epoch=$(( $(date +%s) + 90 ))

  printf '\n=== %s host(s), disjoint ranges, %s connections offered, start epoch %s\n' \
    "$n" "$(( n * 16 ))" "$epoch"

  local sampler
  sampler=$(sample_ontap_port "$epoch")

  cmd=$(send 900 "${ids[@]}" <<SCRIPT
set -uo pipefail
findmnt -no OPTIONS /mnt/bench/target | grep -q 'nconnect=16' || { echo 'MOUNT NOT AS EXPECTED'; exit 1; }
TOK=\$(curl -s -X PUT 'http://169.254.169.254/latest/api/token' -H 'X-aws-ec2-metadata-token-ttl-seconds: 60')
ME=\$(curl -s -H "X-aws-ec2-metadata-token: \$TOK" 'http://169.254.169.254/latest/meta-data/instance-id')
IDX=-1; i=0
for h in ${id_list}; do [ "\$h" = "\$ME" ] && IDX=\$i; i=\$((i+1)); done
[ "\$IDX" -ge 0 ] || { echo "ABORT: \$ME not in the dispatch list"; exit 1; }
SPAN=\$(python3 -c "print(f'{100/${n}:.4f}')")
LO=\$(python3 -c "print(f'{\$IDX * \$SPAN:.4f}')")
HI=\$(python3 -c "print(f'{(\$IDX + 1) * \$SPAN:.4f}')")
echo "host=\$(hostname -s) idx=\$IDX range=(\$LO,\$HI)"
sed "s|^sd=sd1-1,host=hd1,lun=/mnt/bench/target/file1\$|sd=sd1-1,host=hd1,lun=/mnt/bench/target/file1,range=(\$LO,\$HI)|" \
  /opt/bench/parm/${PARM} > /opt/bench/parm/ladder-disjoint.txt
grep -q 'range=(' /opt/bench/parm/ladder-disjoint.txt || { echo 'ABORT: range not injected'; grep '^sd=' /opt/bench/parm/ladder-disjoint.txt; exit 1; }
grep '^sd=sd1-1' /opt/bench/parm/ladder-disjoint.txt
rm -rf /opt/bench/out-disjoint-${n}
while [ "\$(date +%s)" -lt ${epoch} ]; do sleep 1; done
cd /opt/bench/parm || exit 1
/usr/local/bin/vdbench -f ladder-disjoint.txt -o /opt/bench/out-disjoint-${n} > /var/log/vdbench-disjoint-${n}.log 2>&1
echo "rc=\$?"
grep -E 'avg_61-[0-9]+' /var/log/vdbench-disjoint-${n}.log || { echo 'NO AVG LINE'; tail -20 /var/log/vdbench-disjoint-${n}.log; }
SCRIPT
)
  wait_cmd "$cmd" 70 || die "disjoint point $n did not finish"

  total=0; reported=0
  for id in "${ids[@]}"; do
    out=$(invocation_output "$cmd" "$id")
    line=$(printf '%s\n' "$out" | grep -E 'avg_61-[0-9]+' | head -1 || true)
    if [[ -z "$line" ]]; then
      printf '  ! %s produced no steady-state line\n' "$id" >&2
      printf '%s\n' "$out" | tail -6 >&2
      continue
    fi
    mb=$(awk '{print $4}' <<<"$line")
    resp=$(awk '{print $7}' <<<"$line")
    total=$(python3 -c "print(f'{$total + $mb:.2f}')")
    reported=$((reported + 1))
    printf '    %-22s %10s MB/s  %9s ms  %s\n' "$id" "$mb" "$resp" \
      "$(printf '%s\n' "$out" | grep -oE 'range=\([0-9.]+,[0-9.]+\)' | head -1)"
  done

  if [[ "$reported" -ne "$n" ]]; then
    printf '  RESULT disjoint n=%s PARTIAL total=%s over %s of %s -- not comparable\n' \
      "$n" "$total" "$reported" "$n"
    return
  fi
  printf '  RESULT disjoint n=%s total=%s MB/s  per-host=%s MB/s\n' \
    "$n" "$total" "$(python3 -c "print(f'{$total / $n:.2f}')")"
  if wait_cmd "$sampler" 20; then
    printf '  server-side port counter during the steady window:\n'
    invocation_output "$sampler" "$SINGLE_CLIENT_ID" | sed 's/^/    /'
  else
    printf '  ! the port sampler did not finish -- treat total=%s as unverified\n' "$total"
  fi
}

cmd_mounts() {
  local cmd id
  cmd=$(send 300 "${HOST_IDS[@]}" <<'SCRIPT'
echo "host=$(hostname -s)"
findmnt -no SOURCE,OPTIONS /mnt/bench/target 2>/dev/null || echo "not mounted"
echo "conns=$(ss -tn state established '( dport = :2049 )' | tail -n +2 | wc -l)"
SCRIPT
)
  wait_cmd "$cmd" 20 || die 'mount check did not finish'
  for id in "${HOST_IDS[@]}"; do
    printf '=== %s\n' "$id"
    invocation_output "$cmd" "$id"
  done
}

cmd_unmount() {
  local cmd
  cmd=$(send 300 "${HOST_IDS[@]}" <<'SCRIPT'
umount -f /mnt/bench/target 2>/dev/null || true
findmnt -no OPTIONS /mnt/bench/target >/dev/null && echo "STILL MOUNTED" || echo "unmounted"
SCRIPT
)
  wait_cmd "$cmd" 20 || die 'unmount did not finish'
  printf 'unmount requested on %s hosts\n' "${#HOST_IDS[@]}"
}

cmd_stop() {
  aws ec2 stop-instances --region "$REGION" --instance-ids "${HOST_IDS[@]}" \
    --query 'StoppingInstances[].{Id:InstanceId,S:CurrentState.Name}' --output text
}

declare -a HOST_IDS=()
SINGLE_CLIENT_ID=''

# The single client is not part of the ladder. It is used only to reach the
# ONTAP management endpoint, because the endpoint is inside the VPC and this
# script runs outside it.
discover_single_client() {
  SINGLE_CLIENT_ID=$(aws ec2 describe-instances --region "$REGION" \
    --filters "Name=tag:Name,Values=${NAME_PREFIX}-client-single" \
              'Name=instance-state-name,Values=running' \
    --query 'Reservations[0].Instances[0].InstanceId' --output text)
  [[ -n "$SINGLE_CLIENT_ID" && "$SINGLE_CLIENT_ID" != "None" ]] \
    || die "no running instance tagged ${NAME_PREFIX}-client-single to reach the ONTAP endpoint from"
}

case "${1:-}" in
  run)     discover_hosts; discover_single_client; shift; cmd_run "$@" ;;
  disjoint) discover_hosts; discover_single_client; shift; cmd_run_disjoint "$@" ;;
  mounts)  discover_hosts; cmd_mounts ;;
  unmount) discover_hosts; cmd_unmount ;;
  stop)    discover_hosts; cmd_stop ;;
  *)       die 'usage: ladder.sh {run [counts...]|disjoint [count]|mounts|unmount|stop}' ;;
esac
