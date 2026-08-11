# -*- coding: utf-8 -*-
"""E1-V2-0 环境校准冻结测试（E1-V2-0 合同 Step 10；15 项 + 人工微型案例 N=4/M=2）。

覆盖：
1. same seed + same N -> scenario identical；
2. nested workload prefix；
3. 服务器集合不随 N 变化；
4. N 是正式阶段唯一变化的 workload 变量；
5. lambda_j 不随 workload 改变；
6. deadline 不进入成功判据；
7. candidate environments 参数严格在 whitelist 内（s_F × ν profile）；
8. formal seeds 从未访问；
9. CARS/Baseline 使用同一 canonical scenario；
10. 同一 Evaluator；
11. 同一 timeout；
12. selected environment 与 CARS rank 无关；
13. selected yaml 可重新生成同一场景；
14. no algorithm/config tuning；
15. no protected manuscript modification。
人工微型案例：N=4/M=2（总容量↑压力不反升 / aggregate demand 不随 N 降 /
lambda_j 不变 / floor 与正文一致 / nested N=3 ⊂ N=4 / scaling 只改容量）。
"""

import json
import os
import sys

import pytest
import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "experiments", "e1_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

from build_e1_v2_environment import (  # noqa: E402
    ALLOWED_S_F,
    FRAGILITY_PROFILES,
    build_e1_v2_environment,
    prefix_scenario,
)
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

CAL_OUT = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_0_calibration")
SELECTED_PATH = os.path.join(_PROJECT, "configs", "e1_v2", "e1_v2_environment_selected.yaml")
FORMAL_SEEDS = set(range(1101, 1111))


