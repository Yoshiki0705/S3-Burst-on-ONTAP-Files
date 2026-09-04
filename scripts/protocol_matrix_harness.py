#!/usr/bin/env python3
"""Drive auto_vdbench across the protocol matrix, one mount at a time.

This does not measure anything by itself. It mounts a target with one protocol, records the mount
options that are *actually* in effect, hands the path to auto_vdbench, and files the result under a
directory named after the case. Then it unmounts and moves to the next one.

Why a wrapper rather than running auto_vdbench directly: the thing being varied here is the protocol,
which auto_vdbench does not know about. It measures whatever path it is given. So the protocol has to
be established outside it, and the evidence that it was established -- the effective mount options --
has to be captured before the measurement, not inferred from the case name afterwards.

Three things it refuses to do, each because the alternative produces a number that looks fine:

1. **It will not report a case it could not mount.** An unsupported protocol is an absent row, not a
   zero. `--dry-run` prints which cases would be skipped and why, from the documented support matrix,
   before anything is created. SMB is reported separately again: it is supported by FSx for ONTAP but
   mounted from Windows, so this script does not drive it and says so rather than implying it will.
2. **It records effective mount options, not requested ones.** `rsize=1048576` can be requested and
   granted as 65536 while the mount still succeeds.
3. **It will not drive the S3 API.** auto_vdbench runs VDBENCH against a mounted path; VDBENCH has no
   object workload. The A-1 case in the plan uses `measure_s3_throughput.py`, and the two results
   carry different instruments, which the report has to say.

Support status comes from docs/ja/verification/protocol-matrix-efs-vs-ontap.md. Keep the two in step:
this table is what makes the tool skip a case instead of failing halfway through it.

Usage:
    ./protocol_matrix_harness.py --dry-run
    ./protocol_matrix_harness.py --target ontap --host <mgmt-ip> --export /vol1 --mount-root /mnt/bench
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

# --- the matrix ----------------------------------------------------------------------------------

# Keyed on (target, protocol). False means the combination is documented as unsupported, so the case
# is skipped with that reason rather than attempted and reported as a failure. See
# docs/ja/verification/protocol-matrix-efs-vs-ontap.md for the citations.
SUPPORTED: dict[tuple[str, str], bool] = {
    ("efs", "nfsv4.0"): True,
    ("efs", "nfsv4.1"): True,
    ("efs", "nfsv3"): False,
    ("efs", "nfsv4.2"): False,
    ("efs", "smb"): False,
    ("ontap", "nfsv3"): True,
    ("ontap", "nfsv4.0"): True,
    ("ontap", "nfsv4.1"): True,
    ("ontap", "nfsv4.2"): True,
    ("ontap", "smb"): True,
}

UNSUPPORTED_REASON: dict[tuple[str, str], str] = {
    (
        "efs",
        "nfsv3",
    ): "Amazon EFS supports NFSv4.0 and NFSv4.1 only; NFSv2 and NFSv3 are not supported",
    ("efs", "nfsv4.2"): "NFSv4.2 is not listed among the protocols Amazon EFS supports",
    (
        "efs",
        "smb",
    ): "Mounting an EFS file system from an EC2 instance running Windows is not supported",
}

# The mount option that selects each version. NFSv4.2 has no `nfsvers=4.2` spelling on every client,
# so it is requested as 4.2 and the effective version is read back from /proc/mounts rather than
# assumed -- a client that silently negotiates 4.1 would otherwise be recorded as 4.2.
NFS_VERS = {
    "nfsv3": "3",
    "nfsv4.0": "4.0",
    "nfsv4.1": "4.1",
    "nfsv4.2": "4.2",
}


@dataclass
class Case:
    target: str
    protocol: str
    mount_point: Path
    supported: bool
    reason: str = ""
    effective_options: str = ""
    status: str = "pending"
    notes: list[str] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"{self.target}-{self.protocol}".replace(".", "")


# --- shell ---------------------------------------------------------------------------------------


def run(cmd: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    """Run a command with its arguments as a list, never as a shell string.

    Values here come from the command line and end up next to a host and an export path, so a shell
    string would be an injection point for anyone who can influence either.
    """
    return subprocess.run(cmd, capture_output=True, text=True, check=check)


def effective_mount_options(mount_point: Path) -> str:
    """Read what the kernel actually granted, not what was asked for.

    /proc/mounts is the source: `mount -o` reports the request. The difference matters because a
    downgraded `rsize` still produces a mount that works and a measurement that is not the one
    intended.
    """
    text = Path("/proc/mounts").read_text(encoding="utf-8")
    target = str(mount_point)
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == target:
            return parts[3]
    return ""


# --- the run -------------------------------------------------------------------------------------


def build_cases(target: str, mount_root: Path, protocols: list[str]) -> list[Case]:
    cases = []
    for protocol in protocols:
        key = (target, protocol)
        supported = SUPPORTED.get(key)
        if supported is None:
            raise SystemExit(
                f"protocol_matrix_harness: no support status recorded for {key}"
            )
        cases.append(
            Case(
                target=target,
                protocol=protocol,
                mount_point=mount_root / f"{target}-{protocol}".replace(".", ""),
                supported=supported,
                reason=""
                if supported
                else UNSUPPORTED_REASON.get(key, "documented as unsupported"),
            )
        )
    return cases


def mount_case(case: Case, host: str, export: str) -> None:
    if case.protocol == "smb":
        raise SystemExit(
            "protocol_matrix_harness: SMB is mounted from a Windows client, which this script does "
            "not drive. Run auto_vdbench there and file the result under the same case name."
        )
    case.mount_point.mkdir(parents=True, exist_ok=True)
    options = (
        f"nfsvers={NFS_VERS[case.protocol]},rsize=1048576,wsize=1048576,hard,timeo=600"
    )
    run(
        [
            "sudo",
            "mount",
            "-t",
            "nfs",
            "-o",
            options,
            f"{host}:{export}",
            str(case.mount_point),
        ]
    )
    case.effective_options = effective_mount_options(case.mount_point)
    if not case.effective_options:
        case.notes.append(
            "mounted but absent from /proc/mounts; effective options unknown"
        )
    for option in ("rsize=1048576", "wsize=1048576"):
        if option not in case.effective_options:
            case.notes.append(
                f"requested {option} was not granted; see the effective options"
            )
    expected = f"vers={NFS_VERS[case.protocol]}"
    if expected not in case.effective_options.replace("nfsvers=", "vers="):
        case.notes.append(
            f"requested {expected} but the effective options do not show it; the client may have "
            "negotiated a different version"
        )


def unmount_case(case: Case) -> None:
    run(["sudo", "umount", str(case.mount_point)], check=False)


def measure(
    case: Case, auto_vdbench: Path, report_root: Path, extra: list[str]
) -> None:
    report_dir = report_root / case.name
    cmd = [
        str(auto_vdbench),
        "start",
        "--report-dir",
        str(report_dir),
        "--dedup-ratio",
        "1",
        "--compression-ratio",
        "1",
        "--graph-title",
        f"{case.target} {case.protocol}",
        *extra,
    ]
    print(f"  -> {shlex.join(cmd)}")
    result = run(cmd, check=False)
    case.status = (
        "measured" if result.returncode == 0 else f"failed rc={result.returncode}"
    )
    if result.returncode != 0:
        case.notes.append(result.stderr.strip()[:400])


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=["efs", "ontap"], required=False)
    parser.add_argument("--host", help="NFS server address")
    parser.add_argument("--export", help="Export path on the server")
    parser.add_argument("--mount-root", type=Path, default=Path("/mnt/bench"))
    parser.add_argument("--report-root", type=Path, default=Path("report"))
    parser.add_argument("--auto-vdbench", type=Path, default=Path("auto_vdbench.py"))
    parser.add_argument(
        "--protocols",
        nargs="+",
        default=["nfsv3", "nfsv4.0", "nfsv4.1", "nfsv4.2", "smb"],
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print which cases would run and which are skipped, without mounting anything",
    )
    parser.add_argument(
        "--summary", type=Path, help="Write a JSON summary of the run here"
    )
    args, extra = parser.parse_known_args()

    if args.dry_run and not args.target:
        targets = ["efs", "ontap"]
    elif args.target:
        targets = [args.target]
    else:
        parser.error("--target is required unless --dry-run is used")

    all_cases: list[Case] = []
    for target in targets:
        all_cases.extend(build_cases(target, args.mount_root, args.protocols))

    if args.dry_run:
        print("case                     status      reason")
        for case in all_cases:
            if not case.supported:
                state, reason = "skip", case.reason
            elif case.protocol == "smb":
                # Supported by the target, but not by this script: it mounts from Linux. Saying
                # "would run" here would imply the run covers it, and the gap would only surface
                # afterwards, as a missing row nobody was expecting.
                state = "elsewhere"
                reason = "run auto_vdbench on the Windows client; this script does not drive SMB"
            else:
                state, reason = "would run", ""
            print(f"{case.name:24s} {state:11s} {reason}")
        print(
            "\nSupport status is documented, not measured. "
            "See docs/ja/verification/protocol-matrix-efs-vs-ontap.md"
        )
        return 0

    if not (args.host and args.export):
        parser.error("--host and --export are required for a real run")

    for case in all_cases:
        print(f"[{case.name}]")
        if not case.supported:
            case.status = "skipped-unsupported"
            print(f"  skipped: {case.reason}")
            continue
        try:
            mount_case(case, args.host, args.export)
            print(f"  effective options: {case.effective_options}")
            for note in case.notes:
                print(f"  note: {note}")
            measure(case, args.auto_vdbench, args.report_root, extra)
        finally:
            unmount_case(case)

    summary = {
        "generated_at": datetime.now(UTC).isoformat(),
        "note": (
            "Support status is documented; throughput is measured. Skipped cases are unsupported, "
            "not slow. File-protocol figures come from VDBENCH via auto_vdbench and are not "
            "comparable instrument-for-instrument with S3 API figures."
        ),
        "cases": [
            {
                "case": c.name,
                "target": c.target,
                "protocol": c.protocol,
                "supported": c.supported,
                "status": c.status,
                "effective_mount_options": c.effective_options,
                "reason": c.reason,
                "notes": c.notes,
            }
            for c in all_cases
        ],
    }
    text = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.summary:
        args.summary.write_text(text + "\n", encoding="utf-8")
        print(f"\nwrote {args.summary}")
    else:
        print("\n" + text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
