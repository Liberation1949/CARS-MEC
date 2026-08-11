# -*- coding: utf-8 -*-
"""AADA：Allocation-Aware Dynamic Assignment（CARS）。

核心研究思想（候选）：传统 RATA 在 assignment 阶段使用可靠性代理，而后续 LA
才产生真实的任务间资源竞争；AADA 直接让 assignment 感知 downstream allocation
structure（LA sqrt-weight denominator）与 reliability-floor reservation。

冻结公式（阶段合同 §3.2）：
- 任务基础量：a_i = alpha_i * f_i^loc；s_i = sqrt(max(a_i, 0))；
- 服务器动态状态：Q_j = sum_{k in Gamma_j} s_k（downstream LA
  resource-competition state）；G_j = sum_{k in Gamma_j} ell_R_kj
  （可靠性压力诊断，E0/E2 max G/F 语义不变）；H_j = sum_{k in Gamma_j}
  ell_succ_kj（可执行成功 floor 保留，正式准入依据；ell_succ = max(ell_R,
  f_min^exec=1.0)，§III-D）；初始均为 0；
- 可执行 floor 容量约束：仅 H_j + ell_succ_ij <= F_j + eps 的服务器允许接纳任务 i
  （不得先超卖容量再交给 Repair；正文 V-B.5）；
- downstream allocation marginal cost：
  Delta_phi_ij = ((Q_j + s_i)^2 - Q_j^2)/F_j = (2 Q_j s_i + s_i^2)/F_j；
- 禁止使用旧 C_Q + C_Z / gamma / J_RUAD / kappa_R 作为本候选的选择目标。

第一阶段（Local-failure rescue）：local_success=false 的任务优先。排序：
  1) 可满足可靠性的 EDGE 数量少者优先；
  2) best normalized reliability floor min_j(ell_R_ij/F_j) 小者优先；
  3) task_id 升序 tie-break。
  对任务 i：在所有可执行 floor 容量可行（H_j + ell_succ_ij <= F_j）的 server 中选择
  argmin_j (Delta_phi_ij, ell_R_ij/F_j, server_id)；若不存在可行 EDGE，
  保留 LOCAL/UNSERVED 的项目既有语义（不伪造成功方案）。分配 EDGE 后
  Q_j += s_i、H_j += ell_succ_ij（G_j 同步 += ell_R_ij 诊断）。

第二阶段（Local-success lexicographic-improving offloading，正文 V-B.6）：LOCAL
为默认安全方案；EDGE(i,j) 必须同时满足：
  1) 准入约束：H_j + ell_succ_ij <= F_j + eps；
  2) tentative RCLA 可行（sum floors <= F_j，防御性检查）；
  3) P0 字典序改善（canonical lexicographic improvement）：先要求有效可靠性
     不下降 Delta_Rbar_eff > -eps（受影响集 S = {i} ∪ members_j 的可靠性差分，
     含本任务 LOCAL->EDGE 与服务器内已有任务因重新分配的差分，正文 V-B.6）；
     若 |Delta_Rbar_eff| <= eps（可靠性持平），要求真实 system utility 严格
     改善 Delta_U_sys > eps（F-39，含自身 + 传输 + 已有任务）；若
     Delta_Rbar_eff <= -eps（可靠性下降超过容差），即使 Delta_U_sys > 0 也拒绝。
  服务器选择（P0 字典序最优）：优先最大化 Delta_Rbar_eff；|Delta_Rbar_eff| <= eps
  时最大化 Delta_U_sys；再在比较容差内并列时选择较小 Delta_phi_ij；再按 server_id。

E3-V2 变体注入（正文 VI-F.1 / 用户 2026-08-09 设计；单一变化原则）：
  variant="full"             完整 AADA（Phase-1 + Phase-2 P0 字典序门控）；
  variant="no_rescue"        关闭 Phase-1（本地失败任务不救援，保持
                             LOCAL/UNSERVED，由统一 Evaluator 诚实判定）；
  variant="rescue_only"      保留 Phase-1，关闭 Phase-2（本地成功任务全部保持
                             LOCAL）；
  variant="no_alloc_aware"   两阶段均不将 Delta_phi_ij 进入任何选择键
                             （Phase-1 用 (ell_R/F_j, j) 升序；Phase-2 的
                             P0 字典序并列时不再比较 Delta_phi，直接按
                             server_id）；
  variant="no_utility_gate"  Phase-2 去掉"可靠性持平时需 Delta_U_sys>eps"的
                             U 严格改善要求（保留 Delta_Rbar_eff > -eps 门槛；
                             持平时直接按较小 Delta_phi 选服务器）。

确定性：所有排序/选择键均为确定性元组比较；无随机；同输入 -> 同输出。
不调用完整统一 Evaluator（Runner 唯一调用者）；仅引用共享指标原语。
"""

