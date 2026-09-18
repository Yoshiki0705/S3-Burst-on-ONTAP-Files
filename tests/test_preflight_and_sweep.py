"""The two operational gates, tested on the shapes that made them necessary.

WHY THESE TESTS

Both scripts call the AWS CLI, so the interesting part is not the call -- it is what they conclude
from an answer. Every case below is an answer that was actually seen:

  * a Region whose throughput pool is nearly full, which is what refused the third environment on
    2026-09-18 about 25 minutes into creation;
  * a quota that cannot be read, which has to be a finding rather than a pass, because the margin
    would otherwise be measured against a default that may not apply;
  * an empty node list from the read-cache query, which looks identical to "nothing is enabled"
    once it is summarised and means the opposite;
  * a cluster that answers without the words `NetApp Release`, which is how an error page, an empty
    record set and a traceback all arrive;
  * a secret-name filter that matched nothing while six secrets sat there, because the stack name
    and the project name are spelled differently.

The AWS calls are replaced with recorded answers. That keeps the test offline, and it is also the
only way to exercise the failure paths: a healthy account cannot produce them on demand.
"""

from __future__ import annotations

import json

import preflight
import pytest
import sweep_after_teardown as sweep


def fake_aws_json(answers: dict[str, object]):
    """Return an `aws_json` stand-in that dispatches on a substring of the argument list.

    Matching on a fragment rather than on the exact argument list: the queries are long JMESPath
    strings, and a test that pinned them would fail on a whitespace change without saying why.
    """

    def call(*args: str):
        joined = " ".join(args)
        for fragment, answer in answers.items():
            if fragment in joined:
                if isinstance(answer, Exception):
                    raise answer
                return answer
        raise AssertionError(f"no recorded answer for: {joined}")

    return call


# ------------------------------------------------------------------ quota headroom


def test_quota_headroom_refuses_before_the_25_minute_failure(monkeypatch, capsys):
    """8,448 in use, a 2,048 request and a 10,240 limit: this is the case that failed for real."""
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            {
                "get-service-quota": {"Quota": {"Value": 10240.0}},
                "describe-file-systems": [
                    {"Id": "fs-a", "MBps": 6144, "SSD": 4096, "Life": "AVAILABLE"},
                    {"Id": "fs-b", "MBps": 2048, "SSD": 1024, "Life": "AVAILABLE"},
                    {"Id": "fs-c", "MBps": 256, "SSD": 1024, "Life": "AVAILABLE"},
                ],
            }
        ),
    )
    findings = preflight.check_quota("ap-northeast-1", 2048, 1024)
    assert len(findings) == 1
    assert "10496 MB/s against a limit of 10240" in findings[0]
    # The message has to carry the two facts that decide what the reader does next.
    assert "25 minutes" in findings[0]
    assert "4 minutes" in findings[0]
    # Other people's file systems share the pool, so they are listed rather than summed silently.
    assert "fs-a" in capsys.readouterr().out


def test_quota_headroom_passes_with_room(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            {
                "get-service-quota": {"Quota": {"Value": 10240.0}},
                "describe-file-systems": [
                    {"Id": "fs-a", "MBps": 256, "SSD": 1024, "Life": "AVAILABLE"}
                ],
            }
        ),
    )
    assert preflight.check_quota("ap-northeast-1", 2048, 1024) == []


def test_an_unreadable_quota_is_a_finding_not_a_pass(monkeypatch):
    """Without the account's own value the margin is against a default that may not apply."""
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            {
                "get-service-quota": preflight.CheckFailed("AccessDenied"),
                "get-aws-default-service-quota": preflight.CheckFailed("AccessDenied"),
                "describe-file-systems": [],
            }
        ),
    )
    findings = preflight.check_quota("ap-northeast-1", 128, 1024)
    assert findings and "could not be read" in findings[0]


def test_a_granted_increase_is_not_understated(monkeypatch):
    """A raised quota is only visible through get-service-quota; the default would false-alarm."""
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            {
                "get-service-quota": {"Quota": {"Value": 20480.0}},
                "describe-file-systems": [
                    {"Id": "fs-a", "MBps": 10240, "SSD": 1024, "Life": "AVAILABLE"}
                ],
            }
        ),
    )
    assert preflight.check_quota("ap-northeast-1", 6144, 1024) == []


# ------------------------------------------------------------------ Session Manager reachability


def _subnet_answers(*, routes, endpoints, vpc="vpc-1"):
    return {
        "describe-subnets": [
            {"Vpc": vpc, "Az": "ap-northeast-1a", "Public": False, "Free": 4000}
        ],
        "describe-route-tables": routes,
        "describe-vpc-endpoints": endpoints,
    }


def test_no_egress_and_no_endpoints_is_the_twenty_minute_trap(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(_subnet_answers(routes=[{"Dest": "10.0.0.0/16"}], endpoints=[])),
    )
    findings = preflight.check_subnet("ap-northeast-1", "vpc-1", "subnet-1")
    assert findings and "absent from Session Manager" in findings[0]


