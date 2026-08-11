# -*- coding: utf-8 -*-
"""E1-3 场景重建脚本（公开仓库复现入口；source-faithful）。

复用 scripts/reproduce/e1_v2/build_e1_v2_environment.py 的确定性场景构建能力
（E1-V2-0 冻结环境：s_f=1.00、fragility_profile=MEDIUM、M=8、N=200、无 deadline），
为 E1-3 Baseline Budget-Sensitivity 重建与正式实验语义一致的确定性场景，
输出 results/e1_3_budget/scenarios/scenario_seed{seed}_n200.yaml。

场景内容与原 E1-V2-1 formal 场景一致（同一确定性生成器与生成顺序；本脚本
不创建任何新的场景生成规则）。默认重建 formal seeds 1101-1110 与 pilot
seeds 201-203 的 N=200 场景。

用法：
  python scripts/reproduce/e1_3_budget/build_e1_3_budget_scenarios.py
"""
from __future__ import annotations

import argparse
import os
import sys

import yaml

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))

from build_e1_v2_environment import (  # noqa: E402
    build_e1_v2_environment,
    prefix_scenario,
)

N = 200
M = 8
S_F = 1.0
FRAGILITY_PROFILE = "MEDIUM"
FORMAL_SEEDS = [1101, 1102, 1103, 1104, 1105, 1106, 1107, 1108, 1109, 1110]
PILOT_SEEDS = [201, 202, 203]
OUT_DIR = os.path.join(_PROJECT, "results", "e1_3_budget", "scenarios")


def build_scenario_dict(seed: int) -> dict:
    """生成 seed 的 N=200 场景 dict（确定性；与 E1-V2-1 formal 场景同一生成器）。"""
    cfg = build_e1_v2_environment(
        seed=seed, n_max=N, m=M, fragility_profile=FRAGILITY_PROFILE, s_f=S_F)
    return prefix_scenario(cfg, N)


def main() -> int:
    ap = argparse.ArgumentParser(description="E1-3 budget-sensitivity 场景重建")
    ap.add_argument("--seeds", type=int, nargs="*", default=None,
                    help="指定 seeds（默认 formal 1101-1110 + pilot 201-203）")
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    seeds = args.seeds if args.seeds else FORMAL_SEEDS + PILOT_SEEDS
    out_dir = args.out_dir or OUT_DIR
    os.makedirs(out_dir, exist_ok=True)
    for seed in sorted(set(seeds)):
        scen = build_scenario_dict(seed)
        path = os.path.join(out_dir, "scenario_seed%d_n%d.yaml" % (seed, N))
        with open(path, "w", encoding="utf-8") as fh:
            yaml.safe_dump(scen, fh, allow_unicode=True, sort_keys=False)
        print("written:", os.path.relpath(path, _PROJECT))
    print("scenarios done: %d seeds -> %s" % (len(set(seeds)), out_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
