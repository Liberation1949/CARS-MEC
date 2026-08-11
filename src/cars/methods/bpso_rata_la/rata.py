# -*- coding: utf-8 -*-
"""RATA：可靠性感知任务指派（原文 Algorithm 1 / Theorem 1）。

依据：bpso-rata-la.pdf Section V（Algorithm 1）+ 本子阶段适配合同
（R3_BPSO_RATA_LA_adaptation_contract.yaml assignment_rule）。

冻结语义（Algorithm 1 lines 5-9 为图片不可提取 -> POSSIBLE_INTERPRETATION，
依据 Theorem 1 的 z_1>=...>=z_M 排序目标与正文 prose 冻结）：
1. 任务排序：Gamma_off 按 nu_i*c_i 非升序（并列按任务编号升序）。
2. ES 排序：按 y_j = lambda_j/F_j 非降序（并列按服务器编号升序）。
3. 逐任务指派：每任务选物理有效（e_phy=1）且当前累计 z_j 最小的 ES；
   并列时选 ES 排序序列中更靠前者；指派后 z_j += nu_i*c_i。
4. 物理边适配：仅物理有效边为候选；若任务无任何物理有效服务器 ->
   返回 None（粒子 assignment infeasible）。

确定性：所有输入来自 scenario + DerivedState（T0），无未来信息；
无随机数；reference 与 optimized 共用本函数（等价保证）。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from cars.simulator.derived_state import DerivedState


def task_vulnerability(task: Dict) -> float:
    """任务脆弱性指标 nu_i * c_i（Eq.17 z_j 的逐任务分量）。"""
    return float(task["fragility"]) * float(task["cpu_cycles"])


def server_vulnerability(derived: DerivedState, j: int) -> float:
    """ES 脆弱性指标 y_j = lambda_j / F_j（Theorem 1；固定名义故障率）。"""
    st = derived.server_state[j]
    return float(st["lambda_j"]) / float(st["F_j"])


def server_priority_order(derived: DerivedState) -> List[int]:
    """ES 排序：按 y_j = lambda_j/F_j 非降序；并列按服务器编号升序。"""
    m = len(derived.server_ids)
    idx = list(range(m))
    idx.sort(key=lambda j: (server_vulnerability(derived, j), j))
    return idx


def offloaded_task_order(X: Sequence[int], scenario: Dict, derived: DerivedState) -> List[int]:
    """Gamma_off 任务排序：按 nu_i*c_i 非升序；并列按任务编号升序。"""
    n = len(derived.task_ids)
    offloaded = [i for i in range(n) if X[i] == 1]
    offloaded.sort(key=lambda i: (-task_vulnerability(scenario["tasks"][i]), i))
    return offloaded


def assign_tasks(
    X: Sequence[int], scenario: Dict, derived: DerivedState
) -> Optional[Tuple[List[List[int]], List[float]]]:
    """[Algorithm 1] 固定 X 生成指派 A（贪心平衡，物理边跳过）。

    返回 (A, z_j) 或 None（某卸载任务无任何物理有效服务器 -> 粒子 infeasible）。
    不修改 X（只读）；不读取任何未来/修复/RUAD/CALA 状态。
    """
    n = len(derived.task_ids)
    m = len(derived.server_ids)
    server_prio = server_priority_order(derived)
    z: List[float] = [0.0] * m
    A: List[List[int]] = [[0] * m for _ in range(n)]

    for i in offloaded_task_order(X, scenario, derived):
        nu_c = task_vulnerability(scenario["tasks"][i])
        best_j = None
        best_key = None
        for rank, j in enumerate(server_prio):
            ls = derived.link(i, j)
            if ls is None or ls["e_phy"] != 1:
                continue  # 物理无效边跳过
            key = (z[j], rank, j)
            if best_key is None or key < best_key:
                best_j = j
                best_key = key
        if best_j is None:
            return None  # 无物理有效服务器 -> assignment infeasible
        A[i][best_j] = 1
        z[best_j] += nu_c

    return A, z
