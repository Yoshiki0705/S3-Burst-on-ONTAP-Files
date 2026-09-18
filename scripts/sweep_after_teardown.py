#!/usr/bin/env python3
"""Find what a teardown leaves behind and still bills for.

WHY THIS EXISTS

Deleting the stack is not the end of the charge. Four kinds of resource outlive it, and each one
was found by reading a bill rather than by a check:

  1. **Final backups.** CloudFormation takes a backup when it deletes a volume, and
     `SkipFinalBackup` is not a property `AWS::FSx::Volume` accepts -- so it always happens. The
     backup outlives the file system at $0.05 per GB-month; 516 GiB of it came to about $26 a
     month. **It carries no tags and its `FileSystem.FileSystemId` is null**, so a tag-filtered
     sweep misses it entirely. Five of them were left behind on 2026-09-18 alone.
  2. **Unattached EBS volumes.** Four io2 volumes nobody noticed came to $361 a month, almost all
     of it provisioned IOPS rather than capacity.
  3. **Secrets.** Nothing in the teardown path touches Secrets Manager, so the fsxadmin and
     directory-admin secrets stay, and a rebuild under the same name then collides with the
     recovery window.
  4. **Volumes and SVMs whose parent is gone.** A FlexCache deleted on the ONTAP side leaves the
     FSx record, and that record then blocks the SVM deletion with
     `Cannot delete storage virtual machine while it has non-root volumes`.

Default is a report. `--delete` acts, and it requires `--yes` as well: every one of these is a
deletion, and three of the four cannot be undone.

    sweep_after_teardown.py --region ap-northeast-1 --name-prefix s3burst
    sweep_after_teardown.py --region ap-northeast-1 --name-prefix s3burst --delete --yes

**`--name-prefix` narrows the secrets only, and deliberately does not narrow the backups**: they
have no name to match on, which is the whole reason they get missed. It is repeatable and defaults
to several fragments, because the first version of this script defaulted to one and found none
while five secrets sat there under a different spelling. Read the report before deleting in a
shared account -- the backup section lists every backup in the Region, including other people's.

Exit codes: 0 nothing left, 1 something is still billing (or was deleted, with --delete),
2 a check could not run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys


class SweepFailed(Exception):
    """A read did not work. Not the same as a read that found nothing."""


def aws(*args: str) -> str:
    result = subprocess.run(["aws", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise SweepFailed(result.stderr.strip()[:300])
    return result.stdout.strip()


def aws_json(*args: str):
    raw = aws(*args, "--output", "json")
    return json.loads(raw or "null")


def backups(region: str) -> list[dict]:
    """Every FSx backup in the Region, with no filter at all.

    Filtering is what makes these invisible. They have no tags, and the volume they came from is
    gone, so the only reliable question is "what backups exist", answered in full and read by a
    human against what was just torn down.
    """
    found = aws_json(
        "fsx",
        "describe-backups",
        "--region",
        region,
        "--query",
        "Backups[].{Id:BackupId,Created:CreationTime,Life:Lifecycle,Type:Type,"
        "Vol:Volume.Name,Fs:FileSystem.FileSystemId,Size:Volume.OntapConfiguration.SizeInBytes}",
    )
    return found or []


def unattached_volumes(region: str) -> list[dict]:
    found = aws_json(
        "ec2",
        "describe-volumes",
        "--region",
        region,
        "--filters",
        "Name=status,Values=available",
        "--query",
        "Volumes[].{Id:VolumeId,Size:Size,Type:VolumeType,Iops:Iops,Created:CreateTime,"
        "Name:Tags[?Key=='Name']|[0].Value}",
    )
    return found or []


def secrets(region: str, prefixes: list[str]) -> list[dict]:
    """Secrets whose name contains any of the given fragments.

    **A list rather than one string, because one string was already wrong.** The first version of
    this script defaulted to `s3burst` and found none, while five secrets sat there named
    `s3-burst-on-ontap-files/...` -- the template builds the name from `ProjectName`, which is
    hyphenated, and the stack names are not. A filter that matches the stack name misses the
    secrets the stack created.
    """
    clauses = " || ".join(f"contains(Name,'{p}')" for p in prefixes)
    found = aws_json(
        "secretsmanager",
        "list-secrets",
        "--region",
        region,
        "--include-planned-deletion",
        "--query",
        f"SecretList[?{clauses}].{{Name:Name,Deleted:DeletedDate}}",
    )
    return found or []


def orphan_storage(region: str) -> tuple[list[dict], list[dict]]:
    """Volumes and SVMs whose file system is no longer in the Region.

    Read as two lists rather than one: an SVM with a leftover volume fails to delete, and the
    volume is the thing to remove first.
    """
    live = {
        fs["Id"]
        for fs in (
            aws_json(
                "fsx",
                "describe-file-systems",
                "--region",
                region,
                "--query",
                "FileSystems[].{Id:FileSystemId}",
            )
            or []
        )
    }
    volumes = [
        v
        for v in (
            aws_json(
                "fsx",
                "describe-volumes",
                "--region",
                region,
                "--query",
                "Volumes[].{Id:VolumeId,Name:Name,Fs:FileSystemId,Life:Lifecycle}",
            )
            or []
        )
        if v["Fs"] not in live
    ]
    svms = [
        s
        for s in (
            aws_json(
                "fsx",
                "describe-storage-virtual-machines",
                "--region",
                region,
                "--query",
                "StorageVirtualMachines[].{Id:StorageVirtualMachineId,Name:Name,Fs:FileSystemId,Life:Lifecycle}",
            )
            or []
        )
        if s["Fs"] not in live
    ]
    return volumes, svms


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument(
        "--name-prefix",
        action="append",
        default=None,
        help="repeatable fragment matched against secret names. Defaults to both the project name "
        "and the stack prefix, because they differ: secrets are named from ProjectName "
        "(hyphenated) and stacks are not. Backups have no name to match on at all",
    )
    parser.add_argument(
        "--delete",
        action="store_true",
        help="delete what is found. Backups and EBS volumes cannot be recovered afterwards",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="required with --delete. Without it the deletions are listed and not performed",
    )
    parser.add_argument(
        "--secret-recovery-days",
        type=int,
        default=7,
        help="recovery window for scheduled secret deletion, so the one reversible deletion here "
        "stays reversible",
    )
    args = parser.parse_args()

    if args.delete and not args.yes:
        print(
            "--delete needs --yes. Backups, EBS volumes and FSx volumes cannot be recovered "
            "afterwards; only the secrets keep a recovery window"
        )
        return 2

    prefixes = args.name_prefix or ["s3-burst-on-ontap-files", "s3burst", "perfmatrix"]
    acting = args.delete and args.yes
    leftovers = 0

    try:
        print("FSx backups in this Region (no filter: they carry no tags)")
        for backup in backups(args.region):
            size = backup.get("Size")
            gib = f"{int(size) / 1024**3:.0f} GiB" if size else "size unknown"
            print(
                f"  {backup['Id']} {backup['Life']} {backup['Type']} {gib} "
                f"created={backup['Created']} volume={backup['Vol']} fs={backup['Fs']}"
            )
            leftovers += 1
            if acting:
                aws(
                    "fsx",
                    "delete-backup",
                    "--region",
                    args.region,
                    "--backup-id",
                    backup["Id"],
                )
                print("    deleted")

        print("unattached EBS volumes (provisioned IOPS is usually the bigger charge)")
        for volume in unattached_volumes(args.region):
            print(
                f"  {volume['Id']} {volume['Size']} GiB {volume['Type']} iops={volume['Iops']} "
                f"created={volume['Created']} name={volume['Name']}"
            )
            leftovers += 1
            if acting:
                aws(
                    "ec2",
                    "delete-volume",
                    "--region",
                    args.region,
                    "--volume-id",
                    volume["Id"],
                )
                print("    deleted")

        print(f"secrets matching any of {prefixes}")
        for secret in secrets(args.region, prefixes):
            state = "scheduled" if secret["Deleted"] else "active"
            print(f"  {secret['Name']} {state}")
            if secret["Deleted"]:
                continue
            leftovers += 1
            if acting:
                aws(
                    "secretsmanager",
                    "delete-secret",
                    "--region",
                    args.region,
                    "--secret-id",
                    secret["Name"],
                    "--recovery-window-in-days",
                    str(args.secret_recovery_days),
                )
                print(
                    f"    deletion scheduled, {args.secret_recovery_days}-day recovery window"
                )

        print("FSx volumes and SVMs whose file system is gone")
        orphan_volumes, orphan_svms = orphan_storage(args.region)
        for volume in orphan_volumes:
            print(
                f"  volume {volume['Id']} {volume['Name']} fs={volume['Fs']} {volume['Life']}"
            )
            leftovers += 1
        for svm in orphan_svms:
            print(f"  svm    {svm['Id']} {svm['Name']} fs={svm['Fs']} {svm['Life']}")
            leftovers += 1
        if (orphan_volumes or orphan_svms) and acting:
            print(
                "    not deleted by this script. Delete the volume first, then the SVM: an SVM "
                "with a non-root volume refuses with a message that names the volume"
            )
    except SweepFailed as error:
        print(f"COULD NOT RUN: {error}")
        return 2

    if leftovers:
        verb = "deleted or scheduled" if acting else "still present"
        print(f"\nsweep: {leftovers} item(s) {verb}")
        return 1
    print("\nsweep: nothing left behind")
    return 0


if __name__ == "__main__":
    sys.exit(main())
