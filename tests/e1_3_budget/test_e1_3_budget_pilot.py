# -*- coding: utf-8 -*-
"""E1-3 Stage 2 冻结测试（Pilot 校准与 Formal 配置冻结；AC-3/4/5/6/7/9/10）。

覆盖（合同 Step 4）：
1. instrumentation 不改变算法（src 算法 hash 零变化 = 审计锚点；extract 纯函数）；
2. 同 seed 同配置 deterministic（canonical_hash 存在且 per (method,seed,mult) 唯一）；
3. 0.5/1/2/4 mapping 与 Stage-1 一致；
4. actual consumed count 非负；
5. early-stop 标志合法（== cap_reached or soft_deadline_triggered）；
6. timeout record 不丢失（标志与 TIMEOUT 状态一致）；
7. runtime > 0；
8. raw record schema 合法（必填字段齐全）；
9. Pilot seeds 与 Formal seeds 无交集；
10. CARS 无 budget scaling；
11. Formal frozen config 不含 Pilot 结果驱动超参（== Stage-1 mapping；timeout 保持 30s）；
12. 人工微型案例（BPSO/NFA 理论 evaluation count 与 instrumentation 逐项一致）；
13. py_compile。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys

import pytest
import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_3_budget"))

STAGE1 = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_sensitivity_protocol.yaml")
PILOT_CFG = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_pilot.yaml")
FORMAL_FROZEN = os.path.join(_PROJECT, "configs", "e1_3_budget", "e1_3_budget_formal_frozen.yaml")
RAW = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_pilot", "pilot_raw.jsonl")
SUMMARY = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_pilot", "pilot_summary.json")
INTEGRITY = os.path.join(_PROJECT, "results", "e1_3_budget", "budget_pilot", "pilot_integrity.json")

# Stage-2 Pre-state 审计锚点：instrumentation 零算法修改（本阶段关闭后必须保持）。
# 注：不锚定 experiment_docs/III_VII.md（正文由作者并行编辑，hash 由作者维护，
# 本测试只锚定 E1-3 依赖的算法/配置/协议文件——它们在 Stage-2 必须零变化）。
SRC_HASH_ANCHOR = {
    "src/cars/methods/bpso_rata_la/bpso.py": "dfb5fce26f849448",
    "src/cars/methods/nfa_adapted/core.py": "7c07d9eed56f35da",
    "src/cars/methods/nfa_adapted/decode.py": "4a72c3805c7cc8d6",
}

REQUIRED_RAW_FIELDS = [
    "method", "seed", "scenario_id", "budget_multiplier", "configured_native_budget",
    "actual_consumed_search_evaluations", "executed_iterations", "executed_search_steps",
    "early_stop", "timeout", "runtime_ms", "result_status",
]


def _load_yaml(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_jsonl(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return [json.loads(line) for line in fh]


def _sha16(rel):
    with open(os.path.join(_PROJECT, rel), "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# 1. instrumentation 不改变算法（src hash 零变化 + extract 纯函数）
# ---------------------------------------------------------------------------
def test_instrumentation_no_algorithm_modification():
    for rel, anchor in SRC_HASH_ANCHOR.items():
        assert _sha16(rel) == anchor, "算法源码被修改——instrumentation 必须只读"


def test_extract_is_pure_function():
    from run_e1_3_budget_pilot import extract_budget_diagnostics
    diag = {"particle_evaluations": 48, "completed_iterations": 5, "population_size": 8,
            "max_iterations": 5, "soft_deadline_triggered": False}
    conf = {"population_size": 8, "max_iterations": 5, "cap": 112}
    a = extract_budget_diagnostics("bpso_rata_la", diag, conf)
    b = extract_budget_diagnostics("bpso_rata_la", diag, conf)
    assert a == b  # 纯函数：同输入同输出


# ---------------------------------------------------------------------------
# 2. 同 seed 同配置 deterministic（canonical_hash 存在且 per 组合唯一）
# ---------------------------------------------------------------------------
def test_canonical_hash_present_and_unique():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    keys = set()
    for r in raw:
        assert r["canonical_hash"], "canonical_hash 缺失"
        k = (r["method"], r["seed"], r["budget_multiplier"])
        assert k not in keys, "同 (method,seed,mult) 重复——非确定性"
        keys.add(k)


# ---------------------------------------------------------------------------
# 3. 0.5/1/2/4 mapping 与 Stage-1 一致
# ---------------------------------------------------------------------------
def test_mapping_consistent_with_stage1():
    stage1 = _load_yaml("configs/e1_3_budget/e1_3_budget_sensitivity_protocol.yaml")
    formal = _load_yaml("configs/e1_3_budget/e1_3_budget_formal_frozen.yaml")
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    for method in ["bpso_rata_la", "nfa_adapted"]:
        smap = stage1["budget_parameter_mapping"][method]["multiplier_map"]
        fmap = formal["budget_configs"][method]
        assert set(fmap) == set(smap) == {"0.5", "1.0", "2.0", "4.0"}
        for r in raw:
            if r["method"] == method:
                conf = r["configured_native_budget"]
                expected = smap[str(r["budget_multiplier"])]
                if method == "bpso_rata_la":
                    assert conf["population_size"] == expected["population_size_max"]
                    assert conf["max_iterations"] == expected["max_iterations_max"]
                    assert conf["cap"] == expected["particle_evaluation_cap_max"]
                else:
                    assert conf["population_size"] == expected["population_size_max"]
                    assert conf["max_generations"] == expected["max_generations_max"]
                    assert conf["cap"] == expected["objective_evaluation_cap_max"]
    # formal frozen 的每档配置 == Stage-1 mapping 的实际预算键（忽略辅助字段）
    for method in ["bpso_rata_la", "nfa_adapted"]:
        smap = stage1["budget_parameter_mapping"][method]["multiplier_map"]
        fmap = formal["budget_configs"][method]
        budget_keys = (["population_size_max", "max_iterations_max", "particle_evaluation_cap_max"]
                       if method == "bpso_rata_la"
                       else ["population_size_max", "max_generations_max", "objective_evaluation_cap_max"])
        for k in fmap:
            for bk in budget_keys:
                assert fmap[k][bk] == smap[k][bk], "Formal 配置与 Stage-1 mapping 不一致 (%s %s)" % (method, k)


# ---------------------------------------------------------------------------
# 4. actual consumed count 非负
# ---------------------------------------------------------------------------
def test_consumed_non_negative():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    for r in raw:
        if r["method"] == "cars":
            assert r["actual_consumed_search_evaluations"] is None
        else:
            assert r["actual_consumed_search_evaluations"] is not None
            assert r["actual_consumed_search_evaluations"] >= 0


# ---------------------------------------------------------------------------
# 5. early-stop 标志合法
# ---------------------------------------------------------------------------
def test_early_stop_flag_legal():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    for r in raw:
        if r["method"] == "cars":
            assert r["early_stop"] is False
        else:
            assert r["early_stop"] == bool(r["cap_reached"] or r["soft_deadline_triggered"])
            assert r["early_stop"] in (True, False)


# ---------------------------------------------------------------------------
# 6. timeout record 不丢失
# ---------------------------------------------------------------------------
def test_timeout_recorded():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    timeouts = [r for r in raw if r["timeout"]]
    assert len(timeouts) >= 1  # NFA 4× seed 201（Pilot 实测）
    for r in timeouts:
        assert r["result_status"] == "TIMEOUT"
    for r in raw:
        if r["result_status"] == "TIMEOUT":
            assert r["timeout"] is True


# ---------------------------------------------------------------------------
# 7. runtime > 0
# ---------------------------------------------------------------------------
def test_runtime_positive():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    for r in raw:
        assert r["runtime_ms"] is not None
        assert r["runtime_ms"] > 0


# ---------------------------------------------------------------------------
# 8. raw record schema 合法
# ---------------------------------------------------------------------------
def test_raw_record_schema():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    assert len(raw) == 27  # (2*4+1)*3
    for r in raw:
        for f in REQUIRED_RAW_FIELDS:
            assert f in r, "raw 缺少必填字段 %s" % f
        assert r["result_status"] in ("SUCCESS", "BUDGET_EXHAUSTED", "TIMEOUT", "METHOD_ERROR")


# ---------------------------------------------------------------------------
# 9. Pilot seeds 与 Formal seeds 无交集
# ---------------------------------------------------------------------------
def test_pilot_formal_seeds_disjoint():
    pilot = _load_yaml("configs/e1_3_budget/e1_3_budget_pilot.yaml")
    stage1 = _load_yaml("configs/e1_3_budget/e1_3_budget_sensitivity_protocol.yaml")
    formal = _load_yaml("configs/e1_3_budget/e1_3_budget_formal_frozen.yaml")
    ps = set(pilot["pilot"]["seeds"])
    fs = set(stage1["seeds"])
    assert ps & fs == set()
    assert list(formal["seeds"]) == list(stage1["seeds"]) == list(range(1101, 1111))
    integrity = _load_json("results/e1_3_budget/budget_pilot/pilot_integrity.json")
    assert integrity["seed_disjoint"] is True


# ---------------------------------------------------------------------------
# 10. CARS 无 budget scaling
# ---------------------------------------------------------------------------
def test_cars_no_budget_scaling():
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    cars = [r for r in raw if r["method"] == "cars"]
    assert len(cars) == 3
    for r in cars:
        assert r["budget_multiplier"] is None
        assert r["configured_native_budget"] is None
        assert r["actual_consumed_search_evaluations"] is None
        assert r["result_status"] == "SUCCESS"


# ---------------------------------------------------------------------------
# 11. Formal frozen config 不含 Pilot 结果驱动超参
# ---------------------------------------------------------------------------
def test_formal_frozen_no_pilot_driven_params():
    formal = _load_yaml("configs/e1_3_budget/e1_3_budget_formal_frozen.yaml")
    stage1 = _load_yaml("configs/e1_3_budget/e1_3_budget_sensitivity_protocol.yaml")
    # timeout 保持 Stage-1（Pilot 后未调整）
    assert formal["timeout"]["shared_timeout_seconds"] == 30.0
    assert formal["timeout"]["adjustment_history"] == "无（保持 Stage-1 30s；最多一次 timeout calibration 未被触发）"
    # 每档配置 == Stage-1 mapping 的实际预算键（无任何 Pilot 驱动修改；忽略 Stage-1 辅助字段）
    for method in ["bpso_rata_la", "nfa_adapted"]:
        smap = stage1["budget_parameter_mapping"][method]["multiplier_map"]
        budget_keys = (["population_size_max", "max_iterations_max", "particle_evaluation_cap_max"]
                       if method == "bpso_rata_la"
                       else ["population_size_max", "max_generations_max", "objective_evaluation_cap_max"])
        for k in formal["budget_configs"][method]:
            for bk in budget_keys:
                assert formal["budget_configs"][method][k][bk] == smap[k][bk]
    # formal seeds 固定
    assert formal["seeds"] == list(range(1101, 1111))
    # 统计计划预注册
    assert formal["statistical_plan"]["pre_registered"] is True
    assert "Performance–Runtime Tradeoff" in formal["statistical_plan"]["outputs"]["figure"]


# ---------------------------------------------------------------------------
# 12. 人工微型案例（instrumentation 输出 vs 理论 evaluation count）
# ---------------------------------------------------------------------------
def test_manual_micro_case_budget_counts():
    # BPSO：理论粒子评价数 = K*(L+1)
    expected_bpso = {0.5: 4 * 6, 1.0: 8 * 6, 2.0: 16 * 6, 4.0: 32 * 6}
    # NFA：理论 = cap 触达
    expected_nfa = {0.5: 2372, 1.0: 4744, 2.0: 9488, 4.0: 18976}
    raw = _load_jsonl("results/e1_3_budget/budget_pilot/pilot_raw.jsonl")
    for mult, exp in expected_bpso.items():
        rows = [r for r in raw if r["method"] == "bpso_rata_la" and r["budget_multiplier"] == mult]
        assert len(rows) == 3
        for r in rows:
            assert r["actual_consumed_search_evaluations"] == exp  # relative_error=0
    for mult, exp in expected_nfa.items():
        rows = [r for r in raw if r["method"] == "nfa_adapted" and r["budget_multiplier"] == mult]
        assert len(rows) == 3
        for r in rows:
            if r["result_status"] != "TIMEOUT":
                assert r["actual_consumed_search_evaluations"] == exp
            else:
                assert r["actual_consumed_search_evaluations"] < exp  # timeout 截断，如实


# ---------------------------------------------------------------------------
# 13. py_compile（等价静态检查）
# ---------------------------------------------------------------------------
def test_py_compile_runner():
    p = os.path.join(_PROJECT, "scripts", "reproduce", "e1_3_budget", "run_e1_3_budget_pilot.py")
    res = subprocess.run([sys.executable, "-m", "py_compile", p], capture_output=True)
    assert res.returncode == 0


def _load_json(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return json.load(fh)