from __future__ import annotations

import time
from typing import Dict, List

from cars.evaluator import metrics
from cars.methods.cars.rcla import run_rcla

INF = float("inf")


def _edge_utility(derived, i: int, j: int, f_ij: float) -> float:
    """任务 i 卸载到服务器 j（分配 f_ij）时的真实效用 U_i（F-39）。

    复用统一 Evaluator 的共享判定原语（task_end_to_end_delay / task_energy /
    task_utility；R3 集成测试明确允许方法引用 cars.evaluator.metrics）。
    本地基线 U_i=0（T_i=T_loc, E_i=E_loc）。
    """
    m = len(derived.server_ids)
    a_row = [0] * m
    a_row[j] = 1
    f_row = [0.0] * m
    f_row[j] = f_ij
    T_i, _ = metrics.task_end_to_end_delay(derived, i, 1, a_row, f_row)
    E_i = metrics.task_energy(derived, i, 1, a_row, f_row)
    return metrics.task_utility(derived, i, T_i, E_i)


def _edge_reliability(view, i: int, j: int, f_ij: float) -> float:
    """任务 i 卸载到服务器 j（分配 f_ij）时的可靠性 R_i（F-14）。"""
    m = len(view.server_ids)
    a_row = [0] * m
    a_row[j] = 1
    f_row = [0.0] * m
    f_row[j] = f_ij
    return metrics.task_reliability(view.derived, i, 1, a_row, f_row)


def _phase2_deltas(
    view,
    i: int,
    j: int,
    members_j: List[int],
    F_cur: List[List[float]],
    f_new: Dict,
) -> tuple:
    """正文 V-B.6 条件 3：受影响集 S={i}∪members_j 的 Delta_Rbar_eff 与 Delta_U_sys。

    - Delta_Rbar_eff = mean_{k∈S}(R_k^after) - mean_{k∈S}(R_k^before)；
    - Delta_U_sys = U_i(LOCAL->EDGE) + Σ_{k∈members_j}(U_k^after - U_k^before)
      （含自身 + 传输成本，经 T_tx/E_tx 计入真实效用 F-39）。
    """
    before_r = [view.tasks[i]["R_loc"]] + [
        _edge_reliability(view, k, j, F_cur[k][j]) for k in members_j
    ]
    after_r = [_edge_reliability(view, i, j, f_new[i])] + [
        _edge_reliability(view, k, j, f_new[k]) for k in members_j
    ]
    d_rbar = float(sum(after_r) / len(after_r) - sum(before_r) / len(before_r))
    d_u = _edge_utility(view.derived, i, j, f_new[i])
    for k in members_j:
        d_u += _edge_utility(view.derived, k, j, f_new[k]) - _edge_utility(
            view.derived, k, j, F_cur[k][j]
        )
    return d_rbar, d_u


def _better_phase2(
    a: tuple, b: tuple, *, eps_cmp: float, alloc_aware: bool, utility_gate: bool
) -> bool:
    """P0 字典序比较 a/b = (dRbar, dU, dphi, j)。a 严格优于 b 时返回 True。

    - full（alloc_aware + utility_gate）：max dRbar -> |dRbar|<=eps 时 max dU
      -> 并列 min dphi -> server_id；
    - no_utility_gate（alloc_aware，去 U）：max dRbar -> 持平时 min dphi
      -> server_id（不再比较 U）；
    - no_alloc_aware（去 dphi）：max dRbar -> 持平时 max dU -> server_id。
    """
    d_r = a[0] - b[0]
    if d_r > eps_cmp:
        return True
    if d_r < -eps_cmp:
        return False
    # 可靠性持平（容差内）
    if utility_gate:
        d_u = a[1] - b[1]
        if d_u > eps_cmp:
            return True
        if d_u < -eps_cmp:
            return False
    if alloc_aware:
        if a[2] < b[2] - eps_cmp:
            return True
        if a[2] > b[2] + eps_cmp:
            return False
    return a[3] < b[3]


def _phase1_key(view, i: int) -> tuple:
    """第一阶段排序键（升序）。"""
    feas = [j for j in range(view.m) if view.edge_feasible(i, j)]
    best_floor = min(
        (view.edges[(i, j)]["ell_R"] / view.servers[j]["F_j"] for j in feas),
        default=INF,
    )
    return (len(feas), best_floor, i)


