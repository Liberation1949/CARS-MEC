# -*- coding: utf-8 -*-
"""E3-V2-2：正式组件消融与机制验证 runner（Confirmatory Evaluation）。

阶段合同（用户 2026-08-09）：
- 正式环境：LOW=N20 / TRANSITION=N80 / HIGH=N150（PRIMARY=TRANSITION）；
- formal seeds 401-410（pilot 201-203 禁止进入正式统计）；
- 7 个执行单元：full / no_rescue / rescue_only / no_alloc_aware /
  no_utility_gate / fixed_rcla / fixed_ordinary_la（fixed 共享同一 X/A hash）；
- 总规模 10 seeds × 3 pressures × 7 units = 210 runs；
- 同 (pressure, seed) 全部 variant 共享同一 canonical scenario（scenario_hash 记录）；
- 统一 Evaluator 唯一正式评价；正式指标 TSSR（主）+ Rbar_eff/Ubar_eff/V_R/LI_dem；
- 机制诊断 + Δφ audit（max_epsilon_dphi）+ RCLA 诊断 + 失败来源 + runtime 五段；
- 不得调环境/算法/variant/指标；不得删除 seed；不得因无差异重调。

输出：results/e3_v2/e3_v2_2_formal/{scenarios/, raw_records.jsonl}
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e3_v2"))

from build_e3_v2_environment import build_e3_v2_environment  # noqa: E402
from cars.evaluator import evaluator as ev  # noqa: E402
from cars.methods.cars.diagnostics import _decision_hash  # noqa: E402
from cars.methods.cars.pipeline import run_aada_rcla_pipeline  # noqa: E402
from cars.methods.cars.state import CandidateStateView  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结规格（E3-V2-2 合同）
# ---------------------------------------------------------------------------
FORMAL_SEEDS = [401, 402, 403, 404, 405, 406, 407, 408, 409, 410]
PRESSURE_N = {"LOW": 20, "TRANSITION": 80, "HIGH": 150}
PRESSURE_ORDER = ["LOW", "TRANSITION", "HIGH"]
EPS = 1.0e-9
RCLA_CFG = {
    "rcla_mu_tol": 1.0e-9,
    "rcla_max_iters": 200,
    "rcla_mu_lo": 1.0e-12,
    "rcla_mu_hi": 1.0e12,
    "rcla_numeric_epsilon": 1.0e-12,
}
UNITS = [
    ("full", "full", "rcla"),
    ("no_rescue", "no_rescue", "rcla"),
    ("rescue_only", "rescue_only", "rcla"),
    ("no_alloc_aware", "no_alloc_aware", "rcla"),
    ("no_utility_gate", "no_utility_gate", "rcla"),
    ("fixed_ordinary_la", "full", "ordinary_la"),
    # fixed_rcla 由 full 复用（同一 X/A；allocation=RCLA）
]
OUT_DIR = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_formal")
SCEN_DIR = os.path.join(OUT_DIR, "scenarios")
RAW_PATH = os.path.join(OUT_DIR, "raw_records.jsonl")
META_PATH = os.path.join(OUT_DIR, "formal_meta.json")


def _li_dem(view, a_mat):
    """正文 III-E.5：LI^dem(A) = (1/M) sum_j (rho_j^dem - rho^dem_bar)^2；
    rho_j^dem = sum_i a_ij * f_i^loc / F_j。"""
    m = view.m
    rho = []
    for j in range(m):
        F_j = view.servers[j]["F_j"]
        if F_j <= 0.0:
            rho.append(0.0)
            continue
        s = sum(view.tasks[i]["f_loc"] for i in range(view.n) if a_mat[i][j] == 1)
        rho.append(s / F_j)
    rho_bar = sum(rho) / m if m else 0.0
    return float(sum((r - rho_bar) ** 2 for r in rho) / m)


def _failure_sources(eval_out, x):
    """失败来源分类（互斥完整；按任务索引对齐 offloading_decision x）。"""
    counts = {
        "LOCAL_FAILURE_NO_RECOVERABLE_EDGE": 0,
        "EDGE_RELIABILITY_VIOLATION": 0,
        "ALLOCATION_INFEASIBLE": 0,
        "STRUCTURAL_VIOLATION": 0,
        "OTHER": 0,
    }
    tr = eval_out["evaluator_output"]["task_results"]
    for i, r in enumerate(tr):
        reason = r["failure_reason"]
        if reason == "SUCCESS":
            continue
        if reason in ("STRUCT_INVALID", "PATH_AMBIGUOUS", "EXEC_INVALID", "CAPACITY_INFEASIBLE"):
            counts["STRUCTURAL_VIOLATION"] += 1
        elif reason == "RELIABILITY_VIOLATION":
            if x[i] == 1:
                counts["EDGE_RELIABILITY_VIOLATION"] += 1
            else:
                counts["LOCAL_FAILURE_NO_RECOVERABLE_EDGE"] += 1
        else:
            counts["OTHER"] += 1
    return counts


def _x_hash(x):
    return hashlib.sha256(
        json.dumps([int(v) for v in x], separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _a_hash(a):
    return hashlib.sha256(
        json.dumps([[int(v) for v in row] for row in a], separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _xa_hash(off, a):
    n = len(off)
    m = len(a[0]) if a else 0
    zero_f = [[0.0] * m for _ in range(n)]
    return _decision_hash(off, a, zero_f)


def run_one(seed: int, pressure: str) -> list:
    """单 (pressure, seed)：7 个执行单元正式记录（共享同一 scenario）。"""
    os.makedirs(SCEN_DIR, exist_ok=True)
    n = PRESSURE_N[pressure]
    cfg = build_e3_v2_environment(seed=seed, n_max=n, pressure=pressure.lower())
    scen = materialize(cfg)
    derived = DerivedState(scen)
    view = CandidateStateView(scen, derived)

    scen_path = os.path.join(SCEN_DIR, "scenario_%s_n%d_seed%d.yaml" % (pressure, n, seed))
    with open(scen_path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(scen, fh, allow_unicode=True, sort_keys=False)
    with open(scen_path, "rb") as fh:
        scen_hash = hashlib.sha256(fh.read()).hexdigest()

    results = {}
    x_hashes, a_hashes, xa_hashes = {}, {}, {}
    for unit_id, variant, alloc in UNITS:
        r = run_aada_rcla_pipeline(
            scen, derived, eps_cmp=EPS, rcla_cfg=dict(RCLA_CFG),
            aada_variant=variant, allocation_mode=alloc,
        )
        results[unit_id] = r
        x_hashes[unit_id] = _x_hash(r["decision"]["offloading_decision"])
        a_hashes[unit_id] = _a_hash(r["decision"]["assignment_matrix"])
        xa_hashes[unit_id] = _xa_hash(
            r["decision"]["offloading_decision"], r["decision"]["assignment_matrix"]
        )

    # fixed_rcla = full 复用（同一 X/A，allocation=RCLA）
    x_hashes["fixed_rcla"] = x_hashes["full"]
    a_hashes["fixed_rcla"] = a_hashes["full"]
    xa_hashes["fixed_rcla"] = xa_hashes["full"]

    # ---- fixed-assignment 断言（同一 X 与同一 A；不一致则对照无效并停止）----
    if not (x_hashes["full"] == x_hashes["fixed_ordinary_la"] == x_hashes["fixed_rcla"]):
        raise RuntimeError(
            "E3-V2-2 P1: fixed-assignment X hash mismatch seed=%d pressure=%s"
            % (seed, pressure)
        )
    if not (a_hashes["full"] == a_hashes["fixed_ordinary_la"] == a_hashes["fixed_rcla"]):
        raise RuntimeError(
            "E3-V2-2 P1: fixed-assignment A hash mismatch seed=%d pressure=%s"
            % (seed, pressure)
        )

    # ---- 每 unit 正式记录 ----
    # fixed_rcla 复用 full 的完整结果（同一 X/A，allocation=RCLA）
    _SOURCE = {"fixed_rcla": "full"}
    records = []
    for unit_id in ["full", "no_rescue", "rescue_only", "no_alloc_aware",
                    "no_utility_gate", "fixed_rcla", "fixed_ordinary_la"]:
        r = results[_SOURCE.get(unit_id, unit_id)]
        d = r["diagnostics"]
        aada = d["aada"]
        rcla = d["rcla"]
        dec = r["decision"]
        x = dec["offloading_decision"]
        a = dec["assignment_matrix"]
        f = dec["resource_allocation"]

        out = ev.evaluate(scen, dec, derived)
        sm = (out.get("evaluator_output") or {}).get("system_metrics") or {}
        eval_status = out["evaluator_status"].value

        local_failure = aada["local_failure_count"]
        local_success = aada["local_success_count"]
        n_recoverable = 0
        if unit_id in ("full", "no_rescue", "rescue_only", "no_alloc_aware", "no_utility_gate"):
            n_recoverable = sum(
                1 for i in range(view.n)
                if not view.local_success(i) and any(view.edge_feasible(i, j) for j in range(view.m))
            )
        else:  # fixed 与 full 相同（AADA 一致）
            n_recoverable = sum(
                1 for i in range(view.n)
                if not view.local_success(i) and any(view.edge_feasible(i, j) for j in range(view.m))
            )

        g_over_f = aada["per_server_G_over_F"]
        max_gf = max(g_over_f) if g_over_f else 0.0
        active_floor = rcla["active_floor_task_count"]

        failures = _failure_sources(out, x)

        record = {
            "seed": seed,
            "pressure": pressure,
            "N": n,
            "unit": unit_id,
            "scenario_id": scen.get("scenario_id"),
            "scenario_hash16": scen_hash[:16],
            "scenario_hash": scen_hash,
            "evaluator_status": eval_status,
            "TSSR": sm.get("tssr"),
            "Rbar_eff": sm.get("mean_effective_reliability"),
            "Ubar_eff": sm.get("mean_effective_utility"),
            "V_R": sm.get("reliability_violation_rate"),
            "LI_dem": round(_li_dem(view, a), 6),
            # AADA 机制诊断
            "local_failure_count": local_failure,
            "local_failure_rate": round(local_failure / view.n, 4) if view.n else 0.0,
            "recoverable_local_failure_count": n_recoverable,
            "recoverable_local_failure_rate": round(n_recoverable / local_failure, 4) if local_failure else 0.0,
            "rescued_count": aada["rescued_local_failure_count"],
            "RescueRate": round(aada["rescued_local_failure_count"] / local_failure, 4) if local_failure else 0.0,
            "no_candidate_count": aada["no_feasible_edge_count"],
            "phase2_candidate_count": local_success,
            "phase2_candidate_edges": aada["phase2_candidate_edge_count"],
            "phase2_accepted_count": aada["utility_improving_offload_count"],
            "Phase2AcceptRate": round(aada["utility_improving_offload_count"] / local_success, 4) if local_success else 0.0,
            "reliability_gate_rejection_count": aada["phase2_gate_rejected_dRbar_count"],
            "utility_gate_rejection_count": aada["phase2_gate_rejected_utility_count"],
            "edge_assigned_count": int(sum(x)),
            # Δφ audit
            "max_epsilon_dphi": aada["max_epsilon_dphi"],
            "dphi_candidate_count": len(aada["delta_phi_distribution"]),
            # RCLA 诊断
            "N_active_floor": active_floor,
            "active_floor_ratio": round(active_floor / view.n, 4) if view.n else 0.0,
            "max_G_over_F": round(max_gf, 4),
            "mean_G_over_F": round(sum(g_over_f) / len(g_over_f), 4) if g_over_f else 0.0,
            "capacity_residual": rcla.get("max_capacity_residual", 0.0),
            "kkt_residual": rcla.get("kkt_residual", 0.0),
            "N_ALLOCATION_INFEASIBLE": int(rcla.get("allocation_infeasible", False)),
            # 失败来源
            "failure_sources": failures,
            # Runtime 五段
            "runtime": {
                "preprocess_runtime_ms": d["runtime_breakdown"]["preprocess_ms"],
                "phase1_runtime_ms": d["runtime_breakdown"]["aada_phase1_ms"],
                "phase2_runtime_ms": d["runtime_breakdown"]["aada_phase2_ms"],
                "allocation_runtime_ms": d["runtime_breakdown"]["rcla_ms"],
                "total_runtime_ms": d["runtime_breakdown"]["total_ms"],
            },
            "phase2_primary_cost": bool(
                d["runtime_breakdown"]["aada_phase2_ms"]
                >= d["runtime_breakdown"]["rcla_ms"]
            ),
            # X/A hash（fixed-assignment 断言：full/fixed_rcla/fixed_la 三者 X 与 A 均一致）
            "X_hash16": x_hashes[unit_id][:16],
            "A_hash16": a_hashes[unit_id][:16],
            "XA_hash16": xa_hashes[unit_id][:16],
            "paired_scenario_shared": True,
            "formal_seed_used": True,
        }
        records.append(record)
    return records, scen_hash


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(SCEN_DIR, exist_ok=True)
    t0 = time.monotonic()
    n_runs = 0
    scen_hashes = {}
    with open(RAW_PATH, "w", encoding="utf-8") as raw:
        for pressure in PRESSURE_ORDER:
            for seed in FORMAL_SEEDS:
                records, shash = run_one(seed, pressure)
                scen_hashes["%s_%d" % (pressure, seed)] = shash
                for rec in records:
                    raw.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n_runs += 1
                print("  %s seed=%d done (7 units)" % (pressure, seed))

    meta = {
        "stage": "E3-V2-2",
        "mode": "Confirmatory Evaluation (formal)",
        "seeds": FORMAL_SEEDS,
        "pressures": PRESSURE_ORDER,
        "units": [u[0] for u in UNITS] + ["fixed_rcla"],
        "total_expected_runs": 210,
        "total_written_runs": n_runs,
        "scenario_hashes": scen_hashes,
        "elapsed_seconds": round(time.monotonic() - t0, 2),
    }
    with open(META_PATH, "w", encoding="utf-8") as fh:
        json.dump(meta, fh, ensure_ascii=False, indent=2)
    print("\nDONE: %d raw records -> %s" % (n_runs, RAW_PATH))
    return 0


if __name__ == "__main__":
    sys.exit(main())
