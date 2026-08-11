# -*- coding: utf-8 -*-
"""E3-V2-1：环境识别 Pilot runner（机制触发诊断，NOT_FORMAL）。

阶段合同（用户 2026-08-09）：
- 只运行 N={20,80,150} × seeds {201,202,203}；
- 首先运行 **Full AADA+RCLA** 进行环境机制识别（不先跑全部 ablation 挑环境）；
- 环境选择 = mechanism identifiability，**严禁依据 TSSR_Full - TSSR_ablation
  最大选择环境**；
- 所有环境使用同一冻结生成器（build_e3_v2_environment）；同 seed 同 N 实例
  与 pressure 无关（服务器先行、前缀一致）；不得因方法改变重新生成任务；
- 不运行 formal seeds 401-410；不修改正式 cars/Contract V3/Schema V3/III_VI；
- 不新增/删除/重新定义 variant；admission 只验证不消融。

输出：
- results/e3_v2/e3_v2_1_environment_pilot/{scenarios/, run_<N>_<seed>.json}
- results/e3_v2/e3_v2_1_environment_summary.json（环境识别表 + 判定）
"""
from __future__ import annotations

import json
import math
import os
import statistics
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e3_v2"))

from build_e3_v2_environment import (  # noqa: E402
    M_DEFAULT,
    PRESSURE_N_CANDIDATE,
    PRESSURE_ORDER,
    build_e3_v2_environment,
    prefix_scenario,
)
from cars.evaluator import evaluator as ev  # noqa: E402
from cars.methods.cars.diagnostics import _decision_hash  # noqa: E402
from cars.methods.cars.pipeline import run_aada_rcla_pipeline  # noqa: E402
from cars.methods.cars.state import CandidateStateView  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

# ---------------------------------------------------------------------------
# 阶段规格（E3-V2-1 合同冻结）
# ---------------------------------------------------------------------------
PILOT_SEEDS = [201, 202, 203]
PILOT_N = [20, 80, 150]  # 对应 low/transition/high 候选
CANDIDATE_VARIANT = "full"
ALLOCATION_MODE = "rcla"
EPS = 1.0e-9
RCLA_CFG = {
    "rcla_mu_tol": 1.0e-9,
    "rcla_max_iters": 200,
    "rcla_mu_lo": 1.0e-12,
    "rcla_mu_hi": 1.0e12,
    "rcla_numeric_epsilon": 1.0e-12,
}
OUT_DIR = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_1_environment_pilot")
SCEN_DIR = os.path.join(OUT_DIR, "scenarios")
SUMMARY_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_1_environment_summary.json")
FORMAL_SEEDS = list(range(401, 411))


def _median(vals):
    if not vals:
        return 0.0
    return float(statistics.median(vals))


def _mean(vals):
    if not vals:
        return 0.0
    return float(statistics.mean(vals))


def _recoverable_stats(view, local_failure):
    """本地失败任务的可恢复性：存在 e_rec=1（edge_feasible）EDGE 的任务数。"""
    recoverable = sum(1 for i in local_failure if any(view.edge_feasible(i, j) for j in range(view.m)))
    return recoverable


def _edge_density(view):
    """可恢复边密度：e_rec=1 边数 / (N*M)。"""
    total = view.n * view.m
    if total == 0:
        return 0.0
    n_rec = sum(1 for (i, j) in view.edges if view.edges[(i, j)]["e_rec"] == 1)
    return n_rec / total


