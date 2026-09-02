#!/usr/bin/env python3
"""S3 Burst on ONTAP Files — Amazon S3 Files semantics: delete, overwrite, multipart, conflict, route.

Closes the questions `measure_s3files_visibility.py` left in its "read nothing into this" list. That
script measures how long a change takes to become visible; this one measures what the change looks
like when it arrives, and whether a documented behaviour actually happens.

Seven questions, each paired with a control that must hold in the same run. A negative result
without a control can record a mistake in the procedure rather than a property of the target, which
is why every "it did not appear" here sits next to an "and this did appear".

  1. Delete, S3 -> file        DeleteObject, then wait for the file to disappear from the mount
  2. Delete, file -> S3        unlink on the mount, then wait for HeadObject to 404
  3. Overwrite, S3 -> file     PutObject v2 over v1, then wait for the mount to show v2
  4. Overwrite, file -> S3     write v2 on the mount, then wait for S3 to return v2
  5. Multipart visibility      is a partially uploaded object visible as a file before Complete?
  6. Conflict                  change the same key through both paths; who wins, and what moves to
                               .s3files-lost+found-<file-system-id>
  7. Route separation          read latency at ONE object size with the import threshold flipped, so
                               the size is constant and only the storage layer changes. The earlier
                               measurement compared 64 KiB against 4 MiB, which varies size and
                               route together and cannot attribute the difference to either.

Question 7 mutates the file system's synchronisation configuration and restores it at the end.

Usage:
  python3.12 scripts/measure_s3files_semantics.py \
    --file-system-id fs-0123456789abcdef0 \
    --bucket <bucket> \
    --mount-point /mnt/s3files --key-prefix measure/ \
    [--root-mount /mnt/s3files-root] \
    [--iterations 10] [--route-iterations 30] [--fixed-size 65536] \
    [--timeout 300] [--poll-interval 0.5] \
    [--output semantics.json] [--keep]

`--root-mount` is the file system mounted WITHOUT an access point. The lost-and-found directory
lives at the file system root, is mode 0700 root-owned, and is therefore invisible through an access
point rooted at a subdirectory. Reading it needs s3files:ClientRootAccess on the client role. Omit
the flag and question 6 falls back to the CloudWatch LostAndFoundFiles counter, which is weaker
evidence but needs no root bypass.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from measure_s3files_visibility import (
    TIMED_OUT,
    mount_path,
    poll_until,
    read_mount_options,
    summarise,
)

# UploadPart requires at least 5 MiB for any part that is not the last one, so a smaller first part
# would fail for a reason that has nothing to do with visibility.
PART_BYTES = 6 * 1024 * 1024


class Outcome:
    """Named yes/no results, so the report can state what held and what did not."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def record(
        self, check: str, expectation: str, held: bool, detail: str = ""
    ) -> bool:
        self.results.append(
            {
                "check": check,
                "expectation": expectation,
                "held": held,
                "detail": detail,
            }
        )
        mark = "OK  " if held else "FAIL"
        print(f"  {mark} {check}" + (f" -> {detail}" if detail else ""))
        return held


def wait_visible(path: Path, size: int, args) -> bool:
    return (
        poll_until(
            lambda: path.exists() and path.stat().st_size == size,
            args.timeout,
            args.poll_interval,
        )
        is not TIMED_OUT
    )


def wait_in_s3(s3, bucket: str, key: str, size: int, args) -> bool:
    def check():
        return s3.head_object(Bucket=bucket, Key=key)["ContentLength"] == size

    return poll_until(check, args.timeout, args.poll_interval) is not TIMED_OUT


# ------------------------------------------------------------------------------ 1 & 2: deletion
def delete_s3_to_file(s3, bucket, mount, prefix, args, outcome) -> dict:
    """DeleteObject, then time the file disappearing from the mount."""
    print(f"\n1. Delete, S3 -> file ({args.iterations} iterations)")
    body = b"d" * args.object_size
    samples: list = []
    for index in range(args.iterations):
        key = f"{prefix}/del-s3/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount, key, args.key_prefix)
        s3.put_object(Bucket=bucket, Key=key, Body=body)
        if not wait_visible(path, args.object_size, args):
            samples.append(TIMED_OUT)
            continue
        s3.delete_object(Bucket=bucket, Key=key)
        samples.append(
            poll_until(lambda p=path: not p.exists(), args.timeout, args.poll_interval)
        )
    stats = summarise(samples)
    outcome.record(
        "a deleted object disappears from the mount",
        "the file goes away",
        stats["n"] > 0 and stats["timeouts"] == 0,
        f"p50 {stats['p50']} ms, timeouts {stats['timeouts']}",
    )
    return stats


