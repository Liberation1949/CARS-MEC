# -*- coding: utf-8 -*-
"""E2-V2-0 环境校准聚合（读取 calibration_raw.jsonl）。

输出：
- results/e2_v2/e2_v2_0_calibration/environment_diagnostics.json（Layer A 汇总）
- results/e2_v2/e2_v2_0_calibration/environment_comparison.csv（环境比较表）
- results/e2_v2/e2_v2_0_calibration/ac_env_checks.json（AC-E2-ENV-1..5 机械检查）

Layer A 汇总：每 (n, cv_f) 的 3-seed 均值（capacity structure / predecision /
floor pressure）。Layer B：每 (n, cv_f) 各方法 mean TSSR 与 between-method
identifiability（range/variance）。

本脚本只做环境结构诊断汇总与 AC 机械检查；环境最终选择在报告
（E2-V2-0_environment_calibration.md）中按 AC-E2-ENV-1..5 + 优先级 + 预注册
tie-break（N=170）完成，禁止依据 CARS 排名。
"""
from __future__ import annotations

import csv
import json
import math
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e2_v2", "e2_v2_0_calibration")
RAW_PATH = os.path.join(OUT_DIR, "calibration_raw.jsonl")

LAYER_A_KEYS = [
    "F_total", "mean_F", "std_F", "CV_F_target", "CV_F_realized", "theta",
    "min_F", "max_F", "max_min_ratio", "capacity_HHI", "top2_capacity_share",
    "local_feasible_ratio", "edge_feasible_ratio", "tasks_feasible_edge_ratio",
    "floor_positive_ratio", "aggregate_min_floor_demand", "demand_capacity_ratio",
    "per_server_pressure_max", "per_server_pressure_mean", "pressure_dispersion",
    "predecision_infeasible_ratio",
]
LAYER_B_METHODS = ["cars", "bpso_rata_la", "nfa_adapted", "reliability_only"]


