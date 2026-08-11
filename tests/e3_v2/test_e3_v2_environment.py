# -*- coding: utf-8 -*-
"""E3-V2 环境生成器测试（configs/e3_v2/e3_v2_environment_definition.yaml；E3-0 冻结）。

覆盖：
- AC-E1：生成器确定性（同 seed 两次生成逐字节一致）；
- AC-E2：前缀一致性（high 的前 N_low 个任务/链路 == low 的完整实例）；
- AC-E3：三压力档 N 候选 = {low:20, transition:80, high:150}；
- AC-E4：pressure 仅语义标记，不改变生成规则（同 seed 同 N 实例与 pressure 无关）。
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_TESTS)
_GEN_DIR = os.path.join(_PROJECT, "scripts", "reproduce", "e3_v2")
for _p in (_TESTS, _GEN_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from build_e3_v2_environment import (  # noqa: E402
    PRESSURE_N_CANDIDATE,
    PRESSURE_ORDER,
    build_e3_v2_environment,
    prefix_scenario,
)

M = 8


def test_environment_deterministic():
    """AC-E1：同 seed 两次生成逐字节一致。"""
    a = build_e3_v2_environment(seed=201, n_max=50, pressure="low")
    b = build_e3_v2_environment(seed=201, n_max=50, pressure="low")
    assert a == b
    # 序列化一致性（SHA 级）
    sa = json.dumps(a, sort_keys=True, ensure_ascii=False)
    sb = json.dumps(b, sort_keys=True, ensure_ascii=False)
    assert sa == sb


def test_prefix_consistency():
    """AC-E2：high(150) 的前 20 个任务/链路与 low(20) 完全一致（前缀一致性）。"""
    high = build_e3_v2_environment(seed=201, n_max=150, pressure="high")
    low = build_e3_v2_environment(seed=201, n_max=20, pressure="low")
    assert low["tasks"] == high["tasks"][:20]
    assert low["devices"] == high["devices"][:20]
    assert low["links"] == high["links"][: 20 * M]
    # 服务器固定（不随 N 变）
    assert low["servers"] == high["servers"]
    # prefix_scenario 与直接构造一致
    pre = prefix_scenario(high, 20)
    assert pre["tasks"] == low["tasks"]
    assert pre["links"] == low["links"]


def test_pressure_n_candidates():
    """AC-E3：三压力档 N 候选冻结值。"""
    assert PRESSURE_N_CANDIDATE == {"low": 20, "transition": 80, "high": 150}
    assert PRESSURE_ORDER == ["low", "transition", "high"]


def test_pressure_is_metadata_only():
    """AC-E4：pressure 仅语义标记；同 seed 同 N 的实例与 pressure 无关。"""
    a = build_e3_v2_environment(seed=201, n_max=80, pressure="transition")
    b = build_e3_v2_environment(seed=201, n_max=80, pressure="high")
    # 除 scenario_id/pressure（语义标记）外完全一致
    aa = json.loads(json.dumps(a))
    bb = json.loads(json.dumps(b))
    aa.pop("scenario_id", None)
    bb.pop("scenario_id", None)
    aa.pop("pressure", None)
    bb.pop("pressure", None)
    assert aa == bb


def test_invalid_pressure_rejected():
    """AC-E5：非法 pressure 拒绝。"""
    with pytest.raises(ValueError):
        build_e3_v2_environment(seed=201, n_max=80, pressure="invalid")
