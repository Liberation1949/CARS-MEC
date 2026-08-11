# -*- coding: utf-8 -*-
"""E1-3 Stage 1 冻结测试（Baseline Computational-Budget Sensitivity 协议）。

AC-8 覆盖（协议测试）：
1. multiplier 精确为 {0.5, 1.0, 2.0, 4.0}；
2. methods 精确包含 BPSO-RATA-LA / NFA / CARS reference；
3. CARS 不存在 scaleable search-budget parameter；
4. 1× 与当前正式 E1 baseline config（R6 frozen）完全一致；
5. 非 budget 参数在四档中保持一致；
6. seeds 完全一致（== e1_v2_protocol formal_seeds）；
7. scenario 完全一致（N=200, M=8）；
8. timeout policy 完全一致（30s 共享；无 4× 特殊 timeout）；
9. metric definitions 不被重写；
10. 预算映射确定性（BPSO cap=K·(L+1)+64；NFA cap=mult×4744）；
11. YAML deterministic serialization；
12. 人工微型案例（canonical budget 缩放 100 → 50/100/200/400）；
13. 禁止项守卫（Pilot 未授权、无性能结论）。

本测试只读协议/配置；不运行任何算法。
"""
from __future__ import annotations

import os
import sys

import pytest
import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
PROTOCOL = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_sensitivity_protocol.yaml")
BPSO_FROZEN = os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml")
NFA_FROZEN = os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml")
E1_PROTOCOL = os.path.join(_PROJECT, "configs", "e1_v2", "e1_v2_protocol.yaml")


