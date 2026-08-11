# -*- coding: utf-8 -*-
"""E3-V2 变体注入测试（E3-0 冻结）。

覆盖（configs/e3_v2/e3_v2_variant_matrix.yaml）：
- AC-V1：no_rescue 关闭 Phase-1（本地失败任务不救援，保持 LOCAL/UNSERVED）；
- AC-V2：rescue_only 关闭 Phase-2（本地成功任务全部保持 LOCAL）；
- AC-V3：no_alloc_aware 去掉 Delta_phi 选择键（Phase-1 改用 (ell_R/F_j, j)）；
- AC-V4：默认 full 行为与正文 V-B.6 一致（回归：现有 CR-ALG-REDESIGN 测试基线）。
"""

from __future__ import annotations

import math
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_TESTS = os.path.dirname(_HERE)
if _TESTS not in sys.path:
    sys.path.insert(0, _TESTS)

import pytest  # noqa: E402

from cars.methods.cars.aada import run_aada  # noqa: E402
from cars.methods.cars.state import CandidateStateView  # noqa: E402
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


def _view(scenario):
    scen = materialize_scenario(scenario)
    return CandidateStateView(scen, derived_state(scen))


def _run_aada(view, variant="full"):
    return run_aada(view, eps_cmp=EPS, rcla_cfg=RCLA_CFG, variant=variant)


# ---------------------------------------------------------------------------
# 场景 C（复用 test_aada）：t1 local-failure + t2 local-success（慢链路 U<0）
# ---------------------------------------------------------------------------

