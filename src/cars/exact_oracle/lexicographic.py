# -*- coding: utf-8 -*-
"""P0 objective tuple + frozen equality comparator + deterministic tie-break（E4-EXACT-1）。

依据：E4-EXACT-0 冻结的 objective hierarchy（TSSR → Rbar_eff → Ubar_eff；
experiment_docs/III_VII.md IV-D）、数值容差 eps_cmp=1.0e-9（Contract V4 §7）。

禁止 weighted sum / normalize 后相加 / 为效率改变 objective priority。
"""

from __future__ import annotations

from typing import Sequence, Tuple

EPS_CMP = 1.0e-9  # 判定比较绝对容差（R2/Contract V4 §7 冻结；不得事后选择）


def objective_tuple(evaluator_output: dict) -> Tuple[float, float, float]:
    """从公共 Evaluator output 提取 P0 三层字典序目标 (TSSR, Rbar_eff, Ubar_eff)。

    Evaluator output 的 system_metrics 字段（evaluator_io schema）：
      tssr, mean_effective_reliability, mean_effective_utility。
    """
    sm = evaluator_output["system_metrics"]
    return (
        float(sm["tssr"]),
        float(sm["mean_effective_reliability"]),
        float(sm["mean_effective_utility"]),
    )


def lex_compare(a: Sequence[float], b: Sequence[float], eps: float = EPS_CMP) -> int:
    """字典序比较：a 相对 b。

    返回：
      1  -> a 严格更优
      -1 -> b 严格更优
      0  -> 三层目标均在 eps 内等价（进入 deterministic tie-break 域）

    逻辑：先比 Tier-1（TSSR）；Tier-1 等价才比 Tier-2（Rbar_eff）；
    前两层等价才比 Tier-3（Ubar_eff）。不是加权和。
    """
    if len(a) != 3 or len(b) != 3:
        raise ValueError("P0 objective tuple 必须为 3 层")
    for x, y in zip(a, b):
        if abs(x - y) > eps:
            return 1 if x > y else -1
    return 0


def deterministic_tie_break_chosen(first_tup, candidate_tup, eps: float = EPS_CMP) -> bool:
    """deterministic canonical tie-break：目标完全等价时保持先遇到的候选（枚举顺序确定性）。

    只决定"多个 P0-equivalent optimum 中返回哪一个"，不改变 P0 最优值（Contract V4 §6）。
    枚举顺序由 discrete_enumerator / oracle 的确定性顺序决定（task_id/server_id 升序）。
    """
    return lex_compare(first_tup, candidate_tup, eps) == 0