def _load(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


@pytest.fixture(scope="module")
def p():
    return _load(PROTOCOL)


@pytest.fixture(scope="module")
def bpso_1x():
    return _load(BPSO_FROZEN)


@pytest.fixture(scope="module")
def nfa_1x():
    return _load(NFA_FROZEN)


# ---------------------------------------------------------------------------
# 1. multiplier 精确为 {0.5, 1.0, 2.0, 4.0}
# ---------------------------------------------------------------------------
def test_multipliers_exact(p):
    assert p["budget_multipliers"] == [0.5, 1.0, 2.0, 4.0]


# ---------------------------------------------------------------------------
# 2. methods 精确包含 BPSO-RATA-LA / NFA / CARS reference
# ---------------------------------------------------------------------------
def test_methods_exact(p):
    assert p["methods"]["scanned"] == ["bpso_rata_la", "nfa_adapted"]
    assert p["methods"]["reference"] == ["cars"]
    assert p["methods"]["reference_method"] == "cars"
    # 不重跑的方法明确列出
    assert p["methods"]["not_included"] == [
        "jtora_adapted", "reliability_only", "local_only", "foa",
    ]


# ---------------------------------------------------------------------------
# 3. CARS 不存在 scaleable search-budget parameter
# ---------------------------------------------------------------------------
def test_cars_no_budget_parameter(p):
    whitelist = p["parameter_whitelist"]["cars"]
    assert whitelist["allowed_to_scale"] == []
    assert "frozen" in whitelist


# ---------------------------------------------------------------------------
# 4. 1× 与当前正式 E1 baseline config（R6 frozen）完全一致
# ---------------------------------------------------------------------------
def test_bpso_1x_matches_frozen(p, bpso_1x):
    m1 = p["budget_parameter_mapping"]["bpso_rata_la"]["multiplier_map"]["1.0"]
    assert m1["population_size_max"] == bpso_1x["population_size_max"] == 8
    assert m1["max_iterations_max"] == bpso_1x["max_iterations_max"] == 5
    assert m1["particle_evaluation_cap_max"] == bpso_1x["particle_evaluation_cap_max"] == 112
    # 协议中登记的 1× 配置路径与实际 frozen 文件一致
    assert p["methods"]["baseline_1x_configs"]["bpso_rata_la"].endswith("bpso_frozen.yaml")


def test_nfa_1x_matches_frozen(p, nfa_1x):
    m1 = p["budget_parameter_mapping"]["nfa_adapted"]["multiplier_map"]["1.0"]
    assert m1["population_size_max"] == nfa_1x["population_size_max"] == 8
    assert m1["max_generations_max"] == nfa_1x["max_generations_max"] == 10
    assert m1["objective_evaluation_cap_max"] == nfa_1x["objective_evaluation_cap_max"] == 4744
    assert p["methods"]["baseline_1x_configs"]["nfa_adapted"].endswith("nfa_frozen.yaml")


# ---------------------------------------------------------------------------
# 5. 非 budget 参数在四档中保持一致
# ---------------------------------------------------------------------------
def _frozen_keys(method):
    return {
        "bpso_rata_la": ["max_iterations_max"],
        "nfa_adapted": ["population_size_max", "max_generations_max"],
    }[method]


def test_non_budget_params_consistent(p):
    # BPSO：四档中除 allowed_to_scale 外，结构参数一致
    bpso_map = p["budget_parameter_mapping"]["bpso_rata_la"]["multiplier_map"]
    iters = {v["max_iterations_max"] for v in bpso_map.values()}
    assert iters == {5}
    # NFA：四档中 pop/gen 一致（frozen 为 8/10），仅 cap 变化
    nfa_map = p["budget_parameter_mapping"]["nfa_adapted"]["multiplier_map"]
    pops = {v["population_size_max"] for v in nfa_map.values()}
    gens = {v["max_generations_max"] for v in nfa_map.values()}
    assert pops == {8}
    assert gens == {10}


# ---------------------------------------------------------------------------
# 6. seeds 完全一致（== e1_v2_protocol formal_seeds）
# ---------------------------------------------------------------------------
def test_seeds_match_e1(p):
    e1 = _load(E1_PROTOCOL)
    assert p["seeds"] == e1["formal_seeds"] == list(range(1101, 1111))


# ---------------------------------------------------------------------------
# 7. scenario 完全一致（N=200, M=8）
# ---------------------------------------------------------------------------
def test_scenario_frozen(p):
    assert p["scenario"]["n"] == 200
    assert p["scenario"]["m"] == 8
    assert p["scenario"]["topology"] == "fully connected"


# ---------------------------------------------------------------------------
# 8. timeout policy 完全一致（30s 共享；无 4× 特殊 timeout）
# ---------------------------------------------------------------------------
def test_timeout_shared(p):
    assert p["timeout_policy"]["shared_timeout_seconds"] == 30.0
    rule = p["timeout_policy"]["rule"]
    assert "所有 budget 档位使用同一 timeout policy" in rule
    assert "不允许 4× 获得特殊无限 timeout" in rule
    assert "timeout 必须进入正式统计" in rule
    assert "不允许人为关闭原有 early stop" in p["timeout_policy"]["rule"] or \
        "不允许人为关闭原有" in p["early_stop_policy"].get("rule", "")


# ---------------------------------------------------------------------------
# 9. metric definitions 不被重写
# ---------------------------------------------------------------------------
def test_metrics_not_rewritten(p):
    m = p["metrics"]
    assert "tssr" in m["primary_quality"]
    assert "mean_effective_reliability" in m["secondary_quality"]
    assert "mean_effective_utility" in m["secondary_quality"]
    assert "reliability_violation_rate" in m["secondary_quality"]
    assert "method_runtime_ms" in m["computational"]
    assert "total_wall_time_ms" in m["computational"]
    assert "configured_budget_multiplier" in m["computational"]
    assert "actual_consumed_search_evaluations" in m["computational"]
    assert "timeout" in m["computational"]


# ---------------------------------------------------------------------------
# 10. 预算映射确定性（BPSO cap=K·(L+1)+64；NFA cap=mult×4744）
# ---------------------------------------------------------------------------
def test_bpso_budget_mapping_deterministic(p):
    bpso = p["budget_parameter_mapping"]["bpso_rata_la"]
    assert bpso["primary_budget_knob"] == "population_size_max"
    for mult, cfg in bpso["multiplier_map"].items():
        k = cfg["population_size_max"]
        L = cfg["max_iterations_max"]
        assert cfg["particle_evaluation_cap_max"] == k * (L + 1) + 64
        assert cfg["expected_search_evaluations"] == k * (L + 1)


def test_nfa_budget_mapping_deterministic(p):
    nfa = p["budget_parameter_mapping"]["nfa_adapted"]
    assert nfa["primary_budget_knob"] == "objective_evaluation_cap_max"
    for mult, cfg in nfa["multiplier_map"].items():
        assert cfg["objective_evaluation_cap_max"] == float(mult) * 4744
        assert cfg["population_size_max"] == 8
        assert cfg["max_generations_max"] == 10


# ---------------------------------------------------------------------------
# 11. YAML deterministic serialization
# ---------------------------------------------------------------------------
def test_deterministic_serialization(p):
    s1 = yaml.safe_dump(p, allow_unicode=True, sort_keys=False)
    s2 = yaml.safe_dump(_load(PROTOCOL), allow_unicode=True, sort_keys=False)
    assert s1 == s2


# ---------------------------------------------------------------------------
# 12. 人工微型案例（canonical budget 缩放 100 → 50/100/200/400）
# ---------------------------------------------------------------------------
def test_manual_micro_case_budget_scaling():
    # 假设某算法 1× canonical budget = 100 evaluations
    baseline = 100
    expected = {0.5: 50, 1.0: 100, 2.0: 200, 4.0: 400}
    for mult, target in expected.items():
        assert int(round(baseline * mult)) == target
    # 本协议两算法全档位整数精确达成，relative_error = 0
    bpso = [24, 48, 96, 192]
    nfa = [2372, 4744, 9488, 18976]
    for arr, base in ((bpso, 48), (nfa, 4744)):
        for mult, actual in zip([0.5, 1.0, 2.0, 4.0], arr):
            target = base * mult
            assert actual == target  # relative_error = 0
            assert isinstance(actual, int)


# ---------------------------------------------------------------------------
# 13. 禁止项守卫（Pilot 未授权；formal 需授权；无性能结论条款）
# ---------------------------------------------------------------------------
def test_stage_guards(p):
    assert p["stage"] == "Stage 1：实验协议与预算映射冻结（FREEZE_ONLY）"
    assert p["status_date"] == "2026-08-09"
    assert p["pilot_gate"]["authorized"] is False
    assert "formal_freeze_rule" in p
    forbidden = p["forbidden"]
    assert any("不运行 Pilot / Formal" in s for s in forbidden)
    assert any("不生成任何性能结论" in s for s in forbidden)
    assert any("不重新定义 1×" in s for s in forbidden)
