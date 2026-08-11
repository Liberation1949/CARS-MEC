# -*- coding: utf-8 -*-
"""NFA-adapted 共享核心（映射算子 / 移动 / 解码 / 内部目标 / composite heuristic）。

依据：references/NFA.pdf（Algorithm 1 距离型映射、Eq.13/14 移动、Algorithm 2
composite heuristic）+ 本子阶段适配合同（R3_NFA_adaptation_contract.yaml）。

共享原则：
- 所有确定性函数在此单一实现（reference 与 optimized 共用），保证等价；
- 随机数（映射 λ/插入、移动 eps、种群初始化）一律来自显式 seeded RNG
  （Contract Part 7：无全局随机状态）；
- 解码恒返回 Pi in Omega_phy（本地回退保证 C1-C6）；
- 内部目标与 Evaluator 共享同一套 F-19..F-22（Contract Part 6.6 Scorer=Evaluator）。
"""

from __future__ import annotations

import math
import time
from typing import Dict, List, Optional, Sequence, Tuple

from cars.evaluator import constraints
from cars.evaluator import metrics
from cars.simulator.derived_state import DerivedState

# 判定/比较容差（与 evaluator_contract.yaml §5 eps_cmp 一致）
EPS = 1.0e-9
# 映射继承概率上限（NFA.pdf IV-B：p 上限 0.95）
P_CAP = 0.95


def _is_finite(v) -> bool:
    return isinstance(v, (int, float)) and math.isfinite(v)


# ---------------------------------------------------------------------------
# 几何与移动（NFA.pdf Eq.13 / Eq.14）
# ---------------------------------------------------------------------------


def euclidean_distance(x: Sequence[float], y: Sequence[float]) -> float:
    """[Eq.13] r_ij = sqrt(sum_l (X_il - X_jl)^2)。"""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(x, y)))


def attractiveness(r: float, beta0: float, gamma: float) -> float:
    """[Eq.12/14] beta0 * exp(-gamma * r^2)。"""
    return beta0 * math.exp(-gamma * r * r)


def move_firefly(
    x_i: Sequence[float],
    x_j: Sequence[float],
    r_star_i: float,
    eps: Sequence[float],
    beta0: float,
    gamma: float,
    bounds: Sequence[float],
) -> List[float]:
    """[Eq.14] X_i = X_i + beta0*exp(-gamma*r_ij^2)*(X_j - X_i) + r*_i*(eps - 1/2)。

    eps 为逐维 [0,1] 均匀随机数（RNG 提供）；r_ij 由 x_i/x_j 计算；
    移动后逐维 clamp 到 position_bounds（适配合同 position_boundary_policy）。
    """
    r_ij = euclidean_distance(x_i, x_j)
    att = attractiveness(r_ij, beta0, gamma)
    lo, hi = bounds
    out = []
    for l in range(len(x_i)):
        v = x_i[l] + att * (x_j[l] - x_i[l]) + r_star_i * (eps[l] - 0.5)
        out.append(min(max(v, lo), hi))
    return out


# ---------------------------------------------------------------------------
# 距离型映射算子（NFA.pdf Algorithm 1）
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


def mapping(pi_star: Sequence[int], r_star: float, draws, p_cap: float = P_CAP) -> List[int]:
    """[Algorithm 1] 距离型映射算子：萤火虫 -> 任务序列。

    - Step 1：按概率 p = min(e^{-r*_i}, 0.95) 继承 pi* 中任务（保持 pi* 顺序）；
    - Step 2：剩余任务（保持 pi* 顺序）均匀插入当前序列（位置 0..len）。
    draws 提供 .random() -> [0,1)（RNG 或 ListDraws）。
    """
    p = min(math.exp(-r_star), p_cap)
    n = len(pi_star)
    pi: List[int] = []
    inherited = [False] * n
    for j in range(n):
        lam = draws.random()
        if lam <= p:
            pi.append(pi_star[j])
            inherited[j] = True
    for j in range(n):
        if inherited[j]:
            continue
        u = draws.random()
        pos = int(u * (len(pi) + 1))  # 均匀插入位置 [0, len(pi)]
        pi.insert(pos, pi_star[j])
    return pi


# ---------------------------------------------------------------------------
# 解码：任务序列 -> Pi={X,A,F}（适配合同 mec_decoding_to_X_A_F；替代 FTA 角色）
# ---------------------------------------------------------------------------


