# -*- coding: utf-8 -*-
"""E3-V2 Phase-2 P0 字典序门控测试（正文 V-B.6 / VI-C Lemma 4；E3-0 冻结）。

覆盖：
- AC-G1：Delta_Rbar_eff 严格改善 -> 接受（即使 Delta_U_sys < 0；Rbar 优先于 U）；
- AC-G2：Delta_Rbar_eff 严格下降 -> 拒绝（即使 Delta_U_sys > 0；P0 字典序 Rbar 不降）；
- AC-G3：no_utility_gate 保留 Rbar 门槛（Delta_Rbar_eff <= -eps 仍拒绝）；
- AC-G4：_better_phase2 纯函数字典序（full / no_gate / no_alloc 三种选择键）；
- AC-G5：_phase2_deltas 数值与手算一致（R_off - R_loc，服务器空）。

手算（代码盲算；服务器空 -> S={i}，Delta_Rbar = R_off - R_loc）：
  场景 G1（Uneg_Rimp）：t1 local-success（R_loc=exp(-0.002*8*5000/800)=0.904837 >= 0.9）；
    s1 F=100000, λ=0.001；R_off=0.99*exp(-0.001*8*5000/100000)=0.99*exp(-0.0004)=0.989604；
    Delta_Rbar = +0.084767 > eps；慢链路（data_bits=100000, BW=1000）-> U<0。
    预期：full 接受（Rbar 改善优先），no_utility_gate 也接受。
  场景 G2（Rdec_Upos）：t1 local-success（R_loc=exp(-0.002*8*2000/2000)=exp(-0.016)=0.984127）；
    s1 F=5000, λ=0.003；R_off=0.99*exp(-0.003*8*2000/5000)=0.99*exp(-0.0096)=0.980542；
    Delta_Rbar = -0.003585 < -eps；快链路 -> U>0。
    预期：full 拒绝（Rbar 下降），no_utility_gate 也拒绝（保留 Rbar 门槛）。
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

from cars.methods.cars.aada import _better_phase2, run_aada  # noqa: E402
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
# 场景 G1：Rbar 严格改善 + U<0（慢链路）
# ---------------------------------------------------------------------------

def _scenario_g1():
    servers = [
        make_server("s1", capacity_cycles_per_sec=100000, nominal_failure_rate=0.001),
    ]
    devices = [make_device("d1", local_cpu_rate=800)]
    tasks = [
        make_task("t1", "d1", cpu_cycles=5000, fragility=8, delay_weight=0.6, min_reliability=0.9,
                  data_bits=100000),
    ]
    links = [
        make_link("l1", "d1", "s1", bandwidth_hz=1000.0, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
    ]
    return build_scenario(tasks, devices, servers, links, scenario_id="e3v2_scenario_g1")


# ---------------------------------------------------------------------------
# 场景 G2：Rbar 严格下降 + U>0（快链路）
# ---------------------------------------------------------------------------

def _scenario_g2():
    servers = [
        make_server("s1", capacity_cycles_per_sec=5000, nominal_failure_rate=0.003),
    ]
    devices = [make_device("d1", local_cpu_rate=2000)]
    tasks = [
        make_task("t1", "d1", cpu_cycles=2000, fragility=8, delay_weight=0.6, min_reliability=0.9),
    ]
    links = [
        make_link("l1", "d1", "s1", bandwidth_hz=_BW, channel_gain=_GAIN, noise_power=_NOISE, error_probability=_PERR),
    ]
    return build_scenario(tasks, devices, servers, links, scenario_id="e3v2_scenario_g2")


# ---------------------------------------------------------------------------
# 测试
# ---------------------------------------------------------------------------

def test_g1_rbar_improve_beats_negative_utility():
    """AC-G1：Rbar 严格改善时接受卸载，即使 Delta_U_sys<0（P0 字典序 Rbar 优先）。"""
    view = _view(_scenario_g1())
    assert view.local_success(0) is True  # R_loc=0.904837 >= 0.9
    res = _run_aada(view, "full")
    assert res["offloading_decision"][0] == 1
    off = res["diagnostics"]["phase2_offloads"]["t1"]
    # Delta_Rbar_eff 手算：R_off - R_loc（服务器空）
    r_loc = math.exp(-0.002 * 8 * 5000 / 800.0)
    r_off = 0.99 * math.exp(-0.001 * 8 * 5000 / 100000.0)
    assert abs(off["delta_Rbar_eff"] - (r_off - r_loc)) <= 1e-9
    assert off["delta_Rbar_eff"] > EPS
    # Delta_U_sys 为负（慢链路）——证明 Rbar 优先于 U
    assert off["delta_U_sys"] < 0.0


def test_g2_rbar_decrease_rejected_even_with_positive_utility():
    """AC-G2：Rbar 严格下降时拒绝卸载，即使 Delta_U_sys>0（P0 字典序 Rbar 不降）。"""
    view = _view(_scenario_g2())
    assert view.local_success(0) is True  # R_loc=0.984127 >= 0.9
    res = _run_aada(view, "full")
    assert res["offloading_decision"][0] == 0  # 保持 LOCAL
    diag = res["diagnostics"]
    assert diag["phase2_gate_rejected_dRbar_count"] == 1


def test_g3_no_utility_gate_keeps_rbar_threshold():
    """AC-G3：no_utility_gate 保留 Rbar 不降门槛（Rbar 严格下降仍拒绝）。"""
    view = _view(_scenario_g2())
    ng = _run_aada(view, "no_utility_gate")
    assert ng["offloading_decision"][0] == 0
    assert ng["diagnostics"]["phase2_gate_rejected_dRbar_count"] == 1


def test_g4_better_phase2_lexicographic():
    """AC-G4：_better_phase2 纯函数字典序（三种选择键）。"""
    eps = 1e-9
    # full：Rbar 优先
    assert _better_phase2((0.01, -5.0, 1.0, 0), (0.005, 5.0, 1.0, 1),
                          eps_cmp=eps, alloc_aware=True, utility_gate=True)
    assert not _better_phase2((0.005, 5.0, 1.0, 1), (0.01, -5.0, 1.0, 0),
                              eps_cmp=eps, alloc_aware=True, utility_gate=True)
    # full：Rbar 持平 -> U 优先
    assert _better_phase2((0.0, 1.0, 1.0, 0), (0.0, 0.5, 1.0, 1),
                          eps_cmp=eps, alloc_aware=True, utility_gate=True)
    # full：Rbar/U 持平 -> dphi 小者优
    assert _better_phase2((0.0, 1.0, 0.5, 1), (0.0, 1.0, 1.0, 0),
                          eps_cmp=eps, alloc_aware=True, utility_gate=True)
    # full：全持平 -> server_id 小者优
    assert _better_phase2((0.0, 1.0, 1.0, 0), (0.0, 1.0, 1.0, 1),
                          eps_cmp=eps, alloc_aware=True, utility_gate=True)
    # no_utility_gate：忽略 U（dphi 小者优，即使 U 更负）
    assert _better_phase2((0.0, -5.0, 0.5, 1), (0.0, 5.0, 1.0, 0),
                          eps_cmp=eps, alloc_aware=True, utility_gate=False)
    # no_alloc_aware：忽略 dphi（U 高者优，即使 dphi 更大）
    assert _better_phase2((0.0, 1.0, 10.0, 0), (0.0, 0.5, 0.1, 1),
                          eps_cmp=eps, alloc_aware=False, utility_gate=True)


def test_g5_full_accepts_when_rbar_improve_even_negative_utility():
    """AC-G5（补充集成）：full 在 Rbar 改善 + U<0 场景接受；no_gate 同样接受。"""
    view = _view(_scenario_g1())
    full = _run_aada(view, "full")
    ng = _run_aada(view, "no_utility_gate")
    assert full["offloading_decision"][0] == 1
    assert ng["offloading_decision"][0] == 1
