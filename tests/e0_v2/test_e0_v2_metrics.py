# -*- coding: utf-8 -*-
"""E0-V2 机制指标测试（Oracle 独立推导；AC-5）。

compute_e0_mechanism_metrics 的预期值在测试内按正文公式独立手动重算
（不调用被测函数），构成 oracle：
- edge_ratio = |Gamma_edge| / N
- V_F = |{i in Gamma_edge : f_ij < ell_R_ij}| / |Gamma_edge|
- chi_ij = f_ij / ell_R_ij；median(f/ell^R) 取卸载任务 chi 中位数
- max_G_over_F = max_j (sum_{i in Gamma_j} ell_R_ij) / F_j
- LI_dem = (1/M) sum_j (rho_j^dem - rho^dem_bar)^2，rho_j^dem = sum_i a_ij * f_i^loc / F_j

微型案例：n=4, m=2（E0 生成器 seed 201，prefix 到 4）。
"""

from __future__ import annotations

import os
import sys
import statistics

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
_PROJECT = os.path.dirname(_TESTS)
_E0_DIR = os.path.join(_PROJECT, "scripts", "experiments", "e0_v2")
for _p in (_TESTS, _E0_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import pytest  # noqa: E402

from build_e0_v2_environment import build_e0_v2_environment  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

from run_e0_v2_pilot import compute_e0_mechanism_metrics  # noqa: E402

EPS = 1.0e-9
N = 4
M = 2


@pytest.fixture(scope="module")
def env():
    cfg = build_e0_v2_environment(seed=201, n=N, n_max=20)
    scen = materialize(cfg)
    derived = DerivedState(scen)
    return scen, derived


def _manual_metrics(scen, derived, x, a, f):
    """按正文公式独立重算（oracle；不调用被测函数）。"""
    n = len(x)
    m = len(a[0])
    device_by_id = {d["device_id"]: d for d in scen["devices"]}
    task_device = {t["task_id"]: t["device_id"] for t in scen["tasks"]}
    f_loc = []
    for t in scen["tasks"]:
        d = device_by_id[task_device[t["task_id"]]]
        f_loc.append(float(d["local_cpu_rate"]))
    F_j = [float(s["capacity_cycles_per_sec"]) for s in scen["servers"]]

    edge_tasks = [i for i in range(n) if x[i] == 1]
    edge_ratio = len(edge_tasks) / n
    underfloor = 0
    chis = []
    G = [0.0] * m
    for i in edge_tasks:
        j = max(range(m), key=lambda jj: a[i][jj])
        ls = derived.link(i, j)
        ellR = ls["ell_R"] if ls is not None else 0.0
        fij = float(f[i][j])
        if ellR > 0.0:
            chis.append(fij / ellR)
            if fij < ellR - EPS:
                underfloor += 1
        G[j] += ellR
    V_F = underfloor / len(edge_tasks) if edge_tasks else 0.0
    max_gf = max(G[j] / F_j[j] for j in range(m)) if m else 0.0
    rho_dem = [sum(f_loc[i] for i in range(n) if a[i][j] == 1) / F_j[j] for j in range(m)]
    rho_bar = sum(rho_dem) / m
    li_dem = sum((r - rho_bar) ** 2 for r in rho_dem) / m
    return {
        "edge_task_count": len(edge_tasks),
        "edge_ratio": round(edge_ratio, 6),
        "V_F": round(V_F, 6),
        "V_F_underfloor_count": underfloor,
        "median_f_over_ellR": round(statistics.median(chis), 6) if chis else None,
        "chi_count": len(chis),
        "max_G_over_F": round(max_gf, 6),
        "LI_dem": round(li_dem, 6),
    }


def test_metrics_match_oracle_underfloor_case(env):
    """AC-5a：含 underfloor 案例——V_F/chi/median/maxG-F/LI_dem/edge_ratio 与 oracle 一致。"""
    scen, derived = env
    x = [1, 1, 0, 0]
    a = [[1, 0], [0, 1], [0, 0], [0, 0]]
    f = [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    # 任务 0 -> s1：给恰好 floor（chi=1，不 underfloor）
    f[0][0] = derived.link(0, 0)["ell_R"]
    # 任务 1 -> s2：给 0.5*floor（chi=0.5，underfloor）
    f[1][1] = 0.5 * derived.link(1, 1)["ell_R"]

    expected = _manual_metrics(scen, derived, x, a, f)
    got = compute_e0_mechanism_metrics(scen, derived, {"offloading_decision": x,
                                                       "assignment_matrix": a,
                                                       "resource_allocation": f})
    assert got == expected
    # 语义断言（独立于 oracle 的实质检查）
    assert got["edge_ratio"] == 0.5            # 2/4 卸载
    assert got["V_F"] == 0.5                   # 1/2 underfloor
    assert got["V_F_underfloor_count"] == 1
    assert got["chi_count"] == 2
    assert got["median_f_over_ellR"] == 0.75   # median(1.0, 0.5)
    assert got["max_G_over_F"] > 0.0
    assert got["LI_dem"] >= 0.0


def test_metrics_oracle_all_floors_met(env):
    """AC-5b：全部满足 floor 案例——V_F=0。"""
    scen, derived = env
    x = [1, 1, 0, 0]
    a = [[1, 0], [0, 1], [0, 0], [0, 0]]
    f = [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    f[0][0] = derived.link(0, 0)["ell_R"]
    f[1][1] = derived.link(1, 1)["ell_R"]

    expected = _manual_metrics(scen, derived, x, a, f)
    got = compute_e0_mechanism_metrics(scen, derived, {"offloading_decision": x,
                                                       "assignment_matrix": a,
                                                       "resource_allocation": f})
    assert got == expected
    assert got["V_F"] == 0.0
    assert got["V_F_underfloor_count"] == 0
    assert got["chi_count"] == 2


def test_metrics_all_local(env):
    """AC-5c：全本地案例——edge_ratio=0、V_F=0、max G/F=0、LI_dem=0。"""
    scen, derived = env
    x = [0, 0, 0, 0]
    a = [[0, 0]] * N
    f = [[0.0, 0.0]] * N
    got = compute_e0_mechanism_metrics(scen, derived, {"offloading_decision": x,
                                                       "assignment_matrix": a,
                                                       "resource_allocation": f})
    assert got["edge_ratio"] == 0.0
    assert got["V_F"] == 0.0
    assert got["max_G_over_F"] == 0.0
    assert got["LI_dem"] == 0.0
    assert got["median_f_over_ellR"] is None


def test_metrics_deterministic(env):
    """AC-5d：同一输入两次计算结果一致。"""
    scen, derived = env
    x = [1, 1, 0, 0]
    a = [[1, 0], [0, 1], [0, 0], [0, 0]]
    f = [[0.0, 0.0], [0.0, 0.0], [0.0, 0.0], [0.0, 0.0]]
    f[0][0] = derived.link(0, 0)["ell_R"]
    f[1][1] = 0.5 * derived.link(1, 1)["ell_R"]
    d1 = {"offloading_decision": x, "assignment_matrix": a, "resource_allocation": f}
    d2 = {"offloading_decision": list(x), "assignment_matrix": [list(r) for r in a],
          "resource_allocation": [list(r) for r in f]}
    assert compute_e0_mechanism_metrics(scen, derived, d1) == \
        compute_e0_mechanism_metrics(scen, derived, d2)