def run_aada(view, *, eps_cmp: float, rcla_cfg: Dict, variant: str = "full") -> Dict:
    """AADA 主流程。返回 {offloading_decision, assignment_matrix, diagnostics,
    current_allocation, members}（current_allocation/members 供后续 RCLA 复用）。

    variant 见模块 docstring（E3-V2 变体注入；默认 full = 正文 V-B.6 完整语义）。
    """
    n = view.n
    m = view.m
    t0 = time.monotonic()

    phase1_enabled = variant != "no_rescue"
    phase2_enabled = variant != "rescue_only"
    alloc_aware = variant != "no_alloc_aware"
    utility_gate = variant != "no_utility_gate"

    # ---- 任务基础量与服务器动态状态 ----
    s_i = [view.tasks[i]["s_i"] for i in range(n)]
    Q_j = [0.0] * m  # downstream LA resource-competition state
    G_j = [0.0] * m  # reliability-pressure diagnostic (sum ell_R; E0/E2 max G/F 语义不变)
    H_j = [0.0] * m  # executable-success floor reservation (sum ell_succ; 正式准入依据)
    X = [0] * n
    A = [[0] * m for _ in range(n)]
    members: List[List[int]] = [[] for _ in range(m)]

    local_failure = [i for i in range(n) if not view.local_success(i)]
    local_success = [i for i in range(n) if view.local_success(i)]

    # ---- 第一阶段：Local-failure rescue ----
    rescued = 0
    no_feasible = 0
    delta_phi_dist: List[float] = []
    max_epsilon_dphi = 0.0
    phase1_selected = {}
    t_p1 = time.monotonic()
    if phase1_enabled:
        order_fail = sorted(local_failure, key=lambda i: _phase1_key(view, i))
        for i in order_fail:
            best_j = -1
            best_key = None
            for j in range(m):
                if not view.edge_feasible(i, j):
                    continue
                e = view.edges[(i, j)]
                # 可执行 floor 容量约束（H_j + ell_succ_ij <= F_j + eps；正文 V-B.5）
                if H_j[j] + e["ell_succ"] > view.servers[j]["F_j"] + eps_cmp:
                    continue
                dphi = (2.0 * Q_j[j] * s_i[i] + s_i[i] * s_i[i]) / view.servers[j]["F_j"]
                delta_phi_dist.append(dphi)
                # Lemma 2 精确性审计：Delta_phi == phi*(Γ∪{i}) - phi*(Γ)（仅浮点误差）
                exact_dphi = (
                    (Q_j[j] + s_i[i]) ** 2 - Q_j[j] ** 2
                ) / view.servers[j]["F_j"]
                max_epsilon_dphi = max(max_epsilon_dphi, abs(dphi - exact_dphi))
                norm_floor = e["ell_R"] / view.servers[j]["F_j"]
                if alloc_aware:
                    key = (dphi, norm_floor, j)
                else:
                    key = (norm_floor, j)
                if best_key is None or key < best_key:
                    best_key = key
                    best_j = j
            if best_j >= 0:
                A[i][best_j] = 1
                members[best_j].append(i)
                Q_j[best_j] += s_i[i]
                H_j[best_j] += view.edges[(i, best_j)]["ell_succ"]
                G_j[best_j] += view.edges[(i, best_j)]["ell_R"]  # 诊断同步（E0/E2 语义）
                rescued += 1
                phase1_selected[view.task_ids[i]] = "EDGE:%s" % view.server_ids[best_j]
            else:
                no_feasible += 1
                phase1_selected[view.task_ids[i]] = "LOCAL/UNSERVED"
    t_p1_end = time.monotonic()

    # ---- 阶段间：对当前成员运行 RCLA 得到当前分配 F_cur ----
    rcla_phase1 = run_rcla(
        view, A, eps_cmp=eps_cmp, rcla_cfg=rcla_cfg
    )
    F_cur = rcla_phase1["resource_allocation"]

    # ---- 第二阶段：Local-success lexicographic-improving offloading ----
    utility_offload = 0
    gate_rejected_dRbar = 0
    gate_rejected_utility = 0
    # E3-V2-1 pilot 诊断计数（纯统计，不改变算法语义）
    phase2_candidate_edge_count = 0  # 进入条件 3（P0 字典序判断）的候选 EDGE 数
    phase2_gate_passed_count = 0     # 通过 gate 的候选 EDGE 数
    offloads = {}
    t_p2 = time.monotonic()
    if phase2_enabled:
        for i in sorted(local_success):
            best = None  # (dRbar, dU, dphi, j)
            for j in range(m):
                if not view.edge_feasible(i, j):
                    continue
                e = view.edges[(i, j)]
                # 条件 1：准入约束（H_j + ell_succ_ij <= F_j + eps；正文 V-B.5）
                if H_j[j] + e["ell_succ"] > view.servers[j]["F_j"] + eps_cmp:
                    continue
                # 条件 2：tentative RCLA 可行（防御性检查；条件 1 已保证 floor 可行）
                tent_members = members[j] + [i]
                rcla_tent = _solve_server_tentative(
                    view, tent_members, j, rcla_cfg, eps_cmp
                )
                if rcla_tent is None:
                    continue  # 防御：不应发生（条件 1 已保证可行）
                f_new = rcla_tent
                dphi = (2.0 * Q_j[j] * s_i[i] + s_i[i] * s_i[i]) / view.servers[j]["F_j"]
                delta_phi_dist.append(dphi)
                exact_dphi = (
                    (Q_j[j] + s_i[i]) ** 2 - Q_j[j] ** 2
                ) / view.servers[j]["F_j"]
                max_epsilon_dphi = max(max_epsilon_dphi, abs(dphi - exact_dphi))
                # 条件 3：P0 字典序改善（正文 V-B.6）
                phase2_candidate_edge_count += 1
                d_rbar, d_u = _phase2_deltas(view, i, j, members[j], F_cur, f_new)
                if d_rbar <= -eps_cmp:
                    gate_rejected_dRbar += 1
                    continue
                if utility_gate and abs(d_rbar) <= eps_cmp and d_u <= eps_cmp:
                    gate_rejected_utility += 1
                    continue
                phase2_gate_passed_count += 1
                cand = (d_rbar, d_u, dphi, j)
                if best is None or _better_phase2(
                    cand,
                    best,
                    eps_cmp=eps_cmp,
                    alloc_aware=alloc_aware,
                    utility_gate=utility_gate,
                ):
                    best = cand
            if best is not None:
                best_j = best[3]
                A[i][best_j] = 1
                members[best_j].append(i)
                Q_j[best_j] += s_i[i]
                H_j[best_j] += view.edges[(i, best_j)]["ell_succ"]
                G_j[best_j] += view.edges[(i, best_j)]["ell_R"]  # 诊断同步（E0/E2 语义）
                # 更新该服务器成员分配（tentative RCLA 结果）
                tent_F = _solve_server_tentative(
                    view, members[best_j], best_j, rcla_cfg, eps_cmp
                )
                if tent_F is not None:
                    for k in members[best_j]:
                        F_cur[k][best_j] = tent_F[k]
                utility_offload += 1
                offloads[view.task_ids[i]] = {
                    "server": view.server_ids[best_j],
                    "delta_Rbar_eff": float(best[0]),
                    "delta_U_sys": float(best[1]),
                    "delta_phi": float(best[2]),
                }
    t_p2_end = time.monotonic()

    # ---- X = sum_j A_ij ----
    for i in range(n):
        X[i] = sum(A[i])

    diagnostics = {
        "aada_variant": variant,
        "local_success_count": int(len(local_success)),
        "local_failure_count": int(len(local_failure)),
        "rescued_local_failure_count": int(rescued),
        "no_feasible_edge_count": int(no_feasible),
        "utility_improving_offload_count": int(utility_offload),
        "phase2_candidate_edge_count": int(phase2_candidate_edge_count),
        "phase2_gate_passed_count": int(phase2_gate_passed_count),
        "phase2_gate_rejected_dRbar_count": int(gate_rejected_dRbar),
        "phase2_gate_rejected_utility_count": int(gate_rejected_utility),
        "max_epsilon_dphi": float(max_epsilon_dphi),
        "per_server_final_Q": [float(v) for v in Q_j],
        "per_server_final_G": [float(v) for v in G_j],
        "per_server_G_over_F": [
            float(G_j[j] / view.servers[j]["F_j"]) for j in range(m)
        ],
        "delta_phi_distribution": [float(v) for v in delta_phi_dist],
        "phase1_selected": phase1_selected,
        "phase2_offloads": offloads,
        "edge_assigned_count": int(sum(X)),
        "local_assigned_count": int(n - sum(X)),
        "phase1_runtime_ms": float((t_p1_end - t_p1) * 1000.0),
        "phase2_runtime_ms": float((t_p2_end - t_p2) * 1000.0),
        "runtime_ms": float((time.monotonic() - t0) * 1000.0),
    }
    return {
        "offloading_decision": X,
        "assignment_matrix": A,
        "diagnostics": diagnostics,
        "current_allocation": F_cur,
        "members": members,
    }


def _solve_server_tentative(view, tent_members: List[int], j: int, rcla_cfg: Dict, eps_cmp: float):
    """对服务器 j 的 tentative 成员求解 RCLA，返回 {task_idx: f} 或 None（不可行）。"""
    from cars.methods.cars.rcla import solve_server

    floors = [view.edges[(i, j)]["ell_succ"] for i in tent_members]
    alphas = [view.tasks[i]["a_i"] for i in tent_members]
    F_j = view.servers[j]["F_j"]
    alloc, _diag = solve_server(
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
        return None
    return {tent_members[idx]: alloc[idx] for idx in range(len(tent_members))}
