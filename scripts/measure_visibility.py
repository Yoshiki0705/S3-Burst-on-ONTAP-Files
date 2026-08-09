#!/usr/bin/env python3
"""S3 Burst on ONTAP Files — Cross-protocol visibility latency measurement.

Measures the time from write completion to read visibility across 4 directions:
  1. S3 AP PutObject → FlexCache NFS read
  2. S3 AP PutObject → Origin NFS read (direct)
  3. NFS write (Origin) → FlexCache NFS read
  4. NFS write (Origin) → S3 AP GetObject

Optionally measures SMB (mount -t cifs) as a 5th direction for protocol comparison.

Usage:
  python3 measure_visibility.py \
    --s3ap-alias <S3_AP_ALIAS_OR_ARN> \
    --nfs-lif <DATA_LIF_IP> \
    --fc-path /s3burst_verify_fc \
    --origin-path /s3burst_verify \
    [--smb-share <SHARE_NAME> --smb-user <DOMAIN\\User> --smb-pass <PASSWORD>] \
    [--iterations 30] \
    [--region ap-northeast-1] \
    [--output results.json]

Environment:
  Designed to run on the test host created by the CloudFormation template.
  Requires: nfs-utils, cifs-utils (for SMB), boto3, python3.

Notes:
  - Numbers are from a specific test environment and vary by configuration.
  - actimeo=0 and cache=none disable client-side caching to isolate storage latency.
  - Production environments should use appropriate caching settings.
"""

from __future__ import annotations

import argparse
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


def percentiles(values: list[float]) -> dict:
    """Calculate p50, p90, p99, max from a list of ms values."""
    if not values:
        return {"p50": 0, "p90": 0, "p99": 0, "max": 0, "n": 0}
    s = sorted(values)
    n = len(s)
    return {
        "p50": round(s[int(n * 0.5)], 1),
        "p90": round(s[min(int(n * 0.9), n - 1)], 1),
        "p99": round(s[min(int(n * 0.99), n - 1)], 1),
        "max": round(s[-1], 1),
        "n": n,
    }


def mount_nfs(lif: str, path: str, mountpoint: str) -> None:
    """Mount NFS with actimeo=0 (no client cache)."""
    os.makedirs(mountpoint, exist_ok=True)
    subprocess.run(["umount", mountpoint], capture_output=True)
    cmd = [
        "mount",
        "-t",
        "nfs",
        "-o",
        "nfsvers=3,actimeo=0",
        f"{lif}:{path}",
        mountpoint,
    ]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  WARNING: NFS mount failed: {r.stderr.strip()}", file=sys.stderr)


def mount_smb(lif: str, share: str, mountpoint: str, user: str, password: str) -> None:
    """Mount SMB with cache=none (no client cache)."""
    os.makedirs(mountpoint, exist_ok=True)
    subprocess.run(["umount", mountpoint], capture_output=True)
    opts = f"username={user.split(chr(92))[-1]},password={password},domain={user.split(chr(92))[0]},vers=3.0,sec=ntlmssp,cache=none"
    cmd = ["mount", "-t", "cifs", f"//{lif}/{share}", mountpoint, "-o", opts]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print(f"  WARNING: SMB mount failed: {r.stderr.strip()}", file=sys.stderr)


def measure_s3_to_file(
    s3_client, bucket: str, read_path: str, iterations: int, label: str
) -> list[float]:
    """Measure: S3 PutObject → file read visibility."""
    print(f"  {label} ({iterations} iterations)...")
    latencies = []
    for i in range(iterations):
        key = f"vis_{uuid.uuid4().hex[:8]}.txt"
        data = f"DATA-{i}-{uuid.uuid4().hex}"
        s3_client.put_object(Bucket=bucket, Key=key, Body=data.encode())
        t0 = time.time()
        for _ in range(1000):
            try:
                p = Path(read_path) / key
                if p.exists() and data in p.read_text():
                    latencies.append((time.time() - t0) * 1000)
                    break
            except (OSError, PermissionError):
                pass
            time.sleep(0.002)
        else:
            latencies.append(999_999)
    return latencies


def measure_file_to_file(
    write_path: str, read_path: str, iterations: int, label: str
) -> list[float]:
    """Measure: NFS write → file read visibility (FlexCache propagation)."""
    print(f"  {label} ({iterations} iterations)...")
    latencies = []
    for i in range(iterations):
        fname = f"vis_{uuid.uuid4().hex[:8]}.txt"
        data = f"DATA-{i}-{uuid.uuid4().hex}"
        wp = Path(write_path) / fname
        wp.write_text(data)
        os.chmod(wp, 0o644)
        t0 = time.time()
        for _ in range(1000):
            try:
                rp = Path(read_path) / fname
                if rp.exists() and data in rp.read_text():
                    latencies.append((time.time() - t0) * 1000)
                    break
            except (OSError, PermissionError):
                pass
            time.sleep(0.002)
        else:
            latencies.append(999_999)
    return latencies


