# -*- coding: utf-8 -*-
"""NFA-adapted 主循环（Algorithm 3 忠实转写；reference 与 optimized 共用）。

reference（use_cache=False）与 optimized（use_cache=True）共用本主循环与全部
确定性组件（映射/移动/解码/目标/composite heuristic）；唯一差异为目标评价缓存
（纯函数缓存，结果字节级等价）。

Algorithm 3 转写要点：
- Line 2 种群初始化（position_bounds 内逐维均匀抽样）；
- Line 4 composite heuristic 生成初始最优解 pi*；
- Line 5 随机选最亮萤火虫 b；
- Lines 6-13 初始评价（r*_i = dist(X_i, X_b) -> mapping -> 目标 -> 更新 best）；
- Lines 14-27 while t < MaxGeneration：双循环 i,j，I_j > I_i 时移动(Eq.14)+
  重映射+重评价+更新 best-so-far。
"""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Tuple

from cars.common.deterministic import make_rng
from cars.methods.protocol import MethodContext, MethodProposal
from cars.methods.nfa_adapted import config as nfa_config
from cars.methods.nfa_adapted.decode import (
    ObjectiveEvaluator,
    composite_heuristic,
    decode_pi,
    euclidean_distance,
    lex_gt,
    mapping,
    move_firefly,
)


def _deadline_exceeded(ctx: MethodContext) -> bool:
    return time.monotonic() - ctx.start_monotonic >= ctx.soft_deadline_seconds


def _stop_proposal(
    ctx: MethodContext,
    evaluator: ObjectiveEvaluator,
    pi_star: Optional[List[int]],
    timeout_phase: str,
    completed_generations: int,
    completed_moves: int,
    mapping_calls: int,
) -> MethodProposal:
    """预算/截止期触发的停止处理（Contract Part 9.1/9.4）。

    - soft deadline -> 标准 TIMEOUT（incumbent 仅诊断，不按成功计分）；
    - objective_evaluation_cap -> BUDGET_EXHAUSTED（返回 incumbent 并正常评价）。
    """
    runtime = time.monotonic() - ctx.start_monotonic
    soft_triggered = evaluator.soft_deadline_triggered or _deadline_exceeded(ctx)

    incumbent_decision = decode_pi(pi_star, ctx.scenario, ctx.derived) if pi_star is not None else None

    base_diag = {
        "completed_generations": completed_generations,
        "completed_pairwise_moves": completed_moves,
        "objective_evaluations": evaluator.count,
        "mapping_calls": mapping_calls,
        "decode_calls": evaluator.cache_misses,
        "cache_hits": evaluator.cache_hits,
        "cache_misses": evaluator.cache_misses,
        "soft_deadline_triggered": soft_triggered,
        "timeout_phase": timeout_phase,
        "incumbent_available": pi_star is not None,
        "cleanup_completed": True,  # 进程内无子进程；进程树清理由 Runner 记录
        "elapsed_method_seconds": runtime,
        "objective_evaluation_cap": evaluator.cap,
    }

    if soft_triggered:
        diag = dict(base_diag)
        diag["incumbent_decision"] = incumbent_decision  # 诊断用，不按成功计分
        return MethodProposal(
            decision=None,
            method_status="TIMEOUT",
            timed_out=True,
            runtime_seconds=runtime,
            diagnostics=diag,
        )

    if incumbent_decision is None:
        # 防御：无任何目标评价成功（不应发生；cap>0 且本地恒可行）
        diag = dict(base_diag)
        diag["failure"] = "no_incumbent_available"
        return MethodProposal(
            decision=None,
            method_status="METHOD_ERROR",
            timed_out=False,
            runtime_seconds=runtime,
            diagnostics=diag,
        )

    diag = dict(base_diag)
    diag["budget_exhausted"] = True
    return MethodProposal(
        decision=incumbent_decision,
        method_status="BUDGET_EXHAUSTED",
        timed_out=False,
        runtime_seconds=runtime,
        diagnostics=diag,
    )


