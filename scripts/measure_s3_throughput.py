#!/usr/bin/env python3
"""S3 Burst on ONTAP Files — S3 API throughput, IOPS and concurrency, on any S3 endpoint.

One code path, two targets. That is what makes the comparison apples-to-apples: the same client, the
same object sizes, the same concurrency ladder and the same clock are pointed at

  * an FSx for ONTAP S3 Access Point, whose ceiling is the throughput capacity you purchased, and
  * an Amazon S3 bucket fronted by S3 Files, whose ceiling is elastic and not chosen.

Those two ceilings are not the same kind of number, so the output records which is which and the
documents built from it say so. A table that puts "128 MBps" and "elastic" in one column without
that note is misleading, and it is the reason this script prints the target kind in its metadata.

Method, and why each choice matters
-----------------------------------
  * **Retries are disabled.** botocore's default retry mode silently re-sends on a 503, which turns
    a throttled endpoint into a slow one and hides the thing worth measuring. Here `SlowDown` is
    counted and reported as a rate, following the procedure that
    docs/ja/reference/limits/s3ap-design-guide.md sets out and had never executed.
  * **Fixed wall-clock duration per point**, not a fixed object count. Throughput is bytes over
    elapsed time; with a fixed count, a slow point simply takes longer and the rate is unaffected by
    queueing, which is the effect being looked for.
  * **The connection pool is sized to the concurrency.** botocore defaults to 10; at concurrency 64
    the extra 54 threads would queue on connections and the measurement would report client
    contention as endpoint latency.
  * **A warm-up point is discarded** for each (size, concurrency) pair, because the first requests
    pay for TLS handshakes across the whole pool.
  * **Read and write are separate phases.** Reads run against objects written in the write phase, so
    a read is never racing its own write.
  * **The instance type and its network figure are read from IMDS** and recorded. A throughput number
    taken on an instance whose baseline is below the storage ceiling is a measurement of EC2 network
    credits; recording the instance is what lets a reader rule that out.

Usage:
  python3.12 scripts/measure_s3_throughput.py \
    --target-name "FSx for ONTAP S3 AP" --target-kind provisioned \
    --bucket <s3-ap-alias-or-arn> --addressing-style path \
    --sizes 1048576,8388608 --concurrency 1,4,16,64 --duration 30 \
    --output fsx-throughput.json --csv fsx-throughput.csv

  python3.12 scripts/measure_s3_throughput.py \
    --target-name "S3 Files bucket" --target-kind elastic \
    --bucket <bucket> \
    --sizes 1048576,8388608 --concurrency 1,4,16,64 --duration 30 \
    --output s3files-throughput.json --csv s3files-throughput.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import threading
import time
import urllib.request
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

CSV_COLUMNS = [
    "target",
    "target_kind",
    "phase",
    "object_bytes",
    "concurrency",
    "throughput_mb_s",
    "iops",
    "p50_ms",
    "p90_ms",
    "p99_ms",
    "requests",
    "slowdown",
    "slowdown_rate",
    "errors",
    "duration_s",
    "measured_at",
]


def instance_facts() -> dict:
    """Instance type and network figure from IMDSv2, so the client can be ruled out as the limit."""
    facts: dict[str, str] = {}
    try:
        token_req = urllib.request.Request(
            "http://169.254.169.254/latest/api/token",
            method="PUT",
            headers={"X-aws-ec2-metadata-token-ttl-seconds": "60"},
        )
        with urllib.request.urlopen(token_req, timeout=3) as response:
            token = response.read().decode()
        for key, path in (
            ("instance_type", "instance-type"),
            ("availability_zone", "placement/availability-zone"),
            ("instance_id", "instance-id"),
        ):
            req = urllib.request.Request(
                f"http://169.254.169.254/latest/meta-data/{path}",
                headers={"X-aws-ec2-metadata-token": token},
            )
            with urllib.request.urlopen(req, timeout=3) as response:
                facts[key] = response.read().decode()
    except Exception as exc:  # noqa: BLE001 - not on EC2, or IMDS blocked
        facts["imds"] = f"not read: {type(exc).__name__}"
    return facts


def percentile(values: list[float], fraction: float) -> float:
    """Nearest-rank, no interpolation, matching percentiles() in measure_visibility.py."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(int(len(ordered) * fraction), len(ordered) - 1)
    return round(ordered[index], 1)


