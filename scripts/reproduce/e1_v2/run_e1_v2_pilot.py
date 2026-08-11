# -*- coding: utf-8 -*-
"""E1-V2 Pilot runner（CR-CARS-PROMOTION-E1 + E1 Freeze/Pilot；NOT_FORMAL）。

范围（用户 2026-08-09 冻结）：pilot seeds 201-203 × 代表点 N∈{20,80,200} ×
6 主方法（cars/bpso_rata_la/jtora_adapted/nfa_adapted/reliability_only/
local_only）+ FOA 诊断 = 63 runs。

目的：
- 预算/运行性检查（shared timeout=30s 不超、无 METHOD_ERROR、决策合法性）；
- 环境梯度 sanity check（多数方法 TSSR 随 N 下降、压力区间可辨识）；
- 6 方法 + FOA 均通过统一 MethodRunner（R5 公平边界：同一 scenario/seed/
  Evaluator/timeout）；
- 正式 CARS（cars_v4 frozen，AADA→RCLA）与六 Baseline 同框架运行。

禁止：访问 formal seeds 1101-1110；调参；改环境；改算法；因 pilot 结果移动
formal 网格/代表点。

输出：results/e1_v2/e1_v2_1_pilot/（raw_records.jsonl + summary.json）
"""
from __future__ import annotations

import json
import os
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))

from build_e1_v2_environment import build_e1_v2_environment, prefix_scenario  # noqa: E402
from cars.runner.runner import MethodRunner  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结规格（E1-V2 合同；用户 2026-08-09）
# ---------------------------------------------------------------------------
PILOT_SEEDS = [201, 202, 203]
PILOT_N = [20, 80, 200]
TIMEOUT = 30.0

MAIN_METHODS = [
    "cars",
    "bpso_rata_la",
    "jtora_adapted",
    "nfa_adapted",
    "reliability_only",
    "local_only",
]
DIAGNOSTIC_METHODS = ["foa"]
ALL_METHODS = MAIN_METHODS + DIAGNOSTIC_METHODS

CONFIGS = {
    "cars": os.path.join(_PROJECT, "configs", "cars_v4", "cars_frozen_v4.yaml"),
    "bpso_rata_la": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "bpso_frozen.yaml"),
    "jtora_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "jtora_frozen.yaml"),
    "nfa_adapted": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "nfa_frozen.yaml"),
    "reliability_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "reliability_only_frozen.yaml"),
    "local_only": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "local_only_frozen.yaml"),
    "foa": os.path.join(_PROJECT, "configs", "r6", "frozen_method_configs", "foa_frozen.yaml"),
}


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def run_one(method_id: str, cfg: dict, scen_path: str, timeout: float) -> dict:
    runner = MethodRunner()
    rec = runner.run(
        method_id=method_id,
        scenario_cfg_path=scen_path,
        method_config=cfg,
        method_seed=cfg["method_seed"],
        hard_timeout_seconds=timeout,
    )
    return rec


def main() -> int:
    out_dir = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_1_pilot")
    scen_dir = os.path.join(out_dir, "scenarios")
    os.makedirs(scen_dir, exist_ok=True)

    raw_records = []
    start = time.time()
    total = len(PILOT_SEEDS) * len(PILOT_N) * len(ALL_METHODS)
    done = 0

    for seed in PILOT_SEEDS:
        cfg_env = build_e1_v2_environment(seed=seed, n_max=200)
        for n in PILOT_N:
            cfg_n = prefix_scenario(cfg_env, n)
            # 保存原始配置（含 mode=explicit）：MethodRunner 内部 materialize
            # （物化输出无 mode，不可再被 materialize_from_file 读取）
            scen_path = os.path.join(scen_dir, "scenario_seed%d_n%d.yaml" % (seed, n))
            with open(scen_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg_n, fh, allow_unicode=True, sort_keys=False)
            for method_id in ALL_METHODS:
                cfg = load_yaml(CONFIGS[method_id])
                rec = run_one(method_id, cfg, scen_path, TIMEOUT)
                done += 1
                rec_compact = {
                    "seed": seed,
                    "n": n,
                    "method_id": method_id,
                    "method_status": rec["method_status"],
                    "evaluator_status": rec.get("evaluator_status"),
                    "timed_out": rec.get("runtime_censored", False),
                    "tssr": (rec.get("evaluator_output") or {}).get("system_metrics", {}).get("tssr"),
                    "rbar_eff": (rec.get("evaluator_output") or {}).get("system_metrics", {}).get("mean_effective_reliability"),
                    "ubar_eff": (rec.get("evaluator_output") or {}).get("system_metrics", {}).get("mean_effective_utility"),
                    "total_wall_time_ms": rec.get("total_wall_time_ms"),
                    "decision_x": rec.get("decision", {}).get("offloading_decision"),
                    "canonical_hash": rec.get("reproducibility", {}).get("canonical_hash"),
                }
                raw_records.append(rec_compact)
                print("[%3d/%d] seed=%d n=%d %s -> %s tssr=%s" % (
                    done, total, seed, n, method_id, rec["method_status"],
                    rec_compact["tssr"]))

    elapsed = time.time() - start
    summary = {
        "stage": "E1-V2-1 pilot",
        "status": "NOT_FORMAL",
        "seeds": PILOT_SEEDS,
        "n_points": PILOT_N,
        "methods": {"main": MAIN_METHODS, "diagnostic": DIAGNOSTIC_METHODS},
        "total_runs": len(raw_records),
        "timeout_count": sum(1 for r in raw_records if r["timed_out"]),
        "method_error_count": sum(1 for r in raw_records if r["method_status"] == "METHOD_ERROR"),
        "elapsed_seconds": round(elapsed, 1),
    }
    raw_path = os.path.join(out_dir, "raw_records.jsonl")
    with open(raw_path, "w", encoding="utf-8") as fh:
        for r in raw_records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("written:", raw_path)
    print("summary:", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
