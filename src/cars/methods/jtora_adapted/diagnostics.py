# -*- coding: utf-8 -*-
"""JTORA-adapted 诊断构建（提示词 §3.6 冻结字段）。

不伪造正式 Evaluator 指标；全部字段来自方法内部实际运行证据。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from cars.methods.protocol import MethodContext


def build_diagnostics(
    ctx: MethodContext,
    cfg: Dict,
    oracle_stats: Dict,
    Y,
    J_final: Optional[float],
    stats: Optional[Dict],
    source_objective_final: Optional[float],
    history: List[float],
    stopping_reason: str,
    soft_triggered: bool,
    timeout_phase: Optional[str],
    runtime: float,
) -> Dict:
    """构建方法诊断（§3.6 字段 + 运行计数）。

    oracle_stats: dict（use_cache/count/cache_hits/cache_misses/unique_count）。
    """
    source_initial = history[0] if history else None
    oracle_count = oracle_stats.get("count", 0)
    return {
        "method": "jtora_adapted",
        "use_cache": oracle_stats.get("use_cache"),
        "outer_iterations": (stats or {}).get("completed_outer", 0),
        "max_outer_iterations": cfg["max_outer_iterations"],
        "source_objective_initial": source_initial,
        "source_objective_final": source_objective_final,
        "source_objective_history": list(history),
        "offloading_changes": (stats or {}).get("offloading_changes", 0),
        "server_assignment_changes": (stats or {}).get("offloading_changes", 0),
        "resource_solver_calls": oracle_count,
        "convex_subproblem_calls": oracle_count,
        "source_objective_calls": oracle_count,
        "source_objective_cache_hits": oracle_stats.get("cache_hits", 0),
        "source_objective_cache_misses": oracle_stats.get("cache_misses", 0),
        "unique_sets_evaluated": oracle_stats.get("unique_count", 0),
        "binary_search_calls": 0,  # 功率固定（场景输入）；Algorithm 1 不调用
        "binary_search_iterations": 0,
        "max_binary_search_iterations": cfg["max_binary_search_iterations"],
        "feasible_iterations": (stats or {}).get("completed_outer", 0),
        "nonconvergent_subproblems": 0,
        "numerical_tolerance": {
            "absolute": cfg["absolute_tolerance"],
            "relative": cfg["relative_tolerance"],
        },
        "improvement_factor_delta": cfg["improvement_factor_delta"],
        "stopping_reason": stopping_reason,
        "offloaded_tasks": len(Y) if Y is not None else None,
        "soft_deadline_triggered": soft_triggered,
        "timeout_phase": timeout_phase,
        "cleanup_completed": True,  # 进程内无子进程；进程树清理由 Runner 记录
        "elapsed_method_seconds": runtime,
    }
