# -*- coding: utf-8 -*-
"""JTORA-adapted 卸载决策（原文 Algorithm 2 + Routine 1 忠实转写）与主管线。

依据：references/JTORA-adapted.PDF Section V-C（Algorithm 2）+ 本子阶段适配合同。

Algorithm 2 转写要点：
- Step 2-3：best-single 初始化 Y = {argmax J*({x})}（ground set 升序遍历，
  严格大于 -> 并列取先到者，确定性）；
- Step 4-10：remove/exchange 局部改进，改进因子 (1+delta)（原文 Step 4/7）；
  - remove：Y 剔除一个元素 x 后 J* 最大的候选；
  - exchange：加入 (i,j)、移除任务 i 现有卸载（Routine 1 适配，无子带）；
  - 每外层 = remove 阶段 + exchange 阶段；无改进则停止；
  - 迭代上界 max_outer_iterations（适配合同 iteration_budget 冻结）；
- J* 用 Eq.29（materialized transmission + CRA 闭式）；Y 为空 -> J*=0。

reference（use_cache=False）与 production（use_cache=True）共用本模块；
唯一差异为目标评价缓存（frozenset 纯函数缓存，结果字节级等价）。

预算/截止期：oracle 返回 None（软截止期触发）-> 标准 TIMEOUT（incumbent 仅诊断）；
无随机性 -> method_seed 不影响结果。
"""

from __future__ import annotations

import time
from typing import Dict, FrozenSet, List, Optional, Sequence, Tuple

from cars.methods.jtora_adapted import config_validator
from cars.methods.jtora_adapted import diagnostics as diag_mod
from cars.methods.jtora_adapted import resource_allocation as ra_mod
from cars.methods.jtora_adapted import server_selection as ss_mod
from cars.methods.jtora_adapted.numerical_solver import source_objective_value
from cars.methods.jtora_adapted.source_cost import SourceCosts
from cars.methods.protocol import MethodContext, MethodProposal
from cars.simulator.derived_state import DerivedState

NEG_INF = float("-inf")


def _deadline_exceeded(start_monotonic: float, soft_deadline_seconds: float) -> bool:
    return time.monotonic() - start_monotonic >= soft_deadline_seconds


class SourceObjectiveOracle:
    """Y -> J*(Y) 评价器（frozenset 缓存；软截止期检查）。"""

    def __init__(
        self,
        costs: SourceCosts,
        derived: DerivedState,
        soft_deadline_seconds: float,
        start_monotonic: float,
        use_cache: bool = False,
        sleep_seconds_per_eval: float = 0.0,
    ) -> None:
        self.costs = costs
        self.derived = derived
        self.soft_deadline_seconds = float(soft_deadline_seconds)
        self.start = float(start_monotonic)
        self.use_cache = bool(use_cache)
        self.sleep_seconds_per_eval = float(sleep_seconds_per_eval)
        self.count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.unique_count = 0
        self.soft_deadline_triggered = False
        self._cache: Dict[FrozenSet, float] = {}
        self._seen: set = set()

    def evaluate(self, Y: Sequence[Tuple[int, int]]):
        """返回 J*(frozenset(Y))；软截止期触发时返回 None。"""
        key = frozenset(Y)
        if self.use_cache and key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        if key not in self._seen:
            self._seen.add(key)
            self.unique_count += 1
        if self._deadline_exceeded():
            self.soft_deadline_triggered = True
            return None
        if self.sleep_seconds_per_eval > 0.0:
            time.sleep(self.sleep_seconds_per_eval)
        v = source_objective_value(key, self.costs, self.derived)
        self.count += 1
        self.cache_misses += 1
        if self.use_cache:
            self._cache[key] = v
        return v

    def _deadline_exceeded(self) -> bool:
        return time.monotonic() - self.start >= self.soft_deadline_seconds


def _best_single(oracle: SourceObjectiveOracle, G: List[Tuple[int, int]]):
    """[Algorithm 2 Step 2] argmax J*({x})；并列取 ground set 序先者。

    返回 (best, best_val)；G 为空返回 (None, None)。
    """
    best = None
    best_val = None
    for x in G:
        v = oracle.evaluate([x])
        if v is None:
            return None, None  # 截止期触发
        if best is None or v > best_val:
            best = x
            best_val = v
    return best, best_val


