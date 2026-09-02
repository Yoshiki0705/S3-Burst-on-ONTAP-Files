#!/usr/bin/env bash
# =================================================================================================
# THIS SCRIPT has not been run end to end. The mount it performs has: on 2026-09-01 the equivalent
# `mount -t s3files <fs-id>:/ /mnt/s3files` was executed on the measurement host, so the claims below
# are now measured rather than asserted. The script's own error handling and its wait for the mount
# target are what remain unexercised.
#
# It is the S3 Files counterpart of the mount step that scripts/measure_visibility.py performs for
# the ONTAP side (mount_nfs(), nfsvers=3,actimeo=0).
#
# Two differences from that step are not preferences and cannot be configured away:
#
#   1. S3 Files is mounted through a mount helper, as filesystem type `s3files`, not as `nfs`. The
#      helper always adds `tls` and `iam`, and the service does not allow either to be disabled.
#      **Confirmed by measurement.** The resulting data path contains a local process,
#      `efs-proxy --tls` from amazon-efs-utils 3.3.1, listening on 127.0.0.1, and the mount points at
#      that port rather than at the service. The ONTAP side has no equivalent component, and the
#      throughput record attributes the low single-stream figure to it:
#      docs/ja/verification/throughput-iops-concurrency.md
#   2. The protocol version is NFSv4.2 by default (4.1 is also supported); the ONTAP measurement in
#      this repository used NFSv3. So the two sides are NOT mounted with identical options, and no
#      wording in the comparison document should imply they are. What is held identical is the
#      method: one host, one clock, 30 iterations, 64 B objects, concurrency 1.
#      **Confirmed by measurement**: the mount reported `vers=4.2` and `rsize=wsize=1048576`, while
#      the ONTAP side negotiated down to 65536 even when 1048576 was requested explicitly.
#
# Whether `actimeo=0` is honoured by this helper is UNVERIFIED. It is passed below because the
# measurement wants client-side attribute caching out of the way, and the script then prints the
# options that actually took effect — a request is not evidence that the option applied.
# =================================================================================================
set -euo pipefail

FILE_SYSTEM_ID="${FILE_SYSTEM_ID:-fs-0abcdef1234567890}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/s3files}"
# Left empty to mount with the helper's own options only. Set to 0 to ask for attribute caching to
# be disabled, which is what the ONTAP-side measurement did.
ACTIMEO="${ACTIMEO:-0}"

if [[ "${FILE_SYSTEM_ID}" == "fs-0abcdef1234567890" ]]; then
  echo "error: FILE_SYSTEM_ID is still the placeholder." >&2
  echo "       Read it from the stack: aws cloudformation describe-stacks --stack-name <name> \\" >&2
  echo "         --query 'Stacks[0].Outputs[?OutputKey==\`FileSystemId\`].OutputValue' --output text" >&2
  exit 1
fi

echo "== 1. Client =="
# amazon-efs-utils is the client for both Amazon EFS and S3 Files. S3 Files needs 3.0.0 or above;
# an older build mounts EFS correctly and does not know the s3files type at all, which surfaces as
# "unknown filesystem type" rather than as a version complaint.
if ! command -v mount.s3files >/dev/null 2>&1; then
  echo "installing amazon-efs-utils"
  if command -v yum >/dev/null 2>&1; then
    sudo yum -y install amazon-efs-utils
  else
    curl -fsSL https://amazon-efs-utils.aws.com/efs-utils-installer.sh | sudo sh -s -- --install
  fi
fi
# botocore is a separate install and is what the client uses to talk to other AWS services,
# including the CloudWatch metrics for mount status.
python3 -c 'import botocore' 2>/dev/null || sudo python3 -m pip install --quiet botocore

echo "== 2. Mount target state =="
# A mount attempted before the mount target reports available fails in a way that reads like a
# security group problem. The stack reaching CREATE_COMPLETE is a different signal.
aws s3files list-mount-targets \
  --file-system-id "${FILE_SYSTEM_ID}" \
  --query 'mountTargets[].[mountTargetId,status,availabilityZoneId]' \
  --output table

echo "== 3. Mount =="
sudo mkdir -p "${MOUNT_POINT}"
if mountpoint -q "${MOUNT_POINT}"; then
  sudo umount "${MOUNT_POINT}"
fi

if [[ -n "${ACTIMEO}" ]]; then
  sudo mount -t s3files -o "actimeo=${ACTIMEO}" "${FILE_SYSTEM_ID}:/" "${MOUNT_POINT}"
else
  sudo mount -t s3files "${FILE_SYSTEM_ID}:/" "${MOUNT_POINT}"
fi

echo "== 4. What actually took effect =="
# Printed rather than assumed. If actimeo does not appear here, the measurement is running with
# client-side attribute caching on, and the visibility figures include the client's cache expiry
# rather than the service's synchronisation time. That has to be recorded, not worked around.
findmnt -T "${MOUNT_POINT}" -o TARGET,SOURCE,FSTYPE,OPTIONS
df -h "${MOUNT_POINT}"

echo
echo "Mounted at ${MOUNT_POINT}. No /etc/fstab entry was added."
echo "For a persistent mount the entry needs _netdev, and nofail is recommended:"
echo "  ${FILE_SYSTEM_ID}:/ ${MOUNT_POINT} s3files _netdev,nofail 0 0"
echo "Omitting _netdev can leave the instance unresponsive at boot."
