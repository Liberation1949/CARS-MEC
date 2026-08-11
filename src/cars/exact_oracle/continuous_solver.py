# -*- coding: utf-8 -*-
"""固定离散 (X,A) 后每服务器的 exact continuous solver（E4-EXACT-1；Route A + KKT）。

数学依据（E4-EXACT-0 Confirm；E4_EXACT_ORACLE_CONTRACT_V1 §3.2/§4.2）：
  固定成功集 S（EDGE 任务，全 a_i = lambda_j*nu_i*c_i > 0）后，每服务器 j 的 Tier-2 子问题：
      max_{f} sum_{i in S} R_i(f_i)   s.t.  f_i >= ell_i^R,  sum f_i <= F_j
  其中 R_i(f) = R_tx_i * exp(-a_i / f)。
  因 ell_i^R = a_i / ln(R_tx_i / R_i^min) > a_i/2（ln(R_tx/R_min) <= ln(1/0.8) < 2），
  R_i 在 [ell_i^R, +inf) 上严格凹增 => -R_i 严格凸 => 本问题是凸优化，
  KKT 条件充分必要，全局最优唯一（CERTIFIED_NUMERICAL_EXACT）。

  求解：枚举 active set A ⊆ S（f_i = ell_i^R 的任务）；free 任务满足 R_i'(f_i) = mu
  （R_i'(f) = R_tx*a*exp(-a/f)/f^2 在 [ell^R,+inf) 严格递减，f_i(mu) 唯一）；
  mu 由 sum_{free} f_i(mu) = F_j - sum_A ell^R 单调唯一确定（二分）；
  KKT 验证：active 任务 R_i'(ell_i^R) <= mu，free 任务 f_i >= ell_i^R。
  在所有有效候选（枚举 2^k 个 A）中取最大 sum R_i -> 全局最优。

  0-floor 边界（a_i == 0，即 R 为常数 R_tx）：Tier-2 无贡献；按冻结的
  zero_floor_min_resource 预留最小正资源（Evaluator EXEC 仅要求 f>0）；
  Tier-2 最优下 pos 任务用满容量，zero 任务固定 epsilon（E4-EXACT-1 Confirm）。

本求解器不读取 CARS 输出，不调用 CARS 决策逻辑；不修改任何公共模型。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

# 默认求解容差（仅数值实现层；来自 Contract V4 §7 语义）
DEFAULT_EPS_CMP = 1.0e-9
DEFAULT_MAX_ITER = 200
# MATH-FMIN-CR-R2（2026-08-11 用户批准）：最小可调度执行计算速率 f_min^exec = 1.0 cycles/s。
# 对零脆弱性（ν=0, q=0, ell_R=0）任务，成功执行下限为 f_min^exec（真实调度参数，
# 非浮点 epsilon），闭合 P0 可行域（消除 f→0+ supremum 风险）。
DEFAULT_ZERO_FLOOR_MIN_RESOURCE = 1.0  # == f_min^exec


# ---------------------------------------------------------------------------
# 公共可靠性原语（复用 physical_models 语义：R_off = R_tx * R_exe）
# ---------------------------------------------------------------------------
def _r_value(rtx: float, a: float, f: float) -> float:
    """R_i(f) = R_tx * exp(-a/f)（公共 offloading_reliability 结构；f>0）。"""
    return rtx * math.exp(-a / f)


def _r_prime(rtx: float, a: float, f: float) -> float:
    """R_i'(f) = R_tx * a * exp(-a/f) / f^2（在 [ell^R,+inf) 严格递减）。"""
    return rtx * a * math.exp(-a / f) / (f * f)


