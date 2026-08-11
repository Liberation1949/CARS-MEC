# -*- coding: utf-8 -*-
"""LA：效用最优资源分配（原文 Algorithm 2 / Theorem 3 / Eq.25）。

依据：bpso-rata-la.pdf Section VI（Algorithm 2）+ 本子阶段适配合同
（R3_BPSO_RATA_LA_adaptation_contract.yaml resource_allocation_rule）。

冻结语义（Theorem 3 / Eq.25 闭式）：
对每个有任务的 ES j（Gamma_j 非空）：
  f*_ij = F_j * sqrt(alpha_i * f_i^loc) / sum_{tau_k in Gamma_j} sqrt(alpha_k * f_k^loc)
容量守恒：sum_{Gamma_j} f*_ij = F_j（满足 Eq.14 等号）。
正资源：alpha_i>0 且 f_i^loc>0 -> f*_ij > 0（满足 Eq.13）。
未指派边 f_ij=0；无任务的 ES 无分配。

确定性：所有输入来自 scenario + DerivedState（T0）+ 固定 (X,A)；
无随机数；reference 与 optimized 共用本函数。
"""

from __future__ import annotations

import math
from typing import Dict, List, Sequence

from cars.simulator.derived_state import DerivedState


def _local_cpu_rate(scenario: Dict, i: int) -> float:
    """任务 i 所属设备的本地计算速率 f_i^loc（cycles/s）。"""
    task = scenario["tasks"][i]
    for dev in scenario["devices"]:
        if dev["device_id"] == task["device_id"]:
            return float(dev["local_cpu_rate"])
    raise ValueError("device not found for task %r" % task["task_id"])


def _la_weight(scenario: Dict, i: int) -> float:
    """LA 权重 w_i = sqrt(alpha_i * f_i^loc)（Eq.25）。"""
    alpha = float(scenario["tasks"][i]["delay_weight"])
    f_loc = _local_cpu_rate(scenario, i)
    return math.sqrt(alpha * f_loc)


def allocate_resources(
    X: Sequence[int], A: Sequence[Sequence[int]], scenario: Dict, derived: DerivedState
) -> List[List[float]]:
    """[Algorithm 2 / Eq.25] 固定 (X,A) 生成 F。不修改 X/A（只读）。"""
    n = len(derived.task_ids)
    m = len(derived.server_ids)
    F: List[List[float]] = [[0.0] * m for _ in range(n)]

    for j in range(m):
        gamma_j = [i for i in range(n) if A[i][j] == 1]
        if not gamma_j:
            continue  # 无任务的 ES 无分配
        weights = {i: _la_weight(scenario, i) for i in gamma_j}
        denom = sum(weights.values())
        if denom <= 0.0:
            raise ValueError("LA denominator must be positive (alpha_i>0, f_loc>0)")
        F_j = float(derived.server_state[j]["F_j"])
        for i in gamma_j:
            F[i][j] = F_j * weights[i] / denom

    return F