def test_a_nat_route_is_enough(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            _subnet_answers(
                routes=[{"Dest": "0.0.0.0/0", "Nat": "nat-1"}], endpoints=[]
            )
        ),
    )
    assert preflight.check_subnet("ap-northeast-1", "vpc-1", "subnet-1") == []


def test_the_three_interface_endpoints_are_enough(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            _subnet_answers(
                routes=[{"Dest": "10.0.0.0/16"}],
                endpoints=[
                    "com.amazonaws.ap-northeast-1.ssm",
                    "com.amazonaws.ap-northeast-1.ssmmessages",
                    "com.amazonaws.ap-northeast-1.ec2messages",
                ],
            )
        ),
    )
    assert preflight.check_subnet("ap-northeast-1", "vpc-1", "subnet-1") == []


def test_a_subnet_in_another_vpc_is_reported(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(
            _subnet_answers(
                routes=[{"Dest": "0.0.0.0/0", "Igw": "igw-1"}],
                endpoints=[],
                vpc="vpc-other",
            )
        ),
    )
    findings = preflight.check_subnet("ap-northeast-1", "vpc-1", "subnet-1")
    assert any("belongs to vpc-other" in f for f in findings)


def test_a_missing_subnet_cannot_run_rather_than_passing(monkeypatch):
    monkeypatch.setattr(preflight, "aws_json", fake_aws_json({"describe-subnets": []}))
    with pytest.raises(preflight.CheckFailed):
        preflight.check_subnet("ap-northeast-1", "vpc-1", "subnet-gone")


# ------------------------------------------------------------------ ONTAP release


def _ontap(answer):
    def call(instance, region, secret, fs_id, path):
        if isinstance(answer, Exception):
            raise answer
        return answer

    return call


def test_a_release_string_passes(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "ontap_get",
        _ontap(
            {
                "version": {
                    "full": "NetApp Release 9.18.1P6: Fri Aug 07 23:43:59 UTC 2026"
                }
            }
        ),
    )
    assert (
        preflight.check_ontap_release("i-1", "ap-northeast-1", "arn:secret", "fs-1")
        == []
    )


@pytest.mark.parametrize(
    "answer",
    [
        {},  # an empty body
        {"records": []},  # an empty record set, which is what a wrong path returns
        {"version": {"full": ""}},
        {
            "error": {"message": "User is not authorized."}
        },  # HTTP 401, which is non-empty
        # **The two cases that separate the grep from a truthiness check.** A bare number is a
        # non-empty answer, so "did anything come back" accepts it -- and it cannot be compared
        # with the next run's release. Without these the test passed against both implementations,
        # which was true of the first draft of this file and is the reason it is worth a comment.
        {"version": {"full": "9.18.1"}},
        {"version": {"generation": 9, "major": 18}},  # fields present, `full` absent
    ],
)
def test_anything_without_the_release_string_blocks(monkeypatch, answer):
    """Grepping for `NetApp Release`, not for a non-empty answer."""
    monkeypatch.setattr(preflight, "ontap_get", _ontap(answer))
    findings = preflight.check_ontap_release(
        "i-1", "ap-northeast-1", "arn:secret", "fs-1"
    )
    assert findings and "cannot be recovered" in findings[0]


# ------------------------------------------------------------------ NVMe read cache


def test_an_enabled_read_cache_blocks(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "ontap_get",
        _ontap(
            {
                "records": [
                    {"node": "n1", "is_enabled": True},
                    {"node": "n2", "is_enabled": False},
                ]
            }
        ),
    )
    findings = preflight.check_nvme_cache(
        "i-1", "ap-northeast-1", "arn:secret", "fs-1", allow=False
    )
    assert findings and "served from cache" in findings[0]


def test_an_enabled_read_cache_can_be_recorded_deliberately(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "ontap_get",
        _ontap({"records": [{"node": "n1", "is_enabled": True}]}),
    )
    assert (
        preflight.check_nvme_cache(
            "i-1", "ap-northeast-1", "arn:secret", "fs-1", allow=True
        )
        == []
    )


def test_no_nodes_at_all_cannot_run(monkeypatch):
    """An empty list and "the cache is off" look the same once summarised, and are opposites."""
    monkeypatch.setattr(preflight, "ontap_get", _ontap({"records": []}))
    with pytest.raises(preflight.CheckFailed):
        preflight.check_nvme_cache(
            "i-1", "ap-northeast-1", "arn:secret", "fs-1", allow=False
        )


def test_a_body_that_is_not_json_cannot_run(monkeypatch):
    def raises(*_args, **_kwargs):
        raise json.JSONDecodeError("no", "", 0)

    monkeypatch.setattr(preflight, "ssm_shell", lambda *a, **k: "<html>403</html>")
    with pytest.raises(preflight.CheckFailed):
        preflight.ontap_get(
            "i-1", "ap-northeast-1", "arn:secret", "fs-1", "/api/cluster"
        )


# ------------------------------------------------------------------ measurement-invalidating defaults


