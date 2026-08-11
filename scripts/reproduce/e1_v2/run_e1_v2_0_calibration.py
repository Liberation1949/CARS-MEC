# -*- coding: utf-8 -*-
"""E1-V2-0 环境校准 runner（Environment Calibration and Freeze）。

阶段：E1-V2-0（用户 2026-08-09 授权；result-neutral, algorithm-neutral）。

阶段：
  --phase coarse   9 候选环境 × 3 anchors {20,110,200} × 3 calibration seeds
                   {701,702,703} 只跑 Layer A 方法无关诊断（决策前）；
  --phase layerb  对指定候选环境（--envs sf:PROFILE,...）跑 Layer B sanity
                   （4 方法：cars/bpso_rata_la/nfa_adapted/reliability_only；
                   CARS 排名不入评分）；
  --phase confirm 对最终候选（≤2）环境跑 confirm seeds {704..708} × 完整
                   N-grid {20,50,80,110,140,170,200}（Layer A + Layer B sanity）。

禁止：formal seeds 1101-1110；调参；改算法；改 Evaluator；按 CARS 排名选环境；
扫描 lambda_j。

Layer A 诊断为 CALIBRATION_ONLY_DIAGNOSTIC（不进 Evaluator 正式指标），全部
复用 DerivedState 决策前量。

输出：results/e1_v2/e1_v2_0_calibration/calibration_raw.jsonl
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
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))

from build_e1_v2_environment import (  # noqa: E402
    ALLOWED_S_F,
    FRAGILITY_PROFILES,
    build_e1_v2_environment,
    prefix_scenario,
)
from cars.runner.runner import MethodRunner  # noqa: E402
from cars.simulator.derived_state import DerivedState  # noqa: E402
from cars.simulator.scenario_materializer import materialize  # noqa: E402

CAL_SEEDS = [701, 702, 703]
CONFIRM_SEEDS = [704, 705, 706, 707, 708]
COARSE_ANCHORS = [20, 110, 200]
CONFIRM_N_GRID = [20, 50, 80, 110, 140, 170, 200]
TIMEOUT = 30.0

LAYER_B_METHODS = ["cars", "bpso_rata_la", "nfa_adapted", "reliability_only"]
CONFIGS = {
    "cars": os.path.join(_PROJECT, "configs", "cars_v4", "cars_frozen_v4.yaml"),
    "bpso_rata_la": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml"),
    "nfa_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml"),
    "reliability_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "reliability_only_frozen.yaml"),
}

OUT_DIR = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_0_calibration")
RAW_PATH = os.path.join(OUT_DIR, "calibration_raw.jsonl")


def env_id(s_f: float, profile: str) -> str:
    return "sf%s_v%s" % (("%.2f" % s_f).rstrip("0").rstrip("."), profile)


def all_candidate_envs():
    envs = []
    for s_f in ALLOWED_S_F:
        for profile in sorted(FRAGILITY_PROFILES):
            envs.append((env_id(s_f, profile), s_f, profile))
    return envs


# ---------------------------------------------------------------------------
# Layer A：方法无关环境诊断（CALIBRATION_ONLY_DIAGNOSTIC；全部决策前）
# ---------------------------------------------------------------------------

def layer_a_diagnostics(scen, derived) -> dict:
    n = len(derived.task_ids)
    m = len(derived.server_ids)
    b_loc = [tl["b_loc"] for tl in derived.task_local]
    local_feasible = sum(b_loc) / n

    edge_feasible_total = 0
    positive_floors = []
    per_task_min_floor = []
    server_pressure = [0.0] * m
    for i in range(n):
        min_f = None
        for j in range(m):
            ls = derived.link(i, j)
            if ls is None or ls["e_rec"] != 1:
                continue
            edge_feasible_total += 1
            ell = ls["ell_R"]
            if ell > 0.0:
                positive_floors.append(ell)
            server_pressure[j] += ell
            if min_f is None or ell < min_f:
                min_f = ell
        if min_f is not None:
            per_task_min_floor.append(min_f)

    edge_feasible_ratio = edge_feasible_total / (n * m) if n * m else 0.0
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

    return {
        "local_feasible_ratio": round(local_feasible, 6),
        "edge_feasible_ratio": round(edge_feasible_ratio, 6),
        "floor_positive_ratio": round(positive_floor_ratio, 6),
        "floor_min": floor_min,
        "floor_median": round(floor_median, 3) if floor_median is not None else None,
        "floor_max": floor_max,
        "aggregate_min_floor_demand": round(aggregate_min_floor_demand, 3),
        "total_capacity": round(total_capacity, 3),
        "demand_capacity_ratio": round(demand_capacity_ratio, 6),
        "per_server_pressure_max": round(max(per_server_pressure_norm), 6),
        "per_server_pressure_mean": round(mean_p, 6),
        "pressure_dispersion": round(pressure_dispersion, 6),
        "predecision_infeasible_ratio": round(len(derived.predecision_infeasible) / n, 6),
    }


# ---------------------------------------------------------------------------
# 生成 + 保存场景
# ---------------------------------------------------------------------------

def make_scenario_file(s_f, profile, seed, n, scen_dir):
    cfg = build_e1_v2_environment(seed=seed, n_max=200, s_f=s_f, fragility_profile=profile)
    cfg_n = prefix_scenario(cfg, n)
    path = os.path.join(scen_dir, "scenario_%s_seed%d_n%d.yaml" % (env_id(s_f, profile), seed, n))
    with open(path, "w", encoding="utf-8") as fh:
        yaml.safe_dump(cfg_n, fh, allow_unicode=True, sort_keys=False)
    return path


def run_layer_a(s_f, profile, seed, n, scen_dir, raw_writer):
    cfg = build_e1_v2_environment(seed=seed, n_max=200, s_f=s_f, fragility_profile=profile)
    cfg_n = prefix_scenario(cfg, n)
    scen = materialize(cfg_n)
    derived = DerivedState(scen)
    diag = layer_a_diagnostics(scen, derived)
    rec = {"phase": "coarse_layerA", "env": env_id(s_f, profile), "s_f": s_f,
           "profile": profile, "seed": seed, "n": n, "kind": "layer_a",
           **diag}
    raw_writer(rec)
    return rec


def run_layer_b(s_f, profile, seed, n, scen_dir, raw_writer):
    cfg = build_e1_v2_environment(seed=seed, n_max=200, s_f=s_f, fragility_profile=profile)
    cfg_n = prefix_scenario(cfg, n)
    path = make_scenario_file(s_f, profile, seed, n, scen_dir)
    runner = MethodRunner()
    out = {"phase": "layerB", "env": env_id(s_f, profile), "s_f": s_f,
           "profile": profile, "seed": seed, "n": n, "kind": "layer_b"}
    for mid in LAYER_B_METHODS:
        mcfg = load_yaml(CONFIGS[mid])
        rec = runner.run(method_id=mid, scenario_cfg_path=path, method_config=mcfg,
                         method_seed=mcfg["method_seed"], hard_timeout_seconds=TIMEOUT)
        tssr = (rec.get("evaluator_output") or {}).get("system_metrics", {}).get("tssr")
        out["%s_status" % mid] = rec["method_status"]
        out["%s_tssr" % mid] = tssr
        out["%s_timeout" % mid] = rec.get("runtime_censored", False)
        out["%s_wall_ms" % mid] = rec.get("total_wall_time_ms")
    raw_writer(out)
    return out


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> int:
    ap = argparse.ArgumentParser(description="E1-V2-0 环境校准 runner")
    ap.add_argument("--phase", choices=["coarse", "layerb", "confirm"], required=True)
    ap.add_argument("--envs", default=None, help="layerb/confirm 用的候选环境，逗号分隔 env_id")
    ap.add_argument("--seeds", default=None, help="覆盖 seeds（逗号分隔）")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    scen_dir = os.path.join(OUT_DIR, "scenarios")
    os.makedirs(scen_dir, exist_ok=True)

    raw_fh = open(RAW_PATH, "a", encoding="utf-8")

    def writer(rec):
        raw_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    t0 = time.time()
    if args.phase == "coarse":
        envs = all_candidate_envs()
        for s_f, profile in [(e[1], e[2]) for e in envs]:
            for seed in CAL_SEEDS:
                for n in COARSE_ANCHORS:
                    run_layer_a(s_f, profile, seed, n, scen_dir, writer)
                    print("coarse", env_id(s_f, profile), "seed", seed, "n", n)
    elif args.phase == "layerb":
        envs = [e.strip() for e in args.envs.split(",")] if args.envs else []
        seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else CAL_SEEDS
        for eid in envs:
            sf_str, prof = eid[2:].split("_v")
            s_f = float(sf_str)
            for seed in seeds:
                for n in COARSE_ANCHORS:
                    run_layer_b(s_f, prof, seed, n, scen_dir, writer)
                    print("layerB", eid, "seed", seed, "n", n)
    elif args.phase == "confirm":
        envs = [e.strip() for e in args.envs.split(",")] if args.envs else []
        seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else CONFIRM_SEEDS
        for eid in envs:
            sf_str, prof = eid[2:].split("_v")
            s_f = float(sf_str)
            for seed in seeds:
                for n in CONFIRM_N_GRID:
                    run_layer_a(s_f, prof, seed, n, scen_dir, writer)
                    run_layer_b(s_f, prof, seed, n, scen_dir, writer)
                    print("confirm", eid, "seed", seed, "n", n)
    raw_fh.close()
    print("elapsed %.1fs" % (time.time() - t0))
    print("raw:", RAW_PATH)
    return 0


if __name__ == "__main__":
    sys.exit(main())