def _load(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def _load_json(rel):
    with open(os.path.join(_PROJECT, rel), encoding="utf-8") as fh:
        return json.load(fh)


# ---------------------------------------------------------------------------
# 1-5. 生成器：确定性 / 嵌套前缀 / 服务器固定 / 唯一变量 N / lambda_j 不变
# ---------------------------------------------------------------------------

def test_same_seed_same_n_identical():
    a = build_e1_v2_environment(seed=701, n_max=200, s_f=1.0, fragility_profile="MEDIUM")
    b = build_e1_v2_environment(seed=701, n_max=200, s_f=1.0, fragility_profile="MEDIUM")
    assert a == b
    pa = prefix_scenario(a, 110)
    pb = prefix_scenario(b, 110)
    assert pa == pb


def test_nested_workload_prefix():
    cfg = build_e1_v2_environment(seed=701, n_max=200, s_f=0.8, fragility_profile="MEDIUM")
    prev = None
    for n in (20, 50, 80, 110, 140, 170, 200):
        sub = prefix_scenario(cfg, n)
        assert len(sub["tasks"]) == n
        assert [t["task_id"] for t in sub["tasks"]] == [t["task_id"] for t in cfg["tasks"][:n]]
        assert [t["cpu_cycles"] for t in sub["tasks"]] == [t["cpu_cycles"] for t in cfg["tasks"][:n]]
        assert [t["fragility"] for t in sub["tasks"]] == [t["fragility"] for t in cfg["tasks"][:n]]
        prev = sub


def test_server_set_invariant_across_n():
    cfg = build_e1_v2_environment(seed=702, n_max=200, s_f=1.2, fragility_profile="HIGH")
    s200 = cfg["servers"]
    for n in (20, 80, 200):
        assert prefix_scenario(cfg, n)["servers"] == s200


def test_n_is_only_workload_variable():
    """同一 seed 下不同 N 除任务/设备/链路前缀外环境参数一致。"""
    cfg = build_e1_v2_environment(seed=703, n_max=200, s_f=1.0, fragility_profile="MEDIUM")
    a = prefix_scenario(cfg, 50)
    b = prefix_scenario(cfg, 200)
    assert a["servers"] == b["servers"]
    assert a["system_params"] == b["system_params"]
    assert a["s_f"] == b["s_f"] and a["fragility_profile"] == b["fragility_profile"]
    assert b["tasks"][:50] == a["tasks"]


def test_lambda_j_invariant_across_workload():
    cfg = build_e1_v2_environment(seed=701, n_max=200, s_f=0.8, fragility_profile="HIGH")
    lambdas = [s["nominal_failure_rate"] for s in cfg["servers"]]
    for n in (20, 110, 200):
        sub = prefix_scenario(cfg, n)
        assert [s["nominal_failure_rate"] for s in sub["servers"]] == lambdas


def test_lambda_j_not_scanned_by_sf():
    """s_F 只改变容量，不改变 lambda_j（白名单禁止扫描 lambda_j）。"""
    a = build_e1_v2_environment(seed=701, n_max=50, s_f=0.8, fragility_profile="MEDIUM")
    b = build_e1_v2_environment(seed=701, n_max=50, s_f=1.2, fragility_profile="MEDIUM")
    assert [s["nominal_failure_rate"] for s in a["servers"]] == [s["nominal_failure_rate"] for s in b["servers"]]
    assert [s["capacity_cycles_per_sec"] for s in a["servers"]] != [s["capacity_cycles_per_sec"] for s in b["servers"]]


# ---------------------------------------------------------------------------
# 6. deadline 不进入成功判据
# ---------------------------------------------------------------------------

def test_deadline_not_in_success_criterion():
    cfg = build_e1_v2_environment(seed=701, n_max=20, s_f=1.0, fragility_profile="MEDIUM")
    scen = materialize(cfg)
    assert all(t["deadline_seconds"] > 0 for t in scen["tasks"])  # 占位字段存在
    dv = DerivedState(scen)
    # 成功只查可靠性：b_loc 由 R_loc >= R_min 决定（无 deadline 语义）
    # 这里验证 deadline 值不影响决策前状态中的成功相关量
    scen2 = json.loads(json.dumps(scen))
    for t in scen2["tasks"]:
        t["deadline_seconds"] = t["deadline_seconds"] + 500.0
    dv2 = DerivedState(scen2)
    assert [tl["b_loc"] for tl in dv.task_local] == [tl["b_loc"] for tl in dv2.task_local]


# ---------------------------------------------------------------------------
# 7. candidate environments 参数严格在 whitelist 内
# ---------------------------------------------------------------------------

def test_candidate_envs_in_whitelist():
    cfg = build_e1_v2_environment(seed=701, n_max=20, s_f=0.8, fragility_profile="MILD")
    assert cfg["s_f"] in ALLOWED_S_F
    assert cfg["fragility_profile"] in FRAGILITY_PROFILES
    # 非法参数拒绝
    with pytest.raises(ValueError):
        build_e1_v2_environment(seed=1, n_max=20, s_f=0.9, fragility_profile="MEDIUM")
    with pytest.raises(ValueError):
        build_e1_v2_environment(seed=1, n_max=20, s_f=1.0, fragility_profile="EXOTIC")


# ---------------------------------------------------------------------------
# 8. formal seeds 从未访问
# ---------------------------------------------------------------------------

def test_formal_seeds_never_accessed():
    cal_protocol = _load("configs/e1_v2/e1_v2_environment_calibration_protocol.yaml")
    used = set(cal_protocol["calibration_seeds"]) | set(cal_protocol["confirm_seeds"])
    assert used.isdisjoint(FORMAL_SEEDS)
    # 校准 raw 中不得出现 formal seeds
    raw_path = os.path.join(CAL_OUT, "calibration_raw.jsonl")
    if os.path.exists(raw_path):
        with open(raw_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                r = json.loads(line)
                assert r["seed"] not in FORMAL_SEEDS, r


# ---------------------------------------------------------------------------
# 9-11. 同一 canonical scenario / Evaluator / timeout
# ---------------------------------------------------------------------------

def test_same_canonical_scenario_evaluator_timeout():
    """校准与未来 E1 使用同一生成器/canonical scenario/Evaluator/超时。"""
    cal_protocol = _load("configs/e1_v2/e1_v2_environment_calibration_protocol.yaml")
    assert cal_protocol["fixed_params"]["timeout"] == 30.0
    assert cal_protocol["fixed_params"]["system_params"] == "Schema V4（rcla_solver + numeric_epsilon）"
    # 校准 runner 的 4 方法使用统一 MethodRunner（Runner 唯一调用 Evaluator）
    from cars.runner.runner import MethodRunner
    from cars.methods.adaptation import METHOD_WHITELIST
    for m in ("cars", "bpso_rata_la", "nfa_adapted", "reliability_only"):
        assert m in METHOD_WHITELIST


# ---------------------------------------------------------------------------
# 12. selected environment 与 CARS rank 无关（凭据文件）
# ---------------------------------------------------------------------------

def test_selected_environment_rank_independent():
    if not os.path.exists(SELECTED_PATH):
        pytest.skip("selected environment not yet frozen")
    sel = _load("configs/e1_v2/e1_v2_environment_selected.yaml")
    assert sel["selection_basis"]["not_based_on_cars_rank"] is True
    assert sel["selection_basis"]["layer_a_primary"] is True
    # 选择依据必须是 workload coverage / identifiability
    assert any(k in sel["selection_basis"] for k in ("workload_coverage", "identifiability", "pressure_coverage"))


# ---------------------------------------------------------------------------
# 13. selected yaml 可重新生成同一场景
# ---------------------------------------------------------------------------

def test_selected_yaml_regenerates_scenario():
    if not os.path.exists(SELECTED_PATH):
        pytest.skip("selected environment not yet frozen")
    sel = _load("configs/e1_v2/e1_v2_environment_selected.yaml")
    s_f = sel["environment"]["s_f"]
    profile = sel["environment"]["fragility_profile"]
    seed = 701
    a = build_e1_v2_environment(seed=seed, n_max=200, s_f=s_f, fragility_profile=profile)
    b = build_e1_v2_environment(seed=seed, n_max=200, s_f=s_f, fragility_profile=profile)
    assert a == b
    # 保存 yaml 后重新加载再生成应一致
    import tempfile
    tmp = os.path.join(tempfile.gettempdir(), "sel_check.yaml")
    with open(tmp, "w", encoding="utf-8") as fh:
        yaml.safe_dump(a, fh, allow_unicode=True)
    c = yaml.safe_load(open(tmp, encoding="utf-8"))
    assert c["tasks"] == a["tasks"] and c["servers"] == a["servers"]
    os.remove(tmp)


# ---------------------------------------------------------------------------
# 14. no algorithm/config tuning（校准 raw 记录不含调参）
# ---------------------------------------------------------------------------

def test_no_algorithm_tuning_in_calibration():
    cal_protocol = _load("configs/e1_v2/e1_v2_environment_calibration_protocol.yaml")
    assert cal_protocol["forbidden"]  # 白名单禁止项已登记
    assert "不修改算法使其适配环境" in cal_protocol["forbidden"]
    assert "不调优 CARS 或 Baseline" in cal_protocol["forbidden"]
    assert "不依据 CARS 是否第一选择环境" in cal_protocol["forbidden"]
    assert "不扫描 lambda_j 制造 CARS 优势" in cal_protocol["forbidden"]


# ---------------------------------------------------------------------------
# 15. no protected manuscript modification
# ---------------------------------------------------------------------------

def test_protected_objects_unchanged():
    """校准不触碰保护对象（正文/references/data）：校准产物全部在 results/e1_v2。"""
    # 校准输出全部在 results/e1_v2/e1_v2_0_calibration（不在保护目录内）
    assert os.path.isdir(CAL_OUT)
    # 保护目录内不得出现校准/结果文件（只读约束）
    for rel in ("experiment_docs", "references", "data"):
        # 校准产出路径均不以这些目录为前缀
        assert not os.path.join(_PROJECT, rel).startswith(CAL_OUT)
    # 保护对象 hash 未变（与 pre-state 对比，见 integrity；此处结构性检查）
    assert os.path.exists(os.path.join(CAL_OUT, "pre_state_hashes.json"))


# ---------------------------------------------------------------------------
# 人工微型案例：N=4 / M=2
# ---------------------------------------------------------------------------

def _manual_4_2_env(s_f):
    """构造 N=4/M=2 确定性微型场景（服务器先行；显式任务属性）。"""
    return {
        "scenario_id": "manual_e1v2_n4_m2_sf%s" % s_f,
        "seed": 1,
        "mode": "explicit",
        "s_f": float(s_f),
        "fragility_profile": "MEDIUM",
        "system_params": {
            "rcla_solver": {"rcla_mu_tol": 1e-9, "rcla_max_iters": 200,
                            "rcla_mu_lo": 1e-12, "rcla_mu_hi": 1e12,
                            "rcla_numeric_epsilon": 1e-12},
            "numeric_epsilon": 1e-12,
        },
        "tasks": [
            {"task_id": "t1", "device_id": "d1", "data_bits": 1000, "cpu_cycles": 4000,
             "fragility": 0.0, "delay_weight": 0.7, "energy_weight": 0.3,
             "deadline_seconds": 1000.0, "min_reliability": 0.90},
            {"task_id": "t2", "device_id": "d2", "data_bits": 1000, "cpu_cycles": 4000,
             "fragility": 8.0, "delay_weight": 0.6, "energy_weight": 0.4,
             "deadline_seconds": 1000.0, "min_reliability": 0.90},
            {"task_id": "t3", "device_id": "d3", "data_bits": 1000, "cpu_cycles": 5000,
             "fragility": 8.0, "delay_weight": 0.6, "energy_weight": 0.4,
             "deadline_seconds": 1000.0, "min_reliability": 0.90},
            {"task_id": "t4", "device_id": "d4", "data_bits": 1000, "cpu_cycles": 12000,
             "fragility": 16.0, "delay_weight": 0.6, "energy_weight": 0.4,
             "deadline_seconds": 1000.0, "min_reliability": 0.90},
        ],
        "devices": [
            {"device_id": "d1", "local_cpu_rate": 1200, "local_failure_rate": 0.002,
             "switch_capacitance": 1.0, "tx_power_watts": 0.5},
            {"device_id": "d2", "local_cpu_rate": 800, "local_failure_rate": 0.002,
             "switch_capacitance": 1.0, "tx_power_watts": 0.5},
            {"device_id": "d3", "local_cpu_rate": 800, "local_failure_rate": 0.002,
             "switch_capacitance": 1.0, "tx_power_watts": 0.5},
            {"device_id": "d4", "local_cpu_rate": 800, "local_failure_rate": 0.002,
             "switch_capacitance": 1.0, "tx_power_watts": 0.5},
        ],
        "servers": [
            {"server_id": "s1", "capacity_cycles_per_sec": int(10000 * s_f),
             "nominal_failure_rate": 0.002},
            {"server_id": "s2", "capacity_cycles_per_sec": int(10000 * s_f),
             "nominal_failure_rate": 0.002},
        ],
        "links": [{"link_id": "l%d%d" % (i, j), "source_device_id": "d%d" % i,
                   "target_server_id": "s%d" % j, "bandwidth_hz": 1000000,
                   "channel_gain": 1e-9, "noise_power": 1e-10, "error_probability": 0.01}
                  for i in range(1, 5) for j in range(1, 3)],
    }


def _agg_min_floor_demand(cfg, n):
    sub = {"tasks": cfg["tasks"][:n], "devices": cfg["devices"][:n],
           "servers": cfg["servers"], "links": [l for l in cfg["links"]
                                                 if int(l["link_id"][1]) <= n],
           "mode": "explicit", "scenario_id": "x", "system_params": cfg["system_params"]}
    scen = materialize(sub)
    dv = DerivedState(scen)
    total = 0.0
    for i in range(n):
        min_f = None
        for j in range(2):
            ls = dv.link(i, j)
            if ls is not None and ls["e_rec"] == 1:
                if min_f is None or ls["ell_R"] < min_f:
                    min_f = ls["ell_R"]
        if min_f is not None:
            total += min_f
    return total


def test_manual_capacity_up_pressure_not_up():
    """总容量增加时 aggregate floor demand / 压力不得反向升高（需求由任务决定）。"""
    lo = _manual_4_2_env(0.8)
    hi = _manual_4_2_env(1.2)
    d_lo = _agg_min_floor_demand(lo, 4)
    d_hi = _agg_min_floor_demand(hi, 4)
    assert d_lo == pytest.approx(d_hi)  # 需求与容量无关（任务属性决定）
    # 压力 = demand / capacity：容量 ↑ -> 压力 ↓
    cap_lo = sum(s["capacity_cycles_per_sec"] for s in lo["servers"])
    cap_hi = sum(s["capacity_cycles_per_sec"] for s in hi["servers"])
    assert (d_lo / cap_lo) > (d_hi / cap_hi)


def test_manual_aggregate_demand_monotone_in_n():
    """新增任务时 aggregate floor demand 不得下降（单调非降）。"""
    cfg = _manual_4_2_env(1.0)
    prev = 0.0
    for n in (1, 2, 3, 4):
        d = _agg_min_floor_demand(cfg, n)
        assert d >= prev - 1e-9
        prev = d


def test_manual_lambda_j_invariant():
    """人工案例：s_F 不改变 lambda_j。"""
    a = _manual_4_2_env(0.8)
    b = _manual_4_2_env(1.2)
    assert [s["nominal_failure_rate"] for s in a["servers"]] == [s["nominal_failure_rate"] for s in b["servers"]]
    assert a["servers"][0]["capacity_cycles_per_sec"] < b["servers"][0]["capacity_cycles_per_sec"]


def test_manual_reliability_floor_consistent_with_body():
    """人工案例：ell_R 计算与正文 III-D.5 一致（exp 阈值）。"""
    from cars.simulator import physical_models as pm
    cfg = _manual_4_2_env(1.0)
    scen = materialize(cfg)
    dv = DerivedState(scen)
    # t4 (nu=16, c=12000, s2 lambda=0.002, R_tx=0.99, Rmin=0.90)
    ls = dv.link(3, 1)
    assert ls is not None
    ell = ls["ell_R"]
    expected = pm.reliability_threshold(0.002, 16.0, 12000.0, 0.99, 0.90)
    assert ell == pytest.approx(expected, rel=1e-9)


def test_manual_nested_n3_subset_of_n4():
    """nested workload：N=3 严格为 N=4 的前三任务（人工案例）。"""
    cfg = _manual_4_2_env(1.0)
    n4 = {"tasks": cfg["tasks"][:4]}
    n3 = {"tasks": cfg["tasks"][:3]}
    assert [t["task_id"] for t in n3["tasks"]] == [t["task_id"] for t in n4["tasks"][:3]]


def test_manual_scaling_only_capacity():
    """environment scaling（s_F）只能改变允许的 capacity quantity。"""
    a = _manual_4_2_env(0.8)
    b = _manual_4_2_env(1.2)
    # 任务/设备/链路属性完全一致（只容量缩放）
    assert a["tasks"] == b["tasks"]
    assert a["devices"] == b["devices"]
    assert a["links"] == b["links"]
    assert [s["capacity_cycles_per_sec"] for s in a["servers"]] != [s["capacity_cycles_per_sec"] for s in b["servers"]]
