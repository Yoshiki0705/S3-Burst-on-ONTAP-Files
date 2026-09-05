#!/usr/bin/env bash
#
# The host-count run: 1, 2, 4, 6, 8 clients against one NFS data LIF.
#
# WHAT THIS SETTLES
#
# A single host reached 4,406 MB/s with nconnect=16. Two readings fit that
# number equally well -- the file system is at its ceiling, or the one NFS
# data LIF the SVM has is at its ceiling -- and nothing in a single-host
# measurement separates them, because a single host reaches both through the
# same path. Adding hosts separates them: they all arrive at the same LIF,
# so if the LIF is the limit the total holds still and the per-host share
# falls.
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

    cmd=$(send 900 "${ids[@]}" <<SCRIPT
set -uo pipefail
findmnt -no OPTIONS /mnt/bench/target | grep -q 'nconnect=16' || { echo 'MOUNT NOT AS EXPECTED'; findmnt -no OPTIONS /mnt/bench/target; exit 1; }
rm -rf /opt/bench/out-ladder-${n}
while [ "\$(date +%s)" -lt ${epoch} ]; do sleep 1; done
cd /opt/bench/parm || exit 1
/usr/local/bin/vdbench -f ${PARM} -o /opt/bench/out-ladder-${n} > /var/log/vdbench-ladder-${n}.log 2>&1
echo "rc=\$? host=\$(hostname -s)"
echo "conns=\$(ss -tn state established '( dport = :2049 )' | tail -n +2 | wc -l)"
grep -E 'avg_61-240' /var/log/vdbench-ladder-${n}.log || { echo 'NO AVG LINE'; tail -20 /var/log/vdbench-ladder-${n}.log; }
SCRIPT
)
    wait_cmd "$cmd" 70 || die "point $n did not finish"

    total=0; reported=0
    for id in "${ids[@]}"; do
      out=$(invocation_output "$cmd" "$id")
      line=$(printf '%s\n' "$out" | grep -E 'avg_61-240' | head -1 || true)
      if [[ -z "$line" ]]; then
        printf '  ! %s produced no steady-state line\n' "$id" >&2
        printf '%s\n' "$out" | tail -5 >&2
        continue
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
    printf '  RESULT n=%s total=%s MB/s  per-host=%s MB/s\n' "$n" "$total" "$per_host"
  done
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

case "${1:-}" in
  run)     discover_hosts; shift; cmd_run "$@" ;;
  mounts)  discover_hosts; cmd_mounts ;;
  unmount) discover_hosts; cmd_unmount ;;
  stop)    discover_hosts; cmd_stop ;;
  *)       die 'usage: ladder.sh {run [counts...]|mounts|unmount|stop}' ;;
esac