def delete_file_to_s3(s3, bucket, mount, prefix, args, outcome) -> dict:
    """unlink on the mount, then time HeadObject starting to 404."""
    print(f"\n2. Delete, file -> S3 ({args.iterations} iterations)")
    body = b"d" * args.object_size
    directory = mount_path(mount, f"{prefix}/del-file", args.key_prefix)
    directory.mkdir(parents=True, exist_ok=True)
    samples: list = []
    for index in range(args.iterations):
        key = f"{prefix}/del-file/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount, key, args.key_prefix)
        path.write_bytes(body)
        os.chmod(path, 0o644)
        if not wait_in_s3(s3, bucket, key, args.object_size, args):
            samples.append(TIMED_OUT)
            continue
        path.unlink()

        def gone(k=key):
            try:
                s3.head_object(Bucket=bucket, Key=k)
            except ClientError as exc:
                return exc.response["ResponseMetadata"]["HTTPStatusCode"] == 404
            return False

        samples.append(poll_until(gone, args.timeout, args.poll_interval))
    stats = summarise(samples)
    outcome.record(
        "a file deleted on the mount stops being returned by HeadObject",
        "a delete marker becomes the current version",
        stats["n"] > 0 and stats["timeouts"] == 0,
        f"p50 {stats['p50']} ms, timeouts {stats['timeouts']}",
    )
    return stats


# ----------------------------------------------------------------------------- 3 & 4: overwrite
def overwrite_s3_to_file(s3, bucket, mount, prefix, args, outcome) -> dict:
    """PutObject over an existing key, then time the mount showing the new content."""
    print(f"\n3. Overwrite, S3 -> file ({args.iterations} iterations)")
    v1 = b"1" * args.object_size
    v2 = b"2" * (args.object_size * 2)
    samples: list = []
    for index in range(args.iterations):
        key = f"{prefix}/ow-s3/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount, key, args.key_prefix)
        s3.put_object(Bucket=bucket, Key=key, Body=v1)
        if not wait_visible(path, args.object_size, args):
            samples.append(TIMED_OUT)
            continue
        s3.put_object(Bucket=bucket, Key=key, Body=v2)
        # Waiting on the content, not just the size, so a partially updated file cannot pass.
        samples.append(
            poll_until(
                lambda p=path: p.read_bytes() == v2, args.timeout, args.poll_interval
            )
        )
    stats = summarise(samples)
    outcome.record(
        "an overwritten object reaches the mount with the new content",
        "the file shows v2, never a mixture",
        stats["n"] > 0 and stats["timeouts"] == 0,
        f"p50 {stats['p50']} ms, timeouts {stats['timeouts']}",
    )
    return stats


def overwrite_file_to_s3(s3, bucket, mount, prefix, args, outcome) -> dict:
    """Rewrite a file on the mount, then time S3 returning the new bytes."""
    print(f"\n4. Overwrite, file -> S3 ({args.iterations} iterations)")
    v1 = b"1" * args.object_size
    v2 = b"2" * (args.object_size * 2)
    directory = mount_path(mount, f"{prefix}/ow-file", args.key_prefix)
    directory.mkdir(parents=True, exist_ok=True)
    samples: list = []
    versions: list[int] = []
    for index in range(args.iterations):
        key = f"{prefix}/ow-file/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount, key, args.key_prefix)
        path.write_bytes(v1)
        os.chmod(path, 0o644)
        if not wait_in_s3(s3, bucket, key, args.object_size, args):
            samples.append(TIMED_OUT)
            continue
        path.write_bytes(v2)

        def updated(k=key):
            return s3.get_object(Bucket=bucket, Key=k)["Body"].read() == v2

        samples.append(poll_until(updated, args.timeout, args.poll_interval))
        # How many object versions the two writes produced. The batching window is meant to
        # consolidate rapid successive writes into one version; here the writes are minutes apart,
        # so two is the expected answer and one would mean something else happened.
        listed = s3.list_object_versions(Bucket=bucket, Prefix=key).get("Versions", [])
        versions.append(len(listed))
    stats = summarise(samples, {"object_versions_per_key": versions})
    outcome.record(
        "a rewritten file reaches S3 with the new content",
        "GetObject returns v2",
        stats["n"] > 0 and stats["timeouts"] == 0,
        f"p50 {stats['p50']} ms, versions per key {sorted(set(versions))}",
    )
    return stats


