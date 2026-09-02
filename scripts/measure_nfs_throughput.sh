#!/usr/bin/env bash
# S3 Burst on ONTAP Files - sequential throughput over an NFS mount, at several stream counts.
#
# The companion to scripts/measure_s3_throughput.py, and it exists because that script cannot
# measure this. An S3 API sweep against the bucket an S3 Files file system fronts does not travel
# through S3 Files at all: the bucket is an ordinary bucket, so the sweep compares the FSx for ONTAP
# S3 Access Point against Amazon S3. That is a real comparison and it is the write path both
# architectures share, but the read path in both is a file protocol, and nothing about it is visible
# from the object side. This measures that half.
#
# Scope, stated plainly: this is a coarse sequential check at a few stream counts, not a
# characterisation. It reports what one client obtains for large sequential IO. It does not sweep
# block sizes, does not measure random IO, and does not look for the knee in the curve. A published
# fio study already covers FSx for ONTAP in this Region, so repeating that here would spend real
# money to restate someone else's result.
#
# O_DIRECT is used on both directions. Without it the first read is served from the client page cache
# and reports the speed of local memory, which on a 96 GiB instance looks like a storage result and
# is off by an order of magnitude.
#
# Usage:
#   sudo bash measure_nfs_throughput.sh <mount-path> <label> [gib-per-stream] [streams...]
#
# Example:
#   sudo bash measure_nfs_throughput.sh /mnt/origin-noac "FSx for ONTAP NFS" 1 1 4 8

set -euo pipefail

MOUNT="${1:?usage: measure_nfs_throughput.sh <mount-path> <label> [gib-per-stream] [streams...]}"
LABEL="${2:?a label for the result rows}"
GIB="${3:-1}"
shift 3 2>/dev/null || shift 2
STREAMS=("$@")
if [ ${#STREAMS[@]} -eq 0 ]; then
  STREAMS=(1 4 8)
fi

WORK="${MOUNT}/nfs-throughput-$$"
BLOCK="1M"
COUNT=$((GIB * 1024))

if ! mountpoint -q "$MOUNT"; then
  echo "ERROR: $MOUNT is not a mount point. Refusing to measure a local disk and label it storage." >&2
  exit 1
fi

# Record what is actually mounted. A result whose mount options are unknown cannot be compared with
# another run, and actimeo in particular changes what a read means.
echo "# environment"
echo "mount: $MOUNT"
echo "options: $(findmnt -no OPTIONS "$MOUNT" 2>/dev/null || echo unknown)"
echo "fstype: $(findmnt -no FSTYPE "$MOUNT" 2>/dev/null || echo unknown)"
echo "instance: $(curl -s -X PUT http://169.254.169.254/latest/api/token \
  -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' 2>/dev/null \
  | { read -r t; curl -s -H "X-aws-ec2-metadata-token: $t" \
      http://169.254.169.254/latest/meta-data/instance-type 2>/dev/null; } || echo unknown)"
echo "gib_per_stream: $GIB"
echo "block_size: $BLOCK"
echo "o_direct: yes (both directions)"
echo "measured_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

echo "label,phase,streams,gib_per_stream,total_mb,seconds,throughput_mb_s"

for streams in "${STREAMS[@]}"; do
  # ---- write ----
  for index in $(seq 1 "$streams"); do
    : >"${WORK}/w${index}.bin"
  done
  start=$(date +%s.%N)
  for index in $(seq 1 "$streams"); do
    dd if=/dev/zero of="${WORK}/w${index}.bin" bs="$BLOCK" count="$COUNT" \
      oflag=direct >/dev/null 2>&1 &
  done
  wait
  end=$(date +%s.%N)
  total_mb=$(awk -v c="$COUNT" -v s="$streams" 'BEGIN{printf "%.0f", c*s}')
  awk -v l="$LABEL" -v s="$streams" -v g="$GIB" -v mb="$total_mb" -v a="$start" -v b="$end" \
    'BEGIN{d=b-a; printf "%s,write,%d,%d,%d,%.2f,%.1f\n", l, s, g, mb, d, mb/d}'

  # ---- read ----
  # Same files, read back with O_DIRECT so the page cache is not what answers.
  start=$(date +%s.%N)
  for index in $(seq 1 "$streams"); do
    dd if="${WORK}/w${index}.bin" of=/dev/null bs="$BLOCK" \
      iflag=direct >/dev/null 2>&1 &
  done
  wait
  end=$(date +%s.%N)
  awk -v l="$LABEL" -v s="$streams" -v g="$GIB" -v mb="$total_mb" -v a="$start" -v b="$end" \
    'BEGIN{d=b-a; printf "%s,read,%d,%d,%d,%.2f,%.1f\n", l, s, g, mb, d, mb/d}'

  rm -f "${WORK}"/w*.bin
done
