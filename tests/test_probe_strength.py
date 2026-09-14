"""Probe strength, in both directions.

The heading-only rule exists because a sibling ran a criterion this repository did not have and
found three registrations against it that could never fire. All three occur exactly once, so the
multiplicity rule -- the only weakness check here at the time -- was silent on every one. The two
rules are independent, and this file pins that: the same string can be weak under one and sound
under the other.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


strength = load("probe_strength")


# --- heading-only ------------------------------------------------------------------------------


def test_a_probe_that_only_matches_a_heading_is_weak() -> None:
    body = "# Title\n\n## 課金次元の対応\n\n片方にあって他方にない項目が制約になる。\n"
    assert strength.heading_only(body, "課金次元の対応")


def test_the_same_string_in_the_body_makes_it_sound() -> None:
    """本文にあるなら、節の中身が入れ替わったときに発火する。"""
    body = (
        "## 課金次元の対応\n\n課金次元の対応を並べると、片方にない項目が制約になる。\n"
    )
    assert not strength.heading_only(body, "課金次元の対応")


def test_an_absent_string_is_not_reported_as_weak() -> None:
    """不在は別の判定（撤回）の担当。ここで真を返すと 2 つの報告が混ざる。"""
    assert not strength.heading_only("## Something else\n", "課金次元の対応")


def test_four_spaces_of_indent_is_a_code_block_not_a_heading() -> None:
    """CommonMark の見出しは先頭 3 スペースまで。4 つ目からはコードブロック。"""
    assert strength.heading_only(
        "   ## 測定前の合否基準の決定\n", "測定前の合否基準の決定"
    )
    assert not strength.heading_only(
        "    ## 測定前の合否基準の決定\n", "測定前の合否基準の決定"
    )


def test_a_hash_without_a_space_is_not_a_heading() -> None:
    assert not strength.heading_only("#不可逆・作り直しになる操作 in prose\n", "不可逆")


# --- multiplicity, and its independence from the above -----------------------------------------


def test_the_two_rules_do_not_subsume_each_other() -> None:
    once_in_a_heading = "## 課金次元の対応\n\nbody\n"
    twice_in_the_body = "0.18 倍 でした。\n\n別の節でも 0.18 倍 と書いた。\n"

    assert strength.heading_only(once_in_a_heading, "課金次元の対応")
    assert strength.occurrences(once_in_a_heading, "課金次元の対応") == 1

    assert not strength.heading_only(twice_in_the_body, "0.18 倍")
    assert strength.occurrences(twice_in_the_body, "0.18 倍") == 2


# --- the wiring --------------------------------------------------------------------------------


def test_both_directions_use_the_same_predicate() -> None:
    """規則を 2 か所に書くと片方だけが直る。多重一致がまさにその形で二重化していた。"""
    shared = ROOT / "tools" / "probe_strength.py"
    for checker in ("check_incoming_probes", "check_outgoing_probes"):
        module = load(checker)
        # 同一オブジェクトではなく同一ソースで縛る。テスト側の loader が別インスタンスを作る。
        assert Path(module.probe_strength.__file__) == shared, checker
        for name in ("heading_only", "occurrences"):
            assert hasattr(module.probe_strength, name), (checker, name)