def measure_file_to_s3(
    s3_client, bucket: str, write_path: str, iterations: int, label: str
) -> list[float]:
    """Measure: NFS write → S3 AP GetObject visibility."""
    print(f"  {label} ({iterations} iterations)...")
    latencies = []
    for i in range(iterations):
        key = f"vis_{uuid.uuid4().hex[:8]}.txt"
        data = f"DATA-{i}-{uuid.uuid4().hex}"
        wp = Path(write_path) / key
        wp.write_text(data)
        os.chmod(wp, 0o644)
        t0 = time.time()
        for _ in range(1000):
            try:
                r = s3_client.get_object(Bucket=bucket, Key=key)
                if data in r["Body"].read().decode():
                    latencies.append((time.time() - t0) * 1000)
                    break
            except (s3_client.exceptions.NoSuchKey, s3_client.exceptions.ClientError):
                pass
            time.sleep(0.002)
        else:
            latencies.append(999_999)
    return latencies


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--s3ap-alias", required=True, help="S3 AP alias or ARN")
    parser.add_argument(
        "--nfs-lif", required=True, help="Data LIF IP for NFS/SMB mounts"
    )
    parser.add_argument(
        "--fc-path",
        required=True,
        help="FlexCache junction path (e.g. /s3burst_verify_fc)",
    )
    parser.add_argument(
        "--origin-path",
        required=True,
        help="Origin volume junction path (e.g. /s3burst_verify)",
    )
    parser.add_argument(
        "--smb-share", help="SMB share name on the FlexCache (enables SMB measurement)"
    )
    parser.add_argument("--smb-user", help="SMB user (DOMAIN\\User format)")
    parser.add_argument("--smb-pass", help="SMB password")
    parser.add_argument(
        "--iterations", type=int, default=30, help="Number of iterations per direction"
    )
    parser.add_argument("--region", default="ap-northeast-1", help="AWS region")
    parser.add_argument("--output", help="Output JSON file path")
    args = parser.parse_args()

    # Setup
    s3 = boto3.client(
        "s3", region_name=args.region, config=Config(s3={"addressing_style": "path"})
    )
    nfs_fc = "/mnt/s3burst_fc"
    nfs_origin = "/mnt/s3burst_origin"

    print("=== S3 Burst on ONTAP Files — Visibility Measurement ===\n")
    print(f"  S3 AP: {args.s3ap_alias}")
    print(f"  NFS LIF: {args.nfs_lif}")
    print(f"  FlexCache path: {args.fc_path}")
    print(f"  Origin path: {args.origin_path}")
    print(f"  Iterations: {args.iterations}")
    print()

    # Mount NFS
    print("Mounting NFS...")
    mount_nfs(args.nfs_lif, args.fc_path, nfs_fc)
    mount_nfs(args.nfs_lif, args.origin_path, nfs_origin)
    time.sleep(2)

    results = {
        "metadata": {
            "timestamp": datetime.now(UTC).isoformat(),
            "region": args.region,
            "s3ap": args.s3ap_alias,
            "nfs_lif": args.nfs_lif,
            "fc_path": args.fc_path,
            "origin_path": args.origin_path,
            "iterations": args.iterations,
            "nfs_mount_options": "nfsvers=3,actimeo=0",
        },
        "directions": {},
    }

    # Direction 1: S3 AP → FlexCache NFS
    lat = measure_s3_to_file(
        s3,
        args.s3ap_alias,
        nfs_fc,
        args.iterations,
        "Dir 1: S3 AP PutObject → FlexCache NFS read",
    )
    results["directions"]["s3ap_to_fc_nfs"] = percentiles(lat)
    print(f"    → {percentiles(lat)}\n")

    # Direction 2: S3 AP → Origin NFS direct
    lat = measure_s3_to_file(
        s3,
        args.s3ap_alias,
        nfs_origin,
        args.iterations,
        "Dir 2: S3 AP PutObject → Origin NFS read",
    )
    results["directions"]["s3ap_to_origin_nfs"] = percentiles(lat)
    print(f"    → {percentiles(lat)}\n")

    # Direction 3: NFS write (Origin) → FlexCache NFS read
    lat = measure_file_to_file(
        nfs_origin,
        nfs_fc,
        args.iterations,
        "Dir 3: NFS write (Origin) → FlexCache NFS read",
    )
    results["directions"]["nfs_origin_to_fc_nfs"] = percentiles(lat)
    print(f"    → {percentiles(lat)}\n")

    # Direction 4: NFS write (Origin) → S3 AP GetObject
    lat = measure_file_to_s3(
        s3,
        args.s3ap_alias,
        nfs_origin,
        args.iterations,
        "Dir 4: NFS write (Origin) → S3 AP GetObject",
    )
    results["directions"]["nfs_origin_to_s3ap"] = percentiles(lat)
    print(f"    → {percentiles(lat)}\n")

    # Direction 5 (optional): S3 AP → FlexCache SMB
    if args.smb_share and args.smb_user and args.smb_pass:
        smb_mount = "/mnt/s3burst_fc_smb"
        print("Mounting SMB...")
        mount_smb(args.nfs_lif, args.smb_share, smb_mount, args.smb_user, args.smb_pass)
        time.sleep(2)
        lat = measure_s3_to_file(
            s3,
            args.s3ap_alias,
            smb_mount,
            args.iterations,
            "Dir 5: S3 AP PutObject → FlexCache SMB read",
        )
        results["directions"]["s3ap_to_fc_smb"] = percentiles(lat)
        results["metadata"]["smb_mount_options"] = "vers=3.0,sec=ntlmssp,cache=none"
        print(f"    → {percentiles(lat)}\n")
        subprocess.run(["umount", smb_mount], capture_output=True)

    # Cleanup mounts
    subprocess.run(["umount", nfs_fc], capture_output=True)
    subprocess.run(["umount", nfs_origin], capture_output=True)

    # Output
    print("=== Results ===")
    print(json.dumps(results, indent=2))

    if args.output:
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
