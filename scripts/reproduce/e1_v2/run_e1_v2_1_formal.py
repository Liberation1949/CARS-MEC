# -*- coding: utf-8 -*-
"""E1-V2-1 Formal runner（用户 2026-08-09 授权；Confirmatory Evaluation）。

正式实验（E1_V2_PROTOCOL_V1 + E1_V2_ENVIRONMENT_SELECTED_V1）：
- 环境：E1_V2_ENVIRONMENT_SELECTED_V1（sf1_vMEDIUM：s_F=1.00 + ν V-MEDIUM）；
- Formal seeds：1101-1110（10 paired；与 E0-V2 601-620 / E3-V2 401-410 /
  E1-V2 pilot 201-203 全互斥；禁止增加/删除/筛选）；
- 网格：N = {20,50,80,110,140,170,200}（nested prefix；Γ_20 ⊂ ... ⊂ Γ_200）；
- 方法：6 主（cars/bpso_rata_la/jtora_adapted/nfa_adapted/reliability_only/
  local_only）+ FOA（boundary diagnostic；不参与综合最佳排名）；
- 统一 MethodRunner（R5 公平边界：同一 scenario/seed/Evaluator/timeout=30s）；
- 正式 CARS = cars_v4 frozen（AADA→RCLA；Contract V4）。

禁止：pilot seeds 混入；调参；改环境/算法；因结果移动网格或 seed。

输出：results/e1_v2/e1_v2_1_formal/（scenarios/ + raw_records.jsonl + summary.json）
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
# 冻结规格（E1_V2_PROTOCOL_V1；用户 2026-08-09 授权 formal）
# ---------------------------------------------------------------------------
FORMAL_SEEDS = [1101, 1102, 1103, 1104, 1105, 1106, 1107, 1108, 1109, 1110]
FORMAL_N = [20, 50, 80, 110, 140, 170, 200]
TIMEOUT = 30.0
S_F = 1.00
PROFILE = "MEDIUM"

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

OUT_DIR = os.path.join(_PROJECT, "results", "e1_v2", "e1_v2_1_formal")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def main() -> int:
    scen_dir = os.path.join(OUT_DIR, "scenarios")
    os.makedirs(scen_dir, exist_ok=True)
    raw_records = []
    start = time.time()
    total = len(FORMAL_SEEDS) * len(FORMAL_N) * len(ALL_METHODS)
    done = 0
    runner = MethodRunner()

    for seed in FORMAL_SEEDS:
        cfg_env = build_e1_v2_environment(seed=seed, n_max=200, s_f=S_F,
                                          fragility_profile=PROFILE)
        for n in FORMAL_N:
            cfg_n = prefix_scenario(cfg_env, n)
            scen_path = os.path.join(scen_dir, "scenario_seed%d_n%d.yaml" % (seed, n))
            # 保存原始配置（含 mode=explicit）：MethodRunner 内部 materialize
            with open(scen_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg_n, fh, allow_unicode=True, sort_keys=False)
            for method_id in ALL_METHODS:
                cfg = load_yaml(CONFIGS[method_id])
                rec = runner.run(
                    method_id=method_id,
                    scenario_cfg_path=scen_path,
                    method_config=cfg,
                    method_seed=cfg["method_seed"],
                    hard_timeout_seconds=TIMEOUT,
                )
                done += 1
                ev_out = rec.get("evaluator_output") or {}
                sm = ev_out.get("system_metrics", {}) if ev_out else {}
                rec_compact = {
                    "seed": seed,
                    "n": n,
                    "method_id": method_id,
                    "method_status": rec["method_status"],
                    "evaluator_status": rec.get("evaluator_status"),
                    "timed_out": rec.get("runtime_censored", False),
                    "tssr": sm.get("tssr"),
                    "rbar_eff": sm.get("mean_effective_reliability"),
                    "ubar_eff": sm.get("mean_effective_utility"),
                    "v_r": sm.get("reliability_violation_rate"),
                    # 2026-08-09 用户批准：efficiency 主口径改为算法执行时间 method_runtime_ms；
                    # total_wall_time_ms（端到端，含实验框架固定开销）保留为补充参考。
                    "method_runtime_ms": rec.get("method_runtime_ms"),
                    "total_wall_time_ms": rec.get("total_wall_time_ms"),
                    "canonical_hash": rec.get("reproducibility", {}).get("canonical_hash"),
                }
                raw_records.append(rec_compact)
                print("[%3d/%d] seed=%d n=%d %s -> %s tssr=%s" % (
                    done, total, seed, n, method_id, rec["method_status"],
                    rec_compact["tssr"]))

    elapsed = time.time() - start
    summary = {
        "stage": "E1-V2-1 formal",
        "status": "FORMAL",
        "environment": "E1_V2_ENVIRONMENT_SELECTED_V1 (sf1_vMEDIUM)",
        "seeds": FORMAL_SEEDS,
        "n_grid": FORMAL_N,
        "methods": {"main": MAIN_METHODS, "diagnostic": DIAGNOSTIC_METHODS},
        "total_runs": len(raw_records),
        "timeout_count": sum(1 for r in raw_records if r["timed_out"]),
        "method_error_count": sum(1 for r in raw_records if r["method_status"] == "METHOD_ERROR"),
        "elapsed_seconds": round(elapsed, 1),
    }
    raw_path = os.path.join(OUT_DIR, "raw_records.jsonl")
    with open(raw_path, "w", encoding="utf-8") as fh:
        for r in raw_records:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT_DIR, "summary.json"), "w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    print("written:", raw_path)
    print("summary:", summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
