# -*- coding: utf-8 -*-
"""BPSO 主循环（原文 Algorithm 3 忠实转写；reference 与 optimized 共用）。

依据：bpso-rata-la.pdf Section VII（Algorithm 3, Eq.34/37/38）+ 本子阶段
适配合同（R3_BPSO_RATA_LA_adaptation_contract.yaml）。

Algorithm 3 转写要点：
- lines 1-5 随机二进制初始化 K 粒子、pbest_k = p_k、计算每粒子 fitness；
- line 6 gbest = 最大 fitness 者；
- lines 7-21 while 迭代 L 次：逐粒子更新速度(Eq.34)+位置(Eq.37/38) ->
  按 X 划分 Gamma_loc/Gamma_off -> RATA(Algorithm 1)+LA(Algorithm 2) 后
  计算 fitness(Eq.10) 与 R_sys(Eq.9) -> 效用更大更新 pbest/gbest；
- line 22-23 结束后检查可靠性：最终 = gbest_feasible（搜索中满足
  R_sys>=R_th 的效用最优者；论文目标为满足可靠性约束下最大化效用）；
  不存在 -> 标准 BUDGET_EXHAUSTED（不伪造成功）。

reference（use_cache=False）与 optimized（use_cache=True）共用本主循环与
全部确定性组件（rata/la/source_objective）；唯一差异为目标评价缓存
（纯函数缓存，结果字节级等价）。缓存只影响 fitness 计算，不影响 RNG 抽取
顺序（速度/位置更新先于评价，cache 命中不跳过随机数）。
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Sequence, Tuple

from cars.common.deterministic import make_rng
from cars.evaluator import metrics
from cars.methods.protocol import MethodContext, MethodProposal
from cars.methods.bpso_rata_la import config as bpso_config
from cars.methods.bpso_rata_la import la as la_mod
from cars.methods.bpso_rata_la import rata as rata_mod
from cars.methods.bpso_rata_la.source_objective import source_fitness_and_reliability

# 判定/比较容差（与 evaluator_contract.yaml §5 eps_cmp 一致）
EPS = 1.0e-9
NEG_INF = float("-inf")


def _deadline_exceeded(ctx: MethodContext) -> bool:
    return time.monotonic() - ctx.start_monotonic >= ctx.soft_deadline_seconds


# ---------------------------------------------------------------------------
# BPSO 更新原语（Eq.34 / Eq.37 / Eq.38；纯函数，可注入显式随机数）
# ---------------------------------------------------------------------------


class ListDraws:
    """显式随机数列表源（测试/人工案例用；接口与 random.Random 子集一致）。"""

    def __init__(self, values: Sequence[float]) -> None:
        self._values = list(values)
        self._idx = 0

    def random(self) -> float:
        if self._idx >= len(self._values):
            raise RuntimeError("ListDraws exhausted (%d values)" % len(self._values))
        v = self._values[self._idx]
        self._idx += 1
        return v


def update_velocity(
    vel_row: Sequence[float],
    pop_row: Sequence[int],
    pbest_row: Sequence[int],
    gbest_row: Sequence[int],
    inertia: float,
    c1: float,
    c2: float,
    draws,
) -> List[float]:
    """[Eq.34] v_k,i(l) = varrho*v + zeta1*eta1*(pbest-p) + zeta2*eta2*(gbest-p)。

    draws 提供逐维两个 random()（eta1, eta2 in (0,1)）。
    """
    n = len(pop_row)
    out = [0.0] * n
    for i in range(n):
        eta1 = draws.random()
        eta2 = draws.random()
        out[i] = (
            inertia * float(vel_row[i])
            + c1 * eta1 * float(pbest_row[i] - pop_row[i])
            + c2 * eta2 * float(gbest_row[i] - pop_row[i])
        )
    return out


def transfer_probability(v: float) -> float:
    """[Eq.38] V 型转移函数 S(v) = v^2 / (1 + v^2)。"""
    return (v * v) / (1.0 + v * v)


def update_position(vel_row: Sequence[float], draws) -> List[int]:
    """[Eq.37] p_k,i = 1 if rand() < S(v_k,i) else 0（S 由 Eq.38 给出）。

    draws 提供逐维 random()（rand() in [0,1)）。
    """
    return [1 if draws.random() < transfer_probability(float(v)) else 0 for v in vel_row]


# ---------------------------------------------------------------------------
# 粒子评价器（预算计数 + 软截止期检查；cache 开关等价）
# ---------------------------------------------------------------------------


class ParticleEvaluator:
    """X -> (fitness, R_sys, A, F) 评价器。

    - count：实际（非缓存命中）粒子评价次数；<= cap；
    - assignment infeasible（RATA 返回 None）-> (NEG_INF, 0.0, None, None)；
    - 软截止期触发 -> soft_deadline_triggered=True；
    - cap 达到 -> cap_reached=True；
    - use_cache=True 时按 X 元组缓存（RATA+LA+fitness 为 X 的纯函数）。
    """

    def __init__(
        self,
        scenario: Dict,
        derived,
        cap: int,
        soft_deadline_seconds: float,
        start_monotonic: float,
        use_cache: bool = False,
        sleep_seconds_per_eval: float = 0.0,
    ) -> None:
        self.scenario = scenario
        self.derived = derived
        self.cap = int(cap)
        self.soft_deadline_seconds = float(soft_deadline_seconds)
        self.start = float(start_monotonic)
        self.use_cache = bool(use_cache)
        self.sleep_seconds_per_eval = float(sleep_seconds_per_eval)
        self.count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.unique_count = 0  # 去重后的唯一粒子数（reference/production 一致）
        self.cap_reached = False
        self.soft_deadline_triggered = False
        self.assignment_infeasible_count = 0
        self._cache: Dict[Tuple, Tuple] = {}
        self._seen: set = set()

    def _deadline_exceeded(self) -> bool:
        return time.monotonic() - self.start >= self.soft_deadline_seconds

    def evaluate(self, X: Sequence[int]):
        """返回 (fitness, R_sys, A, F)；预算/截止期触发时返回 None。"""
        key = tuple(X)
        if key not in self._seen:
            self._seen.add(key)
            self.unique_count += 1
        if self.use_cache and key in self._cache:
            self.cache_hits += 1
            return self._cache[key]
        if self.count >= self.cap:
            self.cap_reached = True
            return None
        if self._deadline_exceeded():
            self.soft_deadline_triggered = True
            return None
        if self.sleep_seconds_per_eval > 0.0:
            time.sleep(self.sleep_seconds_per_eval)

        az = rata_mod.assign_tasks(X, self.scenario, self.derived)
        if az is None:
            result = (NEG_INF, 0.0, None, None)
            self.assignment_infeasible_count += 1
        else:
            A, _z = az
            F = la_mod.allocate_resources(X, A, self.scenario, self.derived)
            fitness, rsys = source_fitness_and_reliability(X, A, F, self.scenario, self.derived)
            result = (fitness, rsys, A, F)
        self.count += 1
        self.cache_misses += 1
        if self.use_cache:
            self._cache[key] = result
        return result


# ---------------------------------------------------------------------------
# 决策构建与最终选择
# ---------------------------------------------------------------------------


def build_decision(X: Sequence[int], A: Sequence[Sequence[int]], F: Sequence[Sequence[float]]) -> Dict:
    """构造 Schema 决策 dict {X,A,F}。"""
    return {
        "schema_version": "CARS_ACTIVE_SCHEMA_V1",
        "offloading_decision": [int(v) for v in X],
        "assignment_matrix": [[int(v) for v in row] for row in A],
        "resource_allocation": [[float(v) for v in row] for row in F],
    }


def _select_final(best_feasible, best_valid):
    """最终解选择（合同 infeasible_particle_policy / 最终解规则）。

    返回 (decision, method_status, rel_satisfied, final_rel, reason)：
    - best_feasible 存在 -> SUCCESS（R_sys>=R_th）；
    - 否则 best_valid 存在 -> BUDGET_EXHAUSTED（无可靠性可行解，返回效用最优
      物理合法 incumbent，不伪造成功；reliability_constraint_satisfied=False）；
    - 否则 -> METHOD_ERROR（预算内无任何合法决策）。
    """
    if best_feasible is not None:
        X, A, F, _fit, rs = best_feasible
        return build_decision(X, A, F), "SUCCESS", True, rs, "feasible_found"
    if best_valid is not None:
        X, A, F, _fit, rs = best_valid
        return (
            build_decision(X, A, F),
            "BUDGET_EXHAUSTED",
            False,
            rs,
            "no_feasible_solution",
        )
    return None, "METHOD_ERROR", False, None, "no_valid_decision"


def _common_diag(
    cfg: Dict,
    evaluator: ParticleEvaluator,
    completed_iterations: int,
    feasible_count: int,
    best_feasible,
    best_valid,
    gbest,
    gbest_fitness,
    best_fitness_history,
    gbest_update_count,
    soft_triggered,
    timeout_phase,
    reason,
    rel_satisfied,
    final_rel,
    runtime,
):
    """公共诊断字段。"""
    return {
        "method": "bpso_rata_la",
        "use_cache": evaluator.use_cache,
        "completed_iterations": completed_iterations,
        "max_iterations": cfg["max_iterations"],
        "population_size": cfg["population_size"],
        "particle_evaluations": evaluator.count,
        "particle_evaluation_cap": cfg["particle_evaluation_cap"],
        "unique_particles_evaluated": evaluator.unique_count,
        "cache_hits": evaluator.cache_hits,
        "cache_misses": evaluator.cache_misses,
        "rata_calls": evaluator.cache_misses,
        "la_calls": evaluator.cache_misses - evaluator.assignment_infeasible_count,
        "assignment_infeasible_count": evaluator.assignment_infeasible_count,
        "feasible_particle_count": feasible_count,
        "initial_best_fitness": best_fitness_history[0] if best_fitness_history else None,
        "final_best_fitness": gbest_fitness,
        "best_fitness_history": list(best_fitness_history),
        "gbest_update_count": gbest_update_count,
        "reliability_threshold": cfg["reliability_threshold"],
        "final_reliability": final_rel,
        "reliability_constraint_satisfied": bool(rel_satisfied),
        "final_selection_reason": reason,
        "gbest_particle": gbest,
        "soft_deadline_triggered": soft_triggered,
        "timeout_phase": timeout_phase,
        "incumbent_available": best_valid is not None,
        "cleanup_completed": True,  # 进程内无子进程；进程树清理由 Runner 记录
        "elapsed_method_seconds": runtime,
    }


def run_bpso(ctx: MethodContext, use_cache: bool) -> MethodProposal:
    """执行 BPSO-RATA-LA（Algorithm 3 转写）。use_cache 控制评价缓存。"""
    cfg = bpso_config.validate_config(ctx.config)
    n = len(ctx.derived.task_ids)
    rng = make_rng(ctx.method_seed)
    K = cfg["population_size"]
    L = cfg["max_iterations"]
    cap = cfg["particle_evaluation_cap"]
    inertia = cfg["inertia_weight"]
    c1 = cfg["cognitive_coefficient"]
    c2 = cfg["social_coefficient"]
    r_th = cfg["reliability_threshold"]
    sleep = cfg["_test_hook_sleep_seconds_per_evaluation"]

    evaluator = ParticleEvaluator(
        ctx.scenario,
        ctx.derived,
        cap=cap,
        soft_deadline_seconds=ctx.soft_deadline_seconds,
        start_monotonic=ctx.start_monotonic,
        use_cache=use_cache,
        sleep_seconds_per_eval=sleep,
    )

    # 可行/合法解跟踪
    best_feasible: Optional[Tuple] = None  # (X, A, F, fitness, R_sys)；R_sys>=R_th
    best_valid: Optional[Tuple] = None  # (X, A, F, fitness, R_sys)；A 有效
    feasible_count = 0  # 唯一可行粒子数（按 X 去重；reference/production 一致）
    feasible_X: set = set()

    def _record(X, A, F, fitness, rsys):
        nonlocal best_feasible, best_valid, feasible_count
        if A is None:
            return
        if best_valid is None or fitness > best_valid[3]:
            best_valid = (list(X), A, F, fitness, rsys)
        if rsys >= r_th - EPS:
            key = tuple(X)
            if key not in feasible_X:
                feasible_X.add(key)
                feasible_count += 1
            if best_feasible is None or fitness > best_feasible[3]:
                best_feasible = (list(X), A, F, fitness, rsys)

    def _eval_particle(X):
        """评价粒子；仅真实（cache miss）评价时更新可行/合法跟踪。

        返回 res 或 None；cache 命中不重复计数（同 X 恒同 fitness/R_sys）。
        """
        before = evaluator.count
        res = evaluator.evaluate(X)
        if res is None:
            return None
        if evaluator.count > before:  # 真实评价（cache miss）
            f, rs, A, F = res
            _record(X, A, F, f, rs)
        return res

    # Algorithm 3 lines 1-5：随机二进制初始化 + pbest_k = p_k + 初始评价
    pop = [[1 if rng.random() < 0.5 else 0 for _ in range(n)] for _ in range(K)]
    vel = [[0.0] * n for _ in range(K)]
    pbest = [list(p) for p in pop]
    fitness_k = [NEG_INF] * K
    rsys_k = [0.0] * K

    for k in range(K):
        res = _eval_particle(pop[k])
        if res is None:
            return _stop_proposal(
                ctx, cfg, evaluator, feasible_count, best_feasible, best_valid,
                phase="initial_evaluation", completed_iterations=0,
                gbest=None, gbest_fitness=None, best_fitness_history=[],
                gbest_update_count=0,
            )
        fitness_k[k], rsys_k[k], A, F = res

    # Algorithm 3 line 6：gbest = 最大 fitness 者（并列取先到者，确定性）
    gbest_idx = max(range(K), key=lambda k: fitness_k[k])
    gbest = list(pop[gbest_idx])
    gbest_fitness = fitness_k[gbest_idx]
    gbest_update_count = 0
    best_fitness_history = [gbest_fitness]

    # Algorithm 3 lines 7-21：while 迭代 L 次
    completed_iterations = 0
    for it in range(L):
        if _deadline_exceeded(ctx):
            return _stop_proposal(
                ctx, cfg, evaluator, feasible_count, best_feasible, best_valid,
                phase="iteration_start", completed_iterations=it,
                gbest=gbest, gbest_fitness=gbest_fitness,
                best_fitness_history=best_fitness_history,
                gbest_update_count=gbest_update_count,
            )
        for k in range(K):
            # line 9：速度 (Eq.34) 后位置 (Eq.37 with Eq.38)
            vel[k] = update_velocity(vel[k], pop[k], pbest[k], gbest, inertia, c1, c2, rng)
            pop[k] = update_position(vel[k], rng)
            # lines 10-13：评价（RATA + LA + fitness/R_sys）
            res = _eval_particle(pop[k])
            if res is None:
                return _stop_proposal(
                    ctx, cfg, evaluator, feasible_count, best_feasible, best_valid,
                    phase="iteration_inner", completed_iterations=it + 1,
                    gbest=gbest, gbest_fitness=gbest_fitness,
                    best_fitness_history=best_fitness_history,
                    gbest_update_count=gbest_update_count,
                )
            f, rs, A, F = res
            # lines 14-16：pbest 更新（严格大于）
            if f > fitness_k[k]:
                pbest[k] = list(pop[k])
                fitness_k[k] = f
            # lines 17-19：gbest 更新（严格大于）
            if f > gbest_fitness:
                gbest = list(pop[k])
                gbest_fitness = f
                gbest_update_count += 1
        completed_iterations = it + 1
        best_fitness_history.append(gbest_fitness)

    # lines 22-23：最终可靠性检查 -> 最终解选择
    runtime = time.monotonic() - ctx.start_monotonic
    decision, status, rel_satisfied, final_rel, reason = _select_final(
        best_feasible, best_valid
    )
    diag = _common_diag(
        cfg, evaluator, completed_iterations, feasible_count, best_feasible, best_valid,
        gbest, gbest_fitness, best_fitness_history, gbest_update_count,
        soft_triggered=False, timeout_phase=None, reason=reason,
        rel_satisfied=rel_satisfied, final_rel=final_rel, runtime=runtime,
    )
    diag["no_feasible_solution"] = (best_feasible is None) and (best_valid is not None)
    return MethodProposal(
        decision=decision,
        method_status=status,
        timed_out=False,
        runtime_seconds=runtime,
        diagnostics=diag,
    )


def _stop_proposal(
    ctx: MethodContext,
    cfg: Dict,
    evaluator: ParticleEvaluator,
    feasible_count: int,
    best_feasible,
    best_valid,
    phase: str,
    completed_iterations: int,
    gbest,
    gbest_fitness,
    best_fitness_history,
    gbest_update_count: int,
) -> MethodProposal:
    """预算/截止期触发的停止处理（Contract Part 9.1/9.4）。

    - soft deadline -> 标准 TIMEOUT（incumbent 仅诊断，不按成功计分）；
    - particle_evaluation_cap -> BUDGET_EXHAUSTED（返回当前最优决策并正常评价）。
    """
    runtime = time.monotonic() - ctx.start_monotonic
    soft_triggered = evaluator.soft_deadline_triggered or _deadline_exceeded(ctx)

    decision, status, rel_satisfied, final_rel, reason = _select_final(
        best_feasible, best_valid
    )

    if soft_triggered:
        diag = _common_diag(
            cfg, evaluator, completed_iterations, feasible_count, best_feasible, best_valid,
            gbest, gbest_fitness, best_fitness_history, gbest_update_count,
            soft_triggered=True, timeout_phase=phase, reason=reason,
            rel_satisfied=rel_satisfied, final_rel=final_rel, runtime=runtime,
        )
        diag["incumbent_decision"] = decision  # 诊断用，不按成功计分
        return MethodProposal(
            decision=None,
            method_status="TIMEOUT",
            timed_out=True,
            runtime_seconds=runtime,
            diagnostics=diag,
        )

    if decision is None:
        diag = _common_diag(
            cfg, evaluator, completed_iterations, feasible_count, best_feasible, best_valid,
            gbest, gbest_fitness, best_fitness_history, gbest_update_count,
            soft_triggered=False, timeout_phase=phase, reason=reason,
            rel_satisfied=rel_satisfied, final_rel=final_rel, runtime=runtime,
        )
        diag["failure"] = "no_incumbent_available"
        return MethodProposal(
            decision=None,
            method_status="METHOD_ERROR",
            timed_out=False,
            runtime_seconds=runtime,
            diagnostics=diag,
        )

    diag = _common_diag(
        cfg, evaluator, completed_iterations, feasible_count, best_feasible, best_valid,
        gbest, gbest_fitness, best_fitness_history, gbest_update_count,
        soft_triggered=False, timeout_phase=phase, reason=reason,
        rel_satisfied=rel_satisfied, final_rel=final_rel, runtime=runtime,
    )
    diag["budget_exhausted"] = True
    diag["budget_exhausted_reason"] = "particle_evaluation_cap"
    return MethodProposal(
        decision=decision,
        method_status="BUDGET_EXHAUSTED",
        timed_out=False,
        runtime_seconds=runtime,
        diagnostics=diag,
    )
