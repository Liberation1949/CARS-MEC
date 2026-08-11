# -*- coding: utf-8 -*-
"""JTORA-adapted 数值求解（原文 Eq.27/28/29 + Algorithm 1 参考实现）。

依据：references/JTORA-adapted.PDF Section V + 本子阶段适配合同。

包含：
1. crc_closed_form：CRA 闭式（Eq.27/41；生产路径使用；KKT 派生，Lemma 2）。
2. crc_dual_bisection：CRA 对偶二分（验证用；以 Lagrangian 乘子 nu_s 二分使
   sum f_us = f_s，与闭式等价；测试断言一致）。
3. source_objective_value：Eq.29 源目标 J*(Y)（Algorithm 2 的 value oracle）。
4. upa_optimal_power_bisection：Algorithm 1（UPA 二分；source-faithful 参考，
   测试边界/单调性；生产路径功率固定不调用，binary_search_calls=0）。

数值冻结：absolute/relative tolerance（配置）；改进判定 (1+delta)（Algorithm 2）。
所有函数确定性（无随机）；reference 与 production 共用。
"""

from __future__ import annotations

import math
from typing import Dict, FrozenSet, List, Sequence, Tuple

from cars.simulator.derived_state import DerivedState
from cars.methods.jtora_adapted.source_cost import SourceCosts

# 判定容差（与 evaluator_contract.yaml §5 eps_cmp 一致）
EPS = 1.0e-9
LN2 = math.log(2.0)


# ---------------------------------------------------------------------------
# CRA：闭式（Eq.27/41）
# ---------------------------------------------------------------------------


def crc_closed_form(tasks_on_server: Sequence[int], weights: Sequence[float], F_j: float) -> Dict[int, float]:
    """[Lemma 2 / Eq.27] f*_ij = F_j * sqrt(eta_i) / sum_{v} sqrt(eta_v)。

    对服务器 j 上任务集（index 对应 tasks_on_server）分配；容量守恒
    sum f* = F_j（Eq.12g 等号）。weights[i] = sqrt(eta_{tasks[i]})。
    """
    if not tasks_on_server:
        return {}
    denom = sum(weights)
    if denom <= 0.0:
        raise ValueError("CRA denominator must be positive")
    return {i: F_j * w / denom for i, w in zip(tasks_on_server, weights)}


def crc_overhead_closed_form(weights: Sequence[float], F_j: float) -> float:
    """[Eq.28/42] A_j = (1/F_j) * (sum sqrt(eta))^2。"""
    if not weights:
        return 0.0
    s = sum(weights)
    return s * s / F_j


# ---------------------------------------------------------------------------
# CRA：对偶二分（验证用；与闭式数值等价）
# ---------------------------------------------------------------------------


def crc_dual_bisection(
    tasks_on_server: Sequence[int],
    weights: Sequence[float],
    F_j: float,
    max_iterations: int = 200,
    atol: float = 1.0e-8,
) -> Dict[int, float]:
    """CRA 对偶二分：二分 Lagrangian 乘子 nu>0 使 sum f = F_j。

    由 KKT（Appendix B Eq.38/39）：f_i(nu) = sqrt(eta_i)/sqrt(nu)，
    phi(nu) = sum f_i(nu) - F_j 单调减；二分求 phi(nu)=0。
    用于验证闭式（生产路径用 crc_closed_form）。
    """
    if not tasks_on_server:
        return {}
    wsum = sum(weights)
    if wsum <= 0.0:
        raise ValueError("CRA weights must be positive")
    # 由 KKT（Appendix B Eq.38/39）：f_i(nu) = sqrt(eta_i)/sqrt(nu) = w_i/sqrt(nu)，
    # phi(nu) = sum f_i - F_j = wsum/sqrt(nu) - F_j = 0 -> nu = (wsum/F_j)^2
    nu_star = (wsum / F_j) ** 2
    # 二分区间 [nu_lo, nu_hi] 包围 nu_star；收敛按容量残差 |phi| <= atol*F_j
    nu_lo = 1e-15
    nu_hi = max(1e15, nu_star * 2.0)
    for _ in range(max_iterations):
        nu_mid = 0.5 * (nu_lo + nu_hi)
        phi = wsum / math.sqrt(nu_mid) - F_j
        if abs(phi) <= atol * F_j:
            nu = nu_mid
            break
        if phi > 0.0:
            nu_lo = nu_mid
        else:
            nu_hi = nu_mid
    else:
        nu = 0.5 * (nu_lo + nu_hi)
    return {i: w / math.sqrt(nu) for i, w in zip(tasks_on_server, weights)}


# ---------------------------------------------------------------------------
# Eq.29 源目标（Algorithm 2 value oracle）
# ---------------------------------------------------------------------------


def source_objective_value(Y: FrozenSet[Tuple[int, int]], costs: SourceCosts, derived: DerivedState) -> float:
    """[Eq.29] J*(Y) = sum_{(i,j) in Y} lambda_i(beta^t+beta^e)
                     - T(Y) - A(Y, F*)。

    T(Y) = sum_{(i,j) in Y} transmission_overhead(i,j)（物化传输项）；
    A(Y,F*) = sum_j (1/F_j)(sum_{i in Y_j} sqrt(eta_i))^2（Eq.28 闭式）。
    Y 为空 -> J* = 0（无卸载无开销）。
    """
    if not Y:
        return 0.0
    const = 0.0
    trans = 0.0
    # 按服务器聚合计算资源权重
    w_by_server: Dict[int, float] = {}
    for (i, j) in Y:
        const += costs.constant_utility(i)
        trans += costs.transmission_overhead(i, j)
        w_by_server[j] = w_by_server.get(j, 0.0) + costs.w[i]
    cra = 0.0
    for j, wsum in w_by_server.items():
        F_j = float(derived.server_state[j]["F_j"])
        cra += crc_overhead_closed_form([wsum], F_j)
    return const - trans - cra


# ---------------------------------------------------------------------------
# UPA：Algorithm 1（source-faithful 参考；测试用；生产路径不调用）
# ---------------------------------------------------------------------------


def _upa_q(p: float, b: float, zeta: float, nu: float) -> float:
    """[Eq.24] Q(p) = nu log2(1+bp) - b(zeta + nu p)/((1+bp) ln2)。"""
    one_bp = 1.0 + b * p
    return nu * math.log2(one_bp) - b * (zeta + nu * p) / (one_bp * LN2)


def upa_optimal_power_bisection(
    P_max: float,
    b: float,
    zeta: float,
    nu: float,
    max_iterations: int = 64,
    atol: float = 1.0e-8,
) -> float:
    """[Algorithm 1] UPA 最优功率 p*（严格准凸 T_u 的最小点）。

    若 Q(P_max) < 0（Q 单调增且 Q(0)<0）-> p* = P_max；
    否则在 [0, P_max] 二分 Q(p)=0。
    """
    if _upa_q(P_max, b, zeta, nu) < 0.0:
        return P_max
    p_lo = 0.0
    p_hi = P_max
    for _ in range(max_iterations):
        p_mid = 0.5 * (p_lo + p_hi)
        if _upa_q(p_mid, b, zeta, nu) < 0.0:
            p_lo = p_mid
        else:
            p_hi = p_mid
        if (p_hi - p_lo) <= atol:
            break
    return 0.5 * (p_lo + p_hi)
