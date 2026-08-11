# -*- coding: utf-8 -*-
"""E1-V2-0 环境校准聚合（读取 calibration_raw.jsonl）。

输出：
- results/e1_v2/e1_v2_0_calibration/environment_diagnostics.json（Layer A 汇总）
- results/e1_v2/e1_v2_0_calibration/environment_comparison.csv（环境比较表）

Layer A 汇总：每 env × N 的 3-seed 均值（local_feasible / edge_feasible /
aggregate_min_floor_demand / total_capacity / demand_capacity_ratio /
per_server_pressure_max / predecision_infeasible_ratio）。

本脚本只做环境结构诊断汇总；环境选择（coarse 筛 ≤3 -> confirm -> 冻结）在
报告（E1-V2-0_environment_calibration.md）中按 AC-E1-ENV-1..5 + 确定性
tie-break 完成，禁止依据 CARS 排名。
"""
from __future__ import annotations

import csv
import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
OUT_DIR = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_0_calibration")
RAW_PATH = os.path.join(OUT_DIR, "calibration_raw.jsonl")

LAYER_A_KEYS = [
    "local_feasible_ratio", "edge_feasible_ratio", "floor_positive_ratio",
    "aggregate_min_floor_demand", "total_capacity", "demand_capacity_ratio",
    "per_server_pressure_max", "per_server_pressure_mean", "pressure_dispersion",
    "predecision_infeasible_ratio",
]


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
    """返回 {(env, n): {key: mean}}（coarse_layerA 记录，按 seed 平均）。"""
    out = {}
    for r in recs:
        if r.get("kind") != "layer_a":
            continue
        key = (r["env"], r["n"])
        bucket = out.setdefault(key, {})
        for k in LAYER_A_KEYS:
            if k in r:
                bucket.setdefault(k, []).append(r[k])
    return {k: {kk: mean(vv) for kk, vv in v.items()} for k, v in out.items()}


def layer_b_tssr(recs, env, n):
    """Layer B：env×n 下各方法 mean TSSR（跨 seed）。"""
    methods = ["cars", "bpso_rata_la", "nfa_adapted", "reliability_only"]
    out = {}
    for m in methods:
        vals = [r["%s_tssr" % m] for r in recs
                if r.get("kind") == "layer_b" and r["env"] == env and r["n"] == n
                and r.get("%s_tssr" % m) is not None]
        out[m] = mean(vals)
    return out


def main() -> int:
    recs = load_raw()
    agg = aggregate_layer_a(recs)
    envs = sorted({e for (e, _) in agg})
    ns = sorted({n for (_, n) in agg})

    # environment_diagnostics.json
    diag = {"envs": {}}
    for e in envs:
        diag["envs"][e] = {}
        for n in ns:
            diag["envs"][e][str(n)] = agg.get((e, n), {})
    diag["n_grid"] = ns
    with open(os.path.join(OUT_DIR, "environment_diagnostics.json"), "w", encoding="utf-8") as fh:
        json.dump(diag, fh, ensure_ascii=False, indent=2)

    # environment_comparison.csv：每 env 一行，N=20/200 的关键压力指标 + 梯度
    cols = ["env", "n20_local_feasible", "n200_local_feasible",
            "n20_demand_cap_ratio", "n200_demand_cap_ratio", "d_demand_cap_ratio",
            "n20_edge_feasible", "n200_edge_feasible",
            "n20_pressure_max", "n200_pressure_max",
            "n20_preinf", "n200_preinf", "n200_total_capacity"]
    with open(os.path.join(OUT_DIR, "environment_comparison.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(cols)
        for e in envs:
            a20 = agg.get((e, 20), {})
            a200 = agg.get((e, 200), {})
            d = (a200.get("demand_capacity_ratio") - a20.get("demand_capacity_ratio")
                 if a20.get("demand_capacity_ratio") is not None and a200.get("demand_capacity_ratio") is not None else None)
            w.writerow([
                e, a20.get("local_feasible_ratio"), a200.get("local_feasible_ratio"),
                a20.get("demand_capacity_ratio"), a200.get("demand_capacity_ratio"), d,
                a20.get("edge_feasible_ratio"), a200.get("edge_feasible_ratio"),
                a20.get("per_server_pressure_max"), a200.get("per_server_pressure_max"),
                a20.get("predecision_infeasible_ratio"), a200.get("predecision_infeasible_ratio"),
                a200.get("total_capacity"),
            ])
    # 打印可读表
    print("=== Layer A 环境比较（3-seed mean；coarse）===")
    hdr = "%-14s | %-9s %-9s | %-10s %-10s %-9s | %-8s | %-9s | %-9s %-9s | %-8s" % (
        "env", "locF@20", "locF@200", "d/c@20", "d/c@200", "d(d/c)", "eF@20", "pMax@20",
        "preinf@20", "preinf@200", "cap@200")
    print(hdr)
    print("-" * len(hdr))
    for e in envs:
        a20 = agg.get((e, 20), {})
        a200 = agg.get((e, 200), {})
        d = (a200.get("demand_capacity_ratio") - a20.get("demand_capacity_ratio")
             if a20.get("demand_capacity_ratio") is not None and a200.get("demand_capacity_ratio") is not None else None)
        print("%-14s | %-9s %-9s | %-10s %-10s %-9s | %-8s | %-9s | %-9s %-9s | %-8s" % (
            e, a20.get("local_feasible_ratio"), a200.get("local_feasible_ratio"),
            a20.get("demand_capacity_ratio"), a200.get("demand_capacity_ratio"), d,
            a20.get("edge_feasible_ratio"), a20.get("per_server_pressure_max"),
            a20.get("predecision_infeasible_ratio"), a200.get("predecision_infeasible_ratio"),
            a200.get("total_capacity")))
    print("\nwritten: environment_diagnostics.json / environment_comparison.csv")
    return 0


if __name__ == "__main__":
    sys.exit(main())