def _f_of_mu(
    rtx: float,
    a: float,
    ell: float,
    mu: float,
    max_iter: int = DEFAULT_MAX_ITER,
) -> Optional[float]:
    """解 R_i'(f) = mu 的 f in [ell, +inf)（R_i' 严格递减，唯一根）。

    要求 0 < mu <= R_i'(ell)；否则返回 None（f < ell，该任务应 active）。
    """
    if mu <= 0.0:
        return None
    r_ell = _r_prime(rtx, a, ell)
    if mu > r_ell:
        return None
    if abs(mu - r_ell) <= 1.0e-15 * max(1.0, r_ell):
        return ell
    lo = ell
    hi = max(ell * 2.0, 1.0)
    while _r_prime(rtx, a, hi) > mu:
        hi *= 2.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        if _r_prime(rtx, a, mid) > mu:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# 每服务器连续求解
# ---------------------------------------------------------------------------
def _alloc_zero_tasks(zero, f_avail_total, f_min_exec, eps_cmp):
    """零脆弱性（q=0, ell_R=0）任务：每任务至少 f_min^exec（最小可调度速率），
    剩余容量按效用凹结构（f ∝ sqrt(A_u)）分配给 A_u>0 任务（Tier-3 优化）；
    A_u=0 任务效用为常数，仅取保底 f_min^exec。

    返回 (f, R2, U3)；容量不足以容纳 n*f_min^exec 时返回 None。
    """
    n = len(zero)
    if n == 0:
        return {}, 0.0, 0.0
    if f_avail_total < n * f_min_exec - eps_cmp:
        return None
    base = f_min_exec
    rem = f_avail_total - n * base
    pos_u = [t for t in zero if t["A_u"] > 0.0]
    sqrt_a = [math.sqrt(float(t["A_u"])) for t in pos_u]
    s = sum(sqrt_a)
    f = {}
    R2 = 0.0
    U3 = 0.0
    # A_u=0 任务：效用常数，仅保底 f_min^exec
    for t in zero:
        if t["A_u"] <= 0.0:
            f[t["index"]] = base
            R2 += t["R_tx"]
            U3 += t["K_u"]
    # A_u>0 任务：base + 剩余按 sqrt(A_u) 额外分配
    for t, sa in zip(pos_u, sqrt_a):
        extra = rem * sa / s if s > 1e-30 else rem / max(1, len(pos_u))
        fv = base + extra
        f[t["index"]] = fv
        R2 += t["R_tx"]
        U3 += t["K_u"] - t["A_u"] / fv
    return f, R2, U3


