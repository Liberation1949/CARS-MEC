# -*- coding: utf-8 -*-
"""E2-V2 环境生成器（E2-V2-0：Computational Heterogeneity Environment Calibration and Freeze）。

基础环境继承 E1_V2_ENVIRONMENT_SELECTED_V1（sf1_vMEDIUM；无 deadline；λ_j 固定名义
故障率）。唯一干预：服务器容量分布 F_j（ΣF_j = F_total^E1 = 101000 恒定）。

容量生成（用户冻结，E2-V2-0 协议 §3/§5）：
    F_j(θ) = F_total · exp(θ·z_j) / Σ_k exp(θ·z_k)
  - z = 固定对称 rank template [-1.5,-1.0,-0.5,-0.15,0.15,0.5,1.0,1.5]
    （每 seed 用独立 RNG substream "e2_capacity_rank" 置换）；
  - θ 由 deterministic bisection 求解使 CV(F_1..F_M) = CV_F^target（CV 随 θ 单调）；
  - 性质：ΣF 严格恒定、F_j>0、同 seed 跨 CV_F 是同一服务器结构逐渐被拉开
    （paired 设计干净，非每点重抽系统）。

同 seed 跨 CV_F：任务/设备/信道/λ_j/R_min 完全一致（基础环境只生成一次，
仅覆盖 F_j）。CV_F=0 时 θ=0 → F_j = F_total/8 全部相等。

用法：
  python scripts/reproduce/e2_v2/build_e2_v2_environment.py --seed 1201 \
      --cv-f 0.6 --n-max 200 --out-dir DIR
"""
from __future__ import annotations

import argparse
import json
import math
import os
import random
import sys

_PROJECT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
sys.path.insert(0, os.path.join(_PROJECT, "scripts", "reproduce", "e1_v2"))
sys.path.insert(0, os.path.join(_PROJECT, "src"))

from build_e1_v2_environment import (  # noqa: E402
    build_e1_v2_environment,
    prefix_scenario,
)

# E2-V2-0 冻结常量（协议 §2/§3）
M_DEFAULT = 8
N_MAX_DEFAULT = 200
S_F_DEFAULT = 1.0
FRAGILITY_PROFILE_DEFAULT = "MEDIUM"
# 固定对称 rank template（用户冻结）
RANK_TEMPLATE_DEFAULT = [-1.5, -1.0, -0.5, -0.15, 0.15, 0.5, 1.0, 1.5]
# 独立 RNG substream 偏移（与基础环境 RNG(seed) 隔离）
RANK_RNG_OFFSET = 104729  # prime；保证 rank 置换与基础环境抽样独立
RANK_RNG_SPLIT = 41

# 允许的 CV_F（白名单：primary + 预注册扩展探针）
ALLOWED_CV_F_PRIMARY = (0.0, 0.3, 0.6, 0.9, 1.2)
ALLOWED_CV_F_EXTENSION = (1.5,)
ALLOWED_N = (140, 170, 200)
ALLOWED_S_F = (1.0, 0.8, 1.2)  # 后备（仅在 s_F=1.0 全不合格时按协议 §5 启动）

CV_TOL = 1.0e-4      # |CV_realized - CV_target| <= 1e-4
SUM_TOL = 1.0e-10     # |sum F_j - F_total| <= 1e-10 * F_total
THETA_MAX = 30.0
THETA_ITERS = 200


def _cv_of(F):
    """变异系数 CV(F) = std(F)/mean(F)。"""
    mu = sum(F) / len(F)
    if mu <= 0.0:
        return 0.0
    var = sum((x - mu) ** 2 for x in F) / len(F)
    return math.sqrt(var) / mu


def _hhi_of(F):
    """capacity HHI = sum_j (F_j/F_total)^2。"""
    tot = sum(F)
    if tot <= 0.0:
        return 0.0
    return sum((x / tot) ** 2 for x in F)


def capacity_rank_for_seed(seed: int, m: int = M_DEFAULT,
                           rank_template=RANK_TEMPLATE_DEFAULT):
    """每 seed 的固定 capacity rank profile（独立 substream，确定性置换）。"""
    template = list(rank_template)
    rng = random.Random(seed * RANK_RNG_OFFSET + RANK_RNG_SPLIT)
    perm = list(range(m))
    rng.shuffle(perm)
    if len(template) < m:
        raise ValueError("rank_template shorter than m")
    return [template[p] for p in perm]


def solve_theta(cv_f_target: float, z, f_total: float,
                cv_tol: float = CV_TOL, theta_max: float = THETA_MAX,
                theta_iters: int = THETA_ITERS):
    """Deterministic bisection：求 θ>=0 使 CV(F(θ)) = cv_f_target。

    F_j(θ) = F_total·exp(θ z_j)/Σexp(θ z_k)。CV(θ) 随 θ 单调不减。
    返回 (theta, F_list, cv_realized)。cv_f_target=0 时直接 θ=0。
    """
    if cv_f_target <= 0.0:
        F = [f_total / len(z)] * len(z)
        return 0.0, F, 0.0, True

    def F_at(theta):
        w = [math.exp(theta * zj) for zj in z]
        s = sum(w)
        return [f_total * x / s for x in w]

    def cv_at(theta):
        return _cv_of(F_at(theta))

    # 单调上升；二分求 θ 使 cv(θ) 最接近 target
    lo, hi = 0.0, theta_max
    # 若 hi 端 CV 仍未达 target，扩大 hi
    guard = 0
    while cv_at(hi) < cv_f_target - cv_tol and guard < 40:
        hi *= 2.0
        guard += 1
    for _ in range(theta_iters):
        mid = 0.5 * (lo + hi)
        if cv_at(mid) < cv_f_target:
            lo = mid
        else:
            hi = mid
    theta = 0.5 * (lo + hi)
    F = F_at(theta)
    cv_real = _cv_of(F)
    # 精度保护：若目标高于可达上限，返回 hi 端点并如实标记
    if cv_real < cv_f_target - cv_tol:
        F = F_at(theta_max)
        cv_real = _cv_of(F)
        reached = False
    else:
        reached = True
    return theta, F, cv_real, reached