def _task_candidates(task_idx: int, used: List[float], scenario: Dict, derived: DerivedState) -> List[Dict]:
    """任务 i 的候选（本地 + 可行边），按键 (1-qos, T_est, E_est, f_req, index) 排序最小。"""
    loc = derived.task_local[task_idx]
    task = scenario["tasks"][task_idx]
    c = task["cpu_cycles"]
    candidates = [
        {
            "kind": "local",
            "j": -1,
            "qos": loc["b_loc"],
            "T_est": loc["T_loc"],
            "E_est": loc["E_loc"],
            "f_req": 0.0,
            "index": 0,
        }
    ]
    for j in range(len(derived.server_ids)):
        ls = derived.link(task_idx, j)
        if ls is None or ls["e_phy"] != 1:
            continue
        ell_succ = ls["ell_succ"]
        if not _is_finite(ell_succ):
            continue
        F_j = derived.server_state[j]["F_j"]
        if ell_succ > F_j - used[j] + EPS:
            continue  # 容量余量不足（C6 构造性满足）
        candidates.append(
            {
                "kind": "edge",
                "j": j,
                "qos": 1,  # f=ell_succ 时 T<=D 且 R>=R_min（ell_succ 语义）
                "T_est": ls["T_tx"] + c / ell_succ,
                "E_est": ls["E_tx"],
                "f_req": ell_succ,
                "index": j + 1,
            }
        )
    candidates.sort(
        key=lambda cand: (1 - cand["qos"], cand["T_est"], cand["E_est"], cand["f_req"], cand["index"])
    )
    return candidates


def decode_pi(pi: Sequence[int], scenario: Dict, derived: DerivedState) -> Dict:
    """确定性贪心 QoS 感知列表调度：任务序列 pi -> Pi={X,A,F}。

    处理顺序 = pi 顺序；每任务选键最小候选；本地回退保证 Pi in Omega_phy。
    只使用 T0 DerivedState + 当前部分指派 used_j；无未来信息。
    """
    n = len(derived.task_ids)
    m = len(derived.server_ids)
    X = [0] * n
    A = [[0] * m for _ in range(n)]
    F = [[0.0] * m for _ in range(n)]
    used = [0.0] * m

    for task_idx in pi:
        candidates = _task_candidates(task_idx, used, scenario, derived)
        best = candidates[0]  # 已按键排序，键最小
        if best["kind"] == "local":
            X[task_idx] = 0
        else:
            j = best["j"]
            X[task_idx] = 1
            A[task_idx][j] = 1
            f_req = best["f_req"]
            F[task_idx][j] = f_req
            used[j] += f_req

    return {
        "schema_version": "CARS_ACTIVE_SCHEMA_V1",
        "offloading_decision": X,
        "assignment_matrix": A,
        "resource_allocation": F,
    }


# ---------------------------------------------------------------------------
# 内部目标（F-19..F-22, F-40/F-41；与 Evaluator 共享原语）
# ---------------------------------------------------------------------------


def internal_objective(decision: Dict, scenario: Dict, derived: DerivedState, weights=None) -> Tuple:
    """内部目标。weights=None 返回 (z_count, Rsum, Usum) 字典序（原版，等价 P0 乘 N）；
    weights=(w1,w2,w3) 返回 (w1·z/N + w2·Rbar + w3·Ubar,) 加权标量（E1 落实 2026-08-08，
    卸载成功数/效用/可靠性都进入目标）。"""
    cap_flags = constraints.all_cap_flags(scenario, decision)
    x = decision["offloading_decision"]
    a = decision["assignment_matrix"]
    f = decision["resource_allocation"]
    z_count = 0
    rsum = 0.0
    usum = 0.0
    for i in range(len(derived.task_ids)):
        r = metrics.evaluate_task(derived, i, int(x[i]), [int(v) for v in a[i]],
                                  [float(v) for v in f[i]], cap_flags)
        z_count += r["success"]
        rsum += r["effective_reliability"]
        usum += r["effective_utility"]
    if weights is None:
        return (z_count, rsum, usum)
    n = len(derived.task_ids)
    w1, w2, w3 = weights
    score = w1 * (z_count / n) + w2 * (rsum / n) + w3 * (usum / n)
    return (score,)


def lex_gt(a: Tuple, b: Tuple, eps: float = EPS) -> bool:
    """字典序严格大于（容差比较；Contract Part 7.2 严格逐分量）。"""
    for va, vb in zip(a, b):
        if va > vb + eps:
            return True
        if va < vb - eps:
            return False
    return False


def lex_eq(a: Tuple, b: Tuple, eps: float = EPS) -> bool:
    return not lex_gt(a, b, eps) and not lex_gt(b, a, eps)


# ---------------------------------------------------------------------------
# 目标评价器（预算计数 + 软截止期检查；cache 开关等价）
# ---------------------------------------------------------------------------


