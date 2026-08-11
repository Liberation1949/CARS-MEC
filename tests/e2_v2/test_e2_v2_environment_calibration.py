# -*- coding: utf-8 -*-
"""E2-V2-0 冻结测试（Computational Heterogeneity Environment Calibration and Freeze）。

覆盖（E2-V2-0 协议 §十六 Test）：
  1. 同 seed 同 CV_F 字节/数值复现
  2. 不同 CV_F 时任务集合完全一致
  3. ΣF_j 恒定（=101000）
  4. target/realized CV_F 匹配（<=1e-4）
  5. CV_F=0 时所有 F_j 相等
  6. HHI 随 CV_F 增长
  7. capacity rank 在同 seed 下保持
  8. formal seeds 2101-2110 被 calibration runner 拒绝
  9. 非白名单 N/s_F/CV_F 被拒绝
  10. 不得读取未来信息（T0 语义；无 deadline 逻辑；无 λ_eff）
  11. Schema V4 validation
  12. py_compile
  13. 人工微型案例（M=4, F_total=400）
"""
from __future__ import annotations

import json
import os
import py_compile
import sys

import pytest

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
_SCRIPTS_E2 = os.path.join(_PROJECT, "scripts", "reproduce", "e2_v2")
if _SCRIPTS_E2 not in sys.path:
    sys.path.insert(0, _SCRIPTS_E2)

from build_e2_v2_environment import (  # noqa: E402
    ALLOWED_CV_F_EXTENSION,
    ALLOWED_CV_F_PRIMARY,
    RANK_TEMPLATE_DEFAULT,
    build_e2_v2_environment,
    capacity_rank_for_seed,
    solve_theta,
)
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

F_TOTAL_E1 = 101000.0
PRIMARY_CV = [0.0, 0.3, 0.6, 0.9, 1.2]
CAL_SEED = 1201


def _build(seed=CAL_SEED, cv=0.6, n=170, s_f=1.0, profile="MEDIUM"):
    return build_e2_v2_environment(seed=seed, cv_f_target=cv, n_max=n,
                                   s_f=s_f, fragility_profile=profile)


def _scen(build_out):
    return materialize(build_out["scenario_cfg"])


# 1. 同 seed 同 CV_F 字节/数值复现
def test_same_seed_same_cv_reproducible():
    a = _build(seed=1201, cv=0.6, n=170)
    b = _build(seed=1201, cv=0.6, n=170)
    assert json.dumps(a["scenario_cfg"], sort_keys=True) == \
        json.dumps(b["scenario_cfg"], sort_keys=True)
    assert a["metadata"]["cv_f_realized"] == b["metadata"]["cv_f_realized"]
    assert a["metadata"]["theta"] == b["metadata"]["theta"]


# 2. 不同 CV_F 时任务/设备/信道/λ_j/R_min 完全一致（仅 F_j 改变）
def test_different_cv_same_environment_except_capacity():
    base = _build(seed=1201, cv=0.0, n=170)
    for cv in [0.3, 0.6, 0.9, 1.2]:
        out = _build(seed=1201, cv=cv, n=170)
        cfg = out["scenario_cfg"]
        assert [t["task_id"] for t in cfg["tasks"]] == \
            [t["task_id"] for t in base["scenario_cfg"]["tasks"]]
        assert [t["min_reliability"] for t in cfg["tasks"]] == \
            [t["min_reliability"] for t in base["scenario_cfg"]["tasks"]]
        assert [t["cpu_cycles"] for t in cfg["tasks"]] == \
            [t["cpu_cycles"] for t in base["scenario_cfg"]["tasks"]]
        assert [t["fragility"] for t in cfg["tasks"]] == \
            [t["fragility"] for t in base["scenario_cfg"]["tasks"]]
        assert cfg["devices"] == base["scenario_cfg"]["devices"]
        assert cfg["links"] == base["scenario_cfg"]["links"]
        # λ_j 不变
        assert [s["nominal_failure_rate"] for s in cfg["servers"]] == \
            [s["nominal_failure_rate"] for s in base["scenario_cfg"]["servers"]]
        # 容量不同
        assert [s["capacity_cycles_per_sec"] for s in cfg["servers"]] != \
            [s["capacity_cycles_per_sec"] for s in base["scenario_cfg"]["servers"]]


# 3. ΣF_j 恒定
def test_sum_F_constant():
    for seed in [1201, 1202, 1203]:
        for cv in PRIMARY_CV:
            for n in [140, 170, 200]:
                out = _build(seed=seed, cv=cv, n=n)
                F = [s["capacity_cycles_per_sec"] for s in out["scenario_cfg"]["servers"]]
                assert abs(sum(F) - F_TOTAL_E1) <= 1e-10 * F_TOTAL_E1


# 4. target/realized CV_F 匹配
def test_cv_target_realized_match():
    for seed in [1201, 1202, 1203]:
        for cv in PRIMARY_CV:
            md = _build(seed=seed, cv=cv, n=170)["metadata"]
            assert abs(md["cv_f_realized"] - cv) <= 1e-4


# 5. CV_F=0 时所有 F_j 相等
def test_cv0_uniform():
    out = _build(seed=1201, cv=0.0, n=170)
    F = [s["capacity_cycles_per_sec"] for s in out["scenario_cfg"]["servers"]]
    assert all(abs(x - F_TOTAL_E1 / 8) < 1e-9 for x in F)


# 6. HHI 随 CV_F 增长
def test_hhi_monotonic_in_cv():
    hhis = []
    for cv in PRIMARY_CV:
        md = _build(seed=1201, cv=cv, n=170)["metadata"]
        hhis.append(md["hhi"])
    assert all(hhis[i + 1] > hhis[i] for i in range(len(hhis) - 1))


