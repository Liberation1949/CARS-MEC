# -*- coding: utf-8 -*-
"""Evaluator 指标计算（Contract F-01..F-25, F-38..F-43, F-34；正文 III-C/D/E, IV-C, III-F.4）。

Evaluator 是"照镜子"：只根据实际证据（Scenario + DerivedState + decision）判定，
不修复方法结果。z_i 按 Contract Part 3.2 六条件固定顺序判定，首次失败即返回
并记录失败原因。正式指标仅 evaluator_contract.yaml §2 白名单。
"""

from __future__ import annotations

from typing import Dict, List

from cars.evaluator.status_codes import FailureReason
from cars.simulator import physical_models as pm
from cars.simulator.derived_state import DerivedState

EPS_CMP = 1.0e-9  # 判定比较绝对容差（evaluator_contract.yaml §5）
INF = pm.INF


def _unique_carrier(a_row: List[int]) -> int:
    """[F-07] j_i(A)：唯一指派返回索引；否则返回 -1（空）。"""
    hits = [j for j, v in enumerate(a_row) if v == 1]
    if len(hits) == 1:
        return hits[0]
    return -1


def task_end_to_end_delay(derived: DerivedState, i: int, x_i: int, a_row: List[int], f_row: List[int]):
    """[F-08] T_i(Pi) 分段定义。返回 (T_i, j_carrier 或 -1)。"""
    loc = derived.task_local[i]
    T_loc = loc["T_loc"]
    if x_i == 0 and sum(a_row) == 0:
        return T_loc, -1
    if x_i == 1:
        j = _unique_carrier(a_row)
        if j >= 0 and f_row[j] > 0:
            ls = derived.link(i, j)
            T_tx = ls["T_tx"] if ls is not None else INF
            T_exe = pm.edge_exec_delay(derived.scenario["tasks"][i]["cpu_cycles"], f_row[j])
            return T_tx + T_exe, j
    return INF, -1


def task_reliability(derived: DerivedState, i: int, x_i: int, a_row: List[int], f_row: List[int]):
    """[F-14] R_i(Pi) 分段定义。"""
    loc = derived.task_local[i]
    if x_i == 0 and sum(a_row) == 0:
        return loc["R_loc"]
    if x_i == 1:
        j = _unique_carrier(a_row)
        if j >= 0:
            ls = derived.link(i, j)
            if ls is None:
                return 0.0
            R_tx = ls["R_tx"]
            R_exe = pm.edge_exec_reliability(
                derived.server_state[j]["lambda_j"],
                derived.scenario["tasks"][i]["fragility"],
                derived.scenario["tasks"][i]["cpu_cycles"],
                f_row[j],
            )
            return pm.offloading_reliability(R_tx, R_exe)
    return 0.0


def task_energy(derived: DerivedState, i: int, x_i: int, a_row: List[int], f_row: List[int]):
    """[F-09] E_i(Pi) = (1-x_i)E_loc + x_i sum_j a_ij E_tx。"""
    loc = derived.task_local[i]
    E_loc = loc["E_loc"]
    if x_i == 0:
        return E_loc
    total = 0.0
    for j, a_ij in enumerate(a_row):
        if a_ij == 1:
            ls = derived.link(i, j)
            if ls is not None:
                total += ls["E_tx"]
    return total


def task_utility(derived: DerivedState, i: int, T_i, E_i) -> float:
    """[F-39] U_i = alpha (T_loc - T_i)/T_loc + beta (E_loc - E_i)/E_loc。

    本地执行 U_i=0（T_i=T_loc, E_i=E_loc）。T_i=+inf 时数学上 U_i=-inf，
    由序列化规则闭合为 0（U_i^eff 由 z_i 决定恒为 0，正式指标不受影响）。
    """
    task = derived.scenario["tasks"][i]
    loc = derived.task_local[i]
    T_loc = loc["T_loc"]
    E_loc = loc["E_loc"]
    alpha = task["delay_weight"]
    beta = task["energy_weight"]
    if T_i >= INF:
        return float("-inf")
    return alpha * (T_loc - T_i) / T_loc + beta * (E_loc - E_i) / E_loc


