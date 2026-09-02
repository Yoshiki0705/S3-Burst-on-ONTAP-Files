#!/usr/bin/env bash
# S3 Burst on ONTAP Files - warm read against cold read over an NFS mount.
#
# This script exists because an earlier attempt to answer the same question was designed wrong, and
# the way it was wrong is worth encoding here so it is not repeated.
#
# That attempt wrote 8 GiB of other data between writing a file and re-reading it, saw no change in
# the read rate, and concluded the figure was not merely a warm-cache artefact. It could not have
# shown that. The published specifications give the in-memory cache on a first-generation Single-AZ
# file system as **16 GB at the 128 MBps step** and 256 GB at the 2048 MBps step, so 8 GiB of
# intervening traffic cannot evict anything at either step. The test had no power to detect what it
# was looking for.
#
# So the eviction volume is a required argument here rather than a default. There is no safe default:
# it depends on the throughput step, which decides the cache size, and getting it wrong produces a
# confident-looking result that means nothing.
#
#   step         in-memory cache    NVMe read cache
#   128 MBps     16 GB              none
#   256 MBps     32 GB              none
#   512 MBps     64 GB              none
#   1024 MBps    128 GB             none
#   2048 MBps    256 GB             present (Single-AZ 1 at 2 GBps and above)
#
# Source: https://docs.aws.amazon.com/fsx/latest/ONTAPGuide/performance.html
# The figures above are for ap-northeast-1 and the other Regions outside the four that get the
# larger tables. Check the page for the Region in use rather than trusting this comment.
#
# O_DIRECT is used throughout, so the client page cache is never what answers. That is a separate
# concern from the server-side cache this script is trying to evict: O_DIRECT removes the client
# from the question, and the eviction volume removes the server.
#
# Usage:
#   sudo bash measure_nfs_cold_read.sh <mount-path> <label> <target-gib> <evict-gib>
#
# Example, on a 128 MBps file system whose cache is 16 GB:
#   sudo bash measure_nfs_cold_read.sh /mnt/origin "FSx for ONTAP 128 MBps" 1 24

set -euo pipefail

MOUNT="${1:?usage: measure_nfs_cold_read.sh <mount-path> <label> <target-gib> <evict-gib>}"
LABEL="${2:?a label for the result rows}"
TARGET_GIB="${3:?size of the file whose read is being measured, in GiB}"
EVICT_GIB="${4:?intervening traffic in GiB. Must exceed the file server cache or the result is void}"

WORK="${MOUNT}/cold-read-$$"

if ! mountpoint -q "$MOUNT"; then
  echo "ERROR: $MOUNT is not a mount point." >&2
  exit 1
fi

echo "# environment"
echo "mount: $MOUNT"
echo "options: $(findmnt -no OPTIONS "$MOUNT" 2>/dev/null || echo unknown)"
echo "fstype: $(findmnt -no FSTYPE "$MOUNT" 2>/dev/null || echo unknown)"
echo "target_gib: $TARGET_GIB"
echo "evict_gib: $EVICT_GIB"
echo "o_direct: yes"
echo "measured_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo

mkdir -p "$WORK"
trap 'rm -rf "$WORK"' EXIT

rate() { # bytes seconds -> MB/s
  awk -v b="$1" -v s="$2" 'BEGIN{printf "%.1f", (b/1000000)/s}'
}

TARGET_BYTES=$((TARGET_GIB * 1024 * 1024 * 1024))

echo "label,phase,gib,seconds,throughput_mb_s,note"

# ---- write the target ----
start=$(date +%s.%N)
dd if=/dev/zero of="${WORK}/target.bin" bs=1M count=$((TARGET_GIB * 1024)) oflag=direct >/dev/null 2>&1
end=$(date +%s.%N)
d=$(awk -v a="$start" -v b="$end" 'BEGIN{print b-a}')
echo "${LABEL},write-target,${TARGET_GIB},$(printf '%.2f' "$d"),$(rate "$TARGET_BYTES" "$d"),the file under test"

# ---- warm read: immediately after writing, so the file server has just seen every block ----
start=$(date +%s.%N)
dd if="${WORK}/target.bin" of=/dev/null bs=1M iflag=direct >/dev/null 2>&1
end=$(date +%s.%N)
d=$(awk -v a="$start" -v b="$end" 'BEGIN{print b-a}')
WARM=$(rate "$TARGET_BYTES" "$d")
echo "${LABEL},read-warm,${TARGET_GIB},$(printf '%.2f' "$d"),${WARM},read straight after the write"

# ---- evict ----
# Written and then read back. A write populates the cache, and reading it back makes the eviction
# pressure match what a reader would produce, which is the case being simulated.
echo "# evicting with ${EVICT_GIB} GiB of other data (write then read)" >&2
for i in $(seq 1 "$EVICT_GIB"); do
  dd if=/dev/zero of="${WORK}/evict-${i}.bin" bs=1M count=1024 oflag=direct >/dev/null 2>&1
done
for i in $(seq 1 "$EVICT_GIB"); do
  dd if="${WORK}/evict-${i}.bin" of=/dev/null bs=1M iflag=direct >/dev/null 2>&1
done
rm -f "${WORK}"/evict-*.bin

# ---- cold read ----
start=$(date +%s.%N)
dd if="${WORK}/target.bin" of=/dev/null bs=1M iflag=direct >/dev/null 2>&1
end=$(date +%s.%N)
d=$(awk -v a="$start" -v b="$end" 'BEGIN{print b-a}')
COLD=$(rate "$TARGET_BYTES" "$d")
echo "${LABEL},read-cold,${TARGET_GIB},$(printf '%.2f' "$d"),${COLD},read after ${EVICT_GIB} GiB of other traffic"

echo
awk -v w="$WARM" -v c="$COLD" 'BEGIN{
  printf "# warm %.1f MB/s, cold %.1f MB/s, ratio %.2fx\n", w, c, (c>0 ? w/c : 0)
  if (c > 0 && w/c < 1.15)
    print "# within 15 percent: on this evidence the earlier figure was not a cache artefact"
  else
    print "# warm is materially faster: the earlier figure was measuring the cache"
}'