# ------------------------------------------------------------------------- 5: multipart upload
def multipart_visibility(s3, bucket, mount, prefix, args, outcome) -> dict:
    """Is a partially uploaded multipart object visible as a file before CompleteMultipartUpload?

    The same question was answered for this repository's own architecture (it is not visible until
    Complete). Asking it here is what makes the two comparable.
    """
    print("\n5. Multipart visibility")
    observations = []
    for index in range(args.multipart_iterations):
        key = f"{prefix}/mpu/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount, key, args.key_prefix)
        upload = s3.create_multipart_upload(Bucket=bucket, Key=key)["UploadId"]
        part = s3.upload_part(
            Bucket=bucket,
            Key=key,
            UploadId=upload,
            PartNumber=1,
            Body=b"m" * PART_BYTES,
        )
        # Give the import path a fair chance to show something before concluding it shows nothing.
        time.sleep(args.multipart_settle)
        mid = path.exists()
        mid_size = path.stat().st_size if mid else 0
        s3.complete_multipart_upload(
            Bucket=bucket,
            Key=key,
            UploadId=upload,
            MultipartUpload={"Parts": [{"ETag": part["ETag"], "PartNumber": 1}]},
        )
        after = wait_visible(path, PART_BYTES, args)
        observations.append(
            {
                "visible_before_complete": mid,
                "size_before_complete": mid_size,
                "visible_after_complete": after,
                "settle_seconds": args.multipart_settle,
            }
        )
    invisible_before = all(not o["visible_before_complete"] for o in observations)
    visible_after = all(o["visible_after_complete"] for o in observations)
    outcome.record(
        "a partially uploaded multipart object is NOT visible as a file",
        f"invisible until Complete, checked {args.multipart_settle}s after the part",
        invisible_before,
        f"{sum(not o['visible_before_complete'] for o in observations)}/{len(observations)} invisible",
    )
    outcome.record(
        "control: the same object IS visible after CompleteMultipartUpload",
        "so the check above is not merely a broken path",
        visible_after,
        f"{sum(o['visible_after_complete'] for o in observations)}/{len(observations)} visible",
    )
    return {"observations": observations, "part_bytes": PART_BYTES}