def run_offloading_search(
    oracle: SourceObjectiveOracle,
    costs: SourceCosts,
    derived: DerivedState,
    max_outer_iterations: int,
    delta: float,
):
    """[Algorithm 2] 返回 (Y, J_final, stats) 或 None（截止期触发）。

    stats: dict（offloading_changes, completed_outer, stopping_reason, history）。
    """
    G = ss_mod.ground_set(costs)
    if not G:
        return frozenset(), 0.0, {
            "offloading_changes": 0,
            "completed_outer": 0,
            "stopping_reason": "all_local_no_edges",
            "history": [0.0],
            "initial_best_single": None,
        }

    best, best_val = _best_single(oracle, G)
    if best is None:
        return None  # 截止期触发
    Y: FrozenSet = frozenset({best})
    J_cur = best_val
    history = [J_cur]
    offloading_changes = 0
    stopping_reason = "max_outer_iterations"
    completed_outer = 0

    for outer in range(max_outer_iterations):
        improved_outer = False
        # remove 阶段（Algorithm 2 Step 4-6）
        while True:
            best_remove = None
            best_remove_val = None
            for x in Y:
                cand = frozenset(Y - {x})
                v = oracle.evaluate(cand)
                if v is None:
                    return None
                if best_remove is None or v > best_remove_val:
                    best_remove = x
                    best_remove_val = v
            if best_remove is not None and best_remove_val > (1.0 + delta) * J_cur:
                Y = frozenset(Y - {best_remove})
                J_cur = best_remove_val
                offloading_changes += 1
                improved_outer = True
            else:
                break
        # exchange 阶段（Algorithm 2 Step 7-9）
        while True:
            best_ex = None
            best_ex_val = None
            for (i, j) in G:
                if (i, j) in Y:
                    continue
                cand = ss_mod.exchange_set(Y, i, j)
                v = oracle.evaluate(cand)
                if v is None:
                    return None
                if best_ex is None or v > best_ex_val:
                    best_ex = (i, j)
                    best_ex_val = v
            if best_ex is not None and best_ex_val > (1.0 + delta) * J_cur:
                Y = frozenset(ss_mod.exchange_set(Y, best_ex[0], best_ex[1]))
                J_cur = best_ex_val
                offloading_changes += 1
                improved_outer = True
            else:
                break
        completed_outer = outer + 1
        history.append(J_cur)
        if not improved_outer:
            stopping_reason = "no_improvement"
            break

    return Y, J_cur, {
        "offloading_changes": offloading_changes,
        "completed_outer": completed_outer,
        "stopping_reason": stopping_reason,
        "history": history,
        "initial_best_single": best,
    }


def _build_decision(Y: FrozenSet, F: List[List[float]], costs: SourceCosts) -> Dict:
    """从最终执行位置唯一提取 X/A（§2.2）+ F（Eq.27）。"""
    n = costs.n
    m = costs.m
    in_y = [False] * n
    for (i, j) in Y:
        in_y[i] = True
    X = [1 if in_y[i] else 0 for i in range(n)]
    A = [[0] * m for _ in range(n)]
    for (i, j) in Y:
        A[i][j] = 1
    return {
        "schema_version": "CARS_ACTIVE_SCHEMA_V1",
        "offloading_decision": X,
        "assignment_matrix": A,
        "resource_allocation": [[float(v) for v in row] for row in F],
    }


def run_jtora(ctx: MethodContext, use_cache: bool) -> MethodProposal:
    """执行 JTORA-adapted（Algorithm 2 + CRA 闭式）。use_cache 控制评价缓存。"""
    cfg = config_validator.validate_config(ctx.config)
    costs = SourceCosts(ctx.scenario, ctx.derived)
    oracle = SourceObjectiveOracle(
        costs,
        ctx.derived,
        soft_deadline_seconds=ctx.soft_deadline_seconds,
        start_monotonic=ctx.start_monotonic,
        use_cache=use_cache,
        sleep_seconds_per_eval=cfg["_test_hook_sleep_seconds_per_evaluation"],
    )
    res = run_offloading_search(
        oracle,
        costs,
        ctx.derived,
        max_outer_iterations=cfg["max_outer_iterations"],
        delta=cfg["improvement_factor_delta"],
    )
    runtime = time.monotonic() - ctx.start_monotonic
    soft_triggered = oracle.soft_deadline_triggered or _deadline_exceeded(
        ctx.start_monotonic, ctx.soft_deadline_seconds
    )

    oracle_stats = {
        "use_cache": oracle.use_cache,
        "count": oracle.count,
        "cache_hits": oracle.cache_hits,
        "cache_misses": oracle.cache_misses,
        "unique_count": oracle.unique_count,
    }

    if res is None:
        diag = diag_mod.build_diagnostics(
            ctx, cfg, oracle_stats, None, None, None,
            source_objective_final=None, history=[], stopping_reason="soft_deadline",
            soft_triggered=True, timeout_phase="offloading_search", runtime=runtime,
        )
        return MethodProposal(
            decision=None,
            method_status="TIMEOUT",
            timed_out=True,
            runtime_seconds=runtime,
            diagnostics=diag,
        )

    Y, J_final, stats = res

    if soft_triggered:
        diag = diag_mod.build_diagnostics(
            ctx, cfg, oracle_stats, Y, J_final, stats,
            source_objective_final=J_final, history=stats["history"],
            stopping_reason=stats["stopping_reason"],
            soft_triggered=True, timeout_phase="after_search", runtime=runtime,
        )
        diag["incumbent_decision"] = None
        return MethodProposal(
            decision=None,
            method_status="TIMEOUT",
            timed_out=True,
            runtime_seconds=runtime,
            diagnostics=diag,
        )

    F = ra_mod.allocate_resources(Y, costs, ctx.derived)
    decision = _build_decision(Y, F, costs)
    diag = diag_mod.build_diagnostics(
        ctx, cfg, oracle_stats, Y, J_final, stats,
        source_objective_final=J_final, history=stats["history"],
        stopping_reason=stats["stopping_reason"],
        soft_triggered=False, timeout_phase=None, runtime=runtime,
    )
    return MethodProposal(
        decision=decision,
        method_status="SUCCESS",
        timed_out=False,
        runtime_seconds=runtime,
        diagnostics=diag,
    )
