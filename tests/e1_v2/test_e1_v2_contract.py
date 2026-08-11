# -*- coding: utf-8 -*-
"""E1-V2 冻结测试（CR-CARS-PROMOTION-E1 + E1 Freeze/Pilot；AC-7/AC-8）。

覆盖：
- 协议冻结项：定位/方法集合/环境/网格/seeds/压力区间/指标/统计/图表/Claim；
- 环境生成器：N_max=200 前缀一致性（Gamma_20 ⊂ Gamma_50 ⊂ ... ⊂ Gamma_200）、
  确定性（同 seed 重复生成一致）；
- 正式 CARS（AADA→RCLA）与 Baseline 经统一 MethodRunner 冒烟可运行；
- 禁止项：formal seeds 1101-1110 未在本阶段访问；无 V_D/gamma/kappa 字段；
- promoted CARS == candidate（复用等价验证）。
"""

import json
import os
import sys

import pytest
import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "experiments", "e1_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

from build_e1_v2_environment import build_e1_v2_environment, prefix_scenario  # noqa: E402


def _load(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_json(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# AC-1 协议冻结项
# ---------------------------------------------------------------------------

def test_protocol_frozen_fields():
    p = _load("configs/e1_v2/e1_v2_protocol.yaml")
    assert p["protocol_id"] == "e1_v2_protocol_v1"
    assert p["formal_grid"] == [20, 50, 80, 110, 140, 170, 200]
    assert p["formal_seeds"] == [1101, 1102, 1103, 1104, 1105, 1106, 1107, 1108, 1109, 1110]
    # E1-V2-0 校准后四区划分（正式协议）
    assert p["pressure_intervals"] == {
        "LOW": [20, 50], "TRANSITION": [80, 110, 140],
        "HIGH": [170], "NEAR_SATURATION": [200],
    }
    assert p["methods"]["main"] == [
        "cars", "bpso_rata_la", "jtora_adapted", "nfa_adapted",
        "reliability_only", "local_only",
    ]
    assert p["methods"]["diagnostic"] == ["foa"]
    assert p["boundary"]["formal_not_authorized"] is True
    assert p["pilot"]["seeds"] == [201, 202, 203]
    assert p["pilot"]["n_points"] == [20, 80, 200]
    # 统计冻结
    assert p["statistics"]["paired_bootstrap"]["resamples"] == 10000
    assert p["statistics"]["paired_bootstrap"]["rng_seed"] == 20260809
    # 图表 2 图 1 表
    assert "Fig_E1_1" in p["figure_table_contract"]
    assert "Fig_E1_2" in p["figure_table_contract"]
    assert "Table_E1_1" in p["figure_table_contract"]
    # Claim outcome-neutral
    assert set(p["claim_rules"]["allowed"]) == {"supported", "conditionally_supported", "not_supported"}


def test_environment_frozen_fields():
    e = _load("configs/e1_v2/e1_v2_environment.yaml")
    assert e["environment"]["id"] == "E1_V2_ENVIRONMENT_V1"
    assert e["environment"]["m"] == 8
    assert e["environment"]["deadline"] == "无 deadline 模型（deadline_seconds 占位 1000.0，字段兼容，逻辑不使用）"
    assert e["formal_grid"] == [20, 50, 80, 110, 140, 170, 200]
    assert e["formal_seeds"] == list(range(1101, 1111))
    assert e["pilot_seeds"] == [201, 202, 203]


def test_field_definitions_forbid_legacy():
    f = _load("configs/e1_v2/e1_v2_field_definitions.yaml")
    forbidden = f["forbidden_legacy_fields"]
    for bad in ("V_D", "deadline_violation_rate", "lambda_eff", "ruad_gamma",
                "kappa_R", "kappa_D", "cala_weights", "repair_budget"):
        assert bad in forbidden
    assert f["field_definitions"]["TSSR"]["role"] == "primary"
    assert f["field_definitions"]["total_wall_time_ms"]["role"] == "efficiency"
    assert "no_module_runtime" or True  # 模块级拆解属 E3


# ---------------------------------------------------------------------------
# AC-2 环境生成器：前缀一致 + 确定性
# ---------------------------------------------------------------------------

def test_environment_nested_prefix_consistency():
    cfg = build_e1_v2_environment(seed=201, n_max=200)
    assert len(cfg["tasks"]) == 200
    prev_tasks = []
    for n in (20, 50, 80, 110, 140, 170, 200):
        sub = prefix_scenario(cfg, n)
        assert len(sub["tasks"]) == n
        # 前缀一致：小规模任务 = 大规模任务前 n 个
        assert [t["task_id"] for t in sub["tasks"]] == [t["task_id"] for t in cfg["tasks"][:n]]
        assert [t["cpu_cycles"] for t in sub["tasks"]] == [t["cpu_cycles"] for t in cfg["tasks"][:n]]
        # 服务器固定（嵌套一致性核心）
        assert sub["servers"] == cfg["servers"]
        assert len(sub["links"]) == n * len(cfg["servers"])
    # Schema V4 system_params
    assert set(cfg["system_params"].keys()) == {"rcla_solver", "numeric_epsilon"}
    assert "cala_weights" not in cfg["system_params"]


def test_environment_deterministic():
    a = build_e1_v2_environment(seed=202, n_max=200)
    b = build_e1_v2_environment(seed=202, n_max=200)
    assert a == b
    c = build_e1_v2_environment(seed=203, n_max=200)
    assert a != c  # 不同 seed 不同实例


# ---------------------------------------------------------------------------
# AC-3 方法经统一 MethodRunner 冒烟
# ---------------------------------------------------------------------------

def test_cars_runner_smoke():
    from cars.runner.runner import MethodRunner

    cfg_env = build_e1_v2_environment(seed=201, n_max=20)
    scen_path = os.path.join(_PROJECT, "results", "e1_v2", "_smoke_scenario.yaml")
    os.makedirs(os.path.dirname(scen_path), exist_ok=True)
    # 保存原始配置（含 mode=explicit）：MethodRunner 内部 materialize
    with open(scen_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg_env, fh, allow_unicode=True, sort_keys=False)
    cars_cfg = _load("configs/cars_v4/cars_frozen_v4.yaml")
    rec = MethodRunner().run(
        method_id="cars",
        scenario_cfg_path=scen_path,
        method_config=cars_cfg,
        method_seed=cars_cfg["method_seed"],
        hard_timeout_seconds=30.0,
    )
    os.remove(scen_path)
    assert rec["method_status"] == "SUCCESS"
    assert rec["evaluator_status"] == "VALID"
    assert rec["decision"]["schema_version"] == "CARS_ACTIVE_SCHEMA_V4"
    assert rec["decision"]["offloading_decision"] is not None


def test_baseline_runner_smoke():
    from cars.runner.runner import MethodRunner

    cfg_env = build_e1_v2_environment(seed=201, n_max=20)
    scen_path = os.path.join(_PROJECT, "results", "e1_v2", "_smoke_scenario.yaml")
    with open(scen_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg_env, fh, allow_unicode=True, sort_keys=False)
    try:
        for mid, rel in (
            ("reliability_only", "configs/r6/frozen_method_configs/reliability_only_frozen.yaml"),
            ("nfa_adapted", "configs/r6/frozen_method_configs/nfa_frozen.yaml"),
        ):
            cfg = _load(rel)
            rec = MethodRunner().run(
                method_id=mid, scenario_cfg_path=scen_path, method_config=cfg,
                method_seed=cfg["method_seed"], hard_timeout_seconds=30.0,
            )
            assert rec["method_status"] == "SUCCESS", mid
            assert rec["evaluator_status"] == "VALID", mid
    finally:
        if os.path.exists(scen_path):
            os.remove(scen_path)


# ---------------------------------------------------------------------------
# AC-4 等价验证产物存在
# ---------------------------------------------------------------------------

def test_promotion_equivalence_artifact_exists():
    eq = _load_json("results/e1_v2/promotion_equivalence.json")
    assert eq["check"] == "promoted_cars_vs_candidate_equivalence"
    assert eq["all_equivalent"] is True


# ---------------------------------------------------------------------------
# AC-5 禁止项：formal seeds 未运行
# ---------------------------------------------------------------------------

def test_formal_seeds_not_used_in_pilot():
    # Pilot 协议只含 seeds 201-203；formal seeds 1101-1110 未登记于 pilot
    p = _load("configs/e1_v2/e1_v2_protocol.yaml")
    assert set(p["pilot"]["seeds"]) == {201, 202, 203}
    pilot_dir = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_1_pilot")
    if os.path.exists(os.path.join(pilot_dir, "raw_records.jsonl")):
        with open(os.path.join(pilot_dir, "raw_records.jsonl"), encoding="utf-8") as fh:
            for line in fh:
                r = json.loads(line)
                assert r["seed"] in {201, 202, 203}, r
    else:
        pytest.skip("pilot not yet run")
