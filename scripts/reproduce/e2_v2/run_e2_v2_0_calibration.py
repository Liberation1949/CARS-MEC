# -*- coding: utf-8 -*-
"""E2-V2-0 环境校准 runner（Computational Heterogeneity Environment Calibration）。

阶段：E2-V2-0（用户 2026-08-09 授权；result-neutral, algorithm-neutral）。

阶段：
  --phase layer_a   N{140,170,200} × CV_F{0,0.3,0.6,0.9,1.2} × seeds{1201,1202,1203}
                    = 45 次决策前方法无关诊断（复用 DerivedState）；
  --phase layerb    对 Layer A 筛选出的 ≤2 个 N 候选 × CV_F 全档 × seeds
                    {1201,1202,1203} × 4 方法 {cars,bpso_rata_la,nfa_adapted,
                    reliability_only}（CARS 排名不入评分）；
  --phase ext15     预注册扩展探针：仅当 CV=1.2 明显过轻（协议 §13 三条件）才运行
                    CV_F=1.5（保留全部结果）。

禁止：formal seeds 2101-2110（检测到即拒绝）；调参；改算法；改 Evaluator；
按 CARS 排名选环境；扫描 lambda_j。

Layer A 诊断为 CALIBRATION_ONLY_DIAGNOSTIC（不进 Evaluator 正式指标）。

输出：results/e2_v2/e2_v2_0_calibration/calibration_raw.jsonl
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e2_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))

from build_e2_v2_environment import (  # noqa: E402
    ALLOWED_CV_F_EXTENSION,
    ALLOWED_CV_F_PRIMARY,
    build_e2_v2_environment,
)
from cars.runner.runner import MethodRunner  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

# 冻结 seeds（协议 §6）
CAL_SEEDS = [1201, 1202, 1203]
CAL_SEEDS_ALL = [1201, 1202, 1203, 1204, 1205]
FORMAL_SEEDS = [2101, 2102, 2103, 2104, 2105, 2106, 2107, 2108, 2109, 2110]

N_GRID = [140, 170, 200]
CV_GRID = [0.0, 0.3, 0.6, 0.9, 1.2]
TIMEOUT = 30.0

LAYER_B_METHODS = ["cars", "bpso_rata_la", "nfa_adapted", "reliability_only"]
CONFIGS = {
    "cars": os.path.join(_PROJECT, "configs", "cars_v4", "cars_frozen_v4.yaml"),
    "bpso_rata_la": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml"),
    "nfa_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml"),
    "reliability_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "reliability_only_frozen.yaml"),
}

OUT_DIR = os.path.join(_PROJECT, "results", "e2_v2", "e2_v2_0_calibration")
RAW_PATH = os.path.join(OUT_DIR, "calibration_raw.jsonl")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def guard_formal_seed(seed: int):
    """formal seeds 2101-2110 零访问（协议 §6）：任何脚本检测到必须拒绝。"""
    if seed in FORMAL_SEEDS:
        raise SystemExit(
            "REFUSED: formal seed %d accessed during E2-V2-0 calibration" % seed)


def cv_label(cv):
    return ("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0"


# ---------------------------------------------------------------------------
# Layer A：方法无关环境诊断（CALIBRATION_ONLY_DIAGNOSTIC；全部决策前）
# ---------------------------------------------------------------------------

def layer_a_diagnostics(scen, derived, meta: dict) -> dict:
    n = len(derived.task_ids)
    m = len(derived.server_ids)
    b_loc = [tl["b_loc"] for tl in derived.task_local]
    local_feasible = sum(b_loc) / n

    edge_feasible_total = 0
    positive_floors = []
    per_task_min_floor = []
    server_pressure = [0.0] * m
    tasks_with_feasible_edge = 0
    for i in range(n):
        min_f = None
        has_feasible = False
        for j in range(m):
            ls = derived.link(i, j)
            if ls is None or ls["e_rec"] != 1:
                continue
            has_feasible = True
            edge_feasible_total += 1
            ell = ls["ell_R"]
            if ell > 0.0:
                positive_floors.append(ell)
            server_pressure[j] += ell
            if min_f is None or ell < min_f:
                min_f = ell
        if min_f is not None:
            per_task_min_floor.append(min_f)
        if has_feasible:
            tasks_with_feasible_edge += 1

    edge_feasible_ratio = edge_feasible_total / (n * m) if n * m else 0.0
    tasks_feasible_edge_ratio = tasks_with_feasible_edge / n if n else 0.0
    aggregate_min_floor_demand = sum(per_task_min_floor)
    total_capacity = sum(s["F_j"] for s in derived.server_state)
    demand_capacity_ratio = aggregate_min_floor_demand / total_capacity if total_capacity else 0.0

    F_j = [s["F_j"] for s in derived.server_state]
    per_server_pressure_norm = [
        server_pressure[j] / F_j[j] if F_j[j] > 0.0 else 0.0 for j in range(m)
    ]
    mean_p = sum(per_server_pressure_norm) / m if m else 0.0
    var_p = sum((x - mean_p) ** 2 for x in per_server_pressure_norm) / m if m else 0.0
    pressure_dispersion = math.sqrt(var_p)

    positive_floor_ratio = len(positive_floors) / edge_feasible_total if edge_feasible_total else 0.0
    floor_min = min(positive_floors) if positive_floors else None
    sorted_f = sorted(positive_floors)
    floor_median = sorted_f[len(sorted_f) // 2] if sorted_f else None
    floor_max = sorted_f[-1] if sorted_f else None

    mu_F = sum(F_j) / m if m else 0.0
    std_F = math.sqrt(sum((x - mu_F) ** 2 for x in F_j) / m) if m else 0.0
    hhi = sum((x / total_capacity) ** 2 for x in F_j) if total_capacity else 0.0
    top2 = sum(sorted(F_j, reverse=True)[:2]) / total_capacity if total_capacity else 0.0
    max_min_ratio = (max(F_j) / min(F_j)) if min(F_j) > 0 else None

    return {
        "n": n,
        "m": m,
        "F_total": round(total_capacity, 6),
        "mean_F": round(mu_F, 6),
        "std_F": round(std_F, 6),
        "CV_F_target": meta["cv_f_target"],
        "CV_F_realized": round(meta["cv_f_realized"], 6),
        "theta": round(meta["theta"], 6),
        "min_F": round(min(F_j), 6),
        "max_F": round(max(F_j), 6),
        "max_min_ratio": round(max_min_ratio, 6) if max_min_ratio is not None else None,
        "capacity_HHI": round(hhi, 6),
        "top2_capacity_share": round(top2, 6),
        "local_feasible_ratio": round(local_feasible, 6),
        "edge_feasible_ratio": round(edge_feasible_ratio, 6),
        "tasks_feasible_edge_ratio": round(tasks_feasible_edge_ratio, 6),
        "floor_positive_ratio": round(positive_floor_ratio, 6),
        "floor_min": floor_min,
        "floor_median": round(floor_median, 3) if floor_median is not None else None,
        "floor_max": floor_max,
        "aggregate_min_floor_demand": round(aggregate_min_floor_demand, 3),
        "demand_capacity_ratio": round(demand_capacity_ratio, 6),
        "per_server_pressure_max": round(max(per_server_pressure_norm), 6),
        "per_server_pressure_mean": round(mean_p, 6),
        "pressure_dispersion": round(pressure_dispersion, 6),
        "predecision_infeasible_ratio": round(len(derived.predecision_infeasible) / n, 6),
    }


def build_and_diag(seed, cv_f, n):
    """生成 E2 场景（n_max=n）+ materialize + DerivedState + Layer A 诊断。"""
    guard_formal_seed(seed)
    out = build_e2_v2_environment(seed=seed, cv_f_target=cv_f, n_max=n)
    cfg = out["scenario_cfg"]
    scen = materialize(cfg)
    derived = DerivedState(scen)
    diag = layer_a_diagnostics(scen, derived, out["metadata"])
    return cfg, diag


def run_layer_a(seed, cv_f, n, raw_writer):
    cfg, diag = build_and_diag(seed, cv_f, n)
    rec = {"phase": "layerA", "kind": "layer_a", "seed": seed, "n": n,
           "cv_f": cv_f, **diag}
    raw_writer(rec)
    return rec


def run_layer_b(seed, cv_f, n, scen_dir, raw_writer):
    guard_formal_seed(seed)
    out = build_e2_v2_environment(seed=seed, cv_f_target=cv_f, n_max=n)
    cfg = out["scenario_cfg"]
    path = os.path.join(scen_dir, "scenario_cv%s_seed%d_n%d.yaml" % (
        cv_label(cv_f), seed, n))
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
    runner = MethodRunner()
    o = {"phase": "layerB", "kind": "layer_b", "seed": seed, "n": n,
         "cv_f": cv_f, "scenario": os.path.basename(path)}
    for mid in LAYER_B_METHODS:
        mcfg = load_yaml(CONFIGS[mid])
        rec = runner.run(method_id=mid, scenario_cfg_path=path, method_config=mcfg,
                         method_seed=mcfg["method_seed"], hard_timeout_seconds=TIMEOUT)
        ev = rec.get("evaluator_output") or {}
        sm = ev.get("system_metrics", {})
        o["%s_status" % mid] = rec["method_status"]
        o["%s_tssr" % mid] = sm.get("tssr")
        o["%s_rbar" % mid] = sm.get("mean_effective_reliability")
        o["%s_ubar" % mid] = sm.get("mean_effective_utility")
        o["%s_vr" % mid] = sm.get("reliability_violation_rate")
        o["%s_runtime_ms" % mid] = rec.get("method_runtime_ms")
        o["%s_timeout" % mid] = rec.get("runtime_censored", False)
    raw_writer(o)
    return o


def main() -> int:
    ap = argparse.ArgumentParser(description="E2-V2-0 环境校准 runner")
    ap.add_argument("--phase", choices=["layer_a", "layerb", "ext15"], required=True)
    ap.add_argument("--ns", default=None, help="layerb 的 N 候选（逗号分隔）")
    ap.add_argument("--seeds", default=None, help="覆盖 seeds（逗号分隔）")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    scen_dir = os.path.join(OUT_DIR, "scenarios")
    os.makedirs(scen_dir, exist_ok=True)

    raw_fh = open(RAW_PATH, "a", encoding="utf-8")

    def writer(rec):
        raw_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else CAL_SEEDS
    for s in seeds:
        guard_formal_seed(s)

    t0 = time.time()
    if args.phase == "layer_a":
        for seed in seeds:
            for n in N_GRID:
                for cv in CV_GRID:
                    run_layer_a(seed, cv, n, writer)
                    print("layerA seed", seed, "n", n, "cv", cv)
    elif args.phase == "layerb":
        ns = [int(x) for x in args.ns.split(",")] if args.ns else [170]
        for seed in seeds:
            for n in ns:
                for cv in CV_GRID:
                    run_layer_b(seed, cv, n, scen_dir, writer)
                    print("layerB seed", seed, "n", n, "cv", cv)
    elif args.phase == "ext15":
        # 预注册扩展探针：仅按协议 §13 三条件手动确认后调用；结果全部保留
        for seed in seeds:
            for n in N_GRID:
                run_layer_a(seed, 1.5, n, writer)
                run_layer_b(seed, 1.5, n, scen_dir, writer)
                print("ext15 seed", seed, "n", n)
    raw_fh.close()
    print("elapsed %.1fs" % (time.time() - t0))
    print("raw:", RAW_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
