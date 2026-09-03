#!/usr/bin/env python3
"""S3 Burst on ONTAP Files — presigned URL and UploadPartCopy support on an FSx for ONTAP S3 AP.

Answers two questions left unmeasured by `measure_visibility.py`, which covers cross-protocol
visibility and needs NFS mounts. This one talks only to the S3 API, so it runs anywhere the access
point is reachable and creates no resources beyond objects under one prefix.

  1. Do presigned URLs work for PutObject and HeadObject?
  2. Does UploadPartCopy accept a source in the same access point?

Support is settled before latency: a latency number for an operation that does not work is noise.
Every negative result is paired with a control that must succeed in the same run, because a failure
without a control can record a mistake in the procedure rather than a property of the target.

Usage:
  python3 scripts/measure_s3ap_operations.py \
    --access-point arn:aws:s3:<region>:<account>:accesspoint/<name> \
    [--compare-access-point <another AP on the same volume>] \
    [--iterations 30] [--object-size 64] [--region ap-northeast-1] \
    [--prefix measure/s3ap-ops] [--output results.json] [--keep]

Notes:
  - Numbers come from one specific environment and one object size. They are a sample run, not a
    production estimate, and the environment block in the output is part of the result.
  - The presigned requests reuse a single HTTPS connection, and the first call of each kind is
    discarded as a warm-up. Without that, the TLS handshake lands inside the first sample: an
    earlier measurement in this repository reported 873 ms for a step that was 44 ms, because the
    per-call cost of starting a client had been included.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import time
import urllib.parse
from datetime import UTC, datetime

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from measure_visibility import percentiles

# UploadPartCopy requires at least 5 MiB in any part that is not the last one, so a smaller source
# would fail for a reason that has nothing to do with the access point.
COPY_SOURCE_BYTES = 6 * 1024 * 1024


def error_code(exc: ClientError) -> str:
    return exc.response.get("Error", {}).get("Code", "Unknown")


class Recorder:
    """Collects named outcomes so the report can state what held and what did not."""

    def __init__(self) -> None:
        self.results: list[dict] = []

    def run(self, name: str, expectation: str, fn) -> tuple[bool, str]:
        try:
            detail = fn()
        except ClientError as exc:
            outcome, detail_text = False, error_code(exc)
        except OSError as exc:
            outcome, detail_text = False, f"{type(exc).__name__}: {exc}"
        else:
            outcome, detail_text = True, "" if detail is None else str(detail)
        self.results.append(
            {
                "check": name,
                "expectation": expectation,
                "succeeded": outcome,
                "detail": detail_text,
            }
        )
        mark = "OK  " if outcome else "FAIL"
        suffix = f" -> {detail_text}" if detail_text else ""
        print(f"  {mark} {name}{suffix}")
        return outcome, detail_text


class PresignedSession:
    """One HTTPS connection, reused, so the handshake is not measured as request latency."""

    def __init__(self, host: str, timeout: int = 30) -> None:
        self.host = host
        self.timeout = timeout
        self.connection = http.client.HTTPSConnection(host, timeout=timeout)

    def send(
        self,
        url: str,
        method: str,
        body: bytes | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> int:
        parts = urllib.parse.urlparse(url)
        target = parts.path + ("?" + parts.query if parts.query else "")
        headers = dict(extra_headers or {})
        if body is not None:
            # SigV2 signs Content-Type, so a header the client adds on its own invalidates the
            # signature. Setting it explicitly keeps the comparison between the two versions about
            # the signature version rather than about which headers a client happens to send.
            headers.setdefault("Content-Type", "")
            headers.setdefault("Content-Length", str(len(body)))
        for attempt in (1, 2):
            try:
                self.connection.request(method, target, body=body, headers=headers)
                response = self.connection.getresponse()
                response.read()
                return response.status
            except (http.client.HTTPException, OSError):
                # A reused connection can be closed by the peer between calls; rebuild it once.
                if attempt == 2:
                    raise
                self.connection.close()
                self.connection = http.client.HTTPSConnection(
                    self.host, timeout=self.timeout
                )
        raise AssertionError("unreachable")

    def close(self) -> None:
        self.connection.close()


def describe_environment(region: str, access_point: str) -> dict:
    """Environment facts that make the numbers meaningful, read from the API rather than typed."""
    name = access_point.rsplit("/", 1)[-1]
    fsx = boto3.client("fsx", region_name=region)
    environment: dict = {
        "measured_at": datetime.now(UTC).isoformat(),
        "region": region,
        "access_point": name,
    }
    try:
        attachment = fsx.describe_s3_access_point_attachments(Names=[name])[
            "S3AccessPointAttachments"
        ][0]
    except (ClientError, IndexError, KeyError):
        return environment
    ontap = attachment.get("OntapConfiguration", {})
    volume_id = ontap.get("VolumeId")
    environment["volume_id"] = volume_id
    environment["file_system_identity"] = ontap.get("FileSystemIdentity", {}).get(
        "Type"
    )
    environment["access_point_vpc_restricted"] = bool(
        attachment.get("S3AccessPoint", {}).get("VpcConfiguration")
    )
    if not volume_id:
        return environment
    try:
        volume = fsx.describe_volumes(VolumeIds=[volume_id])["Volumes"][0]
        volume_ontap = volume.get("OntapConfiguration", {})
        environment["security_style"] = volume_ontap.get("SecurityStyle")
        environment["snaplock"] = (
            volume_ontap.get("SnaplockConfiguration", {}).get("SnaplockType") or "None"
        )
        file_system_id = volume.get("FileSystemId")
        environment["file_system_id"] = file_system_id
        file_system = fsx.describe_file_systems(FileSystemIds=[file_system_id])[
            "FileSystems"
        ][0]
        file_system_ontap = file_system.get("OntapConfiguration", {})
        environment["deployment_type"] = file_system_ontap.get("DeploymentType")
        environment["throughput_capacity_mbps"] = file_system_ontap.get(
            "ThroughputCapacity"
        )
        environment["storage_capacity_gib"] = file_system.get("StorageCapacity")
    except (ClientError, IndexError, KeyError):
        pass
    # The ONTAP release is not exposed by the FSx API. Recording the absence keeps a reader from
    # assuming the field was simply forgotten -- reading it needs the ONTAP REST API or CLI.
    environment["ontap_version"] = "not determined (not exposed by the FSx API)"
    return environment


def check_presigned_support(
    recorder: Recorder, signed, default_client, access_point: str, prefix: str
) -> PresignedSession:
    key = f"{prefix}/presigned-support.txt"
    sigv4_url = signed.generate_presigned_url(
        "put_object", Params={"Bucket": access_point, "Key": key}, ExpiresIn=600
    )
    session = PresignedSession(urllib.parse.urlparse(sigv4_url).netloc)

    def expect_200(url: str, method: str, body: bytes | None = None):
        status = session.send(url, method, body)
        if status != 200:
            raise OSError(f"HTTP {status}")
        return f"HTTP {status}"

    recorder.run(
        "presigned PutObject (SigV4)",
        "succeeds",
        lambda: expect_200(sigv4_url, "PUT", b"presigned-body"),
    )
    for operation, method in (("head_object", "HEAD"), ("get_object", "GET")):
        url = signed.generate_presigned_url(
            operation, Params={"Bucket": access_point, "Key": key}, ExpiresIn=600
        )
        recorder.run(
            f"presigned {operation} (SigV4)",
            "succeeds",
            lambda u=url, m=method: expect_200(u, m),
        )

    recorder.run(
        "control: the object exists when read with a signed API call",
        "succeeds, so the presigned PUT really wrote",
        lambda: (
            f"{default_client.head_object(Bucket=access_point, Key=key)['ContentLength']} bytes"
        ),
    )

    tampered = signed.generate_presigned_url(
        "get_object", Params={"Bucket": access_point, "Key": key}, ExpiresIn=600
    )
    tampered = tampered[:-6] + "abcdef"

    def tampered_is_refused():
        status = session.send(tampered, "GET")
        # 403 is the expected outcome, so this control passes on refusal. Written the other way
        # round at first, it reported FAIL when the endpoint behaved correctly -- the check itself
        # has to agree about which outcome it is asserting.
        if status == 403:
            return f"HTTP {status}, refused"
        raise OSError(f"a broken signature returned HTTP {status}")

    recorder.run(
        "control: a tampered signature is refused",
        "refused with 403, so the endpoint is not simply open",
        tampered_is_refused,
    )

    # The default client emits SigV2 for presigned URLs even though `meta.config.signature_version`
    # reports s3v4. Recorded because the reported value does not predict what is generated.
    sigv2_url = default_client.generate_presigned_url(
        "put_object",
        Params={"Bucket": access_point, "Key": f"{prefix}/presigned-sigv2.txt"},
        ExpiresIn=600,
    )
    recorder.run(
        "a client built without an explicit signature_version emits SigV2",
        "true; the reported config value says s3v4",
        lambda: "SigV2" if "AWSAccessKeyId" in sigv2_url else "SigV4",
    )
    recorder.run(
        "presigned PutObject (SigV2), Content-Type sent empty",
        "succeeds; SigV2 is accepted when the signed headers match",
        lambda: expect_200(sigv2_url, "PUT", b"sigv2-body"),
    )
    return session


def check_upload_part_copy(
    recorder: Recorder,
    client,
    access_point: str,
    compare_access_point: str | None,
    prefix: str,
) -> None:
    source_key = f"{prefix}/copy-source.bin"
    body = b"u" * COPY_SOURCE_BYTES
    recorder.run(
        f"put a {COPY_SOURCE_BYTES // (1024 * 1024)} MiB source object",
        "succeeds",
        lambda: client.put_object(Bucket=access_point, Key=source_key, Body=body)[
            "ETag"
        ],
    )

    sources = [("the same access point", access_point)]
    if compare_access_point:
        sources.append(
            ("a different access point on the same volume", compare_access_point)
        )

    for label, source_ap in sources:
        print(f"  -- source named through {label}")
        recorder.run(
            f"control: the source is readable through {label}",
            "succeeds",
            lambda a=source_ap: (
                f"{client.head_object(Bucket=a, Key=source_key)['ContentLength']} bytes"
            ),
        )
        destination = f"{prefix}/copy-dest-{source_ap.rsplit('/', 1)[-1]}.bin"
        state: dict = {}

        def initiate(d=destination, s=state):
            s["upload_id"] = client.create_multipart_upload(Bucket=access_point, Key=d)[
                "UploadId"
            ]
            return "created"

        if not recorder.run("control: CreateMultipartUpload", "succeeds", initiate)[0]:
            continue

        # A plain UploadPart proves the multipart session itself is usable, so a failure of
        # UploadPartCopy below cannot be attributed to the session.
        recorder.run(
            "control: UploadPart (not a copy) on that upload",
            "succeeds",
            lambda d=destination, s=state: client.upload_part(
                Bucket=access_point,
                Key=d,
                UploadId=s["upload_id"],
                PartNumber=1,
                Body=body,
            )["ETag"],
        )
        recorder.run(
            f"UploadPartCopy, source through {label}",
            "under test",
            lambda a=source_ap, d=destination, s=state: client.upload_part_copy(
                Bucket=access_point,
                Key=d,
                UploadId=s["upload_id"],
                PartNumber=2,
                CopySource={"Bucket": a, "Key": source_key},
            )["CopyPartResult"]["ETag"],
        )
        # The decisive comparison: an identical CopySource, in the same run, through CopyObject.
        recorder.run(
            f"control: CopyObject with the identical source through {label}",
            "under test; isolates the operation from the source",
            lambda a=source_ap, d=destination: client.copy_object(
                Bucket=access_point,
                Key=d + ".copyobject",
                CopySource={"Bucket": a, "Key": source_key},
            )["CopyObjectResult"]["ETag"],
        )
        recorder.run(
            "cleanup: AbortMultipartUpload",
            "succeeds",
            lambda d=destination, s=state: (
                client.abort_multipart_upload(
                    Bucket=access_point, Key=d, UploadId=s["upload_id"]
                )
                and "aborted"
                or "aborted"
            ),
        )


def measure_latency(
    session: PresignedSession,
    signed,
    client,
    access_point: str,
    prefix: str,
    iterations: int,
    object_size: int,
) -> dict:
    body = b"m" * object_size
    samples: dict[str, list[float]] = {
        "presigned_put": [],
        "presigned_put_with_expect_100": [],
        "api_put_sdk_default": [],
        "api_put_checksum_when_required": [],
        "presigned_head": [],
        "api_head": [],
        "first_read_after_write": [],
    }
    # A second client differing only in the checksum setting. botocore's default
    # (`when_supported`) sends a 64 B body as `aws-chunked` with a CRC32 trailer; `when_required`
    # sends a plain fixed-length body. Without this pair the PUT comparison reads as "presigned is
    # faster than the SDK", when what differs is the request encoding, not the signing.
    no_trailer = boto3.client(
        "s3",
        region_name=client.meta.region_name,
        config=Config(
            signature_version="s3v4", request_checksum_calculation="when_required"
        ),
    )

    # One warm-up of each kind, discarded: the first presigned call pays for the TLS handshake and
    # the first API call pays for endpoint resolution and credential loading.
    warm_key = f"{prefix}/latency-warmup.bin"
    session.send(
        signed.generate_presigned_url(
            "put_object",
            Params={"Bucket": access_point, "Key": warm_key},
            ExpiresIn=900,
        ),
        "PUT",
        body,
    )
    session.send(
        signed.generate_presigned_url(
            "head_object",
            Params={"Bucket": access_point, "Key": warm_key},
            ExpiresIn=900,
        ),
        "HEAD",
    )
    client.put_object(Bucket=access_point, Key=warm_key, Body=body)
    client.head_object(Bucket=access_point, Key=warm_key)

    no_trailer.put_object(
        Bucket=access_point, Key=f"{prefix}/latency-warmup-nt.bin", Body=body
    )

    # PutObject: a fresh key each iteration, so no path is helped by the object already existing.
    # Each path gets its own pass rather than being interleaved. Interleaving was tried first and
    # showed a difference that did not survive separation.
    def timed_presigned_put(tag, extra=None):
        collected = []
        for index in range(iterations):
            url = signed.generate_presigned_url(
                "put_object",
                Params={
                    "Bucket": access_point,
                    "Key": f"{prefix}/lat-{tag}-{index:03d}.bin",
                },
                ExpiresIn=900,
            )
            # Signing sits outside the timed region: it is local work, and timing it would report
            # client CPU as endpoint latency.
            start = time.perf_counter()
            session.send(url, "PUT", body, extra)
            collected.append((time.perf_counter() - start) * 1000)
        return collected

    def timed_api_put(tag, put_client):
        collected = []
        for index in range(iterations):
            start = time.perf_counter()
            put_client.put_object(
                Bucket=access_point,
                Key=f"{prefix}/lat-{tag}-{index:03d}.bin",
                Body=body,
            )
            collected.append((time.perf_counter() - start) * 1000)
        return collected

    samples["presigned_put"] = timed_presigned_put("pput")
    samples["presigned_put_with_expect_100"] = timed_presigned_put(
        "pputexp", {"Expect": "100-continue"}
    )
    samples["api_put_sdk_default"] = timed_api_put("sdkdef", client)
    samples["api_put_checksum_when_required"] = timed_api_put("sdkreq", no_trailer)

    # HeadObject: one settled key for both paths, in separate passes. Reading a key that was just
    # written costs several times more (see `first_read_after_write`), and mixing that in was what
    # first made the presigned path look faster than the SDK -- the two were being timed against
    # keys of different ages rather than against each other.
    settled_key = f"{prefix}/latency-head-settled.bin"
    client.put_object(Bucket=access_point, Key=settled_key, Body=body)
    client.head_object(Bucket=access_point, Key=settled_key)
    for _ in range(iterations):
        head_url = signed.generate_presigned_url(
            "head_object",
            Params={"Bucket": access_point, "Key": settled_key},
            ExpiresIn=900,
        )
        start = time.perf_counter()
        session.send(head_url, "HEAD")
        samples["presigned_head"].append((time.perf_counter() - start) * 1000)
    for _ in range(iterations):
        start = time.perf_counter()
        client.head_object(Bucket=access_point, Key=settled_key)
        samples["api_head"].append((time.perf_counter() - start) * 1000)

    # Recorded separately and deliberately not presented as a headline figure: across two loop
    # shapes this differed by roughly 4x (p50 206 ms and 786 ms), so it is a real effect with no
    # stable value yet. It needs its own measurement, varying object size and the delay after the
    # write, before any number is published.
    for index in range(iterations):
        key = f"{prefix}/latency-fresh-{index:03d}.bin"
        client.put_object(Bucket=access_point, Key=key, Body=body)
        start = time.perf_counter()
        client.head_object(Bucket=access_point, Key=key)
        samples["first_read_after_write"].append((time.perf_counter() - start) * 1000)

    return {name: percentiles(values) for name, values in samples.items()}


def delete_prefix(client, access_point: str, prefix: str) -> int:
    deleted = 0
    token = None
    while True:
        kwargs = {"Bucket": access_point, "Prefix": prefix}
        if token:
            kwargs["ContinuationToken"] = token
        page = client.list_objects_v2(**kwargs)
        keys = [{"Key": item["Key"]} for item in page.get("Contents", [])]
        for start in range(0, len(keys), 1000):
            client.delete_objects(
                Bucket=access_point, Delete={"Objects": keys[start : start + 1000]}
            )
            deleted += len(keys[start : start + 1000])
        if not page.get("IsTruncated"):
            return deleted
        token = page.get("NextContinuationToken")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--access-point", required=True, help="S3 access point ARN or alias"
    )
    parser.add_argument(
        "--compare-access-point",
        help="another access point on the same volume, to separate the operation from the source",
    )
    parser.add_argument("--region", default="ap-northeast-1")
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument(
        "--object-size", type=int, default=64, help="bytes, for the latency phase"
    )
    parser.add_argument("--prefix", default="measure/s3ap-ops")
    parser.add_argument("--output", help="write the result as JSON to this path")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="leave the objects created under --prefix in place",
    )
    args = parser.parse_args()

    # An explicit signature_version is required: without it `generate_presigned_url` emits SigV2
    # while the client reports s3v4.
    signed = boto3.client(
        "s3", region_name=args.region, config=Config(signature_version="s3v4")
    )
    default_client = boto3.client("s3", region_name=args.region)

    environment = describe_environment(args.region, args.access_point)
    print("Environment")
    for key, value in environment.items():
        print(f"  {key}: {value}")

    recorder = Recorder()
    print("\nA. Presigned URL support")
    session = check_presigned_support(
        recorder, signed, default_client, args.access_point, args.prefix
    )

    print("\nB. UploadPartCopy support")
    check_upload_part_copy(
        recorder,
        default_client,
        args.access_point,
        args.compare_access_point,
        args.prefix,
    )

    print(f"\nC. Latency, {args.object_size} B objects, n={args.iterations}")
    latency = measure_latency(
        session,
        signed,
        default_client,
        args.access_point,
        args.prefix,
        args.iterations,
        args.object_size,
    )
    for name, stats in latency.items():
        print(
            f"  {name:16s} p50 {stats['p50']:7.1f} ms  p90 {stats['p90']:7.1f} ms  "
            f"p99 {stats['p99']:7.1f} ms  max {stats['max']:7.1f} ms  n={stats['n']}"
        )
    session.close()

    if args.keep:
        print(f"\n--keep given; objects left under {args.prefix}/")
    else:
        print(
            f"\nCleanup: removed {delete_prefix(default_client, args.access_point, args.prefix)}"
            f" object(s) under {args.prefix}/"
        )

    report = {
        "environment": environment,
        "object_size_bytes": args.object_size,
        "iterations": args.iterations,
        "support": recorder.results,
        "latency_ms": latency,
    }
    if args.output:
        with open(args.output, "w") as handle:
            json.dump(report, handle, indent=2)
        print(f"Saved to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
