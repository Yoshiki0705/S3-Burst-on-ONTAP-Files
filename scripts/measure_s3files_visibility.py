#!/usr/bin/env python3
"""S3 Burst on ONTAP Files — cross-protocol visibility latency for Amazon S3 Files.

UNEXECUTED DRAFT. This script has never been run against a real file system. No number it
produces appears in any document in this repository yet, and the comparison table in
docs/ja/verification/s3files-vs-flexcache.md is deliberately empty until it has been.

Why it exists
-------------
`measure_visibility.py` measures the same question for this repository's architecture: an
FSx for ONTAP volume written over an S3 Access Point and read over NFS, optionally through a
FlexCache. This script measures Amazon S3 Files, which answers the same requirement with a
different design, so that the two can be put in one table.

What is held identical to `measure_visibility.py`
-------------------------------------------------
  - One boto3 client, created once and reused. The lesson is recorded in this repository: an
    earlier measurement published 873 ms for a step that was 44 ms, because a CLI process start
    and a TLS handshake sat inside every sample.
  - One host, one clock. Two hosts would compare two clocks.
  - 30 iterations, 64 B objects, concurrency 1, for the three visibility directions.
  - `percentiles()` is imported rather than reimplemented, so p50/p90/p99/max are computed the
    same way (nearest-rank, no interpolation).

What CANNOT be held identical, and must not be described as if it were
----------------------------------------------------------------------
  - Protocol version. The ONTAP measurement used NFSv3. S3 Files supports NFSv4.1 and NFSv4.2
    only, and its mount helper uses 4.2 by default.
  - Mount options. The helper always adds `tls` and `iam`; neither can be disabled. Whether
    `actimeo=0` is honoured is unverified, so the options that actually took effect are read
    from `findmnt` and recorded in the output rather than assumed.
  Both differences are recorded in the metadata block, because a reader comparing the two
  tables needs to see them next to the figures.

One deliberate deviation from `measure_visibility.py`
-----------------------------------------------------
That script appends a 999_999 sentinel when a poll gives up, and then passes the list to
`percentiles()`. A sentinel inside the distribution silently moves p90 and max, so a single
timeout would publish a wrong figure that looks like a real one. Here a timeout is counted and
excluded, and the count is reported alongside the percentiles. A table with `timeouts: 3` is
readable; a max of 999,999 ms is not.

Timing
------
The export direction is the slow one by design: S3 Files batches file-system writes for about
60 seconds before copying them to the bucket, so direction 2 costs at least that per iteration.
Thirty sequential iterations is therefore half an hour or more. Sequential is kept because
concurrency 1 is what the existing measurement used; use --iterations to trade precision for
time, and record what was used.

Usage:
  python3 scripts/measure_s3files_visibility.py \
    --file-system-id fs-0abcdef1234567890 \
    --bucket <the bucket the file system is a view of> \
    [--mount-point /mnt/s3files] \
    [--iterations 30] [--object-size 64] \
    [--timeout 600] [--poll-interval 0.5] \
    [--small-size 65536] [--large-size 4194304] \
    [--region ap-northeast-1] [--prefix measure/s3files] \
    [--output results.json] [--csv results.csv] [--keep]

Requires: amazon-efs-utils 3.0.0 or above with the file system already mounted, boto3, python3.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from measure_visibility import percentiles

# A poll that gives up is recorded as a timeout rather than as a very large latency. See the
# module docstring: a sentinel mixed into the distribution moves p90 and max without saying so.
TIMED_OUT = object()

# The columns of the comparison table in docs/ja/verification/s3files-vs-flexcache.md, in order.
# They are Japanese because the CSV exists to be pasted into that table; changing one here without
# changing the other is what makes two tables stop lining up.
CSV_COLUMNS = [
    "プロトコル",
    "マウント方法",
    "p50",
    "p90",
    "max",
    "n",
    "計測日",
]


def mount_path(mount_point: str, key: str, key_prefix: str) -> Path:
    """Where a bucket key appears on the mount.

    These are NOT the same string when the file system is mounted through an access point whose
    root directory is a subdirectory. Measured 2026-09-01: an access point rooted at `/measure`
    makes bucket key `measure/a/b.bin` appear at `<mount>/a/b.bin`. A script that treats the key as
    a mount-relative path polls a location that will never exist, and because the failure mode is a
    poll rather than an error it looks exactly like the service being slow. The first run of this
    script spent 15 minutes timing out on a direction that was in fact working.
    """
    relative = (
        key[len(key_prefix) :] if key_prefix and key.startswith(key_prefix) else key
    )
    return Path(mount_point) / relative.lstrip("/")


def attribute_cache_disabled(options: str | None) -> bool:
    """Whether the mount really has attribute caching off.

    Measured 2026-09-01: `mount -o actimeo=0` is accepted and does take effect, but the string
    `actimeo` never appears in the effective options. The kernel expands it into the four
    components below. Grepping the mount options for "actimeo" therefore reports a false negative
    on a mount that is correctly configured, which is how this function came to exist.
    """
    if not options:
        return False
    parts = set(options.split(","))
    return {"acregmin=0", "acregmax=0", "acdirmin=0", "acdirmax=0"} <= parts


def read_mount_options(mount_point: str) -> dict:
    """What the mount actually is, read from the system rather than from our own arguments.

    The helper rewrites and adds options, and a request is not evidence that an option applied.
    If attribute caching is not actually off, the visibility figures include the client's cache
    expiry rather than only the service's synchronisation, and that has to be visible in the output
    instead of being discovered later.

    Note that FSTYPE reads `nfs4`, not `s3files`. The helper mounts through a local TLS proxy, so
    the source is 127.0.0.1 on a high port and the kernel only ever sees NFSv4. An earlier version
    of this script refused to run unless FSTYPE was `s3files`, which never matches.
    """
    fields = {"fstype": None, "options": None, "source": None}
    try:
        result = subprocess.run(
            ["findmnt", "-T", mount_point, "-o", "FSTYPE,OPTIONS,SOURCE", "-n"],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        return fields | {"options": "findmnt not available"}
    if result.returncode != 0 or not result.stdout.strip():
        return fields | {"options": "not a mount point"}
    parts = result.stdout.split()
    if len(parts) >= 3:
        fields["fstype"], fields["options"], fields["source"] = (
            parts[0],
            parts[1],
            parts[2],
        )
    return fields


def describe_environment(region: str, file_system_id: str, mount_point: str) -> dict:
    """Environment facts that make the numbers meaningful, read from the API where possible."""
    environment: dict = {
        "measured_at": datetime.now(UTC).isoformat(),
        "region": region,
        "file_system_id": file_system_id,
        "mount_point": mount_point,
        "draft": "UNEXECUTED DRAFT; this script had not been run when it was written",
    }
    mount = read_mount_options(mount_point)
    environment["mount_fstype"] = mount["fstype"]
    environment["mount_source"] = mount["source"]
    environment["mount_options_effective"] = mount["options"]
    environment["attribute_cache_disabled"] = attribute_cache_disabled(mount["options"])
    version = [
        part for part in (mount["options"] or "").split(",") if part.startswith("vers=")
    ]
    environment["nfs_version"] = version[0] if version else "not reported by findmnt"
    try:
        client = boto3.client("s3files", region_name=region)
    except (
        Exception
    ) as exc:  # botocore raises several unrelated types for an unknown service
        environment["file_system_api"] = f"not read: {type(exc).__name__}"
        return environment
    # The s3files API models its members in lowerCamelCase, unlike the FSx API that this
    # repository's other script talks to, and its operations are get_/list_ rather than describe_.
    # `describe_mount_targets` and `MountTargets` do not exist here; both fail at runtime rather
    # than at review, which is why the shapes below were read from the API reference.
    try:
        file_system = client.get_file_system(fileSystemId=file_system_id)
        environment["file_system_status"] = file_system.get("status")
        environment["bucket"] = file_system.get("bucket")
        environment["prefix_scope"] = file_system.get("prefix") or "(whole bucket)"
        environment["kms_key_id"] = file_system.get("kmsKeyId")
    except (ClientError, IndexError, KeyError) as exc:
        environment["file_system_api"] = f"not read: {type(exc).__name__}"
    try:
        # A separate call. The import threshold and the expiration window decide which storage
        # layer serves a read, so they belong beside any figure taken from this file system.
        sync = client.get_synchronization_configuration(fileSystemId=file_system_id)
        environment["import_rules"] = sync.get("importDataRules")
        environment["expiration_rules"] = sync.get("expirationDataRules")
    except (ClientError, KeyError) as exc:
        environment["synchronization_configuration"] = f"not read: {type(exc).__name__}"
    try:
        targets = client.list_mount_targets(fileSystemId=file_system_id)["mountTargets"]
        environment["mount_targets"] = [
            {
                "id": target.get("mountTargetId"),
                "status": target.get("status"),
                "availability_zone_id": target.get("availabilityZoneId"),
                "subnet_id": target.get("subnetId"),
            }
            for target in targets
        ]
    except (ClientError, IndexError, KeyError) as exc:
        environment["mount_targets"] = f"not read: {type(exc).__name__}"
    return environment


def poll_until(check, timeout: float, interval: float) -> float | object:
    """Time how long `check` takes to become true. Returns ms, or TIMED_OUT.

    The clock starts before the first attempt, so the returned figure includes the polling
    granularity. That is why `interval` is a parameter and is recorded in the output: a 0.5 s
    interval cannot resolve a 10 ms difference, and reading a figure produced with it as though it
    could is the mistake this signature is shaped to prevent.
    """
    start = time.time()
    deadline = start + timeout
    while time.time() < deadline:
        try:
            if check():
                return (time.time() - start) * 1000
        except (OSError, PermissionError, ClientError):
            pass
        time.sleep(interval)
    return TIMED_OUT


def summarise(samples: list, extra: dict | None = None) -> dict:
    """Percentiles over the samples that completed, with the timeouts counted separately."""
    completed = [value for value in samples if value is not TIMED_OUT]
    result = percentiles(completed)
    result["timeouts"] = len(samples) - len(completed)
    result["attempted"] = len(samples)
    if result["timeouts"]:
        result["note"] = (
            "timeouts are excluded from the percentiles; n is the number that completed"
        )
    return result | (extra or {})


def direction_s3_to_file(s3, bucket: str, mount_point: str, prefix: str, args) -> dict:
    """1. S3 PutObject, then wait until the object is readable as a file on the mount."""
    print(f"  Dir 1: S3 PutObject -> S3 Files NFS read ({args.iterations} iterations)")
    body = b"m" * args.object_size
    samples: list = []
    for index in range(args.iterations):
        key = f"{prefix}/d1/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount_point, key, args.key_prefix)
        s3.put_object(Bucket=bucket, Key=key, Body=body)
        samples.append(
            poll_until(
                lambda p=path: p.exists() and p.stat().st_size == args.object_size,
                args.timeout,
                args.poll_interval,
            )
        )
        print(f"    {index + 1}/{args.iterations}", end="\r", flush=True)
    print()
    return summarise(samples)


def direction_file_to_s3(s3, bucket: str, mount_point: str, prefix: str, args) -> dict:
    """2. Write through the mount, then wait until GetObject returns it.

    The slow direction, by design rather than by accident: writes are batched for about 60
    seconds so that rapid successive changes to one file become a single object version.
    """
    print(f"  Dir 2: S3 Files NFS write -> S3 GetObject ({args.iterations} iterations)")
    print(
        "    at least ~60 s per iteration; the export batching window is not a defect"
    )
    body = b"m" * args.object_size
    samples: list = []
    for index in range(args.iterations):
        key = f"{prefix}/d2/{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path = mount_path(mount_point, key, args.key_prefix)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
        # Closed before the clock starts. The file has to be closed for the change to be a
        # candidate for export, so timing from before the close would measure our own file
        # handle rather than the service.
        os.chmod(path, 0o644)

        def visible(k=key):
            return (
                s3.head_object(Bucket=bucket, Key=k)["ContentLength"]
                == args.object_size
            )

        samples.append(poll_until(visible, args.timeout, args.poll_interval))
        print(f"    {index + 1}/{args.iterations}", end="\r", flush=True)
    print()
    return summarise(samples)


def direction_within_mount(mount_point: str, prefix: str, args) -> dict:
    """3. Write and read inside the same mount.

    Not a synchronisation measurement. S3 Files provides read-after-write consistency within the
    file system, so what this times is the NFS round trip. It is here because the ONTAP-side
    table has the equivalent row, and because a reader needs one row that is not waiting on a
    background copy in order to interpret the two that are.
    """
    print(f"  Dir 3: write -> read within the mount ({args.iterations} iterations)")
    body = b"m" * args.object_size
    samples: list = []
    directory = mount_path(mount_point, f"{prefix}/d3", args.key_prefix)
    directory.mkdir(parents=True, exist_ok=True)
    for index in range(args.iterations):
        path = directory / f"{index:03d}-{uuid.uuid4().hex[:8]}.bin"
        path.write_bytes(body)
        samples.append(
            poll_until(
                lambda p=path: p.read_bytes() == body,
                args.timeout,
                args.poll_interval,
            )
        )
    return summarise(samples)


def direction_size_threshold(
    s3, bucket: str, mount_point: str, prefix: str, args
) -> dict:
    """4. Read latency below the import threshold against read latency above 1 MiB.

    Two mechanisms, not one setting. Objects strictly smaller than the import threshold (128 KiB
    by default) have their data placed on the high-performance storage. Reads of 1 MiB or more
    stream from the bucket even when the data is also resident. So the sizes chosen here sit on
    either side of both boundaries.

    The first access to a directory imports metadata for everything in it and is slower than
    every later one, so the directory is listed once and the first read of each size is discarded
    before anything is timed.
    """
    print("  Dir 4: read latency by size (below the import threshold, and >= 1 MiB)")
    results: dict = {}
    for label, size in (("small", args.small_size), ("large", args.large_size)):
        keys = []
        for index in range(args.iterations):
            key = f"{prefix}/d4/{label}-{index:03d}.bin"
            s3.put_object(Bucket=bucket, Key=key, Body=b"m" * size)
            keys.append(key)

        # Wait for the last one to appear before timing any of them, so a read is not racing the
        # import. Without this the "small" figure is a visibility measurement wearing the label
        # of a read measurement.
        last = mount_path(mount_point, keys[-1], args.key_prefix)
        appeared = poll_until(
            lambda p=last: p.exists() and p.stat().st_size == size,
            args.timeout,
            args.poll_interval,
        )
        if appeared is TIMED_OUT:
            results[label] = {
                "error": "objects never became visible on the mount; read not timed",
                "object_size_bytes": size,
            }
            continue

        directory = mount_path(mount_point, f"{prefix}/d4", args.key_prefix)
        list(directory.iterdir())  # first-access metadata import, deliberately untimed
        mount_path(
            mount_point, keys[0], args.key_prefix
        ).read_bytes()  # warm-up, discarded

        samples: list = []
        for key in keys:
            path = mount_path(mount_point, key, args.key_prefix)
            start = time.perf_counter()
            read = path.read_bytes()
            samples.append((time.perf_counter() - start) * 1000)
            if len(read) != size:
                samples[-1] = TIMED_OUT
        results[label] = summarise(samples, {"object_size_bytes": size})
        stats = results[label]
        print(
            f"    {label:5s} {size:>9} B  p50 {stats['p50']:8.1f} ms  "
            f"p90 {stats['p90']:8.1f} ms  max {stats['max']:8.1f} ms  n={stats['n']}"
        )
    return results


def delete_prefix(s3, bucket: str, prefix: str) -> int:
    """Remove every version and delete marker under the prefix.

    Versioning is a prerequisite of S3 Files, not a choice, so `delete_objects` on current
    versions alone leaves the chain behind and the bucket non-empty.
    """
    deleted = 0
    paginator = s3.get_paginator("list_object_versions")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        entries = [
            {"Key": item["Key"], "VersionId": item["VersionId"]}
            for group in ("Versions", "DeleteMarkers")
            for item in page.get(group, [])
        ]
        for start in range(0, len(entries), 1000):
            batch = entries[start : start + 1000]
            s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            deleted += len(batch)
    return deleted


def write_csv(path: str, environment: dict, directions: dict) -> None:
    """One row per measured direction, in the column order of the comparison table."""
    mount = environment.get("mount_options_effective") or "unknown"
    measured_at = environment.get("measured_at", "")[:10]
    rows = []
    for label, stats in directions.items():
        if not isinstance(stats, dict) or "p50" not in stats:
            continue
        rows.append(
            {
                "プロトコル": label,
                "マウント方法": mount,
                "p50": stats["p50"],
                "p90": stats["p90"],
                "max": stats["max"],
                "n": stats["n"],
                "計測日": measured_at,
            }
        )
    with open(path, "w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def flatten(directions: dict) -> dict:
    """Direction 4 nests by size; the CSV wants one row per measured thing."""
    flat = {}
    for name, value in directions.items():
        if isinstance(value, dict) and "p50" in value:
            flat[name] = value
        elif isinstance(value, dict):
            for sub, stats in value.items():
                flat[f"{name}.{sub}"] = stats
    return flat


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--file-system-id", required=True, help="S3 Files file system ID (fs-...)"
    )
    parser.add_argument(
        "--bucket",
        required=True,
        help="the general purpose bucket the file system is a view of",
    )
    parser.add_argument(
        "--mount-point",
        default="/mnt/s3files",
        help="an already-mounted S3 Files file system",
    )
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument(
        "--object-size",
        type=int,
        default=64,
        help="bytes, for directions 1-3; matches the existing measurement",
    )
    parser.add_argument(
        "--small-size",
        type=int,
        default=65536,
        help="bytes, direction 4; must be below the import threshold",
    )
    parser.add_argument(
        "--large-size",
        type=int,
        default=4194304,
        help="bytes, direction 4; must be at least 1 MiB to take the direct-from-S3 path",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=600.0,
        help="seconds to wait for a change to become visible before recording a timeout",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=0.5,
        help="seconds between visibility checks; it bounds the resolution of the result",
    )
    parser.add_argument("--prefix", default="measure/s3files")
    parser.add_argument(
        "--key-prefix",
        default="",
        help=(
            "the bucket key prefix the MOUNT ROOT corresponds to, with a trailing slash. "
            "Empty when the file system root is mounted. When mounting through an access point "
            "whose root directory is /measure, pass measure/ -- otherwise every mount-side poll "
            "looks for a path that cannot exist and times out silently"
        ),
    )
    parser.add_argument("--output", help="write the result as JSON to this path")
    parser.add_argument(
        "--csv", help="write the comparison-table rows as CSV to this path"
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the objects created under --prefix in place",
    )
    args = parser.parse_args()

    print("=== S3 Files visibility measurement (UNEXECUTED DRAFT) ===\n")

    environment = describe_environment(
        args.region, args.file_system_id, args.mount_point
    )
    print("Environment")
    for key, value in environment.items():
        print(f"  {key}: {value}")

    # The guard is "is this a separate mount at all", not "is FSTYPE s3files". FSTYPE reads nfs4
    # because the helper mounts through a local TLS proxy. What this protects against is measuring
    # the instance's root filesystem by accident, which would produce plausible figures for the
    # wrong thing; that risk is covered by requiring a real mount point.
    if environment.get("mount_fstype") not in {"nfs4", "nfs", "s3files"}:
        print(
            f"\nerror: {args.mount_point} is not an NFS mount "
            f"(findmnt reports {environment.get('mount_fstype')!r}).\n"
            "       Mount it first with environments/s3files-compare/mount-s3files.sh.\n"
            "       Refusing to continue: measuring the instance's root filesystem by accident\n"
            "       would produce plausible figures for the wrong thing.",
            file=sys.stderr,
        )
        return 1
    if not environment.get("attribute_cache_disabled"):
        print(
            "warning: attribute caching is not off on this mount "
            f"({environment.get('mount_options_effective')}).\n"
            "         The visibility figures will include the client's cache expiry as well as\n"
            "         the service's synchronisation. Mount with -o actimeo=0 to separate them.",
            file=sys.stderr,
        )
    if args.small_size >= 131072:
        print(
            f"warning: --small-size {args.small_size} is not below the 128 KiB default import "
            "threshold, so direction 4 compares two streamed reads rather than a resident read "
            "against a streamed one.",
            file=sys.stderr,
        )
    if args.large_size < 1048576:
        print(
            f"warning: --large-size {args.large_size} is below 1 MiB, so it does not take the "
            "direct-from-S3 read path that direction 4 is about.",
            file=sys.stderr,
        )

    # One client, created once and reused for every direction.
    s3 = boto3.client(
        "s3",
        region_name=args.region,
        config=Config(retries={"max_attempts": 3, "mode": "standard"}),
    )
    # Warm-up, discarded: the first call pays for endpoint resolution and credential loading.
    warm_key = f"{args.prefix}/warmup.bin"
    s3.put_object(Bucket=args.bucket, Key=warm_key, Body=b"warmup")
    s3.head_object(Bucket=args.bucket, Key=warm_key)

    run_prefix = f"{args.prefix}/{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}"
    # Created over NFS first, deliberately. An object written over the S3 API materialises on the
    # file system as root:root, so a run directory created by the first S3 PutObject cannot then be
    # written into by the access point's POSIX identity -- the file-written directions fail with
    # EACCES on a directory that looks perfectly normal. Creating it here makes the run root owned
    # by the mapped identity, and the imported subdirectories sit inside it.
    run_root = mount_path(args.mount_point, run_prefix, args.key_prefix)
    run_root.mkdir(parents=True, exist_ok=True)
    print(f"\nMeasuring under {run_prefix}/  (run root created over NFS: {run_root})\n")

    directions = {
        "s3_put_to_nfs_read": direction_s3_to_file(
            s3, args.bucket, args.mount_point, run_prefix, args
        ),
        "nfs_write_to_s3_get": direction_file_to_s3(
            s3, args.bucket, args.mount_point, run_prefix, args
        ),
        "within_mount_write_read": direction_within_mount(
            args.mount_point, run_prefix, args
        ),
        "read_by_size": direction_size_threshold(
            s3, args.bucket, args.mount_point, run_prefix, args
        ),
    }

    print("\nResults (ms)")
    for name, stats in flatten(directions).items():
        if "p50" not in stats:
            print(f"  {name:28s} {stats.get('error', 'no result')}")
            continue
        print(
            f"  {name:28s} p50 {stats['p50']:9.1f}  p90 {stats['p90']:9.1f}  "
            f"max {stats['max']:9.1f}  n={stats['n']}  timeouts={stats['timeouts']}"
        )

    if args.keep:
        print(f"\n--keep given; objects left under {args.prefix}/")
    else:
        removed = delete_prefix(s3, args.bucket, args.prefix)
        print(f"\nCleanup: removed {removed} version(s) and delete marker(s)")

    report = {
        "environment": environment,
        "method": {
            "iterations": args.iterations,
            "object_size_bytes": args.object_size,
            "concurrency": 1,
            "key_prefix": args.key_prefix,
            "timeout_seconds": args.timeout,
            "poll_interval_seconds": args.poll_interval,
            "small_size_bytes": args.small_size,
            "large_size_bytes": args.large_size,
            "percentiles": "nearest-rank, no interpolation; shared with measure_visibility.py",
            "timeout_handling": "excluded from percentiles and counted separately",
        },
        "directions": directions,
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
        print(f"Saved to {args.output}")
    if args.csv:
        write_csv(args.csv, environment, flatten(directions))
        print(f"Saved comparison rows to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
