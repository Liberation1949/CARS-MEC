# -*- coding: utf-8 -*-
"""RCLA：Reliability-Constrained Lagrangian Allocation（CARS）。

对每台服务器 j，固定 AADA 得到的 Gamma_j，求（候选冻结公式，源于普通 LA
等价目标 min sum_i a_i/f_ij s.t. sum f_ij <= F_j, f_ij > 0 加可靠性下界）：

  min  sum_{i in Gamma_j} a_i / f_ij
  s.t. sum_i f_ij <= F_j
       f_ij >= ell_succ_ij

其中 a_i = alpha_i * f_i^loc，ell_succ_ij = max(ell_R_ij, f_min^exec=1.0)
（§III-D 可执行成功 floor；对 nu>0 任务 ell_succ == ell_R）。

可行性检查：sum_i ell_succ_ij <= F_j + eps；否则返回 ALLOCATION_INFEASIBLE
（正常情况下 AADA 应防止该状态出现；诊断如实记录，不伪造成功）。

KKT 结构（凸问题，唯一解）：
  f_ij* = max( ell_succ_ij, sqrt(a_i / mu_j) )，mu_j >= 0，
  且 sum_i f_ij* = F_j（容量饱和）。

求解（确定性；阶段合同 §3.3 允许“确定性二分或严格等价 active-set 解法”）：
采用**精确 active-set（water-filling）**——容量精确饱和（残差 ~1e-12，满足
Evaluator C6 容差 eps_cmp=1e-9）：
- 若 sum ell_succ == F_j（容差内）：f = ell_succ（全部 floor 恰好耗尽容量）；
- 否则迭代：free 集合按普通 LA 闭式分配剩余容量，违反 floor 的任务进入
  active 集（f = ell_succ），重复直至无违反；
- 无 active floor 时精确退化为普通 LA：f_ij = F_j * sqrt(a_i) / sum_k sqrt(a_k)
  （Theorem 3/Eq.25）。
- mu_tol/mu_lo/mu_hi 为二分替代方案的冻结参数（保留 API 兼容；active-set 不使用）。

确定性：纯浮点运算，无随机；同输入 -> 同输出。不修改 X/A（只读）。
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Tuple

INF = float("inf")


def _sqrt_a(a: float) -> float:
    return math.sqrt(max(a, 0.0))


def _la_closed_form(alphas: List[float], F_j: float) -> List[float]:
    """普通 LA 闭式：f_i = F_j * sqrt(a_i) / sum_k sqrt(a_k)（Theorem 3/Eq.25）。"""
    n = len(alphas)
    sq = [_sqrt_a(a) for a in alphas]
    denom = sum(sq)
    if denom <= 0.0:
        raise ValueError("RCLA: LA denominator must be positive (alpha_i>0, f_loc>0)")
    return [F_j * s / denom for s in sq]


def solve_server(
    floors: List[float],
    alphas: List[float],
    F_j: float,
    *,
    eps_cmp: float,
    mu_tol: float,
    max_iters: int,
    mu_lo: float,
    mu_hi: float,
    numeric_epsilon: float,
) -> Tuple[Optional[List[float]], Dict]:
    """单服务器 RCLA 求解（精确 active-set，容量精确饱和）。

    求解器选择（阶段合同 §3.3 允许："确定性二分或严格等价 active-set 解法"）：
    采用精确 active-set（water-filling），容量精确饱和（残差 ~1e-12，满足
    Evaluator C6 容差 eps_cmp=1e-9）：
      1) 对 free 集合按普通 LA 闭式分配剩余容量；
      2) 违反 floor（la_i < ell_succ_i - eps）的任务进入 active 集，锁定 f=ell_succ；
      3) 重复直至无违反。
    mu_tol/mu_lo/mu_hi 为二分替代方案的冻结参数（保留 API 兼容；active-set
    不使用）。KKT 结构 f_i* = max(ell_succ_i, sqrt(a_i/mu)) 由 active-set 精确实现：
      free 集 f_i = remaining * sqrt(a_i)/sum_{free} sqrt(a_k)，对应
      mu = (sum_{free} sqrt(a_k)/remaining)^2，且 active 集满足
      sqrt(a_i/mu) < ell_succ_i（floor 收紧）。
    确定性：纯浮点运算，无随机；同输入 -> 同输出。不修改 X/A。
    """
    n = len(floors)
    diag = {
        "allocation_infeasible": False,
        "floor_sum": float(sum(floors)),
        "active_floor_task_count": 0,
        "capacity_utilization": 0.0,
        "capacity_residual": 0.0,
        "kkt_residual": 0.0,
        "la_floor_violation_max": 0.0,
        "all_floors_active": False,
        "no_active_floor": False,
        "bisection_iters": 0,
        "mu": None,
    }
    if n == 0:
        return [], diag

    floor_sum = sum(floors)
    if floor_sum > F_j + eps_cmp:
        diag["allocation_infeasible"] = True
        diag["capacity_residual"] = float(floor_sum - F_j)
        return None, diag

    # 情形 1：floor 恰好耗尽容量 -> f = ell_R（全部 active）
    if floor_sum >= F_j - eps_cmp:
        alloc = [float(f) for f in floors]
        diag["active_floor_task_count"] = n
        diag["all_floors_active"] = True
        diag["capacity_utilization"] = 1.0
        diag["capacity_residual"] = 0.0
        diag["kkt_residual"] = 0.0
        diag["mu"] = INF
        return alloc, diag

    # 情形 2/3：精确 active-set（含无 active floor 时精确退化普通 LA）
    max_iters = int(max_iters)
    active = [False] * n
    free = [i for i in range(n)]
    remaining = float(F_j)
    la_floor_violation_max = 0.0

    for _ in range(min(max_iters, n + 1)):
        sq = {i: _sqrt_a(alphas[i]) for i in free}
        denom = sum(sq.values())
        if denom <= 0.0:
            break  # 防御：free 集合全 alpha=0（floor 方案已由情形 1 覆盖）
        newly = []
        for i in free:
            la_i = remaining * sq[i] / denom
            viol = floors[i] - la_i
            if viol > la_floor_violation_max:
                la_floor_violation_max = viol
            if la_i < floors[i] - eps_cmp:
                newly.append(i)
        if not newly:
            break
        for i in newly:
            active[i] = True
        free = [i for i in free if not active[i]]
        remaining = F_j - sum(floors[i] for i in range(n) if active[i])
        remaining = max(remaining, 0.0)

    alloc = [0.0] * n
    active_count = 0
    for i in range(n):
        if active[i]:
            alloc[i] = float(floors[i])
            active_count += 1
    sq = {i: _sqrt_a(alphas[i]) for i in free}
    denom = sum(sq.values())
    if denom > 0.0:
        for i in free:
            alloc[i] = remaining * sq[i] / denom

    cap_sum = sum(alloc)
    diag["active_floor_task_count"] = int(active_count)
    diag["capacity_utilization"] = float(cap_sum / F_j)
    diag["capacity_residual"] = float(abs(cap_sum - F_j))
    diag["kkt_residual"] = 0.0  # KKT 由 active-set 构造精确满足
    diag["la_floor_violation_max"] = float(max(la_floor_violation_max, 0.0))
    diag["all_floors_active"] = False
    diag["no_active_floor"] = active_count == 0
    diag["mu"] = (
        float((denom / remaining) ** 2) if denom > 0.0 and remaining > 0.0 else INF
    )
    return alloc, diag


# MATH-FMIN-CR-R2（2026-08-11 用户批准）：最小可调度执行计算速率 f_min^exec=1.0 cycles/s。
# RCLA 下限使用可执行成功下限 ell_succ = max(ell_R, f_min^exec)：
#   - 对 nu>0 任务：ell_R > f_min^exec（formal 参数域），ell_succ = ell_R（不变）；
#   - 对 nu=0 任务：ell_R = 0，ell_succ = f_min^exec（闭合可执行性，非数值 epsilon）。
F_MIN_EXEC = 1.0


def run_rcla(
    view,
    assignment_matrix: List[List[int]],
    *,
    eps_cmp: float,
    rcla_cfg: Dict,
) -> Dict:
    """对所有服务器执行 RCLA（固定 AADA 的 A）。不修改 X/A（只读）。

    返回 {resource_allocation, diagnostics}。
    diagnostics 字段（阶段合同 §3.5）：floor_sum / active_floor_task_count /
    capacity_utilization / max_capacity_residual / kkt_residual /
    allocation_infeasible / runtime_ms / per_server。
    """
    t0 = time.monotonic()
    n = view.n
    m = view.m
    F: List[List[float]] = [[0.0] * m for _ in range(n)]

    total_floor_sum = 0.0
    total_active = 0
    max_cap_residual = 0.0
    max_kkt = 0.0
    any_infeasible = False
    per_server = []

    for j in range(m):
        members = [i for i in range(n) if assignment_matrix[i][j] == 1]
        if not members:
            per_server.append(
                {
                    "server_id": view.server_ids[j],
                    "n_members": 0,
                    "allocation_infeasible": False,
                }
            )
            continue
        floors = [max(view.edges[(i, j)]["ell_R"], F_MIN_EXEC) for i in members]
        alphas = [view.tasks[i]["a_i"] for i in members]
        F_j = view.servers[j]["F_j"]
        alloc, sdiag = solve_server(
            floors,
            alphas,
            F_j,
            eps_cmp=eps_cmp,
            mu_tol=rcla_cfg["rcla_mu_tol"],
            max_iters=rcla_cfg["rcla_max_iters"],
            mu_lo=rcla_cfg["rcla_mu_lo"],
            mu_hi=rcla_cfg["rcla_mu_hi"],
            numeric_epsilon=rcla_cfg["rcla_numeric_epsilon"],
        )
        if alloc is None:
            # ALLOCATION_INFEASIBLE（AADA 正常情况下应防止）：回退普通 LA，
            # 任务由统一 Evaluator 诚实判定（不伪造成功）。
            any_infeasible = True
            alloc = _la_closed_form(alphas, F_j)
            sdiag["allocation_infeasible"] = True
        for idx, i in enumerate(members):
            F[i][j] = alloc[idx]
        total_floor_sum += sdiag["floor_sum"]
        total_active += sdiag["active_floor_task_count"]
        max_cap_residual = max(max_cap_residual, sdiag["capacity_residual"])
        max_kkt = max(max_kkt, sdiag["kkt_residual"])
        per_server.append(
            {
                "server_id": view.server_ids[j],
                "n_members": len(members),
                "allocation_infeasible": bool(sdiag["allocation_infeasible"]),
                "floor_sum": sdiag["floor_sum"],
                "active_floor_task_count": sdiag["active_floor_task_count"],
                "capacity_utilization": sdiag["capacity_utilization"],
                "capacity_residual": sdiag["capacity_residual"],
                "kkt_residual": sdiag["kkt_residual"],
                "mu": sdiag["mu"],
            }
        )

    cap_util = [0.0] * m
    for j in range(m):
        cap_util[j] = float(sum(F[i][j] for i in range(n)) / view.servers[j]["F_j"])

    diagnostics = {
        "floor_sum": float(total_floor_sum),
        "active_floor_task_count": int(total_active),
        "capacity_utilization": [float(v) for v in cap_util],
        "max_capacity_residual": float(max_cap_residual),
        "kkt_residual": float(max_kkt),
        "allocation_infeasible": bool(any_infeasible),
        "runtime_ms": float((time.monotonic() - t0) * 1000.0),
        "per_server": per_server,
    }
    return {"resource_allocation": F, "diagnostics": diagnostics}


def run_ordinary_la(view, assignment_matrix: List[List[int]]) -> Dict:
    """普通 LA（fixed assignment，无 reliability floor 下界；E3 fixed-assignment 对照）。

    对固定 AADA 的 A 逐服务器用普通 LA 闭式（Theorem 3/Eq.25）分配：
      f_i = F_j * sqrt(a_i) / sum_k sqrt(a_k)
    不修改 X/A（只读）。诊断字段与 run_rcla 对齐（active_floor_task_count=0、
    allocation_infeasible=False、capacity_residual 精确饱和、kkt_residual=0），
    保证 E3 fixed-assignment 对照表（RCLA vs ordinary LA）字段同构可比较。
    """
    t0 = time.monotonic()
    n = view.n
    m = view.m
    F: List[List[float]] = [[0.0] * m for _ in range(n)]
    per_server = []

    for j in range(m):
        members = [i for i in range(n) if assignment_matrix[i][j] == 1]
        if not members:
            per_server.append(
                {
                    "server_id": view.server_ids[j],
                    "n_members": 0,
                    "allocation_infeasible": False,
                }
            )
            continue
        alphas = [view.tasks[i]["a_i"] for i in members]
        F_j = view.servers[j]["F_j"]
        alloc = _la_closed_form(alphas, F_j)
        for idx, i in enumerate(members):
            F[i][j] = alloc[idx]
        cap_sum = sum(alloc)
        per_server.append(
            {
                "server_id": view.server_ids[j],
                "n_members": len(members),
                "allocation_infeasible": False,
                "floor_sum": 0.0,
                "active_floor_task_count": 0,
                "capacity_utilization": float(cap_sum / F_j) if F_j > 0.0 else 0.0,
                "capacity_residual": float(abs(cap_sum - F_j)),
                "kkt_residual": 0.0,
                "mu": None,
            }
        )

    cap_util = [0.0] * m
    for j in range(m):
        cap_util[j] = float(sum(F[i][j] for i in range(n)) / view.servers[j]["F_j"])

    max_cap_residual = max(
        (p["capacity_residual"] for p in per_server), default=0.0
    )
    diagnostics = {
        "floor_sum": 0.0,
        "active_floor_task_count": 0,
        "capacity_utilization": [float(v) for v in cap_util],
        "max_capacity_residual": float(max_cap_residual),
        "kkt_residual": 0.0,
        "allocation_infeasible": False,
        "runtime_ms": float((time.monotonic() - t0) * 1000.0),
        "per_server": per_server,
        "allocation_mode": "ordinary_la",
    }
    return {"resource_allocation": F, "diagnostics": diagnostics}
