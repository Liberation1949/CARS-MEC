# -*- coding: utf-8 -*-
"""E0-V2 环境生成器测试（scripts/reproduce/e0_v2/build_e0_v2_environment.py；E0-V2-0 冻结）。

覆盖（AC-3）：
- 确定性：同 seed 两次生成逐字节一致；
- 嵌套任务链：Gamma_20 ⊂ Gamma_50 ⊂ Gamma_80 ⊂ Gamma_150 ⊂ Gamma_260（前缀包含）；
- 服务器固定：服务器集合与 N 无关（只依赖 seed）；
- 结构合法：任务数=N、链路数=N*M、服务器数=M；
- 与 E3-V2 同规则交叉验证：同 seed 同 N 的 tasks/devices/servers/links 与 E3-V2 生成器一致
  （仅 scenario_id 前缀不同；代码级复用的忠实性证据）；
- scenario_id 标记为 e0v2。
"""

from __future__ import annotations

import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_TESTS)
_E0_GEN_DIR = os.path.join(_PROJECT, "scripts", "reproduce", "e0_v2")
_E3_GEN_DIR = os.path.join(_PROJECT, "scripts", "reproduce", "e3_v2")
for _p in (_TESTS, _E0_GEN_DIR, _E3_GEN_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from build_e0_v2_environment import (  # noqa: E402
    E0_FORMAL_SEEDS,
    E0_N_MAX,
    E0_PILOT_N_GRID,
    E0_PILOT_SEEDS,
    build_e0_v2_environment,
    build_e0_v2_super_scenario,
    e0_prefix_scenario,
)

M = 8


def test_environment_deterministic():
    """AC-3a：同 seed 两次生成逐字节一致（确定性）。"""
    a = build_e0_v2_environment(seed=201, n=80)
    b = build_e0_v2_environment(seed=201, n=80)
    assert a == b
    assert json.dumps(a, sort_keys=True, ensure_ascii=False) == \
        json.dumps(b, sort_keys=True, ensure_ascii=False)


def test_nested_task_chain():
    """AC-3b：嵌套任务链 Gamma_20 ⊂ Gamma_50 ⊂ ... ⊂ Gamma_260（前缀包含）。"""
    super_cfg = build_e0_v2_super_scenario(seed=201, n_max=260)
    prev_tasks = None
    prev_links = 0
    for n in [20, 50, 80, 150, 260]:
        pre = e0_prefix_scenario(super_cfg, n)
        assert len(pre["tasks"]) == n
        assert len(pre["devices"]) == n
        assert len(pre["links"]) == n * M
        if prev_tasks is not None:
            # 小规模是大规模的前缀（固定子集）
            assert pre["tasks"][: len(prev_tasks)] == prev_tasks
        prev_tasks = pre["tasks"]
        prev_links = len(pre["links"])


def test_servers_fixed_across_n():
    """AC-3c：服务器集合与 N 无关（只依赖 seed）。"""
    super_cfg = build_e0_v2_super_scenario(seed=202, n_max=260)
    s20 = e0_prefix_scenario(super_cfg, 20)
    s260 = e0_prefix_scenario(super_cfg, 260)
    assert s20["servers"] == s260["servers"]
    assert len(s20["servers"]) == M


def test_structure_valid():
    """AC-3d：结构合法（任务/链路/服务器数量；必填字段）。"""
    super_cfg = build_e0_v2_super_scenario(seed=203, n_max=260)
    pre = e0_prefix_scenario(super_cfg, 80)
    assert len(pre["tasks"]) == 80
    assert len(pre["links"]) == 80 * M
    assert len(pre["servers"]) == M
    for t in pre["tasks"]:
        assert "min_reliability" in t
        assert "cpu_cycles" in t
        assert "fragility" in t
    for s in pre["servers"]:
        assert "capacity_cycles_per_sec" in s
        assert "nominal_failure_rate" in s
    # 无 deadline：占位字段存在，但逻辑不使用（结构合法即可）
    assert all("deadline_seconds" in t for t in pre["tasks"])


def test_scenario_id_e0v2():
    """AC-3e：scenario_id 标记 e0v2。"""
    cfg = build_e0_v2_environment(seed=201, n=80)
    assert cfg["scenario_id"].startswith("e0v2_n80_")
    super_cfg = build_e0_v2_super_scenario(seed=201, n_max=260)
    assert super_cfg["scenario_id"].startswith("e0v2_n260_")


def test_same_rule_as_e3_v2():
    """AC-3f：与 E3-V2 生成器同规则（同 seed 同 N 的 tasks/devices/servers/links 一致）。

    代码级复用（build_e0_v2_environment 内部调用 build_e3_v2_environment）的忠实性证据；
    仅 scenario_id 前缀（e0v2 vs e3v2）不同。
    """
    from build_e3_v2_environment import build_e3_v2_environment as build_e3

    e3 = build_e3(seed=201, n_max=80, pressure="transition")
    e0 = build_e0_v2_environment(seed=201, n=80)
    assert e0["tasks"] == e3["tasks"]
    assert e0["devices"] == e3["devices"]
    assert e0["servers"] == e3["servers"]
    assert e0["links"] == e3["links"]
    assert e0["system_params"] == e3["system_params"]


def test_frozen_grids_and_seeds():
    """AC-3g：Pilot 网格 / seeds / N_max / formal seeds 冻结值。"""
    assert E0_PILOT_N_GRID == [20, 40, 60, 80, 100, 120, 150, 180, 220, 260]
    assert E0_PILOT_SEEDS == [201, 202, 203, 204, 205]
    assert E0_FORMAL_SEEDS == list(range(601, 621))
    assert E0_N_MAX == 260


def test_prefix_matches_direct_build():
    """AC-3h：e0_prefix_scenario(super, n) 与直接 build_e0_v2_environment(seed, n) 一致。"""
    super_cfg = build_e0_v2_super_scenario(seed=205, n_max=260)
    pre = e0_prefix_scenario(super_cfg, 40)
    direct = build_e0_v2_environment(seed=205, n=40)
    assert pre["tasks"] == direct["tasks"]
    assert pre["devices"] == direct["devices"]
    assert pre["links"] == direct["links"]
    assert pre["servers"] == direct["servers"]


def test_different_seed_different_instance():
    """AC-3i：不同 seed 生成不同实例（随机源分离）。"""
    a = build_e0_v2_environment(seed=201, n=80)
    b = build_e0_v2_environment(seed=202, n=80)
    assert a["tasks"] != b["tasks"]
