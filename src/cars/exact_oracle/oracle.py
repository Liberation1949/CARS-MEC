# -*- coding: utf-8 -*-
"""Exact Oracle 总流程（E4-EXACT-1；E4_EXACT_ORACLE_CONTRACT_V1 §7 返回格式）。

总流程：
  Scenario
  -> enumerate X/A（discrete_enumerator，确定性）
  -> safe feasibility pruning（feasibility；PRUNE-A/B）
  -> exact F solve（continuous_solver；每服务器 KKT/active-set，Route A）
  -> construct Pi={X,A,F}
  -> common Evaluator（cars.evaluator.evaluator.evaluate）
  -> lexicographic compare（lexicographic.lex_compare，3 层）
  -> best Pi + exactness certificate（certificate.build_certificate）

Oracle 是 reference solver，不注册为论文 baseline；不读取 CARS 输出；
不修改公共模型/Evaluator/CARS；本模块不访问 formal seeds。
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from typing import Callable, Dict, List, Optional, Tuple

import cars.exact_oracle.certificate as cert
import cars.exact_oracle.continuous_solver as continuous_solver
import cars.exact_oracle.discrete_enumerator as discrete_enumerator
import cars.exact_oracle.feasibility as feasibility

from cars.evaluator.evaluator import evaluate as default_evaluate
from cars.evaluator.status_codes import EvaluatorStatus
from cars.exact_oracle.lexicographic import EPS_CMP, lex_compare, objective_tuple
from cars.exact_oracle.model import OracleModel
from cars.simulator.derived_state import DerivedState

DECISION_SCHEMA_VERSION = "CARS_ACTIVE_SCHEMA_V4"
EVALUATOR_ID = "cars.evaluator"
EVALUATOR_VERSION = "CARS_R2_EVALUATOR_CONTRACT_V1"


def _server_capacity(model: OracleModel, j: int) -> float:
    return model.scenario["servers"][j]["capacity_cycles_per_sec"]


def _build_decision(
    model: OracleModel,
    X: List[int],
    A: List[List[int]],
    F: List[List[float]],
) -> Dict:
    return {
        "schema_version": DECISION_SCHEMA_VERSION,
        "offloading_decision": list(X),
        "assignment_matrix": [list(row) for row in A],
        "resource_allocation": [list(row) for row in F],
    }


def solve_exact(
    scenario: Dict,
    derived: Optional[DerivedState] = None,
    *,
    solver_cfg: Optional[Dict] = None,
    mode: str = discrete_enumerator.EXACT_PRUNED,
    evaluator: Optional[Callable] = None,
) -> Dict:
    """求解当前 Scenario 的 P0 lexicographic global optimum。

    返回：
      {
        "oracle_status": str,
        "decision": dict | None,
        "objective_tuple": [TSSR, Rbar_eff, Ubar_eff] | None,
        "evaluator_status": str | None,
        "certificate": dict,
        "server_solutions": dict | None（诊断用）,
      }
    """
    cfg = solver_cfg or {}
    eps_cmp = float(cfg.get("eps_cmp", EPS_CMP))
    max_iter = int(cfg.get("max_iter", 200))
    zero_min = float(cfg.get("zero_floor_min_resource", 1.0))  # MATH-FMIN-CR-R2: f_min^exec=1.0
    # unsafe pruning 拒绝：请求未登记规则 -> 报错
    requested_pruning = list(cfg.get("safe_pruning_rules", []) or [])
    if requested_pruning:
        feasibility.validate_pruning_request(requested_pruning)
    pruning_used = sorted(set(requested_pruning) | {"PRUNE-A"})
    if mode == discrete_enumerator.EXACT_PRUNED:
        pruning_used = sorted(set(pruning_used) | {"PRUNE-B"})

    derived = derived if derived is not None else DerivedState(scenario)
    model = OracleModel(scenario, derived)
    ev_fn = evaluator if evaluator is not None else default_evaluate

    doomed = (
        set(feasibility.doomed_tasks(model))
        if mode == discrete_enumerator.EXACT_PRUNED
        else set()
    )

    n, m = model.n, model.m
    best: Optional[Tuple] = None  # (tup, evaluator_output, decision)
    best_server_sols: Optional[Dict] = None

    stats = {
        "visited_states": 0,
        "infeasible_states": 0,
        "feasible_states": 0,
        "safely_pruned_states": 0,
    }

    for X, A in discrete_enumerator.enumerate_xa(model, mode=mode):
        # 每服务器的 EDGE 任务集
        groups: Dict[int, List[int]] = defaultdict(list)
        for i in range(n):
            for j in range(m):
                if A[i][j] == 1:
                    groups[j].append(i)

        # 每服务器成功集子集（PRUNE-B：排除 doomed 任务 -> 固定失败）
        per_server_subsets: List[List[List[int]]] = []
        for j in range(m):
            g = [i for i in groups[j] if i not in doomed]
            if mode == discrete_enumerator.EXACT_PRUNED:
                stats["safely_pruned_states"] += (len(groups[j]) - len(g))
            subsets = [
                list(combo)
                for r in range(len(g) + 1)
                for combo in itertools.combinations(g, r)
            ]
            per_server_subsets.append(subsets)

        for combo in itertools.product(*per_server_subsets):
            stats["visited_states"] += 1
            server_sols: Dict[int, Dict] = {}
            feasible = True
            for j in range(m):
                S_j = combo[j]
                tasks = [dict(model.edge(i, j)) for i in S_j]
                sol = continuous_solver.solve_server(
                    tasks,
                    _server_capacity(model, j),
                    eps_cmp=eps_cmp,
                    max_iter=max_iter,
                    zero_floor_min_resource=zero_min,
                )
                if sol is None:
                    feasible = False
                    break
                server_sols[j] = sol
            if not feasible:
                stats["infeasible_states"] += 1
                continue

            F = [[0.0] * m for _ in range(n)]
            for j, sol in server_sols.items():
                for i, fval in sol["f"].items():
                    F[i][j] = fval

            decision = _build_decision(model, X, A, F)
            ev = ev_fn(scenario, decision, derived)
            if ev["evaluator_status"] != EvaluatorStatus.VALID:
                stats["infeasible_states"] += 1
                continue
            stats["feasible_states"] += 1
            tup = objective_tuple(ev["evaluator_output"])
            if best is None or lex_compare(tup, best[0], eps=eps_cmp) > 0:
                best = (tup, ev["evaluator_output"], decision)
                best_server_sols = server_sols

    # ------------------------------------------------------------------
    # 构造 certificate
    # ------------------------------------------------------------------
    if best is None:
        oracle_status = cert.INFEASIBLE
        residuals = None
        best_tup = None
        decision = None
        server_sols = None
    else:
        cap = 0.0
        rel = 0.0
        kkt = 0.0
        for j, sol in best_server_sols.items():
            cap = max(cap, sol["capacity_residual"])
            rel = max(rel, sol["reliability_residual"])
            kkt = max(kkt, sol["kkt_residual"])
        residuals = {
            "primal_residual": max(cap, rel),
            "capacity_residual": cap,
            "reliability_residual": rel,
            "kkt_residual": kkt,
        }
        # Tier-3 证书字段：聚合各服务器连续求解的 Tier-2 最优集规模 / Tier-3
        # tie-break 应用 / zero-floor 分配模式（E4 Tier-3 完整性记录）
        t2_sizes = [sol.get("tier2_optimal_set_size", 1) for sol in best_server_sols.values()]
        t3_applied = any(sol.get("tier3_tiebreak_applied", False) for sol in best_server_sols.values())
        zero_modes = [sol.get("zero_alloc_mode", "EPSILON") for sol in best_server_sols.values()]
        residuals["tier2_optimal_set_size_max"] = max(t2_sizes) if t2_sizes else 1
        residuals["tier3_tiebreak_applied"] = bool(t3_applied)
        residuals["zero_alloc_mode"] = "WATERFILL" if "WATERFILL" in zero_modes else "EPSILON"
        best_tup = list(best[0])
        decision = best[2]
        if (
            kkt <= 10.0 * eps_cmp
            and cap <= 10.0 * eps_cmp
            and rel <= 10.0 * eps_cmp
        ):
            oracle_status = cert.CERTIFIED_NUMERICAL_EXACT
        else:
            oracle_status = cert.NOT_EXACT
        server_sols = best_server_sols

    c = cert.build_certificate(
        oracle_status=oracle_status,
        total_discrete_states=discrete_enumerator.theoretical_state_bound(model),
        visited_states=stats["visited_states"],
        safely_pruned_states=stats["safely_pruned_states"],
        infeasible_states=stats["infeasible_states"],
        feasible_states=stats["feasible_states"],
        best_objective_tuple=best_tup,
        decision=decision,
        exactness_mode=(
            "CERTIFIED_NUMERICAL_EXACT"
            if oracle_status in cert.VALID_REFERENCE_STATUSES
            else oracle_status
        ),
        residuals=residuals,
        pruning_rules_used=pruning_used,
        unsafe_pruning_used=False,
        evaluator_id=EVALUATOR_ID,
        evaluator_version=EVALUATOR_VERSION,
        mode=mode,
        timeout_used=False,
    )
    return {
        "oracle_status": oracle_status,
        "decision": decision,
        "objective_tuple": best_tup,
        "evaluator_status": "VALID" if best is not None else None,
        "certificate": c,
        "server_solutions": server_sols,
    }
