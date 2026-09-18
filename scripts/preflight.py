#!/usr/bin/env python3
"""Check the things that make a run fail late, before it fails late.

WHY THIS EXISTS

Every check here was written after the failure it prevents, and each of those failures cost
between twenty minutes and a whole environment:

  1. **Regional throughput-capacity quota.** The total across every FSx for ONTAP file system in
     one Region is capped, the cap is shared with other people's file systems in the same account,
     and exceeding it fails *at creation* -- so the error arrives about 25 minutes in. Three
     environments were being built in parallel on 2026-09-18 and the third was refused, which cost
     the time plus a rebuild of the one that had to be deleted to make room.
  2. **Session Manager reachability.** A host in a subnet with no NAT gateway, no internet gateway
     and no interface endpoints comes up healthy and is simply absent from Session Manager. Nothing
     reports why. Twenty minutes, twice.
  3. **The ONTAP release.** `FileSystemTypeVersion` is null for FSx for ONTAP, so a run that reads
     only the AWS side records no release -- and it cannot be recovered after teardown. Two
     consecutive sessions shipped a full set of numbers with no release, then a third did it again
     because the gate that reads it lived in one runbook and that session used a different path.
     **That is the reason this is a standalone script rather than another runbook phase.**
  4. **Defaults that silently invalidate a measurement.** The NVMe read cache, automatic backups,
     the snapshot policy and inline efficiency each change what a number means without making the
     number look unusual.

None of this can live in CloudFormation. Check 1 has to run before the stack exists, and checks 3
and 4 read ONTAP, which has no AWS API and no public endpoint -- they go through a client inside
the VPC over Systems Manager.

Two subcommands, because they belong to different moments:

    preflight.py pre   --region … --vpc-id … --subnet-id … --throughput-capacity …
    preflight.py post  --file-system-id … --instance-id … --fsxadmin-secret-arn …

Exit codes: 0 nothing blocking, 1 a finding (printed, with what to do), 2 a check could not run.

**A check that could not run exits 2 rather than passing.** An empty answer and a healthy answer
look identical once they are summarised, and they mean opposite things.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time

# The quota codes, read from `aws service-quotas list-service-quotas --service-code fsx`
# (2026-09-19). Both are adjustable, so the applied value is read per account rather than assumed;
# the documented defaults below are only used to say what the number would be if it could not be
# read, and that case is a finding, not a pass.
QUOTA_THROUGHPUT = "L-C5F860DD"  # ONTAP throughput capacity, MB/s, Region-wide total
QUOTA_SSD = "L-E2C89679"  # ONTAP SSD storage capacity, GiB, Region-wide total
DOCUMENTED_DEFAULT_THROUGHPUT = 10240
DOCUMENTED_DEFAULT_SSD = 1048576

# The three interface endpoints Session Manager needs when a subnet has no route to the internet.
SSM_ENDPOINTS = ("ssm", "ssmmessages", "ec2messages")


class CheckFailed(Exception):
    """A check could not be performed. Distinct from a check that ran and found a problem."""


def aws(*args: str) -> str:
    result = subprocess.run(["aws", *args], capture_output=True, text=True)
    if result.returncode != 0:
        raise CheckFailed(result.stderr.strip()[:300])
    return result.stdout.strip()


def aws_json(*args: str):
    raw = aws(*args, "--output", "json")
    return json.loads(raw or "null")


def applied_quota(region: str, code: str, documented_default: int) -> tuple[int, str]:
    """The quota as it applies to this account, with where the figure came from.

    An increase that has been granted is only visible through `get-service-quota`; the default
    list would understate it and turn a legitimate build into a false alarm. When neither call
    works -- usually a missing `servicequotas:GetServiceQuota` -- the documented default is
    returned together with a source string that says so, and the caller reports it as a finding.
    """
    try:
        data = aws_json(
            "service-quotas",
            "get-service-quota",
            "--region",
            region,
            "--service-code",
            "fsx",
            "--quota-code",
            code,
        )
        return int(data["Quota"]["Value"]), "applied quota for this account"
    except (CheckFailed, KeyError, TypeError, ValueError):
        pass
    try:
        data = aws_json(
            "service-quotas",
            "get-aws-default-service-quota",
            "--region",
            region,
            "--service-code",
            "fsx",
            "--quota-code",
            code,
        )
        return int(
            data["Quota"]["Value"]
        ), "AWS default (the account's own value was not readable)"
    except (CheckFailed, KeyError, TypeError, ValueError):
        return (
            documented_default,
            "NOT READ -- the documented default, which may be wrong here",
        )


def ssm_shell(instance: str, region: str, script: list[str]) -> str:
    """Run a read-only shell snippet on a client and return its stdout.

    The payload goes in as a file rather than through the `--parameters` shorthand: the shorthand
    is parsed by the CLI and cannot survive the nested quoting a curl-plus-python line needs.
    """
    payload = {"Parameters": {"commands": ["set -uo pipefail", *script]}}
    path = "/tmp/preflight_cmd.json"
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    command_id = aws(
        "ssm",
        "send-command",
        "--region",
        region,
        "--instance-ids",
        instance,
        "--document-name",
        "AWS-RunShellScript",
        "--timeout-seconds",
        "300",
        "--cli-input-json",
        f"file://{path}",
        "--query",
        "Command.CommandId",
        "--output",
        "text",
    )
    for _ in range(24):
        time.sleep(10)
        data = aws_json(
            "ssm",
            "get-command-invocation",
            "--region",
            region,
            "--command-id",
            command_id,
            "--instance-id",
            instance,
            "--query",
            "{S:Status,O:StandardOutputContent,E:StandardErrorContent}",
        )
        if data.get("S") in ("Success", "Failed", "TimedOut"):
            if data.get("S") != "Success" and not data.get("O"):
                raise CheckFailed(
                    f"the command on {instance} ended {data.get('S')}: "
                    f"{(data.get('E') or '')[:200]}"
                )
            return data.get("O") or ""
    raise CheckFailed(
        "the read did not finish in four minutes. That is not a report that the state is fine"
    )


def ontap_get(
    instance: str, region: str, secret_arn: str, fs_id: str, path: str
) -> dict:
    """GET one ONTAP REST path from inside the VPC, as JSON.

    The password is fetched on the client rather than passed in, because a Run Command's
    parameters are retained in the Systems Manager command history.
    """
    mgmt = f"management.{fs_id}.fsx.{region}.amazonaws.com"
    fetch = (
        f"PW=$(aws secretsmanager get-secret-value --region {region} --secret-id {secret_arn}"
        " --query SecretString --output text"
        " | python3 -c 'import json,sys;print(json.load(sys.stdin)[\"password\"])')"
    )
    curl = f'curl -s -k -m 60 -u "fsxadmin:$PW" "https://{mgmt}{path}"'
    body = ssm_shell(instance, region, [fetch, curl])
    try:
        return json.loads(body)
    except json.JSONDecodeError as error:
        raise CheckFailed(
            f"the cluster did not return JSON for {path}: {body[:200]!r}"
        ) from error


# ---------------------------------------------------------------------------------- pre


def check_quota(region: str, want_mbps: int, want_ssd_gib: int) -> list[str]:
    """Whether this Region has room for the file system about to be created.

    The pool is per Region and per account, so it includes file systems belonging to other work.
    They are listed rather than summed silently: "someone else's 6,144" is the actionable form.
    """
    findings: list[str] = []
    systems = aws_json(
        "fsx",
        "describe-file-systems",
        "--region",
        region,
        "--query",
        "FileSystems[?FileSystemType=='ONTAP']"
        ".{Id:FileSystemId,MBps:OntapConfiguration.ThroughputCapacity,SSD:StorageCapacity,Life:Lifecycle}",
    )
    systems = systems or []
    used_mbps = sum(int(s["MBps"] or 0) for s in systems)
    used_ssd = sum(int(s["SSD"] or 0) for s in systems)

    limit_mbps, mbps_source = applied_quota(
        region, QUOTA_THROUGHPUT, DOCUMENTED_DEFAULT_THROUGHPUT
    )
    limit_ssd, ssd_source = applied_quota(region, QUOTA_SSD, DOCUMENTED_DEFAULT_SSD)

    print(f"  quota    throughput limit {limit_mbps} MB/s ({mbps_source})")
    print(f"           SSD limit {limit_ssd} GiB ({ssd_source})")
    for s in systems:
        print(
            f"           in use: {s['Id']} {s['MBps']} MB/s {s['SSD']} GiB {s['Life']}"
        )
    print(f"           total in use {used_mbps} MB/s, {used_ssd} GiB")
    print(f"           about to add {want_mbps} MB/s, {want_ssd_gib} GiB")

    if "NOT READ" in mbps_source or "NOT READ" in ssd_source:
        findings.append(
            "the quota could not be read, so the headroom below is against a documented default "
            "rather than this account's value. Grant servicequotas:GetServiceQuota, or read it in "
            "the console, before trusting the margin"
        )
    if used_mbps + want_mbps > limit_mbps:
        findings.append(
            f"throughput capacity would reach {used_mbps + want_mbps} MB/s against a limit of "
            f"{limit_mbps}. **Creation fails about 25 minutes in**, with 'can have at most "
            f"{limit_mbps} MB/s of throughput capacity total across file systems in this region'. "
            "Delete or lower a file system first -- freeing a slot took about 4 minutes when "
            "measured -- or request an increase, which is not immediate"
        )
    if used_ssd + want_ssd_gib > limit_ssd:
        findings.append(
            f"SSD capacity would reach {used_ssd + want_ssd_gib} GiB against a limit of {limit_ssd}"
        )
    return findings


def check_subnet(region: str, vpc_id: str, subnet_id: str) -> list[str]:
    """The subnet is in the stated VPC, and a host in it can reach Session Manager."""
    findings: list[str] = []
    subnets = aws_json(
        "ec2",
        "describe-subnets",
        "--region",
        region,
        "--subnet-ids",
        subnet_id,
        "--query",
        "Subnets[].{Vpc:VpcId,Az:AvailabilityZone,Public:MapPublicIpOnLaunch,Free:AvailableIpAddressCount}",
    )
    if not subnets:
        raise CheckFailed(f"subnet {subnet_id} was not found in {region}")
    subnet = subnets[0]
    print(
        f"  subnet   {subnet_id} in {subnet['Vpc']} az={subnet['Az']} "
        f"free-ips={subnet['Free']} auto-public-ip={subnet['Public']}"
    )
    if subnet["Vpc"] != vpc_id:
        findings.append(
            f"subnet {subnet_id} belongs to {subnet['Vpc']}, not to {vpc_id}. "
            "The template puts the file system and the host in this one subnet on purpose"
        )
    if int(subnet["Free"]) < 8:
        findings.append(
            f"only {subnet['Free']} free addresses. The file system takes several ENIs"
        )

    # Session Manager needs either a route off the subnet or the three interface endpoints.
    routes = aws_json(
        "ec2",
        "describe-route-tables",
        "--region",
        region,
        "--filters",
        f"Name=association.subnet-id,Values={subnet_id}",
        "--query",
        "RouteTables[].Routes[].{Dest:DestinationCidrBlock,Nat:NatGatewayId,Igw:GatewayId}",
    )
    if not routes:
        # No explicit association means the VPC main route table applies.
        routes = aws_json(
            "ec2",
            "describe-route-tables",
            "--region",
            region,
            "--filters",
            f"Name=vpc-id,Values={vpc_id}",
            "Name=association.main,Values=true",
            "--query",
            "RouteTables[].Routes[].{Dest:DestinationCidrBlock,Nat:NatGatewayId,Igw:GatewayId}",
        )
    routes = routes or []
    has_egress = any(
        r.get("Dest") == "0.0.0.0/0"
        and (r.get("Nat") or (r.get("Igw") or "").startswith("igw-"))
        for r in routes
    )

    endpoints = aws_json(
        "ec2",
        "describe-vpc-endpoints",
        "--region",
        region,
        "--filters",
        f"Name=vpc-id,Values={vpc_id}",
        "--query",
        "VpcEndpoints[].ServiceName",
    )
    endpoint_names = {name.rsplit(".", 1)[-1] for name in (endpoints or [])}
    missing_endpoints = [name for name in SSM_ENDPOINTS if name not in endpoint_names]

    print(
        f"  ssm      egress-route={has_egress} interface-endpoints-present="
        f"{sorted(endpoint_names & set(SSM_ENDPOINTS)) or '(none)'}"
    )
    if not has_egress and missing_endpoints:
        findings.append(
            "a host here cannot reach Session Manager: there is no 0.0.0.0/0 route through a NAT "
            f"or internet gateway, and these interface endpoints are absent: {missing_endpoints}. "
            "**The instance will come up healthy and be absent from Session Manager**, which is a "
            "confusing way to lose twenty minutes. Either add the endpoints, or deploy with "
            "AssociatePublicIp=true in a subnet that has an internet gateway"
        )
    return findings


# ---------------------------------------------------------------------------------- post


def check_ontap_release(
    instance: str, region: str, secret_arn: str, fs_id: str
) -> list[str]:
    """Read the release from the cluster. This is the gate, not a reminder.

    Grepping for the literal 'NetApp Release' rather than for a non-empty answer: an error page, an
    empty records list and a traceback are all non-empty.
    """
    data = ontap_get(instance, region, secret_arn, fs_id, "/api/cluster?fields=version")
    full = ((data.get("version") or {}).get("full")) or ""
    print(f"  ontap    {full or '(nothing returned)'}")
    if "NetApp Release" not in full:
        return [
            "the cluster did not return a release. **Do not measure without one**: "
            "FileSystemTypeVersion is null for FSx for ONTAP, and after teardown the release "
            "cannot be recovered, so every number from this run would be uncomparable"
        ]
    return []


# Below this, the NVMe read cache is not part of the configuration, so the query returning nothing
# is the answer rather than a failure. AWS documents the cache as present by default on
# first-generation Single-AZ file systems at 2 GBps and above; this script does not try to encode
# the whole matrix, it only separates "no cache here" from "the reader stopped matching".
NVME_CACHE_MIN_MBPS = 2048


def check_nvme_cache(
    instance: str, region: str, secret_arn: str, fs_id: str, allow: bool
) -> list[str]:
    """Every node must report the NVMe read cache disabled before a disk-path read.

    An empty node list normally fails rather than reading as "nothing is enabled" -- those look the
    same once summarised and mean opposite things.

    **The exception was found by running this against the smallest configuration.** On a 128 MBps
    file system the query returns no records at all, because there is no external cache object to
    return, and the first version of this check stopped the quickstart's own environment with
    "could not run". So the throughput capacity is read first: below the threshold an empty answer
    is reported as not applicable, and at or above it an empty answer is still a failure.
    """
    systems = aws_json(
        "fsx",
        "describe-file-systems",
        "--region",
        region,
        "--file-system-ids",
        fs_id,
        "--query",
        "FileSystems[].{MBps:OntapConfiguration.ThroughputCapacity,"
        "Depl:OntapConfiguration.DeploymentType}",
    )
    if not systems:
        raise CheckFailed(f"file system {fs_id} was not found in {region}")
    mbps = int(systems[0]["MBps"] or 0)

    data = ontap_get(
        instance,
        region,
        secret_arn,
        fs_id,
        "/api/private/cli/system/node/external-cache?fields=node,is-enabled",
    )
    records = data.get("records") or []
    if not records and mbps < NVME_CACHE_MIN_MBPS:
        print(
            f"  nvme     not part of this configuration ({mbps} MB/s, "
            f"{systems[0]['Depl']}): the query returned no nodes, which here is the answer"
        )
        return []
    if not records:
        raise CheckFailed(
            f"no nodes came back from the external-cache query on a {mbps} MB/s file system, "
            "which is not the same as the cache being off"
        )
    enabled = [r.get("node") for r in records if r.get("is_enabled")]
    for record in records:
        print(f"  nvme     {record.get('node')} is_enabled={record.get('is_enabled')}")
    if enabled and not allow:
        return [
            f"the NVMe read cache is on for {enabled}. A read taken with it on is served from "
            "cache, so the SSD IOPS setting has no effect on the number. Turn it off "
            "(PATCH the same path with is_enabled false, then re-read: the PATCH returning is not "
            "evidence), or pass --allow-nvme-cache to record deliberately that it was on"
        ]
    if enabled:
        print("           recorded as on, by --allow-nvme-cache")
    return []


def check_measurement_defaults(region: str, fs_id: str) -> list[str]:
    """The four AWS-side settings that change what a number means without looking unusual."""
    findings: list[str] = []
    systems = aws_json(
        "fsx",
        "describe-file-systems",
        "--region",
        region,
        "--file-system-ids",
        fs_id,
        "--query",
        "FileSystems[].{Backup:OntapConfiguration.AutomaticBackupRetentionDays,"
        "MBps:OntapConfiguration.ThroughputCapacity,Iops:OntapConfiguration.DiskIopsConfiguration}",
    )
    if not systems:
        raise CheckFailed(f"file system {fs_id} was not found in {region}")
    system = systems[0]
    iops = system.get("Iops") or {}
    print(
        f"  fs       {system['MBps']} MB/s backup-retention={system['Backup']} "
        f"iops={iops.get('Mode')}/{iops.get('Iops')}"
    )
    if int(system["Backup"] or 0) != 0:
        findings.append(
            f"automatic backups are retained for {system['Backup']} days. A backup's snapshot "
            "holds the blocks an overwrite would have freed, and the volume can reach 100% with "
            "writes dropping to an eighth. `rm` does not give the space back. Set "
            "AutomaticBackupRetentionDays to 0 before writing"
        )
    if (iops.get("Mode") or "") == "AUTOMATIC":
        print(
            "           note: SSD IOPS is AUTOMATIC (3 per GiB). That is the ceiling a read will "
            "hit first -- deliberate for a default-configuration figure, wrong for a disk-path one"
        )

    volumes = aws_json(
        "fsx",
        "describe-volumes",
        "--region",
        region,
        "--query",
        f"Volumes[?FileSystemId=='{fs_id}']"
        ".{Name:Name,Snap:OntapConfiguration.SnapshotPolicy,Eff:OntapConfiguration.StorageEfficiencyEnabled,"
        "Path:OntapConfiguration.JunctionPath}",
    )
    volumes = [v for v in (volumes or []) if v.get("Path") != "/"]
    if not volumes:
        raise CheckFailed(
            "no non-root volume was found on this file system, so nothing could be checked"
        )
    for volume in volumes:
        print(
            f"  volume   {volume['Name']} snapshot-policy={volume['Snap']} "
            f"inline-efficiency={volume['Eff']}"
        )
        if (volume["Snap"] or "").lower() not in ("none", ""):
            findings.append(
                f"volume {volume['Name']} has snapshot policy {volume['Snap']!r}. Set it to 'none' "
                "for a measurement: a snapshot holds overwritten blocks and the volume fills"
            )
        if volume["Eff"]:
            findings.append(
                f"volume {volume['Name']} has inline efficiency on. Compression and deduplication "
                "absorb the payload and return figures above the purchased ceiling. **Turn it off "
                "before writing data** -- doing it afterwards does not un-absorb what was written"
            )
    return findings


def check_smb_multichannel(
    instance: str, region: str, secret_arn: str, fs_id: str, svm: str
) -> list[str]:
    """Whether server-side SMB Multichannel is on, before an SMB figure is taken.

    **This check exists because its absence cost a whole environment.** On 2026-09-18 a window
    ladder ran on a freshly built SMB environment -- six runs, 300 to 900 seconds, flat to 0.07% --
    and every one of them measured the single-channel path, because `is-multichannel-enabled`
    defaults to false and nobody read it. The question the run was set up to answer is still open,
    and the environment it needed is gone.

    **A single-channel session is recognisable from the number**: 1 MiB sequential sits at about
    574 MB/s with about 891 ms of latency, reproduced to within 0.05% on two separately built
    environments. Four channels put the same measurement near 2,227 MB/s read and 1,698 MB/s write.

    Read through the private CLI passthrough: this is a `vserver cifs options` field, and the public
    REST endpoint for the CIFS service does not carry it.
    """
    data = ontap_get(
        instance,
        region,
        secret_arn,
        fs_id,
        f"/api/private/cli/vserver/cifs/options?vserver={svm}"
        "&fields=is-multichannel-enabled",
    )
    records = data.get("records") or []
    if not records:
        raise CheckFailed(
            f"no CIFS options came back for SVM {svm!r}. That is not the same as multichannel "
            "being enabled -- check the SVM name, and that it has a CIFS server at all"
        )
    for record in records:
        print(
            f"  smb      {record.get('vserver', svm)} "
            f"is_multichannel_enabled={record.get('is_multichannel_enabled')}"
        )
    if not any(r.get("is_multichannel_enabled") for r in records):
        return [
            "server-side SMB Multichannel is disabled, which is the default. **An SMB figure taken "
            "now measures the single-channel path** -- about 574 MB/s at 1 MiB, against about 2,227 "
            "with four channels. Enable it with `vserver cifs options modify "
            "-is-multichannel-enabled true`, then **re-establish the session** (Remove-SmbMapping "
            "and New-SmbMapping): an existing session does not gain channels. Read "
            "`(Get-SmbMultichannelConnection).CurrentChannels` while the load is running, because "
            "the count drops when idle"
        ]
    print(
        "           enabled on the server. Still confirm CurrentChannels under load: the count "
        "drops when idle, so a value read between runs is not the run's condition"
    )
    return []


def check_transfer_size(
    instance: str, region: str, secret_arn: str, fs_id: str
) -> list[str]:
    """Report tcp_max_transfer_size. It caps rsize, and 65536 is the default.

    Not a finding either way: 64 KiB is the right condition for a default-configuration figure and
    the wrong one for a transfer-size comparison. Printed so the value lands in the record.
    """
    data = ontap_get(
        instance,
        region,
        secret_arn,
        fs_id,
        "/api/protocols/nfs/services?fields=svm.name,transport.tcp_max_transfer_size",
    )
    records = data.get("records") or []
    if not records:
        raise CheckFailed("no NFS service came back, so the transfer size was not read")
    for record in records:
        svm = (record.get("svm") or {}).get("name")
        size = (record.get("transport") or {}).get("tcp_max_transfer_size")
        print(f"  nfs      {svm} tcp_max_transfer_size={size}")
    return []


# ---------------------------------------------------------------------------------- main


def run(checks) -> int:
    findings: list[str] = []
    for label, call in checks:
        print(f"{label}")
        try:
            findings.extend(call())
        except CheckFailed as error:
            print(f"  COULD NOT RUN: {error}")
            return 2
    if findings:
        print(f"\n{len(findings)} finding(s):")
        for finding in findings:
            print(f"  - {finding}")
        return 1
    print("\npreflight: nothing blocking")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="phase", required=True)

    pre = sub.add_parser("pre", help="before creating anything; AWS API only")
    pre.add_argument("--region", default="ap-northeast-1")
    pre.add_argument("--vpc-id", required=True)
    pre.add_argument("--subnet-id", required=True)
    pre.add_argument(
        "--throughput-capacity",
        type=int,
        required=True,
        help="MB/s about to be created, so the headroom is checked against what you will ask for",
    )
    pre.add_argument("--storage-capacity-gib", type=int, default=1024)

    post = sub.add_parser(
        "post", help="after the stack exists, before measuring; reads ONTAP"
    )
    post.add_argument("--region", default="ap-northeast-1")
    post.add_argument("--file-system-id", required=True)
    post.add_argument(
        "--instance-id",
        required=True,
        help="a client in the same VPC. The management endpoint has no public address",
    )
    post.add_argument("--fsxadmin-secret-arn", required=True)
    post.add_argument(
        "--allow-nvme-cache",
        action="store_true",
        help="record deliberately that the read cache was on, instead of failing",
    )
    post.add_argument(
        "--smb-svm",
        help="the SMB SVM's name. Given, this also reads whether server-side Multichannel is on -- "
        "the check whose absence made six SMB runs measure the single-channel path",
    )

    args = parser.parse_args()

    if args.phase == "pre":
        return run(
            [
                (
                    "quota headroom in this Region (shared with every other file system here)",
                    lambda: check_quota(
                        args.region, args.throughput_capacity, args.storage_capacity_gib
                    ),
                ),
                (
                    "subnet and Session Manager reachability",
                    lambda: check_subnet(args.region, args.vpc_id, args.subnet_id),
                ),
            ]
        )

    return run(
        [
            (
                "ONTAP release (unrecoverable after teardown)",
                lambda: check_ontap_release(
                    args.instance_id,
                    args.region,
                    args.fsxadmin_secret_arn,
                    args.file_system_id,
                ),
            ),
            (
                "NVMe read cache",
                lambda: check_nvme_cache(
                    args.instance_id,
                    args.region,
                    args.fsxadmin_secret_arn,
                    args.file_system_id,
                    args.allow_nvme_cache,
                ),
            ),
            (
                "defaults that change what a number means",
                lambda: check_measurement_defaults(args.region, args.file_system_id),
            ),
            *(
                [
                    (
                        "SMB Multichannel (disabled by default)",
                        lambda: check_smb_multichannel(
                            args.instance_id,
                            args.region,
                            args.fsxadmin_secret_arn,
                            args.file_system_id,
                            args.smb_svm,
                        ),
                    )
                ]
                if args.smb_svm
                else []
            ),
            (
                "NFS transfer size (for the record)",
                lambda: check_transfer_size(
                    args.instance_id,
                    args.region,
                    args.fsxadmin_secret_arn,
                    args.file_system_id,
                ),
            ),
        ]
    )


if __name__ == "__main__":
    sys.exit(main())