# --------------------------------------------------------------------------------- 6: conflict
def conflict(s3, bucket, mount, prefix, args, outcome) -> dict:
    """Change the same key through both paths inside one batching window and see who wins.

    The documentation says the bucket is authoritative and the file system's version is moved to
    lost and found. Both halves are checked: the surviving content, and the arrival of a file in
    .s3files-lost+found-<file-system-id>.
    """
    print("\n6. Conflict between a file write and an S3 write")
    from_file = b"F" * 4096
    from_s3 = b"S" * 8192
    directory = mount_path(mount, f"{prefix}/conflict", args.key_prefix)
    directory.mkdir(parents=True, exist_ok=True)
    lost_before = lost_dir_count(args)
    observations = []
    for index in range(args.conflict_iterations):
        key = f"{prefix}/conflict/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount, key, args.key_prefix)
        path.write_bytes(from_file)
        os.chmod(path, 0o644)
        # Deliberately inside the export window: the file-side write has not reached the bucket yet.
        time.sleep(args.conflict_gap)
        s3.put_object(Bucket=bucket, Key=key, Body=from_s3)
        deadline = time.time() + args.timeout
        winner, size = "undetermined", 0
        while time.time() < deadline:
            try:
                current = path.read_bytes()
            except (OSError, PermissionError):
                time.sleep(args.poll_interval)
                continue
            if current == from_s3:
                winner, size = "s3", len(current)
                break
            time.sleep(args.poll_interval)
        else:
            try:
                size = path.stat().st_size
            except OSError:
                size = 0
            winner = "file-side survived or undetermined"
        observations.append(
            {"winner": winner, "size": size, "gap_seconds": args.conflict_gap}
        )
    lost_after = lost_dir_count(args)
    s3_won = all(o["winner"] == "s3" for o in observations)
    outcome.record(
        "the bucket is authoritative when both sides change one key",
        "the mount ends up showing the S3-written content",
        s3_won,
        f"{sum(o['winner'] == 's3' for o in observations)}/{len(observations)} resolved to S3",
    )
    if lost_before is not None and lost_after is not None:
        outcome.record(
            "the file-side version is moved to lost and found",
            "the lost-and-found directory gains an entry",
            lost_after > lost_before,
            f"{lost_before} -> {lost_after} entries",
        )
    else:
        print(
            "  SKIP lost-and-found inspection: no --root-mount given. It lives at the file system\n"
            "       root, is 0700 root-owned, and needs s3files:ClientRootAccess to read.\n"
            "       Use the CloudWatch LostAndFoundFiles counter instead."
        )
    return {
        "observations": observations,
        "lost_and_found_before": lost_before,
        "lost_and_found_after": lost_after,
    }


def lost_dir_count(args) -> int | None:
    if not args.root_mount:
        return None
    root = Path(args.root_mount)
    candidates = [p for p in root.glob(".s3files-lost+found-*") if p.is_dir()]
    if not candidates:
        return None
    try:
        return sum(1 for _ in candidates[0].rglob("*"))
    except (OSError, PermissionError):
        return None


# -------------------------------------------------------------------------- 7: route separation
def route_separation(s3files, s3, bucket, mount, prefix, args, outcome) -> dict:
    """Read latency at ONE size, with the import threshold flipped between the two passes.

    The earlier run compared 64 KiB against 4 MiB and found a 3.8x difference it could not
    attribute: object size and storage layer changed together. Here the size is fixed and only
    `sizeLessThan` moves, so whatever difference remains belongs to the route.
    """
    print(
        f"\n7. Route separation at a fixed {args.fixed_size} B ({args.route_iterations} each)"
    )
    original = s3files.get_synchronization_configuration(
        fileSystemId=args.file_system_id
    )
    results = {}

    def set_threshold(threshold: int) -> None:
        current = s3files.get_synchronization_configuration(
            fileSystemId=args.file_system_id
        )
        s3files.put_synchronization_configuration(
            fileSystemId=args.file_system_id,
            latestVersionNumber=current["latestVersionNumber"],
            importDataRules=[
                {
                    "prefix": "",
                    "trigger": "ON_DIRECTORY_FIRST_ACCESS",
                    "sizeLessThan": threshold,
                }
            ],
            expirationDataRules=current["expirationDataRules"],
        )

    try:
        for label, threshold in (
            (
                "resident",
                args.fixed_size * 2,
            ),  # size < threshold -> imported to high-perf storage
            ("streamed", 1024),  # size > threshold -> served from the bucket
        ):
            set_threshold(threshold)
            time.sleep(args.route_settle)
            keys = []
            for index in range(args.route_iterations):
                key = f"{prefix}/route-{label}/{index:03d}.bin"
                s3.put_object(Bucket=bucket, Key=key, Body=b"r" * args.fixed_size)
                keys.append(key)
            last = mount_path(mount, keys[-1], args.key_prefix)
            if not wait_visible(last, args.fixed_size, args):
                results[label] = {
                    "error": "objects never became visible",
                    "threshold": threshold,
                }
                continue
            directory = mount_path(mount, f"{prefix}/route-{label}", args.key_prefix)
            list(directory.iterdir())  # first-access metadata import, untimed
            mount_path(
                mount, keys[0], args.key_prefix
            ).read_bytes()  # warm-up, discarded
            samples: list = []
            for key in keys:
                path = mount_path(mount, key, args.key_prefix)
                start = time.perf_counter()
                data = path.read_bytes()
                samples.append((time.perf_counter() - start) * 1000)
                if len(data) != args.fixed_size:
                    samples[-1] = TIMED_OUT
            results[label] = summarise(
                samples,
                {"threshold_bytes": threshold, "object_size_bytes": args.fixed_size},
            )
            print(
                f"    {label:9s} threshold {threshold:>8} B  p50 {results[label]['p50']:8.1f} ms"
                f"  p90 {results[label]['p90']:8.1f} ms  n={results[label]['n']}"
            )
    finally:
        # Deliberately swallowing here. The first version let this raise, and when the client role
        # lacked PutSynchronizationConfiguration the restore failed too -- producing a second
        # traceback for the same AccessDenied that hid which call had failed first.
        try:
            s3files.put_synchronization_configuration(
                fileSystemId=args.file_system_id,
                latestVersionNumber=s3files.get_synchronization_configuration(
                    fileSystemId=args.file_system_id
                )["latestVersionNumber"],
                importDataRules=original["importDataRules"],
                expirationDataRules=original["expirationDataRules"],
            )
            print("    synchronisation configuration restored")
        except ClientError as exc:
            print(
                f"    WARNING: could not restore the synchronisation configuration: "
                f"{exc.response.get('Error', {}).get('Code')}. "
                f"Expected importDataRules {original['importDataRules']}",
                file=sys.stderr,
            )

    both = all(isinstance(v, dict) and "p50" in v for v in results.values())
    if both:
        outcome.record(
            "the storage layer alone changes read latency at a fixed object size",
            "the two passes differ while the size is held constant",
            results["resident"]["p50"] != results["streamed"]["p50"],
            f"resident p50 {results['resident']['p50']} ms vs streamed p50 {results['streamed']['p50']} ms",
        )
    return results


