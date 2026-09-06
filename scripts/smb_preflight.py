#!/usr/bin/env python3
"""Read the four things an SMB mount needs, and fail with the reason when one is missing.

WHY THIS EXISTS

On 2026-09-06 the SMB measurement stalled three times in a row, and all three were the same
mistake: a name was inferred from adjacent data instead of read from the API that owns it.

  1. The volume's junction path was used as the share name. There is no share by that name --
     SMB addresses a share, and a share is a separate ONTAP object that has to be created.
  2. The SVM name was spelled with underscores because the volume names are. It is hyphenated.
  3. The bench account was assumed to exist because its secret did. The directory was new.

The third is the reason this is a script and not a checklist. **A missing account surfaces as
`The specified network password is not correct.`** Read that message and you will spend the next
half hour on the secret. The other two are equally misleading: a missing share reports
`The network name cannot be found.`, which reads like a path or DNS problem.

So this reads state before anything is mounted, and names what is absent. It asserts nothing
about throughput; it only removes the three ways the run has already failed to start.

Mechanism and sources: docs/ja/reference/limits/smb-share-and-identifier-reading.md

Exit codes: 0 all four present, 1 something missing (the reason is on stdout), 2 could not run.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time


def aws(*args: str) -> str:
    result = subprocess.run(["aws", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip()[:300])
    return result.stdout.strip()


def ontap_get(instance: str, region: str, secret_arn: str, mgmt: str, path: str) -> str:
    """Run a read-only ONTAP REST GET from the client, which is inside the VPC.

    The management endpoint has no public address, so this machine cannot reach it. The client
    can. Read-only on purpose: a preflight that changes state is not a preflight.
    """
    fetch = (
        f"PW=$(aws secretsmanager get-secret-value --region {region} --secret-id {secret_arn}"
        " --query SecretString --output text"
        " | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"password\"])')"
    )
    curl = f'curl -s -k -u "fsxadmin:$PW" "https://{mgmt}{path}"'
    payload = {"Parameters": {"commands": ["set -uo pipefail", fetch, curl]}}
    with open("/tmp/smb_preflight_cmd.json", "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    command_id = aws(
        "ssm",
        "send-command",
        "--instance-ids",
        instance,
        "--document-name",
        "AWS-RunShellScript",
        "--timeout-seconds",
        "300",
        "--cli-input-json",
        "file:///tmp/smb_preflight_cmd.json",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    )
    for _ in range(20):
        time.sleep(10)
        raw = aws(
            "ssm",
            "get-command-invocation",
            "--command-id",
            command_id,
            "--instance-id",
            instance,
            "--query",
            "{S:Status,O:StandardOutputContent}",
            "--output",
            "json",
        )
        data = json.loads(raw or "{}")
        if data.get("S") in ("Success", "Failed", "TimedOut"):
            return data.get("O") or ""
    raise RuntimeError(
        "the ONTAP read did not finish; it is not a report that nothing is there"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file-system-id", required=True)
    parser.add_argument(
        "--svm-name", required=True, help="read it, do not derive it from a volume name"
    )
    parser.add_argument("--share", required=True)
    parser.add_argument(
        "--account", required=True, help="the domain account the mount will use"
    )
    parser.add_argument(
        "--client-instance-id",
        required=True,
        help="a running Linux client, for the ONTAP read",
    )
    parser.add_argument(
        "--windows-instance-id",
        required=True,
        help="a joined Windows host, for the account lookup",
    )
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--fsxadmin-secret-arn", required=True)
    args = parser.parse_args()

    findings: list[str] = []

    # 1. The SVM, by name. Reading it here is the check: a typo fails now rather than at mount time.
    try:
        raw = aws(
            "fsx",
            "describe-storage-virtual-machines",
            "--query",
            f"StorageVirtualMachines[?Name=='{args.svm_name}']"
            ".{Id:StorageVirtualMachineId,Life:Lifecycle,Net:ActiveDirectoryConfiguration.NetBiosName}",
            "--output",
            "json",
        )
        svms = json.loads(raw or "[]")
    except RuntimeError as error:
        print(f"could not read the SVMs: {error}")
        return 2
    if not svms:
        names = aws(
            "fsx",
            "describe-storage-virtual-machines",
            "--query",
            "StorageVirtualMachines[].Name",
            "--output",
            "text",
        )
        findings.append(
            f"no SVM named {args.svm_name!r}. Present: {names or '(none)'}. "
            "Do not derive this from a volume name -- the separators differ."
        )
    else:
        svm = svms[0]
        print(f"  svm      {args.svm_name} {svm['Life']} netbios={svm['Net']}")
        if not svm["Net"]:
            findings.append(
                "the SVM has no NetBIOS name, so the domain join has not completed"
            )

    # 2 and 3. The share has to exist, and its path has to be a real junction path.
    junctions = json.loads(
        aws(
            "fsx",
            "describe-volumes",
            "--query",
            f"Volumes[?FileSystemId=='{args.file_system_id}']"
            ".{P:OntapConfiguration.JunctionPath,N:Name}",
            "--output",
            "json",
        )
        or "[]"
    )
    known_paths = {volume["P"] for volume in junctions if volume["P"]}

    mgmt = aws(
        "fsx",
        "describe-file-systems",
        "--file-system-ids",
        args.file_system_id,
        "--query",
        "FileSystems[0].OntapConfiguration.Endpoints.Management.IpAddresses[0]",
        "--output",
        "text",
    )
    try:
        body = ontap_get(
            args.client_instance_id,
            args.region,
            args.fsxadmin_secret_arn,
            mgmt,
            "/api/protocols/cifs/shares?fields=name,path,svm.name",
        )
        shares = json.loads(body).get("records", [])
    except Exception as error:  # noqa: BLE001 - the reason is what matters here
        print(f"could not read the CIFS shares: {error}")
        return 2

    # A hidden administrative share is not a data share. c$ is the SVM root with an ACL of
    # BUILTIN\administrator, so mounting it needs Domain Admins and changes what the figure means.
    data_shares = {
        s["name"]: s.get("path") for s in shares if not s["name"].endswith("$")
    }
    admin_shares = sorted(s["name"] for s in shares if s["name"].endswith("$"))
    print(
        f"  shares   data={sorted(data_shares) or '(none)'} administrative={admin_shares}"
    )

    if args.share not in data_shares:
        findings.append(
            f"no CIFS share named {args.share!r}. Administrative shares present: {admin_shares}. "
            "Those are not data shares -- create one with POST /api/protocols/cifs/shares. "
            "A missing share reports 'The network name cannot be found.' at the client."
        )
    else:
        path = data_shares[args.share]
        print(f"  path     {args.share} -> {path}")
        if path not in known_paths:
            findings.append(
                f"share {args.share!r} points at {path!r}, which is not a junction path on "
                f"{args.file_system_id}. Known: {sorted(known_paths)}"
            )

    # 4. The account, in the directory. The secret is a container for a value, not for an account.
    ps = (
        "$ErrorActionPreference='Continue';"
        f"$u='{args.account}';"
        "try {"
        " $s=New-Object System.DirectoryServices.DirectorySearcher;"
        ' $s.Filter="(sAMAccountName=$u)";'
        " $r=$s.FindOne();"
        " if ($r) { \"FOUND \" + $r.Path } else { 'ABSENT' }"
        "} catch { 'LOOKUP-FAILED ' + $_.Exception.Message }"
    )
    with open("/tmp/smb_preflight_ps.json", "w", encoding="utf-8") as handle:
        json.dump(
            {
                "InstanceIds": [args.windows_instance_id],
                "DocumentName": "AWS-RunPowerShellScript",
                "Parameters": {"commands": [ps]},
            },
            handle,
        )
    command_id = aws(
        "ssm",
        "send-command",
        "--cli-input-json",
        "file:///tmp/smb_preflight_ps.json",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    )
    account_state = "(no answer)"
    for _ in range(20):
        time.sleep(10)
        data = json.loads(
            aws(
                "ssm",
                "get-command-invocation",
                "--command-id",
                command_id,
                "--instance-id",
                args.windows_instance_id,
                "--query",
                "{S:Status,O:StandardOutputContent}",
                "--output",
                "json",
            )
            or "{}"
        )
        if data.get("S") in ("Success", "Failed", "TimedOut"):
            account_state = (
                (data.get("O") or "").strip().splitlines()[0]
                if data.get("O")
                else "(empty)"
            )
            break
    print(f"  account  {args.account} {account_state}")
    if not account_state.startswith("FOUND"):
        findings.append(
            f"the domain account {args.account!r} does not resolve in the directory "
            f"({account_state}). The secret existing is not the account existing. "
            "A missing account surfaces at the client as "
            "'The specified network password is not correct.'"
        )

    if findings:
        print("\nsmb-preflight failed:")
        for finding in findings:
            print(f"  - {finding}")
        print(
            "\n  Mechanism and sources: docs/ja/reference/limits/smb-share-and-identifier-reading.md"
        )
        return 1

    print(
        "\nsmb-preflight: SVM, data share, junction path and domain account all read back present"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