def evaluate_task(derived: DerivedState, i: int, x_i: int, a_row: List[int], f_row: List[int], cap_flags: List[int]) -> Dict:
    """按 Contract Part 3.2 条件顺序判定任务 i，返回 TaskResult 字段。

    无 deadline 模型（E1-CR 2026-08-08）：条件顺序 struct -> path -> exec ->
    cap -> reliability（原 deadline 条件已删除）。
    首次失败即返回 z_i=0 并记录失败原因。cap_flags 为 g_j^cap 数组（F-18，
    维度 M）；容量违约任务按保守评价 z_i=0（CAPACITY_INFEASIBLE，III-E.1）。
    """
    task = derived.scenario["tasks"][i]
    R_min = task["min_reliability"]

    # 条件 1 struct（C1-C2 定义域；约束层已检查，此处防御确认）
    if x_i not in (0, 1) or any(v not in (0, 1) for v in a_row):
        return _task_result(task["task_id"], 0, 0, INF, 0.0, 0.0, 0.0, 0.0, FailureReason.STRUCT_INVALID)

    # 条件 2 path（C3）
    if sum(a_row) != x_i:
        return _task_result(task["task_id"], 0, 0, INF, 0.0, 0.0, 0.0, 0.0, FailureReason.PATH_AMBIGUOUS)

    # 计算 T_i / R_i / E_i（F-08/F-14/F-09）
    T_i, j_carrier = task_end_to_end_delay(derived, i, x_i, a_row, f_row)
    R_i = task_reliability(derived, i, x_i, a_row, f_row)
    E_i = task_energy(derived, i, x_i, a_row, f_row)

    # 条件 3 exec（本地 f_loc>0 恒真；卸载要求 j_i!=null 且 f>0）
    if x_i == 1 and (j_carrier < 0 or f_row[j_carrier] <= 0):
        return _task_result(task["task_id"], 0, 0, T_i, R_i, 0.0, 0.0, 0.0, FailureReason.EXEC_INVALID)

    # 条件 4 cap（F-18/III-E.1）：卸载时 g_j^cap=1；容量违约任务 z_i=0
    if x_i == 1 and (j_carrier < 0 or cap_flags[j_carrier] == 0):
        return _task_result(task["task_id"], 0, 0, T_i, R_i, 0.0, 0.0, 0.0, FailureReason.CAPACITY_INFEASIBLE)

    # 条件 5 reliability（无 deadline 模型：原条件5 deadline 已删除）
    if not (R_i >= R_min - EPS_CMP):
        return _task_result(task["task_id"], 0, 1, T_i, R_i, 0.0, 0.0, 0.0, FailureReason.RELIABILITY_VIOLATION)

    # 全部通过 -> SUCCESS
    U_i = task_utility(derived, i, T_i, E_i)
    return _task_result(task["task_id"], 1, 1, T_i, R_i, R_i, U_i, U_i, FailureReason.SUCCESS)


def _task_result(task_id, success, evaluable, T_i, R_i, R_valid, U_i, U_eff, reason):
    """构造 TaskResult 字典（序列化规则见 evaluator_contract.yaml §6）。

    - end_to_end_delay_seconds：T_i=+inf 时输出显式 sentinel 字符串 "inf"（Contract Part 8.2）；
    - utility：T_i=+inf 时数学上 U_i=-inf，序列化填 0.0（U_i^eff 由 z_i 闭合为 0，正式指标不受影响）。
    """
    delay = "inf" if T_i >= INF else T_i
    util = U_i if (U_i is not None and U_i != float("-inf")) else 0.0
    return {
        "task_id": task_id,
        "success": success,
        "evaluable": evaluable,
        "end_to_end_delay_seconds": delay,
        "end_to_end_reliability": R_i,
        "effective_reliability": R_valid,
        "utility": util,
        "effective_utility": U_eff,
        "failure_reason": reason.value,
    }


def evaluate_all_metrics(derived: DerivedState, decision: Dict, cap_flags: List[int]) -> Dict:
    """对完整 decision 计算逐任务结果与系统指标（Evaluator 的 T4 重算）。"""
    n = len(derived.task_ids)
    x = decision["offloading_decision"]
    a = decision["assignment_matrix"]
    f = decision["resource_allocation"]

    task_results = []
    for i in range(n):
        task_results.append(evaluate_task(derived, i, x[i], a[i], f[i], cap_flags))

    tssr = sum(r["success"] for r in task_results) / n
    rbar = sum(r["effective_reliability"] for r in task_results) / n
    ubar = sum(r["effective_utility"] for r in task_results) / n

    # 无 deadline 模型（E1-CR 2026-08-08）：V_D/V_D_only/V_D_and_R 删除，仅 V_R
    v_r = 0.0
    for i, r in enumerate(task_results):
        if r["evaluable"] != 1:
            continue
        task = derived.scenario["tasks"][i]
        R_min = task["min_reliability"]
        R_i = r["end_to_end_reliability"]
        if R_i < R_min - EPS_CMP:
            v_r += 1.0

    return {
        "task_results": task_results,
        "system_metrics": {
            "tssr": tssr,
            "mean_effective_reliability": rbar,
            "mean_effective_utility": ubar,
            "reliability_violation_rate": v_r / n,
        },
    }
