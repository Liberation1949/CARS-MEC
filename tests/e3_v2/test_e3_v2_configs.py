# -*- coding: utf-8 -*-
"""E3-V2 冻结配置一致性测试（E3-0）。

覆盖：
- AC-C1：三个冻结 yaml 可加载且版本正确；
- AC-C2：variant 矩阵 <-> 字段定义覆盖一致（7 个执行单元、5 个 AADA 变体 + 2 fixed）；
- AC-C3：forbidden 一致性（旧 RUAD/CALA/Repair 消融全部禁止）；
- AC-C4：环境定义三档机制触发标准非空、seeds 冻结值正确。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_TESTS)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import yaml  # noqa: E402

CONFIG_DIR = os.path.join(_PROJECT, "configs", "e3_v2")
VARIANT_MATRIX = os.path.join(CONFIG_DIR, "e3_v2_variant_matrix.yaml")
FIELD_DEFS = os.path.join(CONFIG_DIR, "e3_v2_variant_field_definitions.yaml")
ENV_DEF = os.path.join(CONFIG_DIR, "e3_v2_environment_definition.yaml")

AADA_VARIANTS = {"full", "no_rescue", "rescue_only", "no_alloc_aware", "no_utility_gate"}


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def test_configs_load_and_version():
    """AC-C1：三个 yaml 可加载且版本正确。"""
    vm = _load(VARIANT_MATRIX)
    fd = _load(FIELD_DEFS)
    env = _load(ENV_DEF)
    assert vm["variant_matrix_version"] == "E3_V2_VARIANT_MATRIX_V1"
    assert fd["field_definitions_version"] == "E3_V2_VARIANT_FIELD_DEFINITIONS_V1"
    assert env["environment_definition_version"] == "E3_V2_ENVIRONMENT_DEFINITION_V1"


def test_variant_matrix_consistency():
    """AC-C2：variant 矩阵 7 个执行单元；5 个 AADA 变体 + 2 个 fixed-assignment 对照。"""
    vm = _load(VARIANT_MATRIX)
    fd = _load(FIELD_DEFS)
    variants = vm["variants"]
    assert set(variants.keys()) == {
        "full_cars", "w_no_rescue", "w_rescue_only", "w_no_alloc_aware",
        "w_no_utility_gate", "fixed_a_rcla", "fixed_a_la",
    }
    # 字段定义的 variant_overrides 键一致
    assert set(fd["variant_overrides"].keys()) == set(variants.keys())
    # 每个 variant 的 aada_variant 在合法集合内
    for vid, v in variants.items():
        assert v["aada_variant"] in AADA_VARIANTS
        assert v["allocation_mode"] in {"rcla", "ordinary_la"}
    # 5 个 AADA 变体（aada_variant 覆盖 5 值）+ 2 个 fixed 共享 full
    assert {v["aada_variant"] for v in variants.values()} == AADA_VARIANTS
    # fixed-assignment 对照：同一 X/A hash 协议存在
    assert "fixed_assignment_protocol" in vm
    assert "freeze_and_hash_X0_A0" in vm["fixed_assignment_protocol"]["steps"]


def test_forbidden_consistent():
    """AC-C3：旧消融框架全部禁止（matrix 与字段定义一致）。"""
    vm = _load(VARIANT_MATRIX)
    fd = _load(FIELD_DEFS)
    vm_f = set(vm["forbidden"])
    fd_f = set(fd["forbidden"])
    for item in ("ruad_q_z_ablation", "cala_kappa_ablation", "repair_blr_ablation", "gamma"):
        assert item in vm_f
        assert item in fd_f
    # admission constraint 不消融（正确性不变量；matrix 冻结）
    assert vm["admission_constraint"] == "NOT_ABLATED"
    assert vm["expected_correctness"] == "N_ALLOCATION_INFEASIBLE = 0"


def test_environment_definition():
    """AC-C4：环境定义机制触发标准与 seeds 冻结。"""
    env = _load(ENV_DEF)
    levels = env["pressure_levels"]
    assert set(levels.keys()) == {"low", "transition", "high"}
    for lev in levels.values():
        assert lev["role"] and lev["mechanism_target"] and lev["selection_criterion"]
    assert env["n_candidates"]["low"] == 20
    assert env["n_candidates"]["transition"] == 80
    assert env["n_candidates"]["high"] == 150
    assert env["seeds"]["pilot"] == [201, 202, 203]
    assert len(env["seeds"]["formal"]) == 10
    assert env["seeds"]["formal"][0] == 401
    # formal seeds 不与旧 E3 formal (301-305) / validation (201-203) 重叠
    formal = set(env["seeds"]["formal"])
    assert not (formal & {301, 302, 303, 304, 305})
    assert not (formal & {201, 202, 203})
