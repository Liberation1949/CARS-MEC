# -*- coding: utf-8 -*-
"""E3-V2 fixed-assignment 对照测试（RCLA vs ordinary LA；同一 X/A hash；E3-0 冻结）。

覆盖（configs/e3_v2/e3_v2_variant_matrix.yaml fixed_assignment_protocol）：
- AC-F1：allocation_mode=rcla 与 ordinary_la 共享完全相同的 offloading_decision
  与 assignment_matrix（X/A hash 一致；禁止因 allocation 方法不同重跑 AADA）；
- AC-F2：allocation_mode=ordinary_la 的 RCLA 诊断字段同构（active_floor=0、
  allocation_infeasible=False）；
- AC-F3：RCLA 在 floor 激活时与 ordinary LA 分配不同（capacity/floor 审计差异）。
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import pytest  # noqa: E402

from cars.methods.cars.diagnostics import _decision_hash  # noqa: E402
from cars.methods.cars.pipeline import run_aada_rcla_pipeline  # noqa: E402
from cr_algorithm_redesign.tiny_scenario_builder import (  # noqa: E402
    build_scenario,
    derived_state,
    make_device,
    make_link,
    make_server,
    make_task,
    materialize_scenario,
)

RCLA_CFG = {
    "rcla_mu_tol": 1.0e-9,
    "rcla_max_iters": 200,
    "rcla_mu_lo": 1.0e-12,
    "rcla_mu_hi": 1.0e12,
    "rcla_numeric_epsilon": 1.0e-12,
}
EPS = 1.0e-9
_BW = 1.0e6
_GAIN = 1.0e-9
_NOISE = 1.0e-10
_PERR = 0.01


# ---------------------------------------------------------------------------
# 场景：两任务 local-failure 挤入单服务器（floor 非对称 -> RCLA active floor）
#   s1 F=5500, λ=0.003；t1(c=5000, ν=16)、t2(c=12000, ν=16)
# 手算（代码盲算）：
#   ell_R = λ·ν·c / ln(R_tx/R_min)，R_tx=0.99, R_min=0.85 -> ln(0.99/0.85)=0.152470
#   t1: ell_R = 0.003*16*5000/0.152470 = 1574.0；t2: ell_R = 0.003*16*12000/0.152470 = 3777.9
#   准入：1574 + 3778 = 5352 <= 5500 ✓（两任务均可入）
#   RCLA：free={t1,t2}，LA_i = 5500/2 = 2750（s 相同）；t2: 2750 < 3778 -> active
#     （f=3778）；remaining=1722；t1: 1722 >= 1574 -> 保持 free。
#   -> active_floor_task_count = 1 > 0，且 RCLA 分配 != 普通 LA 分配。
# ---------------------------------------------------------------------------

def _scenario_floor_active():
    servers = [
        make_server("s1", capacity_cycles_per_sec=5500, nominal_failure_rate=0.003),
    ]
    devices = [
        make_device("d1", local_cpu_rate=800),
        make_device("d2", local_cpu_rate=800),
    ]
    tasks = [
        # 两任务均 local-failure（R_loc < 0.85）
        make_task("t1", "d1", cpu_cycles=5000, fragility=16, delay_weight=0.6, min_reliability=0.85),
        make_task("t2", "d2", cpu_cycles=12000, fragility=16, delay_weight=0.6, min_reliability=0.85),
    ]
    links = [
        make_link("l1", "d1", "s1", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
        make_link("l2", "d2", "s1", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
    ]
    return build_scenario(tasks, devices, servers, links, scenario_id="e3v2_scenario_floor_active")


def _run_pipeline(scenario, allocation_mode):
    scen = materialize_scenario(scenario)
    derived = derived_state(scen)
    return run_aada_rcla_pipeline(
        scen, derived, eps_cmp=EPS, rcla_cfg=dict(RCLA_CFG),
        aada_variant="full", allocation_mode=allocation_mode,
    )


def test_fixed_assignment_same_xa_hash():
    """AC-F1：rcla 与 ordinary_la 共享相同 X/A（X/A hash 一致）。"""
    r = _run_pipeline(_scenario_floor_active(), "rcla")
    la = _run_pipeline(_scenario_floor_active(), "ordinary_la")
    assert r["decision"]["offloading_decision"] == la["decision"]["offloading_decision"]
    assert r["decision"]["assignment_matrix"] == la["decision"]["assignment_matrix"]
    xa_r = _decision_hash(
        r["decision"]["offloading_decision"],
        r["decision"]["assignment_matrix"],
        [[0.0] * len(r["decision"]["resource_allocation"][0])] * len(r["decision"]["resource_allocation"]),
    )
    xa_la = _decision_hash(
        la["decision"]["offloading_decision"],
        la["decision"]["assignment_matrix"],
        [[0.0] * len(la["decision"]["resource_allocation"][0])] * len(la["decision"]["resource_allocation"]),
    )
    assert xa_r == xa_la
    # X/A 均非全零（存在 EDGE 指派）
    assert sum(r["decision"]["offloading_decision"]) > 0


def test_ordinary_la_diagnostics_homogeneous():
    """AC-F2：ordinary_la 诊断字段同构（active_floor=0、infeasible=False）。"""
    la = _run_pipeline(_scenario_floor_active(), "ordinary_la")
    rd = la["diagnostics"]["rcla"]
    assert rd["active_floor_task_count"] == 0
    assert rd["allocation_infeasible"] is False
    assert rd["allocation_mode"] == "ordinary_la"
    assert la["diagnostics"]["allocation_mode"] == "ordinary_la"
    assert la["diagnostics"]["runtime_breakdown"]["rcla_ms"] >= 0.0


def test_rcla_floor_changes_allocation():
    """AC-F3：RCLA floor 激活时与 ordinary LA 分配不同（floor 改变分配的证据）。"""
    r = _run_pipeline(_scenario_floor_active(), "rcla")
    la = _run_pipeline(_scenario_floor_active(), "ordinary_la")
    rd = r["diagnostics"]["rcla"]
    # RCLA 存在 active floor（floor 大量激活）
    assert rd["active_floor_task_count"] > 0
    # 两个 allocation 的 F 矩阵不同（floor 改变分配）
    f_r = r["decision"]["resource_allocation"]
    f_la = la["decision"]["resource_allocation"]
    flat_r = [v for row in f_r for v in row]
    flat_la = [v for row in f_la for v in row]
    assert flat_r != flat_la
    # RCLA 无 ALLOCATION_INFEASIBLE（admission invariant；预期=0）
    assert rd["allocation_infeasible"] is False
    # RCLA 的 capacity residual 在 Evaluator C6 容差内
    assert rd["max_capacity_residual"] <= 1e-6