# 7. capacity rank 在同 seed 下保持
def test_rank_preserved_within_seed():
    r1 = capacity_rank_for_seed(1201)
    r2 = capacity_rank_for_seed(1201)
    r3 = capacity_rank_for_seed(1202)
    assert r1 == r2
    assert r1 != r3
    # build 输出的 rank 与独立函数一致
    md = _build(seed=1201, cv=0.6, n=170)["metadata"]
    assert md["rank"] == r1


# 8. formal seeds 2101-2110 被 calibration runner 拒绝
def test_formal_seeds_rejected():
    import run_e2_v2_0_calibration as runner_mod
    for seed in runner_mod.FORMAL_SEEDS:
        with pytest.raises(SystemExit):
            runner_mod.guard_formal_seed(seed)


# 9. 非白名单 N/s_F/CV_F 被拒绝
def test_non_whitelist_rejected():
    with pytest.raises(ValueError):
        _build(cv=0.4)                      # CV_F 非白名单
    with pytest.raises(ValueError):
        _build(cv=0.0, n=150)               # N 非白名单
    with pytest.raises(ValueError):
        _build(cv=0.6, s_f=0.5)             # s_F 非白名单


# 10. 不得读取未来信息（T0 语义；无 deadline 逻辑；无 λ_eff）
def test_no_future_info_t0_semantics():
    out = _build(seed=1201, cv=0.6, n=170)
    scen = _scen(out)
    assert scen["state_timepoint"] == "T0"
    # deadline 为占位（无 deadline 模型）
    assert all(t["deadline_seconds"] == 1000.0 for t in scen["tasks"])
    derived = DerivedState(scen)
    # DerivedState 只含决策前量，无 schedule 依赖字段
    for tl in derived.task_local:
        assert set(tl.keys()) <= {
            "task_id", "device_id", "T_loc", "E_loc", "R_loc", "omega_res",
            "b_loc", "ell_0_R", "ell_0_succ", "f_tilde_0_req"}
    # 服务器只含 F_j / λ_j（无 λ_eff）
    for s in derived.server_state:
        assert set(s.keys()) == {"server_id", "F_j", "lambda_j"}


# 11. Schema V4 validation
def test_schema_v4_validation(schema_docs_v4, schema_registry_v4, schema_errors_v4):
    # 注：公共 materializer 硬编码 schema_version=V1（既有 W37 特性，src 保护对象）；
    # 此处对 V4 标签化 payload 做内容级校验——E2 场景内容（含浮点容量）须符合 V4。
    for cv in [0.0, 0.6, 1.2]:
        cfg = _build(seed=1201, cv=cv, n=170)["scenario_cfg"]
        payload = {
            "schema_version": "CARS_ACTIVE_SCHEMA_V4",
            "scenario_id": cfg["scenario_id"],
            "state_timepoint": "T0",
            "system_params": cfg["system_params"],
            "tasks": cfg["tasks"],
            "devices": cfg["devices"],
            "servers": cfg["servers"],
            "links": cfg["links"],
        }
        errors = schema_errors_v4(payload, "scenario.schema.json",
                                  schema_registry_v4, schema_docs_v4)
        assert errors == [], "Schema V4 errors for cv=%s: %r" % (cv, errors)


# 12. py_compile
def test_py_compile():
    for name in ["build_e2_v2_environment.py", "run_e2_v2_0_calibration.py",
                 "aggregate_e2_v2_0_calibration.py"]:
        py_compile.compile(os.path.join(_SCRIPTS_E2, name), doraise=True)


# 13. 人工微型案例（M=4, F_total=400）
def test_manual_mini_case_m4():
    z = [-1.5, -0.5, 0.5, 1.5]
    f_total = 400.0
    # CV=0 -> [100,100,100,100]
    theta0, F0, cv0, reached0 = solve_theta(0.0, z, f_total)
    assert theta0 == 0.0 and cv0 == 0.0 and reached0
    assert all(abs(x - 100.0) < 1e-9 for x in F0)
    assert abs(sum(F0) - 400.0) <= 1e-10 * 400.0
    # 非零 CV -> Σ=400, CV>0, HHI>HHI_0
    theta, F, cv, reached = solve_theta(0.6, z, f_total)
    assert reached
    assert abs(sum(F) - 400.0) <= 1e-10 * 400.0
    assert cv > 0.0 and abs(cv - 0.6) <= 1e-4
    hhi0 = sum((x / 400.0) ** 2 for x in F0)
    hhi = sum((x / 400.0) ** 2 for x in F)
    assert hhi > hhi0
    # 两任务检查：task 内容 / λ_j / floor 规则不因 CV 改变；唯一改变对象是 F_j
    a = _build(seed=1201, cv=0.0, n=140)
    b = _build(seed=1201, cv=0.9, n=140)
    ta, tb = a["scenario_cfg"]["tasks"][:2], b["scenario_cfg"]["tasks"][:2]
    assert ta == tb
    assert [s["nominal_failure_rate"] for s in a["scenario_cfg"]["servers"]] == \
        [s["nominal_failure_rate"] for s in b["scenario_cfg"]["servers"]]
    da = DerivedState(_scen(a))
    db = DerivedState(_scen(b))
    assert da.task_local[0]["ell_0_R"] == db.task_local[0]["ell_0_R"]   # floor 规则不变
    assert [s["F_j"] for s in da.server_state] != [s["F_j"] for s in db.server_state]
    # 扩展探针可达性（协议 §13 预注册）
    md15 = _build(seed=1201, cv=1.5, n=170)["metadata"]
    assert md15["cv_reached"] is True
    assert abs(md15["cv_f_realized"] - 1.5) <= 1e-4