def _scenario_c():
    servers = [
        make_server("s1", capacity_cycles_per_sec=50000, nominal_failure_rate=0.0001),
    ]
    devices = [
        make_device("d1", local_cpu_rate=800),
        make_device("d2", local_cpu_rate=2000, local_failure_rate=0.001),
    ]
    tasks = [
        make_task("t1", "d1", cpu_cycles=5000, fragility=8, delay_weight=0.6, min_reliability=0.95),
        make_task("t2", "d2", cpu_cycles=2000, fragility=8, delay_weight=0.6, min_reliability=0.9,
                  data_bits=100000),
    ]
    links = [
        make_link("l1", "d1", "s1", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
        make_link("l2", "d2", "s1", bandwidth_hz=1000.0, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
    ]
    return build_scenario(tasks, devices, servers, links, scenario_id="e3v2_scenario_c")


# ---------------------------------------------------------------------------
# 场景 D（复用 test_aada）：t1 local-success（本地慢、链路快 -> 卸载）
# ---------------------------------------------------------------------------

def _scenario_d():
    servers = [
        make_server("s1", capacity_cycles_per_sec=50000, nominal_failure_rate=0.0001),
    ]
    devices = [make_device("d1", local_cpu_rate=800)]
    tasks = [
        make_task("t1", "d1", cpu_cycles=5000, fragility=8, delay_weight=0.6, min_reliability=0.9),
    ]
    links = [
        make_link("l1", "d1", "s1", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
    ]
    return build_scenario(tasks, devices, servers, links, scenario_id="e3v2_scenario_d")


# ---------------------------------------------------------------------------
# 场景 AW：no_alloc_aware 区分场景（Phase-1 选择键冲突）
#   A: F=30000, λ=0.003 -> dphi 小（full 优先）、norm_floor 大
#   B: F=10000, λ=0.0005 -> dphi 大、norm_floor 小（no_alloc_aware 优先）
# 手算（代码盲算）：
#   ell_R = λ·ν·c / ln(R_tx/R_min)，R_tx=0.99, R_min=0.95 -> ln(0.99/0.95)=0.041256
#   A: ell_R=0.003*8*5000/0.041256=2908.7, norm=0.09696, dphi=480/30000=0.016
#   B: ell_R=0.0005*8*5000/0.041256=484.78, norm=0.048478, dphi=480/10000=0.048
#   full: min(dphi,...) -> A；no_alloc_aware: min(norm_floor,...) -> B
# ---------------------------------------------------------------------------

def _scenario_alloc_aware():
    servers = [
        make_server("sA", capacity_cycles_per_sec=30000, nominal_failure_rate=0.003),
        make_server("sB", capacity_cycles_per_sec=10000, nominal_failure_rate=0.0005),
    ]
    devices = [make_device("d1", local_cpu_rate=800)]
    tasks = [
        make_task("t1", "d1", cpu_cycles=5000, fragility=8, delay_weight=0.6, min_reliability=0.95),
    ]
    links = [
        make_link("l1", "d1", "sA", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
        make_link("l2", "d1", "sB", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
    ]
    return build_scenario(tasks, devices, servers, links, scenario_id="e3v2_scenario_alloc_aware")


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------

def test_no_rescue_disables_phase1():
    """AC-V1：no_rescue 下本地失败任务不救援（保持 LOCAL），Phase-2 行为与 full 一致。"""
    view = _view(_scenario_c())
    assert view.local_success(0) is False  # t1 local-failure
    full = _run_aada(view, "full")
    assert full["offloading_decision"][0] == 1  # t1 被 rescue
    assert full["diagnostics"]["rescued_local_failure_count"] == 1
    nr = _run_aada(view, "no_rescue")
    assert nr["offloading_decision"][0] == 0  # t1 不救援
    assert nr["diagnostics"]["rescued_local_failure_count"] == 0
    assert nr["diagnostics"]["aada_variant"] == "no_rescue"
    # Phase-2（t2）行为与 full 一致（t2 在 full 下也保持 LOCAL）
    assert nr["offloading_decision"][1] == full["offloading_decision"][1]


def test_rescue_only_disables_phase2():
    """AC-V2：rescue_only 下本地成功任务全部保持 LOCAL（Phase-2 关闭）。"""
    view = _view(_scenario_d())
    assert view.local_success(0) is True
    full = _run_aada(view, "full")
    assert full["offloading_decision"][0] == 1  # t1 被卸载
    ro = _run_aada(view, "rescue_only")
    assert ro["offloading_decision"][0] == 0  # t1 保持 LOCAL
    assert ro["diagnostics"]["utility_improving_offload_count"] == 0
    assert ro["diagnostics"]["aada_variant"] == "rescue_only"


def test_no_alloc_aware_changes_phase1_selection():
    """AC-V3：no_alloc_aware 去掉 Delta_phi -> Phase-1 选择键变为 (ell_R/F_j, j)。"""
    view = _view(_scenario_alloc_aware())
    assert view.local_success(0) is False  # t1 local-failure（Phase-1 处理）
    # 手算前提：两服务器均 candidate edge 可行
    assert view.edge_feasible(0, 0) and view.edge_feasible(0, 1)
    full = _run_aada(view, "full")
    assert full["assignment_matrix"][0][0] == 1  # full -> A（dphi 小优先）
    na = _run_aada(view, "no_alloc_aware")
    assert na["assignment_matrix"][0][1] == 1  # no_alloc_aware -> B（floor 小优先）
    # 归一化 floor 手算校验（ell_R/F_j）
    ln_r = math.log(0.99 / 0.95)
    ell_a = 0.003 * 8 * 5000 / ln_r
    ell_b = 0.0005 * 8 * 5000 / ln_r
    assert abs(ell_a / 30000.0 - 0.09696) < 1e-3
    assert abs(ell_b / 10000.0 - 0.048478) < 1e-3
    assert ell_a / 30000.0 > ell_b / 10000.0  # A floor 归一化更大


def test_full_default_matches_manuscript_semantics():
    """AC-V4：full 默认行为回归——场景 D 本地成功任务卸载（Rbar 改善）。"""
    view = _view(_scenario_d())
    res = _run_aada(view, "full")
    assert res["offloading_decision"][0] == 1
    assert res["diagnostics"]["aada_variant"] == "full"