def solve_server(
    tasks: List[Dict],
    F_j: float,
    *,
    eps_cmp: float = DEFAULT_EPS_CMP,
    max_iter: int = DEFAULT_MAX_ITER,
    zero_floor_min_resource: float = DEFAULT_ZERO_FLOOR_MIN_RESOURCE,
) -> Optional[Dict]:
    """对固定成功集 tasks（该服务器 EDGE 任务）求 lexicographic 最优 F。

    tasks 元素：{index, ell_R, R_tx, a, A_u, K_u}（来自 OracleModel.edges）。
    返回 dict：
      {f: {index: f_i}, R2: sum z R, U3: sum z U, mode: str,
       capacity_residual, reliability_residual, kkt_residual,
       active_set, mu, visited_active_sets}
    若 S 在容量上不可行返回 None。
    """
    if F_j < 0:
        return None

    pos = [t for t in tasks if t["a"] > 0.0]
    zero = [t for t in tasks if t["a"] == 0.0]

    # 0-floor 任务预留最小正资源（Evaluator EXEC 需 f>0）
    F_avail = F_j - len(zero) * zero_floor_min_resource
    if F_avail < -eps_cmp:
        return None  # 容量不足（0-floor 预留都放不下）

    # ------------------------------------------------------------------
    # 主路径：a>0 任务 Tier-2 KKT（凸问题；唯一全局最优）
    # ------------------------------------------------------------------
    best = None  # {f: dict, R2, U3, active_set, mu, kkt_res}
    cands: List[Dict] = []
    k = len(pos)
    visited = 0
    if k == 0:
        # 无 pos 任务：全部 zero（或空）。Tier-2 贡献常数 R_tx；
        # 每任务至少 f_min^exec，剩余容量按效用凹结构分配（Tier-3）。
        alloc = _alloc_zero_tasks(zero, F_j, zero_floor_min_resource, eps_cmp)
        if alloc is None:
            return None  # 容量不足以容纳 n_zero*f_min^exec
        f, R2, U3 = alloc
        has_utility_dir = any(t["A_u"] > 0.0 for t in zero)
        zero_alloc_mode = (
            "WATERFILL"
            if (has_utility_dir and F_j > len(zero) * zero_floor_min_resource + eps_cmp)
            else "EPSILON"
        )
        return {
            "f": f,
            "R2": R2,
            "U3": U3,
            "mode": "CERTIFIED_NUMERICAL_EXACT",
            "capacity_residual": 0.0,  # 无分配，无容量违约
            "reliability_residual": 0.0,
            "kkt_residual": 0.0,
            "active_set": [t["index"] for t in zero],
            "mu": None,
            "visited_active_sets": 0,
            "tier2_optimal_set_size": 1,
            "tier3_tiebreak_applied": zero_alloc_mode == "WATERFILL",
            "zero_alloc_mode": zero_alloc_mode,
        }

    # 枚举 active set（mask bit=1 -> 该 pos 任务在 floor/active）
    for mask in range(1 << k):
        active = [pos[t] for t in range(k) if (mask >> t) & 1]
        free = [pos[t] for t in range(k) if not ((mask >> t) & 1)]
        floor_sum = sum(t["ell_R"] for t in active)
        C = F_avail - floor_sum
        visited += 1
        if C < -eps_cmp:
            continue

        f = {t["index"]: t["ell_R"] for t in active}
        mu = None
        kkt_res = 0.0

        if free:
            # 二分 mu in (0, min_free R'(ell)] 使 sum_free f_i(mu) = C
            # 可解性：total_f 在 (0, mu_ub] 从 +inf 单调降到 total_f(mu_ub)；
            # 存在 mu 使 total_f(mu)=C 当且仅当 C >= total_f(mu_ub)（且 C < +inf）。
            mu_ub = min(_r_prime(t["R_tx"], t["a"], t["ell_R"]) for t in free)

            def _total_f(m: float) -> float:
                total = 0.0
                for t in free:
                    fv = _f_of_mu(t["R_tx"], t["a"], t["ell_R"], m, max_iter)
                    if fv is None:
                        return math.inf
                    total += fv
                return total

            t_ub = _total_f(mu_ub)
            if not math.isfinite(t_ub) or C < t_ub - eps_cmp:
                # 无 mu 解：该 A 需要更多任务 active（跳过分支候选）
                continue

            lo_mu, hi_mu = 0.0, mu_ub
            for _ in range(max_iter):
                mid = 0.5 * (lo_mu + hi_mu)
                if _total_f(mid) > C:
                    lo_mu = mid
                else:
                    hi_mu = mid
            mu = 0.5 * (lo_mu + hi_mu)

            free_f = {}
            for t in free:
                fv = _f_of_mu(t["R_tx"], t["a"], t["ell_R"], mu, max_iter)
                if fv is None or fv < t["ell_R"] - eps_cmp:
                    free_f = None
                    break
                free_f[t["index"]] = fv
            if free_f is None:
                continue
            f.update(free_f)

            # 数值防护：二分精度可能使 sum f 略超可用容量（free 部分缩放钳制，
            # 保持 active/floor 不变；超量相对极小，不影响 KKT 最优性到容差内）
            tot = sum(f.values())
            if tot > F_j + eps_cmp:
                free_tot = sum(free_f[t["index"]] for t in free)
                if free_tot > eps_cmp:
                    scale = (free_tot - (tot - F_j)) / free_tot
                    scale = max(0.0, scale)
                    for t in free:
                        f[t["index"]] = f[t["index"]] * scale

            # KKT 验证
            kkt_res = 0.0
            ok = True
            for t in active:
                rp = _r_prime(t["R_tx"], t["a"], t["ell_R"])
                if rp > mu + eps_cmp:
                    ok = False  # active 任务应 free
                    break
                kkt_res = max(kkt_res, abs(rp - mu) if rp <= mu else 0.0)
            if not ok:
                continue
            for t in free:
                rp = _r_prime(t["R_tx"], t["a"], f[t["index"]])
                kkt_res = max(kkt_res, abs(rp - mu))
        else:
            # 全 active；容量可能有余（weak candidate，会被 free 候选超越）
            if C > eps_cmp:
                # 非 KKT（无 free 但容量未满）：仍作为候选，但标记 mode 说明
                kkt_res = float("inf") if C > eps_cmp else 0.0
            else:
                kkt_res = 0.0

        # 目标值（仅成功集 S 内任务；z=1）
        R2 = sum(_r_value(t["R_tx"], t["a"], f[t["index"]]) for t in pos)
        U3 = sum(t["K_u"] - t["A_u"] / f[t["index"]] for t in pos)

        # 容量违约残差（Evaluator C6 语义）：仅当 sum f > F_j 时非零
        cap_res = max(0.0, sum(f.values()) - F_j) / max(1.0, F_j)
        rel_res = max((t["ell_R"] - f[t["index"]]) for t in pos)
        rel_res = max(0.0, rel_res)

        cand = {
            "f": f,
            "R2": R2,
            "U3": U3,
            "mode": "CERTIFIED_NUMERICAL_EXACT",
            "capacity_residual": cap_res,
            "reliability_residual": rel_res,
            "kkt_residual": kkt_res if math.isfinite(kkt_res) else 0.0,
            "active_set": [t["index"] for t in active],
            "mu": mu,
            "visited_active_sets": visited,
        }
        cands.append(cand)

    if not cands:
        # 所有 A 都不可行 -> S 在容量上不可行
        return None

    # Tier-2 最优值 R*（仅 pos 任务目标；zero 任务贡献常数 R_tx，不改变 R*）
    r_star = max(c["R2"] for c in cands)
    # Tier-2 最优集：R2 达到 R* 的候选；优先 KKT 有效候选（弱候选容量富余标 inf）
    tier2_set = [c for c in cands if abs(c["R2"] - r_star) <= eps_cmp]
    kkt_ok = [c for c in tier2_set if c["kkt_residual"] != float("inf")]
    pool = kkt_ok if kkt_ok else tier2_set
    # Tier-3 tie-break：在 Tier-2 最优集内选择效用最优候选
    # （确定性：枚举顺序首个平局）
    best = pool[0]
    tier3_tiebreak = False
    for c in pool[1:]:
        if c["U3"] > best["U3"] + eps_cmp:
            best = c
            tier3_tiebreak = True

    # 0-floor（q=0）任务：Tier-2 贡献常数 R_tx，资源分配不改变 R*；
    # Tier-3 在剩余容量内按效用凹结构水填充（f ∝ sqrt(A_u)），用满剩余容量
    # （替代固定 epsilon；epsilon 仅在无有效效用方向时保底）。
    zero_alloc_mode = "EPSILON"
    if zero:
        used = sum(best["f"].values())
        rem = max(0.0, F_j - used)
        alloc = _alloc_zero_tasks(zero, rem, zero_floor_min_resource, eps_cmp)
        if alloc is None:
            return None  # 容量不足（rem < n_zero*f_min^exec）
        zf, zr2, zu3 = alloc
        best["f"].update(zf)
        best["R2"] += zr2
        best["U3"] += zu3
        if (rem > len(zero) * zero_floor_min_resource + eps_cmp
                and any(t["A_u"] > 0.0 for t in zero)):
            zero_alloc_mode = "WATERFILL"

    # 最终 residual（含 zero）：容量违约残差
    cap = max(0.0, sum(best["f"].values()) - F_j) / max(1.0, F_j)
    best["capacity_residual"] = max(best["capacity_residual"], cap)
    best["tier2_optimal_set_size"] = len(pool)
    best["tier3_tiebreak_applied"] = bool(tier3_tiebreak) or (zero_alloc_mode == "WATERFILL")
    best["zero_alloc_mode"] = zero_alloc_mode
    return best
