# -*- coding: utf-8 -*-
"""E2-V2-1 Formal runner（E2 正式主实验；用户授权后方可运行 formal seeds）。

正式实验（E2_V2_FORMAL_PROTOCOL_V1 + E2_V2_ENVIRONMENT_SELECTED_V1）：
- 环境：E2_V2_ENVIRONMENT_SELECTED_V1（N=170/M=8/F_total=101000/s_F=1.0/
  CV_F{0,0.3,0.6,0.9,1.2}）；
- Formal seeds：2101-2110（10 paired；与 E1 1101-1110 / E0-V2 601-620 /
  E3-V2 401-410 / pilot 201-203 / E2 calib 1201-1205 全互斥）；
- 网格：CV_F = {0,0.3,0.6,0.9,1.2}（唯一自变量；同 seed 跨 CV_F 任务/设备/信道/
  λ_j/R_min 全不变，仅 F_j 改变）；
- 方法：6 主（cars/bpso_rata_la/jtora_adapted/nfa_adapted/reliability_only/
  local_only）+ FOA（boundary diagnostic；不参与综合最佳排名）；
- 统一 MethodRunner（R5 公平边界：同一 scenario/seed/Evaluator/timeout=30s）；
- 正式 CARS = cars_v4 frozen（AADA→RCLA；Contract V4）。

**授权守卫**：formal seeds 2101-2110 必须显式传 --authorize-formal-seeds 才允许运行；
否则（含 --seeds 传入 formal seed）立即 SystemExit。正式运行须用户明确授权
（AUTHORIZED_TO_START_E2_V2_1_FORMAL = NO 当前）。

禁止：pilot seeds 混入；调参；改环境/算法；因结果移动网格或 seed。

输出：results/e2_v2/e2_v2_1_formal/（scenarios/ + raw_records.jsonl）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e2_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))

from build_e2_v2_environment import build_e2_v2_environment  # noqa: E402
from cars.runner.runner import MethodRunner  # noqa: E402

# ---------------------------------------------------------------------------
# 冻结规格（E2_V2_FORMAL_PROTOCOL_V1；E2-V2-0 冻结环境）
# ---------------------------------------------------------------------------
FORMAL_SEEDS = [2101, 2102, 2103, 2104, 2105, 2106, 2107, 2108, 2109, 2110]
CV_GRID = [0.0, 0.3, 0.6, 0.9, 1.2]
N_FORMAL = 170
TIMEOUT = 30.0
S_F = 1.0
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

OUT_DIR = os.path.join(_PROJECT, "results", "e2_v2", "e2_v2_1_formal")


def load_yaml(path):
    with open(path, "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def guard_authorization(seeds, authorize_formal: bool):
    """formal seeds 2101-2110 授权守卫（协议 §10）。"""
    formal = [s for s in seeds if s in FORMAL_SEEDS]
    if formal and not authorize_formal:
        raise SystemExit(
            "REFUSED: E2-V2-1 formal seeds %s require --authorize-formal-seeds "
            "(user authorization; AUTHORIZED_TO_START_E2_V2_1_FORMAL = NO)"
            % sorted(formal))


def main() -> int:
    ap = argparse.ArgumentParser(description="E2-V2-1 Formal runner")
    ap.add_argument("--authorize-formal-seeds", action="store_true",
                    help="显式授权运行 formal seeds 2101-2110（须用户授权）")
    ap.add_argument("--seeds", default=None, help="覆盖 seeds（逗号分隔；仅 smoke/pilot 用）")
    ap.add_argument("--cv-f", default=None, help="覆盖 CV_F（逗号分隔；仅 smoke/pilot 用）")
    ap.add_argument("--out-dir", default=None, help="覆盖输出目录（smoke 用独立目录）")
    args = ap.parse_args()

    seeds = [int(x) for x in args.seeds.split(",")] if args.seeds else FORMAL_SEEDS
    cvs = [float(x) for x in args.cv_f.split(",")] if args.cv_f else CV_GRID
    guard_authorization(seeds, args.authorize_formal_seeds)

    out_dir = args.out_dir or OUT_DIR
    scen_dir = os.path.join(out_dir, "scenarios")
    os.makedirs(scen_dir, exist_ok=True)
    raw_path = os.path.join(out_dir, "raw_records.jsonl")
    raw_fh = open(raw_path, "a", encoding="utf-8")

    start = time.time()
    total = len(seeds) * len(cvs) * len(ALL_METHODS)
    done = 0
    runner = MethodRunner()

    for seed in seeds:
        for cv in cvs:
            out = build_e2_v2_environment(seed=seed, cv_f_target=cv, n_max=N_FORMAL)
            cfg = out["scenario_cfg"]
            scen_path = os.path.join(scen_dir, "scenario_cv%s_seed%d_n%d.yaml" % (
                ("%.1f" % cv).rstrip("0").rstrip(".") if cv != 0.0 else "0",
                seed, N_FORMAL))
            with open(scen_path, "w", encoding="utf-8") as fh:
                yaml.safe_dump(cfg, fh, allow_unicode=True, sort_keys=False)
            for method_id in ALL_METHODS:
                mcfg = load_yaml(CONFIGS[method_id])
                rec = runner.run(method_id=method_id, scenario_cfg_path=scen_path,
                                 method_config=mcfg, method_seed=mcfg["method_seed"],
                                 hard_timeout_seconds=TIMEOUT)
                done += 1
                ev_out = rec.get("evaluator_output") or {}
                sm = ev_out.get("system_metrics", {}) if ev_out else {}
                rec_compact = {
                    "seed": seed,
                    "cv_f": cv,
                    "n": N_FORMAL,
                    "method_id": method_id,
                    "method_status": rec["method_status"],
                    "evaluator_status": rec.get("evaluator_status"),
                    "timed_out": rec.get("runtime_censored", False),
                    "tssr": sm.get("tssr"),
                    "rbar_eff": sm.get("mean_effective_reliability"),
                    "ubar_eff": sm.get("mean_effective_utility"),
                    "v_r": sm.get("reliability_violation_rate"),
                    "method_runtime_ms": rec.get("method_runtime_ms"),
                    "total_wall_time_ms": rec.get("total_wall_time_ms"),
                    "canonical_hash": rec.get("reproducibility", {}).get("canonical_hash"),
                }
                raw_fh.write(json.dumps(rec_compact, ensure_ascii=False) + "\n")
                print("[%3d/%d] seed=%d cv=%s %s -> %s tssr=%s" % (
                    done, total, seed, ("%.1f" % cv), method_id,
                    rec["method_status"], rec_compact["tssr"]))
    raw_fh.close()
    print("elapsed %.1fs" % (time.time() - start))
    print("raw:", raw_path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
