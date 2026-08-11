# -*- coding: utf-8 -*-
"""Exactness certificate 构造（E4-EXACT-1）。

依据：E4_EXACT_ORACLE_CONTRACT_V1 §7（Exactness Certificate 字段）、
configs/e4_exact/e4_exact_metric_definitions.yaml §6。

oracle_status 枚举：EXACT_OPTIMAL / CERTIFIED_NUMERICAL_EXACT / INFEASIBLE /
TIMEOUT_UNCERTIFIED / SOLVER_ERROR / NOT_EXACT。
只有 EXACT_OPTIMAL / CERTIFIED_NUMERICAL_EXACT 可作为未来 E4 Formal 的 Oracle reference。
"""

from __future__ import annotations

import hashlib
import json
from typing import Dict, List, Optional

EXACT_OPTIMAL = "EXACT_OPTIMAL"
CERTIFIED_NUMERICAL_EXACT = "CERTIFIED_NUMERICAL_EXACT"
INFEASIBLE = "INFEASIBLE"
TIMEOUT_UNCERTIFIED = "TIMEOUT_UNCERTIFIED"
SOLVER_ERROR = "SOLVER_ERROR"
NOT_EXACT = "NOT_EXACT"

VALID_REFERENCE_STATUSES = (EXACT_OPTIMAL, CERTIFIED_NUMERICAL_EXACT)


def canonical_solution_hash(decision: Dict) -> str:
    """对决策 {X,A,F} 的确定性 SHA-256（canonical solution hash）。"""
    raw = json.dumps(decision, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def build_certificate(
    *,
    oracle_status: str,
    total_discrete_states: int,
    visited_states: int,
    safely_pruned_states: int,
    infeasible_states: int,
    feasible_states: int,
    best_objective_tuple: Optional[List[float]],
    decision: Optional[Dict],
    exactness_mode: str,
    residuals: Optional[Dict],
    pruning_rules_used: List[str],
    unsafe_pruning_used: bool,
    evaluator_id: str,
    evaluator_version: str,
    mode: str,
    timeout_used: bool,
) -> Dict:
    """构造机器可读 exactness certificate（字段见 Contract §7）。"""
    return {
        "oracle_status": oracle_status,
        "total_discrete_states": total_discrete_states,
        "visited_states": visited_states,
        "safely_pruned_states": safely_pruned_states,
        "infeasible_states": infeasible_states,
        "feasible_states": feasible_states,
        "best_objective_tuple": best_objective_tuple,
        "canonical_solution_hash": (
            canonical_solution_hash(decision) if decision is not None else None
        ),
        "exactness_mode": exactness_mode,
        "primal_residual": residuals.get("primal_residual") if residuals else None,
        "capacity_residual": residuals.get("capacity_residual") if residuals else None,
        "reliability_residual": residuals.get("reliability_residual") if residuals else None,
        "kkt_residual": residuals.get("kkt_residual") if residuals else None,
        "tier2_optimal_set_size_max": residuals.get("tier2_optimal_set_size_max") if residuals else None,
        "tier3_tiebreak_applied": residuals.get("tier3_tiebreak_applied") if residuals else None,
        "zero_alloc_mode": residuals.get("zero_alloc_mode") if residuals else None,
        "branch_bound_gap": None,
        "unsafe_pruning_used": bool(unsafe_pruning_used),
        "evaluator_id": evaluator_id,
        "evaluator_version": evaluator_version,
        "enumerator_mode": mode,
        "timeout_used": bool(timeout_used),
    }
