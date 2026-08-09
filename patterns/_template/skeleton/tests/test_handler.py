"""Contract tests for the scaffolded handler.

These run as-is in a freshly scaffolded pattern, so `make test` is green from the first commit. That
matters more than it looks: a scaffolder that leaves the repository red teaches people to skip the
gate, and a skipped gate is the same as no gate.

Keep these tests when you replace the handler body. They assert the contract — entry point name,
return shape, no secret echo — not the placeholder behaviour.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

PATTERN_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PATTERN_ROOT / "functions"))

import handler as handler_module  # noqa: E402


ALL_SET = {
    "PATTERN_NAME": "example-pattern",
    "PATTERN_AXIS": "collect",
    "ENVIRONMENT": "dev",
    "FILE_SYSTEM_ID": "fs-0123456789abcdef0",
    "STORAGE_VIRTUAL_MACHINE_ID": "svm-0123456789abcdef0",
    "VOLUME_NAME": "origin_vol",
    "S3_ACCESS_POINT_ALIAS": "example-alias",
}


@pytest.fixture
def wired(monkeypatch):
    for name, value in ALL_SET.items():
        monkeypatch.setenv(name, value)


def test_the_entry_point_is_handler_handler() -> None:
    """A sibling repository mixed `index.handler` and `handler.handler`; the mismatch only
    surfaces at deploy time, so the name is asserted here."""
    assert callable(handler_module.handler)


def test_it_returns_a_dict_rather_than_none(wired) -> None:
    result = handler_module.handler({})
    assert isinstance(result, dict)


def test_it_reports_itself_as_not_implemented(wired) -> None:
    """The stub must not look like a working pattern to whatever invokes it."""
    assert handler_module.handler({})["implemented"] is False


def test_a_complete_wiring_reports_nothing_missing(wired) -> None:
    assert handler_module.handler({})["wiring"]["missing"] == []


def test_an_unset_variable_is_named(monkeypatch) -> None:
    for name, value in ALL_SET.items():
        monkeypatch.setenv(name, value)
    monkeypatch.delenv("S3_ACCESS_POINT_ALIAS")
    assert handler_module.handler({})["wiring"]["missing"] == ["S3_ACCESS_POINT_ALIAS"]


def test_an_empty_variable_counts_as_unset(monkeypatch) -> None:
    """The template defaults several parameters to "", so present-but-empty is the common case."""
    for name, value in ALL_SET.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("VOLUME_NAME", "")
    assert "VOLUME_NAME" in handler_module.handler({})["wiring"]["missing"]


def test_identifier_values_are_not_echoed(wired) -> None:
    """Identifiers are not secrets, but echoing them by default is how they reach a public issue."""
    flat = repr(handler_module.handler({}))
    for value in ("fs-0123456789abcdef0", "svm-0123456789abcdef0", "example-alias"):
        assert value not in flat


def test_event_keys_are_listed_for_a_mapping(wired) -> None:
    assert handler_module.handler({"b": 1, "a": 2})["event_keys"] == ["a", "b"]


def test_a_non_mapping_event_does_not_raise(wired) -> None:
    assert handler_module.handler(["not", "a", "mapping"])["event_keys"] is None
