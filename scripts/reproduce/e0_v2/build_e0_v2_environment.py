# -*- coding: utf-8 -*-
"""E0-V2 无 deadline 负载扫描环境生成器（E0-V2-0 冻结；新版 E0 现象识别实验）。

背景（2026-08-09）：
- 新版 E0 = 现象识别实验（用户 2026-08-09 设计）：唯一自变量任务数 N，
  M=8 台异构服务器全连接；沿用已冻结并用于 E3 的同一 Scenario generator/config；
- 嵌套任务设计：每个 seed 一次生成 N_max，小规模是大规模的任务前缀/固定子集：
    Gamma_20 ⊂ Gamma_50 ⊂ ... ⊂ Gamma_Nmax
  服务器、信道、任务属性采样规则一致（只依赖 seed）——同 seed 下 N↑ 是真正
  "增加 workload"，不是"换了一批随机场景"；利于曲线斜率与 paired 统计。

本生成器直接复用 E3-V2 冻结生成器（scripts/reproduce/e3_v2/build_e3_v2_environment.py）
的生成规则（服务器先行 + 前缀一致性；结构与 E1_ENVIRONMENT_V1 一致）：
- M=8 全连接；任务 c 三带 {2000/5000/12000} (0.4/0.4/0.2)；设备 f_loc 两档 {800/1200}；
  服务器 F_j=10000*(1+0.3*(j mod 3))；ν∈{0:0.4, 8:0.3, 16:0.3}；λ_j∈U[0.001,0.003]；
  R_min∈U[0.85,0.95]；无 deadline（deadline_seconds 占位）；system_params 只 kappa_R。
代码级复用保证与 E3-V2 绝对一致（防参数漂移），仅 scenario_id 前缀标记为 e0v2。

用法：
  python scripts/reproduce/e0_v2/build_e0_v2_environment.py --seed 201 --n 80 [--n-max 260]
"""
from __future__ import annotations

import argparse
import json
import os
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "src"))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e3_v2"))

from build_e3_v2_environment import (  # noqa: E402  （E3-V2 冻结生成器；代码级复用）
    COMPUTE_SCALE,
    M_DEFAULT,
    build_e3_v2_environment as _build_e3_v2,
)

# ---------------------------------------------------------------------------
# E0 冻结规格（E0-V2-0 合同；用户 2026-08-09 设计）
# ---------------------------------------------------------------------------
E0_N_MAX = 260          # Pilot 网格最大 N（每 seed 生成一次，prefix 到各 N）
E0_PILOT_N_GRID = [20, 40, 60, 80, 100, 120, 150, 180, 220, 260]
E0_PILOT_SEEDS = [201, 202, 203, 204, 205]      # NOT_FORMAL
E0_FORMAL_SEEDS = list(range(601, 621))         # NEW_PAIRED_UNSEEN（20 个）
# E0 内部用 "transition" 语义仅作 E3-V2 生成器参数（不改变生成规则；只影响其 scenario_id）
_E3_PRESSURE_TAG = "transition"


def build_e0_v2_super_scenario(seed: int, n_max: int = E0_N_MAX) -> dict:
    """生成 E0 超场景 Gamma_{n_max}（服务器先行；与 E3-V2 完全同生成规则）。

    返回的 scenario_id 标记为 e0v2（E3-V2 内部 id 会被覆盖）。
    """
    if not isinstance(seed, int) or seed < 0:
        raise ValueError("seed must be a non-negative int")
    if not isinstance(n_max, int) or n_max <= 0:
        raise ValueError("n_max must be a positive int")
    cfg = _build_e3_v2(seed=seed, n_max=n_max, pressure=_E3_PRESSURE_TAG)
    cfg["scenario_id"] = "e0v2_n%d_m%d_s%s_seed%d" % (
        n_max, len(cfg["servers"]), COMPUTE_SCALE, seed)
    cfg["mode"] = "explicit"
    cfg["e0_origin"] = "E3-V2 generator (server-first, prefix-consistent)"
    return cfg


def e0_prefix_scenario(super_cfg: dict, n: int) -> dict:
    """取前 n 个任务/设备/链路的确定性前缀（嵌套任务链核心；服务器固定）。

    Gamma_n = prefix(Gamma_nmax)。断言 n <= N_max。
    """
    assert n <= len(super_cfg["tasks"]) and n > 0, "n must be in (0, N_max]"
    out = json.loads(json.dumps(super_cfg))
    m = len(super_cfg["servers"])
    out["scenario_id"] = "e0v2_n%d_m%d_s%s_seed%d" % (
        n, m, COMPUTE_SCALE, super_cfg["seed"])
    out["tasks"] = super_cfg["tasks"][:n]
    out["devices"] = super_cfg["devices"][:n]
    out["links"] = super_cfg["links"][: n * m]
    return out


def build_e0_v2_environment(seed: int, n: int, n_max: int = E0_N_MAX) -> dict:
    """便捷函数：返回 N=n 的 E0 场景（内部从 N_max 前缀切分，保证嵌套链）。

    注意：多次调用同一 (seed, n) 结果一致（确定性）；对同一 seed 不同 n 的调用
    各自生成 N_max 超场景（runner 可先持有一个 super 复用，避免重复生成）。
    """
    super_cfg = build_e0_v2_super_scenario(seed=seed, n_max=n_max)
    return e0_prefix_scenario(super_cfg, n)


def main() -> int:
    ap = argparse.ArgumentParser(description="E0-V2 负载扫描环境生成器（E0-V2-0 冻结）")
    ap.add_argument("--seed", type=int, default=201)
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--n-max", type=int, default=E0_N_MAX)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    if not (0 < args.n <= args.n_max):
        print("error: need 0 < n <= n_max")
        return 2
    cfg = build_e0_v2_environment(seed=args.seed, n=args.n, n_max=args.n_max)

    out_dir = args.out_dir or os.path.join(_PROJECT, "results", "e0_v2", "environments")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "e0v2_n%d_seed%d.json" % (args.n, args.seed))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh, ensure_ascii=False, indent=2)
    print("written:", path)
    print("N:", args.n, "| seed:", args.seed, "| servers:", len(cfg["servers"]),
          "| tasks:", len(cfg["tasks"]), "| links:", len(cfg["links"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
