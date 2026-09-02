#!/usr/bin/env bash
# =================================================================================================
# UNEXECUTED DRAFT. This script has never been run.
#
# Teardown for the S3 Files comparison environment. The order below is not interchangeable, and the
# reason is the one prerequisite that cannot be turned off: S3 Files requires S3 Versioning, so the
# bucket holds a version chain for every object the measurement wrote and a delete marker for every
# one it deleted. `aws s3 rm --recursive` removes current versions only, leaving the bucket
# non-empty; CloudFormation cannot delete a non-empty bucket, so `delete-stack` runs for several
# minutes and then fails at the last resource — after the file system is already gone.
#
# Nothing here is irreversible in the other direction: no Object Lock, no retention, no vault lock is
# set anywhere in this environment, so every object and every version deletes on request.
#
# What this script does NOT delete, on purpose:
#   - The aws-origin stack, its file system, or its host. They are shared with the other side of the
#     comparison and are not this environment's to remove.
#   - The managed policy attachment this environment asked you to add to the host role. It is
#     printed as a reminder instead, because detaching a policy from a role owned by another stack
#     is the kind of cross-stack mutation that should be a deliberate keystroke.
# =================================================================================================
set -euo pipefail

STACK_NAME="${STACK_NAME:-s3burst-s3files-compare}"
MOUNT_POINT="${MOUNT_POINT:-/mnt/s3files}"
REGION="${AWS_REGION:-ap-northeast-1}"

echo "== 1. Unmount, if this is the measurement host =="
if mountpoint -q "${MOUNT_POINT}" 2>/dev/null; then
  sudo umount "${MOUNT_POINT}"
  echo "unmounted ${MOUNT_POINT}"
else
  echo "nothing mounted at ${MOUNT_POINT} (fine if you are running this from elsewhere)"
fi

echo "== 2. Find the bucket =="
BUCKET="$(aws cloudformation describe-stacks \
  --stack-name "${STACK_NAME}" --region "${REGION}" \
  --query 'Stacks[0].Outputs[?OutputKey==`SourceBucketName`].OutputValue' \
  --output text)"

# An empty or "None" result means the stack or the output is not there. Continuing would empty
# nothing and then report success, so stop instead.
if [[ -z "${BUCKET}" || "${BUCKET}" == "None" ]]; then
  echo "error: could not read SourceBucketName from stack ${STACK_NAME} in ${REGION}." >&2
  echo "       Not proceeding: an unreadable bucket name is not the same as an empty bucket." >&2
  exit 1
fi
echo "bucket: ${BUCKET}"

echo "== 3. Empty every version and delete marker =="
# Two passes, because Versions and DeleteMarkers are separate lists in the same response and a
# bucket with only delete markers left still counts as non-empty. Paginated by the CLI; the loop
# repeats until both lists come back empty rather than assuming one pass is enough.
for pass in 1 2 3 4 5; do
  payload="$(aws s3api list-object-versions \
    --bucket "${BUCKET}" --region "${REGION}" --max-items 1000 \
    --output json \
    --query '{Objects: (Versions[].{Key:Key,VersionId:VersionId} || `[]`)}')"
  markers="$(aws s3api list-object-versions \
    --bucket "${BUCKET}" --region "${REGION}" --max-items 1000 \
    --output json \
    --query '{Objects: (DeleteMarkers[].{Key:Key,VersionId:VersionId} || `[]`)}')"

  versions_left="$(printf '%s' "${payload}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["Objects"] or []))')"
  markers_left="$(printf '%s' "${markers}" | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["Objects"] or []))')"

  if [[ "${versions_left}" == "0" && "${markers_left}" == "0" ]]; then
    echo "pass ${pass}: nothing left"
    break
  fi
  echo "pass ${pass}: ${versions_left} version(s), ${markers_left} delete marker(s)"
  [[ "${versions_left}" != "0" ]] && aws s3api delete-objects \
    --bucket "${BUCKET}" --region "${REGION}" --delete "${payload}" --output text >/dev/null
  [[ "${markers_left}" != "0" ]] && aws s3api delete-objects \
    --bucket "${BUCKET}" --region "${REGION}" --delete "${markers}" --output text >/dev/null
done

echo "== 4. Delete the stack =="
# The file system, its mount target, the mount target's security group, the synchronisation role and
# the now-empty bucket all go with it.
aws cloudformation delete-stack --stack-name "${STACK_NAME}" --region "${REGION}"
aws cloudformation wait stack-delete-complete --stack-name "${STACK_NAME}" --region "${REGION}"

echo "== 5. Confirm, rather than trust the exit status =="
# `delete-stack` returning 0 means the request was accepted. Read the state.
if aws cloudformation describe-stacks --stack-name "${STACK_NAME}" --region "${REGION}" \
    --query 'Stacks[0].StackStatus' --output text 2>/dev/null; then
  echo "warning: the stack is still describable. Check the status printed above." >&2
else
  echo "stack ${STACK_NAME} is gone"
fi

echo
echo "Still attached by hand, and left for you to remove deliberately:"
echo "  aws iam detach-role-policy --role-name <the aws-origin stack's host role> \\"
echo "    --policy-arn arn:aws:iam::aws:policy/AmazonS3FilesClientFullAccess"
echo "  and the inline policy granting s3:GetObject on the bucket that no longer exists"
