# -*- coding: utf-8 -*-
"""E3-V2-2 正式聚合：mean±std + paired 差异 + 失败来源 + 正确性审计。

输入：results/e3_v2/e3_v2_2_formal/raw_records.jsonl（210 runs）
输出：
- results/e3_v2/e3_v2_2_formal_summary.json（per cell mean±std + paired differences）
- results/e3_v2/e3_v2_2_table_e3_1.csv（Table E3-1：Transition 主环境）
- results/e3_v2/e3_v2_2_claim_audit.json（Claim A-F 判定所需证据）
"""
from __future__ import annotations

import json
import os
import statistics
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
RAW_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_formal", "raw_records.jsonl")
SUMMARY_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_formal_summary.json")
CSV_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_table_e3_1.csv")
CLAIM_PATH = os.path.join(_PROJECT, "results", "e3_v2", "e3_v2_2_claim_audit.json")

METRICS = ["TSSR", "Rbar_eff", "Ubar_eff", "V_R", "LI_dem",
           "RescueRate", "Phase2AcceptRate", "N_active_floor", "max_G_over_F"]
UNITS = ["full", "no_rescue", "rescue_only", "no_alloc_aware", "no_utility_gate",
         "fixed_rcla", "fixed_ordinary_la"]
PRESSURES = ["LOW", "TRANSITION", "HIGH"]