def _defaults_answers(
    *, backup=0, snapshot="none", efficiency=False, iops="USER_PROVISIONED"
):
    return {
        "describe-file-systems": [
            {"Backup": backup, "MBps": 2048, "Iops": {"Mode": iops, "Iops": 40000}}
        ],
        "describe-volumes": [
            {
                "Name": "origin_vol",
                "Snap": snapshot,
                "Eff": efficiency,
                "Path": "/origin_vol",
            },
            {"Name": "svm_root", "Snap": "default", "Eff": True, "Path": "/"},
        ],
    }


def test_clean_settings_pass(monkeypatch):
    monkeypatch.setattr(preflight, "aws_json", fake_aws_json(_defaults_answers()))
    assert preflight.check_measurement_defaults("ap-northeast-1", "fs-1") == []


def test_the_root_volume_is_not_judged(monkeypatch):
    """The SVM root keeps the default policy and efficiency; judging it would be a false positive."""
    monkeypatch.setattr(preflight, "aws_json", fake_aws_json(_defaults_answers()))
    findings = preflight.check_measurement_defaults("ap-northeast-1", "fs-1")
    assert not any("svm_root" in f for f in findings)


def test_each_invalidating_default_is_named(monkeypatch):
    monkeypatch.setattr(
        preflight,
        "aws_json",
        fake_aws_json(_defaults_answers(backup=7, snapshot="default", efficiency=True)),
    )
    findings = preflight.check_measurement_defaults("ap-northeast-1", "fs-1")
    assert len(findings) == 3
    assert any("automatic backups" in f for f in findings)
    assert any("snapshot policy" in f for f in findings)
    assert any("inline efficiency" in f for f in findings)


def test_a_file_system_with_no_data_volume_cannot_run(monkeypatch):
    answers = _defaults_answers()
    answers["describe-volumes"] = [
        {"Name": "svm_root", "Snap": "default", "Eff": True, "Path": "/"}
    ]
    monkeypatch.setattr(preflight, "aws_json", fake_aws_json(answers))
    with pytest.raises(preflight.CheckFailed):
        preflight.check_measurement_defaults("ap-northeast-1", "fs-1")


# ------------------------------------------------------------------ the sweep


def test_the_secret_filter_matches_the_spelling_the_template_uses(monkeypatch):
    """The regression this defends: one default fragment found none while six secrets existed.

    The stack is named `s3burst-v13-origin` and the secret it creates is named from `ProjectName`,
    `s3-burst-on-ontap-files/...`. A filter built from the stack name misses every one of them.
    """
    captured: dict[str, str] = {}

    def record(*args: str):
        captured["query"] = " ".join(args)
        return [{"Name": "s3-burst-on-ontap-files/x/fsxadmin", "Deleted": None}]

    monkeypatch.setattr(sweep, "aws_json", record)
    found = sweep.secrets(
        "ap-northeast-1", ["s3-burst-on-ontap-files", "s3burst", "perfmatrix"]
    )
    assert len(found) == 1
    for fragment in ("s3-burst-on-ontap-files", "s3burst", "perfmatrix"):
        assert fragment in captured["query"]
    assert "||" in captured["query"], "the fragments have to be OR-ed, not AND-ed"


def test_backups_are_listed_without_a_filter(monkeypatch):
    """They carry no tags and their FileSystemId is null, so any filter is the bug."""
    captured: dict[str, str] = {}

    def record(*args: str):
        captured["query"] = " ".join(args)
        return [
            {
                "Id": "backup-1",
                "Created": "x",
                "Life": "AVAILABLE",
                "Type": "USER_INITIATED",
                "Vol": None,
                "Fs": None,
                "Size": None,
            }
        ]

    monkeypatch.setattr(sweep, "aws_json", record)
    assert len(sweep.backups("ap-northeast-1")) == 1
    assert "--filters" not in captured["query"]


def test_orphan_storage_compares_against_the_live_file_systems(monkeypatch):
    """A FlexCache deleted on the ONTAP side leaves the FSx record, which then blocks the SVM."""
    monkeypatch.setattr(
        sweep,
        "aws_json",
        fake_aws_json(
            {
                "describe-file-systems": [{"Id": "fs-live"}],
                "describe-volumes": [
                    {
                        "Id": "fsvol-1",
                        "Name": "cache_vol",
                        "Fs": "fs-gone",
                        "Life": "CREATED",
                    },
                    {
                        "Id": "fsvol-2",
                        "Name": "origin_vol",
                        "Fs": "fs-live",
                        "Life": "CREATED",
                    },
                ],
                "describe-storage-virtual-machines": [
                    {
                        "Id": "svm-1",
                        "Name": "cache_svm",
                        "Fs": "fs-gone",
                        "Life": "CREATED",
                    }
                ],
            }
        ),
    )
    volumes, svms = sweep.orphan_storage("ap-northeast-1")
    assert [v["Id"] for v in volumes] == ["fsvol-1"]
    assert [s["Id"] for s in svms] == ["svm-1"]


def test_delete_requires_yes(monkeypatch, capsys):
    """Three of the four deletions cannot be undone, so the flag pair is the guard."""
    monkeypatch.setattr(
        "sys.argv",
        ["sweep_after_teardown.py", "--region", "ap-northeast-1", "--delete"],
    )
    assert sweep.main() == 2
    assert "needs --yes" in capsys.readouterr().out