class ObjectiveEvaluator:
    """π -> objective tuple 评价器。

    - count：实际（非缓存命中）目标评价次数；<= cap；
    - 软截止期触发 -> soft_deadline_triggered=True；
    - cap 达到 -> cap_reached=True；
    - use_cache=True 时按 π 元组缓存解码+目标（纯函数，结果等价）。
    """

    def __init__(
        self,
        scenario: Dict,
        derived: DerivedState,
        cap: int,
        soft_deadline_seconds: float,
        start_monotonic: float,
        use_cache: bool = False,
        sleep_seconds_per_eval: float = 0.0,
        weights: Tuple = None,
    ) -> None:
        self.scenario = scenario
        self.derived = derived
        self.cap = int(cap)
        self.soft_deadline_seconds = float(soft_deadline_seconds)
        self.start = float(start_monotonic)
        self.use_cache = bool(use_cache)
        self.sleep_seconds_per_eval = float(sleep_seconds_per_eval)
        self.weights = weights
        self.count = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.cap_reached = False
        self.soft_deadline_triggered = False
        self._cache: Dict[Tuple, Tuple] = {}

    def _deadline_exceeded(self) -> bool:
        return time.monotonic() - self.start >= self.soft_deadline_seconds

    def evaluate(self, pi: Sequence[int]):
        """返回 objective tuple；预算/截止期触发时返回 None。"""
        key = tuple(pi)
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
        decision = decode_pi(pi, self.scenario, self.derived)
        obj = internal_objective(decision, self.scenario, self.derived, self.weights)
        self.count += 1
        self.cache_misses += 1
        if self.use_cache:
            self._cache[key] = obj
        return obj


# ---------------------------------------------------------------------------
# Composite Heuristic（NFA.pdf Algorithm 2：LTF -> IRM -> SSM）
# ---------------------------------------------------------------------------


def ltf_order(scenario: Dict, derived: DerivedState) -> List[int]:
    """LTF：任务按 T_i^loc 非升序；并列按任务编号升序（适配合同 tie_break）。"""
    n = len(derived.task_ids)
    idx = list(range(n))
    idx.sort(key=lambda i: (-derived.task_local[i]["T_loc"], i))
    return idx


def _ssm_pass(pi_in: Sequence[int], obj_in: Tuple, evaluate) -> Tuple[List[int], Tuple]:
    """SSM 单次扫描（NFA.pdf IV-C 文本）：j 与其后所有任务交换，取每 j 最优。"""
    pi_ssm = list(pi_in)
    obj_ssm = obj_in
    t = len(pi_ssm)
    for j in range(t - 1):
        best_cand = None
        best_obj = None
        for k in range(j + 1, t):
            cand = list(pi_ssm)
            cand[j], cand[k] = cand[k], cand[j]
            obj = evaluate(cand)
            if obj is None:
                return pi_ssm, obj_ssm, True  # stopped
            if best_obj is None or lex_gt(obj, best_obj):
                best_obj = obj
                best_cand = cand
        if best_obj is not None and lex_gt(best_obj, obj_ssm):
            pi_ssm = best_cand
            obj_ssm = best_obj
    return pi_ssm, obj_ssm, False


def composite_heuristic(
    scenario: Dict, derived: DerivedState, evaluate
) -> Tuple[Optional[List[int]], Optional[Tuple], bool]:
    """[Algorithm 2] 生成初始最优解 π_CH。

    返回 (pi_ch, obj_ch, stopped)；stopped=True 表示预算/截止期触发。
    """
    # Step 1: LTF
    pi_ltf = ltf_order(scenario, derived)
    # Step 2: IRM（逐任务插入每个位置，取字典序最优；并列取最小位置）
    pi_irm: List[int] = []
    obj_irm: Optional[Tuple] = None
    for task in pi_ltf:
        best_cand = None
        best_obj = None
        for pos in range(len(pi_irm) + 1):
            cand = pi_irm[:pos] + [task] + pi_irm[pos:]
            obj = evaluate(cand)
            if obj is None:
                return pi_irm, obj_irm, True
            if best_obj is None or lex_gt(obj, best_obj):
                best_obj = obj
                best_cand = cand
        pi_irm = best_cand
        obj_irm = best_obj
    # Step 3: SSM while-improved
    # 不变量：pi_tem 的目标恒等于 obj_ch（初始 pi_irm；改善后同步；无改善重置为 pi_ch）。
    pi_ch = list(pi_irm)
    obj_ch = obj_irm
    pi_tem = list(pi_irm)
    while True:
        pi_ssm, obj_ssm, stopped = _ssm_pass(pi_tem, obj_ch, evaluate)
        if stopped:
            return pi_ch, obj_ch, True
        if lex_gt(obj_ssm, obj_ch):
            pi_tem = list(pi_ssm)
            pi_ch = list(pi_ssm)
            obj_ch = obj_ssm
        else:
            pi_tem = list(pi_ch)
            break
    return pi_ch, obj_ch, False