def delete_prefix(s3, bucket: str, prefix: str) -> int:
    deleted = 0
    for page in s3.get_paginator("list_object_versions").paginate(
        Bucket=bucket, Prefix=prefix
    ):
        entries = [
            {"Key": i["Key"], "VersionId": i["VersionId"]}
            for group in ("Versions", "DeleteMarkers")
            for i in page.get(group, [])
        ]
        for start in range(0, len(entries), 1000):
            batch = entries[start : start + 1000]
            s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            deleted += len(batch)
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--file-system-id", required=True)
    parser.add_argument("--bucket", required=True)
    parser.add_argument("--mount-point", default="/mnt/s3files")
    parser.add_argument(
        "--root-mount",
        default="",
        help="the file system mounted without an access point, for lost-and-found inspection",
    )
    parser.add_argument("--key-prefix", default="")
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--iterations", type=int, default=10)
    parser.add_argument("--multipart-iterations", type=int, default=3)
    parser.add_argument("--conflict-iterations", type=int, default=3)
    parser.add_argument("--route-iterations", type=int, default=30)
    parser.add_argument("--object-size", type=int, default=64)
    parser.add_argument(
        "--fixed-size",
        type=int,
        default=65536,
        help="the one size used for question 7; must be below 1 MiB or the route never changes",
    )
    parser.add_argument("--timeout", type=float, default=300.0)
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument(
        "--multipart-settle",
        type=float,
        default=20.0,
        help="seconds to wait after the part before concluding it is not visible",
    )
    parser.add_argument(
        "--conflict-gap",
        type=float,
        default=5.0,
        help="seconds between the file write and the S3 write; keep it inside the export window",
    )
    parser.add_argument("--route-settle", type=float, default=15.0)
    parser.add_argument(
        "--only",
        default="",
        help=(
            "comma-separated subset of: delete-s3, delete-file, overwrite-s3, overwrite-file, "
            "multipart, conflict, route. Default runs all seven. Questions 2 and 4 wait on the "
            "~60 s export window ten times each, so re-running one question beats re-running all"
        ),
    )
    parser.add_argument("--prefix", default="measure/s3files-semantics")
    parser.add_argument("--output")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    if args.fixed_size >= 1024 * 1024:
        print(
            f"error: --fixed-size {args.fixed_size} is at least 1 MiB. Reads of 1 MiB or more are "
            "served from the bucket whatever the threshold is, so flipping it changes nothing and "
            "question 7 would compare a route against itself.",
            file=sys.stderr,
        )
        return 1

    mount = read_mount_options(args.mount_point)
    if mount["fstype"] not in {"nfs4", "nfs", "s3files"}:
        print(
            f"error: {args.mount_point} is not an NFS mount ({mount['fstype']!r})",
            file=sys.stderr,
        )
        return 1

    s3 = boto3.client(
        "s3",
        region_name=args.region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )
    s3files = boto3.client("s3files", region_name=args.region)

    environment = {
        "measured_at": datetime.now(UTC).isoformat(),
        "region": args.region,
        "file_system_id": args.file_system_id,
        "mount_point": args.mount_point,
        "root_mount": args.root_mount or "(not mounted)",
        "key_prefix": args.key_prefix,
        "mount_options_effective": mount["options"],
        "synchronization_configuration_at_start": s3files.get_synchronization_configuration(
            fileSystemId=args.file_system_id
        ),
    }
    print("Environment")
    for key, value in environment.items():
        print(f"  {key}: {value}")

    run_prefix = f"{args.prefix}/{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    # Created over NFS first: a directory materialised from an S3 write is owned by root, and the
    # access point's POSIX identity cannot then create anything inside it.
    mount_path(args.mount_point, run_prefix, args.key_prefix).mkdir(
        parents=True, exist_ok=True
    )
    print(f"\nMeasuring under {run_prefix}/")

    outcome = Outcome()
    common = (s3, args.bucket, args.mount_point, run_prefix, args, outcome)
    # Registered rather than called inline so --only can select a subset. Questions 2 and 4 each
    # wait on the ~60 s export window ten times, so re-running one question costs minutes where
    # re-running the suite costs the better part of an hour.
    phases: dict[str, tuple[str, object]] = {
        "delete-s3": ("delete_s3_to_file", lambda: delete_s3_to_file(*common)),
        "delete-file": ("delete_file_to_s3", lambda: delete_file_to_s3(*common)),
        "overwrite-s3": ("overwrite_s3_to_file", lambda: overwrite_s3_to_file(*common)),
        "overwrite-file": (
            "overwrite_file_to_s3",
            lambda: overwrite_file_to_s3(*common),
        ),
        "multipart": ("multipart_visibility", lambda: multipart_visibility(*common)),
        "conflict": ("conflict", lambda: conflict(*common)),
        "route": (
            "route_separation",
            lambda: route_separation(
                s3files, s3, args.bucket, args.mount_point, run_prefix, args, outcome
            ),
        ),
    }
    wanted = {name.strip() for name in args.only.split(",") if name.strip()}
    unknown = wanted - set(phases)
    if unknown:
        print(
            f"error: unknown --only value(s) {sorted(unknown)}; "
            f"choose from {sorted(phases)}",
            file=sys.stderr,
        )
        return 1
    selected = [name for name in phases if not wanted or name in wanted]
    print(f"phases to run: {', '.join(selected)}")
    results = {phases[name][0]: phases[name][1]() for name in selected}

    print("\nLatency summary (ms)")
    for name, stats in results.items():
        if isinstance(stats, dict) and "p50" in stats:
            print(
                f"  {name:24s} p50 {stats['p50']:9.1f}  p90 {stats['p90']:9.1f}  "
                f"max {stats['max']:9.1f}  n={stats['n']}  timeouts={stats['timeouts']}"
            )

    if args.keep:
        print(f"\n--keep given; objects left under {args.prefix}/")
    else:
        print(
            f"\nCleanup: removed {delete_prefix(s3, args.bucket, args.prefix)} version(s)"
        )

    report = {
        "environment": environment,
        "method": {
            "iterations": args.iterations,
            "multipart_iterations": args.multipart_iterations,
            "conflict_iterations": args.conflict_iterations,
            "route_iterations": args.route_iterations,
            "object_size_bytes": args.object_size,
            "fixed_size_bytes": args.fixed_size,
            "multipart_settle_seconds": args.multipart_settle,
            "conflict_gap_seconds": args.conflict_gap,
            "concurrency": 1,
            "timeout_seconds": args.timeout,
            "poll_interval_seconds": args.poll_interval,
        },
        "outcomes": outcome.results,
        "results": results,
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False, default=str)
        print(f"Saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