def run_nfa(ctx: MethodContext, use_cache: bool) -> MethodProposal:
    """执行 NFA-adapted（Algorithm 3 转写）。use_cache 控制目标评价缓存。"""
    cfg = nfa_config.validate_config(ctx.config)
    n = len(ctx.derived.task_ids)
    rng = make_rng(ctx.method_seed)
    bounds = cfg["position_bounds"]
    pop_size = cfg["population_size"]
    max_gen = cfg["max_generations"]
    beta0 = cfg["beta_0"]
    gamma = cfg["gamma"]
    cap = cfg["objective_evaluation_cap"]
    sleep = cfg["_test_hook_sleep_seconds_per_evaluation"]

    evaluator = ObjectiveEvaluator(
        ctx.scenario,
        ctx.derived,
        cap=cap,
        soft_deadline_seconds=ctx.soft_deadline_seconds,
        start_monotonic=ctx.start_monotonic,
        use_cache=use_cache,
        sleep_seconds_per_eval=sleep,
        weights=cfg.get("objective_weights"),
    )

    completed_generations = 0
    completed_moves = 0
    mapping_calls = 0

    # Algorithm 3 Line 2：种群初始化
    pop = [[rng.uniform(bounds[0], bounds[1]) for _ in range(n)] for _ in range(pop_size)]

    # Algorithm 3 Line 4：composite heuristic -> pi*
    pi_star, obj_star, stopped = composite_heuristic(
        ctx.scenario, ctx.derived, evaluator.evaluate
    )
    if stopped:
        return _stop_proposal(ctx, evaluator, pi_star, "composite_heuristic", 0, 0, mapping_calls)

    # Algorithm 3 Line 5：随机选最亮萤火虫
    b = rng.randint(0, pop_size - 1)

    # Algorithm 3 Lines 6-13：初始评价
    r_star: List[float] = [0.0] * pop_size
    I: List[Optional[Tuple]] = [None] * pop_size
    pi_list: List[Optional[List[int]]] = [None] * pop_size
    for i in range(pop_size):
        r_star[i] = euclidean_distance(pop[i], pop[b])
        pi_list[i] = mapping(pi_star, r_star[i], rng)
        mapping_calls += 1
        obj = evaluator.evaluate(pi_list[i])
        if obj is None:
            return _stop_proposal(
                ctx, evaluator, pi_star, "initial_evaluation", 0, completed_moves, mapping_calls
            )
        I[i] = obj
        if lex_gt(obj, obj_star):
            b = i
            pi_star = pi_list[i]
            obj_star = obj

    # Algorithm 3 Lines 14-27：while t < MaxGeneration
    t = 0
    while t < max_gen:
        if _deadline_exceeded(ctx):
            return _stop_proposal(
                ctx, evaluator, pi_star, "generation_start", completed_generations, completed_moves, mapping_calls
            )
        for i in range(pop_size):
            for j in range(pop_size):
                if I[i] is None or I[j] is None:
                    continue
                if lex_gt(I[j], I[i]):
                    eps = [rng.random() for _ in range(n)]
                    pop[i] = move_firefly(pop[i], pop[j], r_star[i], eps, beta0, gamma, bounds)
                    completed_moves += 1
                    r_star[i] = euclidean_distance(pop[i], pop[b])
                    pi_list[i] = mapping(pi_star, r_star[i], rng)
                    mapping_calls += 1
                    obj = evaluator.evaluate(pi_list[i])
                    if obj is None:
                        return _stop_proposal(
                            ctx, evaluator, pi_star, "generation_inner", completed_generations, completed_moves, mapping_calls
                        )
                    I[i] = obj
                    if lex_gt(obj, obj_star):
                        b = i
                        pi_star = pi_list[i]
                        obj_star = obj
        t += 1
        completed_generations = t

    # 正常完成：最终解码 pi* -> Pi
    decision = decode_pi(pi_star, ctx.scenario, ctx.derived)
    runtime = time.monotonic() - ctx.start_monotonic
    diagnostics = {
        "method": "nfa_adapted",
        "use_cache": use_cache,
        "completed_generations": completed_generations,
        "max_generations": max_gen,
        "completed_pairwise_moves": completed_moves,
        "objective_evaluations": evaluator.count,
        "mapping_calls": mapping_calls,
        "decode_calls": evaluator.cache_misses + 1,  # 含最终解码
        "cache_hits": evaluator.cache_hits,
        "cache_misses": evaluator.cache_misses,
        "soft_deadline_triggered": False,
        "timeout_phase": None,
        "incumbent_available": True,
        "cleanup_completed": True,
        "elapsed_method_seconds": runtime,
        "objective_evaluation_cap": cap,
        "internal_objective": list(obj_star),
        "best_sequence": pi_star,
    }
    return MethodProposal(
        decision=decision,
        method_status="SUCCESS",
        timed_out=False,
        runtime_seconds=runtime,
        diagnostics=diagnostics,
    )