def run_one(seed: int, n: int) -> dict:
    """单 (N, seed) Full AADA+RCLA 机制识别运行。"""
    pressure = "transition"  # 语义标记（与实例内容无关；同 seed 同 N 实例一致）
    cfg = build_e3_v2_environment(seed=seed, n_max=n, pressure=pressure)
    scen = materialize(cfg)
    derived = DerivedState(scen)
    view = CandidateStateView(scen, derived)

    t0 = time.monotonic()
    result = run_aada_rcla_pipeline(
        scen, derived, eps_cmp=EPS, rcla_cfg=dict(RCLA_CFG),
        aada_variant=CANDIDATE_VARIANT, allocation_mode=ALLOCATION_MODE,
    )
    wall_ms = round((time.monotonic() - t0) * 1000.0, 3)

    # ---- 统一 Evaluator（正式指标唯一计算者）----
    out = ev.evaluate(scen, result["decision"], derived)
    sm = (out.get("evaluator_output") or {}).get("system_metrics") or {}

    d = result["diagnostics"]
    aada = d["aada"]
    rcla = d["rcla"]

    # ---- 机制触发量 ----
    local_failure = [i for i in range(view.n) if not view.local_success(i)]
    local_success = [i for i in range(view.n) if view.local_success(i)]
    n_recoverable = _recoverable_stats(view, local_failure)
    n_local_fail = aada["local_failure_count"]
    n_local_succ = aada["local_success_count"]
    n_rescued = aada["rescued_local_failure_count"]
    n_no_feasible = aada["no_feasible_edge_count"]

    g_over_f = aada["per_server_G_over_F"]
    g_max = max(g_over_f) if g_over_f else 0.0
    g_mean = _mean(g_over_f)
    g_median = _median(g_over_f)

    phase2_cand_edge = aada["phase2_candidate_edge_count"]
    phase2_passed = aada["phase2_gate_passed_count"]
    phase2_accepted = aada["utility_improving_offload_count"]
    rej_dR = aada["phase2_gate_rejected_dRbar_count"]
    rej_U = aada["phase2_gate_rejected_utility_count"]

    active_floor = rcla["active_floor_task_count"]
    n_active_floor = active_floor
    n_infeasible = int(rcla["allocation_infeasible"])

    dphi_dist = aada["delta_phi_distribution"]
    dphi_min = min(dphi_dist) if dphi_dist else 0.0
    dphi_max = max(dphi_dist) if dphi_dist else 0.0
    max_eps_dphi = aada["max_epsilon_dphi"]

    tssr = sm.get("tssr")
    rbar = sm.get("mean_effective_reliability")
    ubar = sm.get("mean_effective_utility")
    v_r = sm.get("reliability_violation_rate")

    # 服务器容量分布 / 任务异构性
    caps = [s["F_j"] for s in view.servers]
    hetero_c = [t["c"] for t in view.tasks]
    hetero_nu = [t["nu"] for t in view.tasks]

    row = {
        "N": n,
        "seed": seed,
        "M": view.m,
        "server_capacity_min": min(caps) if caps else 0,
        "server_capacity_max": max(caps) if caps else 0,
        "server_capacity_mean": round(_mean(caps), 1),
        "task_c_heterogeneity": {"min": min(hetero_c), "max": max(hetero_c)} if hetero_c else {},
        "task_nu_set": sorted(set(hetero_nu)) if hetero_nu else [],
        "edge_density_recoverable": round(_edge_density(view), 4),
        "local_success_ratio": round(n_local_succ / view.n, 4) if view.n else 0.0,
        "local_failure_ratio": round(n_local_fail / view.n, 4) if view.n else 0.0,
        # Phase-1
        "n_local_failure": n_local_fail,
        "n_local_failure_recoverable": n_recoverable,
        "recoverable_ratio": round(n_recoverable / n_local_fail, 4) if n_local_fail else 0.0,
        "n_rescued": n_rescued,
        "RescueRate": round(n_rescued / n_local_fail, 4) if n_local_fail else 0.0,
        "n_no_feasible_edge": n_no_feasible,
        # Phase-2
        "n_phase2_candidate_tasks": n_local_succ,
        "n_phase2_candidate_edges": phase2_cand_edge,
        "n_phase2_gate_passed": phase2_passed,
        "n_phase2_accepted": phase2_accepted,
        "Phase2AcceptRate_tasks": round(phase2_accepted / n_local_succ, 4) if n_local_succ else 0.0,
        "Phase2AcceptRate_edges": round(phase2_accepted / phase2_cand_edge, 4) if phase2_cand_edge else 0.0,
        "gate_rejected_dRbar": rej_dR,
        "gate_rejected_utility": rej_U,
        # Admission / RCLA
        "max_G_over_F": round(g_max, 4),
        "mean_G_over_F": round(g_mean, 4),
        "median_G_over_F": round(g_median, 4),
        "N_active_floor": n_active_floor,
        "active_floor_ratio": round(n_active_floor / n_local_fail, 4) if n_local_fail else 0.0,
        "N_ALLOCATION_INFEASIBLE": n_infeasible,
        "max_capacity_residual": round(rcla.get("max_capacity_residual", 0.0), 6),
        # Delta_phi
        "dphi_candidate_count": len(dphi_dist),
        "dphi_min": round(dphi_min, 6),
        "dphi_max": round(dphi_max, 6),
        "dphi_spread": round(dphi_max - dphi_min, 6),
        "max_epsilon_dphi": float(max_eps_dphi),  # Lemma 2 精确性（仅浮点误差）
        # 正式指标（诊断用途，非环境排名依据）
        "TSSR": tssr,
        "Rbar_eff": rbar,
        "Ubar_eff": ubar,
        "V_R": v_r,
        # Runtime（诊断用途，不参与环境排名）
        "runtime_breakdown": d["runtime_breakdown"],
        "wall_clock_ms": wall_ms,
        "pre_eval_xaf_hash16": _decision_hash(
            result["decision"]["offloading_decision"],
            result["decision"]["assignment_matrix"],
            result["decision"]["resource_allocation"],
        )[:16],
        "formal_seed_accessed": False,
    }
    return row, scen


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SCEN_DIR, exist_ok=True)

    rows = []
    for seed in PILOT_SEEDS:
        for n in PILOT_N:
            row, scen = run_one(seed, n)
            # 场景落盘（确定性重跑用）
            scen_path = os.path.join(SCEN_DIR, "scenario_n%d_seed%d.yaml" % (n, seed))
            with open(scen_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(scen, fh, allow_unicode=True, sort_keys=False)
            run_path = os.path.join(OUT_DIR, "run_n%d_seed%d.json" % (n, seed))
            with open(run_path, "w", encoding="utf-8") as fh:
                json.dump(row, fh, ensure_ascii=False, indent=2)
            rows.append(row)
            print("N=%3d seed=%3d | LF:%3d recv:%3d rescue:%3d (%.2f) | P2 tasks:%3d acc:%3d (%.2f) edges:%4d pass:%3d rej(dR/U):%3d/%3d | floor:%3d | G/Fmax:%.3f | infeas:%d | eps_dphi:%.1e | TSSR:%s" % (
                n, seed,
                row["n_local_failure"], row["n_local_failure_recoverable"], row["n_rescued"], row["RescueRate"],
                row["n_phase2_candidate_tasks"], row["n_phase2_accepted"], row["Phase2AcceptRate_tasks"],
                row["n_phase2_candidate_edges"], row["n_phase2_gate_passed"],
                row["gate_rejected_dRbar"], row["gate_rejected_utility"],
                row["N_active_floor"], row["max_G_over_F"], row["N_ALLOCATION_INFEASIBLE"],
                row["max_epsilon_dphi"], row["TSSR"]))

    # ---- 三 seed 汇总（per N）----
    summary = {"meta": {
        "stage": "E3-V2-1",
        "mode": "environment identification pilot (NOT_FORMAL)",
        "candidate_variant": CANDIDATE_VARIANT,
        "allocation_mode": ALLOCATION_MODE,
        "seeds": PILOT_SEEDS,
        "n_candidates": PILOT_N,
        "formal_seeds": FORMAL_SEEDS,
        "formal_seeds_accessed": False,
        "selection_rule": "mechanism identifiability（严禁按 Full 获胜幅度选环境）",
        "n_runs": len(rows),
    }, "per_point": {}, "per_N": {}}

    for r in rows:
        summary["per_point"]["N%d_seed%d" % (r["N"], r["seed"])] = r

    for n in PILOT_N:
        pts = [r for r in rows if r["N"] == n]
        agg = {
            "N": n,
            "seed_count": len(pts),
            "local_failure_ratio_mean": round(_mean([r["local_failure_ratio"] for r in pts]), 4),
            "recoverable_ratio_mean": round(_mean([r["recoverable_ratio"] for r in pts]), 4),
            "RescueRate_mean": round(_mean([r["RescueRate"] for r in pts]), 4),
            "Phase2AcceptRate_tasks_mean": round(_mean([r["Phase2AcceptRate_tasks"] for r in pts]), 4),
            "Phase2AcceptRate_edges_mean": round(_mean([r["Phase2AcceptRate_edges"] for r in pts]), 4),
            "gate_rejected_total_mean": round(_mean([r["gate_rejected_dRbar"] + r["gate_rejected_utility"] for r in pts]), 2),
            "max_G_over_F_mean": round(_mean([r["max_G_over_F"] for r in pts]), 4),
            "N_active_floor_mean": round(_mean([r["N_active_floor"] for r in pts]), 2),
            "N_ALLOCATION_INFEASIBLE_total": sum(r["N_ALLOCATION_INFEASIBLE"] for r in pts),
            "max_epsilon_dphi_max": max(r["max_epsilon_dphi"] for r in pts),  # 原始浮点
            "dphi_spread_mean": round(_mean([r["dphi_spread"] for r in pts]), 6),
            "TSSR_mean": round(_mean([r["TSSR"] for r in pts]), 4) if all(r["TSSR"] is not None for r in pts) else None,
            "has_phase2_accept_and_reject": all(
                (r["n_phase2_accepted"] > 0) and (r["gate_rejected_dRbar"] + r["gate_rejected_utility"] > 0)
                for r in pts),
            "all_seeds_floor_positive": all(r["N_active_floor"] > 0 for r in pts),
            "all_seeds_floor_some_inactive": all(r["N_active_floor"] > 0 for r in pts),
        }
        summary["per_N"]["N%d" % n] = agg

    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    print("\nDONE: %d runs -> %s" % (len(rows), SUMMARY_PATH))
    for n in PILOT_N:
        a = summary["per_N"]["N%d" % n]
        print("N=%3d | LFratio %.3f | recv %.3f | rescue %.3f | P2acc %.3f | gateRej %.1f | G/F %.3f | floor %.1f | infeas %d | eps %.1e" % (
            n, a["local_failure_ratio_mean"], a["recoverable_ratio_mean"], a["RescueRate_mean"],
            a["Phase2AcceptRate_tasks_mean"], a["gate_rejected_total_mean"], a["max_G_over_F_mean"],
            a["N_active_floor_mean"], a["N_ALLOCATION_INFEASIBLE_total"], a["max_epsilon_dphi_max"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