def build_e2_v2_environment(
    seed: int,
    cv_f_target: float,
    n_max: int = N_MAX_DEFAULT,
    m: int = M_DEFAULT,
    s_f: float = S_F_DEFAULT,
    fragility_profile: str = FRAGILITY_PROFILE_DEFAULT,
    rank_template=RANK_TEMPLATE_DEFAULT,
) -> dict:
    """生成 Gamma_{n_max}（基础 E1 语义 + E2 容量分布覆盖；确定性）。

    返回 dict：
      - "scenario_cfg": 显式场景配置（mode=explicit；servers 容量已覆盖；ΣF=F_total）
      - "metadata":     容量结构元数据（theta/cv_realized/HHI/F_list/rank 等）
    servers 只含 Schema V4 允许字段（server_id/capacity_cycles_per_sec/
    nominal_failure_rate）；λ_j 由基础环境抽样给出（跨 CV_F 不变）。
    """
    if cv_f_target not in ALLOWED_CV_F_PRIMARY and cv_f_target not in ALLOWED_CV_F_EXTENSION:
        raise ValueError(
            "cv_f_target must be in %s or extension %s, got %r"
            % (sorted(ALLOWED_CV_F_PRIMARY), sorted(ALLOWED_CV_F_EXTENSION), cv_f_target))
    if s_f not in ALLOWED_S_F:
        raise ValueError("s_f must be in %s, got %r" % (sorted(ALLOWED_S_F), s_f))
    if n_max not in (140, 170, 200):
        raise ValueError("E2 n_max must be in {140,170,200}, got %r" % (n_max,))

    # 基础环境（s_f=1.0 时 F_total=101000；λ_j/任务/设备/信道只依赖 seed）
    base = build_e1_v2_environment(
        seed=seed, n_max=n_max, m=m, s_f=s_f, fragility_profile=fragility_profile)
    f_total = float(sum(s["capacity_cycles_per_sec"] for s in base["servers"]))
    if abs(f_total - 101000.0) > 1e-6:
        # 记录但不断言：仅当 s_f != 1.0 时 F_total 不同（后备路径）
        pass

    z = capacity_rank_for_seed(seed, m=m, rank_template=rank_template)
    theta, F, cv_real, reached = solve_theta(cv_f_target, z, f_total)

    # 覆盖服务器容量（仅 F_j；λ_j 保持不变）
    servers = []
    for j, s in enumerate(base["servers"]):
        servers.append({
            "server_id": s["server_id"],
            "capacity_cycles_per_sec": F[j],
            "nominal_failure_rate": s["nominal_failure_rate"],
        })
    scenario_cfg = dict(base)
    scenario_cfg["servers"] = servers
    scenario_cfg["scenario_id"] = "e2v2_cv%s_n%d_m%d_seed%d" % (
        ("%.2f" % cv_f_target), n_max, m, seed)
    scenario_cfg["cv_f_target"] = float(cv_f_target)
    scenario_cfg["cv_f_realized"] = float(cv_real)
    scenario_cfg["theta"] = float(theta)
    scenario_cfg["capacity_rank"] = z
    scenario_cfg["capacity_profile"] = F

    metadata = {
        "seed": seed,
        "cv_f_target": float(cv_f_target),
        "cv_f_realized": float(cv_real),
        "cv_reached": reached,
        "theta": float(theta),
        "f_total": float(f_total),
        "F_list": [round(x, 6) for x in F],
        "rank": z,
        "hhi": _hhi_of(F),
        "max_min_ratio": (max(F) / min(F)) if min(F) > 0 else None,
        "top2_share": (sum(sorted(F, reverse=True)[:2]) / f_total) if f_total > 0 else None,
        "sum_F": float(sum(F)),
        "sumF_error": float(sum(F) - f_total),
    }
    return {"scenario_cfg": scenario_cfg, "metadata": metadata}


def e2_prefix_scenario(cfg: dict, n: int) -> dict:
    """E2 场景取前 n 个任务/设备/链路（deterministic prefix；服务器固定）。"""
    return prefix_scenario(cfg, n)


def main() -> int:
    ap = argparse.ArgumentParser(description="E2-V2 环境生成器（softmax 容量分布）")
    ap.add_argument("--seed", type=int, default=1201)
    ap.add_argument("--cv-f", type=float, default=0.6)
    ap.add_argument("--n-max", type=int, default=N_MAX_DEFAULT)
    ap.add_argument("--out-dir", default=None)
    args = ap.parse_args()

    out = build_e2_v2_environment(seed=args.seed, cv_f_target=args.cv_f, n_max=args.n_max)
    if args.out_dir:
        os.makedirs(args.out_dir, exist_ok=True)
        p = os.path.join(args.out_dir, "e2v2_cv%s_seed%d_n%d.json" % (
            ("%.2f" % args.cv_f), args.seed, args.n_max))
        with open(p, "w", encoding="utf-8") as fh:
            json.dump({"scenario_cfg": out["scenario_cfg"], "metadata": out["metadata"]},
                      fh, ensure_ascii=False, indent=2)
        print("written:", p)
    print(json.dumps(out["metadata"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