def _mstd(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return {"mean": None, "std": None, "n": 0}
    return {
        "mean": float(statistics.mean(vals)),
        "std": float(statistics.stdev(vals)) if len(vals) > 1 else 0.0,
        "n": len(vals),
    }


def _paired(a, b):
    """paired 差异 a-b：mean diff、std diff、方向一致 seed 数。"""
    diffs = [x - y for x, y in zip(a, b) if x is not None and y is not None]
    if not diffs:
        return {"mean_diff": None, "std": None, "n": 0, "positive_seeds": 0}
    return {
        "mean_diff": float(statistics.mean(diffs)),
        "std": float(statistics.stdev(diffs)) if len(diffs) > 1 else 0.0,
        "n": len(diffs),
        "positive_seeds": sum(1 for d in diffs if d > 1e-12),
        "negative_seeds": sum(1 for d in diffs if d < -1e-12),
        "zero_seeds": sum(1 for d in diffs if abs(d) <= 1e-12),
    }


def main() -> int:
    rows = []
    with open(RAW_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    print("raw records:", len(rows))
    assert len(rows) == 210, "expected 210 runs, got %d" % len(rows)

    # ---- 完整性 ----
    units_seen = set(r["unit"] for r in rows)
    assert units_seen == set(UNITS), "units mismatch: %s" % sorted(units_seen)
    for p in PRESSURES:
        for s in range(401, 411):
            n = sum(1 for r in rows if r["pressure"] == p and r["seed"] == s)
            assert n == 7, "pressure=%s seed=%d has %d records" % (p, s, n)
    assert all(r["seed"] >= 401 for r in rows), "pilot seed leaked into formal"

    # ---- fixed X/A hash 一致性 ----
    fixed_xa_ok = True
    for p in PRESSURES:
        for s in range(401, 411):
            recs = [r for r in rows if r["pressure"] == p and r["seed"] == s]
            hx = {r["unit"]: r["X_hash16"] for r in recs}
            ha = {r["unit"]: r["A_hash16"] for r in recs}
            if not (hx["full"] == hx["fixed_rcla"] == hx["fixed_ordinary_la"]):
                fixed_xa_ok = False
            if not (ha["full"] == ha["fixed_rcla"] == ha["fixed_ordinary_la"]):
                fixed_xa_ok = False
    print("fixed X/A hash consistent (30 cells):", fixed_xa_ok)

    # ---- per cell mean±std ----
    summary = {"meta": {
        "stage": "E3-V2-2",
        "raw_records": len(rows),
        "seeds": "401-410",
        "pressures": PRESSURES,
        "units": UNITS,
        "fixed_xa_hash_consistent": fixed_xa_ok,
    }, "per_cell": {}, "paired": {}, "correctness": {}, "failure_sources": {}}

    for p in PRESSURES:
        for u in UNITS:
            pts = [r for r in rows if r["pressure"] == p and r["unit"] == u]
            cell = {}
            for m in METRICS:
                cell[m] = _mstd([r[m] for r in pts])
            cell["runtime"] = _mstd([r["runtime"]["total_runtime_ms"] for r in pts])
            summary["per_cell"]["%s/%s" % (p, u)] = cell

    # ---- paired differences（Transition 主环境 + 全压力）----
    pairs = {
        "delta_rescue": ("full", "no_rescue"),
        "delta_phase2": ("full", "rescue_only"),
        "delta_alloc": ("full", "no_alloc_aware"),
        "delta_gate": ("full", "no_utility_gate"),
        "delta_rcla_la": ("fixed_rcla", "fixed_ordinary_la"),
    }
    for pid, (ua, ub) in pairs.items():
        summary["paired"][pid] = {}
        for p in PRESSURES:
            a = [r["TSSR"] for r in rows if r["pressure"] == p and r["unit"] == ua]
            b = [r["TSSR"] for r in rows if r["pressure"] == p and r["unit"] == ub]
            summary["paired"][pid][p] = _paired(a, b)

    # ---- 失败来源汇总（Transition 主环境 + 全压力合计）----
    fs_keys = ["LOCAL_FAILURE_NO_RECOVERABLE_EDGE", "EDGE_RELIABILITY_VIOLATION",
               "ALLOCATION_INFEASIBLE", "STRUCTURAL_VIOLATION", "OTHER"]
    for p in PRESSURES:
        summary["failure_sources"][p] = {}
        for u in UNITS:
            pts = [r for r in rows if r["pressure"] == p and r["unit"] == u]
            agg = {k: sum(r["failure_sources"][k] for r in pts) for k in fs_keys}
            summary["failure_sources"][p][u] = agg

    # ---- 正确性 ----
    summary["correctness"] = {
        "max_epsilon_dphi_max": max(r["max_epsilon_dphi"] for r in rows),
        "N_ALLOCATION_INFEASIBLE_total": sum(r["N_ALLOCATION_INFEASIBLE"] for r in rows),
        "utility_gate_rejection_total": sum(r["utility_gate_rejection_count"] for r in rows),
        "reliability_gate_rejection_total": sum(r["reliability_gate_rejection_count"] for r in rows),
        "fixed_xa_hash_consistent": fixed_xa_ok,
        "formal_seeds_only": all(r["seed"] >= 401 for r in rows),
        "paired_scenario_shared": all(r["paired_scenario_shared"] for r in rows),
        "phase2_primary_cost_cells": sum(1 for r in rows if r["phase2_primary_cost"]),
    }

    with open(SUMMARY_PATH, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)

    # ---- Table E3-1（Transition 主环境）----
    cols = ["Variant", "TSSR", "Rbar_eff", "Ubar_eff", "V_R", "LI_dem",
            "RescueRate", "Phase2AcceptRate", "N_active_floor", "max_G_over_F", "Runtime(ms)"]
    with open(CSV_PATH, "w", encoding="utf-8", newline="") as fh:
        fh.write(",".join(cols) + "\n")
        for u in UNITS:
            c = summary["per_cell"]["TRANSITION/%s" % u]
            row = [u] + [
                "%.4f" % c[m]["mean"] if c[m]["mean"] is not None else ""
                for m in cols[1:-1]
            ] + ["%.1f" % c["runtime"]["mean"] if c["runtime"]["mean"] is not None else ""]
            fh.write(",".join(row) + "\n")

    print("\n== Table E3-1 (TRANSITION, mean) ==")
    print("%-18s %7s %7s %7s %6s %7s %7s %7s %6s %7s" % (
        "Variant", "TSSR", "Rbar", "Ubar", "V_R", "LI", "Rescue", "P2Acc", "Floor", "G/F"))
    for u in UNITS:
        c = summary["per_cell"]["TRANSITION/%s" % u]
        print("%-18s %7.4f %7.4f %7.4f %6.4f %7.4f %7.4f %7.4f %6.1f %7.4f" % (
            u, c["TSSR"]["mean"], c["Rbar_eff"]["mean"], c["Ubar_eff"]["mean"],
            c["V_R"]["mean"], c["LI_dem"]["mean"], c["RescueRate"]["mean"],
            c["Phase2AcceptRate"]["mean"], c["N_active_floor"]["mean"], c["max_G_over_F"]["mean"]))

    print("\n== Paired ΔTSSR (Transition) ==")
    for pid in pairs:
        d = summary["paired"][pid]["TRANSITION"]
        print("%-15s Δ=%.4f±%.4f  pos=%d/10  neg=%d  zero=%d" % (
            pid, d["mean_diff"], d["std"], d["positive_seeds"],
            d["negative_seeds"], d["zero_seeds"]))

    # ---- Claim audit（仅汇总证据；判定在报告/claim_audit）----
    claim_audit = {
        "stage": "E3-V2-2",
        "claim_A_rescue": {
            "transition_delta_tssr": summary["paired"]["delta_rescue"]["TRANSITION"],
            "evidence": "full vs no_rescue（Phase-1 贡献）",
        },
        "claim_B_phase2": {
            "transition_delta_ubar": _paired(
                [r["Ubar_eff"] for r in rows if r["pressure"] == "TRANSITION" and r["unit"] == "full"],
                [r["Ubar_eff"] for r in rows if r["pressure"] == "TRANSITION" and r["unit"] == "rescue_only"]),
            "transition_delta_tssr": summary["paired"]["delta_phase2"]["TRANSITION"],
            "evidence": "full vs rescue_only（Phase-2 贡献，重点 Ubar）",
        },
        "claim_C_alloc_aware": {
            "transition_delta_li_dem": _paired(
                [r["LI_dem"] for r in rows if r["pressure"] == "TRANSITION" and r["unit"] == "full"],
                [r["LI_dem"] for r in rows if r["pressure"] == "TRANSITION" and r["unit"] == "no_alloc_aware"]),
            "transition_delta_tssr": summary["paired"]["delta_alloc"]["TRANSITION"],
            "evidence": "full vs no_alloc_aware（Δφ 作用：TSSR/LI/G-F）",
        },
        "claim_D_utility_gate": {
            "utility_gate_rejection_total": summary["correctness"]["utility_gate_rejection_total"],
            "transition_delta_tssr": summary["paired"]["delta_gate"]["TRANSITION"],
            "evidence": "full vs no_utility_gate（utility branch 是否触发）",
        },
        "claim_E_rcla_floor": {
            "transition_delta_tssr": summary["paired"]["delta_rcla_la"]["TRANSITION"],
            "transition_delta_vr": _paired(
                [r["V_R"] for r in rows if r["pressure"] == "TRANSITION" and r["unit"] == "fixed_rcla"],
                [r["V_R"] for r in rows if r["pressure"] == "TRANSITION" and r["unit"] == "fixed_ordinary_la"]),
            "evidence": "fixed_rcla vs fixed_ordinary_la（同一 X/A，floor 作用）",
        },
        "claim_F_correctness": summary["correctness"],
    }
    with open(CLAIM_PATH, "w", encoding="utf-8") as fh:
        json.dump(claim_audit, fh, ensure_ascii=False, indent=2)

    print("\nsummary ->", SUMMARY_PATH)
    print("table ->", CSV_PATH)
    print("claim_audit ->", CLAIM_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