def load_raw():
    recs = []
    if os.path.exists(RAW_PATH):
        with open(RAW_PATH, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if line:
                    recs.append(json.loads(line))
    return recs


def mean(vals):
    vals = [v for v in vals if v is not None]
    return round(sum(vals) / len(vals), 6) if vals else None


def aggregate_layer_a(recs):
    """返回 {(n, cv_f): {key: mean}}（layer_a 记录，按 seed 平均）。"""
    out = {}
    for r in recs:
        if r.get("kind") != "layer_a":
            continue
        key = (r["n"], r["cv_f"])
        bucket = out.setdefault(key, {})
        for k in LAYER_A_KEYS:
            if k in r:
                bucket.setdefault(k, []).append(r[k])
    return {k: {kk: mean(vv) for kk, vv in v.items()} for k, v in out.items()}


def aggregate_layer_b(recs):
    """返回 {(n, cv_f): {method: mean_tssr}}（layer_b，按 seed 平均）。"""
    out = {}
    for r in recs:
        if r.get("kind") != "layer_b":
            continue
        key = (r["n"], r["cv_f"])
        bucket = out.setdefault(key, {})
        for m in LAYER_B_METHODS:
            if r.get("%s_tssr" % m) is not None:
                bucket.setdefault(m, []).append(r["%s_tssr" % m])
    return {k: {m: mean(v) for m, v in v.items()} for k, v in out.items()}


def identifiability(method_tssr):
    """between-method 可辨识性（方法无关；不含 CARS 排名）。"""
    vals = [v for v in method_tssr.values() if v is not None]
    if len(vals) < 2:
        return {"range": None, "variance": None, "all_ceiling": None, "all_collapse": None}
    rng = max(vals) - min(vals)
    mu = sum(vals) / len(vals)
    var = sum((v - mu) ** 2 for v in vals) / len(vals)
    return {
        "range": round(rng, 6),
        "variance": round(var, 6),
        "all_ceiling": all(v >= 0.999 for v in vals),
        "all_collapse": all(v <= 0.001 for v in vals),
    }


def check_ac(agg, layer_b_agg):
    """AC-E2-ENV-1..5 机械检查（只对数据做客观断言，不做选择）。"""
    checks = {}
    for n in sorted({k[0] for k in agg}):
        hhis = []
        cvs = []
        ftotals = []
        for cv in [0.0, 0.3, 0.6, 0.9, 1.2]:
            rec = agg.get((n, cv))
            if rec is None:
                continue
            hhis.append(rec.get("capacity_HHI"))
            cvs.append(rec.get("CV_F_realized"))
            ftotals.append(rec.get("F_total"))
        # AC-1: HHI 单调上升 + CV 匹配
        hhi_mono = all(
            hhis[i + 1] is not None and hhis[i] is not None and hhis[i + 1] >= hhis[i] - 1e-9
            for i in range(len(hhis) - 1))
        cv_match = all(
            abs(cv_t - cv_r) <= 1e-4
            for cv_t, cv_r in zip([0.0, 0.3, 0.6, 0.9, 1.2][:len(cvs)], cvs)
            if cv_r is not None)
        # AC-5: F_total 恒定
        ft_const = all(
            ft is not None and abs(ft - ftotals[0]) <= 1e-6 * (ftotals[0] or 1)
            for ft in ftotals)
        # AC-4 参考: 最高正式候选点 predecision_infeasible < 0.20
        hi = agg.get((n, 1.2), {})
        preinf_hi = hi.get("predecision_infeasible_ratio")
        checks[str(n)] = {
            "hhi_by_cv": hhis,
            "hhi_monotonic": hhi_mono,
            "cv_realized": cvs,
            "cv_match": cv_match,
            "f_total_by_cv": ftotals,
            "f_total_constant": ft_const,
            "preinf_at_1_2": preinf_hi,
            "preinf_1_2_below_0_20": (preinf_hi is not None and preinf_hi < 0.20),
        }
    return checks


def main() -> int:
    recs = load_raw()
    agg = aggregate_layer_a(recs)
    layer_b = aggregate_layer_b(recs)
    ns = sorted({k[0] for k in agg})
    cvs = sorted({k[1] for k in agg})

    # environment_diagnostics.json
    diag = {"layer_a": {}, "layer_b": {}, "n_grid": ns, "cv_grid": cvs}
    for (n, cv), rec in sorted(agg.items()):
        diag["layer_a"]["n%d_cv%s" % (n, ("%.1f" % cv))] = rec
    for (n, cv), rec in sorted(layer_b.items()):
        cell = dict(rec)
        cell["identifiability"] = identifiability(rec)
        diag["layer_b"]["n%d_cv%s" % (n, ("%.1f" % cv))] = cell
    ac_checks = check_ac(agg, layer_b)
    diag["ac_env_checks"] = ac_checks
    with open(os.path.join(OUT_DIR, "environment_diagnostics.json"), "w",
              encoding="utf-8") as fh:
        json.dump(diag, fh, ensure_ascii=False, indent=2)
    with open(os.path.join(OUT_DIR, "ac_env_checks.json"), "w",
              encoding="utf-8") as fh:
        json.dump({"ac_env_checks": ac_checks}, fh, ensure_ascii=False, indent=2)

    # environment_comparison.csv：每 (n, cv) 一行关键压力指标
    cols = ["n", "cv_f", "F_total", "CV_realized", "HHI", "max_min_ratio",
            "top2_share", "local_feasible", "edge_feasible", "tasks_feasible_edge",
            "aggregate_floor_demand", "d_c_ratio", "pressure_max", "preinf",
            "cars_tssr", "bpso_tssr", "nfa_tssr", "rel_tssr", "between_range"]
    with open(os.path.join(OUT_DIR, "environment_comparison.csv"), "w",
              newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for n in ns:
            for cv in cvs:
                a = agg.get((n, cv), {})
                b = layer_b.get((n, cv), {})
                idf = identifiability(b)
                w.writerow([
                    n, cv, a.get("F_total"), a.get("CV_F_realized"),
                    a.get("capacity_HHI"), a.get("max_min_ratio"),
                    a.get("top2_capacity_share"), a.get("local_feasible_ratio"),
                    a.get("edge_feasible_ratio"), a.get("tasks_feasible_edge_ratio"),
                    a.get("aggregate_min_floor_demand"), a.get("demand_capacity_ratio"),
                    a.get("per_server_pressure_max"), a.get("predecision_infeasible_ratio"),
                    b.get("cars"), b.get("bpso_rata_la"), b.get("nfa_adapted"),
                    b.get("reliability_only"), idf.get("range"),
                ])

    # 打印可读表
    print("=== E2-V2-0 Layer A（3-seed mean）===")
    hdr = "%-4s %-5s | %-9s %-6s %-6s %-8s | %-7s %-7s %-6s %-7s | %-6s %-6s | %-7s" % (
        "N", "CV", "F_total", "CV_r", "HHI", "max/min", "locF", "eF", "tEF", "preinf",
        "d/c", "pMax", "pDisp")
    print(hdr)
    print("-" * len(hdr))
    for n in ns:
        for cv in cvs:
            a = agg.get((n, cv), {})
            print("%-4d %-5s | %-9s %-6s %-6s %-8s | %-7s %-7s %-6s %-7s | %-6s %-6s | %-7s" % (
                n, ("%.1f" % cv), a.get("F_total"), a.get("CV_F_realized"),
                a.get("capacity_HHI"), a.get("max_min_ratio"),
                a.get("local_feasible_ratio"), a.get("edge_feasible_ratio"),
                a.get("tasks_feasible_edge_ratio"), a.get("predecision_infeasible_ratio"),
                a.get("demand_capacity_ratio"), a.get("per_server_pressure_max"),
                a.get("pressure_dispersion")))
    print("\n=== E2-V2-0 Layer B TSSR（3-seed mean；4 方法 sanity）===")
    hdr2 = "%-4s %-5s | %-7s %-10s %-10s %-9s | %-8s %-7s" % (
        "N", "CV", "cars", "bpso", "nfa", "rel", "range", "allceil")
    print(hdr2)
    print("-" * len(hdr2))
    for n in ns:
        for cv in cvs:
            b = layer_b.get((n, cv), {})
            idf = identifiability(b)
            print("%-4d %-5s | %-7s %-10s %-10s %-9s | %-8s %-7s" % (
                n, ("%.1f" % cv), b.get("cars"), b.get("bpso_rata_la"),
                b.get("nfa_adapted"), b.get("reliability_only"),
                idf.get("range"), idf.get("all_ceiling")))
    print("\n=== AC-E2-ENV 机械检查 ===")
    print(json.dumps(ac_checks, ensure_ascii=False, indent=2))
    print("\nwritten: environment_diagnostics.json / environment_comparison.csv / ac_env_checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