class Counters:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.latencies: list[float] = []
        self.bytes = 0
        self.slowdown = 0
        self.errors: dict[str, int] = {}
        # (completion time, bytes) per request, so a long run can be cut into intervals afterwards.
        # A single figure over ten minutes hides the shape: a burst-credit mechanism that runs out
        # partway through averages into something that looks like a lower steady rate, and nothing in
        # the aggregate says which of the two happened.
        self.timeline: list[tuple[float, int]] = []

    def ok(self, milliseconds: float, size: int) -> None:
        with self.lock:
            self.latencies.append(milliseconds)
            self.bytes += size
            self.timeline.append((time.time(), size))

    def failed(self, code: str) -> None:
        with self.lock:
            if code == "SlowDown":
                self.slowdown += 1
            else:
                self.errors[code] = self.errors.get(code, 0) + 1


def intervals(
    timeline: list[tuple[float, int]], started: float, width: float
) -> list[dict]:
    """Bucket a completion timeline into fixed-width intervals.

    Reported so that a sustained run can be read as a curve rather than a single number. Bytes are
    attributed to the interval a request completed in, which is approximate for a request that spans
    a boundary; at these durations the error is small and it keeps the accounting simple.
    """
    if not timeline or width <= 0:
        return []
    buckets: dict[int, list[int]] = {}
    for finished, size in timeline:
        index = int((finished - started) // width)
        buckets.setdefault(index, []).append(size)
    rows = []
    for index in sorted(buckets):
        sizes = buckets[index]
        rows.append(
            {
                "from_s": round(index * width, 1),
                "to_s": round((index + 1) * width, 1),
                "requests": len(sizes),
                "throughput_mb_s": round(sum(sizes) / width / 1_000_000, 1),
            }
        )
    return rows


def client_for(args, concurrency: int):
    """One client per point, with the pool sized to the concurrency and retries off.

    Retries off is the load-bearing part: with the default mode a 503 is re-sent inside botocore and
    never appears in the result, so a throttled endpoint reads as a slower one.
    """
    config = Config(
        max_pool_connections=max(concurrency, 10),
        retries={"max_attempts": 0, "mode": "standard"},
        s3={"addressing_style": args.addressing_style},
        connect_timeout=15,
        read_timeout=120,
    )
    return boto3.client("s3", region_name=args.region, config=config)


def make_body(size: int, kind: str) -> bytes:
    """Build the object payload.

    The choice matters, and it matters asymmetrically. A payload of one repeated byte is what this
    script used originally, and on a file system with inline storage efficiency enabled it never
    reaches the disks: inline compression collapses it, and inline dedup collapses the copies of it
    against each other.

    On reads the effect is decisive. A 280 GiB read of zero-filled data returned at four times the
    file system's documented disk-throughput ceiling, because the blocks were reconstructed rather
    than fetched. At the 128 MBps step, the same warm-against-cold comparison showed a ratio of 1.55
    with zero-filled data and 1.00 with incompressible data -- the whole difference was the payload.

    On writes it is small, and this was measured rather than assumed: 417.1 against 415.1 MB/s
    through the S3 Access Point (0.5%) and 808.6 against 772.0 MB/s over NFS (4.7%), with inline
    efficiency enabled in both cases. A write actually sends the bytes, so only the landing side can
    collapse them; a read can be answered without fetching anything.

    So "random" is what to use when the figure will be compared against a storage-side limit, and it
    is the only safe choice for a read. "fill" is kept as the default because earlier results in this
    repository were produced with it, and moving the default would silently make those incomparable.
    Whichever is used is recorded in the output.
    """
    if kind == "random":
        return os.urandom(size)
    if kind == "fill":
        return b"t" * size
    raise ValueError(f"unknown body kind: {kind}")


def run_point(
    s3, args, phase: str, size: int, concurrency: int, keys: list[str]
) -> dict:
    """Drive one (phase, size, concurrency) point for a fixed wall-clock duration."""
    counters = Counters()
    body = make_body(size, args.body)
    deadline = time.time() + args.duration
    counter_lock = threading.Lock()
    next_key = [0]

    def one_write() -> None:
        while time.time() < deadline:
            key = f"{args.prefix}/tp/{phase}-{size}-{concurrency}-{uuid.uuid4().hex[:12]}.bin"
            start = time.perf_counter()
            try:
                s3.put_object(Bucket=args.bucket, Key=key, Body=body)
            except ClientError as exc:
                counters.failed(exc.response.get("Error", {}).get("Code", "Unknown"))
                continue
            except OSError as exc:
                counters.failed(type(exc).__name__)
                continue
            counters.ok((time.perf_counter() - start) * 1000, size)

    def one_read() -> None:
        while time.time() < deadline:
            with counter_lock:
                key = keys[next_key[0] % len(keys)]
                next_key[0] += 1
            start = time.perf_counter()
            try:
                streamed = s3.get_object(Bucket=args.bucket, Key=key)["Body"].read()
            except ClientError as exc:
                counters.failed(exc.response.get("Error", {}).get("Code", "Unknown"))
                continue
            except OSError as exc:
                counters.failed(type(exc).__name__)
                continue
            counters.ok((time.perf_counter() - start) * 1000, len(streamed))

    worker = one_write if phase == "write" else one_read
    started = time.time()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        for _ in range(concurrency):
            pool.submit(worker)
    elapsed = time.time() - started

    requests = len(counters.latencies)
    attempted = requests + counters.slowdown + sum(counters.errors.values())
    return {
        "phase": phase,
        "object_bytes": size,
        "concurrency": concurrency,
        "duration_s": round(elapsed, 2),
        "requests": requests,
        "bytes": counters.bytes,
        "throughput_mb_s": round(counters.bytes / elapsed / 1_000_000, 1)
        if elapsed
        else 0,
        "iops": round(requests / elapsed, 1) if elapsed else 0,
        "p50_ms": percentile(counters.latencies, 0.50),
        "p90_ms": percentile(counters.latencies, 0.90),
        "p99_ms": percentile(counters.latencies, 0.99),
        "mean_ms": round(statistics.fmean(counters.latencies), 1)
        if counters.latencies
        else 0,
        "slowdown": counters.slowdown,
        "slowdown_rate": round(counters.slowdown / attempted, 4) if attempted else 0,
        "errors": counters.errors,
        "intervals": intervals(
            counters.timeline, started, getattr(args, "report_interval", 0.0)
        ),
    }


def seed_read_objects(s3, args, size: int, wanted: int) -> list[str]:
    """Write the objects the read phase will read, so a read never races its own write."""
    keys = []
    body = b"r" * size
    with ThreadPoolExecutor(max_workers=16) as pool:
        futures = []
        for index in range(wanted):
            key = f"{args.prefix}/seed/{size}-{index:04d}.bin"
            keys.append(key)
            futures.append(
                pool.submit(s3.put_object, Bucket=args.bucket, Key=key, Body=body)
            )
        for future in futures:
            future.result()
    return keys


def delete_prefix(s3, bucket: str, prefix: str) -> int:
    """Remove every version and delete marker under the prefix.

    Versioning is on for an S3 Files bucket (the service requires it), so removing current versions
    alone would leave the bucket non-empty and block its deletion later.
    """

    def plain_listing() -> list[dict]:
        pages = []
        for page in s3.get_paginator("list_objects_v2").paginate(
            Bucket=bucket, Prefix=prefix
        ):
            pages.append(
                {
                    "Versions": [
                        {"Key": i["Key"], "VersionId": "null"}
                        for i in page.get("Contents", [])
                    ]
                }
            )
        return pages

    deleted = 0
    paginator = s3.get_paginator("list_object_versions")
    try:
        pages = list(paginator.paginate(Bucket=bucket, Prefix=prefix))
    except ClientError:
        # An FSx for ONTAP S3 Access Point does not offer object versions.
        pages = plain_listing()
    else:
        # An error is not the only way that call comes back useless. If it answers but reports no
        # versions, the objects may still be there and a cleanup that trusted this would delete
        # nothing while printing a success. Confirm against the plain listing before believing it.
        if not any(page.get("Versions") or page.get("DeleteMarkers") for page in pages):
            pages = plain_listing()
    for page in pages:
        entries = []
        for group in ("Versions", "DeleteMarkers"):
            for item in page.get(group, []):
                entry = {"Key": item["Key"]}
                if item.get("VersionId") and item["VersionId"] != "null":
                    entry["VersionId"] = item["VersionId"]
                entries.append(entry)
        for start in range(0, len(entries), 1000):
            batch = entries[start : start + 1000]
            try:
                s3.delete_objects(Bucket=bucket, Delete={"Objects": batch})
            except ClientError:
                for entry in batch:
                    try:
                        s3.delete_object(Bucket=bucket, Key=entry["Key"])
                    except ClientError:
                        pass
            deleted += len(batch)
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--bucket", required=True, help="bucket name, S3 AP alias, or S3 AP ARN"
    )
    parser.add_argument(
        "--target-name", required=True, help="how the result tables should name it"
    )
    parser.add_argument(
        "--target-kind",
        required=True,
        choices=["provisioned", "elastic"],
        help=(
            "what kind of ceiling this endpoint has. 'provisioned' means a tier was purchased and "
            "the number is a property of that purchase; 'elastic' means the service scales and the "
            "number is not chosen. Recorded so the two are never put in one column unexplained"
        ),
    )
    parser.add_argument(
        "--ceiling-note",
        default="",
        help="the ceiling in the operator's own words, e.g. '128 MBps provisioned, shared with NFS'",
    )
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument(
        "--addressing-style", default="auto", choices=["auto", "path", "virtual"]
    )
    parser.add_argument(
        "--sizes", default="1048576,8388608", help="comma-separated object sizes"
    )
    parser.add_argument(
        "--concurrency", default="1,4,16,64", help="comma-separated ladder"
    )
    parser.add_argument(
        "--duration", type=float, default=30.0, help="seconds per point"
    )
    parser.add_argument(
        "--warmup", type=float, default=5.0, help="seconds discarded per point"
    )
    parser.add_argument(
        "--report-interval",
        type=float,
        default=0.0,
        help=(
            "when above zero, also report throughput per interval of this many seconds. Use it for "
            "a long run: one figure over ten minutes cannot distinguish a steady rate from a burst "
            "that ran out partway through, and both are common on a credit-based mechanism"
        ),
    )
    parser.add_argument(
        "--body",
        choices=("fill", "random"),
        default="fill",
        help=(
            "payload to write. 'fill' repeats one byte and is what earlier results in this "
            "repository used; on a volume with inline storage efficiency enabled it is collapsed "
            "before it reaches the disks. Measured effect: under 5 percent on writes, but a factor "
            "of four on reads, so a read measured with 'fill' cannot be compared against a disk-side "
            "limit at all. 'random' is incompressible and is stored as written. Recorded in the "
            "output so a result can never be read without knowing which was used"
        ),
    )
    parser.add_argument("--read-objects", type=int, default=64)
    parser.add_argument("--phases", default="write,read")
    parser.add_argument("--prefix", default="measure/throughput")
    parser.add_argument("--output")
    parser.add_argument("--csv")
    parser.add_argument("--keep", action="store_true")
    args = parser.parse_args()

    sizes = [int(v) for v in args.sizes.split(",") if v]
    ladder = [int(v) for v in args.concurrency.split(",") if v]
    phases = [p.strip() for p in args.phases.split(",") if p.strip()]

    facts = instance_facts()
    environment = {
        "measured_at": datetime.now(UTC).isoformat(),
        "region": args.region,
        "target": args.target_name,
        "target_kind": args.target_kind,
        "ceiling_note": args.ceiling_note or "(not stated)",
        "addressing_style": args.addressing_style,
        "body": (
            "random, incompressible"
            if args.body == "random"
            else "fill, one repeated byte -- collapsed by inline storage efficiency. Measured cost: "
            "under 5% on writes, a factor of four on reads. Not comparable against a disk-side limit"
        ),
        "retries": "disabled, so SlowDown is counted rather than absorbed",
        **facts,
    }
    print("Environment")
    for key, value in environment.items():
        print(f"  {key}: {value}")

    rows: list[dict] = []
    for size in sizes:
        seeded: list[str] = []
        if "read" in phases:
            print(
                f"\nSeeding {args.read_objects} object(s) of {size} B for the read phase"
            )
            seeded = seed_read_objects(
                client_for(args, 16), args, size, args.read_objects
            )
            if not seeded:
                # Without this the read phase divides by len(seeded) and fails with a
                # ZeroDivisionError, which says nothing about the seeding having been the problem.
                print(
                    "  seeding produced no objects; skipping the read phase for this size"
                )
                phases = [p for p in phases if p != "read"]
        for phase in phases:
            for concurrency in ladder:
                s3 = client_for(args, concurrency)
                # Warm-up at the same shape, discarded: the first requests pay for a TLS handshake
                # on every connection in the pool.
                warm = argparse.Namespace(**{**vars(args), "duration": args.warmup})
                run_point(s3, warm, phase, size, concurrency, seeded)
                result = run_point(s3, args, phase, size, concurrency, seeded)
                result["target"] = args.target_name
                result["target_kind"] = args.target_kind
                result["measured_at"] = environment["measured_at"][:10]
                rows.append(result)
                if phase == "write":
                    # Per-point, not at the end. A write point at 2048 MBps for 30 s lands about
                    # 61 GB, so eight points would need roughly 490 GB of volume that exists only to
                    # be deleted, and the run would fail on capacity partway through rather than
                    # reporting a throughput number. Only the write phase's own prefix is touched;
                    # the seeded objects the read phase seeks are under a different one.
                    delete_prefix(
                        client_for(args, 16), args.bucket, f"{args.prefix}/tp/"
                    )
                print(
                    f"  {phase:5s} {size:>9} B  c={concurrency:<3d} "
                    f"{result['throughput_mb_s']:>8.1f} MB/s  {result['iops']:>7.1f} req/s  "
                    f"p50 {result['p50_ms']:>8.1f}  p99 {result['p99_ms']:>9.1f} ms  "
                    f"503 {result['slowdown']:>4d} ({result['slowdown_rate']:.1%})"
                    + (f"  errors {result['errors']}" if result["errors"] else "")
                )
                for row in result["intervals"]:
                    print(
                        f"      interval {row['from_s']:>6.1f}-{row['to_s']:<6.1f}s "
                        f"{row['throughput_mb_s']:>8.1f} MB/s  {row['requests']:>6d} req"
                    )

    if args.keep:
        print(f"\n--keep given; objects left under {args.prefix}/")
    else:
        removed = delete_prefix(client_for(args, 16), args.bucket, args.prefix)
        print(f"\nCleanup: removed {removed} object(s)/version(s)")

    report = {
        "environment": environment,
        "method": {
            "sizes": sizes,
            "concurrency_ladder": ladder,
            "duration_s": args.duration,
            "warmup_s": args.warmup,
            "phases": phases,
            "read_objects": args.read_objects,
            "percentiles": "nearest-rank, no interpolation",
            "retries": "max_attempts=0; SlowDown counted, not retried",
            "pool": "max_pool_connections sized to the concurrency",
        },
        "points": rows,
    }
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
        print(f"Saved to {args.output}")
    if args.csv:
        with open(args.csv, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=CSV_COLUMNS, extrasaction="ignore"
            )
            writer.writeheader()
            for row in rows:
                writer.writerow(
                    {**row, "errors": json.dumps(row["errors"], ensure_ascii=False)}
                )
        print(f"Saved CSV to {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
